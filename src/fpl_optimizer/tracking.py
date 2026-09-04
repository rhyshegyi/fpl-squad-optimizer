"""Freeze each gameweek's recommendation before its deadline, then score it.

The backtest answers "would this model have worked on 2024-25?". It cannot
answer "is it working now", and that gap is not academic: the fixture features
were inert for a month and every backtest stayed green, because all three
training seasons sit on one consistent scale. Live data is where a change in
what FPL serves actually bites.

So each run before a deadline writes a snapshot of what was recommended and
what every player was projected to score. Once the round has been played, the
snapshot is scored against what happened. Over weeks that accumulates into
out-of-sample evidence on live data — one gameweek at a time, but honestly
dated, and impossible to fit after the fact because the projections were
written down before kickoff.

Deliberately *not* a live-points view. This data refreshes twice a day, so
mid-match it is stale within minutes and provisional bonus moves afterwards.
The official FPL app does live scoring properly. What it cannot tell you is
whether the model was right.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .backtest import score_gameweek
from .db import connect

ARTIFACTS_DIR = Path("data") / "artifacts"
SNAPSHOT_DIR = ARTIFACTS_DIR / "gameweeks"
ACCURACY_PATH = ARTIFACTS_DIR / "accuracy.json"

# Players who did not appear are excluded from accuracy stats. A projection of
# 4.2 for someone who was injured is a squad-selection question, not a
# points-model question, and mixing the two hides both.
MIN_MINUTES_FOR_ACCURACY = 1


@dataclass
class Snapshot:
    gw: int
    path: Path
    data: dict

    @property
    def scored(self) -> bool:
        return self.data.get("scored_at") is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _snapshot_path(gw: int) -> Path:
    return SNAPSHOT_DIR / f"gw{gw:02d}.json"


def load_snapshots() -> list[Snapshot]:
    if not SNAPSHOT_DIR.exists():
        return []
    out: list[Snapshot] = []
    for path in sorted(SNAPSHOT_DIR.glob("gw*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(Snapshot(gw=int(data["gw"]), path=path, data=data))
    return out


# --------------------------------------------------------------------------
# Freeze
# --------------------------------------------------------------------------

def freeze_gameweek(squad: dict, projections: list[dict]) -> Path | None:
    """Write what we are recommending for the next gameweek, if it is still open.

    Overwritten on every run up to the deadline, so the stored snapshot is the
    last advice given while it was still actionable. After the deadline it is
    left alone — that is the whole point, and it is what makes the comparison
    afterwards honest rather than retrofitted.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, deadline_time FROM gameweeks WHERE is_next = 1"
        ).fetchone()
    if row is None:
        return None

    deadline = _parse(row["deadline_time"])
    if deadline is None or _now() >= deadline:
        return None  # locked; whatever we stored before the deadline stands

    path = _snapshot_path(row["id"])
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("scored_at"):
            return None  # already settled, never rewrite history

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "gw": row["id"],
        "name": row["name"],
        "deadline": row["deadline_time"],
        "frozen_at": _now().isoformat(),
        "scored_at": None,
        "squad": squad,
        "projections": [
            {
                "player_id": p["player_id"],
                "web_name": p["web_name"],
                "team_short": p["team_short"],
                "position": p["position"],
                "now_cost": p["now_cost"],
                "projected": round(float(p["projected_points"]), 3),
            }
            for p in projections
        ],
    }, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Score
# --------------------------------------------------------------------------

