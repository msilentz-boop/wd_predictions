import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import requests

CSV_URL = os.environ.get(
    "CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vQtsVsHJG4CKahR4G-Atj6wgI7LpjcjeP899NjMj8RrdSKRVjgrkY5Qt561ax-PJhagyra_69r_aydh/pub?output=csv",
)
KNOCKOUT_CSV_URL = os.environ.get(
    "KNOCKOUT_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vQGds2d4oRC1LtJo8CcBfZwjpywjt-G5gB1TdwRuAZlkBycPMKl-nLe80Q86ZSAKQ/pub?output=csv",
)
API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
API_URL = "https://api.football-data.org/v4/competitions/WC/matches"
LIVE_API_URL = "https://worldcup26.ir/get/games"

# Sheet team names that differ from the football-data.org API names
SHEET_TO_API = {
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde Islands",
    "DR Congo": "Congo DR",
    "Curacao": "Curaçao",
    "Czech Republic": "Czechia",
    "USA": "United States",
}

# Sheet team names that differ from worldcup26.ir names
LIVE_TO_SHEET = {
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "United States": "USA",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Curaçao": "Curacao",
    "Czechia": "Czech Republic",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo",
}


def normalize(name):
    return SHEET_TO_API.get(name, name)


def _parse_scorers(raw):
    if not raw or raw == "null":
        return []
    # Format from API: `{"J. Quiñones 9'"}` or `{"Goal 1'","Goal 2'"}`
    inner = raw.strip().lstrip("{").rstrip("}")
    return [s.strip().strip('"') for s in inner.split('","') if s.strip().strip('"')]


def fetch_live_scores():
    """Return dict of (home_sheet, away_sheet) -> live game data from worldcup26.ir."""
    try:
        resp = requests.get(LIVE_API_URL, timeout=15)
        resp.raise_for_status()
        games = resp.json().get("games", [])
    except Exception as e:
        print(f"WARNING: Could not fetch live scores: {e}")
        return {}

    by_pair = {}
    for g in games:
        home = LIVE_TO_SHEET.get(g.get("home_team_name_en", ""), g.get("home_team_name_en", ""))
        away = LIVE_TO_SHEET.get(g.get("away_team_name_en", ""), g.get("away_team_name_en", ""))
        by_pair[(home, away)] = g
    return by_pair


