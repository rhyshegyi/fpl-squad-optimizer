import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Pitch } from "../components/Pitch";
import { StatusBar } from "../components/StatusBar";
import type { PipelineState, Squad, SquadResponse } from "../types";

const DEFAULT_BUDGET_TENTHS = 1000;
const MIN_BUDGET = 850;
const MAX_BUDGET = 1150;
const STEP = 5;
const DEBOUNCE_MS = 250;

export function SquadPage() {
  const [budget, setBudget] = useState<number>(DEFAULT_BUDGET_TENTHS);
  const [squad, setSquad] = useState<Squad | null>(null);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [meta, setMeta] = useState<{ generatedAt: string | null; source: "cached" | "live" }>({
    generatedAt: null,
    source: "cached",
  });
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load the cached artifact once — cheap default view at £100m.
  useEffect(() => {
    api
      .squad()
      .then((data: SquadResponse) => {
        setSquad(data.squad);
        setPipeline(data.pipeline_state);
        setMeta({ generatedAt: data.generated_at, source: "cached" });
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Re-optimize live whenever the user moves the slider off the default.
  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (budget === DEFAULT_BUDGET_TENTHS && meta.source === "cached") return;

    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true);
      setErr(null);
      try {
        const r = await api.squadOptimize(budget);
        setSquad(r.squad);
        setMeta({ generatedAt: new Date().toISOString(), source: "live" });
      } catch (e) {
        setErr(String(e));
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    };
  }, [budget]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (err && !squad) return <div className="text-red-400">{err}</div>;
  if (!squad) return <div className="text-slate-400">loading…</div>;

  const cost = squad.total_cost / 10;
  const budgetPct = Math.min(100, (squad.total_cost / budget) * 100);
  const budgetM = (budget / 10).toFixed(1);

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

        <div className="w-full sm:w-80">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>
              Budget{" "}
              <span className="text-slate-500">
                (drag to re-optimize · £{budgetM}m)
              </span>
            </span>
            <span>
              £{cost.toFixed(1)}m spent
              {loading && <span className="ml-2 text-emerald-400">…</span>}
            </span>
          </div>
          <input
            type="range"
            min={MIN_BUDGET}
            max={MAX_BUDGET}
            step={STEP}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
          <div className="h-2 rounded-full bg-slate-800 overflow-hidden mt-2">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${budgetPct}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-slate-500">
            <span>£{(MIN_BUDGET / 10).toFixed(0)}m</span>
            <span>£{(DEFAULT_BUDGET_TENTHS / 10).toFixed(0)}m (default)</span>
            <span>£{(MAX_BUDGET / 10).toFixed(0)}m</span>
          </div>
        </div>
      </div>

      {pipeline && meta.generatedAt && (
        <StatusBar
          generatedAt={meta.generatedAt}
          projector="ml"
          pipelineState={pipeline}
        />
      )}

      {meta.source === "live" && (
        <div className="text-xs text-emerald-400/80">
          Live-solved for £{budgetM}m budget · pipeline data still from the last weekly run.
        </div>
      )}

      <Pitch picks={squad.picks} />
    </div>
  );
}
