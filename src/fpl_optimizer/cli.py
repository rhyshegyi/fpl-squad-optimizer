import argparse
import sys

from .entry import fetch_manager_squad
from .export import export_artifacts
from .historical import DEFAULT_SEASONS, ingest_historical
from .ingest import ingest
from .live_history import ingest_live_history
from .model import train
from .optimizer import Pick, Squad, SQUAD_SHAPE, optimize
from .projections import project
from .projections_ml import project_ml
from .staging import stage
from .transfer import TransferPlan, optimize_transfers


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


def _print_transfer_plan(plan: TransferPlan) -> None:
    print(f"\nBank before:   £{plan.bank_before / 10:.1f}m")
    print(f"Bank after:    £{plan.bank_after / 10:.1f}m")
    print(f"Free transfers: {plan.free_transfers}")
    print(f"Transfers made: {plan.transfers_made}"
          f"  (paid hits: {plan.paid_hits}, cost: -{plan.hit_cost} pts)")
    print(f"Net projected:  {plan.projected_points}  (starters + captain - hits)\n")

    if not plan.transfers_in:
        print("No transfers recommended — current squad is already optimal under constraints.")
        return

    print("Suggested transfers")
    outs = sorted(plan.transfers_out, key=lambda p: -p.projected_points)
    ins = sorted(plan.transfers_in, key=lambda p: -p.projected_points)
    for out_p, in_p in zip(outs, ins):
        delta = in_p.projected_points - out_p.projected_points
        cost_delta = (in_p.now_cost - out_p.now_cost) / 10
        sign = "+" if delta >= 0 else ""
        cost_sign = "+" if cost_delta >= 0 else ""
        print(f"  OUT {out_p.web_name:<18} {out_p.team_short:<4} "
              f"£{out_p.now_cost / 10:>4.1f}m   {out_p.projected_points:>5.2f} pts")
        print(f"  IN  {in_p.web_name:<18} {in_p.team_short:<4} "
              f"£{in_p.now_cost / 10:>4.1f}m   {in_p.projected_points:>5.2f} pts    "
              f"({sign}{delta:.2f} pts, {cost_sign}£{cost_delta:.1f}m)")
        print()

    print("New squad")
    _print_squad(plan.new_squad)


def cmd_transfers(args: argparse.Namespace) -> None:
    projector = _pick_projector(args.projector)
    projections = projector()

    if args.entry:
        squad = fetch_manager_squad(args.entry, gw=args.gw)
        print(f"manager: {squad.manager_name} — team: {squad.team_name}")
        print(f"picks from GW{squad.source_gw}, bank £{squad.bank / 10:.1f}m, "
              f"squad value £{squad.squad_value / 10:.1f}m")
        existing_ids = squad.player_ids
        bank = squad.bank
    else:
        if not args.players or not args.bank_tenths:
            raise RuntimeError("must pass --entry OR (--players and --bank-tenths)")
        existing_ids = [int(x) for x in args.players.split(",")]
        bank = args.bank_tenths

    plan = optimize_transfers(
        projections=projections,
        existing_ids=existing_ids,
        bank=bank,
        free_transfers=args.free,
        max_transfers=args.max_transfers,
    )
    _print_transfer_plan(plan)


def cmd_export(args: argparse.Namespace) -> None:
    projector = _pick_projector(args.projector)
    projections = projector()
    squad = optimize(projections)
    paths = export_artifacts(squad, projections, args.projector)
    for name, path in paths.items():
        print(f"{name}: {path}")


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

    ex = sub.add_parser("export", help="write latest squad + projections to data/artifacts/")
    ex.add_argument("--projector", choices=("naive", "ml"), default="ml")
    ex.set_defaults(func=cmd_export)

    tx = sub.add_parser("transfers", help="recommend transfers for an existing squad")
    tx.add_argument("--entry", type=int, help="FPL manager entry ID (auto-pulls picks + bank)")
    tx.add_argument("--gw", type=int, help="which finished GW's picks to use (default: latest finished)")
    tx.add_argument("--players", help="comma-separated 15 player IDs (used when --entry is not given)")
    tx.add_argument("--bank-tenths", type=int, help="bank in tenths of a million (used with --players)")
    tx.add_argument("--free", type=int, default=1, help="free transfers available (default 1)")
    tx.add_argument("--max-transfers", type=int, help="cap on total transfers made")
    tx.add_argument("--projector", choices=("naive", "ml"), default="naive")
    tx.set_defaults(func=cmd_transfers)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
