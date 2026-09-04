"""Tests for the guard against silently-dead features.

These encode the bug that motivated the module. FPL moved team strength from
a ~975-1370 scale to a 1-5 rating and began serving 0 for attack and defence.
The model kept predicting, the pipeline kept passing, and every fixture
feature was inert for a month: sweeping opponent strength across its entire
live range moved predictions by exactly 0.000000.

The first test below is that bug, in miniature.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from fpl_optimizer import export
from fpl_optimizer.features import TEAM_STRENGTH_COLS, season_team_strength_ranks
from fpl_optimizer.validate import compare_distributions


def levels(findings):
    return [f.level for f in findings]


class TestOutOfRange:
    def test_rescaled_feature_is_an_error(self):
        """The actual regression: training on ~1100, serving 1-5."""
        train = pd.Series([975, 1100, 1200, 1350, 1370])
        live = pd.Series([2, 3, 4, 5, 4, 3, 2])
        findings = compare_distributions("opp_strength_overall", train, live, 7)
        assert levels(findings) == ["error"]
        assert "never seen this scale" in findings[0].message

    def test_columns_dropped_to_zero_upstream_are_an_error(self):
        """Attack/defence arrive as 0 for every team, below any trained value."""
        train = pd.Series([1050.0, 1130.0, 1290.0])
        live = pd.Series([0.0] * 30)
        findings = compare_distributions("opp_strength_attack", train, live, 30)
        assert findings[0].level == "error"

    def test_partial_overlap_warns_rather_than_errors(self):
        train = pd.Series([10.0, 20.0, 30.0])
        live = pd.Series([5.0, 6.0, 7.0, 25.0])
        assert levels(compare_distributions("f", train, live, 4)) == ["warn"]

    def test_values_inside_the_training_range_pass(self):
        """Early-season narrowness is normal and must not trip the check."""
        train = pd.Series(range(0, 38))
        live = pd.Series([0, 1, 2] * 20)
        assert compare_distributions("gw_played", train, live, 60) == []


class TestDegenerateFeatures:
    def test_all_null_live_is_an_error(self):
        train = pd.Series([1.0, 2.0, 3.0])
        live = pd.Series([None, None, None], dtype="object")
        findings = compare_distributions("f", train, live, 3)
        assert findings[0].level == "error"
        assert "null" in findings[0].message

    def test_constant_live_value_warns(self):
        train = pd.Series([1.0, 2.0, 3.0])
        live = pd.Series([2.0] * 40)
        findings = compare_distributions("f", train, live, 40)
        assert levels(findings) == ["warn"]
        assert "carries no signal" in findings[0].message

    def test_constant_is_not_flagged_on_a_tiny_sample(self):
        """Three rows all agreeing is not evidence of a dead feature."""
        train = pd.Series([1.0, 2.0, 3.0])
        live = pd.Series([2.0, 2.0, 2.0])
        assert compare_distributions("f", train, live, 3) == []

    def test_feature_constant_in_training_too_is_not_flagged(self):
        train = pd.Series([1.0] * 100)
        live = pd.Series([1.0] * 100)
        assert compare_distributions("f", train, live, 100) == []


class TestStrengthRanks:
    """Rank normalisation is what makes the scale change survivable."""

    def test_ranks_are_identical_across_differently_scaled_seasons(self):
        old = pd.Series([975.0, 1100.0, 1200.0, 1350.0])
        new = pd.Series([2.0, 3.0, 4.0, 5.0])
        assert list(old.rank(pct=True)) == list(new.rank(pct=True))

    def test_live_ranks_land_inside_the_trained_range(self):
        """The end-to-end property: whatever scale FPL serves, ranks are 0..1."""
        ranks = season_team_strength_ranks()
        if ranks.empty:
            pytest.skip("no staged season_teams")
        for col in (f"{c}_rank" for c in TEAM_STRENGTH_COLS):
            values = ranks[col].dropna()
            assert not values.empty
            assert values.min() > 0.0 and values.max() <= 1.0

    def test_every_season_spans_the_full_rank_range(self):
        """A season whose ranks collapse would mean strength stopped varying."""
        ranks = season_team_strength_ranks()
        if ranks.empty:
            pytest.skip("no staged season_teams")
        for season, group in ranks.groupby("season"):
            spread = group["strength_overall_home_rank"].max() - \
                group["strength_overall_home_rank"].min()
            assert spread > 0.5, f"{season} ranks are degenerate"


class TestPublishGuard:
    """`fpl export` must refuse to serialise a database nobody refreshed.

    A four-day-old local snapshot was exported by hand and committed over the
    pipeline's fresh artifacts, which shipped it to the live site. Nothing in
    the act of exporting knew how old its inputs were.
    """

    def test_a_recent_fetch_publishes(self, monkeypatch):
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(
            export, "_last_fetch", lambda: now - timedelta(minutes=3))
        export.assert_publishable()

    def test_a_stale_fetch_is_refused(self, monkeypatch):
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(
            export, "_last_fetch", lambda: now - timedelta(days=4))
        with pytest.raises(export.StaleSnapshot, match="96h ago"):
            export.assert_publishable()

    def test_an_empty_database_is_refused(self, monkeypatch):
        monkeypatch.setattr(export, "_last_fetch", lambda: None)
        with pytest.raises(export.StaleSnapshot, match="has ever been fetched"):
            export.assert_publishable()

    def test_the_boundary_is_the_configured_age(self, monkeypatch):
        """CI fetches seconds before exporting, so the limit only binds locally."""
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(
            export, "_last_fetch", lambda: now - timedelta(hours=5, minutes=50))
        export.assert_publishable()
        monkeypatch.setattr(
            export, "_last_fetch", lambda: now - timedelta(hours=6, minutes=10))
        with pytest.raises(export.StaleSnapshot):
            export.assert_publishable()
