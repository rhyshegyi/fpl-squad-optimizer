"""Tests for what the site says about the round being played.

Three states have to come apart cleanly, because they carry different
warnings: a round still being played (squad locked, projections will move), a
round over but with bonus unconfirmed (a few scores can still shift), and a
round genuinely settled.

The awkward case is a postponed fixture. Anchoring on "any round with unplayed
fixtures" would leave the site claiming football was in progress for weeks
after a match was called off.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fpl_optimizer import export


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def conn_for(*, gw=3, deadline_hours_ago=5, total=10, played=0, started=0,
             last_kickoff_hours_ago=1, data_checked=0, name="Gameweek 3"):
    """A stand-in for the two queries `_current_round` runs."""
    now = datetime.now(timezone.utc)

    class Cur:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def execute(self, sql, params=()):
            if "FROM gameweeks" in sql:
                if gw is None:
                    return Cur(None)
                return Cur({"id": gw, "name": name, "data_checked": data_checked,
                            "deadline_time": iso(now - timedelta(hours=deadline_hours_ago))})
            return Cur({
                "total": total, "played": played, "started": started,
                "last_kickoff": (
                    None if last_kickoff_hours_ago is None
                    else iso(now - timedelta(hours=last_kickoff_hours_ago))
                ),
            })

    return Conn()


class TestInProgress:
    def test_a_round_with_matches_to_come_is_in_progress(self):
        r = export._gameweek_in_progress(conn_for(played=1, started=1))
        assert r is not None
        assert r["matches_played"] == 1 and r["matches_total"] == 10

    def test_a_round_before_any_kickoff_is_in_progress(self):
        """Deadline gone, nothing played — squads are locked."""
        assert export._gameweek_in_progress(
            conn_for(played=0, last_kickoff_hours_ago=-2)) is not None

    def test_a_fully_played_round_is_not_in_progress(self):
        assert export._gameweek_in_progress(conn_for(played=10)) is None

    def test_no_round_has_started_yet(self):
        assert export._gameweek_in_progress(conn_for(gw=None)) is None

    def test_a_round_with_no_fixtures_is_not_in_progress(self):
        assert export._gameweek_in_progress(conn_for(total=0)) is None


class TestPostponement:
    """The case that would otherwise jam the banner on indefinitely."""

    def test_a_straggler_long_after_the_last_kickoff_is_treated_as_called_off(self):
        assert export._gameweek_in_progress(
            conn_for(played=9, last_kickoff_hours_ago=200)) is None

    def test_a_straggler_within_the_grace_window_still_counts_as_live(self):
        """A Monday-night finish, or FPL being slow to flip a flag."""
        assert export._gameweek_in_progress(
            conn_for(played=9, last_kickoff_hours_ago=20)) is not None

    def test_the_grace_boundary(self):
        hours = export.POSTPONEMENT_GRACE.total_seconds() / 3600
        assert export._gameweek_in_progress(
            conn_for(played=9, last_kickoff_hours_ago=hours - 1)) is not None
        assert export._gameweek_in_progress(
            conn_for(played=9, last_kickoff_hours_ago=hours + 1)) is None

    def test_a_missing_kickoff_time_does_not_clear_the_round(self):
        """No timestamp is not evidence the match was called off."""
        assert export._gameweek_in_progress(
            conn_for(played=9, last_kickoff_hours_ago=None)) is not None


class TestBonusPending:
    def test_all_played_but_bonus_unconfirmed(self):
        r = export._bonus_pending(conn_for(played=10, data_checked=0))
        assert r is not None and r["id"] == 3

    def test_bonus_confirmed_is_silent(self):
        assert export._bonus_pending(conn_for(played=10, data_checked=1)) is None

    def test_a_round_still_being_played_is_not_a_bonus_problem(self):
        """Mid-round the bigger warning applies; this one would be noise."""
        assert export._bonus_pending(conn_for(played=4, data_checked=0)) is None

    def test_the_two_states_never_fire_together(self):
        for played in (0, 4, 9, 10):
            c = conn_for(played=played, data_checked=0)
            live = export._gameweek_in_progress(c)
            bonus = export._bonus_pending(c)
            assert not (live and bonus), f"both fired at played={played}"


@pytest.mark.parametrize("played,checked,expect", [
    (1, 0, "in_progress"),
    (10, 0, "bonus"),
    (10, 1, "settled"),
])
def test_the_round_moves_through_its_states_in_order(played, checked, expect):
    c = conn_for(played=played, data_checked=checked)
    live = export._gameweek_in_progress(c)
    bonus = export._bonus_pending(c)
    got = "in_progress" if live else "bonus" if bonus else "settled"
    assert got == expect
