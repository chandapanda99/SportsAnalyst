import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';

describe('Open Sports Analyst workbench', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith('/capabilities')
        ? { providers: ['azure_foundry', 'ollama'], configured_provider: 'azure_foundry', model_configured: false, custom_analysis: false, sports: ['nfl'] }
        : url.endsWith('/sports/nfl/options')
          ? {
              sport: 'nfl', teams: [{ value: 'KC', label: 'Kansas City Chiefs' }], available_seasons: [2024, 2025],
              syncable_seasons: [2025, 2024], syncable_datasets: ['play_by_play', 'rosters', 'injuries'],
              default_metrics: ['epa_per_dropback'], week_values: [1, 2, 3, 4, 5],
              comparison_windows: [
                { value: 'full_seasons', label: 'Full seasons', description: 'Compare seasons.' },
                { value: 'week_ranges', label: 'Custom week ranges', description: 'Compare ranges.' }
              ],
              split_dimensions: [],
              metrics: [{ value: 'epa_per_dropback', label: 'EPA/dropback', category: 'Efficiency', description: 'EPA per dropback.', available_seasons: [2024, 2025] }]
            }
          : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the scoped investigation entry point without model credentials', async () => {
    render(App);
    expect(await screen.findByText('Ask a better football question.')).toBeTruthy();
    expect(screen.getByText('Deterministic mode')).toBeTruthy();
    expect(screen.getByText('Define the comparison')).toBeTruthy();
    expect(screen.getByLabelText('NFL team')).toBeTruthy();
    expect(screen.getByText('Choose what to measure')).toBeTruthy();
    expect(screen.getByText('Manage local nflverse data')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Run investigation/ })).toBeTruthy();
  });
});
