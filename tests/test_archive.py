"""Tests for our own copy of each completed gameweek.

The archive exists because the live season is only ever live data: CI rebuilds
its database every run and discards it, so once the season ends we would have
to ask vaastav for a season we lived through — and their 2026-27 folder
stopped at GW1 on 28 August.

Two properties carry the whole thing. A gameweek is archived only once FPL has
confirmed it, because these files are written once and never rewritten; and
what comes back out has to be exactly what went in, or next season's training
data is silently wrong.
"""
import csv

import pytest

from fpl_optimizer import archive
from fpl_optimizer.historical import INSERT_COLS, TEAMS_INSERT_COLS


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path / "history")
    monkeypatch.setattr(archive, "detect_current_season", lambda: "2026-27")
    return tmp_path / "history"


class Cur:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


def fake_connect(confirmed=(1, 2), rows_by_gw=None, teams=None):
    """Stand-in for the queries archive_season runs."""
    rows_by_gw = rows_by_gw or {}

    class Conn:
        def execute(self, sql, params=()):
            if "FROM gameweeks" in sql:
                return Cur([{"id": gw} for gw in confirmed])
            if "DISTINCT gw" in sql:                       # a finished season
                return Cur([{"gw": gw} for gw in sorted(rows_by_gw)])
            if "historical_player_gw" in sql:
                return Cur(rows_by_gw.get(params[1], []))
            return Cur(teams or [])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return lambda: Conn()


# Built from the column definitions rather than hand-ordered, so adding a
# column (as `fixture` was, for double gameweeks) cannot silently shift every
# value one place to the right and still typecheck.
def _row(cols, values, default=0):
    return tuple(values.get(c, default) for c in cols)


PLAYER_VALUES = {
    "season": "2026-27", "gw": 1, "fixture": 8, "element": 411,
    "name": "Haaland", "position": "FWD", "team": "MCI", "team_id": 15,
    "opponent_team": 3, "was_home": 1, "kickoff_time": "2026-08-23T13:00:00Z",
    "minutes": 90, "total_points": 2, "bps": 12, "influence": 10.4,
    "creativity": 5.2, "threat": 30.0, "ict_index": 4.6,
    "expected_goals": 0.52, "expected_assists": 0.11,
    "expected_goal_involvements": 0.63, "expected_goals_conceded": 1.2,
    "starts": 1, "value": 155,
}
TEAM_VALUES = {
    "season": "2026-27", "id": 1, "name": "Arsenal", "short_name": "ARS",
    "strength": 4, "strength_overall_home": 4, "strength_overall_away": 5,
}

PLAYER_ROW = _row(INSERT_COLS, PLAYER_VALUES)
TEAM_ROW = _row(TEAMS_INSERT_COLS, TEAM_VALUES)


class TestConfirmationGate:
    def test_confirmed_gameweeks_are_written(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1, 2), rows_by_gw={1: [PLAYER_ROW], 2: [PLAYER_ROW]},
            teams=[TEAM_ROW]))
        result = archive.archive_season("2026-27")
        assert result["written"] == [1, 2]
        assert archive.gameweek_path("2026-27", 1).exists()
        assert archive.teams_path("2026-27").exists()

    def test_an_unconfirmed_gameweek_is_left_alone(self, archive_dir, monkeypatch):
        """Bonus points move for hours after the whistle; these files are
        written once, so archiving early would freeze provisional numbers."""
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW], 2: [PLAYER_ROW]},
            teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        assert archive.gameweek_path("2026-27", 1).exists()
        assert not archive.gameweek_path("2026-27", 2).exists()

    def test_an_archived_gameweek_is_never_rewritten(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW]}, teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        archive.gameweek_path("2026-27", 1).write_text("tampered", encoding="utf-8")

        result = archive.archive_season("2026-27")
        assert result["written"] == [] and result["already_archived"] == [1]
        assert archive.gameweek_path("2026-27", 1).read_text(encoding="utf-8") == "tampered"

    def test_team_strength_is_refreshed_not_frozen(self, archive_dir, monkeypatch):
        """FPL revises strength through the season; the last one is the one
        a future training run wants."""
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW]}, teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        updated = ("2026-27", 1, "Arsenal", "ARS", 5, 5, 5, 0, 0, 0, 0)
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW]}, teams=[updated]))
        archive.archive_season("2026-27")

        with archive.teams_path("2026-27").open(newline="", encoding="utf-8") as fh:
            assert next(csv.DictReader(fh))["strength"] == "5"


