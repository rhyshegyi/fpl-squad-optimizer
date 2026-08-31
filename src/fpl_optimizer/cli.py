import argparse
import sys

from .ingest import ingest
from .optimizer import Pick, Squad, SQUAD_SHAPE, optimize
from .projections import project
from .staging import stage


def _fmt_pick(pick: Pick) -> str:
    p = pick.player
    tag = " (C)" if pick.is_captain else " (V)" if pick.is_vice else ""
    return (f"  {p.web_name + tag:<22} {p.team_short:<4} "
            f"£{p.now_cost / 10:>4.1f}m   {p.projected_points:>5.2f} pts")


def _print_squad(squad: Squad) -> None:
    print(f"\nTotal cost:      £{squad.total_cost / 10:.1f}m")
    print(f"Formation:       {squad.formation()}")
    print(f"Projected pts:   {squad.projected_points}  (starters + captain bonus)\n")

    starters_by_pos: dict[str, list[Pick]] = {pos: [] for pos in SQUAD_SHAPE}
    for pick in squad.starters():
        starters_by_pos[pick.player.position].append(pick)
    for picks in starters_by_pos.values():
        picks.sort(key=lambda x: -x.player.projected_points)

    print("Starting XI")
    for pos in SQUAD_SHAPE:
        for pick in starters_by_pos[pos]:
            print(_fmt_pick(pick))
    print()

    print("Bench")
    bench = sorted(squad.bench(), key=lambda x: (x.player.position != "GK",
                                                 -x.player.projected_points))
    for pick in bench:
        print(_fmt_pick(pick))
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
