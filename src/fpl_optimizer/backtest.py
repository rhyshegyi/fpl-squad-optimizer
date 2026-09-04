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
import numpy as np
import pandas as pd

from .features import (
    POSITION_CATEGORIES, STRENGTH_FEATURES, build_training_frame, feature_columns,
)
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
    projector: "Projector | None" = None,
) -> BacktestResult:
    """Pick a squad once, then never transfer — only set the XI each week.

    This is the benchmark that isolates how much the weekly transfer advice
    is actually worth, and it is also the simplest strategy to score, which
    makes it the right thing to validate the engine against first.
    """
    frame = load_season_frame(season)
    if projector is None:
        projector = MLProjector(*train_excluding_season(season))
    actuals = load_actuals(frame)

    opening = projector(frame, start_gw)
    if not opening:
        raise RuntimeError(f"no projections available for {season} GW{start_gw}")

    from .optimizer import optimize
    initial = optimize(opening, budget=budget)
    squad_ids = [pk.player.player_id for pk in initial.picks]
    meta = {pk.player.player_id: pk.player for pk in initial.picks}
    position_of = {pid: pl.position for pid, pl in meta.items()}

    scores: list[GameweekScore] = []
    for gw in range(start_gw, end_gw + 1):
        gw_proj = {p.player_id: p for p in projector(frame, gw)}
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
        strategy=f"set-and-forget[{projector.name}]",
        start_gw=start_gw,
        end_gw=end_gw,
        total_points=sum(s.points for s in scores),
        gameweeks=scores,
    )


# --------------------------------------------------------------------------
# Transfer replay
# --------------------------------------------------------------------------

# FPL let you bank only one spare transfer (so two available) until 2024-25,
# when the cap rose to five. Getting this wrong changes how freely the model
# is allowed to churn the squad.
MAX_BANKED_FREE_TRANSFERS = {"2022-23": 2, "2023-24": 2}
DEFAULT_MAX_BANKED = 5


@dataclass
class TransferLog:
    gw: int
    out_ids: list[int]
    in_ids: list[int]
    hits: int
    bank_after: int
    free_transfers_after: int


def _price_index(frame: pd.DataFrame) -> dict[tuple[int, int], int]:
    """{(element, gw): market price in tenths} — prices drift all season."""
    out: dict[tuple[int, int], int] = {}
    for r in frame.itertuples():
        if not pd.isna(r.value):
            out[(int(r.element), int(r.gw))] = int(r.value)
    return out


def run_with_transfers(
    season: str,
    start_gw: int = 2,
    end_gw: int = 38,
    budget: int = 1000,
    hit_cost: int = 4,
    projector: "Projector | None" = None,
    opening_projector: "Projector | None" = None,
) -> tuple[BacktestResult, list[TransferLog]]:
    """Replay a season taking the transfer the model recommends each week.

    Hits are subtracted from the gameweek they're taken in, matching how FPL
    reports them, so the total is directly comparable to a real season score.

    `opening_projector` picks the initial fifteen and defaults to `projector`.
    They're separable because the benchmark showed the two jobs have different
    winners: the naive rule assembles a far better opening squad, while the ML
    model makes better weekly transfers.
    """
    frame = load_season_frame(season)
    if projector is None:
        projector = MLProjector(*train_excluding_season(season))
    if opening_projector is None:
        opening_projector = projector
    actuals = load_actuals(frame)
    prices = _price_index(frame)
    max_banked = MAX_BANKED_FREE_TRANSFERS.get(season, DEFAULT_MAX_BANKED)

    from .optimizer import optimize
    from .transfer import optimize_transfers, sell_price

    opening = opening_projector(frame, start_gw)
    if not opening:
        raise RuntimeError(f"no projections available for {season} GW{start_gw}")
    initial = optimize(opening, budget=budget)

    squad_ids = [pk.player.player_id for pk in initial.picks]
    meta = {pk.player.player_id: pk.player for pk in initial.picks}
    position_of = {pid: pl.position for pid, pl in meta.items()}
    buy_price = {pid: meta[pid].now_cost for pid in squad_ids}
    bank = budget - sum(buy_price.values())
    free_transfers = 1

    scores: list[GameweekScore] = []
    transfers: list[TransferLog] = []

    for gw in range(start_gw, end_gw + 1):
        gw_proj = {p.player_id: p for p in projector(frame, gw)}

        def as_projection(pid: int) -> PlayerProjection:
            """Squad members with no row this gameweek (blank, or gone from the
            league) still have to be representable, so fall back to their last
            known price and a zero projection."""
            hit = gw_proj.get(pid)
            if hit is not None:
                return hit
            known = meta[pid]
            return PlayerProjection(
                player_id=pid, web_name=known.web_name, team_id=known.team_id,
                team_short=known.team_short, position=known.position,
                now_cost=prices.get((pid, gw), buy_price.get(pid, known.now_cost)),
                projected_points=0.0,
            )

        gw_hits = 0
        if gw > start_gw:
            pool = list(gw_proj.values())
            pool_ids = {p.player_id for p in pool}
            pool += [as_projection(pid) for pid in squad_ids if pid not in pool_ids]

            sells = {
                pid: sell_price(buy_price[pid], prices.get((pid, gw), buy_price[pid]))
                for pid in squad_ids
            }
            plan = optimize_transfers(
                projections=pool,
                existing_ids=squad_ids,
                bank=bank,
                free_transfers=free_transfers,
                hit_cost=hit_cost,
                sell_prices=sells,
            )

            if plan.transfers_made:
                for p in plan.transfers_in:
                    meta[p.player_id] = p
                    position_of[p.player_id] = p.position
                    buy_price[p.player_id] = p.now_cost
                for p in plan.transfers_out:
                    buy_price.pop(p.player_id, None)
                squad_ids = [pk.player.player_id for pk in plan.new_squad.picks]

            bank = plan.bank_after
            gw_hits = plan.hit_cost
            free_transfers = min(
                max_banked,
                max(0, free_transfers - plan.transfers_made) + 1,
            )
            transfers.append(TransferLog(
                gw=gw,
                out_ids=[p.player_id for p in plan.transfers_out],
                in_ids=[p.player_id for p in plan.transfers_in],
                hits=plan.hit_cost,
                bank_after=bank,
                free_transfers_after=free_transfers,
            ))

        xi, bench, cap, vice = _pick_xi_and_captain([as_projection(p) for p in squad_ids])
        score = score_gameweek(gw, xi, bench, cap, vice, position_of, actuals)
        score.points -= gw_hits          # hits land in the week they're taken
        scores.append(score)

    return BacktestResult(
        season=season,
        strategy=(f"transfers[{projector.name}]" if opening_projector is projector
                  else f"transfers[open:{opening_projector.name}+wk:{projector.name}]"),
        start_gw=start_gw,
        end_gw=end_gw,
        total_points=sum(s.points for s in scores),
        gameweeks=scores,
    ), transfers


