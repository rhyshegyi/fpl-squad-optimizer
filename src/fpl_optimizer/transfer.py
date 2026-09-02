"""Transfer-mode LP: given an existing squad, bank and free transfers, choose
the new squad + starting XI + captain that maximizes projected points minus
the -4 penalty per transfer over the free allowance."""
from __future__ import annotations

from dataclasses import dataclass

import pulp

from .optimizer import (
    BENCH_WEIGHT,
    MAX_PER_CLUB,
    SQUAD_SHAPE,
    STARTER_LIMITS,
    STARTING_XI,
    Pick,
    Squad,
)
from .projections import PlayerProjection

HIT_COST = 4  # points lost per transfer beyond the free allowance


@dataclass
class TransferPlan:
    old_squad_ids: list[int]
    new_squad: Squad
    transfers_in: list[PlayerProjection]
    transfers_out: list[PlayerProjection]
    transfers_made: int
    free_transfers: int
    paid_hits: int
    hit_cost: int
    projected_points: float   # from the LP objective, includes hit cost
    bank_before: int
    bank_after: int


def optimize_transfers(
    projections: list[PlayerProjection],
    existing_ids: list[int],
    bank: int,
    free_transfers: int = 1,
    max_transfers: int | None = None,
    hit_cost: int = HIT_COST,
) -> TransferPlan:
    if len(existing_ids) != sum(SQUAD_SHAPE.values()):
        raise ValueError(f"existing squad must have {sum(SQUAD_SHAPE.values())} players, got {len(existing_ids)}")

    by_id = {p.player_id: p for p in projections}
    missing = [pid for pid in existing_ids if pid not in by_id]
    if missing:
        raise RuntimeError(f"existing squad has {len(missing)} players not in projections: {missing[:5]}...")

    existing_set = set(existing_ids)
    squad_current_value = sum(by_id[pid].now_cost for pid in existing_ids)
    total_budget = squad_current_value + bank

    prob = pulp.LpProblem("fpl_transfer", pulp.LpMaximize)
    ids = [p.player_id for p in projections]

    squad = {i: pulp.LpVariable(f"squad_{i}", cat="Binary") for i in ids}
    start = {i: pulp.LpVariable(f"start_{i}", cat="Binary") for i in ids}
    capt = {i: pulp.LpVariable(f"capt_{i}", cat="Binary") for i in ids}
    hits = pulp.LpVariable("hits", lowBound=0, cat="Continuous")

    def proj(i: int) -> float:
        return by_id[i].projected_points

    prob += (
        pulp.lpSum(proj(i) * start[i] + proj(i) * capt[i]
                   + BENCH_WEIGHT * proj(i) * (squad[i] - start[i]) for i in ids)
        - hit_cost * hits
    )

    # 15-man squad, cash budget (bank + squad value at current prices)
    prob += pulp.lpSum(squad.values()) == sum(SQUAD_SHAPE.values())
    prob += pulp.lpSum(by_id[i].now_cost * squad[i] for i in ids) <= total_budget
    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i].position == pos) == n
    for team_id in {p.team_id for p in projections}:
        prob += pulp.lpSum(squad[i] for i in ids if by_id[i].team_id == team_id) <= MAX_PER_CLUB

    # Starting XI, formation, captain
    for i in ids:
        prob += start[i] <= squad[i]
        prob += capt[i] <= start[i]
    prob += pulp.lpSum(start.values()) == STARTING_XI
    for pos, (lo, hi) in STARTER_LIMITS.items():
        starters_pos = pulp.lpSum(start[i] for i in ids if by_id[i].position == pos)
        prob += starters_pos >= lo
        prob += starters_pos <= hi
    prob += pulp.lpSum(capt.values()) == 1

    # Transfers = number of existing players NOT in new squad
    transfers = pulp.lpSum((1 - squad[i]) for i in existing_ids)
    if max_transfers is not None:
        prob += transfers <= max_transfers
    prob += hits >= transfers - free_transfers  # hits >= 0 from bound

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"solver returned {pulp.LpStatus[status]}")

    chosen_ids = [i for i in ids if squad[i].value() > 0.5]
    starter_ids = {i for i in chosen_ids if start[i].value() > 0.5}
    captain_id = next(i for i in chosen_ids if capt[i].value() > 0.5)
    vice_id = max((i for i in starter_ids if i != captain_id), key=lambda i: proj(i))

    picks = [
        Pick(
            player=by_id[i],
            is_starter=i in starter_ids,
            is_captain=(i == captain_id),
            is_vice=(i == vice_id),
        )
        for i in chosen_ids
    ]

    new_ids_set = set(chosen_ids)
    transfers_in = [by_id[i] for i in chosen_ids if i not in existing_set]
    transfers_out = [by_id[i] for i in existing_ids if i not in new_ids_set]
    transfers_made = len(transfers_in)
    paid_hits = max(0, transfers_made - free_transfers)
    total_new_cost = sum(by_id[i].now_cost for i in chosen_ids)

    starter_pts = sum(proj(i) for i in starter_ids)
    captain_bonus = proj(captain_id)
    # Match Squad.projected_points semantics: starters + captain double,
    # bench excluded. Hit cost is applied on top.
    projected = starter_pts + captain_bonus - hit_cost * paid_hits

    new_squad = Squad(
        picks=picks,
        total_cost=total_new_cost,
        projected_points=round(starter_pts + captain_bonus, 2),
    )

    return TransferPlan(
        old_squad_ids=list(existing_ids),
        new_squad=new_squad,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        transfers_made=transfers_made,
        free_transfers=free_transfers,
        paid_hits=paid_hits,
        hit_cost=paid_hits * hit_cost,
        projected_points=round(projected, 2),
        bank_before=bank,
        bank_after=total_budget - total_new_cost,
    )
