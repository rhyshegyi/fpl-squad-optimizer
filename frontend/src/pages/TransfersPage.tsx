import { useEffect, useState } from "react";
import { api } from "../api";
import { Pitch } from "../components/Pitch";
import { teamColor } from "../teamColors";
import type {
  EntrySquadResponse,
  ChipAdvice,
  Pick as SquadPick,
  Player,
  TransferPlanResponse,
} from "../types";

type Source = "entry" | "manual";

/** Work in progress, held for as long as the page stays open.
 *
 *  Deliberately a plain module variable rather than localStorage. The page
 *  should keep your squad and its recommendations while you tab over to
 *  Squad or Scouting and come back — that is one continuous piece of work.
 *  It should NOT still be sitting there for whoever opens the site next: a
 *  stranger's team ID pre-filled on a public page is somebody else's data on
 *  someone else's screen. A module variable gives exactly that boundary,
 *  because a reload or a new tab re-evaluates the module and starts blank.
 *
 *  The plan is kept here too. It used to be dropped on navigation over a
 *  staleness worry, but the artifacts only move twice a day and this store
 *  dies with the tab, so the window where it could go stale is far smaller
 *  than the annoyance of losing a result by clicking away.
 */
interface SessionState {
  source: Source;
  entryIdInput: string;
  manualIds: string;
  bankMillions: string;
  freeTransfers: number;
  maxTransfersInput: string;
  ignoreHits: boolean;
  loadedEntry: EntrySquadResponse | null;
  plan: TransferPlanResponse | null;
}

const BLANK: SessionState = {
  source: "entry",
  entryIdInput: "",
  manualIds: "",
  bankMillions: "0.0",
  freeTransfers: 1,
  maxTransfersInput: "",
  ignoreHits: false,
  loadedEntry: null,
  plan: null,
};

let sessionState: SessionState = { ...BLANK };