class TestFinishedSeasons:
    """A season that has ended is final; only the live one needs the flag.

    The `gameweeks` table holds the live season and nothing else, so testing
    `data_checked` against a past season's gameweek numbers would mirror
    whichever rounds happen to be confirmed right now — GW1-5, not all 38.
    """

    def test_a_past_season_archives_every_gameweek_it_holds(
        self, archive_dir, monkeypatch
    ):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1, 2),                       # live season is only 2 in
            rows_by_gw={g: [PLAYER_ROW] for g in range(1, 39)},
            teams=[TEAM_ROW]))
        result = archive.archive_season("2024-25")
        assert result["written"] == list(range(1, 39))

    def test_the_live_season_still_waits_for_confirmation(
        self, archive_dir, monkeypatch
    ):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1, 2),
            rows_by_gw={g: [PLAYER_ROW] for g in range(1, 39)},
            teams=[TEAM_ROW]))
        result = archive.archive_season("2026-27")
        assert result["written"] == [1, 2]

    def test_a_cancelled_round_leaves_a_gap_rather_than_a_renumber(
        self, archive_dir, monkeypatch
    ):
        """2022-23 has no GW7 — the round FPL cancelled. The gap is real data."""
        held = {g: [PLAYER_ROW] for g in range(1, 39) if g != 7}
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(), rows_by_gw=held, teams=[TEAM_ROW]))
        result = archive.archive_season("2022-23")
        assert 7 not in result["written"]
        assert len(result["written"]) == 37
        assert not archive.gameweek_path("2022-23", 7).exists()


class TestRoundTrip:
    """Fidelity only. These deliberately lower the completeness bar so a
    one-gameweek fixture is readable; TestCompleteness covers the bar itself."""

    @pytest.fixture(autouse=True)
    def _ignore_completeness(self, monkeypatch):
        monkeypatch.setattr(archive, "MIN_COMPLETE_SEASON", 1)

    def test_what_comes_back_is_what_went_in(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW]}, teams=[TEAM_ROW]))
        archive.archive_season("2026-27")

        from fpl_optimizer.historical import _rows_from_archive

        teams, players = _rows_from_archive("2026-27")
        assert players == [PLAYER_ROW]
        assert teams == [TEAM_ROW]

    def test_nulls_survive_as_nulls_not_empty_strings(self, archive_dir, monkeypatch):
        """A missing xG must read back as NULL, not 0 or "" — it would
        otherwise become a real value in a rolling mean."""
        row = list(PLAYER_ROW)
        row[INSERT_COLS.index("expected_goals")] = None
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [tuple(row)]}, teams=[TEAM_ROW]))
        archive.archive_season("2026-27")

        from fpl_optimizer.historical import _rows_from_archive
        _, players = _rows_from_archive("2026-27")
        assert players[0][INSERT_COLS.index("expected_goals")] is None


class TestDiscovery:
    def test_a_season_we_never_archived_reads_as_absent(self, archive_dir):
        assert archive.load_archived_gameweeks("2019-20") is None
        assert archive.archived_seasons() == []

    def test_archived_seasons_are_listed(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW]}, teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        assert archive.archived_seasons() == ["2026-27"]


class TestCompleteness:
    """The window to fix a gap closes when FPL publishes the next season.

    `element-summary` carries per-gameweek rows only for the live season —
    past seasons survive there as one aggregate row each. Anything not
    captured in time is gone from the API for good.
    """

    def test_a_confirmed_but_unarchived_gameweek_is_reported(
        self, archive_dir, monkeypatch
    ):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1, 2, 3), rows_by_gw={g: [PLAYER_ROW] for g in (1, 2, 3)},
            teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        archive.gameweek_path("2026-27", 2).unlink()
        assert archive.archive_gaps("2026-27") == [2]

    def test_a_complete_archive_has_no_gaps(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1, 2), rows_by_gw={1: [PLAYER_ROW], 2: [PLAYER_ROW]},
            teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        assert archive.archive_gaps("2026-27") == []

    def test_an_unconfirmed_gameweek_is_not_a_gap(self, archive_dir, monkeypatch):
        """Waiting on FPL is the design, not a failure."""
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(1,), rows_by_gw={1: [PLAYER_ROW], 2: [PLAYER_ROW]},
            teams=[TEAM_ROW]))
        archive.archive_season("2026-27")
        assert archive.archive_gaps("2026-27") == []

    def test_a_partial_season_is_not_used_as_training_data(
        self, archive_dir, monkeypatch
    ):
        """A third of a season that looks like a whole one is worse than none."""
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(), rows_by_gw={g: [PLAYER_ROW] for g in range(1, 6)},
            teams=[TEAM_ROW]))
        archive.archive_season("2024-25")
        from fpl_optimizer.historical import _rows_from_archive
        assert _rows_from_archive("2024-25") is None

    def test_a_full_season_is_used(self, archive_dir, monkeypatch):
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(), rows_by_gw={g: [PLAYER_ROW] for g in range(1, 39)},
            teams=[TEAM_ROW]))
        archive.archive_season("2024-25")
        from fpl_optimizer.historical import _rows_from_archive
        assert _rows_from_archive("2024-25") is not None

    def test_a_cancelled_round_does_not_count_as_partial(
        self, archive_dir, monkeypatch
    ):
        """2022-23's 37 gameweeks are a complete season, not a broken capture."""
        monkeypatch.setattr(archive, "connect", fake_connect(
            confirmed=(),
            rows_by_gw={g: [PLAYER_ROW] for g in range(1, 39) if g != 7},
            teams=[TEAM_ROW]))
        archive.archive_season("2022-23")
        from fpl_optimizer.historical import _rows_from_archive
        assert _rows_from_archive("2022-23") is not None
