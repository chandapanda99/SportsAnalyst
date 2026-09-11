import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';

describe('Open Sports Analyst workbench', () => {
  let mockInvestigations: Array<Record<string, unknown>>;

  beforeEach(() => {
    mockInvestigations = [];
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value)});
    vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'DELETE' && url.includes('/api/investigations/')) {
        const identifier = url.split('/').at(-1);
        mockInvestigations = mockInvestigations.filter((item: any) =>
          item.run.investigation_id !== identifier && item.run.parent_investigation_id !== identifier
        );
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (init?.method === 'POST' && url.endsWith('/evidence/batch')) {
        const identifiers = JSON.parse(String(init.body)).evidence_ids as string[];
        return Promise.resolve(new Response(JSON.stringify(identifiers.map((identifier) => ({
          evidence_id: identifier,
          label: `Evidence ${identifier}`,
          metric: 'epa_per_dropback',
          value: 0.12,
          sample_size: 50,
          caveats: []
        }))), { status: 200, headers: { 'content-type': 'application/json' } }));
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
      if (init?.method === 'POST' && url.endsWith('/investigations')) {
        return Promise.resolve(new Response(JSON.stringify({ investigation_id: 'investigation-running' }), {
          status: 200, headers: { 'content-type': 'application/json' }
        }));
      }
      if (init?.method === 'POST' && /\/api\/datasets\/[^/]+\/sync$/.test(url)) {
        return Promise.resolve(new Response(JSON.stringify({ job_id: 'sync-running', timeout_seconds: 640 }), {
          status: 202, headers: { 'content-type': 'application/json' }
        }));
      }
      if (url.endsWith('/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          stage: 'pending', message: 'Investigation is still running', progress: 0.75
        }), { status: 200, headers: { 'content-type': 'application/json' } }));
      }
      if (url.includes('/metrics/')) return Promise.resolve(new Response(JSON.stringify({label: 'EPA per dropback', interpretation: 'Average change in expected points per dropback.', qualifying_plays: 'Quarterback dropbacks with recorded EPA.', formula: 'mean(epa)', higher_is_better: true, limitations: ['Describes outcomes rather than individual responsibility.']})));
      if (url.endsWith('/thread')) {
        const identifier = url.split('/').at(-2);
        const selected = mockInvestigations.find((item: any) => item.run.investigation_id === identifier) as any;
        const rootId = selected?.run.parent_investigation_id ?? identifier;
        return Promise.resolve(new Response(JSON.stringify(mockInvestigations.filter((item: any) =>
          item.run.investigation_id === rootId || item.run.parent_investigation_id === rootId
        )), { status: 200, headers: { 'content-type': 'application/json' } }));
      }
      const investigationMatch = url.match(/\/api\/investigations\/([^/?]+)$/);
      if (!init?.method && investigationMatch) {
        const selected = mockInvestigations.find((item: any) => item.run.investigation_id === investigationMatch[1]);
        return Promise.resolve(new Response(JSON.stringify(selected ?? {}), {
          status: selected ? 200 : 404, headers: { 'content-type': 'application/json' }
        }));
      }
      const body = url.endsWith('/capabilities')
        ? { providers: ['azure_foundry', 'ollama'], configured_provider: 'azure_foundry', model_configured: false, custom_analysis: false, sports: ['nfl', 'nba'] }
        : url.endsWith('/sports')
          ? [
              { value: 'nfl', label: 'NFL', available: true, live_available: false },
              { value: 'nba', label: 'NBA', available: true, live_available: false }
            ]
        : url.includes('/sports/nfl/players')
          ? [
              { player_id: '00-0033873', name: 'Patrick Mahomes', teams: ['KC'], positions: ['QB'], seasons: [2024, 2025] },
              { player_id: '00-0036322', name: 'Justin Jefferson', teams: ['MIN'], positions: ['WR'], seasons: [2024, 2025] }
            ]
        : url.includes('/sports/nba/players')
          ? [
              { player_id: '4065648', name: 'Jayson Tatum', teams: ['BOS'], positions: ['SF'], seasons: [2024] },
              { player_id: '3917376', name: 'Jaylen Brown', teams: ['BOS'], positions: ['SG'], seasons: [2024, 2025] }
            ]
        : url.endsWith('/sports/nba/options')
          ? {
              sport: 'nba', teams: [{ value: 'BOS', label: 'Boston Celtics' }], available_seasons: [2024, 2025],
              data_setup: {label: 'Basketball essentials', description: 'Team and player comparisons.', required_datasets: ['play_by_play', 'schedules', 'team_boxscores', 'player_boxscores'], recommended_datasets: [], descriptions: {}},
              syncable_seasons: [2025, 2024], syncable_datasets: ['play_by_play', 'schedules', 'team_boxscores', 'player_boxscores', 'lineups', 'stats_rosters', 'stats_game_rosters', 'player_crosswalk'],
              dataset_min_seasons: { play_by_play: 2002, schedules: 2002, team_boxscores: 2002, player_boxscores: 2002, lineups: 2008, stats_rosters: 1997, stats_game_rosters: 1997, player_crosswalk: 2026 },
              dataset_available_seasons: { play_by_play: [2024, 2025], schedules: [2024, 2025], team_boxscores: [2024, 2025], player_boxscores: [2024, 2025], lineups: [2024, 2025], stats_rosters: [2024, 2025], stats_game_rosters: [2024, 2025], player_crosswalk: [2026] },
              default_metrics: ['points_per_game'], week_values: [], subject_types: [{ value: 'team', label: 'Team' }, { value: 'player', label: 'Player' }],
              comparison_windows: [
                { value: 'full_seasons', label: 'Full season range', description: 'Compare seasons.' },
                { value: 'season_segments', label: 'Season segments', description: 'Compare segments.' }
              ],
              season_segments: [
                { value: 'full_season', label: 'Full season', description: 'All games.' },
                { value: 'regular_season', label: 'Regular season', description: 'Regular season.' },
                { value: 'post_all_star', label: 'Post-All-Star', description: 'After the break.' }
              ],
              segment_availability: { '2024': ['full_season', 'regular_season', 'post_all_star'], '2025': ['full_season', 'regular_season', 'post_all_star'] },
              split_dimensions: [], optional_capabilities: { live_nba_stats: false },
              analysis_domains: [
                { value: 'offense', label: 'Offense', description: 'Team offense.', subject_type: 'team' },
                { value: 'scoring', label: 'Scoring', description: 'Player scoring.', subject_type: 'player' }
              ],
              default_metrics_by_domain: { offense: ['points_per_game'], scoring: ['points_per_game'] },
              metrics: [
                { value: 'points_per_game', label: 'Points per game', category: 'Scoring', analysis_domain: 'offense', description: 'Points.', available_seasons: [2024, 2025], subject_types: ['team'] },
                { value: 'points_per_game', label: 'Points per game', category: 'Scoring', analysis_domain: 'scoring', description: 'Points.', available_seasons: [2024, 2025], subject_types: ['player'] }
              ]
            }
        : url.endsWith('/datasets') || url.includes('/datasets?sport=')
          ? url.includes('sport=nba') ? [2024, 2025].flatMap(season => ['play_by_play', 'schedules', 'team_boxscores', 'player_boxscores'].map(dataset => ({dataset, season, sport: 'nba'}))) : [
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
              syncable_seasons: [2025, 2024, 2023, 2022], syncable_datasets: ['play_by_play', 'rosters', 'injuries', 'nextgen_passing'],
              dataset_min_seasons: { play_by_play: 1999, rosters: 1920, injuries: 2009, nextgen_passing: 2016 },
              default_metrics: ['epa_per_dropback'], week_values: [1, 2, 3, 4, 5],
              subject_types: [{ value: 'team', label: 'Team' }, { value: 'player', label: 'Player' }],
              comparison_windows: [
                { value: 'full_seasons', label: 'Full seasons', description: 'Compare seasons.' },
                { value: 'week_ranges', label: 'Custom week ranges', description: 'Compare ranges.' }
              ],
              split_dimensions: [
                { value: 'down', label: 'Down', description: 'Compare by down.', available_seasons: [2024, 2025] }
              ],
              analysis_domains: [
                { value: 'passing', label: 'Passing', description: 'Quarterback dropbacks.', subject_type: 'team' },
                { value: 'rushing', label: 'Rushing', description: 'Rushing attempts.', subject_type: 'team' },
                { value: 'offense', label: 'Overall offense', description: 'All qualifying offensive plays.', subject_type: 'team' },
                { value: 'quarterback', label: 'Quarterback', description: 'Player passing outcomes.', subject_type: 'player' },
                { value: 'receiving', label: 'Receiving', description: 'Player receiving outcomes.', subject_type: 'player' },
                { value: 'running', label: 'Rushing', description: 'Player rushing outcomes.', subject_type: 'player' }
              ],
              default_metrics_by_domain: {
                passing: ['epa_per_dropback'], rushing: ['epa_per_rush'], offense: ['epa_per_play'],
                quarterback: ['qb_epa_per_dropback'], receiving: ['receiver_epa_per_target'], running: ['rusher_epa_per_carry']
              },
              metrics: [
                { value: 'epa_per_dropback', label: 'EPA/dropback', category: 'Efficiency', analysis_domain: 'passing', description: 'EPA per dropback.', available_seasons: [2024, 2025], subject_types: ['team'] },
                { value: 'success_rate', label: 'Success rate', category: 'Efficiency', analysis_domain: 'passing', description: 'Share with positive EPA.', available_seasons: [2024, 2025], subject_types: ['team'] },
                { value: 'epa_per_rush', label: 'EPA/rush', category: 'Rushing Efficiency', analysis_domain: 'rushing', description: 'EPA per rush.', available_seasons: [2024, 2025], subject_types: ['team'] },
                { value: 'epa_per_play', label: 'EPA/play', category: 'Overall Efficiency', analysis_domain: 'offense', description: 'EPA per play.', available_seasons: [2024, 2025], subject_types: ['team'] },
                { value: 'qb_epa_per_dropback', label: 'QB EPA/dropback', category: 'Efficiency', analysis_domain: 'quarterback', description: 'Player EPA per dropback.', available_seasons: [2024, 2025], subject_types: ['player'] },
                { value: 'receiver_epa_per_target', label: 'EPA/target', category: 'Efficiency', analysis_domain: 'receiving', description: 'Player EPA per target.', available_seasons: [2024, 2025], subject_types: ['player'] },
                { value: 'rusher_epa_per_carry', label: 'EPA/carry', category: 'Efficiency', analysis_domain: 'running', description: 'Player EPA per carry.', available_seasons: [2024, 2025], subject_types: ['player'] }
              ]
            }
          : url.endsWith('/investigations') || url.includes('/investigations?sport=')
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
    expect(await screen.findByText('Football analysis')).toBeTruthy();
    expect(screen.getByText('Deterministic Mode')).toBeTruthy();
    expect(screen.getByText('Who do you want to understand?')).toBeTruthy();
    expect(screen.getByLabelText('NFL team')).toBeTruthy();
    expect(screen.getByText('Choose what to measure')).toBeTruthy();
    expect(await screen.findByText('Data ready · Manage data')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Run analysis/i })).toBeTruthy();
  });

  it('guides an empty library through explicit quick setup and remembers onboarding dismissal', async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    let downloaded = false;
    let progress!: {onmessage: ((event: MessageEvent) => void) | null};
    vi.stubGlobal('EventSource', class {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror = null;
      constructor() { progress = this; }
      close() {}
    });
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/datasets?sport=')) return new Response(JSON.stringify(downloaded ? [2024, 2025].flatMap(season => ['play_by_play', 'rosters'].map(dataset => ({season, dataset, sport: 'nfl'}))) : []));
      if (url.endsWith('/sports/nfl/options')) {
        const options = await (await defaultFetch(input, init)).json();
        options.available_seasons = downloaded ? [2024, 2025] : [];
        options.data_setup = {label: 'Football essentials', description: 'Plays and player identities.', required_datasets: ['play_by_play'], recommended_datasets: ['rosters'], descriptions: {rosters: 'Player names and teams.'}};
        return new Response(JSON.stringify(options));
      }
      return defaultFetch(input, init);
    });
    render(App);
    expect(await screen.findByText('Football essentials')).toBeTruthy();
    expect(screen.getByRole('region', {name: 'How it works'})).toBeTruthy();
    expect(screen.queryByRole('checkbox', {name: 'Injuries'})).toBeNull();
    expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    await fireEvent.click(screen.getByRole('button', {name: 'Download 2 sources for 2 seasons'}));
    const syncCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith('/nfl/sync'))!;
    expect(JSON.parse(String(syncCall[1]?.body))).toEqual({seasons: [2025, 2024], datasets: ['play_by_play', 'rosters']});
    downloaded = true;
    await waitFor(() => expect(progress.onmessage).toBeTruthy());
    progress.onmessage?.({data: JSON.stringify({stage: 'complete', message: 'Download finished', progress: 1})} as MessageEvent);
    await fireEvent.click(await screen.findByRole('button', {name: 'Continue building analysis'}));
    expect(document.activeElement?.id).toBe('scope-heading');
    const team = screen.getByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.keyDown(team, {key: 'ArrowDown'});
    await fireEvent.keyDown(team, {key: 'Enter'});
    await waitFor(() => expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(screen.getByRole('button', {name: 'Dismiss guide'}));
    cleanup();
    render(App);
    await screen.findByText('Data ready · Manage data');
    expect(screen.queryByRole('region', {name: 'How it works'})).toBeNull();
    await fireEvent.click(screen.getByRole('button', {name: 'Getting Started'}));
    const guide = await screen.findByRole('region', {name: 'How it works'});
    expect(guide).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(guide));
    expect(screen.getByRole('button', {name: 'Getting Started'}).getAttribute('aria-expanded')).toBe('true');
  });

  it('explains readiness and retains custom metrics and questions through period and sport changes', async () => {
    render(App);
    await screen.findByRole('button', {name: /Passing.*Quarterback/});
    await fireEvent.click(screen.getByRole('button', {name: /Choose a team or player/}));
    expect(document.activeElement?.id).toBe('scope-heading');
    await fireEvent.click(screen.getByRole('button', {name: 'Customize metrics'}));
    await fireEvent.click(screen.getByRole('button', {name: 'About EPA/dropback'}));
    expect(await screen.findByText('mean(epa)')).toBeTruthy();
    expect(screen.getByText('Higher is generally better')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Close explanation'}));
    await fireEvent.click(screen.getByRole('checkbox', {name: /Success rate/}));
    await fireEvent.change(screen.getByLabelText('From season'), {target: {value: '2023'}});
    await waitFor(() => expect((screen.getByRole('checkbox', {name: /Success rate/}) as HTMLInputElement).disabled).toBe(true));
    expect((screen.getByRole('checkbox', {name: /Success rate/}) as HTMLInputElement).checked).toBe(true);
    await fireEvent.change(screen.getByLabelText('From season'), {target: {value: '2024'}});
    await waitFor(() => expect((screen.getByRole('checkbox', {name: /Success rate/}) as HTMLInputElement).disabled).toBe(false));
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'My own football question'}});
    await fireEvent.click(screen.getByRole('button', {name: /NBA.*Bulk data mode/}));
    await screen.findByRole('button', {name: /Offense.*Team offense/});
    await fireEvent.click(screen.getByRole('button', {name: 'NFL'}));
    await screen.findByRole('button', {name: /Passing.*Quarterback/});
    expect((screen.getByRole('checkbox', {name: /Success rate/}) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('Your Question:') as HTMLTextAreaElement).value).toBe('My own football question');
    await fireEvent.click(screen.getByRole('button', {name: 'Clear All Metrics'}));
    expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Choose at least one available metric to run your analysis.')).toBeTruthy();
  });

  it('waits for backend readiness before requesting the workspace catalog', async () => {
    const fetchMock = vi.mocked(fetch);
    const defaultImplementation = fetchMock.getMockImplementation()!;
    let releaseHealth!: () => void;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith('/api/health')) {
        return new Promise<Response>((resolve) => {
          releaseHealth = () => resolve(new Response(JSON.stringify({ status: 'ready' }), {
            status: 200, headers: { 'content-type': 'application/json' }
          }));
        });
      }
      return defaultImplementation(input, init);
    });

    render(App);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/health'));
    expect(fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => !url.endsWith('/api/health'))).toHaveLength(0);

    releaseHealth();
    expect(await screen.findByText('Football analysis')).toBeTruthy();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/sports/nfl/options'))).toBe(true));
  });

  it('retries and atomically displays a completed analysis when its first result fetch is not ready', async () => {
    const completed = {
      run: {
        investigation_id: 'investigation-running', sport: 'nfl',
        question: 'What changed?', created_at: '2026-09-01T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 18] }, comparison: { season: 2025, weeks: [1, 18] }
        }
      },
      summary: 'The completed analysis response is now visible.', claims: [], aggregate_evidence: [],
      play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true
    };
    const fetchMock = vi.mocked(fetch);
    const baseFetch = fetchMock.getMockImplementation()!;
    let resultAttempts = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init?.method && url === '/api/investigations/investigation-running') {
        resultAttempts += 1;
        if (resultAttempts === 1) {
          mockInvestigations = [completed];
          return Promise.resolve(new Response(JSON.stringify({detail: 'Result is still being committed'}), {
            status: 404, headers: {'content-type': 'application/json'}
          }));
        }
      }
      return baseFetch(input, init);
    });
    class CompletingEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        setTimeout(() => this.onmessage?.({data: JSON.stringify({
          stage: 'complete', message: 'Investigation ready', progress: 1
        })} as MessageEvent), 0);
      }
      close() {}
    }
    vi.stubGlobal('EventSource', CompletingEventSource);

    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.click(screen.getByRole('button', {name: /Run analysis/i}));

    expect((await screen.findAllByText('The completed analysis response is now visible.')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('What changed?').length).toBeGreaterThanOrEqual(2);
    expect(resultAttempts).toBe(2);
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'smooth' });
  });

  it('switches sports, supports NBA players, and restores the NFL draft', async () => {
    render(App);
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('nfl');
    expect(document.querySelector('main')?.classList.contains('nfl-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(false);
    const nflTeam = await screen.findByRole('combobox', { name: 'NFL team' });
    await fireEvent.focus(nflTeam);
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Kansas City Chiefs/ }));

    await fireEvent.click(screen.getByRole('button', { name: /NBA.*Bulk data mode/ }));
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('nba');
    expect(document.querySelector('main')?.classList.contains('nba-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(true);
    expect(await screen.findByText('Basketball analysis')).toBeTruthy();
    expect(screen.queryByLabelText('NFL team')).toBeNull();
    expect(screen.queryByText('EPA/dropback')).toBeNull();
    await fireEvent.click(screen.getByText(/Data ready · Manage data|Prepare your data/, {selector: 'strong'}));
    await fireEvent.click(screen.getByRole('button', {name: 'Customize data sources'}));
    expect((await screen.findByLabelText(/Player Crosswalk/) as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByLabelText(/On-court Lineups/)).toBeNull();
    expect(screen.getByText(/not offered for selected seasons/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Player' }));
    const player = await screen.findByRole('combobox', { name: 'Player' }) as HTMLInputElement;
    await fireEvent.focus(player);
    expect(await screen.findByRole('option', { name: /Jaylen Brown/i })).toBeTruthy();
    const playerRequestsBeforeTyping = vi.mocked(fetch).mock.calls
      .filter(([input]) => String(input).includes('/sports/nba/players')).length;
    await fireEvent.input(player, { target: { value: 'tatum' } });
    const playerRequestsAfterTyping = vi.mocked(fetch).mock.calls
      .filter(([input]) => String(input).includes('/sports/nba/players')).length;
    expect(playerRequestsAfterTyping).toBe(playerRequestsBeforeTyping);
    expect(screen.queryByRole('option', { name: /Jaylen Brown/i })).toBeNull();
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Jayson Tatum/ }));
    expect(player.value).toBe('Jayson Tatum · BOS');
    expect(screen.getByRole('button', {name: /Jayson Tatum's scoring.*rim pressure.*perimeter volume/i})).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Show 6 more examples'}));
    expect(screen.getByRole('button', {name: /opponent.*venue.*rest.*Jayson Tatum's scoring comparison/i})).toBeTruthy();
    expect(screen.getByRole('button', {name: 'Show fewer examples'})).toBeTruthy();
    expect(player.getAttribute('aria-invalid')).toBe('false');
    const playerSeasonSelectors = screen.getAllByLabelText('Season') as HTMLSelectElement[];
    expect(playerSeasonSelectors).toHaveLength(2);
    expect(playerSeasonSelectors.every((select) => [...select.options].map((option) => option.value).join(',') === '2024')).toBe(true);
    expect(screen.getByText('1 player seasons available')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'NFL' }));
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('nfl');
    expect(document.querySelector('main')?.classList.contains('nfl-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(false);
    const restored = await screen.findByRole('combobox', { name: 'NFL team' }) as HTMLInputElement;
    await waitFor(() => expect(restored.value).toBe('Kansas City Chiefs (KC)'));
  });

  it('switches metric domains and controls between team and player analysis', async () => {
    render(App);
    expect(await screen.findByRole('button', { name: /Passing.*Quarterback dropbacks/ })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /EPA\/dropback/ })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: 'Down' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Player' }));

    expect(await screen.findByRole('button', { name: /^Quarterback/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Passing.*Quarterback dropbacks/ })).toBeNull();
    expect(screen.getByRole('checkbox', { name: /QB EPA\/dropback/ })).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /^EPA\/dropback/ })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'Down' })).toBeNull();
    expect(screen.getByText(/Team-oriented diagnostic cuts are disabled/)).toBeTruthy();

    const player = screen.getByRole('combobox', {name: 'Player'});
    await fireEvent.focus(player);
    await fireEvent.input(player, {target: {value: 'Justin Jefferson'}});
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Justin Jefferson/}));
    expect(screen.getByRole('checkbox', {name: /EPA\/target/})).toBeTruthy();
    expect(screen.getByRole('button', {name: /Justin Jefferson's production.*target volume/i})).toBeTruthy();
    expect(screen.queryByRole('button', {name: /^Quarterback/})).toBeNull();
    expect(screen.queryByRole('button', {name: /quarterback's EPA per dropback/i})).toBeNull();
    await fireEvent.click(screen.getByRole('button', {name: 'Show 5 more examples'}));
    expect(screen.getByRole('button', {name: /reliable.*receiving trend.*recorded targets/i})).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Team' }));

    expect(await screen.findByRole('button', { name: /Passing.*Quarterback dropbacks/ })).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /QB EPA\/dropback/ })).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Down' })).toBeTruthy();
  });

  it('keeps package selection independent from local-installation badges', async () => {
    let progressUrl = '';
    class IdleEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) { progressUrl = url; }
      close() {}
    }
    vi.stubGlobal('EventSource', IdleEventSource);
    render(App);
    await fireEvent.click(await screen.findByText('Data ready · Manage data'));
    await fireEvent.click(screen.getByRole('button', {name: 'Customize data sources'}));
    const season2024 = await screen.findByRole('checkbox', { name: '2024 season' }) as HTMLInputElement;
    const season2025 = screen.getByRole('checkbox', { name: '2025 season' }) as HTMLInputElement;
    const playByPlay = await screen.findByRole('checkbox', { name: /Play By Play/ }) as HTMLInputElement;
    const rosters = screen.getByRole('checkbox', { name: /Rosters/ }) as HTMLInputElement;
    const injuries = screen.getByRole('checkbox', { name: /Injuries/ }) as HTMLInputElement;

    expect(season2024.checked).toBe(true);
    expect(season2025.checked).toBe(true);
    await fireEvent.click(season2025);

    expect(playByPlay.checked).toBe(true);
    expect(rosters.checked).toBe(false);
    expect(injuries.checked).toBe(false);
    expect(rosters.indeterminate).toBe(false);
    expect(screen.getByLabelText('Rosters local status: Installed')).toBeTruthy();

    await fireEvent.click(season2025);

    expect(playByPlay.checked).toBe(true);
    expect(playByPlay.indeterminate).toBe(false);
    expect(rosters.checked).toBe(false);
    expect(rosters.indeterminate).toBe(false);
    expect(injuries.checked).toBe(false);
    expect(injuries.indeterminate).toBe(false);
    expect(screen.getByLabelText('Rosters local status: Local 1/2')).toBeTruthy();

    const nextgen = screen.getByRole('checkbox', { name: /Nextgen Passing/ }) as HTMLInputElement;
    await fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => input.checked)).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Deselect all' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => !input.checked)).toBe(true);
    expect(screen.getByLabelText('Rosters local status: Local 1/2')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    await fireEvent.click(screen.getByRole('button', { name: /Download .* sources/ }));
    await waitFor(() => expect(progressUrl).toBe('/api/dataset-jobs/sync-running/events?timeout_seconds=640'));
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
    expect(await screen.findByText('Who do you want to understand?')).toBeTruthy();
    expect(screen.queryByText('The follow-up found a consistent shift.')).toBeNull();
    await fireEvent.click(await screen.findByText('Which games changed the most?'));
    expect(await screen.findByText('Was it consistent across the sample?')).toBeTruthy();
    expect(screen.getByText('The follow-up found a consistent shift.')).toBeTruthy();
    const messageTimes = document.querySelectorAll('.chat-message-meta time[datetime]');
    expect(messageTimes).toHaveLength(4);
    expect([...messageTimes].every((time) => /^\d{2}:\d{2}$/.test(time.textContent ?? ''))).toBe(true);
    expect(screen.getAllByText('1 follow-up').length).toBeGreaterThan(0);
    const deleteButton = screen.getByRole('button', { name: 'Delete investigation thread: Which games changed the most?' });
    expect(deleteButton.classList.contains('delete-report')).toBe(true);
    expect(screen.getAllByRole('button', { name: /Delete investigation thread/ })).toHaveLength(1);

    await fireEvent.click(deleteButton);

    expect(fetch).toHaveBeenCalledWith('/api/investigations/investigation-delete-me', { method: 'DELETE' });
    expect(screen.queryByText('Which games changed the most?')).toBeNull();
    expect(screen.queryByText('Was it consistent across the sample?')).toBeNull();
  });

  it('shows diversified representative evidence by comparison window and selection role', async () => {
    mockInvestigations = [{
      run: {
        investigation_id: 'investigation-diverse-evidence', sport: 'nfl',
        question: 'Which plays explain the change?', created_at: '2026-08-21T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 18] }, comparison: { season: 2025, weeks: [1, 18] }
        }
      },
      summary: 'Summary', claims: [], aggregate_evidence: [], charts: [], methodological_caveats: [], fallback_used: true,
      play_evidence: [{
        evidence_id: 'baseline-typical', game_id: '2024_01_KC_BAL', play_id: 11,
        description: 'A representative baseline completion.', epa: 0.08, supporting: true,
        window: 'baseline', evidence_role: 'typical', selection_reason: 'Closest to the baseline window median EPA.',
        selection_metric: 'EPA', candidate_pool_size: 160, selector_version: 'diverse-v1'
      }, {
        evidence_id: 'comparison-counter', game_id: '2025_02_BUF_KC', play_id: 24,
        description: 'A comparison-window counterexample.', epa: -1.12, supporting: false,
        window: 'comparison', evidence_role: 'counterexample', selection_reason: 'Runs against the observed improvement in EPA.',
        selection_metric: 'EPA', candidate_pool_size: 148, selector_version: 'diverse-v1'
      }]
    }];

    render(App);
    await fireEvent.click(await screen.findByText('Which plays explain the change?'));

    expect(await screen.findByText('Reference period')).toBeTruthy();
    expect(screen.getByText('Comparison window')).toBeTruthy();
    expect(screen.getByText('1 of 160 qualifying plays selected')).toBeTruthy();
    expect(screen.getByText('Typical')).toBeTruthy();
    expect(screen.getByText('Counterexample')).toBeTruthy();
    expect(screen.getByText('Runs against the observed improvement in EPA.')).toBeTruthy();
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
    await fireEvent.click(await screen.findByText('What changed?'));
    const first = await screen.findByRole('button', { name: 'Inspect evidence for finding 1' });
    const second = screen.getByRole('button', { name: 'Inspect evidence for finding 2' });

    const evidencePanel = within(document.querySelector('.desktop-evidence') as HTMLElement);
    expect(await evidencePanel.findByText('Evidence evidence-shared')).toBeTruthy();
    expect(evidencePanel.getByText('Evidence evidence-one')).toBeTruthy();
    expect(first.getAttribute('aria-pressed')).toBe('true');
    expect(second.getAttribute('aria-pressed')).toBe('false');

    await fireEvent.click(second);
    expect(await evidencePanel.findByText('Evidence evidence-two')).toBeTruthy();
    expect(evidencePanel.queryByText('Evidence evidence-one')).toBeNull();
    expect(first.getAttribute('aria-pressed')).toBe('false');
    expect(second.getAttribute('aria-pressed')).toBe('true');
  });
});
