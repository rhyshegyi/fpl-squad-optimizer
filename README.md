# FPL Squad Optimizer

Recommends an optimal Fantasy Premier League squad using linear programming, with weekly auto-updates, transfer suggestions, and a scouting view backed by a LightGBM points predictor.

- **Squad view** — recommended 15-man squad on a pitch with formation, captain/vice markers, and a live-solving budget slider
- **Transfers** — paste 15 player IDs (or auto-load via an FPL entry ID) and get recommended in/out swaps under the free-transfer allowance and the -4 hit rule
- **Scouting** — sortable/filterable ranking of every player with form, minutes reliability, xG+xA, ownership, next-fixture FDR, and availability flags

## Pipeline

```
FPL API + vaastav historical CSVs
    → SQLite (raw + typed + historical_player_gw + season_teams)
    → feature engineering (rolling means, own/opp team strength, price)
    → LightGBM regressor (or naive form × FDR baseline)
    → PuLP LP: 15-man squad + starting XI + captain in one solve
    → versioned JSON artifacts in data/artifacts/
    → FastAPI serves the artifacts and hosts the React SPA
```

Model beats the naive baseline on 2024-25 hold-out (RMSE 2.069 vs 2.159, MAE 1.050 vs 1.084).

## Getting started

One-off: build the training set and fit the model.

```bash
uv sync
uv run fpl ingest-history       # pull 3 seasons of per-GW rows from vaastav
uv run fpl train                # fit LightGBM with time-based split
```

Weekly refresh (also runs automatically via GitHub Actions):

```bash
uv run fpl ingest               # bootstrap-static + fixtures
uv run fpl stage                # normalize into typed tables
uv run fpl ingest-live-history  # current-season per-player history
uv run fpl export --projector ml   # rewrite data/artifacts/*.json
```

Run the site locally (two terminals):

```bash
uv run fpl serve                # FastAPI on http://127.0.0.1:8000
```

```bash
cd frontend && npm install && npm run dev   # Vite dev server on 5173
```

Open http://localhost:5173.

Transfer recommendations from the CLI:

```bash
uv run fpl transfers --entry 12345 --free 1
uv run fpl transfers --players 86,88,... --bank-tenths 5 --free 2 --max-transfers 3
```

## Deploy

Single-container deploy to [Fly.io](https://fly.io). The multi-stage Dockerfile builds the React SPA, then serves it alongside the API from `python:3.13-slim` on port 8080. Runtime is slim — the deployed API only reads the cached JSON artifacts (no SQLite, no LightGBM inference).

```bash
flyctl auth login
flyctl launch --no-deploy       # accepts existing Dockerfile + fly.toml
flyctl deploy                   # ~2-3 min: builds + rolls out
```

Auto-deploy on push (optional): add a `FLY_API_TOKEN` GitHub secret (generate via `flyctl tokens create deploy`), then a `.github/workflows/deploy.yml` that runs `flyctl deploy --remote-only` on pushes to `main`. Every weekly artifact commit then rolls to prod automatically.

## Layout

```
src/fpl_optimizer/
├── cli.py            # fpl ingest | stage | train | optimize | transfers | export | serve | run
├── db.py             # SQLite schema + connect helper (training + local dev)
├── ingest.py         # bootstrap-static + fixtures → raw JSON tables
├── staging.py        # raw → typed players/teams/fixtures/gameweeks + season_teams
├── historical.py     # vaastav merged_gw.csv + teams.csv → historical_player_gw
├── live_history.py   # element-summary per player → historical_player_gw (current season)
├── features.py       # rolling 3/5 means, cumulatives, team strengths, price, position
├── model.py          # LightGBM training, time-based split, native-format persistence
├── projections.py    # naive form × FDR projector
├── projections_ml.py # ML projector: loads model, builds predict frame, availability multiplier
├── scouting.py       # enrich projections with season / recent / next-fixture stats
├── optimizer.py      # PuLP LP: 15-man squad + starting XI + captain (accepts budget)
├── entry.py          # fetch a manager's picks + bank from FPL entry endpoints
├── transfer.py       # transfer-mode LP: keep/buy/sell + configurable hits penalty
├── export.py         # write latest_squad.json + latest_projections.json (enriched)
└── api.py            # FastAPI routes + static SPA serving

frontend/             # Vite + React + TypeScript + Tailwind
└── src/
    ├── api.ts + types.ts + teamColors.ts
    ├── components/   # Pitch, PlayerCard, FdrChip, GameweekBadge, StatusBar
    └── pages/        # SquadPage, ProjectionsPage, TransfersPage

.github/workflows/
└── weekly.yml        # Tuesday 06:00 UTC cron: full pipeline → commit artifacts

Dockerfile            # multi-stage: node builds SPA, python:3.13-slim serves it
fly.toml              # Fly.io app config
```

## Configuration decisions

- **Data source** — public FPL API + `vaastav/Fantasy-Premier-League` for historical seasons
- **Update cadence** — scheduled (Tuesday 06:00 UTC), not live/on-demand
- **Scheduler** — GitHub Actions cron, artifacts committed back to the repo
- **Build order** — LP optimizer first (with naive projections), then swap in the ML predictor
- **Frontend** — Vite + React + Tailwind (not Streamlit) served by the same FastAPI process in prod
- **Transfer mode** — same LP as the from-scratch optimizer with keep/buy/sell variables + hits penalty
- **Deploy runtime** — only reads cached artifacts, so no SQLite or LightGBM in the image
