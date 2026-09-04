"""The target squad: where you're trying to get to, not what you'd field on Saturday.

The Squad page used to show the best fifteen for the next gameweek. That
answers a question nobody has — you can't reach it on one free transfer, and
it's stale a week later. Measured on 2024-25 it turned over 11.4 of 15
players every single week, so it wasn't even self-consistent.

This projects a squad worth aiming at over the next month or so, by blending:

* a multi-fixture horizon, so a good run of fixtures pulls a player in, and
* season-to-date quality, shrunk toward the positional average, so a proven
  performer isn't displaced by someone with two good games.

Both live entirely on current-season data. Only the fixture context advances
across the horizon — the fixture list is public in advance, future form is
not — so nothing here peeks at information you wouldn't have on the day.

Backtested equivalents and the weight sweep behind the defaults live in
`backtest.py`.
"""
from __future__ import annotations

import pandas as pd

from .db import connect
from .features import (
    POSITION_CATEGORIES, STRENGTH_FEATURES, STRENGTH_KINDS, build_predict_frame,
    season_team_strength_ranks,
)
from .model import load_model
from .projections import PlayerProjection
from .projections_ml import _availability_multiplier, _next_gameweek

DEFAULT_HORIZON = 6
DEFAULT_QUALITY_WEIGHT = 0.7   # see the churn/payoff sweep in backtest.py
DECAY = 0.75
START_MINUTES = 60
SHRINKAGE_GAMES = 5

# How much football it takes before season-to-date scoring is trusted at its
# full weight. The 0.7 weight was swept over GW8-30, where "season quality"
# means seven or more games; at GW3 it means two, and leaning on two games at
# 70% is leaning on noise. Among players who started, form correlates with
# next-gameweek points at only +0.128, so this term deserves its weight only
# once there's real evidence behind it.
WEIGHT_RAMP_GAMES = 6


def effective_quality_weight(games: int, base: float = DEFAULT_QUALITY_WEIGHT) -> float:
    """Scale the season-quality weight by how many games back it.

    Approaches `base` asymptotically rather than reaching it, which is honest:
    you never have unlimited evidence. Early season this hands the decision to
    the fixture horizon, which is the better-founded signal when almost nothing
    has been played.
    """
    if games <= 0:
        return 0.0
    return base * games / (games + WEIGHT_RAMP_GAMES)

# The only columns that legitimately differ between this gameweek and a future
# one at decision time.
FIXTURE_COLUMNS = ["is_home", *STRENGTH_FEATURES]


def _current_season(conn) -> str:
    row = conn.execute("SELECT MIN(deadline_time) AS d FROM gameweeks").fetchone()
    if row is None or row["d"] is None:
        raise RuntimeError("no gameweeks staged — run `fpl stage` first")
    year = int(row["d"][:4])
    return f"{year}-{str(year + 1)[2:]}"


def _team_strengths(season: str) -> dict[int, dict]:
    """{team_id: {"<kind>_<side>": rank}} for one season.

    Shares `season_team_strength_ranks` with the training path on purpose: the
    horizon must advance fixtures on exactly the scale the model learned on.
    """
    ranks = season_team_strength_ranks()
    ranks = ranks[ranks["season"] == season]
    return {
        int(r["id"]): {
            f"{kind}_{side}": r[f"strength_{kind}_{side}_rank"]
            for kind in STRENGTH_KINDS
            for side in ("home", "away")
        }
        for _, r in ranks.iterrows()
    }


def _fixture_context(conn, season: str, gws: list[int]) -> dict[tuple[int, int], dict]:
    """{(team_id, gw): resolved strength ranks + is_home}.

    Mirrors how `features._add_team_strengths` resolves home/away: your own
    side uses its home figure when at home, and the opponent uses its *away*
    figure in the same fixture.
    """
    strengths = _team_strengths(season)
    if not gws:
        return {}

    placeholders = ",".join("?" * len(gws))
    fixtures = conn.execute(
        f"SELECT event, team_h, team_a FROM fixtures WHERE event IN ({placeholders})",
        gws,
    ).fetchall()

    out: dict[tuple[int, int], dict] = {}
    for f in fixtures:
        gw, home, away = f["event"], f["team_h"], f["team_a"]
        for team, opp, at_home in ((home, away, True), (away, home, False)):
            own_s, opp_s = strengths.get(team), strengths.get(opp)
            if own_s is None or opp_s is None:
                continue
            # A double gameweek would overwrite here; the first fixture is
            # kept, which understates DGW players. Flagged, not yet handled.
            side, opp_side = ("home", "away") if at_home else ("away", "home")
            out.setdefault((team, gw), {
                "is_home": int(at_home),
                **{f"own_strength_{k}_rank": own_s[f"{k}_{side}"]
                   for k in STRENGTH_KINDS},
                **{f"opp_strength_{k}_rank": opp_s[f"{k}_{opp_side}"]
                   for k in STRENGTH_KINDS},
            })
    return out


