import json

from .db import connect

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def stage() -> dict[str, int]:
    """Normalize the latest raw payloads into typed tables. Returns row counts."""
    with connect() as conn:
        bootstrap_row = conn.execute(
            "SELECT payload FROM raw_bootstrap ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        fixtures_row = conn.execute(
            "SELECT payload FROM raw_fixtures ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()

        if bootstrap_row is None or fixtures_row is None:
            raise RuntimeError("no raw payloads found — run ingest first")

        bootstrap = json.loads(bootstrap_row["payload"])
        fixtures = json.loads(fixtures_row["payload"])

        conn.execute("DELETE FROM teams")
        conn.execute("DELETE FROM players")
        conn.execute("DELETE FROM fixtures")
        conn.execute("DELETE FROM gameweeks")

        conn.executemany(
            "INSERT INTO teams (id, name, short_name, strength_overall_home, strength_overall_away) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (t["id"], t["name"], t["short_name"],
                 t["strength_overall_home"], t["strength_overall_away"])
                for t in bootstrap["teams"]
            ],
        )

        conn.executemany(
            "INSERT INTO players "
            "(id, web_name, team_id, position, now_cost, form, points_per_game, "
            " total_points, minutes, selected_by_percent, status, chance_next_round) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    p["id"],
                    p["web_name"],
                    p["team"],
                    POSITION_MAP[p["element_type"]],
                    p["now_cost"],
                    float(p["form"] or 0),
                    float(p["points_per_game"] or 0),
                    p["total_points"],
                    p["minutes"],
                    float(p["selected_by_percent"] or 0),
                    p["status"],
                    p.get("chance_of_playing_next_round"),
                )
                for p in bootstrap["elements"]
            ],
        )

        conn.executemany(
            "INSERT INTO fixtures "
            "(id, event, team_h, team_a, team_h_difficulty, team_a_difficulty, kickoff_time, finished) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f["id"],
                    f["event"],
                    f["team_h"],
                    f["team_a"],
                    f["team_h_difficulty"],
                    f["team_a_difficulty"],
                    f["kickoff_time"],
                    int(f["finished"]),
                )
                for f in fixtures
            ],
        )

        conn.executemany(
            "INSERT INTO gameweeks (id, name, is_current, is_next, finished, deadline_time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    e["id"],
                    e["name"],
                    int(e["is_current"]),
                    int(e["is_next"]),
                    int(e["finished"]),
                    e["deadline_time"],
                )
                for e in bootstrap["events"]
            ],
        )

        return {
            "teams": len(bootstrap["teams"]),
            "players": len(bootstrap["elements"]),
            "fixtures": len(fixtures),
            "gameweeks": len(bootstrap["events"]),
        }
