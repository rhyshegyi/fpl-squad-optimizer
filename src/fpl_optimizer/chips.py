"""Chip advice: is this a good week to play Triple Captain or Bench Boost?

Deliberately heuristics, not optimised timing. Optimal chip scheduling is a
season-long problem, and three seasons of history contains two wildcards, one
bench boost and one triple captain per season — nowhere near enough to fit or
validate a timing strategy. So these answer the narrower, honest question:
*given the squad you have and this week's fixtures, does this week stand out?*

Both signals are expressed relative to the squad's own starters rather than an
absolute points threshold, because projections are compressed (most starters
land in a narrow band) and a fixed cutoff would be meaningless.

Wildcard and Free Hit are not here on purpose: they're already answered by the
Transfers page's unlimited mode, which shows exactly the squad an unlimited
rebuild would produce.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# A captain worth tripling should stand clear of the rest of your XI, not just
# edge it. 1.5x the median starter is roughly "your standout asset has a
# genuinely soft fixture" rather than "he's marginally the best of a flat set".
TRIPLE_CAPTAIN_RATIO = 1.5

# Bench boost pays out the bench total. It's worth playing when the bench
# approaches what a starter would return, i.e. when the squad has no dead
# weight that week.
BENCH_BOOST_RATIO = 0.75


@dataclass
class ChipAdvice:
    chip: str                 # "triple_captain" | "bench_boost"
    label: str
    recommended: bool
    headline: str
    detail: str
    value: float              # the quantity being judged
    benchmark: float          # what it's being judged against


def _median_starter(starters: list[dict]) -> float:
    values = [float(p["projected_points"]) for p in starters]
    return median(values) if values else 0.0


def triple_captain_advice(picks: list[dict]) -> ChipAdvice:
    starters = [p for p in picks if p.get("is_starter")]
    captain = next((p for p in picks if p.get("is_captain")), None)

    if captain is None or not starters:
        return ChipAdvice(
            chip="triple_captain", label="Triple Captain", recommended=False,
            headline="No captain selected", detail="", value=0.0, benchmark=0.0,
        )

    cap_pts = float(captain["projected_points"])
    baseline = _median_starter(starters)
    threshold = baseline * TRIPLE_CAPTAIN_RATIO
    ratio = cap_pts / baseline if baseline else 0.0
    recommended = cap_pts >= threshold

    if recommended:
        headline = f"{captain['web_name']} stands out this week"
        detail = (
            f"Projected {cap_pts:.1f} pts against a median starter of "
            f"{baseline:.1f} ({ratio:.1f}x). Tripling him gains roughly "
            f"{cap_pts:.1f} extra points on top of the usual double."
        )
    else:
        headline = "No standout captain this week"
        detail = (
            f"{captain['web_name']} projects {cap_pts:.1f} pts against a median "
            f"starter of {baseline:.1f} ({ratio:.1f}x). Worth holding for a week "
            f"where your captain clears {threshold:.1f}, ideally a double gameweek."
        )

    return ChipAdvice(
        chip="triple_captain", label="Triple Captain", recommended=recommended,
        headline=headline, detail=detail, value=round(cap_pts, 2),
        benchmark=round(threshold, 2),
    )


def bench_boost_advice(
    picks: list[dict],
    players_without_fixture: set[int] | None = None,
) -> ChipAdvice:
    starters = [p for p in picks if p.get("is_starter")]
    bench = [p for p in picks if not p.get("is_starter")]
    blanks = players_without_fixture or set()

    if not bench or not starters:
        return ChipAdvice(
            chip="bench_boost", label="Bench Boost", recommended=False,
            headline="Squad incomplete", detail="", value=0.0, benchmark=0.0,
        )

    bench_total = sum(float(p["projected_points"]) for p in bench)
    baseline = _median_starter(starters)
    threshold = baseline * len(bench) * BENCH_BOOST_RATIO

    # A blank anywhere in the fifteen wastes part of the chip outright, so it
    # overrides the points comparison rather than just weighing against it.
    blanking = [p for p in picks if p["player_id"] in blanks]
    if blanking:
        names = ", ".join(p["web_name"] for p in blanking[:3])
        more = f" and {len(blanking) - 3} more" if len(blanking) > 3 else ""
        return ChipAdvice(
            chip="bench_boost", label="Bench Boost", recommended=False,
            headline=f"{len(blanking)} of your 15 have no fixture",
            detail=(
                f"{names}{more} don't play this gameweek, so part of the chip "
                f"would be wasted. Bench Boost is best in a week where all "
                f"fifteen have a game."
            ),
            value=round(bench_total, 2), benchmark=round(threshold, 2),
        )

    recommended = bench_total >= threshold
    if recommended:
        headline = f"Bench projects {bench_total:.1f} pts"
        detail = (
            f"All fifteen have a fixture and the bench is close to starter "
            f"quality ({bench_total:.1f} against a {threshold:.1f} bar). "
            f"That's roughly what you'd gain by playing it now."
        )
    else:
        headline = "Bench is too weak this week"
        detail = (
            f"The four substitutes project {bench_total:.1f} pts against a "
            f"{threshold:.1f} bar. Worth waiting for a week where the bench is "
            f"stronger, or a double gameweek."
        )

    return ChipAdvice(
        chip="bench_boost", label="Bench Boost", recommended=recommended,
        headline=headline, detail=detail, value=round(bench_total, 2),
        benchmark=round(threshold, 2),
    )


def chip_advice(
    picks: list[dict],
    players_without_fixture: set[int] | None = None,
) -> list[dict]:
    """Advice for the chips this tool can reason about, as plain dicts."""
    return [
        vars(triple_captain_advice(picks)),
        vars(bench_boost_advice(picks, players_without_fixture)),
    ]
