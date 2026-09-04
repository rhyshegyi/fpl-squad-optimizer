"""Guard against features that are silently dead at predict time.

The model trained happily, the pipeline stayed green, the site rendered, and
every fixture-difficulty feature was inert for a month. FPL had switched
`strength_overall_*` from a ~975-1370 scale to a 1-5 rating and started
serving 0 for attack and defence. The model, trained on the old scale, read
every live fixture as off the bottom of the range and sorted them all into
one leaf: sweeping opponent strength across its entire live range moved
predictions by exactly 0.000000.

Nothing raised. That is the point of this module. A feature that disappears
is indistinguishable from a feature that says "no signal here" unless
something compares the two distributions and complains.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .db import connect
from .features import build_predict_frame, build_training_frame, feature_columns
from .projections_ml import _next_gameweek

SKIP = {"position"}          # categorical; range comparison is meaningless
MIN_ROWS = 20                # below this, "constant" says nothing


@dataclass
class Finding:
    level: str               # "error" | "warn"
    feature: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper():5s}] {self.feature}: {self.message}"


def _describe(series: pd.Series) -> tuple[pd.Series, int]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return values, int(values.nunique())


def compare_distributions(
    feature: str, train: pd.Series, live: pd.Series, n_live_rows: int
) -> list[Finding]:
    """Findings for one feature's live values against its training values.

    Split out from the frame plumbing so the rules can be tested directly —
    the whole point of this module is that its rules are the thing that has
    to be right.
    """
    train_vals, train_uniq = _describe(train)
    live_vals, live_uniq = _describe(live)

    if live_vals.empty:
        return [Finding("error", feature,
                        f"every live value is null ({n_live_rows} rows)")]
    if train_vals.empty:
        return []

    findings: list[Finding] = []
    lo, hi = float(train_vals.min()), float(train_vals.max())
    outside = (live_vals < lo) | (live_vals > hi)

    if outside.all():
        return [Finding(
            "error", feature,
            f"all {len(live_vals)} live values lie outside the training range "
            f"[{lo:g}, {hi:g}] (live spans [{live_vals.min():g}, "
            f"{live_vals.max():g}]) — the model has never seen this scale")]
    if outside.mean() > 0.5:
        findings.append(Finding(
            "warn", feature,
            f"{outside.mean():.0%} of live values fall outside the training "
            f"range [{lo:g}, {hi:g}]"))

    if live_uniq == 1 and train_uniq > 1 and len(live_vals) >= MIN_ROWS:
        findings.append(Finding(
            "warn", feature,
            f"constant at {live_vals.iloc[0]:g} across {len(live_vals)} live "
            f"rows, but varied in training — carries no signal this week"))
    return findings


def check_feature_ranges() -> list[Finding]:
    """Compare live predict-frame features against their training ranges."""
    with connect() as conn:
        gw = _next_gameweek(conn)
        row = conn.execute("SELECT MIN(deadline_time) AS d FROM gameweeks").fetchone()
    if gw is None or row is None or row["d"] is None:
        return [Finding("error", "-", "no staged gameweeks; run `fpl stage`")]
    season = f"{int(row['d'][:4])}-{str(int(row['d'][:4]) + 1)[2:]}"

    train = build_training_frame()
    live = build_predict_frame(season, gw)
    findings: list[Finding] = []

    for col in feature_columns():
        if col in SKIP:
            continue
        if col not in live.columns:
            findings.append(Finding("error", col, "missing from the predict frame"))
            continue

        findings.extend(
            compare_distributions(col, train[col], live[col], len(live))
        )

    return findings


def check_bootstrap_freshness() -> list[Finding]:
    """Flag a bootstrap snapshot taken mid-gameweek.

    `players` season totals and `historical_player_gw` are fetched separately,
    so a snapshot taken between two fixtures leaves them describing different
    numbers of matches. Anything reading both at once then contradicts itself.
    """
    with connect() as conn:
        row = conn.execute("SELECT MIN(deadline_time) AS d FROM gameweeks").fetchone()
        if row is None or row["d"] is None:
            return []
        season = f"{int(row['d'][:4])}-{str(int(row['d'][:4]) + 1)[2:]}"
        mismatched = conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "  SELECT p.id, p.total_points AS boot, SUM(h.total_points) AS gws"
            "  FROM players p JOIN historical_player_gw h ON h.element = p.id"
            "  WHERE h.season = ? GROUP BY p.id HAVING boot != gws"
            ")", (season,),
        ).fetchone()["n"]
        total = conn.execute(
            "SELECT COUNT(DISTINCT element) AS n FROM historical_player_gw WHERE season = ?",
            (season,),
        ).fetchone()["n"]

    if not total or not mismatched:
        return []
    return [Finding(
        "warn", "bootstrap",
        f"{mismatched} of {total} players have season totals that disagree with "
        f"their per-gameweek rows — the snapshot was taken mid-gameweek")]


def run_checks() -> list[Finding]:
    return check_feature_ranges() + check_bootstrap_freshness()
