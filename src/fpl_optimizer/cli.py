import argparse
import sys

from .ingest import ingest
from .optimizer import Squad, optimize
from .projections import project
from .staging import stage


def _print_squad(squad: Squad) -> None:
    print(f"\nTotal cost:   £{squad.total_cost / 10:.1f}m")
    print(f"Projected pts: {squad.total_points}\n")
    for pos, players in squad.by_position().items():
        print(f"{pos}")
        for p in players:
            print(f"  {p.web_name:<18} {p.team_short:<4} "
                  f"£{p.now_cost / 10:>4.1f}m   {p.projected_points:>5.2f} pts")
        print()


def cmd_ingest(_: argparse.Namespace) -> None:
    fetched_at = ingest()
    print(f"ingested at {fetched_at}")


def cmd_stage(_: argparse.Namespace) -> None:
    counts = stage()
    print("staged:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_optimize(_: argparse.Namespace) -> None:
    projections = project()
    squad = optimize(projections)
    _print_squad(squad)


def cmd_run(_: argparse.Namespace) -> None:
    print("ingesting...")
    fetched_at = ingest()
    print(f"  fetched_at={fetched_at}")
    print("staging...")
    counts = stage()
    print(f"  {counts}")
    print("projecting + optimizing...")
    squad = optimize(project())
    _print_squad(squad)


def main() -> None:
    parser = argparse.ArgumentParser(prog="fpl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="pull FPL API into raw tables").set_defaults(func=cmd_ingest)
    sub.add_parser("stage", help="normalize raw payloads into typed tables").set_defaults(func=cmd_stage)
    sub.add_parser("optimize", help="print optimal 15-man squad").set_defaults(func=cmd_optimize)
    sub.add_parser("run", help="ingest + stage + optimize").set_defaults(func=cmd_run)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
