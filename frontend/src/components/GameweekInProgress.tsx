import type { ReactNode } from "react";
import type { GameweekProgress } from "../types";

/** Shown between a deadline and the last whistle of that round.
 *
 *  The headline is shared because the fact is the same everywhere; the body
 *  is per-page because the *consequence* differs. On Transfers a locked squad
 *  is an inconvenience. On Squad it is a warning about how much the numbers
 *  will still move: measured on the night GW3 opened, a single played match
 *  changed 4 of the 15 recommended players, because the positional averages
 *  every projection is shrunk toward shift with each new result.
 */
export function GameweekInProgress({
  gw,
  children,
}: {
  gw: GameweekProgress;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-5 py-4">
      <div className="flex items-center gap-2 text-amber-200 font-medium text-sm">
        <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
        {gw.name} is being played — {gw.matches_played} of {gw.matches_total}{" "}
        matches finished
      </div>
      <p className="text-slate-400 text-sm mt-2 max-w-3xl">{children}</p>
    </div>
  );
}