def _season_quality(conn, season: str, upto_gw: int) -> tuple[dict[int, tuple[float, int]], dict]:
    """Season-to-date points and starts per player, plus positional averages.

    Only gameweeks strictly before `upto_gw` count, so this never sees a
    result that hasn't happened.
    """
    rows = conn.execute(
        "SELECT element, position, SUM(total_points) AS pts, COUNT(*) AS games "
        "FROM historical_player_gw "
        "WHERE season = ? AND gw < ? AND minutes >= ? "
        "GROUP BY element",
        (season, upto_gw, START_MINUTES),
    ).fetchall()
    per_player = {r["element"]: (float(r["pts"] or 0), int(r["games"] or 0)) for r in rows}

    pos_rows = conn.execute(
        "SELECT position, AVG(total_points) AS avg_pts "
        "FROM historical_player_gw "
        "WHERE season = ? AND gw < ? AND minutes >= ? "
        "GROUP BY position",
        (season, upto_gw, START_MINUTES),
    ).fetchall()
    per_position = {r["position"]: float(r["avg_pts"] or 0) for r in pos_rows}
    return per_player, per_position


def project_target(
    horizon: int = DEFAULT_HORIZON,
    quality_weight: float = DEFAULT_QUALITY_WEIGHT,
) -> list[PlayerProjection]:
    """Projections for the target squad, on a points-per-gameweek scale."""
    booster, feat_cols = load_model()

    with connect() as conn:
        season = _current_season(conn)
        gw = _next_gameweek(conn)
        if gw is None:
            raise RuntimeError("no upcoming gameweek in staged data")
        future_gws = list(range(gw + 1, gw + horizon))
        fixtures = _fixture_context(conn, season, future_gws)
        quality, pos_avg = _season_quality(conn, season, gw)

    base = build_predict_frame(season, gw)
    if base.empty:
        raise RuntimeError("no players in predict frame — did staging run?")
    base = base.copy()
    base["position"] = pd.Categorical(base["position"], categories=POSITION_CATEGORIES)

    # --- horizon: freeze form, advance the fixtures -------------------------
    total = booster.predict(base[feat_cols]).astype(float)
    weight_sum = 1.0
    teams = base["team_id"].tolist()

    for step, target_gw in enumerate(future_gws, start=1):
        shifted = base.copy()
        for col in FIXTURE_COLUMNS:
            if col not in shifted.columns:
                continue
            shifted[col] = [
                fixtures.get((int(t), target_gw), {}).get(col)
                if pd.notna(t) else None
                for t in teams
            ]
            shifted[col] = pd.to_numeric(shifted[col], errors="coerce")

        # Blank gameweek contributes nothing — the reason to look ahead at all
        has_fixture = shifted["opp_strength_overall_rank"].notna().to_numpy()
        preds = booster.predict(shifted[feat_cols]).astype(float)
        preds = [p if ok else 0.0 for p, ok in zip(preds, has_fixture)]

        w = DECAY ** step
        total = [t + w * p for t, p in zip(total, preds)]
        weight_sum += w

    horizon_pts = [t / weight_sum for t in total]

    # --- blend with season-to-date quality ---------------------------------
    overall_avg = sum(pos_avg.values()) / len(pos_avg) if pos_avg else 2.0

    out: list[PlayerProjection] = []
    for (_, r), h in zip(base.iterrows(), horizon_pts):
        pid = int(r["element"])
        position = str(r["position"])
        prior = pos_avg.get(position, overall_avg)

        pts, games = quality.get(pid, (0.0, 0))
        q = (pts + prior * SHRINKAGE_GAMES) / (games + SHRINKAGE_GAMES)

        w = effective_quality_weight(games, quality_weight)
        blended = w * q + (1 - w) * float(h)
        blended *= _availability_multiplier(r.get("status"), r.get("chance_next_round"))

        out.append(PlayerProjection(
            player_id=pid,
            web_name=str(r["name"]),
            team_id=int(r["team_id"]),
            team_short=str(r["team"]),
            position=position,
            now_cost=int(r["now_cost"]),
            projected_points=round(max(blended, 0.0), 3),
        ))
    return out
