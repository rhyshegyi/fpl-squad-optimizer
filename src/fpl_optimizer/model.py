"""Train and persist a LightGBM next-GW points predictor."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .features import build_training_frame, feature_columns
from .projections import FDR_MULTIPLIER

# One definition, imported by the backtest too. These used to be duplicated
# there: identical by luck rather than by construction, so changing one would
# have left the harness quietly validating a model we do not ship.
LGB_PARAMS = {
    # Poisson, not squared error. FPL points are count-like and 62% zero, and
    # a log link ranks them measurably better: +0.0179 mean per-gameweek
    # Spearman over 147 gameweeks, t=+11.75, better in 81% of them, and better
    # on RMSE too despite that metric favouring the loss it replaced.
    #
    # Not for the reason it was proposed. The pitch was that the model
    # compresses reality -- actual points among players who feature have
    # sd 2.95 against our sd 0.96 -- and that this would widen it. It does
    # not: Poisson's spread is slightly narrower. A conditional mean *should*
    # have less spread than the outcome; that was a normal property of the
    # estimator being read as a defect.
    "objective": "poisson",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.9,
    "bagging_freq": 5,
    "min_data_in_leaf": 40,
    "verbose": -1,
}

# Objectives that model a non-negative, count-like target. FPL points can be
# negative (red cards, own goals), which these cannot represent, so the target
# is clipped for them -- 485 of 113,582 training rows, 0.43%, and not
# something the model could predict anyway.
NON_NEGATIVE_OBJECTIVES = {"poisson", "tweedie", "gamma"}


def params_for(objective: str | None = None, **overrides) -> dict:
    """Training parameters. `objective=None` means whatever we ship."""
    objective = objective or LGB_PARAMS["objective"]
    params = {**LGB_PARAMS, "objective": objective}
    if objective == "tweedie":
        params.setdefault("tweedie_variance_power", 1.3)
    params.update(overrides)
    return params


def prepare_target(y, objective: str | None = None):
    """Clip the target where the objective cannot represent negative points."""
    objective = objective or LGB_PARAMS["objective"]
    return y.clip(lower=0) if objective in NON_NEGATIVE_OBJECTIVES else y


MODEL_PATH = Path("data") / "model.txt"
FEATURES_PATH = Path("data") / "model_features.json"

TARGET = "total_points"


@dataclass
class TrainResult:
    n_train: int
    n_valid: int
    val_seasons: list[str]
    model_rmse: float
    model_mae: float
    baseline_rmse: float
    baseline_mae: float
    top_features: list[tuple[str, int]]


def _naive_baseline(df: pd.DataFrame) -> pd.Series:
    """form × FDR-multiplier baseline. FDR isn't in historical rows, so we use
    a per-season season-avg fixture difficulty of 3 (multiplier 1.0)."""
    form = df["total_points_r5"].fillna(0)
    return form * FDR_MULTIPLIER[3]


def _rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - yhat) ** 2)))


def _mae(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs(y - yhat)))


def train(val_season: str | None = None, objective: str | None = None,
          **param_overrides) -> TrainResult:
    df = build_training_frame()
    # Only seasons with a full slate (>= 35 GWs) are eligible for validation —
    # excludes the mid-flight current season which would otherwise get picked
    # as the latest and give a tiny/misleading sample.
    max_gw_by_season = df.groupby("season")["gw"].max()
    complete_seasons = sorted(max_gw_by_season[max_gw_by_season >= 35].index)
    if len(complete_seasons) < 2:
        raise RuntimeError("need at least two complete historical seasons to train")

    val_season = val_season or complete_seasons[-1]
    train_df = df[(df["season"] != val_season) & (df["season"].isin(complete_seasons))]
    val_df = df[df["season"] == val_season]

    feat_cols = feature_columns()
    X_train = train_df[feat_cols]
    y_train = prepare_target(train_df[TARGET].astype(float), objective)
    X_val = val_df[feat_cols]
    y_val = prepare_target(val_df[TARGET].astype(float), objective)

    train_ds = lgb.Dataset(X_train, label=y_train, categorical_feature=["position"])
    val_ds = lgb.Dataset(X_val, label=y_val, categorical_feature=["position"], reference=train_ds)

    params = params_for(objective, **param_overrides)

    booster = lgb.train(
        params,
        train_ds,
        num_boost_round=2000,
        valid_sets=[val_ds],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
    )

    yhat = booster.predict(X_val, num_iteration=booster.best_iteration)
    y_val_arr = y_val.to_numpy()

    baseline_pred = _naive_baseline(val_df).to_numpy()

    importance = booster.feature_importance(importance_type="gain")
    top = sorted(zip(feat_cols, importance), key=lambda p: -p[1])[:10]

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(MODEL_PATH), num_iteration=booster.best_iteration)
    FEATURES_PATH.write_text(json.dumps(feat_cols))

    return TrainResult(
        n_train=len(train_df),
        n_valid=len(val_df),
        val_seasons=[val_season],
        model_rmse=_rmse(y_val_arr, yhat),
        model_mae=_mae(y_val_arr, yhat),
        baseline_rmse=_rmse(y_val_arr, baseline_pred),
        baseline_mae=_mae(y_val_arr, baseline_pred),
        top_features=[(name, int(gain)) for name, gain in top],
    )


def load_model() -> tuple[lgb.Booster, list[str]]:
    if not MODEL_PATH.exists() or not FEATURES_PATH.exists():
        raise RuntimeError("no trained model — run `fpl train` first")
    booster = lgb.Booster(model_file=str(MODEL_PATH))
    feat_cols = json.loads(FEATURES_PATH.read_text())
    return booster, feat_cols
