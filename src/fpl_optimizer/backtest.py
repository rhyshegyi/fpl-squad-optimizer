"""Replay a past season following the tool's own advice, and score it.

Phase 1 covers the scoring engine: point-in-time projections, XI + captain
selection each gameweek, and FPL's auto-substitution rules. Transfers come
in phase 2.

The engine deliberately reuses `optimize()` from the production optimizer
rather than reimplementing selection, so what gets measured is the real
logic rather than a lookalike.

Correctness notes that matter more than they look:

* No lookahead. Features are already lag-safe (`_add_rolling` shifts by one
  gameweek before rolling), but the *model* must also be trained without the
  season under test — otherwise the backtest grades its own homework. See
  `train_excluding_season`.
* Auto-subs. A starter who logs 0 minutes is replaced by the first eligible
  bench player that keeps the formation legal. Skipping this understates
  every strategy, and understates active ones more than passive ones.
* Captaincy. If the captain blanks, the armband falls to the vice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import pandas as pd

from .features import POSITION_CATEGORIES, build_training_frame, feature_columns
from .optimizer import SQUAD_SHAPE, STARTER_LIMITS, STARTING_XI
from .projections import PlayerProjection

# LightGBM params kept in step with model.train() so backtest numbers reflect
# the shipped model rather than a differently-tuned one.
LGB_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.9,
    "bagging_freq": 5,
    "min_data_in_leaf": 40,
    "verbose": -1,
}


@dataclass
class GameweekScore:
    gw: int
    points: int                       # after captain doubling and auto-subs
    starter_points: int               # before captain bonus
    captain_id: int | None
    captain_points: int               # the doubled portion actually earned
    captain_blanked: bool             # armband fell through to the vice
    autosubs: list[tuple[int, int]] = field(default_factory=list)  # (out, in)
    points_left_on_bench: int = 0


@dataclass
class BacktestResult:
    season: str
    strategy: str
    start_gw: int
    end_gw: int
    total_points: int
    gameweeks: list[GameweekScore]

    def points_per_gw(self) -> float:
        return self.total_points / len(self.gameweeks) if self.gameweeks else 0.0

    def captain_hit_rate(self) -> float:
        """How often the armband landed on the squad's actual top scorer."""
        scored = [g for g in self.gameweeks if g.captain_id is not None]
        if not scored:
            return 0.0
        return sum(1 for g in scored if not g.captain_blanked) / len(scored)


# --------------------------------------------------------------------------
# Point-in-time data
# --------------------------------------------------------------------------

def load_season_frame(season: str) -> pd.DataFrame:
    """Feature rows for one season. Rolling features are already lagged, so a
    row for gameweek N only sees gameweeks < N."""
    df = build_training_frame([season])
    return df[df["season"] == season].copy()


def train_excluding_season(exclude: str) -> tuple[lgb.Booster, list[str]]:
    """Fit a model on every complete season except `exclude`.

    Backtesting a season the model trained on would be self-fulfilling, so
    the excluded season is held out entirely rather than merely used for
    validation.
    """
    df = build_training_frame()
    max_gw = df.groupby("season")["gw"].max()
    complete = sorted(max_gw[max_gw >= 35].index)
    train_seasons = [s for s in complete if s != exclude]
    if not train_seasons:
        raise RuntimeError(
            f"no complete seasons left to train on after excluding {exclude}"
        )

    feat = feature_columns()
    train_df = df[df["season"].isin(train_seasons)]
    ds = lgb.Dataset(
        train_df[feat],
        label=train_df["total_points"].astype(float),
        categorical_feature=["position"],
    )
    booster = lgb.train(LGB_PARAMS, ds, num_boost_round=400)
    return booster, feat


def project_gameweek(
    frame: pd.DataFrame,
    booster: lgb.Booster,
    feat: list[str],
    gw: int,
) -> list[PlayerProjection]:
    """Projections for one gameweek, using only prior-gameweek information."""
    rows = frame[frame["gw"] == gw]
    if rows.empty:
        return []

    rows = rows.copy()
    rows["position"] = pd.Categorical(rows["position"], categories=POSITION_CATEGORIES)
    preds = booster.predict(rows[feat])

    out: list[PlayerProjection] = []
    for (_, r), p in zip(rows.iterrows(), preds):
        cost = r.get("value")
        if pd.isna(cost) or pd.isna(r.get("position")):
            continue
        out.append(PlayerProjection(
            player_id=int(r["element"]),
            web_name=str(r.get("name") or r["element"]),
            team_id=int(r["team_id"]) if not pd.isna(r.get("team_id")) else 0,
            team_short=str(r.get("team") or ""),
            position=str(r["position"]),
            now_cost=int(cost),
            projected_points=round(max(float(p), 0.0), 3),
        ))
    return out


def load_actuals(frame: pd.DataFrame) -> dict[tuple[int, int], tuple[int, int]]:
    """{(element, gw): (actual_points, minutes)} — the ground truth we score against."""
    actuals: dict[tuple[int, int], tuple[int, int]] = {}
    for r in frame.itertuples():
        pts = 0 if pd.isna(r.total_points) else int(r.total_points)
        mins = 0 if pd.isna(r.minutes) else int(r.minutes)
        actuals[(int(r.element), int(r.gw))] = (pts, mins)
    return actuals


# --------------------------------------------------------------------------
# FPL scoring rules
# --------------------------------------------------------------------------

def formation_is_legal(positions: list[str]) -> bool:
    if len(positions) != STARTING_XI:
        return False
    counts = {p: positions.count(p) for p in SQUAD_SHAPE}
    for pos, (lo, hi) in STARTER_LIMITS.items():
        if not (lo <= counts.get(pos, 0) <= hi):
            return False
    return True


