import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import App from './App.svelte';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it.each(['analysis', 'school download', 'conference download', 'player selection'])(
  'keeps CFB subject selection first and scopes the %s workflow', async (workflow) => {
  const storage = new Map<string, string>();
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null,
                               setItem: (key: string, value: string) => storage.set(key, value)});
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
  let submitted: any = null;
  let downloaded: any = null;
  const response = (value: unknown) => new Response(JSON.stringify(value), {headers: {'content-type': 'application/json'}});
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/health') return response({status: 'ready'});
    if (url.pathname === '/api/capabilities') return response({providers: ['ollama'], sports: ['nfl', 'cfb'], job_progress_transport: 'stream'});
    if (url.pathname === '/api/sports') return response([{value: 'nfl', label: 'NFL', available: true}, {value: 'cfb', label: 'College Football', available: true}]);
    if (url.pathname.endsWith('/options')) {
      const sport = url.pathname.split('/')[3];
      return response({sport, teams: [], available_seasons: sport === 'cfb' ? [] : [2024, 2025], syncable_seasons: [],
        metrics: [{value: 'win_rate', label: 'Win rate', category: 'results', analysis_domain: 'results', available_seasons: [], subject_types: ['team']}],
        default_metrics: ['win_rate'], default_metrics_by_domain: {results: ['win_rate']},
        analysis_domains: [{value: 'results', label: 'Results', description: 'Recorded results', subject_type: 'team'}],
        subject_types: sport === 'cfb' ? [{value: 'team', label: 'Team'}, {value: 'player', label: 'Player'}] : [{value: 'team', label: 'Team'}], split_dimensions: [],
        comparison_windows: [{value: 'full_seasons', label: 'Full seasons', description: 'Compare recorded games'}],
        syncable_datasets: ['schedules', 'team_stats', 'rosters'], dataset_min_seasons: {schedules: null, team_stats: null, rosters: null},
        week_values: [1, 2], data_setup: {required_datasets: ['schedules'], recommended_datasets: ['team_stats', 'rosters'], descriptions: {schedules: 'Schedule'},
                                       label: 'Selected college data', description: 'Prepared on demand'}});
    }
    if (url.pathname === '/api/sports/cfb/catalog') {
      if (!url.searchParams.has('season')) return response({seasons: [2025, 2024], conferences: [], teams: []});
      if (!url.searchParams.has('subdivision')) return response({subdivisions: [{value: 'fbs', label: 'FBS'}, {value: 'fcs', label: 'FCS'}]});
      return response({conferences: [{value: '8', label: 'Selected Conference'}],
                       teams: url.searchParams.has('conference_id') ? [{value: '1', label: 'Selected School'}, {value: '2', label: 'Other School'}] : [], cached: true});
    }
    if (url.pathname === '/api/sports/cfb/players') return response([{player_id: '10', name: 'School Player', teams: ['1'], positions: ['QB'], seasons: [2025, 2024]}]);
    if (url.pathname === '/api/sports/cfb/players/10/seasons') return response({seasons: [2025, 2024]});
    if (url.pathname === '/api/datasets/cfb/sync-stream' && init?.method === 'POST') {
      downloaded = JSON.parse(String(init.body));
      return new Response('data: {"stage":"complete","message":"Data downloaded","progress":1}\n\n', {headers: {'content-type': 'text/event-stream'}});
    }
    if (url.pathname === '/api/datasets') return response([{manifest_id: 'missing-roster', sport: 'cfb', partition_key: 'team:1',
      dataset: 'rosters', season: 2025, row_count: 0, sha256: 'empty', acquired_at: '2026-10-13T19:00:00Z', columns: [],
      availability: 'source_unavailable', availability_message: 'No recorded roster is available for this school/season',
      coverage: {expected_matches: 1, completed_matches: 0}}]);
    if (url.pathname === '/api/investigations') return response(url.searchParams.get('sport') === 'cfb' ? [{
      run: {investigation_id: 'saved-school', sport: 'cfb', question: 'Saved college comparison',
        subject: {type: 'team', id: '1', display_name: 'Selected School'}, created_at: '2026-10-13T19:00:00Z',
        scope: {team: '1', season_type: 'REG', baseline: {season: 2024, weeks: [1, 22]}, comparison: {season: 2025, weeks: [1, 22]}}},
      summary: 'Recorded comparison', fallback_used: true,
    }] : []);
    if (url.pathname === '/api/investigations/stream' && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body));
      return new Response('data: {"stage":"preparing","message":"Preparing selected school games","progress":0.15}\n\n',
                          {headers: {'content-type': 'text/event-stream'}});
    }
    return response([]);
  });
  vi.stubGlobal('fetch', fetch);
  render(App);
  const collegeTab = await screen.findByRole('button', {name: 'College Football'});
  expect(document.getElementById('data-setup')!.compareDocumentPosition(document.getElementById('scope-heading')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await fireEvent.click(collegeTab);
  await screen.findByText('Saved college comparison');
  expect(document.querySelector('.recent-subject-badge img')?.getAttribute('src')).toBe('https://a.espncdn.com/i/teamlogos/ncaa/500/1.png');
  await screen.findByRole('option', {name: 'Selected Conference'});
  const subject = screen.getByRole('region', {name: 'Choose Your Subject'});
  const dataSetup = document.getElementById('data-setup')!;
  expect(subject.compareDocumentPosition(dataSetup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(dataSetup.compareDocumentPosition(document.getElementById('comparison-heading')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(dataSetup.querySelector('.cfb-conference-download')).toBeTruthy();
  expect(subject.querySelector('#sport-team')).toBeNull(); // School selection is the single team control.
  expect((dataSetup.querySelector('.download-data-button') as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', {name: 'Download Entire Conference'}) as HTMLButtonElement).disabled).toBe(true);
  await fireEvent.click(screen.getByRole('button', {name: 'Choose a School'}));
  expect(document.activeElement?.id).toBe('scope-heading');
  if (workflow === 'player selection') {
    await fireEvent.click(screen.getByRole('button', {name: 'Player'}));
    expect((screen.getByRole('combobox', {name: 'Player'}) as HTMLInputElement).disabled).toBe(true);
  }
  await fireEvent.change(screen.getByLabelText('Conference'), {target: {value: '8'}});
  await screen.findByRole('option', {name: 'Selected School'});
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  if (workflow === 'conference download') {
    expect((dataSetup.querySelector('.download-data-button') as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole('checkbox', {name: 'Rosters'}));
    await fireEvent.click(screen.getByRole('button', {name: 'Download Entire Conference'}));
    await waitFor(() => expect(downloaded).not.toBeNull());
    expect(downloaded).toMatchObject({subdivision: 'fbs', conference_id: '8', seasons: [2025, 2024]});
    expect(downloaded.team_ids).toBeUndefined();
    expect(downloaded.datasets).not.toContain('rosters');
    expect(downloaded.datasets).toContain('schedules');
    return;
  }
  await fireEvent.change(screen.getByLabelText('School'), {target: {value: '1'}});
  expect(await screen.findByText('Selected School · Selected School')).toBeTruthy();
  if (workflow === 'school download') {
    await fireEvent.click(dataSetup.querySelector('.download-data-button')!);
    await waitFor(() => expect(downloaded).not.toBeNull());
    expect(downloaded).toMatchObject({team_ids: ['1'], seasons: [2025, 2024]});
    expect(downloaded.conference_id).toBeUndefined();
    return;
  }
  if (workflow === 'player selection') {
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).includes('/cfb/players?'))).toBe(true));
    const player = screen.getByRole('combobox', {name: 'Player'});
    expect((player as HTMLInputElement).disabled).toBe(false);
    await fireEvent.focus(player);
    await fireEvent.mouseDown(await screen.findByRole('option', {name: /School Player/}));
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).includes('/cfb/players/10/seasons'))).toBe(true));
    expect((player as HTMLInputElement).value).toContain('School Player');
    expect(fetch.mock.calls.filter(([input]) => String(input).includes('/cfb/players?')).every(([input]) => String(input).includes('team_id=1'))).toBe(true);
    expect(downloaded).toBeNull();
    expect(submitted).toBeNull();
    return;
  }
  await fireEvent.click(await screen.findByRole('button', {name: 'Show 5 more examples'}));
  const coverageQuestion = screen.getByRole('button', {name: /How reliable is the results trend given unequal game counts/});
  await fireEvent.click(coverageQuestion);
  expect((screen.getByLabelText('Your Question:') as HTMLTextAreaElement).value).toBe(coverageQuestion.textContent?.trim());
  const season = await screen.findByRole('checkbox', {name: '2025 season'});
  if (!(season as HTMLInputElement).checked) await fireEvent.click(season);
  await screen.findByText('Limited source coverage · recheck hourly');
  expect(screen.getByText('2025: No recorded roster is available for this school/season')).toBeTruthy();
  await waitFor(() => expect((screen.getByRole('button', {name: /Run analysis/}) as HTMLButtonElement).disabled).toBe(false));
  await fireEvent.click(screen.getByRole('button', {name: /Run analysis/}));
  await waitFor(() => expect(submitted?.sport).toBe('cfb'));
  expect(submitted.subject).toMatchObject({type: 'team', id: '1'});
  expect(submitted.scope).toMatchObject({team: '1', baseline: {season: 2024}, comparison: {season: 2025}});
  expect(fetch.mock.calls.some(([url]) => String(url).includes('/sync') || String(url).includes('/players'))).toBe(false);
});
