import type { PipelineState } from "../types";

/** How much to trust the numbers on this page, stated plainly.
 *
 *  Three states, in priority order. A round being played matters more than a
 *  timestamp: between a deadline and the last whistle every projection is
 *  provisional, because the results that feed them are still arriving. Elapsed
 *  time cannot express that, and a green tick actively misleads.
 */
function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function FreshnessChip({ state }: { state: PipelineState | null }) {
  if (!state?.last_fetch) return null;

  const health = state.data_health;
  const live = health?.gameweek_in_progress ?? null;
  const missing = health?.players_disagreeing ?? 0;

  let tone: "live" | "stale" | "ok" = "ok";
  if (live) tone = "live";
  else if (missing > 0) tone = "stale";

  const cls = {
    live: "border-amber-500/40 bg-amber-500/10 text-amber-200",
    stale: "border-amber-500/40 bg-amber-500/10 text-amber-200",
    ok: "border-white/10 bg-white/5 text-slate-300",
  }[tone];

  const dot = {
    live: "bg-amber-400 animate-pulse",
    stale: "bg-amber-400",
    ok: "bg-emerald-400",
  }[tone];

  const label = live
    ? `${live.name.replace("Gameweek", "GW")} in progress`
    : tone === "stale"
      ? `${missing} players stale`
      : "Current";

  const detail = live
    ? `${live.matches_played}/${live.matches_total} played`
    : ago(state.last_fetch);

  const title = live
    ? `${live.name} is being played — ${live.matches_played} of ` +
      `${live.matches_total} matches finished. Your squad is locked, and ` +
      `these projections are for the next gameweek built on results so far. ` +
      `They will keep moving until this round ends. Data fetched ` +
      `${ago(state.last_fetch)}.`
    : tone === "stale"
      ? `${missing} of ${health?.players_tracked ?? "?"} players have season ` +
        `totals that disagree with their per-gameweek rows, so at least one ` +
        `result is missing from this snapshot.`
      : `Every match played so far is on file and both data sources agree.`;

  return (
    <div
      className={"hidden md:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs " + cls}
      title={title}
    >
      <span className={"inline-block w-1.5 h-1.5 rounded-full " + dot} />
      <div>
        <div className="uppercase tracking-widest text-[10px] opacity-70">
          Data
        </div>
        <div className="font-medium">
          {label}
          <span className="opacity-60 font-normal"> · {detail}</span>
        </div>
      </div>
    </div>
  );
}
