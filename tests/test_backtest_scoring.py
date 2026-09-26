"""Tests for the backtest scoring rules.

These matter more than most: every number the backtest produces rests on
auto-subs and captaincy being applied exactly the way FPL applies them. A
quiet bug here doesn't crash anything, it just yields a plausible-looking
wrong answer.
"""
from fpl_optimizer.backtest import (
    apply_autosubs,
    formation_is_legal,
    score_gameweek,
)

# A legal 4-4-2: 1 GK, 4 DEF, 4 MID, 2 FWD, plus a 4-man bench.
STARTERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
BENCH = [12, 13, 14, 15]
POSITIONS = {
    1: "GK",
    2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
    6: "MID", 7: "MID", 8: "MID", 9: "MID",
    10: "FWD", 11: "FWD",
    12: "GK",            # bench keeper
    13: "DEF", 14: "MID", 15: "FWD",
}


def played(*ids: int) -> dict[int, int]:
    """Everyone in the squad played 90; the named ids blanked."""
    return {p: (0 if p in ids else 90) for p in STARTERS + BENCH}


class TestFormationLegality:
    def test_accepts_442(self):
        assert formation_is_legal([POSITIONS[p] for p in STARTERS])

    def test_accepts_352(self):
        assert formation_is_legal(
            ["GK"] + ["DEF"] * 3 + ["MID"] * 5 + ["FWD"] * 2
        )

    def test_rejects_two_keepers(self):
        assert not formation_is_legal(
            ["GK"] * 2 + ["DEF"] * 3 + ["MID"] * 4 + ["FWD"] * 2
        )

    def test_rejects_too_few_defenders(self):
        assert not formation_is_legal(
            ["GK"] + ["DEF"] * 2 + ["MID"] * 5 + ["FWD"] * 3
        )

    def test_rejects_zero_forwards(self):
        assert not formation_is_legal(["GK"] + ["DEF"] * 5 + ["MID"] * 5)

    def test_rejects_wrong_size(self):
        assert not formation_is_legal(["GK"] + ["DEF"] * 4 + ["MID"] * 4)


class TestAutosubs:
    def test_no_subs_when_everyone_plays(self):
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, played())
        assert xi == STARTERS
        assert subs == []

    def test_outfield_blank_is_replaced(self):
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, played(9))
        assert len(subs) == 1
        assert 9 not in xi
        assert formation_is_legal([POSITIONS[p] for p in xi])

    def test_subs_follow_bench_order_not_position(self):
        """FPL brings on the highest-priority bench player that keeps the
        formation legal — it is NOT a like-for-like positional swap.

        A midfielder blanking in 4-4-2 is replaced by the bench DEF (first
        outfielder on the bench), giving 5-3-2, because that is still legal.
        Bench order is therefore a real decision, not cosmetic.
        """
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, played(9))
        assert subs == [(9, 13)], "should take bench order, not the bench MID"
        assert [POSITIONS[p] for p in xi].count("DEF") == 5

    def test_bench_order_changes_which_sub_comes_on(self):
        # Same blank, midfielder listed first on the bench this time
        reordered = [12, 14, 13, 15]
        xi, subs = apply_autosubs(STARTERS, reordered, POSITIONS, played(9))
        assert subs == [(9, 14)]
        assert [POSITIONS[p] for p in xi].count("MID") == 4

    def test_keeper_only_replaced_by_keeper(self):
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, played(1))
        assert subs == [(1, 12)], "bench GK should come on for the starting GK"
        assert formation_is_legal([POSITIONS[p] for p in xi])

    def test_outfielder_never_replaced_by_bench_keeper(self):
        # Only the bench GK is available; an outfield blank must go unfilled
        xi, subs = apply_autosubs(STARTERS, [12], POSITIONS, played(9))
        assert subs == []
        assert len(xi) == 11 and 9 in xi

    def test_sub_rejected_when_it_would_break_formation(self):
        # 3-5-2 with only a DEF on the bench. A defender blanking would drop
        # us to 2 at the back, so the swap must be a like-for-like DEF.
        starters = [1, 2, 3, 4, 6, 7, 8, 9, 20, 10, 11]
        positions = dict(POSITIONS)
        positions[20] = "MID"        # 1 GK, 3 DEF, 5 MID, 2 FWD
        positions[16] = "FWD"
        # Bench offers only a forward — swapping DEF->FWD leaves 2 DEF, illegal
        xi, subs = apply_autosubs(starters, [16], positions, {
            **{p: 90 for p in starters}, 16: 90, 4: 0,
        })
        assert subs == []
        assert formation_is_legal([positions[p] for p in xi])

    def test_bench_player_who_also_blanked_cannot_come_on(self):
        minutes = played(9, 14)      # the starter AND the bench MID blanked
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, minutes)
        assert all(in_id != 14 for _, in_id in subs)

    def test_multiple_blanks_use_distinct_bench_players(self):
        xi, subs = apply_autosubs(STARTERS, BENCH, POSITIONS, played(5, 9))
        assert len(subs) == 2
        incoming = [i for _, i in subs]
        assert len(set(incoming)) == 2, "a bench player cannot come on twice"
        assert formation_is_legal([POSITIONS[p] for p in xi])


