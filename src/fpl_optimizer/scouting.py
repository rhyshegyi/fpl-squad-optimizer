"""Enrich raw projections with the context stats that answer 'why this projection?'.

We attach season-to-date rates, current-season rolling last-5 form, next-fixture
context, and availability signals. Everything is loaded once per call — a
single pass over `players`, `historical_player_gw` (current season), and
`fixtures`, then merged in Python.
"""
from __future__ import annotations

from dataclasses import asdict

from .db import connect
from .projections import PlayerProjection


def _current_season_code(conn) -> str:
    row = conn.execute(
        "SELECT MIN(deadline_time) AS d FROM gameweeks"
    ).fetchone()
    if row is None or row["d"] is None:
        raise RuntimeError("no gameweeks staged — run `fpl stage` first")
    year = int(row["d"][:4])
    return f"{year}-{str(year + 1)[2:]}"


def _next_gameweek(conn) -> int | None:
    row = conn.execute(
        "SELECT id FROM gameweeks WHERE is_next = 1 LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT MIN(id) AS id FROM gameweeks WHERE finished = 0"
    ).fetchone()
    return row["id"] if row and row["id"] is not None else None


def _load_scouting_map() -> dict[int, dict]:
    """Return {player_id: {season stats + recent aggregates + next fixture}}."""
    with connect() as conn:
        season = _current_season_code(conn)
        next_gw = _next_gameweek(conn)

        # Only the fields that genuinely live on the bootstrap and cannot be
        # derived: live price, ownership, and availability.
        base_rows = conn.execute(
            "SELECT id, web_name, team_id, selected_by_percent, status, "
            "       chance_next_round "
            "FROM players"
        ).fetchall()

        # Season totals come from the per-gameweek table, not from the
        # bootstrap's own `total_points` / `minutes` / `form`. The two are
        # fetched separately, so a snapshot taken between two fixtures has
        # them describing a different number of matches — which put
        # "gws_played 2" next to a one-game points total on the same row and
        # made the model look like it was ignoring a player's latest score.
        recent_rows = conn.execute(
            "SELECT element, "
            "       COUNT(*) AS gws_played, "
            "       SUM(total_points) AS season_points, "
            "       SUM(minutes) AS season_minutes, "
            "       AVG(minutes) AS minutes_avg, "
            "       AVG(total_points) AS points_avg, "
            "       SUM(COALESCE(expected_goals, 0)) AS xg_recent, "
            "       SUM(COALESCE(expected_assists, 0)) AS xa_recent, "
            "       SUM(COALESCE(bonus, 0)) AS bonus_recent "
            "FROM historical_player_gw "
            "WHERE season = ? "
            "GROUP BY element",
            (season,),
        ).fetchall()
        recent_map = {r["element"]: dict(r) for r in recent_rows}

        # FPL's own `form` is mean points over the last 30 days, so rebuild it
        # from kickoff times rather than carrying the stale bootstrap value.
        form_map = {
            r["element"]: r["form"]
            for r in conn.execute(
                "SELECT element, AVG(total_points) AS form "
                "FROM historical_player_gw "
                "WHERE season = ? AND kickoff_time >= ("
                "  SELECT DATETIME(MAX(kickoff_time), '-30 days') "
                "  FROM historical_player_gw WHERE season = ?"
                ") GROUP BY element",
                (season, season),
            )
        }

        team_short = {
            r["id"]: r["short_name"]
            for r in conn.execute("SELECT id, short_name FROM teams")
        }

        next_fixture: dict[int, dict] = {}
        if next_gw is not None:
            fixtures = conn.execute(
                "SELECT team_h, team_a, team_h_difficulty, team_a_difficulty "
                "FROM fixtures WHERE event = ?",
                (next_gw,),
            ).fetchall()
            for f in fixtures:
                next_fixture[f["team_h"]] = {
                    "opp_id": f["team_a"],
                    "opp_short": team_short.get(f["team_a"]),
                    "is_home": True,
                    "fdr": f["team_h_difficulty"],
                }
                next_fixture[f["team_a"]] = {
                    "opp_id": f["team_h"],
                    "opp_short": team_short.get(f["team_h"]),
                    "is_home": False,
                    "fdr": f["team_a_difficulty"],
                }

    scouting: dict[int, dict] = {}
    for r in base_rows:
        pid = r["id"]
        recent = recent_map.get(pid, {})
        fixture = next_fixture.get(r["team_id"], {})
        games = recent.get("gws_played") or 0
        season_points = recent.get("season_points") or 0
        scouting[pid] = {
            "form": _round(form_map.get(pid) or 0, 1),
            "season_ppg": _round(season_points / games if games else 0, 2),
            "season_points": season_points,
            "season_minutes": recent.get("season_minutes") or 0,
            "selected_by": float(r["selected_by_percent"] or 0),
            "status": r["status"],
            "chance_next_round": r["chance_next_round"],
            "gws_played": recent.get("gws_played", 0),
            "minutes_avg": _round(recent.get("minutes_avg"), 1),
            "points_avg": _round(recent.get("points_avg"), 2),
            "xg_recent": _round(recent.get("xg_recent"), 2),
            "xa_recent": _round(recent.get("xa_recent"), 2),
            "bonus_recent": recent.get("bonus_recent", 0),
            "opp_short": fixture.get("opp_short"),
            "is_home": fixture.get("is_home"),
            "fdr": fixture.get("fdr"),
        }
    return scouting


def _round(value, ndigits: int):
    if value is None:
        return None
    return round(float(value), ndigits)


def enrich_projections(projections: list[PlayerProjection]) -> list[dict]:
    """Return one dict per player: PlayerProjection fields + scouting stats."""
    scouting = _load_scouting_map()
    out: list[dict] = []
    for p in projections:
        row = asdict(p)
        row.update(scouting.get(p.player_id, {}))
        out.append(row)
    return out
