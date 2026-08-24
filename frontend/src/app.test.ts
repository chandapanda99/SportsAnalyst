import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';

describe('Open Sports Analyst workbench', () => {
  let mockInvestigations: Array<Record<string, unknown>>;

  beforeEach(() => {
    mockInvestigations = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'DELETE' && url.includes('/api/investigations/')) {
        const identifier = url.split('/').at(-1);
        mockInvestigations = mockInvestigations.filter((item: any) =>
          item.run.investigation_id !== identifier && item.run.parent_investigation_id !== identifier
        );
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url.includes('/evidence/')) {
        const identifier = url.split('/').at(-1)!;
        return Promise.resolve(new Response(JSON.stringify({
          evidence_id: identifier,
          label: `Evidence ${identifier}`,
          metric: 'epa_per_dropback',
          value: 0.12,
          sample_size: 50,
          caveats: []
        }), { status: 200, headers: { 'content-type': 'application/json' } }));
      }
      const body = url.endsWith('/capabilities')
        ? { providers: ['azure_foundry', 'ollama'], configured_provider: 'azure_foundry', model_configured: false, custom_analysis: false, sports: ['nfl'] }
        : url.endsWith('/datasets')
          ? [
              { dataset: 'play_by_play', season: 2024 },
              { dataset: 'rosters', season: 2024 },
              { dataset: 'injuries', season: 2024 },
              { dataset: 'play_by_play', season: 2025 }
            ]
        : url.endsWith('/sports/nfl/options')
          ? {
              sport: 'nfl', teams: [
                { value: 'KC', label: 'Kansas City Chiefs' },
                { value: 'BUF', label: 'Buffalo Bills' },
                { value: 'PHI', label: 'Philadelphia Eagles' }
              ], available_seasons: [2022, 2023, 2024, 2025],
              syncable_seasons: [2025, 2024, 2023, 2022], syncable_datasets: ['play_by_play', 'rosters', 'injuries'],
              default_metrics: ['epa_per_dropback'], week_values: [1, 2, 3, 4, 5],
              comparison_windows: [
                { value: 'full_seasons', label: 'Full seasons', description: 'Compare seasons.' },
                { value: 'week_ranges', label: 'Custom week ranges', description: 'Compare ranges.' }
              ],
              split_dimensions: [],
              metrics: [
                { value: 'epa_per_dropback', label: 'EPA/dropback', category: 'Efficiency', description: 'EPA per dropback.', available_seasons: [2024, 2025] },
                { value: 'success_rate', label: 'Success rate', category: 'Efficiency', description: 'Share with positive EPA.', available_seasons: [2024, 2025] }
              ]
            }
          : url.endsWith('/investigations')
            ? mockInvestigations
            : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
    }));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders the scoped investigation entry point without model credentials', async () => {
    render(App);
    expect(await screen.findByText('Analyze and Discuss Football Play-by-Play Data!')).toBeTruthy();
    expect(screen.getByText('Deterministic Mode')).toBeTruthy();
    expect(screen.getByText('Define Comparison')).toBeTruthy();
    expect(screen.getByLabelText('NFL team')).toBeTruthy();
    expect(screen.getByText('Choose what to measure')).toBeTruthy();
    expect(screen.getByText('Manage Local nflverse Data')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Start investigation/i })).toBeTruthy();
  });

  it('starts with no implied team and supports searchable team selection', async () => {
    render(App);
    const combobox = await screen.findByRole('combobox', { name: 'NFL team' }) as HTMLInputElement;
    expect(combobox.value).toBe('');

    await fireEvent.focus(combobox);
    expect(await screen.findByRole('option', { name: /Buffalo Bills/ })).toBeTruthy();

    await fireEvent.input(combobox, { target: { value: 'buff' } });
    const buffalo = screen.getByRole('option', { name: /Buffalo Bills/ });
    expect(screen.queryByRole('option', { name: /Kansas City Chiefs/ })).toBeNull();

    await fireEvent.mouseDown(buffalo);
    expect(combobox.value).toBe('Buffalo Bills (BUF)');
    expect(combobox.getAttribute('aria-expanded')).toBe('false');
  });

  it('cycles to a different supported analysis question', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    render(App);
    const question = screen.getByLabelText(/Your Question/i) as HTMLTextAreaElement;
    expect(question.value).toBe("Why did this team's passing efficiency change?");

    await fireEvent.click(screen.getByRole('button', { name: 'Show another example question' }));
    expect(question.value).toBe('Did this team become more consistent, or was the change concentrated in a few periods?');
  });

  it('supports explicit all-metric and recommended-metric selection', async () => {
    render(App);
    const epa = await screen.findByRole('checkbox', { name: /EPA\/dropback/ }) as HTMLInputElement;
    const successRate = screen.getByRole('checkbox', { name: /Success rate/ }) as HTMLInputElement;
    expect(epa.checked).toBe(true);
    expect(successRate.checked).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Clear All Metrics' }));
    expect(epa.checked).toBe(false);
    expect(successRate.checked).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Select All Metrics' }));
    expect(epa.checked).toBe(true);
    expect(successRate.checked).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Use Recommended Metrics' }));
    expect(epa.checked).toBe(true);
    expect(successRate.checked).toBe(false);
  });

  it('treats full seasons as an inclusive season range', async () => {
    render(App);
    const from = await screen.findByLabelText('From season') as HTMLSelectElement;
    const through = screen.getByLabelText('Through season') as HTMLSelectElement;

    await fireEvent.change(from, { target: { value: '2022' } });
    await fireEvent.change(through, { target: { value: '2025' } });

    expect(screen.getByText('Includes every season from 2022 through 2025: 2022, 2023, 2024, 2025.')).toBeTruthy();
  });

  it('keeps the data manager open and shows actual package coverage', async () => {
    render(App);
    const details = document.querySelector('details.data-manager') as HTMLDetailsElement;
    const rosters = await screen.findByLabelText(/Rosters/);

    expect(details.open).toBe(true);
    expect(screen.getByRole('option', { name: '2024 · 3/3 packages' })).toBeTruthy();
    expect(screen.getByRole('option', { name: '2025 · PBP only' })).toBeTruthy();

    await fireEvent.click(rosters);
    expect(details.open).toBe(true);
  });

  it('groups follow-ups as a saved conversation and deletes the full thread', async () => {
    mockInvestigations = [{
      run: {
        investigation_id: 'investigation-follow-up', parent_investigation_id: 'investigation-delete-me',
        question: 'Was it consistent across the sample?', created_at: '2026-08-21T13:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 18] }, comparison: { season: 2025, weeks: [1, 18] }
        }
      },
      summary: 'The follow-up found a consistent shift.', claims: [], aggregate_evidence: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true
    }, {
      run: {
        investigation_id: 'investigation-delete-me', question: 'Which games changed the most?', created_at: '2026-08-21T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 18] }, comparison: { season: 2025, weeks: [1, 18] }
        }
      },
      summary: 'Summary', claims: [], aggregate_evidence: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true
    }];
    vi.stubGlobal('confirm', vi.fn(() => true));

    render(App);
    expect(await screen.findByText('Was it consistent across the sample?')).toBeTruthy();
    expect(screen.getByText('The follow-up found a consistent shift.')).toBeTruthy();
    expect(screen.getAllByText('1 follow-up').length).toBeGreaterThan(0);
    const deleteButton = screen.getByRole('button', { name: 'Delete investigation thread: Which games changed the most?' });
    expect(deleteButton.classList.contains('delete-report')).toBe(true);
    expect(screen.getAllByRole('button', { name: /Delete investigation thread/ })).toHaveLength(1);

    await fireEvent.click(deleteButton);

    expect(fetch).toHaveBeenCalledWith('/api/investigations/investigation-delete-me', { method: 'DELETE' });
    expect(screen.queryByText('Which games changed the most?')).toBeNull();
    expect(screen.queryByText('Was it consistent across the sample?')).toBeNull();
  });

  it('selects only the clicked finding and lists all of its cited evidence', async () => {
    mockInvestigations = [{
      run: {
        investigation_id: 'investigation-evidence', question: 'What changed?', created_at: '2026-08-21T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 22] }, comparison: { season: 2025, weeks: [1, 22] }
        }
      },
      summary: 'Summary', aggregate_evidence: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true,
      claims: [
        { claim_id: 'claim-one', claim_type: 'measured', statement: 'First finding', evidence_ids: ['evidence-shared', 'evidence-one'], confidence: 'high' },
        { claim_id: 'claim-two', claim_type: 'interpretation', statement: 'Second finding', evidence_ids: ['evidence-shared', 'evidence-two'], confidence: 'high' }
      ]
    }];

    render(App);
    const first = await screen.findByRole('button', { name: 'Inspect evidence for finding 1' });
    const second = screen.getByRole('button', { name: 'Inspect evidence for finding 2' });

    await fireEvent.click(first);
    expect(await screen.findByText('2 evidence records')).toBeTruthy();
    expect(screen.getByText('Evidence evidence-shared')).toBeTruthy();
    expect(screen.getByText('Evidence evidence-one')).toBeTruthy();
    expect(first.getAttribute('aria-pressed')).toBe('true');
    expect(second.getAttribute('aria-pressed')).toBe('false');

    await fireEvent.click(second);
    expect(await screen.findByText('Evidence evidence-two')).toBeTruthy();
    expect(first.getAttribute('aria-pressed')).toBe('false');
    expect(second.getAttribute('aria-pressed')).toBe('true');
  });
});
