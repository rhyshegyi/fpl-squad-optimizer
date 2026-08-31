import argparse
import sys

from .historical import DEFAULT_SEASONS, ingest_historical
from .ingest import ingest
from .live_history import ingest_live_history
from .model import train
from .optimizer import Pick, Squad, SQUAD_SHAPE, optimize
from .projections import project
from .projections_ml import project_ml
from .staging import stage


def _pick_projector(name: str):
    if name == "naive":
        return project
    if name == "ml":
        return project_ml
    raise ValueError(f"unknown projector: {name}")


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


def cmd_optimize(args: argparse.Namespace) -> None:
    projector = _pick_projector(args.projector)
    squad = optimize(projector())
    print(f"projector: {args.projector}")
    _print_squad(squad)


def cmd_run(args: argparse.Namespace) -> None:
    print("ingesting...")
    fetched_at = ingest()
    print(f"  fetched_at={fetched_at}")
    print("staging...")
    counts = stage()
    print(f"  {counts}")
    print(f"projecting + optimizing (projector={args.projector})...")
    projector = _pick_projector(args.projector)
    squad = optimize(projector())
    _print_squad(squad)


def cmd_ingest_history(args: argparse.Namespace) -> None:
    seasons = args.seasons or DEFAULT_SEASONS
    print(f"ingesting historical seasons: {seasons}")
    counts = ingest_historical(seasons)
    print(counts)


def cmd_ingest_live_history(_: argparse.Namespace) -> None:
    print("ingesting current-season per-player history (may take a minute)...")
    print(ingest_live_history())


def cmd_train(args: argparse.Namespace) -> None:
    r = train(val_season=args.val_season)
    print(f"train n={r.n_train}, valid n={r.n_valid} (season={r.val_seasons})")
    print(f"model:    RMSE={r.model_rmse:.3f}  MAE={r.model_mae:.3f}")
    print(f"baseline: RMSE={r.baseline_rmse:.3f}  MAE={r.baseline_mae:.3f}")
    print("top features:")
    for name, gain in r.top_features:
        print(f"  {name:<28} gain={gain}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="fpl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="pull FPL API into raw tables").set_defaults(func=cmd_ingest)
    sub.add_parser("stage", help="normalize raw payloads into typed tables").set_defaults(func=cmd_stage)

    opt = sub.add_parser("optimize", help="print optimal 15-man squad")
    opt.add_argument("--projector", choices=("naive", "ml"), default="naive")
    opt.set_defaults(func=cmd_optimize)

    run = sub.add_parser("run", help="ingest + stage + optimize")
    run.add_argument("--projector", choices=("naive", "ml"), default="naive")
    run.set_defaults(func=cmd_run)

    hist = sub.add_parser("ingest-history", help="pull vaastav historical CSVs")
    hist.add_argument("--seasons", nargs="+", help="e.g. --seasons 2022-23 2023-24 2024-25")
    hist.set_defaults(func=cmd_ingest_history)

    lh = sub.add_parser("ingest-live-history", help="pull current-season per-player history")
    lh.set_defaults(func=cmd_ingest_live_history)

    tr = sub.add_parser("train", help="train the ML predictor")
    tr.add_argument("--val-season", help="e.g. 2024-25")
    tr.set_defaults(func=cmd_train)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
