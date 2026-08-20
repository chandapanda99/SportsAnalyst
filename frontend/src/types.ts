export type DatasetManifest = {
  manifest_id: string; season: number; row_count: number; sha256: string; acquired_at: string;
};
export type Evidence = {
  evidence_id: string; metric?: string; label?: string; value?: number; baseline_value?: number;
  comparison_value?: number; sample_size?: number; caveats?: string[]; game_id?: string;
  play_id?: number; description?: string; epa?: number; supporting?: boolean;
};
export type Claim = { claim_id: string; claim_type: 'measured' | 'interpretation'; statement: string; evidence_ids: string[]; confidence: string };
export type Chart = { chart_id: string; title: string; specification: Record<string, unknown>; evidence_ids: string[] };
export type Investigation = {
  run: { investigation_id: string; parent_investigation_id?: string; question: string; scope: { team: string; baseline_season: number; comparison_season: number; season_type: string }; created_at: string };
  summary: string; claims: Claim[]; aggregate_evidence: Evidence[]; play_evidence: Evidence[];
  charts: Chart[]; methodological_caveats: string[]; model_id?: string; fallback_used: boolean;
};
export type Capabilities = { providers: string[]; configured_provider: string; model_configured: boolean; custom_analysis: boolean; sports: string[] };
