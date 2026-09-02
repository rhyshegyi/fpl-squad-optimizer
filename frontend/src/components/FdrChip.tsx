interface Props {
  fdr: number | null | undefined;
  opp: string | null | undefined;
  isHome: boolean | null | undefined;
}

// FPL's own palette: green (easy) → red (hard). Same buckets fpl.com uses.
const FDR_CLASS: Record<number, string> = {
  1: "bg-emerald-500/25 text-emerald-200 border-emerald-500/40",
  2: "bg-emerald-500/15 text-emerald-200 border-emerald-500/25",
  3: "bg-slate-500/20 text-slate-200 border-slate-400/30",
  4: "bg-red-500/20 text-red-200 border-red-500/40",
  5: "bg-red-500/35 text-red-100 border-red-500/60",
};

export function FdrChip({ fdr, opp, isHome }: Props) {
  if (fdr == null || !opp) {
    return <span className="text-slate-600 text-xs">—</span>;
  }
  const cls = FDR_CLASS[fdr] ?? FDR_CLASS[3];
  return (
    <span
      className={"inline-flex items-center gap-1 rounded px-1.5 py-0.5 border text-xs font-medium " + cls}
      title={`FDR ${fdr}`}
    >
      <span className="uppercase tracking-wider">
        {opp}
        <span className="opacity-60">{isHome ? " (H)" : " (A)"}</span>
      </span>
    </span>
  );
}
