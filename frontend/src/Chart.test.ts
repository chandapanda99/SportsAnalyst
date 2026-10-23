import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import Chart from './Chart.svelte';

const {embed} = vi.hoisted(() => ({embed: vi.fn(async () => ({view: {finalize: vi.fn(), resize: () => ({runAsync: async () => {}})}}))}));
vi.mock('./chartRenderer', () => ({loadChartRenderer: async () => embed}));
afterEach(() => {cleanup(); vi.clearAllMocks();});

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
