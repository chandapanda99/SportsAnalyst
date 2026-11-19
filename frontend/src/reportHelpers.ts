import type {Evidence, Investigation} from './types';

/** A request for a report's first finding evidence, started while the report was still loading. */
export type PrefetchedEvidence = {investigationId: string; claimId: string; request: Promise<Evidence[]>};

/** The headline metrics a report lists first: up to six, one per metric in a head-to-head range. */
export function keyMetrics(result: Investigation) {
  const selected = new Set(result.run.metrics ?? []);
  const metrics = result.aggregate_evidence.filter(item => item.baseline_value != null && item.comparison_value != null && (!selected.size || selected.has(item.metric ?? '')));
  if (!result.run.comparison_subject) return metrics.slice(0, 6);
  // A head-to-head season range has one record per season; one card lists them all.
  const byMetric = new Map<string, Evidence>();
  for (const item of metrics) if (!byMetric.has(item.metric ?? '')) byMetric.set(item.metric ?? '', item);
  return [...byMetric.values()].slice(0, 6);
}

export function chartGuidance(specification: Record<string, unknown>) {
  const usermeta = specification.usermeta as { chartKind?: string } | undefined;
  if (usermeta?.chartKind === 'metric-rows') {
    return ''; // The chart owns its guidance and matching series legend.
  }
  const encoding = specification.encoding as Record<string, unknown> | undefined;
  const x = encoding?.x as Record<string, unknown> | undefined;
  const color = encoding?.color as Record<string, unknown> | undefined;
  if (x?.field === 'metric' && color?.field === 'season') {
    return 'Grouped bars include every season in the selected range.';
  }
  return x?.field === 'season'
      ? 'A continuous season-by-season trend; labels mark the first and last seasons.'
      : '';
}

export function orderedCharts(charts: Investigation['charts']) {
  const isMetricComparison = (chart: Investigation['charts'][number]) =>
      (chart.specification.usermeta as { chartKind?: string } | undefined)?.chartKind === 'metric-rows';
  return [...charts].sort((left, right) => Number(isMetricComparison(left)) - Number(isMetricComparison(right)));
}

export function isMetricRowChart(specification: Record<string, unknown>) {
  return (specification.usermeta as { chartKind?: string } | undefined)?.chartKind === 'metric-rows';
}

export function isTrendChart(specification: Record<string, unknown>) {
  if (isMetricRowChart(specification)) return false;
  const encoding = specification.encoding as Record<string, unknown> | undefined;
  const x = encoding?.x as { field?: string } | undefined;
  return x?.field === 'season' || x?.field === 'week';
}

export function evidenceRoleLabel(play: Evidence) {
  const labels: Record<NonNullable<Evidence['evidence_role']>, string> = {
    typical: 'Typical',
    metric_example: 'Metric example',
    supports_change: 'Supports change',
    counterexample: 'Counterexample'
  };
  return play.evidence_role ? labels[play.evidence_role] : play.supporting ? 'Support' : 'Counter';
}

export function evidenceGroups(plays: Evidence[], periods: { baseline: string; comparison: string }) {
  const definitions = [
    {key: 'baseline', label: periods.baseline},
    {key: 'comparison', label: periods.comparison},
    {key: 'legacy', label: 'Selected evidence'}
  ];
  return definitions.map((definition) => ({
    ...definition,
    plays: plays.filter((play) => definition.key === 'legacy' ? !play.window : play.window === definition.key)
  })).filter((group) => group.plays.length > 0);
}

export function evidenceCoverage(plays: Evidence[], noun: string) {
  const poolSize = Math.max(0, ...plays.map((play) => play.candidate_pool_size ?? 0));
  return poolSize
      ? `${plays.length} of ${poolSize.toLocaleString()} qualifying ${noun} selected`
      : `${plays.length} ${noun} selected`;
}

export function chatTimestamp(createdAt: string) {
  const timestamp = new Date(createdAt);
  if (Number.isNaN(timestamp.getTime())) return '--:--';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).format(timestamp);
}
