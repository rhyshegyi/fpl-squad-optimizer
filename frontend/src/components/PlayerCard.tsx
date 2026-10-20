import { teamColor } from "../teamColors";
import type { Pick, Player } from "../types";

interface Props {
  player: Player | Pick;
  compact?: boolean;
  /** What the points number means here. The Squad page ranks on a 6-gameweek
   *  target while Transfers ranks on the next gameweek, and the two disagree
   *  often enough that an unlabelled number reads as a bug. */
  metric?: "next GW" | "6 GW";
}

function isPick(p: Player | Pick): p is Pick {
  return "is_starter" in p;
}

export function PlayerCard({ player, compact = false, metric }: Props) {
  const captain = isPick(player) && player.is_captain;
  const vice = isPick(player) && player.is_vice;

  const badge = captain ? "C" : vice ? "V" : null;
  const badgeCls = captain
    ? "bg-amber-400 text-slate-900"
    : "bg-slate-300 text-slate-800";

  const color = teamColor(player.team_short);
  const played = isPick(player) && player.actual_points !== undefined;
  const scored = isPick(player) && player.actual_points !== undefined
    ? player.actual_points * (player.counted_as_captain ? 2 : 1)
    : 0;
  const benched = isPick(player) && player.subbed_off;

  return (
    <div
      className={
        "relative flex flex-col items-center rounded-lg bg-slate-900/85 " +
        "backdrop-blur border border-white/10 border-t-[3px] shadow-md " +
        // On a phone five midfielders have ~60px each. The card shrinks to
        // fit rather than letting the line wrap: a wrapped line puts a
        // centre-back below his own penalty box and the formation stops
        // reading as one.
        "min-w-0 flex-1 basis-0 max-w-[104px] px-1 py-1.5 " +
        (benched ? "opacity-50 " : "") +
        (compact ? "sm:px-2 sm:min-w-[92px] sm:flex-none" : "sm:px-2.5 sm:py-2 sm:min-w-[104px] sm:flex-none")
      }
      style={{ borderTopColor: color }}
    >
      {badge && (
        <span
          className={
            "absolute -top-2 -right-2 flex items-center justify-center " +
            "w-5 h-5 rounded-full text-[10px] font-bold shadow " + badgeCls
          }
          title={captain ? "Captain" : "Vice-captain"}
        >
          {badge}
        </span>
      )}
      <div
        className="text-[10px] uppercase tracking-wider font-semibold"
        style={{ color }}
      >
        {player.team_short}
      </div>
      <div className="w-full text-center text-[11px] sm:text-sm font-semibold leading-tight truncate">
        {player.web_name}
      </div>
      {played ? (
        // A recorded week: what he scored is the headline, what we expected
        // sits beneath it. Points are as counted — doubled for whoever wore
        // the armband, which is the vice if the captain did not play.
        <div className="mt-0.5 flex flex-col items-center leading-tight">
          <span className={"text-sm sm:text-base font-bold tabular-nums " +
                           (scored >= 6 ? "text-emerald-300" : "text-slate-100")}>
            {scored}
            {isPick(player) && player.counted_as_captain && (
              <span className="ml-0.5 text-[10px] text-amber-300">×2</span>
            )}
          </span>
          <span className="text-[10px] text-slate-500 tabular-nums"
                title="What the model projected before the deadline">
            proj {player.projected_points.toFixed(1)}
          </span>
        </div>
      ) : (
        <div className="mt-0.5 flex flex-col items-center sm:flex-row sm:gap-2 text-[10px] sm:text-[11px] leading-tight text-slate-300">
          <span>£{(player.now_cost / 10).toFixed(1)}</span>
          <span
            className="text-emerald-400 font-medium"
            title={metric ? `Projected points, ${metric}` : undefined}
          >
            {player.projected_points.toFixed(1)}
            {metric === "6 GW" ? " /gw" : " pts"}
          </span>
        </div>
      )}
      {isPick(player) && player.subbed_off && (
        <div className="text-[9px] uppercase tracking-wider text-red-300/80">didn't play</div>
      )}
      {isPick(player) && player.subbed_on && (
        <div className="text-[9px] uppercase tracking-wider text-emerald-300/90">came on</div>
      )}
    </div>
  );
}
