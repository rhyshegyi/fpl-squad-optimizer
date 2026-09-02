import { teamColor } from "../teamColors";
import type { Pick, Player } from "../types";

interface Props {
  player: Player | Pick;
  compact?: boolean;
}

function isPick(p: Player | Pick): p is Pick {
  return "is_starter" in p;
}

export function PlayerCard({ player, compact = false }: Props) {
  const captain = isPick(player) && player.is_captain;
  const vice = isPick(player) && player.is_vice;

  const badge = captain ? "C" : vice ? "V" : null;
  const badgeCls = captain
    ? "bg-amber-400 text-slate-900"
    : "bg-slate-300 text-slate-800";

  const color = teamColor(player.team_short);

  return (
    <div
      className={
        "relative flex flex-col items-center rounded-lg bg-slate-900/85 " +
        "backdrop-blur border border-white/10 shadow-md overflow-hidden " +
        (compact ? "px-2 py-1.5 pt-2 min-w-[92px]" : "px-2.5 py-2 pt-2.5 min-w-[104px]")
      }
      style={{ boxShadow: `inset 0 3px 0 0 ${color}` }}
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
      <div className="text-sm font-semibold leading-tight truncate max-w-[100px]">
        {player.web_name}
      </div>
      <div className="mt-0.5 flex gap-2 text-[11px] text-slate-300">
        <span>£{(player.now_cost / 10).toFixed(1)}</span>
        <span className="text-emerald-400 font-medium">
          {player.projected_points.toFixed(1)} pts
        </span>
      </div>
    </div>
  );
}
