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
API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
API_URL = "https://api.football-data.org/v4/competitions/WC/matches"

# Sheet team names that differ from the API's names
SHEET_TO_API = {
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde Islands",
    "DR Congo": "Congo DR",
    "Curacao": "Curaçao",
    "Czech Republic": "Czechia",
    "USA": "United States",
}


def normalize(name):
    return SHEET_TO_API.get(name, name)


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


def fetch_sheet_rows():
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    players = [f for f in reader.fieldnames if f not in ("Date", "Group", "Home Team", "Away Team", "Result")]
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

    print("Fetching sheet predictions from public CSV…")
    rows, players = fetch_sheet_rows()
    print(f"  Players: {players}")
    print(f"  Rows: {len(rows)}")

    leaderboard = {p: {"name": p, "points": 0, "correct": 0, "played": 0} for p in players}
    finished_matches = []
    upcoming_matches = []
    unmatched = []

    for row in rows:
        home_sheet = row["Home Team"].strip()
        away_sheet = row["Away Team"].strip()
        home_api = normalize(home_sheet)
        away_api = normalize(away_sheet)

        m = api_by_pair.get((home_api, away_api))
        if m is None:
            unmatched.append(f"{home_sheet} vs {away_sheet}")
            continue

        status = m["status"]
        ft = m["score"]["fullTime"]
        home_score = ft.get("home")
        away_score = ft.get("away")
        result_label = None

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
                is_correct = pick == result_label
                correct_map[p] = is_correct
                leaderboard[p]["played"] += 1
                if is_correct:
                    leaderboard[p]["points"] += 1
                    leaderboard[p]["correct"] += 1
            else:
                correct_map[p] = None

        match_payload = {
            "id": m["id"],
            "date": m["utcDate"],
            "group": row.get("Group", ""),
            "stage": m["stage"],
            "homeTeam": home_sheet,
            "awayTeam": away_sheet,
            "homeScore": home_score,
            "awayScore": away_score,
            "status": status,
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
