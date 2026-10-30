import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import Chart from './Chart.svelte';
import {compile} from 'vega-lite';
import {parse, View} from 'vega';
import {applyTeamChartPalette, chartSeriesStyles, colorContrastRatio, CHART_SURFACE_COLOR} from './teamPalettes';
import {filterMetric, comparisonRows} from './chartRows';
import {initializeBranding} from './sportsBranding';

const {embed} = vi.hoisted(() => ({embed: vi.fn(async () => ({view: {finalize: vi.fn(), resize: () => ({runAsync: async () => {}})}}))}));
vi.mock('./chartRenderer', () => ({loadChartRenderer: async () => embed}));
afterEach(() => {cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals();});

it('defers offscreen charts until needed and releases their renderer when closed', async () => {
  let visible: (entries: Array<{isIntersecting: boolean}>) => void = () => {};
  const disconnect = vi.fn();
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: typeof visible) {visible = callback;}
    observe() {}
    disconnect = disconnect;
  });
  const page = render(Chart, {props: {team: 'CHI', specification: {
    data: {values: [{season: 2024, value: .2}]}, mark: 'point',
    encoding: {x: {field: 'season'}, y: {field: 'value'}}
  }}});
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(embed).not.toHaveBeenCalled();
  visible([{isIntersecting: true}]);
  await waitFor(() => expect(embed).toHaveBeenCalledTimes(1));
  const {view} = await embed.mock.results[0].value;
  await page.unmount();
  expect(view.finalize).toHaveBeenCalledTimes(1);
  expect(disconnect).toHaveBeenCalled();
});

it('shows a compact all-season matrix instead of a single-point plot and exposes missing measurements', async () => {
  const values = [{metric: 'Total Shots', window: '2023–24', value: 169, display_value: '169', sample_size: 12}];
  const specification = {usermeta: {chartKind: 'metric-rows', displayMode: 'matrix', comparisonKind: 'period-comparison',
    seriesField: 'window', seriesLabels: ['2023–24', '2024–25', '2025–26'], expectedPeriods: ['2023–24', '2024–25', '2025–26'],
    missingPeriods: ['2024–25', '2025–26'], comparisonSummary: [{metric: 'Total Shots', category: '', availablePeriods: 1,
      cells: [{period: '2023–24', status: 'recorded', entries: [{value: '169', sample: 12, evidence_id: 'e1'}]},
        {period: '2024–25', status: 'No registered measurement', entries: []},
        {period: '2025–26', status: 'No registered measurement', entries: []}]}]}, data: {values}, vconcat: []};
  const page = render(Chart, {props: {team: '132', sport: 'soccer', specification}});
  const table = screen.getByRole('table');
  expect(table.textContent).toContain('2024–25');
  expect(table.textContent).toContain('2025–26');
  expect(table.textContent).toContain('169');
  expect(table.textContent).toContain('Sample: 12');
  expect(screen.getAllByText('No measurement')).toHaveLength(2);
  expect(screen.queryByRole('button', {name: 'Expand chart'})).toBeNull();
  expect(screen.queryByRole('button', {name: 'Explore comparable measurements'})).toBeNull();
  expect(embed).not.toHaveBeenCalled();
  await page.unmount();
  const comparable = structuredClone(specification) as any;
  comparable.data.values.push({metric: 'Total Shots', window: '2024–25', value: 180, display_value: '180', sample_size: 13});
  comparable.usermeta.comparisonSummary[0].cells[1].entries = [{value: '180', sample: 13, evidence_id: 'e2'}];
  comparable.vconcat = [{title: {text: 'Total Shots'}, data: {values: comparable.data.values}, layer: [
    {mark: {type: 'point'}, encoding: {x: {field: 'window'}, y: {field: 'value'}}}]}];
  render(Chart, {props: {team: '132', sport: 'soccer', specification: comparable}});
  expect(embed).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole('button', {name: 'Explore comparable measurements'}));
  await waitFor(() => expect(embed).toHaveBeenCalled());
  expect(screen.getByRole('button', {name: 'Hide plot'})).toBeTruthy();
});

