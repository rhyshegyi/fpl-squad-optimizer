"""Ingest current-season per-GW history for every active player via element-summary.

Writes to the same `historical_player_gw` table as `historical.py`, using the
detected current-season code (e.g. '2025-26'). This lets us build rolling
features at predict time the same way we build them at train time.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

from .db import connect
from .historical import COLUMNS, INSERT_SQL, POSITION_NORMALIZE

ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{pid}/"
MAX_WORKERS = 8

# A match plus stoppage, used only when a history row carries no fixture id.
MATCH_DURATION = timedelta(hours=2, minutes=30)


def _current_season(conn) -> str:
    row = conn.execute(
        "SELECT MIN(deadline_time) AS d FROM gameweeks"
    ).fetchone()
    if row is None or row["d"] is None:
        raise RuntimeError("no gameweeks staged — run `fpl stage` first")
    year = int(row["d"][:4])
    return f"{year}-{str(year + 1)[2:]}"


def _players_and_positions(conn) -> list[tuple[int, str, str, str, int]]:
    """Returns (player_id, web_name, position, team_short, team_id) for every player."""
    rows = conn.execute(
        "SELECT p.id, p.web_name, p.position, t.short_name AS team_short, p.team_id "
        "FROM players p JOIN teams t ON t.id = p.team_id"
    ).fetchall()
    return [(r["id"], r["web_name"], r["position"], r["team_short"], r["team_id"])
            for r in rows]


def _played_fixtures(conn) -> set[int]:
    """Fixture ids for matches that have actually been played.

    FPL flips three flags in sequence: `started` at kickoff,
    `finished_provisional` at the final whistle, and `finished` only once
    bonus points are confirmed — often hours later, sometimes not until the
    round ends. `finished` is therefore useless for this: mid-round it is
    False for matches that finished two hours ago.
    """
    return {
        r["id"] for r in conn.execute(
            "SELECT id FROM fixtures WHERE finished = 1 OR finished_provisional = 1"
        )
    }


def _is_played(entry: dict, played: set[int]) -> bool:
    """Has this history row's match actually been played?

    `element-summary` returns a row for a player's *upcoming* fixture, with
    minutes 0 and points 0, indistinguishable in shape from a real row where
    he was an unused substitute. Writing those made every player look like
    they had played a gameweek they had not: during GW3, 610 of 652 players
    showed three games on file when one match of ten had kicked off. That
    fed a zero into `minutes_r3` — the model's single largest feature — for
    everyone at once, and divided `form` by a gameweek that had not happened.

    A 0-minute row for a match that *has* been played is real information
    (available, not picked) and is kept.
    """
    fixture = entry.get("fixture")
    if fixture is not None:
        return int(fixture) in played
    # No fixture id to match on: fall back to the clock, allowing for a match
    # plus stoppage before calling it played.
    kickoff = entry.get("kickoff_time")
    if not kickoff:
        return False
    try:
        started = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - started > MATCH_DURATION


def _fetch_history(pid: int) -> list[dict]:
    r = requests.get(ELEMENT_SUMMARY_URL.format(pid=pid), timeout=30)
    r.raise_for_status()
    return r.json().get("history", [])


def _coerce_history_row(
    season: str,
    pid: int,
    web_name: str,
    position: str,
    team_short: str,
    team_id: int,
    entry: dict,
) -> tuple:
    gw = entry.get("round")
    values: list[object | None] = [season, gw]
    for col, kind in COLUMNS:
        if col == "element":
            values.append(pid)
        elif col == "name":
            values.append(web_name)
        elif col == "position":
            values.append(POSITION_NORMALIZE.get(position, position))
        elif col == "team":
            values.append(team_short)
        elif col == "team_id":
            values.append(team_id)
        else:
            raw = entry.get(col)
            if raw is None or raw == "":
                values.append(None)
            elif kind is int:
                values.append(int(raw) if not isinstance(raw, bool) else int(raw))
            elif kind is float:
                values.append(float(raw))
            else:
                values.append(str(raw))
    return tuple(values)


def ingest_live_history() -> dict[str, object]:
    """Pull current-season history for every player into historical_player_gw."""
    with connect() as conn:
        season = _current_season(conn)
        players = _players_and_positions(conn)
        played = _played_fixtures(conn)

        all_rows: list[tuple] = []
        failed: list[int] = []
        skipped = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_history, pid): (pid, name, pos, team, team_id)
                       for pid, name, pos, team, team_id in players}
            for fut in as_completed(futures):
                pid, name, pos, team, team_id = futures[fut]
                try:
                    history = fut.result()
                except Exception:
                    failed.append(pid)
                    continue
                for entry in history:
                    if not _is_played(entry, played):
                        skipped += 1
                        continue
                    all_rows.append(
                        _coerce_history_row(season, pid, name, pos, team, team_id, entry)
                    )

        conn.execute("DELETE FROM historical_player_gw WHERE season = ?", (season,))
        conn.executemany(INSERT_SQL, all_rows)

        return {
            "season": season,
            "players": len(players),
            "failed": len(failed),
            "rows": len(all_rows),
            "skipped_unplayed": skipped,
        }
