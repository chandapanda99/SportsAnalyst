import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import CFBGameTablet from './CFBGameTablet.svelte';
import CFBPlayTablet from './CFBPlayTablet.svelte';
import type {CFBRecordedPlay} from './types';
import {api} from './api';
import type {Evidence} from './types';

afterEach(() => {cleanup(); vi.restoreAllMocks();});
const evidence = (id: string): Evidence => ({evidence_id: id, sport: 'cfb', season: 2024, game_id: id, play_id: 0,
  description: 'Away at Home', visualization: {sport: 'cfb', cfb_statistics: {rows: [], schools: {'1': 'Home'},
    covered_team_epa: [{team_id: '1', epa_per_play: .15, plays: 60, games: 1}]}}} as Evidence);
const detail = (id = 'p1') => ({coverage: '2/3 source plays processed', message: 'Modeled values',
  teams: [{id: '1', name: 'Home', abbreviation: 'HOME', side: 'home', color: '#751D4A'},
          {id: '2', name: 'Away', side: 'away', color: '#5e0009'}],
  plays: [{id, play_type: 'Pass Reception', formation: 'Shotgun', text: 'Verified passer complete to receiver', down: 2, distance: 7, quarter: 1, clock: '12:00',
           team_id: '1', end_team_id: '1', yards_to_goal: 60, end_yards_to_goal: 45, epa: .3, wpa: .02,
           resolution_version: 'cfb-resolved-1',
           secondary_coverage_json: JSON.stringify({ncaa: {matched_plays: 1, unmatched: 1, primary_overtime_plays: 2, matched_overtime_plays: 0}}),
           source_provenance_json: JSON.stringify({provenance: {formation: {provider_id: 'espn', method: 'text_parsed', processing_version: 'test'}},
             secondary_status: {ncaa: 'acquired', cfbd: 'unavailable; primary ESPN plays retained'},
             conflicts: {formation: [{provider_id: 'espn', value: 'Shotgun'}, {provider_id: 'ncaa', value: 'I-Formation'}]},
             alignment: {ncaa: {clock_disagreement: true}}}),
           participants: [{athlete_id: '10', name: 'Verified QB', role: 'passer', team_id: '1'},
                          {athlete_id: '11', name: 'Verified WR', role: 'receiver', team_id: '1'}]},
          {id: 'p2', play_type: 'Rush', text: 'Recorded rush without identity', down: 1, distance: 10, quarter: 2, clock: '09:00',
           team_id: '2', end_team_id: '2', yards_to_goal: 20, end_yards_to_goal: 17, participants: []}]});