it('renders named horizontal categories with season colours and readable exact values', async () => {
  const values = ['2023–24', '2024–25', '2025–26'].flatMap((window, i) => [
    {metric: 'Possession', category: 'Bayern Munich', window, value: 55 + i, display_value: `${55 + i}%`,
      context_label: `${window} · Home team: Bayern Munich`, sample_size: 6},
    {metric: 'Possession', category: 'Recorded Opponent', window, value: 40 + i, display_value: `${40 + i}%`,
      context_label: `${window} · Home team: Recorded Opponent`, sample_size: 2}
  ]);
  const specification = {usermeta: {chartKind: 'metric-rows', comparisonKind: 'grouped-observations', categoryLayout: 'rows',
    seriesField: 'category', seriesLabels: ['Bayern Munich', 'Recorded Opponent'], colorField: 'window',
    colorLabels: ['2023–24', '2024–25', '2025–26']}, data: {values},
    vconcat: [{title: {text: 'Possession'}, height: 240, data: {values}, layer: [
      {mark: {type: 'point', filled: true}, encoding: {x: {field: 'value', type: 'quantitative'},
        y: {field: 'category', type: 'nominal'}, yOffset: {field: 'window', type: 'nominal'},
        color: {field: 'window', type: 'nominal', legend: null}}},
      {mark: {type: 'text'}, encoding: {x: {field: 'value', type: 'quantitative'}, y: {field: 'category', type: 'nominal'},
        yOffset: {field: 'window', type: 'nominal'}, text: {field: 'display_value'}}}]}]};
  const styles = chartSeriesStyles(specification, '132', 'soccer');
  expect(new Set(styles.map(style => style.color)).size).toBe(3);
  const themed = applyTeamChartPalette(specification, '132', 'soccer') as any;
  expect(themed.vconcat[0].height).toBe(240);
  expect(themed.vconcat[0].layer[0].encoding.y.field).toBe('category');
  expect(themed.vconcat[0].layer[1].mark).toMatchObject({align: 'left', dy: 0});
  const view = new View(parse(compile(themed).spec), {renderer: 'none'});
  try {expect(await view.toSVG()).toContain('Bayern Munich');} finally {view.finalize();}
  render(Chart, {props: {team: '132', sport: 'soccer', specification}});
  expect(screen.getByLabelText('Periods legend').textContent).toContain('2024–25');
  const table = screen.getByLabelText('Exact metric comparison').textContent;
  expect(table).toContain('Bayern Munich');
  expect(table).toContain('2025–26');
  expect(table).not.toContain('Reference Period');
  expect(table).not.toContain('Home Team Id');
});

it('keeps monthly chronology separate from window colours and avoids a misleading endpoint comparison', () => {
  const specification = {usermeta: {chartKind: 'metric-rows', comparisonKind: 'monthly-trend',
    seriesField: 'observation', seriesLabels: ['2024-09', '2025-03'], colorField: 'window',
    colorLabels: ['Reference Period', 'Comparison Period']},
    data: {values: [{metric: 'Possession', observation: '2024-09', window: 'Reference Period', value: .6, sample_size: 3},
      {metric: 'Possession', observation: '2025-03', window: 'Comparison Period', value: .5, sample_size: 2}]},
    vconcat: [{title: {text: 'Possession'}, layer: [{mark: {type: 'point'}, encoding: {
      x: {field: 'observation'}, y: {field: 'value'}, color: {field: 'window'}}}]}]};
  expect(chartSeriesStyles(specification, '132', 'soccer').map(item => item.label)).toEqual(['Reference Period', 'Comparison Period']);
  const rows = comparisonRows(specification);
  expect(rows[0].entries.map(item => item.series)).toEqual(['2024-09', '2025-03']);
  expect(rows[0].change).toBeNull();
  const themed = applyTeamChartPalette(specification, '132', 'soccer') as any;
  expect(themed.vconcat[0].layer[0].encoding.color.scale.domain).toEqual(['Reference Period', 'Comparison Period']);
});