def fetch_api_matches():
    resp = requests.get(API_URL, headers={"X-Auth-Token": API_KEY}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    last_updated = data.get("resultSet", {}).get("lastUpdated") or datetime.now(timezone.utc).isoformat()
    by_pair = {}
    for m in data["matches"]:
        home = m["homeTeam"].get("name")
        away = m["awayTeam"].get("name")
        if not home or not away:
            continue
        by_pair[(home, away)] = m
    return by_pair, last_updated


NON_PLAYER_COLS = {"Date", "Group", "Match", "Home Team", "Away Team", "Result"}


def fetch_sheet_rows(url):
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    players = [f for f in reader.fieldnames if f not in NON_PLAYER_COLS]
    return rows, players


def derive_result_label(match, home_sheet, away_sheet):
    """Return the sheet-style result label for a finished match."""
    winner = match["score"]["winner"]
    if winner == "HOME_TEAM":
        return home_sheet
    if winner == "AWAY_TEAM":
        return away_sheet
    if winner == "DRAW":
        return "Draw"
    return None


def main():
    print("Fetching API match data…")
    api_by_pair, last_updated = fetch_api_matches()

    print("Fetching live scores from worldcup26.ir…")
    live_by_pair = fetch_live_scores()
    print(f"  Live games found: {len([g for g in live_by_pair.values() if g.get('time_elapsed') == 'live'])}")

    print("Fetching group stage predictions…")
    rows_group, players_group = fetch_sheet_rows(CSV_URL)
    print(f"  Players: {players_group}, Rows: {len(rows_group)}")

    print("Fetching knockout stage predictions…")
    rows_knockout, players_knockout = fetch_sheet_rows(KNOCKOUT_CSV_URL)
    print(f"  Players: {players_knockout}, Rows: {len(rows_knockout)}")

    players = list(dict.fromkeys(players_group + players_knockout))
    rows = rows_group + rows_knockout
    print(f"  Combined: {len(players)} players, {len(rows)} rows")

    leaderboard = {p: {"name": p, "points": 0, "correct": 0, "played": 0} for p in players}
    finished_matches = []
    upcoming_matches = []
    unmatched = []

    for row in rows:
        home_sheet = row["Home Team"].strip()
        away_sheet = row["Away Team"].strip()
        if not home_sheet or not away_sheet:
            continue
        home_api = normalize(home_sheet)
        away_api = normalize(away_sheet)

        m = api_by_pair.get((home_api, away_api))
        if m is None:
            # Football-data.org doesn't have this fixture yet (common for early knockout rounds).
            # If the sheet has no result, synthesize a TIMED upcoming entry so it appears on the dashboard.
            sheet_result = row.get("Result", "").strip()
            if sheet_result:
                unmatched.append(f"{home_sheet} vs {away_sheet}")
                continue
            raw_date = row.get("Date", "").strip()
            try:
                iso_date = datetime.strptime(raw_date, "%d-%b-%Y").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                iso_date = ""
            picks = {p: row.get(p, "").strip() for p in players if row.get(p, "").strip()}
            upcoming_matches.append({
                "id": hash(f"{home_sheet}|{away_sheet}") & 0x7FFFFFFF,
                "date": iso_date,
                "group": row.get("Group") or row.get("Match", ""),
                "stage": "ROUND_OF_32",
                "pointsAvailable": 8,
                "homeTeam": home_sheet,
                "awayTeam": away_sheet,
                "homeScore": None,
                "awayScore": None,
                "status": "TIMED",
                "timeElapsed": None,
                "homeScorers": [],
                "awayScorers": [],
                "result": None,
                "picks": picks,
                "correct": {p: None for p in picks},
            })
            continue

        status = m["status"]
        ft = m["score"]["fullTime"]
        home_score = ft.get("home")
        away_score = ft.get("away")
        result_label = None
        time_elapsed = None

        # Override with live data from worldcup26.ir if available
        live = live_by_pair.get((home_sheet, away_sheet))
        if live:
            te = live.get("time_elapsed", "")
            if te == "live":
                status = "IN_PLAY"
                time_elapsed = "live"
            elif te in ("halftime", "half"):
                status = "PAUSED"
                time_elapsed = "halftime"
            elif live.get("finished") == "TRUE":
                status = "FINISHED"
            try:
                home_score = int(live["home_score"])
                away_score = int(live["away_score"])
            except (KeyError, TypeError, ValueError):
                pass

        if status == "FINISHED":
            result_label = derive_result_label(m, home_sheet, away_sheet)

        picks = {}
        correct_map = {}
        for p in players:
            pick = row.get(p, "").strip()
            if not pick:
                continue
            picks[p] = pick
            if result_label is not None:
                correct_map[p] = pick == result_label
            else:
                correct_map[p] = None

        is_knockout = m["stage"] != "GROUP_STAGE"
        knockout_pool = 8

        if result_label is not None:
            correct_count = sum(1 for v in correct_map.values() if v)
            points_each = (knockout_pool / correct_count) if (is_knockout and correct_count > 0) else (0 if is_knockout else 1)
            for p, is_correct in correct_map.items():
                leaderboard[p]["played"] += 1
                if is_correct:
                    leaderboard[p]["points"] += points_each
                    leaderboard[p]["correct"] += 1

        points_available = knockout_pool if is_knockout else 1

        match_payload = {
            "id": m["id"],
            "date": m["utcDate"],
            "group": row.get("Group") or row.get("Match", ""),
            "stage": m["stage"],
            "pointsAvailable": points_available,
            "homeTeam": home_sheet,
            "awayTeam": away_sheet,
            "homeScore": home_score,
            "awayScore": away_score,
            "status": status,
            "timeElapsed": time_elapsed,
            "homeScorers": _parse_scorers(live.get("home_scorers")) if live else [],
            "awayScorers": _parse_scorers(live.get("away_scorers")) if live else [],
            "result": result_label,
            "picks": picks,
            "correct": correct_map,
        }

        if status == "FINISHED":
            finished_matches.append(match_payload)
        else:
            upcoming_matches.append(match_payload)

    if unmatched:
        print(f"WARNING: {len(unmatched)} sheet rows had no API match: {unmatched}")

    sorted_lb = sorted(
        leaderboard.values(),
        key=lambda x: (-x["points"], -x["correct"], x["name"]),
    )
    for entry in sorted_lb:
        played = entry["played"]
        entry["accuracy"] = round(entry["correct"] / played, 3) if played else 0.0
        entry["points"] = round(entry["points"], 2)

    output = {
        "lastUpdated": last_updated,
        "players": players,
        "leaderboard": sorted_lb,
        "finished": finished_matches,
        "upcoming": upcoming_matches,
    }

    os.makedirs("docs", exist_ok=True)
    out_path = "docs/data.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Written {out_path}: {len(finished_matches)} finished, {len(upcoming_matches)} upcoming, {len(unmatched)} unmatched")
    for entry in sorted_lb:
        print(f"  {entry['name']}: {entry['points']}pts ({entry['correct']}/{entry['played']})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        raise
