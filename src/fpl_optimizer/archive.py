"""Keep our own copy of every completed gameweek, so the season survives us.

Training data comes from vaastav's CSVs, and the current season only ever
exists as live API data — CI rebuilds its database from scratch every run and
throws it away. That works until the season ends: `historical_seasons()` then
asks vaastav for it, and vaastav is a volunteer scrape that can stop. Their
2026-27 folder has not been touched since GW1 was published on 28 August,
five gameweeks ago. A season we lived through should not be something we have
to ask someone else for.

So each completed gameweek is written to `data/history/<season>/gwNN.csv` and
committed, in the same shape vaastav publishes. `ingest_historical` reads
these in preference to the network, and falls back to vaastav only for seasons
from before this project existed.

Two rules, both learned the hard way elsewhere in this codebase:

* A gameweek is archived only once FPL sets `data_checked` — not merely when
  the last whistle blows. Bonus points move for hours afterwards, and these
  files are written once and never rewritten, so archiving early would freeze
  provisional numbers permanently.
* Team strength is the exception: FPL revises it through the season, so
  `teams.csv` is refreshed on every run while the season is live. The last
  version written is the one a future training run wants.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .db import connect
from .historical import INSERT_COLS, TEAMS_INSERT_COLS, detect_current_season

ARCHIVE_DIR = Path("data") / "history"


def season_dir(season: str) -> Path:
    return ARCHIVE_DIR / season


def gameweek_path(season: str, gw: int) -> Path:
    return season_dir(season) / f"gw{gw:02d}.csv"


def teams_path(season: str) -> Path:
    return season_dir(season) / "teams.csv"


def _confirmed_gameweeks(conn, season: str, is_current: bool) -> list[int]:
    """Gameweeks safe to freeze: confirmed by FPL, and held by us.

    Only the live season gets the `data_checked` test, because the
    `gameweeks` table holds the live season and nothing else — staging
    replaces it wholesale each run. Applying it to a finished season would
    read this season's flags against that season's gameweek numbers, and
    archive whichever rounds happen to be confirmed right now. A season that
    has already ended is final by definition.
    """
    if not is_current:
        return [
            r["gw"] for r in conn.execute(
                "SELECT DISTINCT gw FROM historical_player_gw "
                "WHERE season = ? ORDER BY gw", (season,),
            )
        ]
    return [
        r["id"] for r in conn.execute(
            "SELECT g.id FROM gameweeks g "
            "WHERE COALESCE(g.data_checked, 0) = 1 "
            "  AND EXISTS (SELECT 1 FROM historical_player_gw h "
            "              WHERE h.season = ? AND h.gw = g.id) "
            "ORDER BY g.id", (season,),
        )
    ]


def _write_csv(path: Path, header: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        n = 0
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            n += 1
    return n


def archive_season(season: str | None = None) -> dict[str, object]:
    """Write any confirmed gameweek we have not archived yet, plus teams.csv."""
    current = detect_current_season()
    season = season or current
    written: list[int] = []
    skipped: list[int] = []

    with connect() as conn:
        for gw in _confirmed_gameweeks(conn, season, season == current):
            path = gameweek_path(season, gw)
            if path.exists():
                skipped.append(gw)
                continue
            rows = conn.execute(
                f"SELECT {', '.join(INSERT_COLS)} FROM historical_player_gw "
                f"WHERE season = ? AND gw = ? ORDER BY element", (season, gw),
            )
            _write_csv(path, INSERT_COLS, rows)
            written.append(gw)

        teams = conn.execute(
            f"SELECT {', '.join(TEAMS_INSERT_COLS)} FROM season_teams "
            f"WHERE season = ? ORDER BY id", (season,),
        ).fetchall()

    n_teams = _write_csv(teams_path(season), TEAMS_INSERT_COLS, teams) if teams else 0
    return {
        "season": season,
        "written": written,
        "already_archived": skipped,
        "teams": n_teams,
    }


def archived_seasons() -> list[str]:
    if not ARCHIVE_DIR.exists():
        return []
    return sorted(
        d.name for d in ARCHIVE_DIR.iterdir()
        if d.is_dir() and any(d.glob("gw*.csv"))
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_archived_gameweeks(season: str) -> list[dict[str, str]] | None:
    """Every archived row for a season, or None if we have not archived it."""
    files = sorted(season_dir(season).glob("gw*.csv")) if season_dir(season).exists() else []
    if not files:
        return None
    rows: list[dict[str, str]] = []
    for path in files:
        rows.extend(_read_csv(path))
    return rows


def load_archived_teams(season: str) -> list[dict[str, str]] | None:
    path = teams_path(season)
    return _read_csv(path) if path.exists() else None
