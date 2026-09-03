from dataclasses import dataclass

import pulp

from .projections import PlayerProjection

BUDGET = 1000  # £100.0m in tenths
SQUAD_SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3

STARTING_XI = 11
STARTER_LIMITS = {
    "GK": (1, 1),
    "DEF": (3, 5),
    "MID": (2, 5),
    "FWD": (1, 3),
}
BENCH_WEIGHT = 0.1  # bench players count at 10% (they only score if a starter doesn't play)


@dataclass
class Pick:
    player: PlayerProjection
    is_starter: bool
    is_captain: bool
    is_vice: bool


@dataclass
class Squad:
    picks: list[Pick]
    total_cost: int
    projected_points: float  # expected points including 2× captain, bench excluded

    def starters(self) -> list[Pick]:
        return [p for p in self.picks if p.is_starter]

    def bench(self) -> list[Pick]:
        return [p for p in self.picks if not p.is_starter]

    def formation(self) -> str:
        counts = {"DEF": 0, "MID": 0, "FWD": 0}
        for p in self.starters():
            if p.player.position in counts:
                counts[p.player.position] += 1
        return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


def optimize(
    projections: list[PlayerProjection],
    budget: int = BUDGET,
    formation: tuple[int, int, int] | None = None,
) -> Squad:
    """Pick the squad, starting XI and captain in one solve.

    `formation` pins the starting XI to an exact (DEF, MID, FWD) shape. Left
    as None the LP chooses freely within FPL's legal bounds, which is what you
    normally want — pinning it is for comparing what a given shape costs you.
    """
    if formation is not None:
        defenders, midfielders, forwards = formation
        if 1 + defenders + midfielders + forwards != STARTING_XI:
            raise ValueError(f"formation {formation} plus a keeper isn't {STARTING_XI} players")
        for pos, count in (("DEF", defenders), ("MID", midfielders), ("FWD", forwards)):
            lo, hi = STARTER_LIMITS[pos]
            if not (lo <= count <= hi):
                raise ValueError(f"{count} at {pos} is outside FPL's {lo}-{hi}")

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)

    ids = [p.player_id for p in projections]
    by_id = {p.player_id: p for p in projections}

    squad = {i: pulp.LpVariable(f"squad_{i}", cat="Binary") for i in ids}
    start = {i: pulp.LpVariable(f"start_{i}", cat="Binary") for i in ids}
    capt = {i: pulp.LpVariable(f"capt_{i}", cat="Binary") for i in ids}

    def proj(i: int) -> float:
        return by_id[i].projected_points

    # Objective: starters (1×) + captain doubles again (+1×) + bench at BENCH_WEIGHT
    prob += pulp.lpSum(
        proj(i) * start[i] + proj(i) * capt[i]
        + BENCH_WEIGHT * proj(i) * (squad[i] - start[i])
        for i in ids
    )

    # 15-man squad, budget, positional shape, per-club cap
    prob += pulp.lpSum(squad.values()) == sum(SQUAD_SHAPE.values())
    prob += pulp.lpSum(by_id[i].now_cost * squad[i] for i in ids) <= budget
    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i].position == pos) == n
    for team_id in {p.team_id for p in projections}:
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i].team_id == team_id) <= MAX_PER_CLUB

    # Starting XI: 11 players, must be in squad, formation limits per position
    for i in ids:
        prob += start[i] <= squad[i]
    prob += pulp.lpSum(start.values()) == STARTING_XI
    pinned = (
        None if formation is None
        else {"DEF": formation[0], "MID": formation[1], "FWD": formation[2], "GK": 1}
    )
    for pos, (lo, hi) in STARTER_LIMITS.items():
        starters_pos = pulp.lpSum(start[i] for i in ids if by_id[i].position == pos)
        if pinned is not None:
            prob += starters_pos == pinned[pos]
        else:
            prob += starters_pos >= lo
            prob += starters_pos <= hi

    # Captain: exactly one, must be a starter
    prob += pulp.lpSum(capt.values()) == 1
    for i in ids:
        prob += capt[i] <= start[i]

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"solver returned {pulp.LpStatus[status]}")

    chosen_ids = [i for i in ids if squad[i].value() > 0.5]
    starter_ids = {i for i in chosen_ids if start[i].value() > 0.5}
    captain_id = next(i for i in chosen_ids if capt[i].value() > 0.5)

    # Vice-captain: highest-projected starter that isn't the captain
    vice_id = max(
        (i for i in starter_ids if i != captain_id),
        key=lambda i: proj(i),
    )

    picks = [
        Pick(
            player=by_id[i],
            is_starter=i in starter_ids,
            is_captain=(i == captain_id),
            is_vice=(i == vice_id),
        )
        for i in chosen_ids
    ]

    starter_points = sum(proj(i) for i in starter_ids)
    captain_bonus = proj(captain_id)
    return Squad(
        picks=picks,
        total_cost=sum(by_id[i].now_cost for i in chosen_ids),
        projected_points=round(starter_points + captain_bonus, 2),
    )