# --------------------------------------------------------------------------
# Projectors — swappable so strategies can be compared on equal footing
# --------------------------------------------------------------------------

class Projector:
    """Turns one gameweek's feature rows into projections."""
    name = "base"

    def __call__(self, frame: pd.DataFrame, gw: int) -> list[PlayerProjection]:
        raise NotImplementedError


class MLProjector(Projector):
    name = "ml"

    def __init__(self, booster: lgb.Booster, feat: list[str]):
        self.booster, self.feat = booster, feat

    def __call__(self, frame, gw):
        return project_gameweek(frame, self.booster, self.feat, gw)


class NaiveProjector(Projector):
    """Recent form scaled by fixture difficulty — the rule the ML model has
    to justify itself against.

    Historical rows carry no FDR, so difficulty is reconstructed by cutting
    the opponent's within-season strength rank into five buckets, mirroring
    how FPL assigns it. Falls back to a neutral multiplier where strength is
    missing.
    """
    name = "naive"

    FDR_MULTIPLIER = {1: 1.30, 2: 1.15, 3: 1.00, 4: 0.85, 5: 0.70}

    def __call__(self, frame, gw):
        rows = frame[frame["gw"] == gw].copy()
        if rows.empty:
            return []

        strength = rows["opp_strength_overall_rank"]
        if strength.notna().any():
            # Five equal-width buckets over the season's range of opponents
            buckets = pd.cut(strength, bins=5, labels=[1, 2, 3, 4, 5])
        else:
            buckets = pd.Series(3, index=rows.index)

        out: list[PlayerProjection] = []
        for (_, r), b in zip(rows.iterrows(), buckets):
            if pd.isna(r.get("value")) or pd.isna(r.get("position")):
                continue
            form = 0.0 if pd.isna(r.get("total_points_r5")) else float(r["total_points_r5"])
            mult = self.FDR_MULTIPLIER.get(int(b), 1.0) if not pd.isna(b) else 1.0
            out.append(PlayerProjection(
                player_id=int(r["element"]),
                web_name=str(r.get("name") or r["element"]),
                team_id=int(r["team_id"]) if not pd.isna(r.get("team_id")) else 0,
                team_short=str(r.get("team") or ""),
                position=str(r["position"]),
                now_cost=int(r["value"]),
                projected_points=round(max(form * mult, 0.0), 3),
            ))
        return out


# --------------------------------------------------------------------------
# Two-stage model
# --------------------------------------------------------------------------

