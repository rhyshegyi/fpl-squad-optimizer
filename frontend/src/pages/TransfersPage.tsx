import { useEffect, useState } from "react";
import { api } from "../api";
import { Pitch } from "../components/Pitch";
import type {
  EntrySquadResponse,
  TransferPlanResponse,
} from "../types";

type Source = "entry" | "manual";
type Projector = "ml" | "naive";

// Persist just the form + loaded-entry across navigation so users don't
// have to re-enter their FPL entry ID every time they switch pages. The
// plan itself is deliberately NOT stored because data goes stale — user
// clicks Recommend again to refresh, which is now ~250ms.
const STORAGE_KEY = "fpl-transfers-state.v1";

interface PersistedState {
  source: Source;
  entryIdInput: string;
  manualIds: string;
  bankMillions: string;
  freeTransfers: number;
  maxTransfersInput: string;
  projector: Projector;
  ignoreHits: boolean;
  loadedEntry: EntrySquadResponse | null;
}

const DEFAULT_STATE: PersistedState = {
  source: "entry",
  entryIdInput: "",
  manualIds: "",
  bankMillions: "0.0",
  freeTransfers: 1,
  maxTransfersInput: "",
  projector: "ml",
  ignoreHits: false,
  loadedEntry: null,
};

function readPersistedState(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    return { ...DEFAULT_STATE, ...(JSON.parse(raw) as Partial<PersistedState>) };
  } catch {
    return DEFAULT_STATE;
  }
}

