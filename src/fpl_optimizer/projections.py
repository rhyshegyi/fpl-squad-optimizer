from dataclasses import dataclass

from .db import connect

FDR_MULTIPLIER = {1: 1.30, 2: 1.15, 3: 1.00, 4: 0.85, 5: 0.70}


@dataclass
class PlayerProjection:
    player_id: int
    web_name: str
    team_id: int
    team_short: str
    position: str
    now_cost: int
    projected_points: float


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


def _next_fdr_by_team(conn, gw: int) -> dict[int, float]:
    """Average FDR per team across all fixtures in the given gameweek (handles double GWs)."""
    rows = conn.execute(
        "SELECT team_h AS team, team_h_difficulty AS fdr FROM fixtures WHERE event = ? "
        "UNION ALL "
        "SELECT team_a AS team, team_a_difficulty AS fdr FROM fixtures WHERE event = ?",
        (gw, gw),
    ).fetchall()
    by_team: dict[int, list[float]] = {}
    for r in rows:
        by_team.setdefault(r["team"], []).append(float(r["fdr"]))
    return {t: sum(vals) / len(vals) for t, vals in by_team.items()}


def project() -> list[PlayerProjection]:
    """Naive projection: form × FDR multiplier for the next gameweek.

    Players with no scheduled fixture next GW get 0. Injured/suspended players (status != 'a')
    are excluded from optimization consideration by dropping to 0.
    """
    with connect() as conn:
        gw = _next_gameweek(conn)
        fdr_by_team = _next_fdr_by_team(conn, gw) if gw is not None else {}

        rows = conn.execute(
            "SELECT p.id, p.web_name, p.team_id, p.position, p.now_cost, p.form, "
            "       p.status, p.minutes, t.short_name AS team_short "
            "FROM players p JOIN teams t ON t.id = p.team_id"
        ).fetchall()

        out: list[PlayerProjection] = []
        for r in rows:
            fdr = fdr_by_team.get(r["team_id"])
            if fdr is None or r["status"] != "a":
                proj = 0.0
            else:
                fdr_bucket = max(1, min(5, round(fdr)))
                proj = r["form"] * FDR_MULTIPLIER[fdr_bucket]
                if fdr - round(fdr) != 0:
                    lo, hi = int(fdr), int(fdr) + 1
                    frac = fdr - lo
                    lo_mult = FDR_MULTIPLIER[max(1, min(5, lo))]
                    hi_mult = FDR_MULTIPLIER[max(1, min(5, hi))]
                    proj = r["form"] * (lo_mult * (1 - frac) + hi_mult * frac)

            out.append(PlayerProjection(
                player_id=r["id"],
                web_name=r["web_name"],
                team_id=r["team_id"],
                team_short=r["team_short"],
                position=r["position"],
                now_cost=r["now_cost"],
                projected_points=round(proj, 3),
            ))
        return out