# Splitting availability from performance. 59% of training rows are players
# who didn't feature, so a single regressor spends its capacity learning
# "will he play?" — the easy question — and barely learns "how well will he
# do?", the one that actually differentiates the players you'd consider.
# Conditioning the second stage on rows where the player started lets it
# learn from performance alone.
#
# Cameos (1-59 minutes) are folded into the availability term as misses. That
# slightly understates bit-part players, who aren't realistic picks anyway.
START_MINUTES = 60

CLASSIFIER_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.9,
    "bagging_freq": 5,
    "min_data_in_leaf": 40,
    "verbose": -1,
}


def train_two_stage_excluding_season(
    exclude: str,
) -> tuple[lgb.Booster, lgb.Booster, list[str]]:
    """Fit P(starts) and E[points | started], holding out one season."""
    df = build_training_frame()
    max_gw = df.groupby("season")["gw"].max()
    complete = sorted(max_gw[max_gw >= 35].index)
    train_seasons = [s for s in complete if s != exclude]
    if not train_seasons:
        raise RuntimeError(f"no complete seasons left after excluding {exclude}")

    feat = feature_columns()
    train_df = df[df["season"].isin(train_seasons)]

    starts = (train_df["minutes"] >= START_MINUTES).astype(int)
    clf = lgb.train(
        CLASSIFIER_PARAMS,
        lgb.Dataset(train_df[feat], label=starts, categorical_feature=["position"]),
        num_boost_round=400,
    )

    started = train_df[train_df["minutes"] >= START_MINUTES]
    reg = lgb.train(
        LGB_PARAMS,
        lgb.Dataset(
            started[feat],
            label=started["total_points"].astype(float),
            categorical_feature=["position"],
        ),
        num_boost_round=400,
    )
    return clf, reg, feat


class TwoStageProjector(Projector):
    """P(starts) x E[points | started]."""
    name = "two-stage"

    def __init__(self, clf: lgb.Booster, reg: lgb.Booster, feat: list[str]):
        self.clf, self.reg, self.feat = clf, reg, feat

    def __call__(self, frame, gw):
        rows = frame[frame["gw"] == gw]
        if rows.empty:
            return []
        rows = rows.copy()
        rows["position"] = pd.Categorical(rows["position"], categories=POSITION_CATEGORIES)

        p_start = self.clf.predict(rows[self.feat])
        pts_if_start = self.reg.predict(rows[self.feat])

        out: list[PlayerProjection] = []
        for (_, r), p, e in zip(rows.iterrows(), p_start, pts_if_start):
            if pd.isna(r.get("value")) or pd.isna(r.get("position")):
                continue
            out.append(PlayerProjection(
                player_id=int(r["element"]),
                web_name=str(r.get("name") or r["element"]),
                team_id=int(r["team_id"]) if not pd.isna(r.get("team_id")) else 0,
                team_short=str(r.get("team") or ""),
                position=str(r["position"]),
                now_cost=int(r["value"]),
                projected_points=round(max(float(p) * float(e), 0.0), 3),
            ))
        return out


# --------------------------------------------------------------------------
# Multi-gameweek horizon
# --------------------------------------------------------------------------

# Fixture context is the only thing that legitimately varies across a horizon
# at decision time: you know who a team plays in three weeks, you do not know
# what form anyone will be in. So future gameweeks reuse the player's current
# form features and swap only these columns.
FIXTURE_COLUMNS = ["is_home", *STRENGTH_FEATURES]