it('opens recorded plays with involved actors, a college field, and scoped modeled context', async () => {
  vi.spyOn(api, 'cfbPlays').mockResolvedValue(detail());
  render(CFBGameTablet, {play: evidence('game1'), investigationId: 'investigation', onclose: vi.fn()});
  expect(await screen.findByRole('status')).toBeTruthy();
  await screen.findByRole('option', {name: /Verified passer/});
  expect(screen.getByRole('region', {name: /schematic for play p1/})).toBeTruthy();
  expect(screen.getByText(/a full lineup is a template/)).toBeTruthy();
  expect(screen.getByRole('heading', {name: /Recorded involved players \(2\)/})).toBeTruthy();
  expect(screen.getByText('Sources and field provenance')).toBeTruthy();
  expect(screen.getByText(/espn · text parsed · version test/)).toBeTruthy();
  expect(screen.getByText(/Source disagreements/)).toBeTruthy();
  expect(screen.getByText(/cfbd: unavailable; primary ESPN plays retained/)).toBeTruthy();
  expect(screen.getByText(/Overtime: primary ESPN plays retained/)).toBeTruthy();
  expect(screen.getByText(/sources disagree on this play's clock/)).toBeTruthy();
  const field = document.querySelector('.football-tablet .field');
  expect(field?.querySelectorAll('.yard-line')).toHaveLength(19);
  expect(field?.querySelectorAll('.inbound-hash')).toHaveLength(160);
  expect(Number(field?.querySelector('.inbound-hash')?.getAttribute('y1'))).toBeCloseTo(20 - 1 / 3);
  expect([...field!.querySelectorAll('.endzone-name')].map(node => node.textContent)).toEqual(['Home', 'Home']);
  expect(field?.querySelector('.box-area')).toBeTruthy();
  expect(field?.querySelectorAll('.field-player')).toHaveLength(22);
  expect(field?.querySelector('.field-player')?.namespaceURI).toBe('http://www.w3.org/2000/svg');
  expect(field?.querySelectorAll('.rush-ring')).toHaveLength(4);
  expect(field?.querySelector('.play-path.pass')?.getAttribute('d')).toContain(' Q ');
  expect(field?.querySelector('.play-path.after-catch')).toBeNull();
  const qbX = Number(field?.querySelector('[aria-label^="Verified QB"]')?.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]);
  const wrX = Number(field?.querySelector('[aria-label^="Verified WR"]')?.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]);
  expect(qbX).toBeLessThan(wrX);
  const marker = screen.getByRole('button', {name: /Verified QB.*illustrative placement/});
  await fireEvent.focus(marker);
  expect(document.querySelector('svg > g:last-child.tooltip')).toBeTruthy();
  expect(screen.getByRole('heading', {name: /prepared game sample/})).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Next play'}));
  expect(screen.getByText(/No participant IDs recorded/)).toBeTruthy();
  expect(screen.queryByRole('button', {name: /Verified QB.*illustrative placement/})).toBeNull();
  expect(document.querySelectorAll('.field-player')).toHaveLength(22);
  expect(document.querySelector('.play-path.carry')).toBeTruthy();
});

it('does not invent scrimmage action for penalties, special teams, missing position or unknown turnover paths', async () => {
  const base: CFBRecordedPlay = {...detail().plays[0], yards_gained: 15};
  const view = render(CFBPlayTablet, {event: {...base, id: 'penalty', play_type: 'Penalty', text: 'NO PLAY'}, teams: detail().teams});
  for (const event of [
    {...base, id: 'penalty', play_type: 'Penalty', text: 'NO PLAY'},
    {...base, id: 'kickoff', play_type: 'Kickoff'},
    {...base, id: 'negated', provider_context_json: JSON.stringify({penalty_negated_play: true})},
    {...base, id: 'missing', yards_to_goal: null}
  ]) {
    await view.rerender({event, teams: detail().teams});
    expect(document.querySelectorAll('.field-player')).toHaveLength(0);
    expect(document.querySelector('.play-path')).toBeNull();
    expect(document.querySelector('.box-area')).toBeNull();
  }
  await view.rerender({event: {...base, id: 'turnover', play_type: 'Pass Interception', interception: true}, teams: detail().teams});
  expect(document.querySelectorAll('.field-player')).toHaveLength(22);
  expect(document.querySelector('.play-path')).toBeNull();
  expect(screen.getByText(/No trajectory is shown/)).toBeTruthy();
  await view.rerender({event: {...base, id: 'sourced-return', play_type: 'Pass Interception', interception: true,
    turnover: true, air_yards: 10, provider_context_json: JSON.stringify({yds_int_return: 5})}, teams: detail().teams});
  expect(document.querySelector('.play-path.return')).toBeTruthy();
  expect(document.querySelector('.event-marker.turnover')).toBeTruthy();
});

