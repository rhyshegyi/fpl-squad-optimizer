"""ML-backed projections that plug into the existing PlayerProjection contract."""
from __future__ import annotations

from .db import connect
from .features import build_predict_frame
from .live_history import _current_season
from .model import load_model
from .projections import PlayerProjection


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


def project_ml() -> list[PlayerProjection]:
    booster, feat_cols = load_model()

    with connect() as conn:
        season = _current_season(conn)
        gw = _next_gameweek(conn)

    if gw is None:
        raise RuntimeError("no upcoming gameweek in staged data")

    df = build_predict_frame(season, gw)
    if df.empty:
        raise RuntimeError("no players in predict frame — did staging run?")

    yhat = booster.predict(df[feat_cols])
    df = df.assign(projected_points=yhat)

    out: list[PlayerProjection] = []
    for _, r in df.iterrows():
        proj = float(r["projected_points"]) if r["status"] == "a" and r.get("opponent_team") else 0.0
        out.append(PlayerProjection(
            player_id=int(r["element"]),
            web_name=str(r["name"]),
            team_id=int(r["team_id"]),
            team_short=str(r["team"]),
            position=str(r["position"]),
            now_cost=int(r["now_cost"]),
            projected_points=round(max(proj, 0.0), 3),
        ))
    return out
