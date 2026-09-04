import type { PipelineState } from "../types";

/** How stale the numbers on this page are, stated plainly.
 *
 *  A timestamp alone doesn't answer "is this current?" — an hour-old fetch
 *  taken between two Saturday fixtures is worse than a day-old one taken
 *  after the round finished. So the amber state keys off results the
 *  snapshot is provably missing, not off elapsed time.
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
  const missing = health?.players_disagreeing ?? 0;
  const stale = missing > 0;

  const cls = stale
    ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
    : "border-white/10 bg-white/5 text-slate-300";

  const title = stale
    ? `${missing} of ${health?.players_tracked ?? "?"} players have season ` +
      `totals that disagree with their per-gameweek rows. The data was ` +
      `fetched mid-round, so at least one match is missing. Projections use ` +
      `the per-gameweek history, which is the fresher of the two.`
    : `Bootstrap and per-gameweek history agree on every player, so this ` +
      `snapshot has every result that had been played when it was taken.`;

  return (
    <div
      className={"hidden md:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs " + cls}
      title={title}
    >
      <span
        className={
          "inline-block w-1.5 h-1.5 rounded-full " +
          (stale ? "bg-amber-400" : "bg-emerald-400")
        }
      />
      <div>
        <div className="uppercase tracking-widest text-[10px] opacity-70">
          Data
        </div>
        <div className="font-medium">
          {stale ? `${missing} players stale` : "Current"}
          <span className="opacity-60 font-normal"> · {ago(state.last_fetch)}</span>
        </div>
      </div>
    </div>
  );
}
