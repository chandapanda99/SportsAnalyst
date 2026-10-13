import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import CFBGameTablet from './CFBGameTablet.svelte';
import {api} from './api';
import type {Evidence} from './types';

afterEach(() => {cleanup(); vi.restoreAllMocks();});
const evidence = (id: string): Evidence => ({evidence_id: id, sport: 'cfb', season: 2024, game_id: id, play_id: 0,
  description: 'Away at Home', visualization: {sport: 'cfb', cfb_statistics: {rows: [], schools: {'1': 'Home'},
    covered_team_epa: [{team_id: '1', epa_per_play: .15, plays: 60, games: 1}]}}} as Evidence);
const detail = (id = 'p1') => ({coverage: '2/3 source plays processed', message: 'Modeled values',
  teams: [{id: '1', name: 'Home', abbreviation: 'HOME', side: 'home', color: '#751D4A'},
          {id: '2', name: 'Away', side: 'away', color: '#5e0009'}],
  plays: [{id, text: 'Verified passer complete to receiver', down: 2, distance: 7, quarter: 1, clock: '12:00',
           team_id: '1', end_team_id: '1', yards_to_goal: 60, end_yards_to_goal: 45, epa: .3, wpa: .02,
           participants: [{athlete_id: '10', name: 'Verified QB', role: 'passer', team_id: '1'},
                          {athlete_id: '11', name: 'Verified WR', role: 'receiver', team_id: '1'}]},
          {id: 'p2', text: 'Recorded rush without identity', down: 1, distance: 10, quarter: 2, clock: '09:00',
           team_id: '2', end_team_id: '2', yards_to_goal: 20, end_yards_to_goal: 17, participants: []}]});

it('opens recorded plays with involved actors, a college field, and scoped modeled context', async () => {
  vi.spyOn(api, 'cfbPlays').mockResolvedValue(detail());
  render(CFBGameTablet, {play: evidence('game1'), investigationId: 'investigation', onclose: vi.fn()});
  expect(await screen.findByRole('status')).toBeTruthy();
  await screen.findByRole('option', {name: /Verified passer/});
  expect(screen.getByRole('region', {name: /schematic for play p1/})).toBeTruthy();
  expect(screen.getByText(/not a full lineup|No full lineup/)).toBeTruthy();
  expect(screen.getByRole('heading', {name: /Recorded involved players \(2\)/})).toBeTruthy();
  const marker = screen.getByRole('button', {name: /Verified QB.*illustrative placement/});
  await fireEvent.focus(marker);
  expect(document.querySelector('svg > g:last-child.tooltip')).toBeTruthy();
  expect(screen.getByRole('heading', {name: /prepared game sample/})).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Next play'}));
  expect(screen.getByText(/No participant IDs recorded/)).toBeTruthy();
  expect(screen.queryByRole('button', {name: /Verified QB.*illustrative placement/})).toBeNull();
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
