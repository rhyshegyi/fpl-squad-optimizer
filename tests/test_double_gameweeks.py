"""Tests for fixtures that are not one-per-team-per-week.

A double gameweek is worth both matches; a blank is worth nothing. Two
mechanisms handle this, and the difference is the shape of the data:

* Historical rows genuinely contain two rows per player for a double, so the
  backtest merges them after projecting (`combine_doubles`).
* The live predict frame is built from the fixture list, so it builds one
  frame per fixture slot and sums. Emitting two rows instead would corrupt the
  rolling features -- the cumulative ones use cumsum, where one NaN poisons
  every value after it.
"""
import pytest

from fpl_optimizer.target import _slot


class TestSlotLookup:
    FIXTURES = {
        (16, 8): [{"is_home": 1, "opp_strength_overall_rank": 0.9},
                  {"is_home": 0, "opp_strength_overall_rank": 0.2}],
        (12, 8): [{"is_home": 0, "opp_strength_overall_rank": 0.5}],
    }

    def test_first_leg_of_a_double(self):
        assert _slot(self.FIXTURES, 16, 8, 0)["opp_strength_overall_rank"] == 0.9

    def test_second_leg_of_a_double(self):
        assert _slot(self.FIXTURES, 16, 8, 1)["opp_strength_overall_rank"] == 0.2

    def test_a_single_fixture_has_no_second_leg(self):
        """Empty means no opponent, which downstream scores as zero."""
        assert _slot(self.FIXTURES, 12, 8, 1) == {}

    def test_a_blank_gameweek_has_no_fixture_at_all(self):
        assert _slot(self.FIXTURES, 99, 8, 0) == {}

    def test_a_missing_team_id_is_not_an_error(self):
        import pandas as pd
        assert _slot(self.FIXTURES, pd.NA, 8, 0) == {}


class TestFixtureSlots:
    def _conn(self, busiest):
        class Cur:
            def fetchone(self):
                return {"n": busiest}

        class Conn:
            def execute(self, *a):
                return Cur()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return lambda: Conn()

    def test_a_normal_week_has_one_slot(self, monkeypatch):
        import fpl_optimizer.features as F
        monkeypatch.setattr(F, "connect", self._conn(1))
        assert F.fixture_slots(6) == 1

    def test_a_double_gameweek_has_two(self, monkeypatch):
        import fpl_optimizer.features as F
        monkeypatch.setattr(F, "connect", self._conn(2))
        assert F.fixture_slots(26) == 2

    def test_a_gameweek_with_no_fixtures_has_none(self, monkeypatch):
        import fpl_optimizer.features as F
        monkeypatch.setattr(F, "connect", self._conn(None))
        assert F.fixture_slots(99) == 0


class TestBacktestMerge:
    """The historical-data path, kept in step with the live one."""

    def test_both_legs_are_counted(self):
        from fpl_optimizer.backtest import combine_doubles
        from fpl_optimizer.projections import PlayerProjection

        def mk(pid, pts):
            return PlayerProjection(player_id=pid, web_name="P", team_id=1,
                                    team_short="T", position="MID",
                                    now_cost=50, projected_points=pts)

        out = combine_doubles([mk(1, 4.0), mk(1, 3.0)])
        assert len(out) == 1 and out[0].projected_points == 7.0