class HorizonProjector(Projector):
    """Value a player over the next N fixtures rather than just the next one.

    The weekly LP was myopic: it transferred for next Saturday and ignored
    that a player might face three of the top six after it. This sums decayed
    projections across a fixture window, which is what actually distinguishes
    a good transfer from a good one-week punt.

    Crucially this introduces no lookahead. Form features are frozen at what
    was known on the decision gameweek; only the fixture columns advance,
    because the fixture list is public in advance.
    """

    def __init__(
        self,
        booster: lgb.Booster,
        feat: list[str],
        horizon: int = 4,
        decay: float = 0.75,
    ):
        self.booster, self.feat = booster, feat
        self.horizon, self.decay = horizon, decay
        self.name = f"horizon{horizon}"

    def __call__(self, frame, gw):
        base = frame[frame["gw"] == gw]
        if base.empty:
            return []
        base = base.copy()
        base["position"] = pd.Categorical(base["position"], categories=POSITION_CATEGORIES)

        # Fixture context for every future gameweek, keyed by (team, gw)
        future = frame[(frame["gw"] > gw) & (frame["gw"] < gw + self.horizon)]
        fixtures: dict[tuple[int, int], dict] = {}
        for r in future.itertuples():
            if pd.isna(r.team_id):
                continue
            key = (int(r.team_id), int(r.gw))
            if key not in fixtures:
                fixtures[key] = {
                    c: getattr(r, c, None) for c in FIXTURE_COLUMNS
                }

        total = self.booster.predict(base[self.feat]).astype(float)
        weight_sum = 1.0

        for step in range(1, self.horizon):
            target_gw = gw + step
            shifted = base.copy()
            # Advance only the fixture columns; form stays as known today
            for col in FIXTURE_COLUMNS:
                if col not in shifted.columns:
                    continue
                shifted[col] = [
                    fixtures.get((int(t), target_gw), {}).get(col)
                    if not pd.isna(t) else None
                    for t in base["team_id"]
                ]
                shifted[col] = pd.to_numeric(shifted[col], errors="coerce")

            has_fixture = shifted["opp_strength_overall_rank"].notna().to_numpy()
            preds = self.booster.predict(shifted[self.feat]).astype(float)
            # A blank gameweek contributes nothing, which is the point of
            # looking ahead in the first place
            preds = np.where(has_fixture, preds, 0.0)

            w = self.decay ** step
            total = total + w * preds
            weight_sum += w

        # Rescale so the number stays on a single-gameweek scale, keeping it
        # comparable with other projectors and with the -4 hit cost.
        total = total / weight_sum

        out: list[PlayerProjection] = []
        for (_, r), p in zip(base.iterrows(), total):
            if pd.isna(r.get("value")) or pd.isna(r.get("position")):
                continue
            out.append(PlayerProjection(
                player_id=int(r["element"]),
                web_name=str(r.get("name") or r["element"]),
                team_id=int(r["team_id"]) if not pd.isna(r.get("team_id")) else 0,
                team_short=str(r.get("team") or ""),
                position=str(r["position"]),
                now_cost=int(r["value"]),
                projected_points=round(max(float(p), 0.0), 3),
            ))
        return out


class BlendProjector(Projector):
    """Season-long quality blended with near-term fixtures.

    Powers the "target squad" view: the squad you're aiming at over the next
    month, not the one you'd field if you could rebuild for Saturday. Those
    are different questions and were previously answered by the same number.

    Two components, both on a points-per-gameweek scale:

    * quality  - season-to-date points per game, shrunk toward the positional
      average so a player with two good games doesn't outrank a proven one.
      This is what keeps the target stable enough to actually aim at.
    * horizon  - the multi-fixture projection, so a good run of fixtures still
      pulls a player in.

    `weight` is the share given to quality. It's a genuine tuning knob and
    three seasons isn't enough to fit it, so it defaults to an even split and
    is documented as a judgement call rather than an optimised value.
    """

    # Games of positional-average evidence mixed in before a player's own
    # record is trusted. Five is roughly where FPL managers stop calling a
    # start "a small sample".
    SHRINKAGE_GAMES = 5

    # Shrinking the value isn't enough on its own — the *weight* has to earn
    # itself too. At GW3 "season quality" is two games, and leaning on that at
    # 70% is leaning on noise. Mirrors target.effective_quality_weight.
    WEIGHT_RAMP_GAMES = 6

    def __init__(
        self,
        booster: lgb.Booster,
        feat: list[str],
        horizon: int = 6,
        weight: float = 0.7,
    ):
        self.horizon_projector = HorizonProjector(booster, feat, horizon=horizon)
        self.weight = weight
        self.name = f"blend(h={horizon},w={weight:g})"

    def __call__(self, frame, gw):
        horizon = {p.player_id: p for p in self.horizon_projector(frame, gw)}
        if not horizon:
            return []

        # Season to date means strictly before this gameweek — no lookahead.
        past = frame[frame["gw"] < gw]
        if past.empty:
            return list(horizon.values())

        played = past[past["minutes"] >= START_MINUTES]
        by_pos_avg = played.groupby("position", observed=True)["total_points"].mean()
        overall_avg = float(played["total_points"].mean()) if len(played) else 2.0

        agg = played.groupby("element").agg(
            pts=("total_points", "sum"), games=("total_points", "size")
        )

        out: list[PlayerProjection] = []
        for pid, p in horizon.items():
            row = agg.loc[pid] if pid in agg.index else None
            prior = float(by_pos_avg.get(p.position, overall_avg))
            if row is None:
                quality = prior
            else:
                k = self.SHRINKAGE_GAMES
                quality = (float(row.pts) + prior * k) / (float(row.games) + k)

            games = float(row.games) if row is not None else 0.0
            w = self.weight * games / (games + self.WEIGHT_RAMP_GAMES) if games > 0 else 0.0
            blended = w * quality + (1 - w) * p.projected_points
            out.append(PlayerProjection(
                player_id=p.player_id, web_name=p.web_name, team_id=p.team_id,
                team_short=p.team_short, position=p.position, now_cost=p.now_cost,
                projected_points=round(max(blended, 0.0), 3),
            ))
        return out
