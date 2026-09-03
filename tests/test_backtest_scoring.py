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
