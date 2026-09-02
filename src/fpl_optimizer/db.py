import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "fpl.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_bootstrap (
    fetched_at TEXT PRIMARY KEY,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_fixtures (
    fetched_at TEXT PRIMARY KEY,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id                     INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL,
    short_name             TEXT NOT NULL,
    strength_overall_home  INTEGER,
    strength_overall_away  INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    id                   INTEGER PRIMARY KEY,
    web_name             TEXT NOT NULL,
    team_id              INTEGER NOT NULL REFERENCES teams(id),
    position             TEXT NOT NULL,        -- GK/DEF/MID/FWD
    now_cost             INTEGER NOT NULL,     -- tenths of a million
    form                 REAL NOT NULL,
    points_per_game      REAL NOT NULL,
    total_points         INTEGER NOT NULL,
    minutes              INTEGER NOT NULL,
    selected_by_percent  REAL NOT NULL,
    status               TEXT NOT NULL,        -- a/i/s/u/d
    chance_next_round    INTEGER               -- 0-100 or NULL
);

CREATE TABLE IF NOT EXISTS fixtures (
    id                 INTEGER PRIMARY KEY,
    event              INTEGER,               -- gameweek, NULL if unscheduled
    team_h             INTEGER NOT NULL REFERENCES teams(id),
    team_a             INTEGER NOT NULL REFERENCES teams(id),
    team_h_difficulty  INTEGER NOT NULL,
    team_a_difficulty  INTEGER NOT NULL,
    kickoff_time       TEXT,
    finished           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS gameweeks (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    is_current   INTEGER NOT NULL,
    is_next      INTEGER NOT NULL,
    finished     INTEGER NOT NULL,
    deadline_time TEXT
);

-- Per-player per-gameweek training rows sourced from vaastav historical CSVs
-- and the live element-summary endpoint for the current season.
CREATE TABLE IF NOT EXISTS historical_player_gw (
    season                    TEXT NOT NULL,   -- e.g. '2024-25'
    element                   INTEGER NOT NULL,-- player id within that season
    gw                        INTEGER NOT NULL,
    name                      TEXT,
    position                  TEXT,            -- GK/DEF/MID/FWD
    team                      TEXT,            -- full or short name (varies by source)
    team_id                   INTEGER,         -- per-season team id (joins to season_teams)
    opponent_team             INTEGER,
    was_home                  INTEGER,
    kickoff_time              TEXT,
    minutes                   INTEGER,
    total_points              INTEGER,
    goals_scored              INTEGER,
    assists                   INTEGER,
    clean_sheets              INTEGER,
    goals_conceded            INTEGER,
    bonus                     INTEGER,
    bps                       INTEGER,
    influence                 REAL,
    creativity                REAL,
    threat                    REAL,
    ict_index                 REAL,
    expected_goals            REAL,
    expected_assists          REAL,
    expected_goal_involvements REAL,
    expected_goals_conceded    REAL,
    starts                    INTEGER,
    value                     INTEGER,         -- price at time of GW (tenths)
    PRIMARY KEY (season, element, gw)
);

CREATE INDEX IF NOT EXISTS idx_hpg_season_gw
    ON historical_player_gw (season, gw);

CREATE TABLE IF NOT EXISTS season_teams (
    season                 TEXT NOT NULL,
    id                     INTEGER NOT NULL,
    name                   TEXT NOT NULL,
    short_name             TEXT NOT NULL,
    strength                INTEGER,
    strength_overall_home  INTEGER,
    strength_overall_away  INTEGER,
    strength_attack_home   INTEGER,
    strength_attack_away   INTEGER,
    strength_defence_home  INTEGER,
    strength_defence_away  INTEGER,
    PRIMARY KEY (season, id)
);
"""


def ensure_column(conn, table: str, column: str, decl: str) -> None:
    """Idempotently add a column to an existing table (SQLite CREATE IF NOT
    EXISTS doesn't add new columns to pre-existing tables)."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    ensure_column(conn, "historical_player_gw", "team_id", "INTEGER")
    return conn
