import { useEffect, useState } from "react";
import { api } from "../api";
import type { PipelineState } from "../types";

function fmtDeadline(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function GameweekBadge() {
  const [state, setState] = useState<PipelineState | null>(null);

  useEffect(() => {
    api.status().then((r) => setState(r.pipeline_state)).catch(() => {});
  }, []);

  if (!state) return null;
  const target = state.next_gw ?? state.current_gw;
  if (!target) return null;

  return (
    <div className="hidden sm:flex items-center gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-1.5 text-xs">
      <div>
        <div className="uppercase tracking-widest text-emerald-300/80 text-[10px]">
          {state.next_gw ? "Planning" : "Current"}
        </div>
        <div className="font-semibold text-emerald-300">
          {target.name}
        </div>
      </div>
      {"deadline_time" in target && target.deadline_time && (
        <div className="border-l border-emerald-500/20 pl-3">
          <div className="uppercase tracking-widest text-emerald-300/80 text-[10px]">
            Deadline
          </div>
          <div className="text-emerald-100">
            {fmtDeadline(target.deadline_time)}
          </div>
        </div>
      )}
    </div>
  );
}