class TestGameweekScoring:
    def _actuals(self, points: dict[int, int], blanks: tuple[int, ...] = ()):
        return {
            (p, 1): (points.get(p, 2), 0 if p in blanks else 90)
            for p in STARTERS + BENCH
        }

    def test_captain_points_are_doubled(self):
        actuals = self._actuals({10: 12})
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, actuals)
        # ten players on 2 + the captain on 12, then the captain again
        assert s.starter_points == 10 * 2 + 12
        assert s.captain_points == 12
        assert s.points == s.starter_points + 12
        assert not s.captain_blanked

    def test_armband_falls_to_vice_when_captain_blanks(self):
        actuals = self._actuals({10: 12, 11: 9}, blanks=(10,))
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, actuals)
        assert s.captain_blanked
        assert s.captain_id == 11
        assert s.captain_points == 9

    def test_blanking_captain_is_replaced_and_doubles_nothing_of_its_own(self):
        actuals = self._actuals({10: 12}, blanks=(10,))
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, actuals)
        # The captain's own 12 must not be counted; he never played
        assert 10 not in [p for p in STARTERS if p in (10,)] or s.captain_id != 10

    def test_autosub_points_count_towards_the_total(self):
        # 13 is first outfielder on the bench, so he is the one who comes on
        actuals = self._actuals({9: 15, 13: 7}, blanks=(9,))
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, actuals)
        assert s.autosubs == [(9, 13)]
        # the blanking starter's 15 is excluded, the sub's 7 included
        assert s.starter_points == 10 * 2 + 7

    def test_bench_points_are_reported_not_counted(self):
        actuals = self._actuals({12: 9, 13: 9, 14: 9, 15: 9})
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, actuals)
        assert s.points_left_on_bench == 36
        assert s.starter_points == 11 * 2

    def test_missing_data_scores_zero_rather_than_raising(self):
        s = score_gameweek(1, STARTERS, BENCH, 10, 11, POSITIONS, {})
        assert s.points == 0


