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
VAASTAV_TEAMS_URL = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/"
    "data/{season}/teams.csv"
)

TEAM_COLUMNS = [
    ("id", int),
    ("name", str),
    ("short_name", str),
    ("strength", int),
    ("strength_overall_home", int),
    ("strength_overall_away", int),
    ("strength_attack_home", int),
    ("strength_attack_away", int),
    ("strength_defence_home", int),
    ("strength_defence_away", int),
]

TEAMS_INSERT_COLS = ["season"] + [c for c, _ in TEAM_COLUMNS]
TEAMS_INSERT_SQL = (
    f"INSERT OR REPLACE INTO season_teams ({', '.join(TEAMS_INSERT_COLS)}) "
    f"VALUES ({', '.join(['?'] * len(TEAMS_INSERT_COLS))})"
)

DEFAULT_SEASONS = ["2022-23", "2023-24", "2024-25"]

POSITION_NORMALIZE = {
    "GK": "GK", "GKP": "GK",
    "DEF": "DEF",
    "MID": "MID",
    "FWD": "FWD", "FW": "FWD",
}

# Every column we try to lift from the CSV. Missing ones become NULL.
# `team_id` isn't in vaastav's merged_gw.csv but is populated post-hoc via a
# name → id map from the same season's teams.csv; live_history sets it from
# the staged players table.
COLUMNS = [
    ("element", int),
    ("name", str),
    ("position", str),
    ("team", str),
    ("team_id", int),
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


def _row_values(
    season: str,
    row: dict[str, str],
    team_name_to_id: dict[str, int],
) -> tuple | None:
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

    # Fill in team_id from the team-name → id map (vaastav merged_gw stores full name).
    team_idx = INSERT_COLS.index("team")
    team_id_idx = INSERT_COLS.index("team_id")
    team_name = values[team_idx]
    if isinstance(team_name, str):
        values[team_id_idx] = team_name_to_id.get(team_name)

    return tuple(values)


def _fetch_teams(season: str) -> list[tuple]:
    url = VAASTAV_TEAMS_URL.format(season=season)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows: list[tuple] = []
    for raw in reader:
        values: list[object | None] = [season]
        for col, kind in TEAM_COLUMNS:
            values.append(_coerce(raw.get(col), kind))
        if values[TEAMS_INSERT_COLS.index("id")] is not None:
            rows.append(tuple(values))
    return rows


def _fetch_season(season: str, team_name_to_id: dict[str, int]) -> list[tuple]:
    url = VAASTAV_MERGED_URL.format(season=season)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows: list[tuple] = []
    for raw in reader:
        row = _row_values(season, raw, team_name_to_id)
        if row is not None:
            rows.append(row)
    return rows


def ingest_historical(seasons: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Pull merged_gw.csv + teams.csv for each season."""
    seasons = seasons or DEFAULT_SEASONS
    counts: dict[str, dict[str, int]] = {}
    with connect() as conn:
        for season in seasons:
            team_rows = _fetch_teams(season)
            conn.execute("DELETE FROM season_teams WHERE season = ?", (season,))
            conn.executemany(TEAMS_INSERT_SQL, team_rows)

            name_idx = TEAMS_INSERT_COLS.index("name")
            id_idx = TEAMS_INSERT_COLS.index("id")
            team_name_to_id = {r[name_idx]: r[id_idx] for r in team_rows}

            player_rows = _fetch_season(season, team_name_to_id)
            conn.execute("DELETE FROM historical_player_gw WHERE season = ?", (season,))
            conn.executemany(INSERT_SQL, player_rows)
            counts[season] = {"teams": len(team_rows), "player_gws": len(player_rows)}
    return counts
