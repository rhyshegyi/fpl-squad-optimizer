"""Ingest current-season per-GW history for every active player via element-summary.

Writes to the same `historical_player_gw` table as `historical.py`, using the
detected current-season code (e.g. '2025-26'). This lets us build rolling
features at predict time the same way we build them at train time.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .db import connect
from .historical import COLUMNS, INSERT_SQL, POSITION_NORMALIZE

ELEMENT_SUMMARY_URL = "https://fantasy.premierleague.com/api/element-summary/{pid}/"
MAX_WORKERS = 8


def _current_season(conn) -> str:
    row = conn.execute(
        "SELECT MIN(deadline_time) AS d FROM gameweeks"
    ).fetchone()
    if row is None or row["d"] is None:
        raise RuntimeError("no gameweeks staged — run `fpl stage` first")
    year = int(row["d"][:4])
    return f"{year}-{str(year + 1)[2:]}"


def _players_and_positions(conn) -> list[tuple[int, str, str, str]]:
    """Returns (player_id, web_name, position, team_short) for every player."""
    rows = conn.execute(
        "SELECT p.id, p.web_name, p.position, t.short_name AS team_short "
        "FROM players p JOIN teams t ON t.id = p.team_id"
    ).fetchall()
    return [(r["id"], r["web_name"], r["position"], r["team_short"]) for r in rows]


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

        all_rows: list[tuple] = []
        failed: list[int] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_history, pid): (pid, name, pos, team)
                       for pid, name, pos, team in players}
            for fut in as_completed(futures):
                pid, name, pos, team = futures[fut]
                try:
                    history = fut.result()
                except Exception:
                    failed.append(pid)
                    continue
                for entry in history:
                    all_rows.append(
                        _coerce_history_row(season, pid, name, pos, team, entry)
                    )

        conn.execute("DELETE FROM historical_player_gw WHERE season = ?", (season,))
        conn.executemany(INSERT_SQL, all_rows)

        return {
            "season": season,
            "players": len(players),
            "failed": len(failed),
            "rows": len(all_rows),
        }
