export type Position = "GK" | "DEF" | "MID" | "FWD";

export interface Player {
  player_id: number;
  web_name: string;
  team_id: number;
  team_short: string;
  position: Position;
  now_cost: number;         // tenths of £m
  projected_points: number;

  /** 6-gameweek target value — what the Squad page ranks on. Differs from
   *  projected_points (next gameweek) and can reorder players entirely. */
  target_points?: number | null;

  // Scouting stats (optional — present when the row was enriched via scouting.py)
  form?: number;
  season_ppg?: number;
  season_points?: number;
  season_minutes?: number;
  selected_by?: number;      // %
  status?: "a" | "d" | "i" | "s" | "u" | string;
  chance_next_round?: number | null;
  gws_played?: number;
  minutes_avg?: number | null;
  points_avg?: number | null;
  xg_recent?: number | null;
  xa_recent?: number | null;
  bonus_recent?: number;
  opp_short?: string | null;
  is_home?: boolean | null;
  fdr?: number | null;       // 1 (easy) .. 5 (hard)
}

export interface Pick extends Player {
  is_starter: boolean;
  is_captain: boolean;
  is_vice: boolean;
}

export interface Squad {
  total_cost: number;
  projected_points: number;
  formation: string;
  picks: Pick[];
}

/** Whether the snapshot behind these numbers is internally consistent.
 *  The bootstrap and the per-gameweek history are fetched separately, so a
 *  snapshot taken mid-round has them describing a different number of
 *  matches. `players_disagreeing > 0` means results are missing. */
export interface DataHealth {
  players_tracked: number;
  players_disagreeing: number;
  latest_gw_on_file: number | null;
  latest_result: string | null;
  /** Present only while a round is being played: squads are locked and
   *  results are partial, so every projection on the site will still move. */
  gameweek_in_progress?: GameweekProgress | null;
}

export interface GameweekProgress {
  id: number;
  name: string;
  matches_played: number;
  matches_started: number;
  matches_total: number;
}

export interface PipelineState {
  last_fetch: string | null;
  data_health?: DataHealth;
  current_gw: { id: number; name: string } | null;
  next_gw: { id: number; name: string; deadline_time: string } | null;
}

export interface SquadResponse {
  generated_at: string;
  projector: "naive" | "ml";
  pipeline_state: PipelineState;
  squad: Squad;
}

export interface TargetSquadResponse {
  generated_at: string;
  horizon: number;
  quality_weight: number;
  pipeline_state: PipelineState;
  budget_tenths: number;
  squad: Squad;
}

export interface OptimizedSquadResponse {
  projector: "naive" | "ml";
  budget_tenths: number;
  squad: Squad;
}

export interface ProjectionsResponse {
  generated_at: string;
  projector: "naive" | "ml";
  count: number;
  projections: Player[];
}

export interface StatusResponse {
  generated_at: string;
  projector: "naive" | "ml";
  pipeline_state: PipelineState;
}

export interface EntrySquadResponse {
  entry_id: number;
  manager_name: string;
  team_name: string;
  source_gw: number;
  bank: number;         // tenths
  squad_value: number;  // tenths
  player_ids: number[]; // 15 entries
  captain_id: number | null;
  vice_id: number | null;
}

export interface TransferRequestBody {
  existing_ids: number[];
  bank_tenths: number;
  free_transfers: number;
  max_transfers?: number | null;
  ignore_hit_cost?: boolean;
}

export interface ChipAdvice {
  chip: "triple_captain" | "bench_boost";
  label: string;
  recommended: boolean;
  headline: string;
  detail: string;
  value: number;
  benchmark: number;
}

export interface TransferPlanResponse {
  chips?: ChipAdvice[];
  old_squad_ids: number[];
  transfers_made: number;
  free_transfers: number;
  paid_hits: number;
  hit_cost: number;
  projected_points: number;
  bank_before: number;
  bank_after: number;
  transfers_in: Player[];
  transfers_out: Player[];
  new_squad: Squad;
}

/** One scored gameweek: what was recommended before the deadline, and what
 *  actually happened. Written before kickoff, so it cannot be fitted after. */
export interface TrackedGameweek {
  gw: number;
  name: string | null;
  deadline: string | null;
  frozen_at: string | null;
  points: number;
  fpl_average: number | null;
  beat_average: number | null;
  captain_points: number;
  captain_blanked: boolean;
  points_left_on_bench: number;
  scores_final: boolean;
  mae: number | null;
  spearman: number | null;
  players_appeared: number;
  hits: PlayerOutcome[];
  misses: PlayerOutcome[];
}

export interface PlayerOutcome {
  web_name: string;
  team_short: string;
  position: Position;
  projected: number;
  actual: number;
  minutes: number;
}

export interface AccuracyResponse {
  generated_at: string | null;
  totals: {
    gameweeks_scored: number;
    total_points?: number | null;
    mean_points?: number | null;
    mean_fpl_average?: number | null;
    weeks_beating_average?: number;
    weeks_rated?: number;
    mean_mae?: number | null;
    mean_spearman?: number | null;
  };
  gameweeks: TrackedGameweek[];
  pending: { gw: number; name: string | null; deadline: string | null }[];
}
