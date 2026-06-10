# WC 2026 Prediction Pool Dashboard

Static leaderboard dashboard for a World Cup 2026 outcome-prediction pool.
Auto-updates every 2 hours via GitHub Actions → served on GitHub Pages.

## How it works

1. GitHub Actions fetches live match results from [football-data.org](https://football-data.org)
2. Reads everyone's picks from the Google Sheet (published as public CSV)
3. Calculates standings: **+1 point per correct outcome** (home win / away win / draw)
4. Writes `docs/data.json` back to this repo
5. GitHub Pages serves `docs/index.html` which reads `data.json`

## Setup

### 1. GitHub Secret

Add one secret in **Settings → Secrets → Actions**:

| Secret | Value |
|--------|-------|
| `FOOTBALL_DATA_API_KEY` | your football-data.org free tier key |

### 2. GitHub Pages

Settings → Pages → **Source: Deploy from branch** → branch: `main`, folder: `/docs`

### 3. Manual trigger

Actions → "Update WC Leaderboard" → **Run workflow** — runs immediately and commits updated data.

## Google Sheet requirements

The published CSV must match this column layout:

```
Date | Group | Home Team | Away Team | <player names…> | Result
```

Keep the sheet published (File → Share → Publish to web → CSV) and the
`CSV_URL` env var or the hardcoded URL in `src/update_dashboard.py` updated if the
publish link changes.

## Scoring

- **+1 point** for picking the correct match outcome (home win, away win, or draw)
- Knockout rounds score the same way — the API reports the final outcome including
  extra time / penalties
- No predictions for knockout rounds are expected until teams are confirmed
