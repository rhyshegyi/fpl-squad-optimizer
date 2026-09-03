import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Pitch } from "../components/Pitch";
import { StatusBar } from "../components/StatusBar";
import type { PipelineState, Squad, TargetSquadResponse } from "../types";

const DEFAULT_BUDGET_TENTHS = 1000;
const MIN_BUDGET = 850;
const MAX_BUDGET = 1150;
const STEP = 5;
const DEBOUNCE_MS = 250;

export function SquadPage() {
  const [budget, setBudget] = useState<number>(DEFAULT_BUDGET_TENTHS);
  const [squad, setSquad] = useState<Squad | null>(null);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [meta, setMeta] = useState<{ generatedAt: string | null; horizon: number }>({
    generatedAt: null,
    horizon: 6,
  });
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    api
      .squadTarget()
      .then((data: TargetSquadResponse) => {
        setSquad(data.squad);
        setPipeline(data.pipeline_state);
        setMeta({ generatedAt: data.generated_at, horizon: data.horizon });
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Re-solve for a different budget once the user moves the slider.
  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (!touched) return;
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true);
      setErr(null);
      try {
        const r = await api.squadTarget(budget);
        setSquad(r.squad);
      } catch (e) {
        setErr(String(e));
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    };
  }, [budget, touched]);

  if (err && !squad) return <div className="text-red-400">{err}</div>;
  if (!squad) return <div className="text-slate-400">loading…</div>;

  const cost = squad.total_cost / 10;
  const budgetPct = Math.min(100, (squad.total_cost / budget) * 100);
  const budgetM = (budget / 10).toFixed(1);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-xl">
          <div className="text-xs uppercase tracking-widest text-slate-500">
            Target squad
          </div>
          <h1 className="text-3xl font-bold mt-1">
            {squad.formation}{" "}
            <span className="text-slate-500 font-normal text-2xl">
              · {squad.projected_points.toFixed(1)} pts/GW
            </span>
          </h1>
          <p className="text-slate-400 text-sm mt-2">
            The best squad for the money over roughly the next{" "}
            {meta.horizon} gameweeks — what to work towards, not what to
            field on Saturday. It blends season-long quality with upcoming
            fixtures so it stays stable enough to actually aim at.
          </p>
        </div>

        <div className="w-full sm:w-80">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>
              Budget{" "}
              <span className="text-slate-500">(drag · £{budgetM}m)</span>
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
            onChange={(e) => {
              setTouched(true);
              setBudget(Number(e.target.value));
            }}
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
            <span>£{(DEFAULT_BUDGET_TENTHS / 10).toFixed(0)}m</span>
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

      <div className="rounded-lg border border-white/10 bg-slate-900/40 px-4 py-3 text-sm text-slate-400">
        Can't reach this in one week — that's expected.{" "}
        <Link to="/transfers" className="text-emerald-400 hover:underline">
          Transfers
        </Link>{" "}
        shows what you can realistically do with the free transfers you have,
        and{" "}
        <Link to="/projections" className="text-emerald-400 hover:underline">
          Scouting
        </Link>{" "}
        shows why each player is rated where they are.
      </div>

      <Pitch picks={squad.picks} />
    </div>
  );
}
