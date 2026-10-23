export interface MetricValue {metric: string; value: number; display_value?: string; unit?: string; [key: string]: unknown}
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
    const percentage = ['percentage', 'rate'].includes(first.unit ?? '') && entries.every(row => Math.abs(row.value) <= 1);
    const change = (last.value - first.value) * (percentage ? 100 : 1);
    return {metric, entries: entries.map(row => ({series: String(row[field]), value: row.display_value ?? String(row.value)})),
      change: entries.length > 1 ? `${change > 0 ? '+' : ''}${Number(change.toFixed(3))}${percentage ? ' pp' : first.unit ? ` ${first.unit}` : ''}` : null};
  });
}

export function filterMetric(spec: Record<string, unknown>, metric: string) {
  if (!metric) return spec;
  return {...spec, data: {...spec.data as object, values: ((spec.data as {values?: MetricValue[]})?.values ?? []).filter(row => row.metric === metric)},
    vconcat: (spec.vconcat as {title?: {text?: string}}[] | undefined)?.filter(row => row.title?.text === metric)};
}