export function TransfersPage() {
  const initial = sessionState;
  const [source, setSource] = useState<Source>(initial.source);
  const [entryIdInput, setEntryIdInput] = useState(initial.entryIdInput);
  const [manualIds, setManualIds] = useState(initial.manualIds);
  const [bankMillions, setBankMillions] = useState(initial.bankMillions);
  const [freeTransfers, setFreeTransfers] = useState(initial.freeTransfers);
  const [maxTransfersInput, setMaxTransfersInput] = useState(initial.maxTransfersInput);
  const [ignoreHits, setIgnoreHits] = useState<boolean>(initial.ignoreHits);

  const [loadedEntry, setLoadedEntry] = useState<EntrySquadResponse | null>(initial.loadedEntry);
  const [plan, setPlan] = useState<TransferPlanResponse | null>(initial.plan);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"load" | "submit" | null>(null);
  const [targetPicks, setTargetPicks] = useState<SquadPick[]>([]);

  // The Squad page's target is the thing this page helps you move towards,
  // so show how far off you currently are.
  useEffect(() => {
    api.squadTarget()
      .then((t) => setTargetPicks(t.squad.picks))
      .catch(() => setTargetPicks([]));
  }, []);

  useEffect(() => {
    sessionState = {
      source, entryIdInput, manualIds, bankMillions, freeTransfers,
      maxTransfersInput, ignoreHits, loadedEntry, plan,
    };
  }, [source, entryIdInput, manualIds, bankMillions, freeTransfers,
      maxTransfersInput, ignoreHits, loadedEntry, plan]);

  const squadIds = manualIds
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isFinite(n));
  const targetIds = new Set(targetPicks.map((p) => p.player_id));

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

  function clearSquad() {
    setLoadedEntry(null);
    setEntryIdInput("");
    setManualIds("");
    setBankMillions(BLANK.bankMillions);
    setPlan(null);
    setErr(null);
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
        <h1 className="text-3xl font-bold mt-1">What can you do this week?</h1>
        <p className="text-slate-400 mt-2 max-w-2xl">
          Load your squad by FPL entry ID or paste the 15 player IDs directly.
          <span className="text-slate-300"> This week</span> respects your free
          transfers and the -4 hit penalty, so an extra transfer is only
          recommended when the projected gain beats 4 points.{" "}
          <span className="text-slate-300">Wildcard / Free Hit</span> ignores
          both, showing the best squad you could build if transfers were free.
        </p>
      </div>

      {targetIds.size > 0 && squadIds.length === 15 && (
        <TargetDistance
          squadIds={squadIds}
          targetPicks={targetPicks}
        />
      )}

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
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-medium">
                      {loadedEntry.manager_name}{" "}
                      <span className="text-slate-500">
                        · {loadedEntry.team_name}
                      </span>
                    </div>
                    {/* Everything here is dropped on reload anyway, but on a
                        shared machine "reload the page" is a poor answer. */}
                    <button
                      onClick={clearSquad}
                      className="text-xs text-slate-500 hover:text-slate-200 shrink-0"
                      title="Forget this squad"
                    >
                      Clear
                    </button>
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
          </div>

          <div>
            <span className="text-xs uppercase tracking-wider text-slate-400">
              Mode
            </span>
            <div className="mt-1 flex gap-1 rounded-lg bg-slate-950 border border-white/10 p-1">
              {([false, true] as const).map((unlimited) => (
                <button
                  key={String(unlimited)}
                  onClick={() => setIgnoreHits(unlimited)}
                  className={
                    "flex-1 px-3 py-1.5 text-sm rounded-md transition " +
                    (ignoreHits === unlimited
                      ? "bg-emerald-500 text-slate-950 font-semibold"
                      : "text-slate-300 hover:text-white")
                  }
                >
                  {unlimited ? "Wildcard / Free Hit" : "This week"}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-400">
              {ignoreHits
                ? "Transfers are free and unlimited, so this is the squad a wildcard or free hit could get you. Cap it with max transfers to see a smaller rebuild."
                : "Constrained to your free transfers, with -4 per extra. This is what you can actually do before the deadline."}
            </p>
          </div>

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

      {plan?.chips && plan.chips.length > 0 && <Chips advice={plan.chips} />}

      {plan && <TransferPlanView plan={plan} unlimited={ignoreHits} />}
    </div>
  );
}

function TransferPlanView({
  plan,
  unlimited,
}: {
  plan: TransferPlanResponse;
  unlimited: boolean;
}) {
  const outs = [...plan.transfers_out].sort(
    (a, b) => a.projected_points - b.projected_points
  );
  const ins = [...plan.transfers_in].sort(
    (a, b) => b.projected_points - a.projected_points
  );
  const rows = outs.map((out, i) => ({ out, in_: ins[i] }));
  const isSingle = outs.length === 1 && ins.length === 1;
  const totalDelta =
    ins.reduce((t, p) => t + p.projected_points, 0) -
    outs.reduce((t, p) => t + p.projected_points, 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Transfers made"
          value={String(plan.transfers_made)}
          sub={unlimited ? "unlimited" : `${plan.free_transfers} free`}
        />
        <Stat
          label="Hits"
          value={plan.hit_cost > 0 ? `${plan.paid_hits}` : "None"}
          sub={
            plan.hit_cost > 0
              ? `-${plan.hit_cost} pts`
              : unlimited
              ? "free on a wildcard"
              : "within your free transfers"
          }
          tone={plan.hit_cost > 0 ? "warn" : "ok"}
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
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
            <div className="text-xs uppercase tracking-widest text-slate-400">
              {isSingle ? "Suggested swap" : "Players in and out"}
            </div>
            <div className="text-xs text-emerald-400">
              {totalDelta >= 0 ? "+" : ""}
              {totalDelta.toFixed(2)} pts across the squad
            </div>
          </div>

          {isSingle ? (
            <SwapRow out={outs[0]} in_={ins[0]} />
          ) : (
            <>
              {/* The LP picks the whole squad at once, so there is no
                  meaningful one-to-one mapping between a player going out
                  and a specific player coming in. Pairing them would imply
                  swaps that were never recommended. */}
              <div className="grid gap-5 sm:grid-cols-2">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-red-300/80 mb-2">
                    Out ({outs.length})
                  </div>
                  <ul className="space-y-1.5">
                    {outs.map((p) => (
                      <li key={p.player_id} className="flex justify-between text-sm">
                        <span className="text-slate-300">{p.web_name}</span>
                        <span className="text-xs text-slate-500">
                          {p.team_short} · £{(p.now_cost / 10).toFixed(1)}m ·{" "}
                          {p.projected_points.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-emerald-300/80 mb-2">
                    In ({ins.length})
                  </div>
                  <ul className="space-y-1.5">
                    {ins.map((p) => (
                      <li key={p.player_id} className="flex justify-between text-sm">
                        <span className="text-slate-100 font-medium">{p.web_name}</span>
                        <span className="text-xs text-slate-500">
                          {p.team_short} · £{(p.now_cost / 10).toFixed(1)}m ·{" "}
                          {p.projected_points.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <p className="mt-4 text-xs text-slate-500">
                These are chosen together as one squad, so they don't pair up
                one-for-one — read them as a set rather than as individual swaps.
              </p>
            </>
          )}
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
        <Pitch picks={plan.new_squad.picks} metric="next GW" />
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


function TargetDistance({
  squadIds,
  targetPicks,
}: {
  squadIds: number[];
  targetPicks: SquadPick[];
}) {
  const owned = new Set(squadIds);
  const have = targetPicks.filter((p) => owned.has(p.player_id));
  const missing = [...targetPicks]
    .filter((p) => !owned.has(p.player_id))
    .sort((a, b) => b.projected_points - a.projected_points);

  const pct = Math.round((have.length / targetPicks.length) * 100);

  return (
    <section className="rounded-xl border border-white/10 bg-slate-900/60 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-xs uppercase tracking-widest text-slate-400">
          Distance from target squad
        </div>
        <div className="text-sm text-slate-400">
          <span className="text-2xl font-bold text-emerald-400">
            {have.length}
          </span>
          <span className="text-slate-500"> / {targetPicks.length} owned</span>
        </div>
      </div>

      <div className="h-2 rounded-full bg-slate-800 overflow-hidden mt-3">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>

      {missing.length > 0 ? (
        <>
          <div className="mt-4 text-xs text-slate-400">
            Still to bring in, best first — these are the gaps between your
            squad and the multi-week target.
          </div>
          <ul className="mt-2 flex flex-wrap gap-2">
            {missing.map((p) => (
              <li
                key={p.player_id}
                className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-950 px-2.5 py-1.5 text-xs"
                style={{ borderTopColor: teamColor(p.team_short), borderTopWidth: 2 }}
              >
                <span className="font-medium text-slate-100">{p.web_name}</span>
                <span className="text-slate-500">{p.team_short}</span>
                <span className="text-slate-400">£{(p.now_cost / 10).toFixed(1)}m</span>
                <span className="text-emerald-400">
                  {p.projected_points.toFixed(1)}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="mt-4 text-sm text-emerald-300">
          You already own the entire target squad.
        </div>
      )}
    </section>
  );
}


function SwapRow({ out, in_ }: { out: Player; in_: Player }) {
  const delta = in_.projected_points - out.projected_points;
  const costDelta = (in_.now_cost - out.now_cost) / 10;
  return (
    <div className="grid grid-cols-[1fr,auto,1fr,auto] items-center gap-3 text-sm">
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
    </div>
  );
}


function Chips({ advice }: { advice: ChipAdvice[] }) {
  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <div className="text-xs uppercase tracking-widest text-slate-400">
          Chips this week
        </div>
        <div className="text-xs text-slate-500">
          Heuristics based on your squad and this week's fixtures — not
          optimised season-long timing
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {advice.map((c) => (
          <div
            key={c.chip}
            className={
              "rounded-xl border p-4 " +
              (c.recommended
                ? "border-emerald-500/40 bg-emerald-500/5"
                : "border-white/10 bg-slate-900/60")
            }
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-slate-100">{c.label}</span>
              <span
                className={
                  "text-[10px] uppercase tracking-widest px-2 py-0.5 rounded border font-semibold " +
                  (c.recommended
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                    : "bg-slate-500/15 text-slate-400 border-slate-500/30")
                }
              >
                {c.recommended ? "Play" : "Hold"}
              </span>
            </div>

            <div
              className={
                "mt-2 text-sm font-medium " +
                (c.recommended ? "text-emerald-300" : "text-slate-300")
              }
            >
              {c.headline}
            </div>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed">{c.detail}</p>

            {c.benchmark > 0 && (
              <div className="mt-3">
                <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={c.recommended ? "h-full bg-emerald-500" : "h-full bg-slate-600"}
                    style={{
                      width: `${Math.min(100, (c.value / c.benchmark) * 100)}%`,
                    }}
                  />
                </div>
                <div className="mt-1 flex justify-between text-[10px] text-slate-500">
                  <span>{c.value.toFixed(1)} projected</span>
                  <span>{c.benchmark.toFixed(1)} to justify playing it</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
