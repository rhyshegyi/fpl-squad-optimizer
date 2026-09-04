"""Tests for the frozen-recommendation track record.

The value of this record rests entirely on one property: the projections were
written down *before* kickoff and never touched afterwards. If a snapshot can
be rewritten once results are known, the whole thing is worthless — so the
freeze boundary and the never-rewrite rule are what these tests guard.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from fpl_optimizer import tracking


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def snapdir(tmp_path, monkeypatch):
    monkeypatch.setattr(tracking, "SNAPSHOT_DIR", tmp_path / "gameweeks")
    monkeypatch.setattr(tracking, "ACCURACY_PATH", tmp_path / "accuracy.json")
    return tmp_path / "gameweeks"


SQUAD = {
    "formation": "3-5-2",
    "picks": [
        {"player_id": 1, "position": "GK", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 2, "position": "DEF", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 3, "position": "DEF", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 4, "position": "DEF", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 5, "position": "MID", "is_starter": True, "is_captain": True, "is_vice": False},
        {"player_id": 6, "position": "MID", "is_starter": True, "is_captain": False, "is_vice": True},
        {"player_id": 7, "position": "MID", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 8, "position": "MID", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 9, "position": "MID", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 10, "position": "FWD", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 11, "position": "FWD", "is_starter": True, "is_captain": False, "is_vice": False},
        {"player_id": 12, "position": "GK", "is_starter": False, "is_captain": False, "is_vice": False},
        {"player_id": 13, "position": "DEF", "is_starter": False, "is_captain": False, "is_vice": False},
        {"player_id": 14, "position": "MID", "is_starter": False, "is_captain": False, "is_vice": False},
        {"player_id": 15, "position": "FWD", "is_starter": False, "is_captain": False, "is_vice": False},
    ],
}


def write_snapshot(snapdir, gw=4, scored_at=None, projections=None):
    snapdir.mkdir(parents=True, exist_ok=True)
    path = snapdir / f"gw{gw:02d}.json"
    data = {
        "gw": gw,
        "name": f"Gameweek {gw}",
        "deadline": iso(datetime.now(timezone.utc) - timedelta(days=1)),
        "frozen_at": iso(datetime.now(timezone.utc) - timedelta(days=1, hours=1)),
        "scored_at": scored_at,
        "squad": SQUAD,
        "projections": projections if projections is not None else [
            {"player_id": i, "web_name": f"P{i}", "team_short": "ARS",
             "position": "MID", "now_cost": 50, "projected": 4.0}
            for i in range(1, 16)
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return tracking.Snapshot(gw=gw, path=path, data=data)


class TestFreezeBoundary:
    """A snapshot may be rewritten right up to the deadline, never after."""

    def test_an_open_gameweek_is_written(self, snapdir, monkeypatch):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        monkeypatch.setattr(tracking, "connect", _fake_connect(4, iso(future)))
        path = tracking.freeze_gameweek(SQUAD, _projection_rows())
        assert path is not None and path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["gw"] == 4

    def test_a_passed_deadline_is_not_written(self, snapdir, monkeypatch):
        """After the deadline the advice is locked — that is the whole point."""
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        monkeypatch.setattr(tracking, "connect", _fake_connect(4, iso(past)))
        assert tracking.freeze_gameweek(SQUAD, _projection_rows()) is None

    def test_an_already_scored_gameweek_is_never_rewritten(self, snapdir, monkeypatch):
        """Rewriting a scored week would let results leak into the record."""
        write_snapshot(snapdir, gw=4, scored_at=iso(datetime.now(timezone.utc)))
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        monkeypatch.setattr(tracking, "connect", _fake_connect(4, iso(future)))
        assert tracking.freeze_gameweek(SQUAD, _projection_rows()) is None

    def test_no_next_gameweek_is_not_an_error(self, snapdir, monkeypatch):
        monkeypatch.setattr(tracking, "connect", _fake_connect(None, None))
        assert tracking.freeze_gameweek(SQUAD, _projection_rows()) is None


class TestScoring:
    def test_an_incomplete_round_is_not_scored(self, snapdir, monkeypatch):
        """Scoring mid-round would bake in partial results permanently."""
        snap = write_snapshot(snapdir)
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=6, total=10))
        assert tracking.score_snapshot(snap) is False
        assert snap.data.get("scored_at") is None

    def test_a_scored_snapshot_is_not_rescored(self, snapdir):
        snap = write_snapshot(snapdir, scored_at=iso(datetime.now(timezone.utc)))
        assert tracking.score_snapshot(snap) is False

    def test_a_complete_round_scores(self, snapdir, monkeypatch):
        actuals = {i: (2, 90) for i in range(1, 16)}
        actuals[5] = (10, 90)   # captain
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=10, total=10, actuals=actuals, average=50))
        snap = write_snapshot(snapdir)
        assert tracking.score_snapshot(snap) is True

        r = snap.data["result"]
        # 10 starters on 2 + captain on 10 = 30, doubled captain adds 10
        assert r["starter_points"] == 30
        assert r["points"] == 40
        assert r["captain_points"] == 10
        assert r["captain_blanked"] is False
        assert r["fpl_average"] == 50

    def test_accuracy_ignores_players_who_did_not_appear(self, snapdir, monkeypatch):
        """A projection for someone who never played is a selection question."""
        actuals = {i: (2, 90) for i in range(1, 16)}
        actuals[9] = (0, 0)     # did not feature
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=10, total=10, actuals=actuals, average=50))
        snap = write_snapshot(snapdir)
        tracking.score_snapshot(snap)
        assert snap.data["accuracy"]["players_appeared"] == 14

    def test_bias_records_direction_not_just_size(self, snapdir, monkeypatch):
        """Systematic over-projection is a different fault from noise."""
        actuals = {i: (1, 90) for i in range(1, 16)}   # projected 4.0, scored 1
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=10, total=10, actuals=actuals, average=50))
        snap = write_snapshot(snapdir)
        tracking.score_snapshot(snap)
        assert snap.data["accuracy"]["bias"] == pytest.approx(-3.0)
        assert snap.data["accuracy"]["mae"] == pytest.approx(3.0)

    def test_spearman_needs_a_real_sample(self, snapdir, monkeypatch):
        """15 players is not enough to report a correlation from."""
        actuals = {i: (i, 90) for i in range(1, 16)}
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=10, total=10, actuals=actuals, average=50))
        snap = write_snapshot(snapdir)
        tracking.score_snapshot(snap)
        assert snap.data["accuracy"]["spearman"] is None


class TestSummary:
    def test_only_scored_weeks_reach_the_summary(self, snapdir, monkeypatch):
        actuals = {i: (2, 90) for i in range(1, 16)}
        monkeypatch.setattr(tracking, "connect", _fake_connect(
            4, None, played=10, total=10, actuals=actuals, average=50))
        snap = write_snapshot(snapdir, gw=4)
        tracking.score_snapshot(snap)
        write_snapshot(snapdir, gw=5)      # frozen, not played

        s = tracking.build_summary()
        assert s["totals"]["gameweeks_scored"] == 1
        assert [w["gw"] for w in s["gameweeks"]] == [4]
        assert [p["gw"] for p in s["pending"]] == [5]

    def test_empty_is_a_valid_answer(self, snapdir):
        s = tracking.build_summary()
        assert s["totals"]["gameweeks_scored"] == 0
        assert s["gameweeks"] == [] and s["pending"] == []


# --------------------------------------------------------------------------

def _projection_rows():
    return [
        {"player_id": i, "web_name": f"P{i}", "team_short": "ARS",
         "position": "MID", "now_cost": 50, "projected_points": 4.0}
        for i in range(1, 16)
    ]


def _fake_connect(next_gw, deadline, played=0, total=10, actuals=None, average=None):
    """Minimal stand-in for the SQLite rows tracking.py reads."""
    class Cur:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def __iter__(self):
            return iter(self.rows)

    class Conn:
        def execute(self, sql, params=()):
            if "is_next = 1" in sql:
                return Cur([] if next_gw is None else
                           [{"id": next_gw, "name": f"Gameweek {next_gw}",
                             "deadline_time": deadline}])
            if "MIN(deadline_time)" in sql:
                return Cur([{"d": "2026-08-21T17:30:00Z"}])
            if "FROM fixtures WHERE event" in sql:
                return Cur([{"total": total, "played": played}])
            if "historical_player_gw" in sql:
                return Cur([{"element": k, "total_points": v[0], "minutes": v[1]}
                            for k, v in (actuals or {}).items()])
            if "average_entry_score" in sql:
                return Cur([{"average_entry_score": average,
                             "highest_score": 120, "data_checked": 1}])
            return Cur([])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return lambda: Conn()
