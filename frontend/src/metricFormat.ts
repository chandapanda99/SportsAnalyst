import type {AnalysisWindow, Evidence, Investigation} from './types';

type Scope = Investigation['run']['scope'];
type Measure = Pick<Evidence, 'metric' | 'unit' | 'value' | 'baseline_value' | 'comparison_value'>;
export type MetricColumn = {label: string; value: number | undefined; sample?: number};

// Rates that are not shares of 100, so they must not read as percentages.
const NON_SHARE_RATES = new Set(['usage_proxy']);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function decimalsFor(values: number[]) {
  if (values.every(Number.isInteger)) return 0;
  const largest = Math.max(...values.map(Math.abs));
  return largest < 1 ? 3 : largest < 100 ? 2 : 1;
}

function fixed(value: number, digits: number, signed = false) {
  return new Intl.NumberFormat(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits,
    signDisplay: signed ? 'exceptZero' : 'auto'}).format(value);
}

/** One number style per metric, shared by its period values and its change. */
export function metricFormatter(item: Measure, extraValues: Array<number | undefined> = []) {
  const known = [item.baseline_value, item.comparison_value, item.value, ...extraValues].filter(finite);
  const share = item.unit === 'rate' && !NON_SHARE_RATES.has(item.metric ?? '') && known.every(value => Math.abs(value) <= 1);
  const points = item.unit === 'percentage_points';
  const digits = decimalsFor(known.length ? known : [0]);
  const unit = (item.unit ?? '').replaceAll('_', ' ');
  return {
    value(value: number | undefined) {
      if (!finite(value)) return 'Not recorded';
      if (share) return `${fixed(value * 100, 1)}%`;
      return points ? `${fixed(value, 1)} pct pts` : fixed(value, digits);
    },
    change(value: number | undefined) {
      if (!finite(value)) return 'Not recorded';
      if (share || points) return `${fixed(share ? value * 100 : value, 1, true)} pct pts`;
      return `${fixed(value, digits, true)}${unit ? ` ${unit}` : ''}`;
    }
  };
}

export function periodLabel(window: AnalysisWindow, design: string | undefined, seasonLabel: (season: number) => string) {
  if (window.start_date) return `${window.start_date} to ${window.end_date ?? ''}`.trim();
  const season = seasonLabel(window.season);
  if (window.segment && window.segment !== 'full_season') {
    return `${season} ${window.segment.split('_').map(word => word[0].toUpperCase() + word.slice(1)).join(' ')}`;
  }
  return design === 'full_seasons' || (window.weeks[0] === 1 && window.weeks[1] === 22)
      ? season : `${season} · Wk ${window.weeks[0]}–${window.weeks[1]}`;
}

function evidenceSeason(item: Evidence) {
  const season = Number(item.context?.season ?? item.label?.split(' ·', 1)[0]);
  return Number.isInteger(season) ? season : undefined;
}

/** Every period a metric was measured in; season ranges include their middle seasons. */
export function metricColumns(metric: Evidence, evidence: Evidence[], scope: Scope, seasonLabel: (season: number) => string) {
  // Head-to-head columns are the two subjects, not two periods.
  const subjects = scope.comparison_design === 'head_to_head' && Array.isArray(metric.context?.subjects) ? metric.context.subjects : null;
  const first: MetricColumn = {label: subjects?.[0] ?? periodLabel(scope.baseline, scope.comparison_design, seasonLabel), value: metric.baseline_value,
    sample: finite(metric.context?.baseline_sample) ? metric.context.baseline_sample : undefined};
  const last: MetricColumn = {label: subjects?.[1] ?? periodLabel(scope.comparison, scope.comparison_design, seasonLabel), value: metric.comparison_value,
    sample: finite(metric.context?.comparison_sample) ? metric.context.comparison_sample : metric.sample_size};
  const start = scope.baseline.season, end = scope.comparison.season;
  if (scope.comparison_design !== 'full_seasons' || end - start < 2) return {columns: [first, last], middleSeasonsMissing: false};
  const seasonal = new Map(evidence.filter(item => item.metric === `seasonal_${metric.metric}`).map(item => [evidenceSeason(item), item]));
  const middle = Array.from({length: end - start - 1}, (_, index) => start + index + 1);
  if (!middle.some(season => seasonal.has(season))) return {columns: [first, last], middleSeasonsMissing: true};
  const columns = middle.map((season): MetricColumn => {
    const item = seasonal.get(season);
    return {label: typeof item?.context?.season_label === 'string' ? item.context.season_label : seasonLabel(season),
      value: item?.value, sample: item?.sample_size};
  });
  return {columns: [first, ...columns, last], middleSeasonsMissing: false};
}

/** A head-to-head season range pairs the two subjects separately in each season, oldest first. */
export function headToHeadSeasons(metric: Evidence, evidence: Evidence[]) {
  if (!finite(metric.context?.season)) return [];
  return evidence.filter(item => item.metric === metric.metric && finite(item.context?.season))
      .sort((a, b) => Number(a.context?.season) - Number(b.context?.season));
}

/** Who leads a head-to-head metric: the difference is second minus first. */
export function headToHeadLeader(difference: number | undefined, higherIsBetter: boolean | null | undefined, names: [string, string]) {
  const verdict = changeVerdict(difference, higherIsBetter);
  return verdict === 'Better' ? names[1] : verdict === 'Worse' ? names[0] : '';
}

export function changeVerdict(change: number | undefined, higherIsBetter: boolean | null | undefined) {
  if (higherIsBetter == null || !finite(change) || change === 0) return '';
  return (change > 0) === higherIsBetter ? 'Better' : 'Worse';
}
