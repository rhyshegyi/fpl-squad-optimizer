from dataclasses import dataclass

import pulp

from .projections import PlayerProjection

BUDGET = 1000  # £100.0m in tenths
SQUAD_SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3


@dataclass
class Squad:
    players: list[PlayerProjection]
    total_cost: int
    total_points: float

    def by_position(self) -> dict[str, list[PlayerProjection]]:
        out: dict[str, list[PlayerProjection]] = {p: [] for p in SQUAD_SHAPE}
        for p in self.players:
            out[p.position].append(p)
        for pos in out:
            out[pos].sort(key=lambda x: -x.projected_points)
        return out


def optimize(projections: list[PlayerProjection]) -> Squad:
    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {p.player_id: pulp.LpVariable(f"x_{p.player_id}", cat="Binary")
         for p in projections}

    prob += pulp.lpSum(p.projected_points * x[p.player_id] for p in projections)

    prob += pulp.lpSum(x.values()) == sum(SQUAD_SHAPE.values())
    prob += pulp.lpSum(p.now_cost * x[p.player_id] for p in projections) <= BUDGET

    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(
            x[p.player_id] for p in projections if p.position == pos
        ) == n

    teams = {p.team_id for p in projections}
    for team_id in teams:
        prob += pulp.lpSum(
            x[p.player_id] for p in projections if p.team_id == team_id
        ) <= MAX_PER_CLUB

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"solver returned {pulp.LpStatus[status]}")

    chosen = [p for p in projections if x[p.player_id].value() > 0.5]
    return Squad(
        players=chosen,
        total_cost=sum(p.now_cost for p in chosen),
        total_points=round(sum(p.projected_points for p in chosen), 2),
    )
