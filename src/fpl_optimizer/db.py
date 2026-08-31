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
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
