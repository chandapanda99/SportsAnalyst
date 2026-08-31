export type DatasetManifest = {
  manifest_id: string; sport: string; dataset: string; season: number; row_count: number; sha256: string; acquired_at: string; columns: string[];
};
export type AnalysisWindow = { season: number; weeks: [number, number]; segment?: string };
export type TeamOption = { value: string; label: string };
export type PlayerOption = {
  player_id: string;
  name: string;
  teams: string[];
  positions: string[];
  seasons: number[];
  seasons_by_domain?: Record<string, number[]>;
};
export type AnalysisSubject = { type: 'team' | 'player'; id: string; team_id?: string; display_name?: string };
export type MetricOption = {
  value: string; label: string; category: string; description: string; analysis_domain: string; available_seasons: number[]; subject_types?: string[];
};
export type SplitDimensionOption = {
  value: string; label: string; description: string; available_seasons: number[];
};
export type ComparisonWindowOption = { value: string; label: string; description: string };
export type AnalysisOptions = {
  sport: string;
  teams: TeamOption[];
  available_seasons: number[];
  syncable_seasons: number[];
  metrics: MetricOption[];
  default_metrics: string[];
  analysis_domains: Array<{ value: string; label: string; description: string; subject_type?: string }>;
  default_metrics_by_domain: Record<string, string[]>;
  split_dimensions: SplitDimensionOption[];
  comparison_windows: ComparisonWindowOption[];
  week_values: number[];
  syncable_datasets: string[];
  dataset_min_seasons: Record<string, number | null>;
  dataset_available_seasons?: Record<string, number[]>;
  subject_types?: Array<{value: 'team' | 'player'; label: string}>;
  season_segments?: Array<{value: string; label: string; description: string}>;
  segment_availability?: Record<string, string[]>;
  optional_capabilities?: Record<string, boolean>;
};
export type InvestigationRequest = {
  sport: string;
  subject: AnalysisSubject;
  question: string;
  analysis_domain: string;
  scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: 'REG' | 'POST' | 'ALL'; comparison_design: string };
  metrics: string[];
  splits: string[];
};
export type Evidence = {
  evidence_id: string; metric?: string; label?: string; value?: number; baseline_value?: number;
  comparison_value?: number; sample_size?: number; caveats?: string[]; game_id?: string;
  play_id?: number; season?: number; team?: string; description?: string; epa?: number; metric_value?: number; supporting?: boolean;
  window?: 'baseline' | 'comparison'; evidence_role?: 'typical' | 'metric_example' | 'supports_change' | 'counterexample';
  selection_reason?: string; selection_metric?: string; candidate_pool_size?: number; selector_version?: string;
  visualization?: PlayVisualization;
};
export type PlayVisualization = {
  sport?: string;
  source_packages?: string[];
  week?: number; quarter?: number; clock?: string; down?: number; yards_to_go?: number; yardline_100?: number;
  possession_team?: string; defensive_team?: string; possession_score?: number; defensive_score?: number;
  possession_timeouts?: number; defensive_timeouts?: number; score_differential?: number; goal_to_go?: boolean; play_type?: string;
  formation?: string; personnel?: string; defensive_personnel?: string; shotgun?: boolean; no_huddle?: boolean; pass_length?: string;
  pass_location?: string; run_location?: string; run_gap?: string; air_yards?: number; yards_after_catch?: number;
  yards_gained?: number; passer?: string; receiver?: string; rusher?: string; touchdown?: boolean; turnover?: boolean;
  complete_pass?: boolean; interception?: boolean; fumble?: boolean; fumble_lost?: boolean; return_yards?: number;
  return_team?: string; turnover_player?: string; recovery_player?: string; recovery_team?: string; recovery_yards?: number;
  sack?: boolean; penalty?: boolean; first_down?: boolean; win_probability?: number; win_probability_added?: number;
  defenders_in_box?: number; pass_rushers?: number; route?: string; coverage_type?: string; man_zone?: string;
  pressure?: boolean; time_to_throw?: number; motion?: boolean; play_action?: boolean; rpo?: boolean; screen?: boolean;
  catchable_ball?: boolean; receiver_drop?: boolean; starting_hash?: string; qb_location?: string;
  offense_backfield_count?: number; defense_box_count?: number; blitzers?: number; trick_play?: boolean;
  qb_out_of_pocket?: boolean; interception_worthy?: boolean; throw_away?: boolean; read_thrown?: string;
  contested_ball?: boolean; created_reception?: boolean; qb_sneak?: boolean; qb_fault_sack?: boolean;
  offense_names?: string[]; offense_positions?: string[]; defense_names?: string[]; defense_positions?: string[];
  period?: number; event_type?: string; action_type?: string; player_id?: string; player_name?: string; team_id?: string;
  team_abbreviation?: string; home_team_abbreviation?: string; away_team_abbreviation?: string; home_score?: number; away_score?: number;
  scoring_play?: boolean; shooting_play?: boolean; shot_result?: string; shot_value?: number; shot_distance?: number;
  shot_x?: number; shot_y?: number; shot_coordinate_system?: string; possession_number?: number; offense_player_ids?: string[]; defense_player_ids?: string[];
};
export type Claim = { claim_id: string; claim_type: 'measured' | 'interpretation'; statement: string; evidence_ids: string[]; confidence: string };
export type Chart = { chart_id: string; title: string; specification: Record<string, unknown>; evidence_ids: string[] };
export type Investigation = {
  run: { investigation_id: string; parent_investigation_id?: string; sport?: string; subject?: AnalysisSubject; question: string; analysis_domain?: string; metrics?: string[]; splits?: string[]; scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: string; comparison_design?: string }; created_at: string };
  summary: string; claims: Claim[]; aggregate_evidence: Evidence[]; play_evidence: Evidence[];
  charts: Chart[]; methodological_caveats: string[]; model_id?: string; fallback_used: boolean;
};
export type InvestigationSummary = Pick<Investigation, 'run' | 'summary' | 'model_id' | 'fallback_used'>;
export type Capabilities = { providers: string[]; configured_provider: string; model_configured: boolean; custom_analysis: boolean; sports: string[] };
export type SportOption = { value: string; label: string; available: boolean; live_available: boolean; live_message?: string };
