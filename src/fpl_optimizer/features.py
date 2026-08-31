"""Feature engineering for the next-GW points predictor.

Training rows: one per (season, player, gw) where we want to predict `total_points`
from features derived strictly from the player's prior GWs in the same season
plus the fixture context of the GW being predicted.

Predict rows: one per (season=current, player, next_gw) built the same way, but
using the live current-season history for the rolling features and the
staged `fixtures` + `teams` tables for the target fixture context.
"""
from __future__ import annotations

import pandas as pd

from .db import connect

# Columns used to compute rolling means / sums over prior GWs.
ROLLING_COLS = [
    "minutes", "total_points", "goals_scored", "assists",
    "clean_sheets", "goals_conceded", "bonus", "bps",
    "influence", "creativity", "threat", "ict_index",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "starts",
]

WINDOWS = (3, 5)

# Feature columns produced (used at train + predict time). Position is a
# categorical LightGBM feature; season and gw are for splits only.
POSITION_CATEGORIES = ["GK", "DEF", "MID", "FWD"]


def _load_history(seasons: list[str] | None = None) -> pd.DataFrame:
    with connect() as conn:
        if seasons is None:
            q = "SELECT * FROM historical_player_gw"
            df = pd.read_sql_query(q, conn)
        else:
            placeholders = ",".join("?" * len(seasons))
            q = f"SELECT * FROM historical_player_gw WHERE season IN ({placeholders})"
            df = pd.read_sql_query(q, conn, params=seasons)
    return df.sort_values(["season", "element", "gw"]).reset_index(drop=True)


def _add_rolling(df: pd.DataFrame) -> pd.DataFrame:
    """For each (season, element) add lag-shifted rolling means for ROLLING_COLS."""
    df = df.copy()
    for col in ROLLING_COLS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")
    grouped = df.groupby(["season", "element"], sort=False)
    for w in WINDOWS:
        for col in ROLLING_COLS:
            # shift(1) so the current GW is excluded from its own rolling window.
            df[f"{col}_r{w}"] = (
                grouped[col]
                .transform(lambda s, w=w: s.shift(1).rolling(w, min_periods=1).mean())
            )
    for col in ROLLING_COLS:
        df[f"{col}_cum"] = grouped[col].transform(lambda s: s.shift(1).cumsum())
    df["gw_played"] = grouped.cumcount()  # number of prior GWs on file
    return df


def _fixture_context_train(df: pd.DataFrame) -> pd.DataFrame:
    """was_home + opponent_team are already in the row from vaastav CSV; keep them."""
    df = df.copy()
    df["is_home"] = df["was_home"].fillna(0).astype(int)
    return df


def build_training_frame(seasons: list[str] | None = None) -> pd.DataFrame:
    """One row per (season, player, gw) with features + target `total_points`.

    Drops rows where the player had never played before (no prior signal).
    """
    df = _load_history(seasons)
    df = _add_rolling(df)
    df = _fixture_context_train(df)
    df = df[df["gw_played"] >= 1].copy()
    df["position"] = pd.Categorical(df["position"], categories=POSITION_CATEGORIES)
    return df


def feature_columns() -> list[str]:
    cols: list[str] = ["is_home", "gw_played", "position"]
    for w in WINDOWS:
        cols.extend(f"{c}_r{w}" for c in ROLLING_COLS)
    cols.extend(f"{c}_cum" for c in ROLLING_COLS)
    return cols


def build_predict_frame(current_season: str, target_gw: int) -> pd.DataFrame:
    """One row per active player for the given target GW.

    Uses the player's current-season history for rolling features, and the
    staged fixtures/teams tables for the target-GW fixture context.
    """
    with connect() as conn:
        history = pd.read_sql_query(
            "SELECT * FROM historical_player_gw WHERE season = ?",
            conn, params=[current_season],
        )
        players = pd.read_sql_query(
            "SELECT p.id AS element, p.web_name AS name, p.position, p.team_id, "
            "       p.now_cost AS value, p.status, t.short_name AS team "
            "FROM players p JOIN teams t ON t.id = p.team_id",
            conn,
        )
        fixtures = pd.read_sql_query(
            "SELECT team_h, team_a, team_h_difficulty, team_a_difficulty "
            "FROM fixtures WHERE event = ?",
            conn, params=[target_gw],
        )

    # Append a synthetic row per player representing the target GW.
    stub = players.copy()
    stub["season"] = current_season
    stub["gw"] = target_gw
    stub["team"] = stub["team"]

    synthetic_rows: list[dict] = []
    for _, p in stub.iterrows():
        home_fixture = fixtures[fixtures["team_h"] == p["team_id"]]
        away_fixture = fixtures[fixtures["team_a"] == p["team_id"]]
        if not home_fixture.empty:
            opp = int(home_fixture.iloc[0]["team_a"])
            was_home = 1
        elif not away_fixture.empty:
            opp = int(away_fixture.iloc[0]["team_h"])
            was_home = 0
        else:
            opp = None
            was_home = None
        synthetic_rows.append({
            "season": current_season,
            "element": int(p["element"]),
            "gw": target_gw,
            "name": p["name"],
            "position": p["position"],
            "team": p["team"],
            "opponent_team": opp,
            "was_home": was_home,
            "value": int(p["value"]),
            **{c: None for c in ROLLING_COLS},
        })
    synth = pd.DataFrame(synthetic_rows)

    combined = pd.concat([history, synth], ignore_index=True, sort=False)
    combined = combined.sort_values(["season", "element", "gw"]).reset_index(drop=True)
    combined = _add_rolling(combined)
    combined["is_home"] = combined["was_home"].fillna(0).astype(int)

    predict = combined[(combined["gw"] == target_gw) & (combined["season"] == current_season)].copy()
    # Attach live status/team/now_cost for downstream use.
    predict = predict.merge(
        players[["element", "status", "team_id", "value"]].rename(
            columns={"value": "now_cost"}),
        on="element", how="left", suffixes=("", "_live"),
    )
    predict["position"] = pd.Categorical(predict["position"], categories=POSITION_CATEGORIES)
    return predict
