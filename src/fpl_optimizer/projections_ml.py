"""ML-backed projections that plug into the existing PlayerProjection contract."""
from __future__ import annotations

from .db import connect
from .features import build_predict_frame, fixture_slots
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

    # A double gameweek is worth both matches. Each extra slot is a separate
    # frame with that fixture's opponent and home/away, predicted and added;
    # players without a second fixture have no opponent there and contribute
    # nothing, which is what `opponent_team` being null already means.
    for slot in range(1, fixture_slots(gw)):
        extra = build_predict_frame(season, gw, fixture_slot=slot)
        played = extra["opponent_team"].notna().to_numpy()
        yhat = yhat + booster.predict(extra[feat_cols]) * played
        df = df.assign(
            fixtures=df.get("fixtures", 1) + played.astype(int),
            opponent_team=df["opponent_team"].fillna(extra["opponent_team"]),
        )

    df = df.assign(projected_points=yhat)

    out: list[PlayerProjection] = []
    for _, r in df.iterrows():
        raw = float(r["projected_points"])
        if not r.get("opponent_team"):  # no fixture this GW (blank)
            proj = 0.0
        else:
            proj = raw * _availability_multiplier(r.get("status"), r.get("chance_next_round"))
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


def _availability_multiplier(status: str | None, chance: float | None) -> float:
    """Damp the model's raw prediction by expected availability.

    FPL status codes: a=available, d=doubt, i=injured, s=suspended, u=unavailable.
    chance_next_round is 0..100 when the API expresses uncertainty, else NULL.
    """
    if status in ("i", "s", "u"):
        return 0.0
    if chance is not None:
        try:
            return max(0.0, min(1.0, float(chance) / 100.0))
        except (TypeError, ValueError):
            pass
    return 1.0 if status == "a" else 0.0
