"""Fetch a manager's current squad + bank from the public FPL API.

We use the picks from the last completed gameweek. This will miss any
transfers the manager made after that deadline (the picks endpoint for
the upcoming GW is private until it locks). Good enough for a first pass;
if the manager needs pixel-perfect current state they should supply the
15 player IDs directly.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

ENTRY_URL = "https://fantasy.premierleague.com/api/entry/{eid}/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{eid}/event/{gw}/picks/"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


@dataclass
class ManagerSquad:
    entry_id: int
    manager_name: str
    team_name: str
    source_gw: int          # gameweek the picks came from
    bank: int               # tenths of a million
    squad_value: int        # tenths, includes bank
    player_ids: list[int]   # 15 element ids
    captain_id: int | None
    vice_id: int | None


def _fetch_json(url: str) -> dict:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _latest_finished_gw_live() -> int | None:
    """Ask FPL bootstrap-static for the latest finished GW. Avoids a DB read
    so the API server can run without a local SQLite copy."""
    events = _fetch_json(BOOTSTRAP_URL).get("events") or []
    finished = [e["id"] for e in events if e.get("finished")]
    return max(finished) if finished else None


def fetch_manager_squad(entry_id: int, gw: int | None = None) -> ManagerSquad:
    entry = _fetch_json(ENTRY_URL.format(eid=entry_id))

    source_gw = gw or _latest_finished_gw_live()
    if source_gw is None:
        raise RuntimeError(
            "no finished gameweek available yet — pass --gw explicitly "
            "or wait until GW1 finishes"
        )

    picks = _fetch_json(PICKS_URL.format(eid=entry_id, gw=source_gw))

    entry_history = picks.get("entry_history") or {}
    manager_name = f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip()
    team_name = entry.get("name") or ""

    player_ids = [p["element"] for p in picks["picks"]]
    captain_id = next((p["element"] for p in picks["picks"] if p.get("is_captain")), None)
    vice_id = next((p["element"] for p in picks["picks"] if p.get("is_vice_captain")), None)

    return ManagerSquad(
        entry_id=entry_id,
        manager_name=manager_name,
        team_name=team_name,
        source_gw=source_gw,
        bank=int(entry_history.get("bank", entry.get("last_deadline_bank") or 0)),
        squad_value=int(entry_history.get("value", entry.get("last_deadline_value") or 0)),
        player_ids=player_ids,
        captain_id=captain_id,
        vice_id=vice_id,
    )
