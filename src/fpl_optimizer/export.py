"""Serialize the latest optimizer output + player projections to versioned
JSON artifacts under data/artifacts/.

These files are the persistence layer that a future backend (Phase 5) reads
from. They're also small enough to check into git after each weekly run so
history is browsable in the repo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .db import connect
from .optimizer import Squad
from .projections import PlayerProjection
from .scouting import enrich_projections

ARTIFACTS_DIR = Path("data") / "artifacts"


def _squad_to_dict(squad: Squad) -> dict:
    return {
        "total_cost": squad.total_cost,
        "projected_points": squad.projected_points,
        "formation": squad.formation(),
        "picks": [
            {
                "player_id": pick.player.player_id,
                "web_name": pick.player.web_name,
                "team_id": pick.player.team_id,
                "team_short": pick.player.team_short,
                "position": pick.player.position,
                "now_cost": pick.player.now_cost,
                "projected_points": pick.player.projected_points,
                "is_starter": pick.is_starter,
                "is_captain": pick.is_captain,
                "is_vice": pick.is_vice,
            }
            for pick in squad.picks
        ],
    }


def _projections_to_list(projections: list[PlayerProjection]) -> list[dict]:
    return enrich_projections(projections)


def _pipeline_state() -> dict:
    """Snapshot of what the run saw: last data fetch, current + next GW."""
    with connect() as conn:
        last_fetch = conn.execute(
            "SELECT MAX(fetched_at) AS ts FROM raw_bootstrap"
        ).fetchone()
        current = conn.execute(
            "SELECT id, name FROM gameweeks WHERE is_current = 1"
        ).fetchone()
        nxt = conn.execute(
            "SELECT id, name, deadline_time FROM gameweeks WHERE is_next = 1"
        ).fetchone()
    return {
        "last_fetch": last_fetch["ts"] if last_fetch else None,
        "current_gw": {"id": current["id"], "name": current["name"]} if current else None,
        "next_gw": {
            "id": nxt["id"], "name": nxt["name"], "deadline_time": nxt["deadline_time"],
        } if nxt else None,
    }


def export_artifacts(
    squad: Squad,
    projections: list[PlayerProjection],
    projector: str,
) -> dict[str, Path]:
    """Write latest_squad.json + latest_projections.json. Returns file paths."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    state = _pipeline_state()

    squad_data = {
        "generated_at": generated_at,
        "projector": projector,
        "pipeline_state": state,
        "squad": _squad_to_dict(squad),
    }
    proj_data = {
        "generated_at": generated_at,
        "projector": projector,
        "pipeline_state": state,
        "projections": _projections_to_list(projections),
    }

    squad_path = ARTIFACTS_DIR / "latest_squad.json"
    proj_path = ARTIFACTS_DIR / "latest_projections.json"
    squad_path.write_text(json.dumps(squad_data, indent=2))
    proj_path.write_text(json.dumps(proj_data, indent=2))

    return {"squad": squad_path, "projections": proj_path}
