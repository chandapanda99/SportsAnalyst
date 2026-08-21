export type DatasetManifest = {
  manifest_id: string; dataset: string; season: number; row_count: number; sha256: string; acquired_at: string; columns: string[];
};
export type AnalysisWindow = { season: number; weeks: [number, number] };
export type TeamOption = { value: string; label: string };
export type MetricOption = {
  value: string; label: string; category: string; description: string; available_seasons: number[];
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
  split_dimensions: SplitDimensionOption[];
  comparison_windows: ComparisonWindowOption[];
  week_values: number[];
  syncable_datasets: string[];
};
export type InvestigationRequest = {
  question: string;
  scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: 'REG' | 'POST' | 'ALL'; comparison_design: 'full_seasons' | 'week_ranges' | 'before_after' };
  metrics: string[];
  splits: string[];
};
export type Evidence = {
  evidence_id: string; metric?: string; label?: string; value?: number; baseline_value?: number;
  comparison_value?: number; sample_size?: number; caveats?: string[]; game_id?: string;
  play_id?: number; description?: string; epa?: number; supporting?: boolean;
};
export type Claim = { claim_id: string; claim_type: 'measured' | 'interpretation'; statement: string; evidence_ids: string[]; confidence: string };
export type Chart = { chart_id: string; title: string; specification: Record<string, unknown>; evidence_ids: string[] };
export type Investigation = {
  run: { investigation_id: string; parent_investigation_id?: string; question: string; scope: { team: string; baseline: AnalysisWindow; comparison: AnalysisWindow; season_type: string; comparison_design?: 'full_seasons' | 'week_ranges' | 'before_after' }; created_at: string };
  summary: string; claims: Claim[]; aggregate_evidence: Evidence[]; play_evidence: Evidence[];
  charts: Chart[]; methodological_caveats: string[]; model_id?: string; fallback_used: boolean;
};
export type Capabilities = { providers: string[]; configured_provider: string; model_configured: boolean; custom_analysis: boolean; sports: string[] };
