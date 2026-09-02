"""FastAPI backend serving the latest artifacts + a live transfer endpoint.

Read-only endpoints (status, squad, projections) return the versioned JSON
files under `data/artifacts/` — those are refreshed by the weekly GH Actions
run, so serving is O(read a small JSON file).

The transfers endpoint is live-computed: it reprojects players (naive or ML)
and solves the transfer LP for the caller's existing 15 IDs + bank/free.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .export import ARTIFACTS_DIR
from .projections import project
from .projections_ml import project_ml
from .transfer import optimize_transfers

SQUAD_JSON = ARTIFACTS_DIR / "latest_squad.json"
PROJECTIONS_JSON = ARTIFACTS_DIR / "latest_projections.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"artifact not found: {path.name} — run `fpl export` "
                   f"(or wait for the weekly workflow)",
        )
    return json.loads(path.read_text())


app = FastAPI(
    title="FPL Squad Optimizer API",
    description="Serves the latest optimized squad, projections, and live "
                "transfer recommendations.",
    version="0.1.0",
)

# Wide-open CORS is fine here — this backend has no auth or mutating side
# effects that touch shared state, and the frontend runs on a different port
# in local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/status")
def get_status() -> dict:
    """Report artifact freshness + which gameweeks the data covers."""
    squad = _load_json(SQUAD_JSON)
    return {
        "generated_at": squad["generated_at"],
        "projector": squad["projector"],
        "pipeline_state": squad["pipeline_state"],
    }


@app.get("/api/squad/latest")
def get_squad() -> dict:
    return _load_json(SQUAD_JSON)


@app.get("/api/projections/latest")
def get_projections(
    position: Literal["GK", "DEF", "MID", "FWD"] | None = None,
    max_cost_tenths: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    sort: Literal["projected_points", "now_cost", "web_name"] = "projected_points",
) -> dict:
    data = _load_json(PROJECTIONS_JSON)
    rows = data["projections"]
    if position:
        rows = [r for r in rows if r["position"] == position]
    if max_cost_tenths is not None:
        rows = [r for r in rows if r["now_cost"] <= max_cost_tenths]
    reverse = sort != "web_name"
    rows = sorted(rows, key=lambda r: r[sort], reverse=reverse)[:limit]
    return {
        "generated_at": data["generated_at"],
        "projector": data["projector"],
        "count": len(rows),
        "projections": rows,
    }


class TransferRequest(BaseModel):
    existing_ids: list[int] = Field(..., min_length=15, max_length=15,
                                    description="The manager's 15 current player ids")
    bank_tenths: int = Field(..., ge=0, description="Money in bank, tenths of £m")
    free_transfers: int = Field(1, ge=0, le=5)
    max_transfers: int | None = Field(None, ge=0, le=15)
    projector: Literal["naive", "ml"] = "ml"


@app.post("/api/transfers")
def post_transfers(req: TransferRequest) -> dict:
    projections = project_ml() if req.projector == "ml" else project()
    try:
        plan = optimize_transfers(
            projections=projections,
            existing_ids=req.existing_ids,
            bank=req.bank_tenths,
            free_transfers=req.free_transfers,
            max_transfers=req.max_transfers,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "old_squad_ids": plan.old_squad_ids,
        "transfers_made": plan.transfers_made,
        "free_transfers": plan.free_transfers,
        "paid_hits": plan.paid_hits,
        "hit_cost": plan.hit_cost,
        "projected_points": plan.projected_points,
        "bank_before": plan.bank_before,
        "bank_after": plan.bank_after,
        "transfers_in": [asdict(p) for p in plan.transfers_in],
        "transfers_out": [asdict(p) for p in plan.transfers_out],
        "new_squad": {
            "total_cost": plan.new_squad.total_cost,
            "projected_points": plan.new_squad.projected_points,
            "formation": plan.new_squad.formation(),
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
                for pick in plan.new_squad.picks
            ],
        },
    }
