import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
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
      if (url.endsWith('/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          stage: 'pending', message: 'Investigation is still running', progress: 0.75
        }), { status: 200, headers: { 'content-type': 'application/json' } }));
      }
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
          ? [{ player_id: '00-0033873', name: 'Patrick Mahomes', teams: ['KC'], positions: ['QB'], seasons: [2024, 2025] }]
        : url.includes('/sports/nba/players')
          ? [
              { player_id: '4065648', name: 'Jayson Tatum', teams: ['BOS'], positions: ['SF'], seasons: [2024] },
              { player_id: '3917376', name: 'Jaylen Brown', teams: ['BOS'], positions: ['SG'], seasons: [2024, 2025] }
            ]
        : url.endsWith('/sports/nba/options')
          ? {
              sport: 'nba', teams: [{ value: 'BOS', label: 'Boston Celtics' }], available_seasons: [2024, 2025],
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
    expect(await screen.findByText('Analyze and Discuss Football Play-by-Play Data!')).toBeTruthy();
    expect(screen.getByText('Deterministic Mode')).toBeTruthy();
    expect(screen.getByText('Define Comparison')).toBeTruthy();
    expect(screen.getByLabelText('NFL team')).toBeTruthy();
    expect(screen.getByText('Choose what to measure')).toBeTruthy();
    expect(screen.getByText('Manage Local nflverse Data')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Start investigation/i })).toBeTruthy();
  });

  it('shows data-library progress while the active sport catalog is loading', async () => {
    const fetchMock = vi.mocked(fetch);
    const defaultImplementation = fetchMock.getMockImplementation()!;
    let releaseOptions!: () => void;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith('/sports/nfl/options')) {
        return new Promise<Response>((resolve) => {
          releaseOptions = () => void Promise.resolve(defaultImplementation(input, init)).then(resolve);
        });
      }
      return defaultImplementation(input, init);
    });

    render(App);
    expect(await screen.findByText('Loading data catalog')).toBeTruthy();
    expect(screen.getByRole('status')).toBeTruthy();
    expect(screen.getByText('Loading data…')).toBeTruthy();

    await waitFor(() => expect(typeof releaseOptions).toBe('function'));
    releaseOptions();
    await waitFor(() => expect(screen.queryByText('Loading data catalog')).toBeNull());
    expect(screen.getByText('4 local files')).toBeTruthy();
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
    expect(await screen.findByText('Analyze and Discuss Football Play-by-Play Data!')).toBeTruthy();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/sports/nfl/options'))).toBe(true));
  });

  it('combines the animated catch loader with live investigation status', async () => {
    class IdleEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      close() {}
    }
    vi.stubGlobal('EventSource', IdleEventSource);
    render(App);

    const team = await screen.findByRole('combobox', { name: 'NFL team' });
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Kansas City Chiefs/ }));
    await fireEvent.click(screen.getByRole('button', { name: /Start investigation/i }));

    const progress = await screen.findByRole('progressbar', { name: 'Investigation progress' });
    expect(progress.getAttribute('aria-valuenow')).toBe('3');
    expect(screen.getByText('Starting investigation')).toBeTruthy();
    expect(document.querySelector<HTMLImageElement>('.catch-scene')?.getAttribute('src'))
      .toBe('/open-sports-analyst-loader.svg');
    expect(screen.getByText('Analysis still running...')).toBeTruthy();
  });

  it('uses the basketball animation for NBA loading without replacing the NFL loader', async () => {
    class IdleEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      close() {}
    }
    vi.stubGlobal('EventSource', IdleEventSource);
    render(App);

    await fireEvent.click(await screen.findByRole('button', { name: /NBA.*Bulk data mode/ }));
    const team = await screen.findByRole('combobox', { name: 'NBA team' });
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Boston Celtics/ }));
    await fireEvent.click(screen.getByRole('button', { name: /Start investigation/i }));

    expect(await screen.findByText('LIVE ANALYSIS POSSESSION')).toBeTruthy();
    expect(document.querySelector('.basketball-animation')).toBeTruthy();
    expect(document.querySelector('.catch-scene')).toBeNull();
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
    expect(question.value).toBe("What drove the change in this offense's EPA per dropback: down-to-down success, completion performance, or explosive passes?");

    await fireEvent.click(screen.getByRole('button', { name: 'Show another example question' }));
    expect(question.value).toBe('Did the passing game become consistently more efficient, or did a handful of explosive plays and outlier games drive the difference?');
  });

  it('keeps example questions aligned to sport, subject, and analysis domain', async () => {
    render(App);
    const question = await screen.findByLabelText(/Your Question/i) as HTMLTextAreaElement;

    await fireEvent.click(await screen.findByRole('button', { name: 'Player' }));
    expect(question.value).toContain("quarterback's EPA per dropback");
    await fireEvent.click(await screen.findByRole('button', { name: /^Receiving/ }));
    expect(question.value).toContain("receiver's production");

    await fireEvent.click(screen.getByRole('button', { name: /NBA.*Bulk data mode/ }));
    expect(question.value).toContain("team's offensive rating");
    await fireEvent.click(await screen.findByRole('button', { name: 'Player' }));
    expect(question.value).toContain("player's scoring");
  });

  it('switches sports, supports NBA players, and restores the NFL draft', async () => {
    render(App);
    const nflTeam = await screen.findByRole('combobox', { name: 'NFL team' });
    await fireEvent.focus(nflTeam);
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Kansas City Chiefs/ }));

    await fireEvent.click(screen.getByRole('button', { name: /NBA.*Bulk data mode/ }));
    expect(await screen.findByText('Analyze and Discuss Basketball Play-by-Play Data!')).toBeTruthy();
    expect(screen.queryByLabelText('NFL team')).toBeNull();
    expect(screen.queryByText('EPA/dropback')).toBeNull();
    expect((await screen.findByLabelText(/Player Crosswalk/) as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByLabelText(/On-court Lineups/)).toBeNull();
    expect(screen.getByText('not offered for selected seasons')).toBeTruthy();
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
    expect(player.getAttribute('aria-invalid')).toBe('false');
    const playerSeasonSelectors = screen.getAllByLabelText('Season') as HTMLSelectElement[];
    expect(playerSeasonSelectors).toHaveLength(2);
    expect(playerSeasonSelectors.every((select) => [...select.options].map((option) => option.value).join(',') === '2024')).toBe(true);
    expect(screen.getByText('1 player seasons available')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'NFL' }));
    const restored = await screen.findByRole('combobox', { name: 'NFL team' }) as HTMLInputElement;
    await waitFor(() => expect(restored.value).toBe('Kansas City Chiefs (KC)'));
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

    await fireEvent.click(screen.getByRole('button', { name: /Rushing.*Rushing attempts/ }));
    const rushEpa = screen.getByRole('checkbox', { name: /EPA\/rush/ }) as HTMLInputElement;
    expect(rushEpa.checked).toBe(true);
    expect(screen.queryByRole('checkbox', { name: /EPA\/dropback/ })).toBeNull();
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

    await fireEvent.click(screen.getByRole('button', { name: 'Team' }));

    expect(await screen.findByRole('button', { name: /Passing.*Quarterback dropbacks/ })).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /QB EPA\/dropback/ })).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Down' })).toBeTruthy();
  });

  it('distinguishes player loading from an empty player search', async () => {
    const fetchMock = vi.mocked(fetch);
    const defaultImplementation = fetchMock.getMockImplementation()!;
    let releasePlayers!: () => void;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).includes('/sports/nfl/players?query=')) {
        return new Promise<Response>((resolve) => {
          releasePlayers = () => void Promise.resolve(defaultImplementation(input, init)).then(resolve);
        });
      }
      return defaultImplementation(input, init);
    });

    render(App);
    await fireEvent.click(await screen.findByRole('button', { name: 'Player' }));
    const player = screen.getByRole('combobox', { name: 'Player' });
    await fireEvent.focus(player);

    expect(await screen.findByText('Loading NFL players…')).toBeTruthy();
    expect(screen.queryByText(/No players match/)).toBeNull();
    expect(player.getAttribute('aria-busy')).toBe('true');

    releasePlayers();
    expect(await screen.findByRole('option', { name: /Patrick Mahomes/ })).toBeTruthy();
    expect(player.getAttribute('aria-busy')).toBe('false');
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
    expect(screen.getByText('3/4 local')).toBeTruthy();
    expect(screen.getByText('PBP only')).toBeTruthy();
    const nextgen = screen.getByLabelText(/Nextgen Passing/) as HTMLInputElement;
    expect(nextgen.disabled).toBe(false);
    expect(screen.getByText('0/2 local · 2016+')).toBeTruthy();

    await fireEvent.click(rosters);
    expect(details.open).toBe(true);
  });

  it('selects locally available packages when the selected seasons change', async () => {
    render(App);
    const season2024 = await screen.findByRole('checkbox', { name: '2024 season' }) as HTMLInputElement;
    const season2025 = screen.getByRole('checkbox', { name: '2025 season' }) as HTMLInputElement;
    const playByPlay = await screen.findByLabelText(/Play By Play/) as HTMLInputElement;
    const rosters = screen.getByLabelText(/Rosters/) as HTMLInputElement;
    const injuries = screen.getByLabelText(/Injuries/) as HTMLInputElement;

    expect(season2024.checked).toBe(true);
    expect(season2025.checked).toBe(true);
    await fireEvent.click(season2025);

    expect(playByPlay.checked).toBe(true);
    expect(rosters.checked).toBe(true);
    expect(injuries.checked).toBe(true);
    expect(rosters.indeterminate).toBe(false);

    await fireEvent.click(season2025);

    expect(playByPlay.checked).toBe(true);
    expect(playByPlay.indeterminate).toBe(false);
    expect(rosters.checked).toBe(true);
    expect(rosters.indeterminate).toBe(true);
    expect(injuries.checked).toBe(true);
    expect(injuries.indeterminate).toBe(true);

    const nextgen = screen.getByLabelText(/Nextgen Passing/) as HTMLInputElement;
    await fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => input.checked)).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Deselect all' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => !input.checked)).toBe(true);
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
    expect(await screen.findByText('Define Comparison')).toBeTruthy();
    expect(screen.queryByText('The follow-up found a consistent shift.')).toBeNull();
    await fireEvent.click(await screen.findByText('Which games changed the most?'));
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

  it('uses player names and initials instead of identifiers in saved investigation navigation', async () => {
    mockInvestigations = [{
      run: {
        investigation_id: 'investigation-player', sport: 'nfl',
        subject: { type: 'player', id: '00-0033873', team_id: 'KC' },
        question: 'Which dropbacks best represented the change?', created_at: '2026-08-21T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 18] }, comparison: { season: 2025, weeks: [1, 18] }
        }
      },
      summary: 'Summary', claims: [], aggregate_evidence: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true
    }];

    render(App);
    expect(await screen.findByText('Patrick Mahomes')).toBeTruthy();
    const badge = screen.getByText('PM');
    expect(badge.classList.contains('recent-subject-badge')).toBe(true);
    expect(screen.queryByText('00-0033873')).toBeNull();

    await fireEvent.click(screen.getByText('Which dropbacks best represented the change?'));
    expect(await screen.findByRole('heading', { name: 'Patrick Mahomes investigation' })).toBeTruthy();
    expect(await screen.findByRole('heading', { name: 'Patrick Mahomes Film Room' })).toBeTruthy();
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

    expect(await screen.findByText('Baseline window')).toBeTruthy();
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
