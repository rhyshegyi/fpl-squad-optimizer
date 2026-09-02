import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { FdrChip } from "../components/FdrChip";
import { teamColor } from "../teamColors";
import type { Player, Position, ProjectionsResponse } from "../types";

const POSITIONS: (Position | "ALL")[] = ["ALL", "GK", "DEF", "MID", "FWD"];

type SortKey =
  | "projected_points"
  | "now_cost"
  | "web_name"
  | "form"
  | "selected_by";

function statusPill(p: Player): { label: string; cls: string } | null {
  const chance = p.chance_next_round;
  if (p.status === "i" || p.status === "u")
    return { label: "OUT", cls: "bg-red-500/20 text-red-300 border-red-500/40" };
  if (p.status === "s")
    return { label: "SUS", cls: "bg-red-500/20 text-red-300 border-red-500/40" };
  if (p.status === "d" || (chance != null && chance < 100))
    return {
      label: chance != null ? `${chance}%` : "DBT",
      cls: "bg-amber-500/20 text-amber-300 border-amber-500/40",
    };
  return null;
}

export function ProjectionsPage() {
  const [data, setData] = useState<ProjectionsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [position, setPosition] = useState<Position | "ALL">("ALL");
  const [sort, setSort] = useState<SortKey>("projected_points");
  const [maxCost, setMaxCost] = useState<number>(160);
  const [query, setQuery] = useState<string>("");
  const [hideUnavailable, setHideUnavailable] = useState<boolean>(true);

  // The list is only ~600 rows, so fetch once (no server-side sort for the new
  // client-only sort keys) and filter/sort in the browser.
  useEffect(() => {
    setData(null);
    api
      .projections({ limit: 1000 })
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  const rows: Player[] = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    let filtered = data.projections.filter((p) => {
      if (position !== "ALL" && p.position !== position) return false;
      if (p.now_cost > maxCost) return false;
      if (hideUnavailable && (p.status === "i" || p.status === "s" || p.status === "u"))
        return false;
      if (q && !p.web_name.toLowerCase().includes(q) &&
          !p.team_short.toLowerCase().includes(q)) return false;
      return true;
    });
    const desc = sort !== "web_name";
    filtered = filtered.slice().sort((a, b) => {
      const va = a[sort] ?? -Infinity;
      const vb = b[sort] ?? -Infinity;
      if (typeof va === "string" && typeof vb === "string") {
        return desc ? vb.localeCompare(va) : va.localeCompare(vb);
      }
      return desc ? (vb as number) - (va as number) : (va as number) - (vb as number);
    });
    return filtered.slice(0, 200);
  }, [data, position, sort, maxCost, query, hideUnavailable]);

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500">
          Scouting
        </div>
        <h1 className="text-3xl font-bold mt-1">Player projections</h1>
        <p className="text-slate-400 mt-2 max-w-2xl text-sm">
          Every player ranked with the context that explains their projection —
          recent form, minutes reliability, xG/xA underlying, ownership, and
          the next fixture (colored by difficulty). Availability flags surface
          doubts and suspensions.
        </p>
      </div>

      <div className="flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-xs uppercase tracking-wider text-slate-400 mb-1">
            Search
          </label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="name or team code"
            className="bg-slate-900 border border-white/10 rounded-lg px-3 py-1.5 text-sm w-52"
          />
        </div>

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
            <option value="form">Form</option>
            <option value="selected_by">Ownership</option>
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
            max={160}
            step={5}
            value={maxCost}
            onChange={(e) => setMaxCost(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-300 pb-1">
          <input
            type="checkbox"
            checked={hideUnavailable}
            onChange={(e) => setHideUnavailable(e.target.checked)}
            className="accent-emerald-500"
          />
          Hide injured / suspended
        </label>
      </div>

      {err && <div className="text-red-400">{err}</div>}
      {!data && !err && <div className="text-slate-400">loading…</div>}

      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-400">
              <tr className="border-b border-white/10">
                <th className="px-2 py-2 text-left">Player</th>
                <th className="px-2 py-2 text-left">Pos</th>
                <th className="px-2 py-2 text-right">£m</th>
                <th className="px-2 py-2 text-right" title="Model projected points for the next GW">
                  Proj
                </th>
                <th className="px-2 py-2 text-right" title="FPL form: average points over the last 30 days">
                  Form
                </th>
                <th className="px-2 py-2 text-right" title="Avg minutes across GWs played this season">
                  Mins
                </th>
                <th className="px-2 py-2 text-right" title="Sum of xG + xA over this season's played GWs">
                  xG+xA
                </th>
                <th className="px-2 py-2 text-right" title="Bonus points won this season">
                  Bns
                </th>
                <th className="px-2 py-2 text-right" title="% of FPL managers who own this player">
                  Own%
                </th>
                <th className="px-2 py-2 text-left" title="Next fixture (colored by difficulty)">
                  Next
                </th>
                <th className="px-2 py-2 text-right" title="Value: projected points per £m">
                  Value
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const status = statusPill(p);
                const xgxa = (p.xg_recent ?? 0) + (p.xa_recent ?? 0);
                return (
                  <tr
                    key={p.player_id}
                    className="border-b border-white/5 hover:bg-white/5"
                  >
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: teamColor(p.team_short) }}
                          title={p.team_short}
                        />
                        <span className="font-medium">{p.web_name}</span>
                        <span className="text-[10px] uppercase tracking-widest text-slate-500">
                          {p.team_short}
                        </span>
                        {status && (
                          <span
                            className={"text-[10px] px-1.5 py-0.5 rounded border font-semibold " + status.cls}
                          >
                            {status.label}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-slate-400">{p.position}</td>
                    <td className="px-2 py-2 text-right">
                      {(p.now_cost / 10).toFixed(1)}
                    </td>
                    <td className="px-2 py-2 text-right text-emerald-400 font-semibold">
                      {p.projected_points.toFixed(2)}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-200">
                      {p.form?.toFixed(1) ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300">
                      {p.minutes_avg != null ? Math.round(p.minutes_avg) : "—"}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300">
                      {p.gws_played ? xgxa.toFixed(2) : "—"}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-400">
                      {p.bonus_recent ?? 0}
                    </td>
                    <td className="px-2 py-2 text-right text-slate-400">
                      {p.selected_by?.toFixed(1) ?? "—"}
                    </td>
                    <td className="px-2 py-2">
                      <FdrChip
                        fdr={p.fdr}
                        opp={p.opp_short}
                        isHome={p.is_home}
                      />
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300">
                      {p.now_cost === 0
                        ? "—"
                        : ((p.projected_points / p.now_cost) * 10).toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-3 text-xs text-slate-500">
            Showing {rows.length} of {data.count}
          </div>
        </div>
      )}
    </div>
  );
}
