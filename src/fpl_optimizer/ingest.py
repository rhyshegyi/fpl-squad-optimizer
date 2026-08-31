import json
from datetime import datetime, timezone

import requests

from .db import connect

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"


def _fetch(url: str) -> dict | list:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def ingest() -> str:
    """Pull bootstrap-static + fixtures into raw tables. Returns fetched_at."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    bootstrap = _fetch(BOOTSTRAP_URL)
    fixtures = _fetch(FIXTURES_URL)

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO raw_bootstrap (fetched_at, payload) VALUES (?, ?)",
            (fetched_at, json.dumps(bootstrap)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO raw_fixtures (fetched_at, payload) VALUES (?, ?)",
            (fetched_at, json.dumps(fixtures)),
        )

    return fetched_at