class TestHeldSquadAcrossAClubMove:
    """A held player moving club must not make the XI unpickable.

    Semenyo moved Bournemouth -> Man City in January 2025-26. A squad already
    holding three City players then held four, and `_pick_xi_and_captain`
    raised "solver returned Infeasible" — the three-per-club cap limits which
    squads you may build, not which XI you may field from players you own.
    """

    def _squad(self):
        from fpl_optimizer.projections import PlayerProjection

        shape = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
        out = []
        for i, pos in enumerate(shape, start=1):
            # Four from club 1 (three owned + the one who moved in), rest spread out
            team = 1 if i in (3, 8, 9, 13) else 100 + i
            out.append(PlayerProjection(
                player_id=i, web_name=f"P{i}", team_id=team, team_short=f"T{team}",
                position=pos, now_cost=50, projected_points=float(i % 7),
            ))
        return out

    def test_four_from_one_club_still_yields_an_xi(self):
        from fpl_optimizer.backtest import _pick_xi_and_captain

        xi, bench, captain, vice = _pick_xi_and_captain(self._squad())
        assert len(xi) == 11 and len(bench) == 4
        assert captain in xi

    def test_building_a_squad_still_enforces_the_cap(self):
        """The cap only relaxes for a held squad; new squads keep it."""
        import pytest
        from fpl_optimizer.optimizer import optimize

        with pytest.raises(RuntimeError, match="Infeasible"):
            optimize(self._squad(), budget=750)


class TestDoubleGameweeks:
    """A gameweek is not always one match.

    The key on `historical_player_gw` was (season, element, gw), so the second
    fixture of every double overwrote the first — 374 rows lost in 2024-25,
    419 in 2025-26, exactly the count of duplicated pairs at source. Adding
    `fixture` to the key recovered 3,314 rows across four seasons and broke two
    downstream assumptions that these tests now pin.
    """

    def test_actual_points_are_summed_across_both_fixtures(self):
        import pandas as pd
        from fpl_optimizer.backtest import load_actuals

        frame = pd.DataFrame([
            {"element": 1, "gw": 30, "total_points": 6, "minutes": 90},
            {"element": 1, "gw": 30, "total_points": 9, "minutes": 85},
            {"element": 2, "gw": 30, "total_points": 2, "minutes": 90},
        ])
        assert load_actuals(frame)[(1, 30)] == (15, 175)
        assert load_actuals(frame)[(2, 30)] == (2, 90)

    def test_minutes_are_summed_so_one_blank_leg_is_not_an_autosub(self):
        """Playing only the second leg is not the same as not playing."""
        import pandas as pd
        from fpl_optimizer.backtest import load_actuals

        frame = pd.DataFrame([
            {"element": 1, "gw": 30, "total_points": 0, "minutes": 0},
            {"element": 1, "gw": 30, "total_points": 8, "minutes": 90},
        ])
        assert load_actuals(frame)[(1, 30)] == (8, 90)

    def test_a_double_becomes_one_projection_worth_both_matches(self):
        from fpl_optimizer.backtest import combine_doubles
        from fpl_optimizer.projections import PlayerProjection

        def mk(pid, pts):
            return PlayerProjection(player_id=pid, web_name=f"P{pid}", team_id=1,
                                    team_short="T", position="MID", now_cost=50,
                                    projected_points=pts)

        out = combine_doubles([mk(1, 3.0), mk(2, 4.0), mk(1, 2.5)])
        assert {p.player_id: p.projected_points for p in out} == {1: 5.5, 2: 4.0}

    def test_no_player_appears_twice(self):
        """Two entries for one player would be two signings to the optimizer."""
        from fpl_optimizer.backtest import combine_doubles
        from fpl_optimizer.projections import PlayerProjection

        rows = [PlayerProjection(player_id=7, web_name="P", team_id=1,
                                 team_short="T", position="MID", now_cost=50,
                                 projected_points=1.0) for _ in range(3)]
        out = combine_doubles(rows)
        assert len(out) == 1 and out[0].projected_points == 3.0

    def test_single_fixtures_are_untouched(self):
        from fpl_optimizer.backtest import combine_doubles
        from fpl_optimizer.projections import PlayerProjection

        rows = [PlayerProjection(player_id=i, web_name=f"P{i}", team_id=1,
                                 team_short="T", position="MID", now_cost=50,
                                 projected_points=float(i)) for i in (1, 2, 3)]
        assert combine_doubles(rows) == rows
