import type {
  EntrySquadResponse,
  OptimizedSquadResponse,
  Position,
  ProjectionsResponse,
  SquadResponse,
  StatusResponse,
  TargetSquadResponse,
  TransferPlanResponse,
  TransferRequestBody,
} from "./types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = "";
    try {
      const body = await r.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    } catch {
      /* body not JSON, ignore */
    }
    throw new Error(`${r.status} ${r.statusText}${detail ? " — " + detail : ""}`);
  }
  return (await r.json()) as T;
}

export const api = {
  status: () => json<StatusResponse>("/api/status"),
  squad: () => json<SquadResponse>("/api/squad/latest"),
  squadTarget: (budgetTenths?: number) =>
    json<TargetSquadResponse>(
      "/api/squad/target" + (budgetTenths != null ? `?budget_tenths=${budgetTenths}` : "")
    ),
  squadOptimize: (budgetTenths: number) =>
    json<OptimizedSquadResponse>(
      `/api/squad/optimize?budget_tenths=${budgetTenths}`
    ),
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
  entrySquad: (entryId: number) =>
    json<EntrySquadResponse>(`/api/entry/${entryId}/squad`),
  transfers: (body: TransferRequestBody) =>
    json<TransferPlanResponse>("/api/transfers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