export function TransfersPage() {
  const initial = readPersistedState();
  const [source, setSource] = useState<Source>(initial.source);
  const [entryIdInput, setEntryIdInput] = useState(initial.entryIdInput);
  const [manualIds, setManualIds] = useState(initial.manualIds);
  const [bankMillions, setBankMillions] = useState(initial.bankMillions);
  const [freeTransfers, setFreeTransfers] = useState(initial.freeTransfers);
  const [maxTransfersInput, setMaxTransfersInput] = useState(initial.maxTransfersInput);
  const [projector, setProjector] = useState<Projector>(initial.projector);
  const [ignoreHits, setIgnoreHits] = useState<boolean>(initial.ignoreHits);

  const [loadedEntry, setLoadedEntry] = useState<EntrySquadResponse | null>(initial.loadedEntry);
  const [plan, setPlan] = useState<TransferPlanResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"load" | "submit" | null>(null);

  useEffect(() => {
    const state: PersistedState = {
      source, entryIdInput, manualIds, bankMillions, freeTransfers,
      maxTransfersInput, projector, ignoreHits, loadedEntry,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch { /* localStorage full or disabled — silently drop persistence */ }
  }, [source, entryIdInput, manualIds, bankMillions, freeTransfers,
      maxTransfersInput, projector, ignoreHits, loadedEntry]);

  async function loadEntry() {
    setErr(null);
    setBusy("load");
    try {
      const id = Number(entryIdInput);
      if (!Number.isFinite(id) || id <= 0) throw new Error("enter a valid entry id");
      const data = await api.entrySquad(id);
      setLoadedEntry(data);
      setManualIds(data.player_ids.join(","));
      setBankMillions((data.bank / 10).toFixed(1));
    } catch (e) {
      setErr(String(e));
      setLoadedEntry(null);
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    setErr(null);
    setPlan(null);
    setBusy("submit");
    try {
      const ids = manualIds
        .split(/[\s,]+/)
        .filter(Boolean)
        .map((s) => Number(s));
      if (ids.length !== 15 || ids.some((n) => !Number.isFinite(n) || n <= 0)) {
        throw new Error("need exactly 15 valid player ids");
      }
      const bankTenths = Math.round(Number(bankMillions) * 10);
      if (!Number.isFinite(bankTenths) || bankTenths < 0) {
        throw new Error("bank must be a non-negative number");
      }
      const max = maxTransfersInput.trim() === "" ? null : Number(maxTransfersInput);
      if (max !== null && (!Number.isFinite(max) || max < 0)) {
        throw new Error("max transfers must be a non-negative integer or blank");
      }
      const result = await api.transfers({
        existing_ids: ids,
        bank_tenths: bankTenths,
        free_transfers: freeTransfers,
        max_transfers: max ?? undefined,
        projector,
        ignore_hit_cost: ignoreHits,
      });
      setPlan(result);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500">
          Transfer recommendations
        </div>
        <h1 className="text-3xl font-bold mt-1">Optimize your existing squad</h1>
        <p className="text-slate-400 mt-2 max-w-2xl">
          Load your squad by FPL entry ID or paste the 15 player IDs directly.
          The optimizer respects your free transfers and factors in the -4 hit
          penalty for anything over the allowance — so a second transfer is
          only recommended when the projected gain from that swap exceeds
          4 points. Flip the "ignore hit penalty" toggle if you want to
          plan multiple moves without that trade-off.
        </p>
      </div>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5 space-y-4">
          <div className="text-xs uppercase tracking-widest text-slate-400">
            1. Existing squad
          </div>

          <div className="flex gap-1 rounded-lg bg-slate-950 border border-white/10 p-1 w-max">
            {(["entry", "manual"] as Source[]).map((s) => (
              <button
                key={s}
                onClick={() => setSource(s)}
                className={
                  "px-3 py-1 text-sm rounded-md transition " +
                  (source === s
                    ? "bg-emerald-500 text-slate-950 font-semibold"
                    : "text-slate-300 hover:text-white")
                }
              >
                {s === "entry" ? "FPL entry ID" : "Player IDs"}
              </button>
            ))}
          </div>

          {source === "entry" ? (
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs uppercase tracking-wider text-slate-400">
                  Entry ID
                </span>
                <div className="mt-1 flex gap-2">
                  <input
                    value={entryIdInput}
                    onChange={(e) => setEntryIdInput(e.target.value)}
                    placeholder="e.g. 12345"
                    className="flex-1 bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm"
                  />
                  <button
                    onClick={loadEntry}
                    disabled={busy === "load"}
                    className="px-4 py-2 rounded-lg bg-emerald-500 text-slate-950 text-sm font-semibold disabled:opacity-50"
                  >
                    {busy === "load" ? "loading…" : "Load"}
                  </button>
                </div>
              </label>
              {loadedEntry && (
                <div className="rounded-lg bg-slate-950 border border-white/5 px-3 py-2 text-sm">
                  <div className="font-medium">
                    {loadedEntry.manager_name}{" "}
                    <span className="text-slate-500">
                      · {loadedEntry.team_name}
                    </span>
                  </div>
                  <div className="text-slate-400 text-xs mt-1">
                    Picks from GW{loadedEntry.source_gw} · bank £
                    {(loadedEntry.bank / 10).toFixed(1)}m · squad value £
                    {(loadedEntry.squad_value / 10).toFixed(1)}m
                  </div>
                </div>
              )}
            </div>
          ) : (
            <label className="block">
              <span className="text-xs uppercase tracking-wider text-slate-400">
                15 player IDs (comma or whitespace separated)
              </span>
              <textarea
                value={manualIds}
                onChange={(e) => setManualIds(e.target.value)}
                placeholder="86,88,115,165,277,279,367,385,391,399,411,464,565,572,17"
                rows={3}
                className="mt-1 w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono"
              />
            </label>
          )}
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5 space-y-4">
          <div className="text-xs uppercase tracking-widest text-slate-400">
            2. Parameters
          </div>

          <div className="grid gap-3 grid-cols-2">
            <label className="block">
              <span className="text-xs uppercase tracking-wider text-slate-400">
                Bank (£m)
              </span>
              <input
                type="number"
                min={0}
                step={0.1}
                value={bankMillions}
                onChange={(e) => setBankMillions(e.target.value)}
                className="mt-1 w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs uppercase tracking-wider text-slate-400">
                Free transfers
              </span>
              <input
                type="number"
                min={0}
                max={5}
                value={freeTransfers}
                onChange={(e) => setFreeTransfers(Number(e.target.value))}
                className="mt-1 w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs uppercase tracking-wider text-slate-400">
                Max transfers (blank = no cap)
              </span>
              <input
                type="number"
                min={0}
                value={maxTransfersInput}
                onChange={(e) => setMaxTransfersInput(e.target.value)}
                className="mt-1 w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs uppercase tracking-wider text-slate-400">
                Projector
              </span>
              <select
                value={projector}
                onChange={(e) => setProjector(e.target.value as Projector)}
                className="mt-1 w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-sm"
              >
                <option value="ml">ml (LightGBM)</option>
                <option value="naive">naive (form × FDR)</option>
              </select>
            </label>
          </div>

          <label className="flex items-start gap-2 text-xs text-slate-300 pt-1">
            <input
              type="checkbox"
              checked={ignoreHits}
              onChange={(e) => setIgnoreHits(e.target.checked)}
              className="accent-emerald-500 mt-0.5"
            />
            <span>
              <span className="font-medium text-slate-200">Ignore hit penalty.</span>{" "}
              Treat extra transfers as free — the LP picks the best possible squad
              regardless of how many swaps it takes. Use with{" "}
              <span className="text-slate-100">max transfers</span> to cap.
            </span>
          </label>

          <button
            onClick={submit}
            disabled={busy === "submit"}
            className="w-full py-2 rounded-lg bg-emerald-500 text-slate-950 text-sm font-semibold disabled:opacity-50"
          >
            {busy === "submit" ? "computing…" : "Recommend transfers"}
          </button>
        </div>
      </section>

      {err && (
        <div className="rounded-lg bg-red-950/50 border border-red-500/40 px-4 py-3 text-sm text-red-300">
          {err}
        </div>
      )}

      {plan && <TransferPlanView plan={plan} />}
    </div>
  );
}

function TransferPlanView({ plan }: { plan: TransferPlanResponse }) {
  const outs = [...plan.transfers_out].sort(
    (a, b) => a.projected_points - b.projected_points
  );
  const ins = [...plan.transfers_in].sort(
    (a, b) => b.projected_points - a.projected_points
  );
  const rows = outs.map((out, i) => ({ out, in_: ins[i] }));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Transfers made" value={String(plan.transfers_made)} sub={`${plan.free_transfers} free`} />
        <Stat
          label="Hits"
          value={plan.paid_hits === 0 ? "None" : `${plan.paid_hits}`}
          sub={plan.hit_cost > 0 ? `-${plan.hit_cost} pts` : "no penalty"}
          tone={plan.paid_hits > 0 ? "warn" : "ok"}
        />
        <Stat
          label="Net projected"
          value={plan.projected_points.toFixed(2)}
          sub="starters + captain − hits"
          tone="pos"
        />
        <Stat
          label="Bank"
          value={`£${(plan.bank_after / 10).toFixed(1)}m`}
          sub={`was £${(plan.bank_before / 10).toFixed(1)}m`}
        />
      </div>

      {rows.length > 0 ? (
        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5">
          <div className="text-xs uppercase tracking-widest text-slate-400 mb-3">
            Suggested swaps
          </div>
          <ul className="space-y-3">
            {rows.map(({ out, in_ }, i) => {
              const delta = in_.projected_points - out.projected_points;
              const costDelta = (in_.now_cost - out.now_cost) / 10;
              return (
                <li
                  key={i}
                  className="grid grid-cols-[1fr,auto,1fr,auto] items-center gap-3 text-sm"
                >
                  <div className="text-right text-slate-400">
                    <div className="font-medium text-slate-200">{out.web_name}</div>
                    <div className="text-xs">
                      {out.team_short} · £{(out.now_cost / 10).toFixed(1)}m ·{" "}
                      {out.projected_points.toFixed(2)} pts
                    </div>
                  </div>
                  <div className="text-emerald-400">→</div>
                  <div className="text-slate-200">
                    <div className="font-medium">{in_.web_name}</div>
                    <div className="text-xs text-slate-400">
                      {in_.team_short} · £{(in_.now_cost / 10).toFixed(1)}m ·{" "}
                      {in_.projected_points.toFixed(2)} pts
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className={delta >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {delta >= 0 ? "+" : ""}
                      {delta.toFixed(2)} pts
                    </div>
                    <div className="text-slate-500">
                      {costDelta >= 0 ? "+" : ""}£{costDelta.toFixed(1)}m
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5 text-slate-300">
          No transfers recommended — your squad is already optimal under these constraints.
        </div>
      )}

      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">
          New squad
        </div>
        <Pitch picks={plan.new_squad.picks} />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "pos" | "warn" | "ok";
}) {
  const valueCls =
    tone === "pos"
      ? "text-emerald-400"
      : tone === "warn"
      ? "text-amber-400"
      : tone === "ok"
      ? "text-slate-100"
      : "text-slate-100";
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </div>
      <div className={"text-2xl font-bold mt-1 " + valueCls}>{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    </div>
  );
}