def apply_autosubs(
    starter_ids: list[int],
    bench_ids: list[int],
    position_of: dict[int, str],
    minutes_of: dict[int, int],
) -> tuple[list[int], list[tuple[int, int]]]:
    """Replace starters who logged 0 minutes, following FPL's rules.

    Bench players are tried in order; a swap only happens if it leaves a legal
    formation and the incoming player actually played. The bench goalkeeper
    can only come on for the starting goalkeeper.
    """
    xi = list(starter_ids)
    available_bench = [b for b in bench_ids if minutes_of.get(b, 0) > 0]
    subs: list[tuple[int, int]] = []

    blanks = [p for p in starter_ids if minutes_of.get(p, 0) == 0]
    for out_id in blanks:
        out_pos = position_of.get(out_id)
        for in_id in list(available_bench):
            in_pos = position_of.get(in_id)
            # Keepers are a closed swap in both directions
            if (out_pos == "GK") != (in_pos == "GK"):
                continue
            candidate = [in_id if p == out_id else p for p in xi]
            if formation_is_legal([position_of[p] for p in candidate]):
                xi = candidate
                available_bench.remove(in_id)
                subs.append((out_id, in_id))
                break
    return xi, subs


def score_gameweek(
    gw: int,
    starter_ids: list[int],
    bench_ids: list[int],
    captain_id: int | None,
    vice_id: int | None,
    position_of: dict[int, str],
    actuals: dict[tuple[int, int], tuple[int, int]],
) -> GameweekScore:
    def pts(pid: int) -> int:
        return actuals.get((pid, gw), (0, 0))[0]

    def mins(pid: int) -> int:
        return actuals.get((pid, gw), (0, 0))[1]

    minutes_of = {p: mins(p) for p in starter_ids + bench_ids}
    xi, subs = apply_autosubs(starter_ids, bench_ids, position_of, minutes_of)

    starter_points = sum(pts(p) for p in xi)

    # Armband falls through to the vice when the captain doesn't feature
    captain_blanked = False
    effective_captain = captain_id
    if captain_id is not None and minutes_of.get(captain_id, 0) == 0:
        captain_blanked = True
        effective_captain = vice_id if vice_id in xi else None

    captain_bonus = pts(effective_captain) if effective_captain in xi else 0

    benched = [p for p in (starter_ids + bench_ids) if p not in xi]
    return GameweekScore(
        gw=gw,
        points=starter_points + captain_bonus,
        starter_points=starter_points,
        captain_id=effective_captain,
        captain_points=captain_bonus,
        captain_blanked=captain_blanked,
        autosubs=subs,
        points_left_on_bench=sum(pts(p) for p in benched),
    )


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

def _pick_xi_and_captain(
    squad: list[PlayerProjection],
) -> tuple[list[int], list[int], int | None, int | None]:
    """Best legal XI + captain from a fixed 15, via the production optimizer.

    Feeding `optimize()` exactly fifteen players with a budget equal to their
    combined cost forces it to select all of them, so what it is really
    solving is the XI/captain problem — the same code path the live app uses.

    Bench order is by projected points (keeper first), which is what decides
    who comes on as an auto-sub.
    """
    from .optimizer import optimize

    budget = sum(p.now_cost for p in squad)
    result = optimize(squad, budget=budget)

    starters = [pk.player.player_id for pk in result.picks if pk.is_starter]
    bench_picks = [pk for pk in result.picks if not pk.is_starter]
    bench_picks.sort(key=lambda pk: (pk.player.position != "GK",
                                     -pk.player.projected_points))
    bench = [pk.player.player_id for pk in bench_picks]

    captain = next((pk.player.player_id for pk in result.picks if pk.is_captain), None)
    vice = next((pk.player.player_id for pk in result.picks if pk.is_vice), None)
    return starters, bench, captain, vice


def run_set_and_forget(
    season: str,
    start_gw: int = 2,
    end_gw: int = 38,
    budget: int = 1000,
) -> BacktestResult:
    """Pick a squad once, then never transfer — only set the XI each week.

    This is the benchmark that isolates how much the weekly transfer advice
    is actually worth, and it is also the simplest strategy to score, which
    makes it the right thing to validate the engine against first.
    """
    frame = load_season_frame(season)
    booster, feat = train_excluding_season(season)
    actuals = load_actuals(frame)

    opening = project_gameweek(frame, booster, feat, start_gw)
    if not opening:
        raise RuntimeError(f"no projections available for {season} GW{start_gw}")

    from .optimizer import optimize
    initial = optimize(opening, budget=budget)
    squad_ids = [pk.player.player_id for pk in initial.picks]
    meta = {pk.player.player_id: pk.player for pk in initial.picks}
    position_of = {pid: pl.position for pid, pl in meta.items()}

    scores: list[GameweekScore] = []
    for gw in range(start_gw, end_gw + 1):
        gw_proj = {p.player_id: p for p in project_gameweek(frame, booster, feat, gw)}
        # A squad member with no row this gameweek (missing data, or out of the
        # league) still has to be selectable, so fall back to a zero projection.
        pool = [
            gw_proj.get(pid) or PlayerProjection(
                player_id=pid,
                web_name=meta[pid].web_name,
                team_id=meta[pid].team_id,
                team_short=meta[pid].team_short,
                position=meta[pid].position,
                now_cost=meta[pid].now_cost,
                projected_points=0.0,
            )
            for pid in squad_ids
        ]
        xi, bench, cap, vice = _pick_xi_and_captain(pool)
        scores.append(
            score_gameweek(gw, xi, bench, cap, vice, position_of, actuals)
        )

    return BacktestResult(
        season=season,
        strategy="set-and-forget",
        start_gw=start_gw,
        end_gw=end_gw,
        total_points=sum(s.points for s in scores),
        gameweeks=scores,
    )