it('uses provider air yards, YAC and direction while preserving missing and zero values', async () => {
  const base: CFBRecordedPlay = {...detail().plays[0], yards_gained: 15, air_yards: 10, yards_after_catch: 5, pass_direction: 'right'};
  const view = render(CFBPlayTablet, {event: base, teams: detail().teams});
  expect(screen.getByText('Air yards: 10 · provider-derived')).toBeTruthy();
  expect(screen.getByText('YAC: 5 · provider-derived')).toBeTruthy();
  const flight = document.querySelector('.play-path.pass')?.getAttribute('d');
  expect(document.querySelector('.play-path.after-catch')).toBeTruthy();
  const marker = screen.getByRole('button', {name: /Catch · Verified WR/});
  await fireEvent.focus(marker);
  expect(document.querySelector('.event-tooltip')).toBeTruthy();
  await view.rerender({event: {...base, provider_context_json: JSON.stringify({qb_hurry: false, cp: 0, cp_model: 'game_state'})}, teams: detail().teams});
  const sourceContext = screen.getByText('Available Provider Context (3 fields)').closest('details')!;
  await fireEvent.click(sourceContext.querySelector('summary')!);
  expect(sourceContext.textContent).toContain('false');
  expect(sourceContext.querySelectorAll('dd')[1].textContent).toBe('0');
  expect(sourceContext.textContent).toContain('game_state');
  await view.rerender({event: {...base, id: 'zero', air_yards: 0, yards_after_catch: 0, yards_gained: 0}, teams: detail().teams});
  expect(screen.getByText('Air yards: 0 · provider-derived')).toBeTruthy();
  expect(screen.getByText('YAC: 0 · provider-derived')).toBeTruthy();
  await view.rerender({event: {...base, id: 'missing-yac', yards_after_catch: null}, teams: detail().teams});
  expect(document.querySelector('.play-path.after-catch')).toBeNull();
  await view.rerender({event: {...base, id: 'missing-air', air_yards: null, yards_after_catch: null}, teams: detail().teams});
  expect(screen.queryByText(/Air yards: /)).toBeNull();
  expect(document.querySelector('.play-path.after-catch')).toBeNull();
  expect(document.querySelector('.play-path.pass')?.getAttribute('d')).not.toBe(flight);
});

it('ignores stale game responses and offers a retry instead of an empty participant list', async () => {
  let resolveOld!: (value: ReturnType<typeof detail>) => void;
  const fetch = vi.spyOn(api, 'cfbPlays').mockImplementationOnce(() => new Promise(resolve => {resolveOld = resolve;}))
    .mockRejectedValueOnce(new Error('Recorded play source unavailable')).mockResolvedValueOnce(detail('new-play'));
  const view = render(CFBGameTablet, {play: evidence('old'), investigationId: 'investigation', onclose: vi.fn()});
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await view.rerender({play: evidence('new'), investigationId: 'investigation', onclose: vi.fn()});
  await screen.findByRole('button', {name: 'Retry play detail'});
  resolveOld(detail('old-play'));
  await waitFor(() => expect(screen.queryByRole('region', {name: /old-play/})).toBeNull());
  await fireEvent.click(screen.getByRole('button', {name: 'Retry play detail'}));
  await screen.findByRole('region', {name: /new-play/});
});

