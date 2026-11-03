import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';
import {teamLogoUrl} from './teamPalettes';

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
        const savedPlay = mockInvestigations.flatMap((item: any) => item.play_evidence ?? [])
          .find((item: any) => item.evidence_id === identifier);
        if (savedPlay) return Promise.resolve(new Response(JSON.stringify(savedPlay), {
          status: 200, headers: {'content-type': 'application/json'}
        }));
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
      if (init?.method === 'POST' && url.endsWith('/investigations/stream')) {
        return Promise.resolve(new Response(
          'data: {"stage":"planning","message":"Planning analysis","progress":0.1}\n\n' +
          'data: {"stage":"complete","message":"Investigation ready","progress":1,"investigation_id":"investigation-running"}\n\n',
          { status: 200, headers: { 'content-type': 'text/event-stream' } }
        ));
      }
      if (init?.method === 'POST' && /\/api\/datasets\/[^/]+\/sync-stream$/.test(url)) {
        return Promise.resolve(new Response(
          'data: {"stage":"downloading","message":"Downloading data","progress":0.5}\n\n' +
          'data: {"stage":"complete","message":"Dataset sync complete","progress":1}\n\n',
          { status: 200, headers: { 'content-type': 'text/event-stream' } }
        ));
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
        ? { providers: ['azure_foundry', 'ollama'], configured_provider: 'azure_foundry', model_configured: false, custom_analysis: false, sports: ['nfl', 'nba', 'soccer'] }
        : url.endsWith('/sports')
          ? [
              { value: 'nfl', label: 'NFL', available: true, live_available: false },
              { value: 'nba', label: 'NBA', available: true, live_available: false },
              { value: 'soccer', label: 'Soccer', available: true, live_available: false }
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
        : url.includes('/sports/soccer/players')
          ? [{ player_id: '10', name: 'Alex Forward', teams: ['1'], positions: ['F'], seasons: [2024, 2025] }]
        : url.includes('/sports/soccer/options')
          ? {
              sport: 'soccer', teams: [{ value: '1', label: 'Home FC' }],
              available_seasons: url.includes('usa.1') ? [] : [2024, 2025],
              syncable_seasons: [2025, 2024], syncable_datasets: ['play_by_play', 'team_stats', 'lineups', 'key_events'],
              dataset_min_seasons: {play_by_play: 2016, team_stats: 2016, lineups: 2016, key_events: 2016},
              dataset_available_seasons: {play_by_play: [2024, 2025], team_stats: [2024, 2025], lineups: [2024, 2025], key_events: [2024, 2025]},
              data_setup: {label: 'Soccer match data', description: 'Match data.', required_datasets: ['play_by_play'],
                           recommended_datasets: ['team_stats', 'lineups', 'key_events'], descriptions: {}},
              default_metrics: ['points_per_match'], default_metrics_by_domain: {results: ['points_per_match'], usage: ['appearances']},
              metrics: [
                {value: 'points_per_match', label: 'Points per match', category: 'Results', analysis_domain: 'results', description: 'Points.', available_seasons: [2024, 2025], subject_types: ['team']},
                {value: 'appearances', label: 'Appearances', category: 'Usage', analysis_domain: 'usage', description: 'Matches.', available_seasons: [2024, 2025], subject_types: ['player']}
              ],
              analysis_domains: [{value: 'results', label: 'Results', description: 'Team results.', subject_type: 'team'},
                                 {value: 'usage', label: 'Usage', description: 'Player usage.', subject_type: 'player'}],
              comparison_windows: [{value: 'full_seasons', label: 'Full seasons', description: 'Compare seasons.'},
                                   {value: 'date_ranges', label: 'Date ranges', description: 'Compare dates.'}],
              split_dimensions: [], week_values: [], subject_types: [{value: 'team', label: 'Team'}, {value: 'player', label: 'Player'}]
            }
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
          ? url.includes('sport=soccer') ? [2024, 2025].flatMap(season => ['play_by_play', 'team_stats', 'lineups', 'key_events', 'expected_goals'].map(dataset => ({dataset, season, sport: 'soccer', competition: 'eng.1', coverage: {completed_matches: 2, expected_matches: 2, recorded_matches: dataset === 'expected_goals' ? (season === 2025 ? 2 : 0) : 2}})))
            : url.includes('sport=nba') ? [2024, 2025].flatMap(season => ['play_by_play', 'schedules', 'team_boxscores', 'player_boxscores'].map(dataset => ({dataset, season, sport: 'nba'}))) : [
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
                { value: 'head_to_head', label: 'Head-to-head', description: 'Compare two teams or two players over the same season.' },
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
    window.history.replaceState({}, '', '/');
  });

  it('opens the desktop workspace while history is stalled and offers a separate retry on failure', async () => {
    window.history.replaceState({}, '', '/?desktop');
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    let failHistory!: (error: Error) => void;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (/\/api\/investigations\?/.test(String(input))) return new Promise((_, reject) => { failHistory = reject; });
      return defaultFetch(input, init);
    });
    try {
      render(App);
      await screen.findByText('Loading the Film Room…');
      expect(document.querySelector('.desktop-startup-overlay')).toBeNull();
      failHistory(new Error('Investigation history timed out.'));
      await screen.findByRole('button', {name: 'Retry History'});
      vi.mocked(fetch).mockImplementation(defaultFetch);
      await fireEvent.click(screen.getByRole('button', {name: 'Retry History'}));
      await waitFor(() => expect(screen.queryByRole('button', {name: 'Retry History'})).toBeNull());
    } finally {
      window.history.replaceState({}, '', '/');
    }
  });

  it('identifies a failed desktop initialization step and opens the workspace after retry', async () => {
    window.history.replaceState({}, '', '/?desktop');
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input).includes('/sports/nfl/options')) return Promise.resolve(new Response(JSON.stringify({detail: 'Options unavailable'}), {status: 503}));
      return defaultFetch(input, init);
    });
    try {
      render(App);
      await screen.findByRole('button', {name: 'Try Again'});
      expect(screen.getByText(/We couldn't finish opening your workspace.*season and analysis options.*Options unavailable/)).toBeTruthy();
      vi.mocked(fetch).mockImplementation(defaultFetch);
      await fireEvent.click(screen.getByRole('button', {name: 'Try Again'}));
      await waitFor(() => expect(document.querySelector('.desktop-startup-overlay')).toBeNull());
    } finally {
      window.history.replaceState({}, '', '/');
    }
  });

  it('renders the scoped investigation entry point without model credentials', async () => {
    render(App);
    expect(await screen.findByText('Football analysis')).toBeTruthy();
    expect(await screen.findByText('No AI model set up')).toBeTruthy();
    expect(screen.getByText('Who do you want to understand?')).toBeTruthy();
    expect(screen.getByLabelText('NFL team')).toBeTruthy();
    expect(screen.getByText('Choose what to measure')).toBeTruthy();
    expect(await screen.findByText('Data Ready · Manage Data')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Run analysis/i })).toBeTruthy();
  });

  it('starts an investigation with preparable seasons even when its library is empty', async () => {
    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/datasets?sport=')) return new Response('[]');
      if (url.endsWith('/sports/nfl/options')) {
        const options = await (await baseFetch(input, init)).json();
        options.available_seasons = [];
        options.automatic_preparation = true;
        options.preparable_seasons = [2024, 2025];
        options.metrics = options.metrics.map((metric: any) => ({...metric, available_seasons: [], preparable_seasons: [2024, 2025]}));
        return new Response(JSON.stringify(options));
      }
      if (url.endsWith('/investigations/stream') && init?.method === 'POST') {
        return new Response('data: {"stage":"preparing","message":"Preparing missing NFL data","progress":0.15}\n\n',
                            {headers: {'content-type': 'text/event-stream'}});
      }
      return baseFetch(input, init);
    });
    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'What changed in the passing game?'}});
    await waitFor(() => expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByText('Missing data will prepare when you run')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Run analysis'}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/investigations/stream'))).toBe(true));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('/sync-stream'))).toBe(false);
  });

  it('runs one season against the season before it and explains blocked periods', async () => {
    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.change(screen.getByLabelText('From season'), {target: {value: '2025'}});
    expect((await screen.findAllByText('Choose an end season after the start season')).length).toBeGreaterThan(0);
    await fireEvent.change(screen.getByLabelText('Comparison type'), {target: {value: 'season_vs_prior'}});
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'What changed in the passing game?'}});
    await waitFor(() => expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByText('Measured against')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Run analysis'}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/investigations/stream'))).toBe(true));
    const [, request] = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith('/investigations/stream'))!;
    expect(JSON.parse(String(request?.body)).scope).toMatchObject({
      comparison_design: 'full_seasons', baseline: {season: 2024}, comparison: {season: 2025}
    });
  });

  it('guides an empty library through explicit quick setup and remembers onboarding dismissal', async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    let downloaded = false;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/datasets?sport=')) return new Response(JSON.stringify(downloaded ? [2024, 2025].flatMap(season => ['play_by_play', 'rosters'].map(dataset => ({season, dataset, sport: 'nfl'}))) : []));
      if (url.endsWith('/sports/nfl/options')) {
        const options = await (await defaultFetch(input, init)).json();
        options.available_seasons = downloaded ? [2024, 2025] : [];
        options.data_setup = {label: 'Football essentials', description: 'Plays and player identities.', required_datasets: ['play_by_play'], recommended_datasets: ['rosters'], descriptions: {rosters: 'Player names and teams.'}};
        return new Response(JSON.stringify(options));
      }
      if (url.endsWith('/datasets/nfl/sync-stream')) {
        return new Response(new ReadableStream({
          start(controller) { controller.error(new TypeError('Network connection interrupted')); }
        }), {headers: {'x-job-id': 'sync-running', 'content-type': 'text/event-stream'}});
      }
      if (url.endsWith('/dataset-jobs/sync-running/status')) {
        downloaded = true;
        return new Response(JSON.stringify({stage: 'complete', message: 'Data downloaded', progress: 1}));
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
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(
      ([input]) => String(input).endsWith('/datasets/nfl/sync-stream')
    )).toHaveLength(1));
    const syncCalls = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/datasets/nfl/sync-stream'));
    expect(syncCalls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      {seasons: [2025, 2024], datasets: ['play_by_play', 'rosters']}
    ]);
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/dataset-jobs/sync-running/status'))).toBe(true);
    await fireEvent.click(await screen.findByRole('button', {name: 'Continue building analysis'}));
    expect(document.activeElement?.id).toBe('scope-heading');
    const team = screen.getByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.keyDown(team, {key: 'ArrowDown'});
    await fireEvent.keyDown(team, {key: 'Enter'});
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'What changed in the passing game?'}});
    await waitFor(() => expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(screen.getByRole('button', {name: 'Dismiss guide'}));
    cleanup();
    render(App);
    await screen.findByText('Data Ready · Manage Data');
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
    await fireEvent.click(screen.getByRole('button', {name: 'NBA'}));
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
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.objectContaining({signal: expect.any(AbortSignal)})));
    expect(fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => !url.endsWith('/api/health'))).toHaveLength(0);

    releaseHealth();
    expect(await screen.findByText('Football analysis')).toBeTruthy();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/sports/nfl/options'))).toBe(true));
  });

  it('recovers and atomically displays a completed analysis after its progress stream disconnects', async () => {
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
      if (init?.method === 'POST' && url.endsWith('/investigations/stream')) {
        mockInvestigations = [completed];
        const interrupted = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(
              'data: {"stage":"planning","message":"Planning analysis","progress":0.1}\n\n'
            ));
            queueMicrotask(() => controller.error(new TypeError('HTTP/2 stream closed')));
          }
        });
        return Promise.resolve(new Response(interrupted, {
          status: 200,
          headers: {'content-type': 'text/event-stream', 'x-investigation-id': 'investigation-running'}
        }));
      }
      if (!init?.method && url === '/api/investigations/investigation-running') {
        resultAttempts += 1;
      }
      return baseFetch(input, init);
    });

    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'What changed in the passing game?'}});
    await fireEvent.click(screen.getByRole('button', {name: /Run analysis/i}));

    expect((await screen.findAllByText('The completed analysis response is now visible.')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('What changed?').length).toBeGreaterThanOrEqual(2);
    expect(resultAttempts).toBeGreaterThanOrEqual(2);
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'smooth' });
    expect(await screen.findByText('Report Ready')).toBeTruthy();
  });

  it('offers the 2026 NFL season and syncs its current snapshot', async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).endsWith('/sports/nfl/options')) {
        const options = await (await defaultFetch(input, init)).json();
        options.syncable_seasons = [2026, ...options.syncable_seasons];
        return new Response(JSON.stringify(options));
      }
      return defaultFetch(input, init);
    });
    render(App);
    await fireEvent.click(await screen.findByText('Data Ready · Manage Data'));
    expect((screen.getByRole('checkbox', {name: '2026 season'}) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/2026 is still in progress/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Download or Refresh 1 sources for 2 seasons'}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/datasets/nfl/sync-stream'))).toBe(true));
    const syncCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith('/datasets/nfl/sync-stream'));
    expect(JSON.parse(String(syncCall?.[1]?.body))).toEqual({seasons: [2026], datasets: ['play_by_play']});
  });

  it('sends the chosen conference with explicit downloads even when league data is already local', async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes('/download-catalog?')) return new Response(JSON.stringify({
        teams:[{value:'KC',label:'Kansas City Chiefs'}], conferences:[{value:'nfl:afc',label:'AFC'}], divisions:[]
      }));
      return defaultFetch(input, init);
    });
    render(App);
    await fireEvent.click(await screen.findByText('Data Ready · Manage Data'));
    await fireEvent.change(screen.getByLabelText('Download By'), {target:{value:'conference'}});
    await waitFor(() => expect(screen.getByRole('option',{name:'AFC'})).toBeTruthy());
    await fireEvent.change(screen.getByLabelText('Download Conference'), {target:{value:'nfl:afc'}});
    await fireEvent.click(screen.getByRole('button', {name:/Download 1 sources for 2 seasons · AFC/}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/datasets/nfl/sync-stream'))).toBe(true));
    const call = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith('/datasets/nfl/sync-stream'));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({seasons:[2025,2024],datasets:['play_by_play'],conference_id:'nfl:afc'});
  });

  it('switches sports, supports NBA players, and restores the NFL draft', async () => {
    render(App);
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('nfl');
    expect(document.querySelector('main')?.classList.contains('nfl-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(false);
    const nflTeam = await screen.findByRole('combobox', { name: 'NFL team' });
    await fireEvent.focus(nflTeam);
    await fireEvent.mouseDown(await screen.findByRole('option', { name: /Kansas City Chiefs/ }));

    await fireEvent.click(screen.getByRole('button', { name: 'NBA' }));
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('nba');
    expect(document.querySelector('main')?.classList.contains('nba-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(true);
    expect(await screen.findByText('Basketball analysis')).toBeTruthy();
    expect(screen.queryByLabelText('NFL team')).toBeNull();
    expect(screen.queryByText('EPA/dropback')).toBeNull();
    await fireEvent.click(screen.getByText(/Data Ready · Manage Data|Sync Data/, {selector: 'strong'}));
    await fireEvent.click(await screen.findByRole('button', {name: 'Customize data sources'}));
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
    await fireEvent.click(screen.getByRole('button', {name: 'Show 8 more examples'}));
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
    class IdleEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(_url: string) {}
      close() {}
    }
    vi.stubGlobal('EventSource', IdleEventSource);
    render(App);
    await fireEvent.click(await screen.findByText('Data Ready · Manage Data'));
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
    await fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => input.checked)).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Deselect All' }));
    expect([playByPlay, rosters, injuries, nextgen].every((input) => !input.checked)).toBe(true);
    expect(screen.getByLabelText('Rosters local status: Local 1/2')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    await fireEvent.click(screen.getByRole('button', { name: /Download .* sources/ }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input, init]) =>
      String(input) === '/api/datasets/nfl/sync-stream' && init?.method === 'POST'
    )).toBe(true));
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
    await screen.findByText('Which games changed the most?');
    const galleryLogo = document.querySelector('.recent-subject-badge img') as HTMLImageElement;
    expect(galleryLogo.getAttribute('src')).toBe(teamLogoUrl('KC', 'nfl'));
    await fireEvent.load(galleryLogo);
    expect(galleryLogo.classList.contains('loaded')).toBe(true);
    await fireEvent.error(galleryLogo);
    expect(document.querySelector('.recent-subject-badge img')).toBeNull();
    expect(document.querySelector('.recent-subject-badge')?.textContent?.trim()).toBe('KC');
    await fireEvent.click(await screen.findByText('Which games changed the most?'));
    expect(await screen.findByText('Was it consistent across the sample?')).toBeTruthy();
    expect(screen.getByText('The follow-up found a consistent shift.')).toBeTruthy();
    const messageTimes = document.querySelectorAll('.chat-message-meta time[datetime]');
    expect(messageTimes).toHaveLength(4);
    expect([...messageTimes].every((time) => /^\d{2}:\d{2}$/.test(time.textContent ?? ''))).toBe(true);
    expect(screen.getAllByText('1 follow-up').length).toBeGreaterThan(0);
    const deleteButton = screen.getByRole('button', { name: 'Delete saved report: Which games changed the most?' });
    expect(deleteButton.classList.contains('delete-report')).toBe(true);
    expect(screen.getAllByRole('button', { name: /Delete saved report/ })).toHaveLength(1);

    await fireEvent.click(deleteButton);

    expect(fetch).toHaveBeenCalledWith('/api/investigations/investigation-delete-me', expect.objectContaining({method: 'DELETE'}));
    await waitFor(() => expect(screen.queryAllByText('Which games changed the most?')).toHaveLength(0));
    expect(screen.queryAllByText('Was it consistent across the sample?')).toHaveLength(0);
    expect(await screen.findByText('Report Deleted')).toBeTruthy();
  });

  it('keeps the report in place when a follow-up is answered', async () => {
    const root = {
      run: {
        investigation_id: 'investigation-root', sport: 'nfl', question: 'How did the passing game change?', created_at: '2026-08-21T12:00:00Z', metrics: ['success_rate'],
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 22] }, comparison: { season: 2025, weeks: [1, 22] }
        }
      },
      summary: 'The original report answer.', claims: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true,
      aggregate_evidence: [{evidence_id: 'success', metric: 'success_rate', label: 'Success rate', unit: 'rate', value: 0.0443,
        baseline_value: 0.3884, comparison_value: 0.4327, sample_size: 594, context: {baseline_sample: 636, comparison_sample: 594}}]
    };
    const answer = {...root, summary: 'The third-down answer.', aggregate_evidence: [],
      run: {...root.run, investigation_id: 'investigation-answer', parent_investigation_id: 'investigation-root', question: 'What about third down?', created_at: '2026-08-21T13:00:00Z'}};
    mockInvestigations = [root];
    render(App);
    await fireEvent.click(await screen.findByText('How did the passing game change?'));
    expect(await screen.findByText('Your question')).toBeTruthy();
    expect(screen.getByText('38.8%')).toBeTruthy();
    expect(screen.getByText('+4.4 pct pts')).toBeTruthy();
    expect(screen.getByText('Sample 636')).toBeTruthy();

    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'POST' && url.includes('investigation-root')) {
        mockInvestigations = [answer, root];
        return new Response('data: {"stage":"complete","message":"Done","progress":1,"investigation_id":"investigation-answer"}\n\n',
                            {headers: {'content-type': 'text/event-stream'}});
      }
      if (url.endsWith('/investigations/investigation-answer')) return new Response(JSON.stringify(answer));
      if (url.includes('investigation-answer') || url.includes('investigation-root/thread')) return new Response(JSON.stringify([root, answer]));
      return baseFetch(input, init);
    });
    const scrollTo = vi.fn();
    vi.stubGlobal('scrollTo', scrollTo);
    await fireEvent.input(screen.getByRole('textbox', {name: 'Ask a follow-up question'}), {target: {value: 'What about third down?'}});
    await fireEvent.click(screen.getByRole('button', {name: 'Send'}));

    expect(await screen.findByText('The third-down answer.')).toBeTruthy();
    expect(screen.getAllByText('The original report answer.').length).toBeGreaterThan(0);
    expect(document.querySelector('.report-summary')?.textContent).toContain('The original report answer.');
    expect(screen.getByText('38.8%')).toBeTruthy();
    expect(scrollTo).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByText('The third-down answer.'));
    expect(await screen.findByRole('button', {name: 'Back to the original report'})).toBeTruthy();
    expect(document.querySelector('.key-metrics')).toBeNull();
    await fireEvent.click(screen.getByRole('button', {name: 'Back to the original report'}));
    await waitFor(() => expect(document.querySelector('.key-metrics')).toBeTruthy());
  });

  const savedReport = (id: string, question: string, sport = 'nfl') => ({
    run: {
      investigation_id: id, sport, question, created_at: '2026-08-21T12:00:00Z',
      scope: {
        team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
        baseline: { season: 2024, weeks: [1, 22] }, comparison: { season: 2025, weeks: [1, 22] }
      }
    },
    summary: `Answer for ${question}`, claims: [], aggregate_evidence: [], play_evidence: [], charts: [], methodological_caveats: [], fallback_used: true
  });

  it('starts with an empty question and suggests examples as a placeholder', async () => {
    render(App);
    const field = await screen.findByLabelText('Your Question:') as HTMLTextAreaElement;
    expect(field.value).toBe('');
    expect(field.placeholder).toMatch(/^For example: /);
    expect((await screen.findAllByText('Add your question')).length).toBeGreaterThan(0);
  });

  it('lists every saved report behind a toggle and explains an empty Film Room', async () => {
    render(App);
    expect(await screen.findByText(/No saved reports for this sport yet/)).toBeTruthy();
    cleanup();
    mockInvestigations = Array.from({length: 10}, (_, index) => savedReport(`investigation-${index}`, `Saved question ${index}`));
    render(App);
    await screen.findByText('Saved question 0');
    expect(screen.queryByText('Saved question 9')).toBeNull();
    await fireEvent.click(screen.getByRole('button', {name: 'Show all 10'}));
    expect(screen.getByText('Saved question 9')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Show fewer'}));
    expect(screen.queryByText('Saved question 9')).toBeNull();
  });

  it('renders model markdown as text and hides technical identifiers', async () => {
    mockInvestigations = [{...savedReport('investigation-plain', 'What changed?'), model_id: 'azure_foundry:test', fallback_used: false,
      summary: 'Across *all qualifying plays*, EPA **rose**.',
      claims: [{claim_id: 'claim-one', claim_type: 'measured', statement: 'A *measured* gain.', confidence: 'high', evidence_ids: ['evidence-abcdef0123456789', 'evidence-second']}],
      play_evidence: [{evidence_id: 'play-one', game_id: '2023_14_DET_CHI', play_id: 210, description: 'A play.', epa: 1.1, supporting: true, window: 'baseline', candidate_pool_size: 1089}]}];
    render(App);
    await fireEvent.click(await screen.findByText('What changed?'));
    await screen.findByText('Week 14 · DET at CHI');
    const page = document.querySelector('main')?.textContent ?? '';
    expect(page).not.toContain('*');
    expect(page).not.toContain('2023_14_DET_CHI');
    expect(page).not.toContain('evidence-abcdef');
    expect(document.querySelector('.report-summary')?.textContent).not.toContain('azure_foundry');
    expect(screen.getByText('2 sources')).toBeTruthy();
    expect(screen.getByText('1 of 1,089 qualifying plays selected')).toBeTruthy();
  });

  it('finds players beyond the downloaded list by searching the server', async () => {
    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    const brady = {player_id: '00-0019596', name: 'Tom Brady', teams: ['TB'], positions: ['QB'], seasons: [2025],
      seasons_by_domain: {quarterback: [2025]}};
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes('/sports/nfl/players?query=Brady')) return new Response(JSON.stringify([brady]));
      return baseFetch(input, init);
    });
    render(App);
    await fireEvent.click(await screen.findByRole('button', {name: 'Player'}));
    const player = await screen.findByRole('combobox', {name: 'Player'});
    await fireEvent.focus(player);
    await fireEvent.input(player, {target: {value: 'Brady'}});
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Tom Brady/}));
    expect((player as HTMLInputElement).value).toContain('Tom Brady');
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('query=Brady'))).toBe(true);
  });

  it('searches the server for a head-to-head opponent', async () => {
    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    const allen = {player_id: '00-0034857', name: 'Josh Allen', teams: ['BUF'], positions: ['QB'], seasons: [2024, 2025],
      seasons_by_domain: {quarterback: [2024, 2025]}};
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes('/sports/nfl/players?query=Allen')) return new Response(JSON.stringify([allen]));
      return baseFetch(input, init);
    });
    render(App);
    await fireEvent.click(await screen.findByRole('button', {name: 'Player'}));
    const player = await screen.findByRole('combobox', {name: 'Player'});
    await fireEvent.focus(player);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Patrick Mahomes/}));
    await fireEvent.change(screen.getByLabelText('Comparison type'), {target: {value: 'head_to_head'}});
    const compare = await screen.findByRole('combobox', {name: 'Compare with'});
    await fireEvent.focus(compare);
    await fireEvent.input(compare, {target: {value: 'Allen'}});
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Josh Allen/}));
    expect((await screen.findAllByText('Subjects selected')).length).toBeGreaterThan(0);
  });

  it('compares two teams head-to-head in one season', async () => {
    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.change(screen.getByLabelText('Comparison type'), {target: {value: 'head_to_head'}});
    expect((await screen.findAllByText('Choose who to compare with')).length).toBeGreaterThan(0);
    const compare = screen.getByRole('combobox', {name: 'Compare with'});
    await fireEvent.focus(compare);
    expect(screen.queryByRole('option', {name: /Kansas City Chiefs/})).toBeNull();
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Buffalo Bills/}));
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'Which offense passed better?'}});
    await waitFor(() => expect((screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement).disabled).toBe(false));
    expect(document.querySelector('.analysis-brief')?.textContent).toContain('Kansas City Chiefs (KC) vs Buffalo Bills');
    await fireEvent.click(screen.getByRole('button', {name: 'Run analysis'}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith('/investigations/stream'))).toBe(true));
    const [, request] = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith('/investigations/stream'))!;
    const body = JSON.parse(String(request?.body));
    expect(body.comparison_subject).toMatchObject({type: 'team', id: 'BUF', display_name: 'Buffalo Bills'});
    expect(body.scope.comparison_design).toBe('head_to_head');
    expect(body.scope.baseline).toEqual(body.scope.comparison);
  });

  it('shows a head-to-head report with both names and who leads', async () => {
    const season = {season: 2025, weeks: [1, 22]};
    mockInvestigations = [{
      ...savedReport('investigation-h2h', 'Which offense passed better?'),
      run: {...savedReport('investigation-h2h', 'Which offense passed better?').run,
        subject: {type: 'team', id: 'KC', display_name: 'Kansas City Chiefs'}, comparison_subject: {type: 'team', id: 'BUF', display_name: 'Buffalo Bills'},
        metrics: ['epa_per_dropback'], scope: {team: 'KC', comparison_design: 'head_to_head', season_type: 'REG', baseline: season, comparison: season}},
      aggregate_evidence: [{evidence_id: 'h2h-epa', metric: 'epa_per_dropback', label: 'EPA/dropback', unit: 'per play', value: -0.2,
        baseline_value: 0.058, comparison_value: -0.142, sample_size: 160,
        context: {comparison_kind: 'head_to_head', subjects: ['Kansas City Chiefs', 'Buffalo Bills'], baseline_sample: 160, comparison_sample: 170}}]
    }];
    render(App);
    await fireEvent.click(await screen.findByText('Which offense passed better?'));
    expect(await screen.findByRole('heading', {level: 1, name: 'Kansas City Chiefs vs Buffalo Bills report'})).toBeTruthy();
    const card = await waitFor(() => {
      const article = document.querySelector('.key-metrics article');
      expect(article).toBeTruthy();
      return article!;
    });
    expect(card.textContent).toContain('Kansas City Chiefs');
    expect(card.textContent).toContain('Buffalo Bills');
    expect(card.textContent).toContain('Difference');
    await waitFor(() => expect(card.textContent).toContain('Kansas City Chiefs ahead'));
    expect(card.textContent).not.toContain('Better');
    expect(screen.getAllByText('2025 · Head-to-head').length).toBeGreaterThan(0);
  });

  it('gives each report a URL that reloads and follows browser history', async () => {
    mockInvestigations = [savedReport('investigation-linked', 'What changed for Kansas City?')];
    window.history.replaceState({}, '', '/#/reports/investigation-linked');
    const {unmount} = render(App);
    expect((await screen.findAllByText('Answer for What changed for Kansas City?')).length).toBeGreaterThan(0);
    await waitFor(() => expect(document.title).toContain('report'));
    unmount();

    window.history.replaceState({}, '', '/');
    render(App);
    await fireEvent.click(await screen.findByText('What changed for Kansas City?'));
    await waitFor(() => expect(window.location.hash).toBe('#/reports/investigation-linked'));
    await fireEvent.click(screen.getByRole('button', {name: 'New Analysis'}));
    await waitFor(() => expect(window.location.hash).toBe(''));
    expect(await screen.findByText('Who do you want to understand?')).toBeTruthy();
    window.history.replaceState({}, '', '/#/reports/investigation-linked');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect((await screen.findAllByText('Answer for What changed for Kansas City?')).length).toBeGreaterThan(0);
  });

  it('explains a report link that no longer exists', async () => {
    window.history.replaceState({}, '', '/#/reports/investigation-deleted');
    render(App);
    expect(await screen.findByText('That report could not be found. It may have been deleted.')).toBeTruthy();
    expect(window.location.hash).toBe('');
    expect(screen.getByText('Who do you want to understand?')).toBeTruthy();
  });

  it('cancels a running analysis and returns to the selections', async () => {
    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    let finish: (() => void) | undefined;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode('data: {"stage":"planning","message":"Planning analysis","progress":0.1}\n\n'));
        finish = () => {
          controller.enqueue(encoder.encode('data: {"stage":"cancelled","message":"Analysis cancelled","progress":0.1}\n\n'));
          controller.close();
        };
      }
    });
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'POST' && url.endsWith('/investigations/stream')) {
        return new Response(body, {headers: {'content-type': 'text/event-stream', 'x-investigation-id': 'investigation-running'}});
      }
      if (url.endsWith('/investigations/investigation-running/cancel')) {
        finish?.();
        return new Response(JSON.stringify({cancelled: true}));
      }
      return baseFetch(input, init);
    });
    render(App);
    const team = await screen.findByRole('combobox', {name: 'NFL team'});
    await fireEvent.focus(team);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Kansas City Chiefs/}));
    await fireEvent.input(screen.getByLabelText('Your Question:'), {target: {value: 'What changed in the passing game?'}});
    const run = screen.getByRole('button', {name: 'Run analysis'}) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    await fireEvent.click(run);
    await fireEvent.click(await screen.findByRole('button', {name: 'Cancel Analysis'}));
    expect(await screen.findByText('Analysis Cancelled')).toBeTruthy();
    expect((screen.getByRole('combobox', {name: 'NFL team'}) as HTMLInputElement).value).toContain('Kansas City');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Run analysis'})));
  });

  it('says plainly when the analysis service is not running', async () => {
    const baseFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.useFakeTimers({shouldAdvanceTime: true});
    let online = false;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (!online) throw new TypeError('Failed to fetch');
      return baseFetch(input, init);
    });
    try {
      render(App);
      await vi.advanceTimersByTimeAsync(4_000);
      expect(await screen.findByText("The analysis service isn't running. Start it, then try again.")).toBeTruthy();
      expect(screen.getByText('Service offline')).toBeTruthy();
      expect(screen.queryByText('No AI model set up')).toBeNull();
      expect((screen.getByRole('button', {name: 'NBA'}) as HTMLButtonElement).disabled).toBe(true);
      online = true;
      await fireEvent.click(screen.getByRole('button', {name: 'Try Again'}));
      expect(await screen.findByText('Football analysis')).toBeTruthy();
      await waitFor(() => expect(screen.queryByText("The analysis service isn't running. Start it, then try again.")).toBeNull());
    } finally {
      vi.useRealTimers();
    }
  });

  it('exposes finding text to assistive technology and offers a skip link', async () => {
    mockInvestigations = [{...savedReport('investigation-a11y', 'What changed?'), claims: [{
      claim_id: 'claim-one', claim_type: 'measured', statement: 'EPA rose by 0.128.', confidence: 'high', evidence_ids: ['evidence-one']
    }]}];
    render(App);
    await fireEvent.click(await screen.findByText('What changed?'));
    const finding = await screen.findByRole('button', {name: /Inspect evidence for finding 1: .*EPA rose by 0\.128/});
    expect(finding.getAttribute('aria-label')).toBeNull();
    expect(screen.getByRole('heading', {level: 2, name: 'Core Findings'})).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', {name: 'The answer'})));
    await fireEvent.click(screen.getByRole('button', {name: 'Skip to main content'}));
    expect(document.activeElement?.tagName).toBe('MAIN');
  });

  it('moves to a selected play and returns focus when it closes', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    mockInvestigations = [{
      run: {
        investigation_id: 'investigation-play', sport: 'nfl', question: 'Which play mattered?', created_at: '2026-08-21T12:00:00Z',
        scope: {
          team: 'KC', comparison_design: 'full_seasons', season_type: 'REG',
          baseline: { season: 2024, weeks: [1, 22] }, comparison: { season: 2025, weeks: [1, 22] }
        }
      },
      summary: 'Summary', claims: [], aggregate_evidence: [], charts: [], methodological_caveats: [], fallback_used: true,
      play_evidence: [{evidence_id: 'play-one', game_id: '2025_02_BUF_KC', play_id: 24, description: 'A key play.', epa: 1.1, supporting: true, window: 'comparison'}]
    }];
    render(App);
    await fireEvent.click(await screen.findByText('Which play mattered?'));
    const play = await screen.findByRole('button', {name: /Inspect .* evidence from Week 2 · BUF at KC/});
    play.focus();
    await fireEvent.click(play);
    const panel = await screen.findByRole('region', {name: 'Selected play details'});
    await waitFor(() => expect(document.activeElement).toBe(panel));
    expect(scrollIntoView).toHaveBeenCalledWith(expect.objectContaining({block: 'start'}));
    delete (Element.prototype as Partial<Element>).scrollIntoView;
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

    expect(await screen.findByText('2024', {selector: '.evidence-window-heading strong'})).toBeTruthy();
    expect(screen.getByText('2025', {selector: '.evidence-window-heading strong'})).toBeTruthy();
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
    const first = await screen.findByRole('button', { name: /^Inspect evidence for finding 1:/ });
    const second = screen.getByRole('button', { name: /^Inspect evidence for finding 2:/ });

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

  it('scopes the soccer tab by competition and opens recorded match evidence', async () => {
    mockInvestigations = [{
      run: {investigation_id: 'soccer-report', sport: 'soccer', question: 'How did Home FC change?',
            created_at: '2026-08-21T12:00:00Z', subject: {type: 'team', id: '1'},
            scope: {team: '1', competition: 'eng.1', comparison_design: 'full_seasons', season_type: 'REG',
                    baseline: {season: 2024, weeks: [1, 22]}, comparison: {season: 2025, weeks: [1, 22]}}},
      summary: 'Home FC improved.', claims: [], aggregate_evidence: [], charts: [], methodological_caveats: [], fallback_used: true,
      play_evidence: [{sport: 'soccer', evidence_id: 'soccer-match', season: 2025, game_id: '501', play_id: 0,
                       team: '1', description: 'Home FC 2–0 Away FC', supporting: true, window: 'comparison', evidence_role: 'typical',
                       visualization: {sport: 'soccer', game_date: '2024-09-15', home_team_name: 'Home FC', away_team_name: 'Away FC',
                                       home_score: 2, away_score: 0, home_expected_goals: 1.574, away_expected_goals: 0,
                                       soccer_timeline: [
                                         {clock: '', type: 'Kickoff', text: 'First Half begins.', side: 'neutral'},
                                         {clock: '', type: 'Kickoff', text: 'Second Half begins.', side: 'neutral'},
                                         {clock: "42'", type: 'Goal', text: 'Alex scores', side: 'home', scoring_play: true},
                                         {clock: "60'", type: 'Yellow Card', text: 'Morgan cautioned', side: 'away', scoring_play: false},
                                         {clock: "65'", type: 'Substitution', text: 'Substitution, Home FC. Robin replaces Alex.', side: 'home'},
                                         {clock: "65'", type: 'Substitution', text: 'Robin Substitution', side: 'home', player_in: 'Robin', player_out: 'Alex'},
                                         {clock: "90+2'", type: 'VAR Review', text: 'Decision confirmed', side: 'neutral', scoring_play: false}
                                       ]}}]
    }];
    render(App);
    await fireEvent.click(await screen.findByRole('button', {name: 'Soccer'}));
    expect(document.querySelector('main')?.getAttribute('data-sport-background')).toBe('soccer');
    expect(document.querySelector('main')?.classList.contains('soccer-background')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('soccer-theme')).toBe(true);
    expect(document.querySelector('.app-shell')?.classList.contains('nba-theme')).toBe(false);
    const competition = await screen.findByLabelText('Competition');
    const statsBadge = await screen.findByText('Team stats: 4 matches · xG: 2/4 matches · limited source coverage');
    expect(statsBadge.classList.contains('partial')).toBe(false);
    expect(within(competition).getByRole('option', {name: 'UEFA Champions League'})).toBeTruthy();
    await fireEvent.change(competition, {target: {value: 'uefa.champions'}});
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) =>
      String(input) === '/api/sports/soccer/options?competition=uefa.champions')).toBe(true));
    await fireEvent.change(competition, {target: {value: 'eng.1'}});
    expect(screen.getAllByRole('option', {name: 'UEFA Champions League'})).toHaveLength(1);
    expect(document.getElementById('data-setup')?.contains(competition)).toBe(false);
    await fireEvent.click(await screen.findByRole('button', {name: 'Player'}));
    const playerInput = screen.getByRole('combobox', {name: 'Player'}) as HTMLInputElement;
    await fireEvent.focus(playerInput);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /Alex Forward/}));
    expect(playerInput.value).toBe('Alex Forward · Home FC');
    await fireEvent.change(competition, {target: {value: 'usa.1'}});
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) =>
      String(input) === '/api/sports/soccer/options?competition=usa.1')).toBe(true));
    expect(screen.queryByText('How did Home FC change?')).toBeNull();
    const defaultFetch = vi.mocked(fetch).getMockImplementation()!;
    let finishSync: () => void = () => {};
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input) === '/api/investigations/soccer-report/evidence/soccer-match') {
        const saved = (mockInvestigations[0] as any).play_evidence[0];
        const shot = {id: 'fotmob-shot', eventType: 'Goal', min:42, x:93, y:30, goalCrossedY:35,
          goalCrossedZ:.8, playerName:'Alex Forward', expectedGoals:.3, espn_team_id:'1'};
        const enriched = {...saved, visualization:{...saved.visualization,
          soccer_analytics:[{provider:'fotmob', game_id:'501', team_id:'1', shots_json:JSON.stringify([shot])}],
          soccer_timeline:saved.visualization.soccer_timeline.map((event: any) => event.type === 'Goal'
            ? {...event, spatial_provider:'fotmob', spatial_event_id:shot.id, spatial_context:{shot}} : event)}};
        return Promise.resolve(new Response(JSON.stringify(enriched), {status:200, headers:{'content-type':'application/json'}}));
      }
      if (String(input) === '/api/datasets/soccer/sync-stream') {
        return Promise.resolve(new Response(new ReadableStream({
          start(controller) {
            const encoder = new TextEncoder();
            controller.enqueue(encoder.encode('data: {"stage":"downloading","message":"Downloading match data","progress":0.5}\n\n'));
            finishSync = () => {
              controller.enqueue(encoder.encode('data: {"stage":"complete","message":"Dataset sync complete","progress":1}\n\n'));
              controller.close();
            };
          }
        }), {headers: {'content-type': 'text/event-stream'}}));
      }
      return defaultFetch(input, init);
    });
    await fireEvent.click(await screen.findByRole('button', {name: /Download \d+ sources for \d+ seasons/}));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input, init]) =>
      String(input) === '/api/datasets/soccer/sync-stream' && JSON.parse(String(init?.body)).competition === 'usa.1')).toBe(true));
    expect(await screen.findByText('LIVE ANALYSIS BUILDUP')).toBeTruthy();
    expect(document.querySelector('.soccer-loading-scene')).toBeTruthy();
    expect(document.querySelector('.catch-scene')).toBeNull();
    expect(screen.getByRole('progressbar', {name: 'Download progress'}).getAttribute('aria-valuenow')).toBe('50');
    finishSync();
    await screen.findByText('Download finished');
    expect(await screen.findByText('Data Sync Complete')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: 'Dismiss Data Sync Complete notification'}));
    expect(screen.queryByText('Data Sync Complete')).toBeNull();
    await fireEvent.change(competition, {target: {value: 'eng.1'}});
    await fireEvent.click(await screen.findByText('How did Home FC change?'));
    expect(document.querySelector('.recent-subject-name')?.textContent).toBe('Home FC');
    await fireEvent.click(await screen.findByRole('button', {name: /Inspect Typical evidence from/}));
    // The saved report has no shots. The tablet must consume the enriched
    // evidence response, not remain attached to the stale saved example.
    // The soccer tablet loads lazily; give a cold module load time to finish.
    await fireEvent.click(await screen.findByRole('button', {name: 'Open shot detail'}, {timeout: 5000}));
    expect(await screen.findByText('Where the goal crossed the line')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name: '← Back to pitch'}));
    expect(screen.getByRole('option', {name:'FotMob'})).toBeTruthy();
    expect((await screen.findAllByText('Alex scores')).length).toBeGreaterThan(0);
    expect(await screen.findByText('Expected goals (ESPN): 1.57 : 0.00')).toBeTruthy();
    const timeline = screen.getByRole('list', {name: 'Recorded match events in time order'});
    expect(within(timeline).queryByRole('button', {name: /Kickoff/})).toBeNull();
    expect(within(timeline).getByText('Kickoff · 0′')).toBeTruthy();
    const substitution = within(timeline).getByRole('button', {name: "65' Substitution — Home FC"});
    expect(within(substitution).getByText('On: Robin')).toBeTruthy();
    expect(within(substitution).getByText('Off: Alex')).toBeTruthy();
    expect(substitution.querySelector('svg')).toBeTruthy();
    await fireEvent.click(substitution);
    expect(screen.getAllByText('Substitution, Home FC. Robin replaces Alex.').length).toBeGreaterThan(0);
    expect(within(timeline).getByRole('button', {name: "42' Goal — Home FC"}).closest('li')?.classList.contains('home')).toBe(true);
    const awayEvent = within(timeline).getByRole('button', {name: "60' Yellow Card — Away FC"});
    expect(awayEvent.closest('li')?.classList.contains('away')).toBe(true);
    await fireEvent.click(awayEvent);
    expect((await screen.findAllByText('Morgan cautioned')).length).toBeGreaterThan(0);
    expect(within(timeline).getByRole('button', {name: "90+2' VAR Review — Team not recorded"}).closest('li')?.classList.contains('neutral')).toBe(true);
  });
});
