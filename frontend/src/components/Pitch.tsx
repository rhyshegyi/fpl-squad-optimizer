import type { Pick, Position } from "../types";
import { PlayerCard } from "./PlayerCard";

const ROW_ORDER: Position[] = ["GK", "DEF", "MID", "FWD"];

interface Props {
  picks: Pick[];
}

export function Pitch({ picks }: Props) {
  const starters = picks.filter((p) => p.is_starter);
  const bench = picks.filter((p) => !p.is_starter);

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
        {/* pitch markings */}
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute inset-4 border border-white/25 rounded-md" />
          <div className="absolute left-1/2 top-0 bottom-0 w-px bg-white/25 -translate-x-px" />
          <div className="absolute left-1/2 top-1/2 w-24 h-24 -translate-x-12 -translate-y-12 border border-white/25 rounded-full" />
        </div>

        <div className="relative flex flex-col justify-between gap-6 px-6 py-8 min-h-[520px]">
          {ROW_ORDER.map((row) => (
            <div
              key={row}
              className="flex justify-center gap-3 flex-wrap"
            >
              {byRow[row].map((p) => (
                <PlayerCard key={p.player_id} player={p} />
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
            <PlayerCard key={p.player_id} player={p} compact />
          ))}
        </div>
      </div>
    </div>
  );
}
