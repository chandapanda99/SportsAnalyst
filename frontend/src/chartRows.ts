export interface MetricValue {metric: string; value: number; display_value?: string; unit?: string; [key: string]: unknown}

export function chartComparisonKind(spec: Record<string, unknown>) {
  const meta = spec.usermeta as {comparisonKind?: string; seriesField?: string} | undefined;
  return meta?.comparisonKind ?? (meta?.seriesField === 'season' ? 'season-trend' : 'period-comparison');
}

export function chartSeriesLabels(spec: Record<string, unknown>): string[] {
  const meta = spec.usermeta as {seriesField?: string; seriesLabels?: string[]; colorField?: string; colorLabels?: string[]} | undefined;
  const values = (spec.data as {values?: MetricValue[]})?.values ?? [];
  return [...new Set([...(meta?.colorLabels ?? meta?.seriesLabels ?? []).map(String),
    ...values.map(row => String(row[meta?.colorField ?? meta?.seriesField ?? 'window']))])];
}

export function chartGuidance(spec: Record<string, unknown>): string {
  const meta = spec.usermeta as {chartKind?: string; description?: string} | undefined;
  if (meta?.chartKind !== 'metric-rows') return '';
  if (meta.description) return meta.description;
  return `Each metric has its own vertical scale. ${chartComparisonKind(spec) === 'season-trend'
    ? 'Seasons run left to right.' : 'Compare the selected periods left to right.'} Values are labelled directly; hover or open exact values for details.`;
}

export function comparisonRows(spec: Record<string, unknown>) {
  const meta = spec.usermeta as {chartKind?: string; seriesField?: string; seriesLabels?: string[]} | undefined;
  if (meta?.chartKind !== 'metric-rows' || !meta.seriesField) return [];
  const field = meta.seriesField;
  const values = ((spec.data as {values?: MetricValue[]})?.values ?? [])
    .filter(row => typeof row.metric === 'string' && typeof row.value === 'number' && Number.isFinite(row.value));
  return [...new Set(values.map(row => row.metric))].map(metric => {
    const entries = values.filter(row => row.metric === metric).sort((a, b) =>
      (meta.seriesLabels?.indexOf(String(a[field])) ?? 0) - (meta.seriesLabels?.indexOf(String(b[field])) ?? 0));
    const first = entries[0], last = entries.at(-1)!;
    const percentage = ['percentage', 'rate', 'proportion'].includes(first.unit ?? '') && entries.every(row => Math.abs(row.value) <= 1);
    const change = (last.value - first.value) * (percentage ? 100 : 1);
    return {metric, entries: entries.map(row => ({series: String(row[field]), value: (row.display_value ?? String(row.value)).replace(/^\+/, ''),
      context: typeof row.context_label === 'string' && row.context_label !== 'Not recorded' ? row.context_label : '',
      sample: typeof row.sample_size === 'number' ? row.sample_size : undefined})),
      change: entries.length > 1 && !['grouped-observations', 'monthly-trend'].includes(chartComparisonKind(spec))
        ? `${change > 0 ? '+' : ''}${Number(change.toFixed(3))}${percentage || ['percent_points', 'percentage_points'].includes(first.unit ?? '') ? ' pp' : first.unit ? ` ${first.unit}` : ''}` : null};
  });
}

export function filterMetric(spec: Record<string, unknown>, metric: string) {
  if (!metric) return spec;
  return {...spec, data: {...spec.data as object, values: ((spec.data as {values?: MetricValue[]})?.values ?? []).filter(row => row.metric === metric)},
    vconcat: (spec.vconcat as {title?: {text?: string}}[] | undefined)?.filter(row => row.title?.text === metric)};
}
