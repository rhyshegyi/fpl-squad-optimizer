import type { Pick, Position } from "../types";
import { PlayerCard } from "./PlayerCard";

const ROW_ORDER: Position[] = ["GK", "DEF", "MID", "FWD"];

interface Props {
  picks: Pick[];
  metric?: "next GW" | "6 GW";
}

// Real dimensions of one half of a pitch, in metres. The team lines up top to
// bottom — keeper first, strikers last — so the markings are a half-pitch with
// your goal at the top and the halfway line at the bottom, as the FPL app
// draws it. These used to be a side-on pitch: a vertical halfway line through
// the middle of the defence and no goal at all, so nothing said which end the
// keeper was defending.
const HALF_LENGTH = 52.5;
const WIDTH = 68;
const BOX_DEPTH = 16.5;
const BOX_WIDTH = 40.32;
const SIX_DEPTH = 5.5;
const SIX_WIDTH = 18.32;
const GOAL_WIDTH = 7.32;
const SPOT = 11;
const ARC_R = 9.15;

const pctW = (m: number) => `${(m / WIDTH) * 100}%`;
const pctH = (m: number) => `${(m / HALF_LENGTH) * 100}%`;
const LINE = "rgba(255,255,255,0.32)";

/** Lines and boxes stretch with the pitch; arcs and spots are sized off its
 *  width so they stay round however tall the squad makes it. */
function HalfPitchMarkings() {
  // The "D": the part of the 9.15m circle round the penalty spot that falls
  // outside the box. Its chord and height follow from the spot sitting
  // 5.5m inside the box edge.
  const dHeight = ARC_R - (BOX_DEPTH - SPOT);
  const dChord = 2 * Math.sqrt(ARC_R ** 2 - (BOX_DEPTH - SPOT) ** 2);
  const stroke = {
    fill: "none",
    stroke: LINE,
    strokeWidth: 1.5,
    vectorEffect: "non-scaling-stroke" as const,
  };

  return (
    <div className="pointer-events-none absolute inset-3">
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100"
           preserveAspectRatio="none" aria-hidden>
        {/* goal line (top), touchlines, halfway line (bottom) */}
        <rect x="0" y="0" width="100" height="100" {...stroke} />
        <rect x={50 - (BOX_WIDTH / WIDTH) * 50} y="0"
              width={(BOX_WIDTH / WIDTH) * 100}
              height={(BOX_DEPTH / HALF_LENGTH) * 100} {...stroke} />
        <rect x={50 - (SIX_WIDTH / WIDTH) * 50} y="0"
              width={(SIX_WIDTH / WIDTH) * 100}
              height={(SIX_DEPTH / HALF_LENGTH) * 100} {...stroke} />
      </svg>

      {/* the goal, just behind the goal line */}
      <div className="absolute -top-2 left-1/2 h-2 -translate-x-1/2 border border-b-0"
           style={{ width: pctW(GOAL_WIDTH), borderColor: LINE }} />

      {/* penalty spot */}
      <div className="absolute left-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full"
           style={{ top: pctH(SPOT), background: LINE }} />

      {/* the D, hanging off the edge of the box */}
      <div className="absolute left-1/2 -translate-x-1/2"
           style={{ top: pctH(BOX_DEPTH), width: pctW(dChord) }}>
        <svg viewBox={`0 0 ${dChord} ${dHeight}`} className="block w-full" aria-hidden>
          <path d={`M 0 0 A ${ARC_R} ${ARC_R} 0 0 0 ${dChord} 0`} {...stroke} />
        </svg>
      </div>

      {/* centre circle, half of it on our side of the halfway line */}
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2"
           style={{ width: pctW(ARC_R * 2) }}>
        <svg viewBox={`0 0 ${ARC_R * 2} ${ARC_R}`} className="block w-full" aria-hidden>
          <path d={`M 0 ${ARC_R} A ${ARC_R} ${ARC_R} 0 0 1 ${ARC_R * 2} ${ARC_R}`} {...stroke} />
        </svg>
      </div>
      <div className="absolute bottom-0 left-1/2 h-1 w-1 -translate-x-1/2 translate-y-1/2 rounded-full"
           style={{ background: LINE }} />
    </div>
  );
}

export function Pitch({ picks, metric }: Props) {
  const starters = picks.filter((p) => p.is_starter);
  // Keeper first, as FPL shows it. The outfield three keep their order, which
  // is the priority auto-subs are made in.
  const bench = picks
    .filter((p) => !p.is_starter)
    .sort((a, b) => Number(b.position === "GK") - Number(a.position === "GK"));

  const byRow: Record<Position, Pick[]> = { GK: [], DEF: [], MID: [], FWD: [] };
  for (const p of starters) byRow[p.position].push(p);
  for (const row of Object.values(byRow)) {
    row.sort((a, b) => b.projected_points - a.projected_points);
  }

  return (
    <div className="space-y-6">
      <div
        className="relative rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
        style={{
          background:
            "repeating-linear-gradient(0deg, #0f7a3a 0 60px, #0b5e2c 60px 120px)",
        }}
      >
        <HalfPitchMarkings />

        <div className="relative flex flex-col justify-between gap-6 px-3 sm:px-6 py-8 min-h-[440px] sm:min-h-[520px]">
          {ROW_ORDER.map((row) => (
            <div
              key={row}
              className="flex justify-center gap-1.5 sm:gap-3"
            >
              {byRow[row].map((p) => (
                <PlayerCard key={p.player_id} player={p} metric={metric} />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">
          Bench
        </div>
        <div className="flex gap-3 flex-wrap rounded-xl bg-slate-900/60 border border-white/10 px-4 py-3">
          {bench.map((p) => (
            <PlayerCard key={p.player_id} player={p} compact metric={metric} />
          ))}
        </div>
      </div>
    </div>
  );
}
