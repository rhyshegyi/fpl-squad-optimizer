# FPL Squad Optimizer

Recommends an optimal Fantasy Premier League squad using linear programming, with weekly auto-updates and transfer suggestions.

## Pipeline

FPL API → raw SQLite → staging tables → naive projections → PuLP LP optimizer

## Getting started

```bash
uv sync
uv run fpl ingest      # pull latest FPL data into data/fpl.db
uv run fpl stage       # normalize raw payloads into typed tables
uv run fpl optimize    # print the optimal 15-man squad
```

Or run the whole thing:

```bash
uv run fpl run
```

## Layout

- `src/fpl_optimizer/ingest.py` — fetch bootstrap-static + fixtures
- `src/fpl_optimizer/db.py` — SQLite schema + connection helper
- `src/fpl_optimizer/staging.py` — raw JSON → typed rows
- `src/fpl_optimizer/projections.py` — naive form × fixture difficulty
- `src/fpl_optimizer/optimizer.py` — PuLP LP model
- `src/fpl_optimizer/cli.py` — command entry points
