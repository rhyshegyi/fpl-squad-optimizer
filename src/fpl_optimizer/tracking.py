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
    season: str
    gw: int
    path: Path
    data: dict

    @property
    def scored(self) -> bool:
        return self.data.get("scored_at") is not None

    @property
    def settled(self) -> bool:
        """Scored against numbers FPL has confirmed. Only then is it locked."""
        return self.scored and bool((self.data.get("result") or {}).get("scores_final"))


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


def _season_from_deadline(deadline: str | None) -> str | None:
    """The FPL season a deadline belongs to; the year turns over in July."""
    d = _parse(deadline)
    if d is None:
        return None
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _snapshot_path(season: str, gw: int) -> Path:
    """`gameweeks/<season>/gwNN.json`.

    The season is in the path, not just the payload, because the never-rewrite
    rule keys off whether the file exists. With bare `gwNN.json`, next season's
    GW4 would find this season's scored `gw04.json`, correctly refuse to
    overwrite it, and never be frozen at all — nothing after GW38 would ever be
    recorded again.
    """
    return SNAPSHOT_DIR / season / f"gw{gw:02d}.json"


def migrate_legacy_snapshots() -> list[Path]:
    """Move pre-season-namespacing `gameweeks/gwNN.json` files into place.

    Idempotent: a file already at its destination is left alone, never
    overwritten, for the same reason a scored snapshot is never rewritten.
    """
    if not SNAPSHOT_DIR.exists():
        return []
    moved: list[Path] = []
    for path in sorted(SNAPSHOT_DIR.glob("gw*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        season = data.get("season") or _season_from_deadline(data.get("deadline"))
        if season is None:
            continue
        data["season"] = season
        dest = _snapshot_path(season, int(data["gw"]))
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        path.unlink()
        moved.append(dest)
    return moved


def load_snapshots(season: str | None = None) -> list[Snapshot]:
    """Every snapshot, or one season's, oldest first."""
    if not SNAPSHOT_DIR.exists():
        return []
    pattern = f"{season}/gw*.json" if season else "*/gw*.json"
    out: list[Snapshot] = []
    for path in sorted(SNAPSHOT_DIR.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(Snapshot(
            season=data.get("season") or path.parent.name,
            gw=int(data["gw"]), path=path, data=data,
        ))
    return sorted(out, key=lambda x: (x.season, x.gw))


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
        season = _current_season(conn) if row is not None else None
    if row is None:
        return None

    deadline = _parse(row["deadline_time"])
    if deadline is None or _now() >= deadline:
        return None  # locked; whatever we stored before the deadline stands

    path = _snapshot_path(season, row["id"])
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("scored_at"):
            return None  # already settled, never rewrite history

    # Which model made these projections. The record spans retrains — adding
    # 2025-26 to training changed every projection from GW6 on — and a season
    # overview has to be able to say which weeks came from which model.
    from .historical import historical_seasons

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "season": season,
        "gw": row["id"],
        "model": {"trained_on": historical_seasons(season)},
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
    """Fill in what actually happened. Returns True if it (re)scored.

    Two halves of a snapshot, locked at different moments. The *prediction* —
    squad and projections — is frozen at the deadline and never touched here.
    The *outcome* is not final at the last whistle: FPL keeps revising bonus
    points and its `average_entry_score` until `data_checked`. GW5 was first
    scored with an FPL average of 18 that later read 44, which made a 51-point
    week look like +33. So the outcome is re-scored on every run until FPL
    confirms the round, and only then settles.
    """
    if snap.settled:
        return False

    with connect() as conn:
        # The fixtures and gameweeks tables hold only the live season. Scoring
        # a past season's snapshot against them would grade last May's GW38
        # against this August's GW38 fixtures, so an unscored snapshot from a
        # finished season is left as it is rather than scored wrongly.
        if snap.season != _current_season(conn):
            return False
        if not _round_is_complete(conn, snap.gw):
            return False
        actuals = _actuals(conn, snap.season, snap.gw)
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
    if bench and bench["data_checked"]:
        snap.data["settled_at"] = snap.data["scored_at"]
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

LEADERBOARD_SIZE = 30


def season_leaders(limit: int = LEADERBOARD_SIZE) -> list[dict]:
    """Who has actually scored the most this season, and at what price.

    Straight from the per-gameweek rows, so it counts only matches that have
    been played — no phantom rows for fixtures still to come. Points come from
    the history table while price and ownership come from the live bootstrap,
    because a player's cost today is what matters for acting on this.

    Backward-looking on purpose. It is not a shopping list and the projections
    are not trying to reproduce it: a player can top this table on two
    hauls against weak defences and still be a poor bet for the next six
    gameweeks. It is here so the model's output can be read against what has
    actually happened.
    """
    with connect() as conn:
        season = _current_season(conn)
        rows = conn.execute(
            "SELECT h.element, p.web_name, t.short_name AS team_short, "
            "       h.position, p.now_cost, p.selected_by_percent, "
            "       SUM(h.total_points) AS points, "
            "       SUM(h.minutes) AS minutes, "
            "       SUM(h.goals_scored) AS goals, "
            "       SUM(h.assists) AS assists, "
            "       SUM(h.bonus) AS bonus, "
            "       COUNT(*) AS games "
            "FROM historical_player_gw h "
            "JOIN players p ON p.id = h.element "
            "JOIN teams t ON t.id = p.team_id "
            "WHERE h.season = ? "
            "GROUP BY h.element "
            "ORDER BY points DESC, minutes ASC "
            "LIMIT ?",
            (season, limit),
        ).fetchall()

    out = []
    for rank, r in enumerate(rows, start=1):
        points = int(r["points"] or 0)
        cost = int(r["now_cost"] or 0)
        games = int(r["games"] or 0)
        out.append({
            "rank": rank,
            "player_id": r["element"],
            "web_name": r["web_name"],
            "team_short": r["team_short"],
            "position": r["position"],
            "now_cost": cost,
            "points": points,
            "games": games,
            "minutes": int(r["minutes"] or 0),
            "goals": int(r["goals"] or 0),
            "assists": int(r["assists"] or 0),
            "bonus": int(r["bonus"] or 0),
            "ppg": round(points / games, 2) if games else 0.0,
            "value": round(points / (cost / 10), 2) if cost else None,
            "selected_by": float(r["selected_by_percent"] or 0),
        })
    return out


def _target_squad_ids() -> set[int]:
    path = ARTIFACTS_DIR / "latest_target.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError):
        return set()
    return {p["player_id"] for p in data.get("squad", {}).get("picks", [])}


def _week_row(s: Snapshot) -> dict:
    r, a = s.data["result"], s.data["accuracy"]
    return {
        "season": s.season,
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
    }


def _totals(weeks: list[dict]) -> dict:
    # Only confirmed weeks are rated against FPL's average, because until
    # `data_checked` that average is still being revised — sometimes by more
    # than half.
    rated = [w for w in weeks if w["beat_average"] is not None and w["scores_final"]]
    maes = [w["mae"] for w in weeks if w["mae"] is not None]
    rhos = [w["spearman"] for w in weeks if w["spearman"] is not None]
    return {
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
        "mean_mae": round(sum(maes) / len(maes), 3) if maes else None,
        "mean_spearman": round(sum(rhos) / len(rhos), 4) if rhos else None,
    }


def build_summary(season: str | None = None) -> dict:
    """The rolled-up track record the site reads, for one season.

    Totals never mix seasons: a model retrained over the summer is a different
    model, and averaging its first weeks into last season's record would blur
    the one comparison the record exists to make. `seasons` indexes every
    season on file so a season overview or selector can read past ones
    without another artifact.
    """
    if season is None:
        with connect() as conn:
            season = _current_season(conn)

    snaps = load_snapshots()
    this_season = [s for s in snaps if s.season == season]
    weeks = [_week_row(s) for s in this_season if s.scored]
    pending = [
        {"gw": s.gw, "name": s.data.get("name"), "deadline": s.data.get("deadline")}
        for s in this_season if not s.scored
    ]

    seasons = []
    for code in sorted({s.season for s in snaps} | {season}):
        scored = [_week_row(s) for s in snaps if s.season == code and s.scored]
        seasons.append({"season": code, "current": code == season, **_totals(scored)})

    try:
        leaders = season_leaders()
        owned = _target_squad_ids()
        for row in leaders:
            row["in_target_squad"] = row["player_id"] in owned
        top10 = sum(1 for row in leaders[:10] if row["in_target_squad"])
    except Exception as e:  # noqa: BLE001 - the track record matters more
        print(f"  warning: season leaders omitted ({e})")
        leaders, top10 = [], 0

    return {
        "generated_at": _now().isoformat(),
        "season": season,
        "totals": _totals(weeks),
        "gameweeks": weeks,
        "pending": pending,
        "seasons": seasons,
        "leaders": leaders,
        "leaders_in_target_top10": top10,
    }


def update_tracking(squad: dict, projections: list[dict]) -> dict[str, object]:
    """Freeze the open gameweek, score any finished ones, rewrite the summary."""
    migrated = migrate_legacy_snapshots()
    frozen = freeze_gameweek(squad, projections)
    scored = [f"{s.season} GW{s.gw}" for s in load_snapshots() if score_snapshot(s)]

    ACCURACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCURACY_PATH.write_text(json.dumps(build_summary(), indent=2), encoding="utf-8")
    return {
        "migrated": [str(m) for m in migrated],
        "frozen": str(frozen) if frozen else None,
        "scored": scored,
        "summary": str(ACCURACY_PATH),
    }
