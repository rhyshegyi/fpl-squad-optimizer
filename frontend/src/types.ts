export type Position = "GK" | "DEF" | "MID" | "FWD";

export interface Player {
  player_id: number;
  web_name: string;
  team_id: number;
  team_short: string;
  position: Position;
  now_cost: number;         // tenths of £m
  projected_points: number;
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

export interface PipelineState {
  last_fetch: string | null;
  current_gw: { id: number; name: string } | null;
  next_gw: { id: number; name: string; deadline_time: string } | null;
}

export interface SquadResponse {
  generated_at: string;
  projector: "naive" | "ml";
  pipeline_state: PipelineState;
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
