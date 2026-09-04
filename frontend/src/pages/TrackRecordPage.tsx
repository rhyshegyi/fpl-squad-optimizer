import { useEffect, useState } from "react";
import { api } from "../api";
import { teamColor } from "../teamColors";
import type { AccuracyResponse, PlayerOutcome, TrackedGameweek } from "../types";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

function Tile({
  label, value, sub, tone = "plain",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "plain" | "good" | "bad";
}) {
  const colour = {
    plain: "text-slate-100",
    good: "text-emerald-400",
    bad: "text-red-400",
  }[tone];
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </div>
      <div className={"text-2xl font-bold mt-1 " + colour}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function OutcomeRow({ p }: { p: PlayerOutcome }) {
  const delta = p.actual - p.projected;
  return (
    <div className="flex items-center gap-2 text-sm py-1">
      <span
        className="inline-block w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: teamColor(p.team_short) }}
      />
      <span className="font-medium truncate flex-1">{p.web_name}</span>
      <span className="text-slate-500 tabular-nums">{p.projected.toFixed(1)}</span>
      <span className="text-slate-600">→</span>
      <span className="tabular-nums w-6 text-right">{p.actual}</span>
      <span
        className={
          "tabular-nums w-12 text-right text-xs " +
          (delta >= 0 ? "text-emerald-400" : "text-red-400")
        }
      >
        {delta >= 0 ? "+" : ""}{delta.toFixed(1)}
      </span>
    </div>
  );
}

function GameweekCard({ w }: { w: TrackedGameweek }) {
  const beat = w.beat_average;
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5 space-y-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <span className="font-semibold text-lg">{w.name ?? `GW${w.gw}`}</span>
          <span className="text-slate-500 text-xs ml-2">
            frozen {fmtDate(w.frozen_at)}
          </span>
          {!w.scores_final && (
            <span className="ml-2 text-[10px] uppercase tracking-wider text-amber-300/80">
              bonus provisional
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums">{w.points}</span>
          {beat != null && (
            <span
              className={
                "text-sm font-medium " +
                (beat > 0 ? "text-emerald-400" : beat < 0 ? "text-red-400" : "text-slate-400")
              }
            >
              {beat > 0 ? "+" : ""}{beat} vs avg {w.fpl_average}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400">
        <span>captain {w.captain_points}{w.captain_blanked && " (vice)"}</span>
        <span>bench {w.points_left_on_bench}</span>
        {w.mae != null && <span>MAE {w.mae.toFixed(2)}</span>}
        {w.spearman != null && <span>ρ {w.spearman.toFixed(3)}</span>}
        <span>{w.players_appeared} players rated</span>
      </div>

      {(w.hits.length > 0 || w.misses.length > 0) && (
        <div className="grid sm:grid-cols-2 gap-4 pt-1">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-emerald-400/70 mb-1">
              Most underrated
            </div>
            {w.hits.slice(0, 5).map((p) => (
              <OutcomeRow key={p.web_name + p.team_short} p={p} />
            ))}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-widest text-red-400/70 mb-1">
              Most overrated
            </div>
            {w.misses.slice(0, 5).map((p) => (
              <OutcomeRow key={p.web_name + p.team_short} p={p} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function TrackRecordPage() {
  const [data, setData] = useState<AccuracyResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.accuracy().then(setData).catch((e) => setErr(String(e)));
  }, []);

  const t = data?.totals;
  const weeks = data?.gameweeks ?? [];
  const scored = t?.gameweeks_scored ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-500">
          Track record
        </div>
        <h1 className="text-3xl font-bold mt-1">Was the model right?</h1>
        <p className="text-slate-400 mt-2 max-w-2xl text-sm">
          Before every deadline the recommended squad and every player's
          projection are written down. Once the round finishes they are scored
          against what actually happened. Because the numbers are frozen before
          kickoff, none of this can be fitted after the fact.
        </p>
        <p className="text-slate-400 mt-2 max-w-2xl text-sm">
          This is not a live scoreboard — the FPL app does that better, and
          this data only refreshes twice a day. It answers a different
          question: whether the projections are any good on data the model has
          never seen.
        </p>
      </div>

      {err && <div className="text-red-400">{err}</div>}
      {!data && !err && <div className="text-slate-400">loading…</div>}

      {data && scored === 0 && (
        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-6">
          <div className="font-medium">Nothing scored yet.</div>
          <p className="text-slate-400 text-sm mt-2 max-w-2xl">
            Tracking starts from the next deadline — earlier gameweeks are not
            backfilled, because a recommendation reconstructed after the
            results are known is worth nothing.
            {data.pending.length > 0 && (
              <>
                {" "}
                <span className="text-slate-300">
                  {data.pending[0].name ?? `GW${data.pending[0].gw}`}
                </span>{" "}
                is frozen and waiting on results.
              </>
            )}
          </p>
        </div>
      )}

      {data && scored > 0 && t && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Tile
              label="Gameweeks scored"
              value={String(t.gameweeks_scored)}
            />
            <Tile
              label="Mean points"
              value={t.mean_points?.toFixed(1) ?? "—"}
              sub={t.mean_fpl_average != null ? `FPL average ${t.mean_fpl_average}` : undefined}
              tone={
                t.mean_points != null && t.mean_fpl_average != null
                  ? t.mean_points >= t.mean_fpl_average ? "good" : "bad"
                  : "plain"
              }
            />
            <Tile
              label="Weeks beating average"
              value={`${t.weeks_beating_average ?? 0}/${t.weeks_rated ?? 0}`}
            />
            <Tile
              label="Rank correlation"
              value={t.mean_spearman?.toFixed(3) ?? "—"}
              sub={t.mean_mae != null ? `MAE ${t.mean_mae.toFixed(2)}` : undefined}
            />
          </div>

          {(t.weeks_rated ?? 0) < 6 && (
            <p className="text-xs text-slate-500 max-w-2xl">
              Too few gameweeks to read anything into yet. A single week's
              squad total carries a standard deviation of roughly 15–20 points,
              so it takes months before beating or missing the average means
              much. The per-player accuracy numbers settle faster.
            </p>
          )}

          <div className="space-y-4">
            {[...weeks].reverse().map((w) => (
              <GameweekCard key={w.gw} w={w} />
            ))}
          </div>
        </>
      )}

      {data && data.pending.length > 0 && scored > 0 && (
        <div className="text-xs text-slate-500">
          Awaiting results:{" "}
          {data.pending.map((p) => p.name ?? `GW${p.gw}`).join(", ")}
        </div>
      )}
    </div>
  );
}
