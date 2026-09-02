import type { PipelineState } from "../types";

interface Props {
  generatedAt: string;
  projector: "naive" | "ml";
  pipelineState: PipelineState;
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function StatusBar({ generatedAt, projector, pipelineState }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-slate-400">
      <span>
        <span className="text-slate-500">projector</span>{" "}
        <span className="font-medium text-slate-200">{projector}</span>
      </span>
      <span>
        <span className="text-slate-500">generated</span>{" "}
        <span className="font-medium text-slate-200">
          {relTime(generatedAt)}
        </span>
      </span>
      {pipelineState.next_gw && (
        <span>
          <span className="text-slate-500">next</span>{" "}
          <span className="font-medium text-slate-200">
            {pipelineState.next_gw.name}
          </span>{" "}
          <span className="text-slate-500">
            (deadline{" "}
            {new Date(pipelineState.next_gw.deadline_time).toLocaleString()})
          </span>
        </span>
      )}
    </div>
  );
}
