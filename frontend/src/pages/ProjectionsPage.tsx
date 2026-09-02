import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Player, Position, ProjectionsResponse } from "../types";

const POSITIONS: (Position | "ALL")[] = ["ALL", "GK", "DEF", "MID", "FWD"];

type SortKey = "projected_points" | "now_cost" | "web_name";

export function ProjectionsPage() {
  const [data, setData] = useState<ProjectionsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [position, setPosition] = useState<Position | "ALL">("ALL");
  const [sort, setSort] = useState<SortKey>("projected_points");
  const [maxCost, setMaxCost] = useState<number>(150); // in tenths

  useEffect(() => {
    setData(null);
    api
      .projections({
        position: position === "ALL" ? undefined : position,
        sort,
        maxCostTenths: maxCost,
        limit: 400,
      })
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [position, sort, maxCost]);

  const rows: Player[] = useMemo(() => data?.projections ?? [], [data]);

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500">
          Player projections
        </div>
        <h1 className="text-3xl font-bold mt-1">
          Ranked by{" "}
          <span className="text-emerald-400">
            {sort === "projected_points"
              ? "projected points"
              : sort === "now_cost"
              ? "price"
              : "name"}
          </span>
        </h1>
      </div>

      <div className="flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">
            Position
          </label>
          <div className="flex gap-1 rounded-lg bg-slate-900 border border-white/10 p-1">
            {POSITIONS.map((p) => (
              <button
                key={p}
                onClick={() => setPosition(p)}
                className={
                  "px-3 py-1 text-sm rounded-md transition " +
                  (position === p
                    ? "bg-emerald-500 text-slate-950 font-semibold"
                    : "text-slate-300 hover:text-white")
                }
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">
            Sort
          </label>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="bg-slate-900 border border-white/10 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="projected_points">Projected points</option>
            <option value="now_cost">Price</option>
            <option value="web_name">Name</option>
          </select>
        </div>

        <div className="flex-1 min-w-[220px]">
          <label className="flex items-center justify-between text-xs uppercase tracking-wider text-slate-400 mb-1">
            <span>Max price</span>
            <span className="text-slate-300">£{(maxCost / 10).toFixed(1)}m</span>
          </label>
          <input
            type="range"
            min={40}
            max={150}
            step={5}
            value={maxCost}
            onChange={(e) => setMaxCost(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>
      </div>

      {err && <div className="text-red-400">{err}</div>}
      {!data && !err && <div className="text-slate-400">loading…</div>}

      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">Player</th>
                <th className="px-3 py-2 text-left">Team</th>
                <th className="px-3 py-2 text-left">Pos</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Projected</th>
                <th className="px-3 py-2 text-right">Value (pts/£m)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr
                  key={p.player_id}
                  className="border-t border-white/5 hover:bg-white/5"
                >
                  <td className="px-3 py-2 font-medium">{p.web_name}</td>
                  <td className="px-3 py-2 text-slate-400">{p.team_short}</td>
                  <td className="px-3 py-2 text-slate-400">{p.position}</td>
                  <td className="px-3 py-2 text-right">
                    £{(p.now_cost / 10).toFixed(1)}m
                  </td>
                  <td className="px-3 py-2 text-right text-emerald-400 font-semibold">
                    {p.projected_points.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300">
                    {p.now_cost === 0
                      ? "—"
                      : ((p.projected_points / p.now_cost) * 10).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