def _round_is_complete(conn, gw: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(COALESCE(finished, 0) = 1 "
        "           OR COALESCE(finished_provisional, 0) = 1) AS played "
        "FROM fixtures WHERE event = ?", (gw,),
    ).fetchone()
    return bool(row and row["total"] and row["played"] == row["total"])


def _actuals(conn, season: str, gw: int) -> dict[int, tuple[int, int]]:
    return {
        r["element"]: (int(r["total_points"] or 0), int(r["minutes"] or 0))
        for r in conn.execute(
            "SELECT element, total_points, minutes FROM historical_player_gw "
            "WHERE season = ? AND gw = ?", (season, gw),
        )
    }


def _current_season(conn) -> str:
    row = conn.execute("SELECT MIN(deadline_time) AS d FROM gameweeks").fetchone()
    year = int(row["d"][:4])
    return f"{year}-{str(year + 1)[2:]}"


def _spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Rank correlation between projected and actual. None below 30 pairs."""
    if len(pairs) < 30:
        return None
    import pandas as pd

    df = pd.DataFrame(pairs, columns=["projected", "actual"])
    value = df["projected"].corr(df["actual"], method="spearman")
    return None if pd.isna(value) else round(float(value), 4)


def score_snapshot(snap: Snapshot) -> bool:
    """Fill in what actually happened. Returns True if it scored."""
    if snap.scored:
        return False

    with connect() as conn:
        if not _round_is_complete(conn, snap.gw):
            return False
        season = _current_season(conn)
        actuals = _actuals(conn, season, snap.gw)
        bench = conn.execute(
            "SELECT average_entry_score, highest_score, data_checked "
            "FROM gameweeks WHERE id = ?", (snap.gw,),
        ).fetchone()

    if not actuals:
        return False

    picks = snap.data["squad"]["picks"]
    position_of = {p["player_id"]: p["position"] for p in picks}
    starters = [p["player_id"] for p in picks if p["is_starter"]]
    benched = [p["player_id"] for p in picks if not p["is_starter"]]
    captain = next((p["player_id"] for p in picks if p["is_captain"]), None)
    vice = next((p["player_id"] for p in picks if p["is_vice"]), None)

    result = score_gameweek(
        gw=snap.gw,
        starter_ids=starters,
        bench_ids=benched,
        captain_id=captain,
        vice_id=vice,
        position_of=position_of,
        actuals={(pid, snap.gw): v for pid, v in actuals.items()},
    )

    rows = []
    for p in snap.data["projections"]:
        pts, mins = actuals.get(p["player_id"], (0, 0))
        rows.append({**p, "actual": pts, "minutes": mins})

    appeared = [r for r in rows if r["minutes"] >= MIN_MINUTES_FOR_ACCURACY]
    errors = [r["actual"] - r["projected"] for r in appeared]
    n = len(errors)

    snap.data["scored_at"] = _now().isoformat()
    snap.data["result"] = {
        "points": result.points,
        "starter_points": result.starter_points,
        "captain_id": result.captain_id,
        "captain_points": result.captain_points,
        "captain_blanked": result.captain_blanked,
        "autosubs": result.autosubs,
        "points_left_on_bench": result.points_left_on_bench,
        "fpl_average": bench["average_entry_score"] if bench else None,
        "fpl_highest": bench["highest_score"] if bench else None,
        "scores_final": bool(bench["data_checked"]) if bench else False,
    }
    snap.data["accuracy"] = {
        "players_appeared": n,
        "mae": round(sum(abs(e) for e in errors) / n, 3) if n else None,
        "rmse": round((sum(e * e for e in errors) / n) ** 0.5, 3) if n else None,
        "bias": round(sum(errors) / n, 3) if n else None,
        "spearman": _spearman([(r["projected"], r["actual"]) for r in appeared]),
    }
    # Only players who appeared: a 0 for someone who never left the bench is
    # not a modelling miss, and would swamp the list.
    ranked = sorted(appeared, key=lambda r: r["actual"] - r["projected"])
    snap.data["misses"] = [_trim(r) for r in ranked[:8]]
    snap.data["hits"] = [_trim(r) for r in reversed(ranked[-8:])]

    snap.path.write_text(json.dumps(snap.data, indent=2), encoding="utf-8")
    return True


def _trim(row: dict) -> dict:
    return {
        "web_name": row["web_name"],
        "team_short": row["team_short"],
        "position": row["position"],
        "projected": row["projected"],
        "actual": row["actual"],
        "minutes": row["minutes"],
    }


# --------------------------------------------------------------------------
# Roll-up
# --------------------------------------------------------------------------

def build_summary() -> dict:
    """The rolled-up track record the site reads."""
    snaps = [s for s in load_snapshots() if s.scored]
    weeks = []
    for s in snaps:
        r, a = s.data["result"], s.data["accuracy"]
        weeks.append({
            "gw": s.gw,
            "name": s.data.get("name"),
            "deadline": s.data.get("deadline"),
            "frozen_at": s.data.get("frozen_at"),
            "points": r["points"],
            "fpl_average": r.get("fpl_average"),
            "beat_average": (
                None if r.get("fpl_average") in (None, 0)
                else r["points"] - r["fpl_average"]
            ),
            "captain_points": r["captain_points"],
            "captain_blanked": r["captain_blanked"],
            "points_left_on_bench": r["points_left_on_bench"],
            "scores_final": r.get("scores_final", False),
            "mae": a["mae"],
            "spearman": a["spearman"],
            "players_appeared": a["players_appeared"],
            "hits": s.data.get("hits", []),
            "misses": s.data.get("misses", []),
        })

    rated = [w for w in weeks if w["beat_average"] is not None]
    totals = {
        "gameweeks_scored": len(weeks),
        "total_points": sum(w["points"] for w in weeks) or None,
        "mean_points": (
            round(sum(w["points"] for w in weeks) / len(weeks), 1) if weeks else None
        ),
        "mean_fpl_average": (
            round(sum(w["fpl_average"] for w in rated) / len(rated), 1)
            if rated else None
        ),
        "weeks_beating_average": sum(1 for w in rated if w["beat_average"] > 0),
        "weeks_rated": len(rated),
    }
    maes = [w["mae"] for w in weeks if w["mae"] is not None]
    rhos = [w["spearman"] for w in weeks if w["spearman"] is not None]
    totals["mean_mae"] = round(sum(maes) / len(maes), 3) if maes else None
    totals["mean_spearman"] = round(sum(rhos) / len(rhos), 4) if rhos else None

    pending = [
        {"gw": s.gw, "name": s.data.get("name"), "deadline": s.data.get("deadline")}
        for s in load_snapshots() if not s.scored
    ]
    return {
        "generated_at": _now().isoformat(),
        "totals": totals,
        "gameweeks": weeks,
        "pending": pending,
    }


def update_tracking(squad: dict, projections: list[dict]) -> dict[str, object]:
    """Freeze the open gameweek, score any finished ones, rewrite the summary."""
    frozen = freeze_gameweek(squad, projections)
    scored = [s.gw for s in load_snapshots() if score_snapshot(s)]

    ACCURACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCURACY_PATH.write_text(json.dumps(build_summary(), indent=2), encoding="utf-8")
    return {
        "frozen": str(frozen) if frozen else None,
        "scored": scored,
        "summary": str(ACCURACY_PATH),
    }
