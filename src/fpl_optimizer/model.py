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


def train(val_season: str | None = None) -> TrainResult:
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
    y_train = train_df[TARGET].astype(float)
    X_val = val_df[feat_cols]
    y_val = val_df[TARGET].astype(float)

    train_ds = lgb.Dataset(X_train, label=y_train, categorical_feature=["position"])
    val_ds = lgb.Dataset(X_val, label=y_val, categorical_feature=["position"], reference=train_ds)

    params = {
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
