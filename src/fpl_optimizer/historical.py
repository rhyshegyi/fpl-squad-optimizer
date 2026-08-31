"""Ingest per-GW player rows from vaastav/Fantasy-Premier-League into SQLite.

The upstream schema evolved over the years; earlier seasons don't have xG/xA
etc. We coerce every row into the wide `historical_player_gw` shape and leave
missing columns as NULL.
"""
from __future__ import annotations

import csv
import io

import requests

from .db import connect

VAASTAV_MERGED_URL = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/"
    "data/{season}/gws/merged_gw.csv"
)

DEFAULT_SEASONS = ["2022-23", "2023-24", "2024-25"]

POSITION_NORMALIZE = {
    "GK": "GK", "GKP": "GK",
    "DEF": "DEF",
    "MID": "MID",
    "FWD": "FWD", "FW": "FWD",
}

# Every column we try to lift from the CSV. Missing ones become NULL.
COLUMNS = [
    ("element", int),
    ("name", str),
    ("position", str),
    ("team", str),
    ("opponent_team", int),
    ("was_home", int),  # bool → 0/1
    ("kickoff_time", str),
    ("minutes", int),
    ("total_points", int),
    ("goals_scored", int),
    ("assists", int),
    ("clean_sheets", int),
    ("goals_conceded", int),
    ("bonus", int),
    ("bps", int),
    ("influence", float),
    ("creativity", float),
    ("threat", float),
    ("ict_index", float),
    ("expected_goals", float),
    ("expected_assists", float),
    ("expected_goal_involvements", float),
    ("expected_goals_conceded", float),
    ("starts", int),
    ("value", int),
]

INSERT_COLS = ["season", "gw"] + [c for c, _ in COLUMNS]
INSERT_SQL = (
    f"INSERT OR REPLACE INTO historical_player_gw ({', '.join(INSERT_COLS)}) "
    f"VALUES ({', '.join(['?'] * len(INSERT_COLS))})"
)


def _coerce(raw: str | None, kind: type) -> object | None:
    if raw is None or raw == "" or raw == "NA":
        return None
    try:
        if kind is int:
            if raw in ("True", "true"):
                return 1
            if raw in ("False", "false"):
                return 0
            return int(float(raw))
        if kind is float:
            return float(raw)
        return raw
    except (TypeError, ValueError):
        return None


def _row_values(season: str, row: dict[str, str]) -> tuple | None:
    gw = _coerce(row.get("GW") or row.get("round"), int)
    if gw is None:
        return None

    values: list[object | None] = [season, gw]
    for col, kind in COLUMNS:
        values.append(_coerce(row.get(col), kind))

    # Normalize position spellings (GKP → GK, FW → FWD, etc.)
    position_idx = INSERT_COLS.index("position")
    pos = values[position_idx]
    if isinstance(pos, str):
        values[position_idx] = POSITION_NORMALIZE.get(pos.upper(), pos.upper())

    return tuple(values)


def _fetch_season(season: str) -> list[tuple]:
    url = VAASTAV_MERGED_URL.format(season=season)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows: list[tuple] = []
    for raw in reader:
        row = _row_values(season, raw)
        if row is not None:
            rows.append(row)
    return rows


def ingest_historical(seasons: list[str] | None = None) -> dict[str, int]:
    """Pull merged_gw.csv for each season into historical_player_gw. Returns row counts."""
    seasons = seasons or DEFAULT_SEASONS
    counts: dict[str, int] = {}
    with connect() as conn:
        for season in seasons:
            rows = _fetch_season(season)
            conn.execute("DELETE FROM historical_player_gw WHERE season = ?", (season,))
            conn.executemany(INSERT_SQL, rows)
            counts[season] = len(rows)
    return counts
