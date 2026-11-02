import {describe, expect, it} from 'vitest';
import {changeVerdict, metricColumns, metricFormatter, periodLabel} from './metricFormat';
import type {Evidence, Investigation} from './types';

const window = (season: number, weeks: [number, number] = [1, 22]) => ({season, weeks});
const range = (start: number, end: number) => ({team: 'CHI', baseline: window(start), comparison: window(end),
  season_type: 'REG', comparison_design: 'full_seasons'}) as Investigation['run']['scope'];
const metric = {evidence_id: 'epa', metric: 'epa_per_play', label: 'EPA/play', unit: 'per play', value: 0.128,
  baseline_value: -0.049, comparison_value: 0.0793, sample_size: 1096,
  context: {baseline_sample: 1089, comparison_sample: 1096}} as Evidence;

describe('metricFormatter', () => {
  it('shows shares as percentages and their change in percentage points', () => {
    const format = metricFormatter({metric: 'success_rate', unit: 'rate', value: 0.0443, baseline_value: 0.3884, comparison_value: 0.4327});
    expect(format.value(0.4327)).toBe('43.3%');
    expect(format.change(0.0443)).toBe('+4.4 pct pts');
  });

  it('never exposes raw unit names', () => {
    const format = metricFormatter({metric: 'cpoe', unit: 'percentage_points', value: -3.4033, baseline_value: -0.1022, comparison_value: -3.5054});
    expect(format.value(-3.5054)).toBe('-3.5 pct pts');
    expect(format.change(-3.4033)).toBe('-3.4 pct pts');
  });

  it('keeps a metric at one precision so values agree', () => {
    const format = metricFormatter(metric);
    expect(format.value(0.0793)).toBe('0.079');
    expect(format.value(-0.049)).toBe('-0.049');
    expect(format.change(0.128)).toBe('+0.128 per play');
  });

  it('does not read per-minute rates or out-of-range values as percentages', () => {
    expect(metricFormatter({metric: 'usage_proxy', unit: 'rate', value: 0.02, baseline_value: 0.61, comparison_value: 0.63}).value(0.63)).toBe('0.630');
    expect(metricFormatter({metric: 'field_goal_pct', unit: 'rate', value: 2, baseline_value: 44, comparison_value: 46}).value(46)).toBe('46');
  });
});

describe('metricColumns', () => {
  const label = (season: number) => String(season);

  it('uses real period names with a sample for each one', () => {
    const {columns} = metricColumns(metric, [], range(2024, 2025), label);
    expect(columns).toEqual([{label: '2024', value: -0.049, sample: 1089}, {label: '2025', value: 0.0793, sample: 1096}]);
  });

  it('includes middle seasons from season-by-season evidence', () => {
    const seasonal = {evidence_id: 'mid', metric: 'seasonal_epa_per_play', label: '2024 · EPA/play', value: -0.082, sample_size: 1010} as Evidence;
    expect(metricColumns(metric, [seasonal], range(2023, 2025), label).columns.map(column => [column.label, column.value]))
        .toEqual([['2023', -0.049], ['2024', -0.082], ['2025', 0.0793]]);
  });

  it('flags a range whose middle seasons were not measured for this metric', () => {
    const result = metricColumns(metric, [], range(2023, 2025), label);
    expect(result.columns).toHaveLength(2);
    expect(result.middleSeasonsMissing).toBe(true);
  });
});

describe('periodLabel', () => {
  it('describes week windows, segments and dates', () => {
    const label = (season: number) => String(season);
    expect(periodLabel(window(2025, [1, 9]), 'before_after', label)).toBe('2025 · Wk 1–9');
    expect(periodLabel({...window(2025), segment: 'post_all_star'}, 'season_segments', label)).toBe('2025 Post All Star');
    expect(periodLabel({...window(2025), start_date: '2025-01-01', end_date: '2025-03-01'}, 'date_ranges', label)).toBe('2025-01-01 to 2025-03-01');
  });
});

describe('changeVerdict', () => {
  it('follows the metric direction and stays silent when direction is unknown', () => {
    expect(changeVerdict(-0.012, false)).toBe('Better');
    expect(changeVerdict(0.012, false)).toBe('Worse');
    expect(changeVerdict(0.012, null)).toBe('');
    expect(changeVerdict(0, true)).toBe('');
  });
});