it('labels additional recorded roles and keeps optional starter projections separate from snap identities', async () => {
  const base: CFBRecordedPlay = {...detail().plays[0], participants: [
    {athlete_id: '10', name: 'Verified QB', role: 'passer', team_id: '1', position: 'QB'},
    {athlete_id: '11', name: 'Recorded Tight End', role: 'receiver', team_id: '1', position: 'TE', position_source: 'ESPN participant position'},
    {athlete_id: '22', name: 'Recorded Edge', role: 'assisted_by', position: 'EDGE'},
    {athlete_id: '22', name: 'Recorded Edge', role: 'sacked_by', position: 'EDGE'},
    {athlete_id: '23', name: 'Recorded Pass Defender', role: 'pass_defender'},
    {athlete_id: '24', name: 'Recorded Forced Fumble', role: 'forced_by', team_id: '2', position: 'S'}]};
  const roster = [
    {athlete_id: '66', team_id: '1', name: 'Projected Guard', position: 'G', starter: true},
    {athlete_id: '30', team_id: '2', name: 'Projected Linebacker', position: 'LB', starter: true},
    {athlete_id: '99', team_id: '1', name: 'Bench Quarterback', position: 'QB', starter: true},
    {athlete_id: '55', team_id: '1', name: 'Did Not Play', position: 'T', starter: true, did_not_play: true},
    {athlete_id: '56', team_id: '3', name: 'Other School', position: 'T', starter: true}];
  const view = render(CFBPlayTablet, {event: base, teams: detail().teams, roster});
  expect(document.querySelectorAll('.field-player')).toHaveLength(22);
  expect(document.querySelectorAll('.field-player.recorded')).toHaveLength(5);
  expect(document.querySelectorAll('.field-player.projected')).toHaveLength(0);
  expect(screen.getByRole('button', {name: /Recorded Tight End · TE/})).toBeTruthy();
  expect(screen.getByRole('button', {name: /Recorded Edge · EDGE/})).toBeTruthy();
  expect(screen.getByRole('button', {name: /Recorded Pass Defender · DB/})).toBeTruthy();
  expect(screen.getByRole('button', {name: /Recorded Forced Fumble · S/})).toBeTruthy();
  expect(screen.getAllByRole('button', {name: / · N\/A/}).length).toBeGreaterThan(0);
  await fireEvent.click(screen.getByRole('checkbox', {name: 'Show Projected Starters'}));
  expect(document.querySelectorAll('.field-player')).toHaveLength(22);
  expect(document.querySelectorAll('.field-player.recorded')).toHaveLength(5);
  expect(document.querySelectorAll('.field-player.projected')).toHaveLength(2);
  const projected = screen.getByRole('button', {name: /Projected Guard.*Projected starter, not confirmed on this play/});
  await fireEvent.focus(projected);
  expect(document.querySelector('.tooltip')?.textContent).toContain('Projected starter, not confirmed on this play');
  expect(screen.queryByRole('button', {name: /Bench Quarterback|Did Not Play|Other School/})).toBeNull();
  expect(screen.getByRole('heading', {name: /Recorded involved players \(5\)/}).nextElementSibling?.textContent).not.toContain('Projected Guard');
  // The projection is presentation-only and never modifies the event evidence.
  expect(base.participants).toHaveLength(6);
  expect(base.participants?.some(actor => actor.athlete_id === '66')).toBe(false);
  await view.rerender({event: {...base, id: 'no-roster'}, teams: detail().teams, roster: []});
  expect(screen.queryByRole('checkbox', {name: 'Show Projected Starters'})).toBeNull();
  expect(document.querySelectorAll('.field-player.projected')).toHaveLength(0);
  expect(document.querySelectorAll('.field-player.recorded')).toHaveLength(5);
});

it('opens the cited play directly and shows its selection reason and recorded formation context', async () => {
  const selectedId = '401756849101855201'; // ESPN IDs exceed JavaScript's safe integer range.
  const plays = detail();
  plays.plays[1] = {...plays.plays[1], id: selectedId};
  vi.spyOn(api, 'cfbPlays').mockResolvedValue({...plays, plays: plays.plays.map(play => play.id === selectedId
    ? {...play, formation: 'Shotgun', formation_source: 'Recorded play narrative',
       personnel_context: {status: 'not_recorded', entries: [], scope: 'No verified personnel data for this selected play'}} : play)});
  const cited = evidence('game');
  render(CFBGameTablet, {play: {...cited, play_id: Number(selectedId), selection_metric: 'Third-down conversion rate',
    visualization: {...cited.visualization, cfb_statistics: {selected_play: {id: selectedId}}},
    evidence_role: 'counterexample', selection_reason: 'Counterexample in the measured comparison window.'},
    investigationId: 'investigation', onclose: vi.fn()});
  await screen.findByRole('region', {name: new RegExp(`schematic for play ${selectedId}`)});
  expect((screen.getByLabelText('Select recorded play') as HTMLSelectElement).value).toBe(selectedId);
  expect(screen.getByText('Counterexample in the measured comparison window.')).toBeTruthy();
  expect(screen.getByText(/Formation: Shotgun/)).toBeTruthy();
  expect(screen.getByText(/Personnel source: not recorded/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Previous play'}));
  await screen.findByRole('region', {name: /schematic for play p1/});
});
