import { useEffect, useState } from "react";
import { api } from "../api";
import { Pitch } from "../components/Pitch";
import { StatusBar } from "../components/StatusBar";
import type { SquadResponse } from "../types";

export function SquadPage() {
  const [data, setData] = useState<SquadResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.squad().then(setData).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">{err}</div>;
  if (!data) return <div className="text-slate-400">loading…</div>;

  const { squad } = data;
  const cost = squad.total_cost / 10;
  const budgetPct = Math.min(100, (squad.total_cost / 1000) * 100);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500">
            Recommended squad
          </div>
          <h1 className="text-3xl font-bold mt-1">
            {squad.formation}{" "}
            <span className="text-slate-500 font-normal text-2xl">
              · {squad.projected_points.toFixed(1)} projected pts
            </span>
          </h1>
        </div>
        <div className="w-full sm:w-72">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>Budget</span>
            <span>£{cost.toFixed(1)}m / £100.0m</span>
          </div>
          <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${budgetPct}%` }}
            />
          </div>
        </div>
      </div>

      <StatusBar
        generatedAt={data.generated_at}
        projector={data.projector}
        pipelineState={data.pipeline_state}
      />

      <Pitch picks={squad.picks} />
    </div>
  );
}