it('offers exact comparisons, percentage-point changes, metric filtering and expanded charts', async () => {
  render(Chart, {props: {team: 'KC', specification: {
    usermeta: {chartKind: 'metric-rows', metricRowCount: 2, seriesField: 'window', seriesLabels: ['2024', '2025']},
    data: {values: [
      {metric: 'Success rate', window: '2024', value: 0, display_value: '0.0%', unit: 'rate'},
      {metric: 'Success rate', window: '2025', value: .45, display_value: '45.0%', unit: 'rate'},
      {metric: 'Yards', window: '2024', value: 400, display_value: '400', unit: 'yards'},
      {metric: 'Yards', window: '2025', value: 500, display_value: '500', unit: 'yards'},
    ]},
    vconcat: [{title: {text: 'Success rate'}}, {title: {text: 'Yards'}}],
  }}});
  expect(screen.getByLabelText('Exact metric comparison').textContent).toContain('0.0%');
  expect(screen.getByLabelText('Exact metric comparison').textContent).toContain('+45 pp');
  expect(screen.getByLabelText('Exact metric comparison').textContent).toContain('+100 yards');
  await fireEvent.change(screen.getByRole('combobox', {name: 'Show metric'}), {target: {value: 'Success rate'}});
  expect(screen.getByLabelText('Exact metric comparison').textContent).not.toContain('Yards');
  await waitFor(() => expect(embed).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({vconcat: [expect.objectContaining({title: {text: 'Success rate'}})]}), expect.anything()));
  await fireEvent.click(screen.getByRole('button', {name: 'Show comparison chart'}));
  await fireEvent.click(screen.getByRole('button', {name: 'Expand chart'}));
  expect(screen.getByRole('dialog', {name: 'chart'})).toBeTruthy();
});

it('renders three-season trends with readable marks and matching, stable legends across all sports', async () => {
  await initializeBranding();
  const labels = ['2023', '2024', '2025'];
  const values = labels.flatMap((season, i) => [
    {season, metric: 'EPA/play', value: [-.049, -.082, .079][i], display_value: ['-0.049', '-0.082', '0.079'][i]},
    ...(i === 1 ? [] : [{season, metric: 'Success rate', value: [.418, .398, .458][i], display_value: ['41.8%', '39.8%', '45.8%'][i]}])
  ]);
  const spec = {
    usermeta: {chartKind: 'metric-rows', seriesField: 'season', seriesLabels: labels, metricRowCount: 2}, data: {values},
    vconcat: ['EPA/play', 'Success rate'].map(metric => ({title: {text: metric}, width: 500, height: 120,
      data: {values: values.filter(row => row.metric === metric)}, layer: [
        {mark: {type: 'point', filled: true}, encoding: {
          x: {field: 'season', type: 'ordinal'}, y: {field: 'value', type: 'quantitative'},
          color: {field: 'season', type: 'nominal', legend: null}}},
        {mark: {type: 'text', dy: -10}, encoding: {x: {field: 'season', type: 'ordinal'},
          y: {field: 'value', type: 'quantitative'}, text: {field: 'display_value'}}}
      ]})), resolve: {scale: {y: 'independent'}}
  };
  for (const [sport, team] of [['nfl', 'CHI'], ['nba', 'BOS'], ['cfb', '66'], ['soccer', '359']]) {
    const styles = chartSeriesStyles(spec, team, sport, 2025);
    const themed = applyTeamChartPalette(filterMetric(spec, 'Success rate'), team, sport, 2025);
    const plot = (themed.vconcat as any[])[0];
    expect(plot.layer[0].encoding.color.scale).toEqual({domain: labels, range: styles.map(item => item.color)});
    expect(styles.every(item => colorContrastRatio(item.color, CHART_SURFACE_COLOR) >= 3)).toBe(true);
    const view = new View(parse(compile(themed as any).spec), {renderer: 'none'});
    try {
      const svg = await view.toSVG();
      expect(svg).toContain('41.8%');
      expect(svg).not.toContain('NaN');
      expect(svg).toContain(styles[2].color);
    } finally {view.finalize();}
  }
  const result = render(Chart, {props: {team: 'CHI', specification: spec}});
  const legend = screen.getByLabelText('Seasons legend');
  expect(legend.textContent).not.toMatch(/Reference|Comparison/);
  expect(legend.querySelectorAll('svg')).toHaveLength(3);
  const styles = chartSeriesStyles(spec, 'CHI');
  expect(Array.from(legend.querySelectorAll('svg')).map(svg => svg.style.color)).toEqual(styles.map(item => {
    const element = document.createElement('div'); element.style.color = item.color; return element.style.color;
  }));
  await result.unmount();
});
