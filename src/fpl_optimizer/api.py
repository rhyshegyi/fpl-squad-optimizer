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

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .chips import chip_advice
from .entry import fetch_manager_squad
from .export import ARTIFACTS_DIR
from .optimizer import optimize
from .projections import PlayerProjection
from .transfer import HIT_COST, optimize_transfers

SQUAD_JSON = ARTIFACTS_DIR / "latest_squad.json"
PROJECTIONS_JSON = ARTIFACTS_DIR / "latest_projections.json"
TARGET_JSON = ARTIFACTS_DIR / "latest_target.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"artifact not found: {path.name} — run `fpl export` "
                   f"(or wait for the weekly workflow)",
        )
    return json.loads(path.read_text())


def _players_without_fixture() -> set[int]:
    """Ids with no fixture in the upcoming gameweek.

    The enriched projections carry the next opponent, so a null there means a
    blank — which matters for Bench Boost, where a single blank wastes part of
    the chip regardless of how good the rest of the bench looks.
    """
    data = _load_json(PROJECTIONS_JSON)
    return {
        r["player_id"] for r in data["projections"]
        if not r.get("opp_short")
    }


def _projections_from_artifact() -> list[PlayerProjection]:
    """Rebuild PlayerProjection list from the cached JSON — the deployed
    API never touches SQLite or LightGBM at runtime; the LP just runs off
    what the weekly export produced."""
    data = _load_json(PROJECTIONS_JSON)
    return [
        PlayerProjection(
            player_id=r["player_id"],
            web_name=r["web_name"],
            team_id=r["team_id"],
            team_short=r["team_short"],
            position=r["position"],
            now_cost=r["now_cost"],
            projected_points=r["projected_points"],
        )
        for r in data["projections"]
    ]


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


@app.get("/api/squad/optimize")
def get_squad_optimize(
    budget_tenths: int = Query(default=1000, ge=400, le=1500),
) -> dict:
    """Live LP solve for an arbitrary budget. Player values shift over the
    season (rising to £15.5m stars, falling on out-of-form assets), so this
    lets the UI ask 'given £X available, what should I pick?'. Uses the
    cached projections — the numbers match the weekly artifact, but the
    squad shape adapts to the new budget."""
    projections = _projections_from_artifact()
    squad = optimize(projections, budget=budget_tenths)
    return {
        "projector": "ml",
        "budget_tenths": budget_tenths,
        "squad": {
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
        },
    }


def _projections_from(payload: dict) -> list[PlayerProjection]:
    return [
        PlayerProjection(
            player_id=r["player_id"], web_name=r["web_name"], team_id=r["team_id"],
            team_short=r["team_short"], position=r["position"],
            now_cost=r["now_cost"], projected_points=r["projected_points"],
        )
        for r in payload["projections"]
    ]


@app.get("/api/squad/target")
def get_target_squad(
    budget_tenths: int | None = Query(default=None, ge=400, le=1500),
) -> dict:
    """The squad worth aiming at over the next several gameweeks.

    Distinct from /api/squad/latest, which optimises purely for the next
    fixture — a squad you cannot reach on one free transfer and which is
    stale a week later. This one blends season-to-date quality with a
    multi-fixture horizon so it stays stable enough to actually aim at.

    Passing `budget_tenths` re-solves the LP; omitting it returns the
    precomputed £100m squad.
    """
    data = _load_json(TARGET_JSON)
    if budget_tenths is None:
        return {
            "generated_at": data["generated_at"],
            "horizon": data["horizon"],
            "quality_weight": data["quality_weight"],
            "pipeline_state": data["pipeline_state"],
            "budget_tenths": 1000,
            "squad": data["squad"],
        }

    squad = optimize(_projections_from(data), budget=budget_tenths)
    return {
        "generated_at": data["generated_at"],
        "horizon": data["horizon"],
        "quality_weight": data["quality_weight"],
        "pipeline_state": data["pipeline_state"],
        "budget_tenths": budget_tenths,
        "squad": {
            "total_cost": squad.total_cost,
            "projected_points": squad.projected_points,
            "formation": squad.formation(),
            "picks": [
                {
                    "player_id": pk.player.player_id,
                    "web_name": pk.player.web_name,
                    "team_id": pk.player.team_id,
                    "team_short": pk.player.team_short,
                    "position": pk.player.position,
                    "now_cost": pk.player.now_cost,
                    "projected_points": pk.player.projected_points,
                    "is_starter": pk.is_starter,
                    "is_captain": pk.is_captain,
                    "is_vice": pk.is_vice,
                }
                for pk in squad.picks
            ],
        },
    }


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


@app.get("/api/entry/{entry_id}/squad")
def get_entry_squad(entry_id: int, gw: int | None = None) -> dict:
    """Pull a manager's 15 picks + bank from the public FPL entry endpoints."""
    try:
        squad = fetch_manager_squad(entry_id, gw=gw)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"could not fetch entry: {e}")
    return {
        "entry_id": squad.entry_id,
        "manager_name": squad.manager_name,
        "team_name": squad.team_name,
        "source_gw": squad.source_gw,
        "bank": squad.bank,
        "squad_value": squad.squad_value,
        "player_ids": squad.player_ids,
        "captain_id": squad.captain_id,
        "vice_id": squad.vice_id,
    }


class TransferRequest(BaseModel):
    existing_ids: list[int] = Field(..., min_length=15, max_length=15,
                                    description="The manager's 15 current player ids")
    bank_tenths: int = Field(..., ge=0, description="Money in bank, tenths of £m")
    free_transfers: int = Field(1, ge=0, le=5)
    max_transfers: int | None = Field(None, ge=0, le=15)
    ignore_hit_cost: bool = Field(
        False,
        description=(
            "If true, treat hits as free (0 pts penalty). Lets the LP pick "
            "the top-of-the-market squad regardless of transfer count — "
            "useful for planning multi-week moves."
        ),
    )


@app.post("/api/transfers")
def post_transfers(req: TransferRequest) -> dict:
    projections = _projections_from_artifact()
    try:
        plan = optimize_transfers(
            projections=projections,
            existing_ids=req.existing_ids,
            bank=req.bank_tenths,
            free_transfers=req.free_transfers,
            max_transfers=req.max_transfers,
            hit_cost=0 if req.ignore_hit_cost else HIT_COST,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    picks = [
        {
            "player_id": pk.player.player_id,
            "web_name": pk.player.web_name,
            "projected_points": pk.player.projected_points,
            "is_starter": pk.is_starter,
            "is_captain": pk.is_captain,
        }
        for pk in plan.new_squad.picks
    ]

    return {
        "chips": chip_advice(picks, _players_without_fixture()),
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

# Static frontend
# ---------------
# When the built React SPA lives at frontend/dist (populated during the Docker
# build), FastAPI serves its assets alongside the API on the same origin.
# In dev this directory doesn't exist, so we skip the mount and let the vite
# dev server handle the frontend at :5173 instead.
_FRONTEND_DIST = Path("frontend") / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    @app.get("/favicon.svg", include_in_schema=False)
    async def _favicon() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "favicon.svg")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        # React Router owns everything that isn't an /api route — hand back
        # index.html so client-side routing picks it up.
        return FileResponse(_FRONTEND_DIST / "index.html")
