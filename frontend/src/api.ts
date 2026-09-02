import type {
  Position,
  ProjectionsResponse,
  SquadResponse,
  StatusResponse,
} from "./types";

async function json<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} — ${path}`);
  }
  return (await r.json()) as T;
}

export const api = {
  status: () => json<StatusResponse>("/api/status"),
  squad: () => json<SquadResponse>("/api/squad/latest"),
  projections: (opts: {
    position?: Position;
    maxCostTenths?: number;
    limit?: number;
    sort?: "projected_points" | "now_cost" | "web_name";
  } = {}) => {
    const q = new URLSearchParams();
    if (opts.position) q.set("position", opts.position);
    if (opts.maxCostTenths != null) q.set("max_cost_tenths", String(opts.maxCostTenths));
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.sort) q.set("sort", opts.sort);
    const qs = q.toString();
    return json<ProjectionsResponse>(`/api/projections/latest${qs ? "?" + qs : ""}`);
  },
};
