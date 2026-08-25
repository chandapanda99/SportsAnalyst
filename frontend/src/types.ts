export type DatasetManifest = {
  manifest_id: string; dataset: string; season: number; row_count: number; sha256: string; acquired_at: string; columns: string[];
};
export type AnalysisWindow = { season: number; weeks: [number, number] };
export type TeamOption = { value: string; label: string };
export type MetricOption = {
  value: string; label: string; category: string; description: string; analysis_domain: 'passing' | 'rushing' | 'offense'; available_seasons: number[];
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
  analysis_domains: Array<{ value: 'passing' | 'rushing' | 'offense'; label: string; description: string }>;
  default_metrics_by_domain: Record<string, string[]>;
  split_dimensions: SplitDimensionOption[];
  comparison_windows: ComparisonWindowOption[];
  week_values: number[];
  syncable_datasets: string[];
  dataset_min_seasons: Record<string, number | null>;
};
export type InvestigationRequest = {
  question: string;
  analysis_domain: 'passing' | 'rushing' | 'offense';
  scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: 'REG' | 'POST' | 'ALL'; comparison_design: 'full_seasons' | 'week_ranges' | 'before_after' };
  metrics: string[];
  splits: string[];
};
export type Evidence = {
  evidence_id: string; metric?: string; label?: string; value?: number; baseline_value?: number;
  comparison_value?: number; sample_size?: number; caveats?: string[]; game_id?: string;
  play_id?: number; season?: number; team?: string; description?: string; epa?: number; supporting?: boolean;
  visualization?: PlayVisualization;
};
export type PlayVisualization = {
  week?: number; quarter?: number; clock?: string; down?: number; yards_to_go?: number; yardline_100?: number;
  possession_team?: string; defensive_team?: string; possession_score?: number; defensive_score?: number;
  possession_timeouts?: number; defensive_timeouts?: number; score_differential?: number; goal_to_go?: boolean; play_type?: string;
  formation?: string; personnel?: string; defensive_personnel?: string; shotgun?: boolean; no_huddle?: boolean; pass_length?: string;
  pass_location?: string; run_location?: string; run_gap?: string; air_yards?: number; yards_after_catch?: number;
  yards_gained?: number; passer?: string; receiver?: string; rusher?: string; touchdown?: boolean; turnover?: boolean;
  sack?: boolean; penalty?: boolean; first_down?: boolean; win_probability?: number; win_probability_added?: number;
  defenders_in_box?: number; pass_rushers?: number; route?: string; coverage_type?: string; man_zone?: string;
  pressure?: boolean; time_to_throw?: number; motion?: boolean; play_action?: boolean; rpo?: boolean; screen?: boolean;
  catchable_ball?: boolean; receiver_drop?: boolean; starting_hash?: string; qb_location?: string;
  offense_backfield_count?: number; defense_box_count?: number; blitzers?: number; trick_play?: boolean;
  qb_out_of_pocket?: boolean; interception_worthy?: boolean; throw_away?: boolean; read_thrown?: string;
  contested_ball?: boolean; created_reception?: boolean; qb_sneak?: boolean; qb_fault_sack?: boolean;
  offense_names?: string[]; offense_positions?: string[]; defense_names?: string[]; defense_positions?: string[];
};
export type Claim = { claim_id: string; claim_type: 'measured' | 'interpretation'; statement: string; evidence_ids: string[]; confidence: string };
export type Chart = { chart_id: string; title: string; specification: Record<string, unknown>; evidence_ids: string[] };
export type Investigation = {
  run: { investigation_id: string; parent_investigation_id?: string; question: string; analysis_domain?: 'passing' | 'rushing' | 'offense'; metrics?: string[]; splits?: string[]; scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: string; comparison_design?: 'full_seasons' | 'week_ranges' | 'before_after' }; created_at: string };
  summary: string; claims: Claim[]; aggregate_evidence: Evidence[]; play_evidence: Evidence[];
  charts: Chart[]; methodological_caveats: string[]; model_id?: string; fallback_used: boolean;
};
export type Capabilities = { providers: string[]; configured_provider: string; model_configured: boolean; custom_analysis: boolean; sports: string[] };
