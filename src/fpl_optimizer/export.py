"""Serialize the latest optimizer output + player projections to versioned
JSON artifacts under data/artifacts/.

These files are the persistence layer that a future backend (Phase 5) reads
from. They're also small enough to check into git after each weekly run so
history is browsable in the repo.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
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
    """Enriched next-gameweek rows, plus each player's 6-gameweek target value.

    Both numbers live on the same row so the Scouting page can show them side
    by side. They routinely disagree — and not by a constant offset, they
    genuinely reorder players — so showing only one invites the reasonable
    conclusion that the other page is wrong.
    """
    rows = enrich_projections(projections)
    try:
        from .target import project_target
        target = {p.player_id: p.projected_points for p in project_target()}
    except Exception as e:  # noqa: BLE001 - the next-GW rows must still ship
        print(f"  warning: target values omitted from projections ({e})")
        target = {}

    for r in rows:
        r["target_points"] = target.get(r["player_id"])
    return rows


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _data_health(conn, season: str) -> dict:
    """Is this snapshot internally consistent, and does it cover every result?

    "How old is the data" is the wrong question. An hour-old fetch taken
    between two Saturday fixtures is worse than a day-old one taken after the
    round finished, and a stale snapshot cannot tell you it is stale by
    looking at itself — its own `fixtures.finished` flags are stale too.

    So the check compares two sources that are fetched independently: the
    bootstrap's season totals, and the per-gameweek history. When a snapshot
    lands mid-round they disagree, and the count of players they disagree
    about is the number the answer turns on.
    """
    disagreeing = conn.execute(
        "SELECT COUNT(*) AS n FROM ("
        "  SELECT p.id FROM players p"
        "  JOIN historical_player_gw h ON h.element = p.id"
        "  WHERE h.season = ?"
        "  GROUP BY p.id HAVING p.total_points != SUM(h.total_points)"
        ")", (season,),
    ).fetchone()["n"]
    covered = conn.execute(
        "SELECT COUNT(DISTINCT element) AS n, MAX(gw) AS gw "
        "FROM historical_player_gw WHERE season = ?", (season,),
    ).fetchone()
    latest = conn.execute(
        "SELECT MAX(kickoff_time) AS ts FROM fixtures "
        "WHERE finished = 1 OR finished_provisional = 1"
    ).fetchone()

    return {
        "players_tracked": covered["n"] or 0,
        "players_disagreeing": disagreeing,
        "latest_gw_on_file": covered["gw"],
        "latest_result": (_parse(latest["ts"]).isoformat()
                          if latest and _parse(latest["ts"]) else None),
        "gameweek_in_progress": _gameweek_in_progress(conn),
        "bonus_pending": _bonus_pending(conn),
    }


# How long after a round's last scheduled kickoff an unplayed fixture stops
# meaning "still being played" and starts meaning "called off". Without this a
# single postponed match would leave the site claiming a round was in progress
# for weeks. Generous enough to absorb a Monday-night finish plus FPL taking
# its time flipping flags.
POSTPONEMENT_GRACE = timedelta(hours=36)


def _current_round(conn) -> dict | None:
    """The round whose deadline has most recently passed, with its fixture counts.

    Anchoring on "latest deadline passed" rather than "any round with unplayed
    fixtures" is what stops an older postponed match from being mistaken for
    live football once the next round has started.
    """
    now = datetime.now(timezone.utc).isoformat()
    gw = conn.execute(
        "SELECT id, name, data_checked FROM gameweeks "
        "WHERE deadline_time <= ? ORDER BY deadline_time DESC LIMIT 1",
        (now,),
    ).fetchone()
    if gw is None:
        return None
    counts = conn.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(COALESCE(finished, 0) = 1 "
        "           OR COALESCE(finished_provisional, 0) = 1) AS played, "
        "       SUM(COALESCE(started, 0) = 1) AS started, "
        "       MAX(kickoff_time) AS last_kickoff "
        "FROM fixtures WHERE event = ?", (gw["id"],),
    ).fetchone()
    return {
        "id": gw["id"],
        "name": gw["name"],
        "data_checked": bool(gw["data_checked"]),
        "total": counts["total"] or 0,
        "played": counts["played"] or 0,
        "started": counts["started"] or 0,
        "last_kickoff": counts["last_kickoff"],
    }


def _gameweek_in_progress(conn) -> dict | None:
    """The gameweek being played right now, if there is one.

    Between a deadline and the last whistle of that round, squads are locked
    and results are partial. Recommendations on the site are for the *next*
    gameweek and are built on everything up to the last completed match, so
    they are real but provisional — every result that lands this weekend
    moves them. Saying so is more honest than a green tick.
    """
    cur = _current_round(conn)
    if cur is None or not cur["total"] or cur["played"] >= cur["total"]:
        return None

    last = _parse(cur["last_kickoff"])
    if last and datetime.now(timezone.utc) - last > POSTPONEMENT_GRACE:
        return None  # whatever is left was called off, not kicked off

    return {
        "id": cur["id"],
        "name": cur["name"],
        "matches_played": cur["played"],
        "matches_started": cur["started"],
        "matches_total": cur["total"],
    }


def _bonus_pending(conn) -> dict | None:
    """Every match played, but FPL has not confirmed bonus points yet.

    A narrower caveat than a round in progress and worth keeping separate: the
    football is over and the projections are built on all of it, but a handful
    of players can still move by a point or two when bonus settles. Matters
    most to the track record, which scores against these numbers.
    """
    cur = _current_round(conn)
    if cur is None or not cur["total"]:
        return None
    if cur["played"] < cur["total"] or cur["data_checked"]:
        return None
    return {"id": cur["id"], "name": cur["name"]}


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
        ts = last_fetch["ts"] if last_fetch else None
        first = conn.execute(
            "SELECT MIN(deadline_time) AS d FROM gameweeks"
        ).fetchone()
        year = int(first["d"][:4]) if first and first["d"] else None
        health = (
            _data_health(conn, f"{year}-{str(year + 1)[2:]}")
            if year else {}
        )
    return {
        "last_fetch": ts,
        "current_gw": {"id": current["id"], "name": current["name"]} if current else None,
        "next_gw": {
            "id": nxt["id"], "name": nxt["name"], "deadline_time": nxt["deadline_time"],
        } if nxt else None,
        "data_health": health,
    }


# A fetch older than this is stale for FPL purposes: prices move nightly and
# injury news lands continuously through the week.
MAX_SNAPSHOT_AGE = timedelta(hours=6)


class StaleSnapshot(RuntimeError):
    """Raised when the database is too old to publish from."""


def _last_fetch() -> datetime | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(fetched_at) AS ts FROM raw_bootstrap"
        ).fetchone()
    return _parse(row["ts"] if row else None)


def assert_publishable(max_age: timedelta = MAX_SNAPSHOT_AGE) -> None:
    """Refuse to build artifacts from a database nobody has refreshed.

    The artifacts are a build output, and the pipeline that owns them fetches
    seconds before writing them — so in CI this never fires. It exists for the
    laptop, where `fpl export` will happily serialise a database last filled
    days ago. That is how a four-day-old snapshot got committed over CI's
    fresh output and shipped to production: nothing in the act of exporting
    knew, or could say, how old its inputs were.
    """
    fetched = _last_fetch()
    if fetched is None:
        raise StaleSnapshot(
            "no data has ever been fetched — run `fpl ingest` first"
        )

    age = datetime.now(timezone.utc) - fetched
    if age > max_age:
        hours = age.total_seconds() / 3600
        raise StaleSnapshot(
            f"the last fetch was {hours:.0f}h ago ({fetched.isoformat()}), "
            f"older than the {max_age.total_seconds() / 3600:.0f}h limit.\n"
            f"Run `fpl ingest && fpl stage && fpl ingest-live-history` first, "
            f"or pass --allow-stale if you are deliberately rebuilding old "
            f"artifacts. Committing stale artifacts overwrites the pipeline's "
            f"fresh ones and ships them to the live site."
        )


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

    written = {"squad": squad_path, "projections": proj_path}

    # The target squad needs SQLite and LightGBM, which the deployed image
    # deliberately lacks, so it's computed here and served from cache like
    # everything else. Player-level projections go in alongside the squad so
    # the API can still re-solve for an arbitrary budget without them.
    target_path = _export_target()
    if target_path is not None:
        written["target"] = target_path

    # Freezing has to happen on every run, because we cannot know which run is
    # the last one before a deadline. Wrapped because a tracking failure must
    # never cost the site its projections.
    try:
        from .tracking import update_tracking

        result = update_tracking(squad_data["squad"], proj_data["projections"])
        if result["frozen"]:
            written["frozen"] = Path(str(result["frozen"]))
        if result["scored"]:
            print(f"  scored gameweeks: {result['scored']}")
        written["accuracy"] = Path(str(result["summary"]))
    except Exception as e:  # noqa: BLE001 - projections matter more than tracking
        print(f"  warning: tracking update skipped ({e})")

    return written


def _export_target() -> Path | None:
    """Write latest_target.json: the multi-week squad worth aiming at."""
    try:
        from .optimizer import optimize
        from .target import (
            DEFAULT_HORIZON, DEFAULT_QUALITY_WEIGHT, project_target,
        )

        projections = project_target()
        squad = optimize(projections, budget=1000)
    except Exception as e:  # noqa: BLE001 - a missing target must not break the run
        print(f"  warning: target squad export skipped ({e})")
        return None

    path = ARTIFACTS_DIR / "latest_target.json"
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon": DEFAULT_HORIZON,
        "quality_weight": DEFAULT_QUALITY_WEIGHT,
        "pipeline_state": _pipeline_state(),
        "squad": _squad_to_dict(squad),
        "projections": [asdict(p) for p in projections],
    }, indent=2))
    return path
