"""Ingest per-GW player rows from vaastav/Fantasy-Premier-League into SQLite.

The upstream schema evolved over the years; earlier seasons don't have xG/xA
etc. We coerce every row into the wide `historical_player_gw` shape and leave
missing columns as NULL.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

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

# The first season FPL published expected goals / assists. The xG and xA
# rolling features are meaningless before it, so history starts here rather
# than at the oldest season vaastav has.
EARLIEST_SEASON = "2022-23"


def season_code(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[2:]}"


def detect_current_season() -> str:
    """The season being played, from staged gameweeks if there are any.

    Falls back to the calendar when the database is empty (a fresh CI runner
    before `fpl stage`): the FPL year turns over in July, when the new game is
    published.
    """
    try:
        with connect() as conn:
            row = conn.execute("SELECT MIN(deadline_time) AS d FROM gameweeks").fetchone()
        if row and row["d"]:
            return season_code(int(row["d"][:4]))
    except Exception:  # noqa: BLE001 - an unreadable DB is the fallback case
        pass
    today = datetime.now(timezone.utc)
    return season_code(today.year if today.month >= 7 else today.year - 1)


def historical_seasons(current: str | None = None) -> list[str]:
    """Every complete season from EARLIEST_SEASON up to, not including, the current one.

    Derived rather than hardcoded. The hardcoded list stopped at 2024-25 and
    quietly stayed there: by September 2026 the model was training on data
    two seasons old, missing 2025-26 entirely — the first season scored with
    defensive-contribution points, and so the only one scored under the rules
    being played now. It would also have dropped the current season out of
    training at rollover, because CI rebuilds its database every run and the
    live season is only ever ingested as live data.
    """
    current = current or detect_current_season()
    return [
        season_code(y)
        for y in range(int(EARLIEST_SEASON[:4]), int(current[:4]))
    ]


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


_PLAYER_TYPES = {"season": str, "gw": int, **dict(COLUMNS)}
_TEAM_TYPES = {"season": str, **dict(TEAM_COLUMNS)}


def _rows_from_archive(season: str) -> tuple[list[tuple], list[tuple]] | None:
    """Our own committed copy of a season, if we lived through it.

    Preferred over the network: these files were written from the FPL API at
    the time, so they do not depend on anyone else still publishing.
    """
    from .archive import load_archived_gameweeks, load_archived_teams

    players = load_archived_gameweeks(season)
    teams = load_archived_teams(season)
    if not players or not teams:
        return None

    team_rows = [
        tuple(_coerce(r.get(c), _TEAM_TYPES[c]) for c in TEAMS_INSERT_COLS)
        for r in teams
    ]
    player_rows = [
        tuple(_coerce(r.get(c), _PLAYER_TYPES[c]) for c in INSERT_COLS)
        for r in players
    ]
    return team_rows, player_rows


def ingest_historical(seasons: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Pull merged_gw.csv + teams.csv for each season.

    A season vaastav has not published is skipped with a note rather than
    failing the pipeline — but the count of seasons actually loaded is in the
    result, and training refuses to run on fewer than two.
    """
    seasons = seasons or historical_seasons()
    counts: dict[str, dict[str, int]] = {}
    with connect() as conn:
        for season in seasons:
            local = _rows_from_archive(season)
            if local is not None:
                team_rows, player_rows = local
                conn.execute("DELETE FROM season_teams WHERE season = ?", (season,))
                conn.executemany(TEAMS_INSERT_SQL, team_rows)
                conn.execute(
                    "DELETE FROM historical_player_gw WHERE season = ?", (season,))
                conn.executemany(INSERT_SQL, player_rows)
                counts[season] = {"teams": len(team_rows),
                                  "player_gws": len(player_rows), "source": "archive"}
                continue

            try:
                team_rows = _fetch_teams(season)
            except requests.HTTPError as e:
                print(f"  skipping {season}: not available upstream ({e})")
                counts[season] = {"teams": 0, "player_gws": 0, "missing": 1}
                continue
            conn.execute("DELETE FROM season_teams WHERE season = ?", (season,))
            conn.executemany(TEAMS_INSERT_SQL, team_rows)

            name_idx = TEAMS_INSERT_COLS.index("name")
            id_idx = TEAMS_INSERT_COLS.index("id")
            team_name_to_id = {r[name_idx]: r[id_idx] for r in team_rows}

            player_rows = _fetch_season(season, team_name_to_id)
            conn.execute("DELETE FROM historical_player_gw WHERE season = ?", (season,))
            conn.executemany(INSERT_SQL, player_rows)
            counts[season] = {"teams": len(team_rows),
                              "player_gws": len(player_rows), "source": "vaastav"}
    return counts
