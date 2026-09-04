import { useEffect, useState } from "react";
import { api } from "../api";
import { teamColor } from "../teamColors";
import type {
  AccuracyResponse,
  PlayerOutcome,
  SeasonLeader,
  TrackedGameweek,
} from "../types";

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

function SeasonLeaders({
  leaders,
  inTop10,
}: {
  leaders: SeasonLeader[];
  inTop10: number;
}) {
  // Mid-round some clubs have played a game more than others, which flatters
  // them on totals. Games played is shown so that is visible rather than
  // hidden, and points per game is there to read past it.
  const spread = new Set(leaders.map((l) => l.games));
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-xl font-semibold">Season so far</h2>
        <p className="text-slate-400 text-sm mt-1 max-w-2xl">
          Who has actually scored the most, from played matches only.{" "}
          <span className="text-slate-300">{inTop10} of the top 10</span> are in
          the current target squad — a number worth reading carefully, because
          this table is backward-looking and the squad is not trying to
          reproduce it. Two hauls against weak defences can top this list and
          still be a poor bet for the next six gameweeks.
          {spread.size > 1 && (
            <> Clubs that have played an extra match this round sit higher on
            total points; the GP and PPG columns show that.</>
          )}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-400">
            <tr className="border-b border-white/10">
              <th className="px-2 py-2 text-right w-8">#</th>
              <th className="px-2 py-2 text-left">Player</th>
              <th className="px-2 py-2 text-left">Pos</th>
              <th className="px-2 py-2 text-right">£m</th>
              <th className="px-2 py-2 text-right">Pts</th>
              <th className="px-2 py-2 text-right" title="Games played">GP</th>
              <th className="px-2 py-2 text-right" title="Points per game">PPG</th>
              <th className="px-2 py-2 text-right" title="Goals / assists">G/A</th>
              <th className="px-2 py-2 text-right" title="Bonus points">Bns</th>
              <th className="px-2 py-2 text-right" title="Points per £m">Value</th>
              <th className="px-2 py-2 text-right" title="% of managers who own them">Own%</th>
            </tr>
          </thead>
          <tbody>
            {leaders.map((l) => (
              <tr
                key={l.player_id}
                className={
                  "border-b border-white/5 hover:bg-white/5 " +
                  (l.in_target_squad ? "bg-emerald-500/5" : "")
                }
              >
                <td className="px-2 py-2 text-right text-slate-500 tabular-nums">
                  {l.rank}
                </td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: teamColor(l.team_short) }}
                      title={l.team_short}
                    />
                    <span className="font-medium">{l.web_name}</span>
                    <span className="text-[10px] uppercase tracking-widest text-slate-500">
                      {l.team_short}
                    </span>
                    {l.in_target_squad && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded border font-semibold border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        title="In the current target squad"
                      >
                        TARGET
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-2 py-2 text-slate-400">{l.position}</td>
                <td className="px-2 py-2 text-right tabular-nums">
                  {(l.now_cost / 10).toFixed(1)}
                </td>
                <td className="px-2 py-2 text-right font-semibold tabular-nums">
                  {l.points}
                </td>
                <td className="px-2 py-2 text-right text-slate-400 tabular-nums">
                  {l.games}
                </td>
                <td className="px-2 py-2 text-right text-slate-200 tabular-nums">
                  {l.ppg.toFixed(1)}
                </td>
                <td className="px-2 py-2 text-right text-slate-300 tabular-nums">
                  {l.goals}/{l.assists}
                </td>
                <td className="px-2 py-2 text-right text-slate-400 tabular-nums">
                  {l.bonus}
                </td>
                <td className="px-2 py-2 text-right text-slate-300 tabular-nums">
                  {l.value?.toFixed(2) ?? "—"}
                </td>
                <td className="px-2 py-2 text-right text-slate-400 tabular-nums">
                  {l.selected_by.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

      {data && (data.leaders?.length ?? 0) > 0 && (
        <SeasonLeaders
          leaders={data.leaders!}
          inTop10={data.leaders_in_target_top10 ?? 0}
        />
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
