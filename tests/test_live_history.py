"""Tests for the unplayed-fixture filter.

FPL's `element-summary` returns a history row for a player's *upcoming*
fixture, with minutes 0 and points 0 — shaped identically to a real row where
he was an unused substitute. Writing those made every player look like they
had played a gameweek that had not happened: during GW3, 610 of 652 players
showed three games on file when one match of ten had kicked off.

The cost was not cosmetic. A zero went into `minutes_r3`, the model's single
largest feature at ~40% of gain, for every player at once. Measured on live
data, correcting it moved the mean projection +15.9% and Haaland's +22.0%.
"""
from datetime import datetime, timedelta, timezone

from fpl_optimizer.live_history import _is_played


def entry(fixture=None, kickoff=None):
    e = {}
    if fixture is not None:
        e["fixture"] = fixture
    if kickoff is not None:
        e["kickoff_time"] = kickoff
    return e


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class TestFixtureIdIsAuthoritative:
    def test_a_played_fixture_is_kept(self):
        assert _is_played(entry(fixture=21), {21, 22}) is True

    def test_an_unplayed_fixture_is_dropped(self):
        """The bug: fixture 26 kicks off tomorrow, row already exists."""
        assert _is_played(entry(fixture=26), {21}) is False

    def test_a_zero_minute_row_for_a_played_match_is_still_kept(self):
        """An unused sub is real information and must survive the filter."""
        assert _is_played(entry(fixture=21), {21}) is True

    def test_kickoff_time_does_not_override_a_known_fixture(self):
        """A match that finished hours ago but is not yet flagged stays out.

        Deliberate: the fixture set is built from `finished_provisional`, so
        anything missing from it genuinely has no result yet.
        """
        long_ago = iso(datetime.now(timezone.utc) - timedelta(days=2))
        assert _is_played(entry(fixture=99, kickoff=long_ago), {21}) is False


class TestKickoffFallback:
    """Only used when a row carries no fixture id at all."""

    def test_a_match_that_has_finished_is_kept(self):
        past = iso(datetime.now(timezone.utc) - timedelta(hours=3))
        assert _is_played(entry(kickoff=past), set()) is True

    def test_a_match_still_being_played_is_dropped(self):
        mid = iso(datetime.now(timezone.utc) - timedelta(minutes=45))
        assert _is_played(entry(kickoff=mid), set()) is False

    def test_a_future_match_is_dropped(self):
        soon = iso(datetime.now(timezone.utc) + timedelta(days=1))
        assert _is_played(entry(kickoff=soon), set()) is False

    def test_a_row_with_neither_is_dropped(self):
        assert _is_played(entry(), set()) is False

    def test_an_unparseable_kickoff_is_dropped(self):
        assert _is_played(entry(kickoff="not a date"), set()) is False


class TestFetchRetries:
    """A failed fetch used to be counted and skipped. The archive writes each
    confirmed gameweek once, so a player missing on that one run would be
    missing from the file for good. One did fail locally in October and
    fetched fine seconds later."""

    class Resp:
        def __init__(self, status, history=None):
            self.status_code = status
            self._history = history or []

        def raise_for_status(self):
            import requests
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code}")

        def json(self):
            return {"history": self._history}

    def _patch(self, monkeypatch, responses):
        import fpl_optimizer.live_history as L
        calls = iter(responses)

        def fake_get(*a, **k):
            r = next(calls)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(L.requests, "get", fake_get)
        monkeypatch.setattr(L, "BACKOFF_SECONDS", 0)
        return L

    def test_a_transient_failure_is_retried(self, monkeypatch):
        import requests
        L = self._patch(monkeypatch, [
            requests.ConnectionError("blip"),
            self.Resp(200, [{"round": 1}]),
        ])
        assert L._fetch_history(80) == [{"round": 1}]

    def test_a_server_error_is_retried(self, monkeypatch):
        L = self._patch(monkeypatch, [self.Resp(503), self.Resp(200, [{"round": 2}])])
        assert L._fetch_history(80) == [{"round": 2}]

    def test_persistent_failure_raises_after_retries(self, monkeypatch):
        import pytest, requests
        L = self._patch(monkeypatch, [requests.Timeout("t")] * L_retries())
        with pytest.raises(requests.Timeout):
            L._fetch_history(80)

    def test_a_removed_player_is_empty_not_a_failure(self, monkeypatch):
        """A 404 would otherwise fail every run forever."""
        L = self._patch(monkeypatch, [self.Resp(404)])
        assert L._fetch_history(999) == []


def L_retries():
    from fpl_optimizer.live_history import RETRIES
    return RETRIES
