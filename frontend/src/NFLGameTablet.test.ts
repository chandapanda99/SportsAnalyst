import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import NFLGameTablet from './NFLGameTablet.svelte';
import {api} from './api';
import type {Evidence} from './types';

afterEach(() => {cleanup(); vi.restoreAllMocks();});
const cited: Evidence = {evidence_id: 'cited', game_id: '2025_01_KC_BUF', play_id: 20, description: 'Mahomes completion',
  epa: .4, evidence_role: 'supports_change', visualization: {sport: 'nfl', quarter: 1, clock: '10:00',
    possession_team: 'KC', defensive_team: 'BUF', home_team_abbreviation: 'BUF', down: 2, yards_to_go: 5, yardline_100: 60}};
const opponent: Evidence = {...cited, evidence_id: 'context', play_id: 30, description: 'Buffalo kickoff',
  epa: undefined, evidence_role: undefined, visualization: {...cited.visualization, possession_team: 'BUF', play_type: 'kickoff'}};

it('opens on the cited NFL play, browses opponent context, searches, and returns without changing evidence', async () => {
  vi.spyOn(api, 'nflPlays').mockResolvedValue({plays: [cited, opponent], coverage: '2 recorded plays'});
  render(NFLGameTablet, {play: cited, investigationId: 'report', onclose: vi.fn()});
  expect(screen.getByRole('heading', {name: 'CHIEFS at BILLS'})).toBeTruthy();
  expect(screen.getByText('NFL · RECORDED GAME CONTEXT')).toBeTruthy();
  expect(screen.getByLabelText('Selected NFL play metrics')).toBeTruthy();
  await waitFor(() => expect((screen.getByLabelText('Select game play') as HTMLSelectElement).disabled).toBe(false));
  expect((screen.getByLabelText('Select game play') as HTMLSelectElement).value).toBe('20');
  await fireEvent.click(screen.getByRole('button', {name: 'Next play'}));
  expect(screen.getByRole('region', {name: /play 30/})).toBeTruthy();
  expect(screen.getByText('Game browsing context · not selected as report evidence')).toBeTruthy();
  await fireEvent.input(screen.getByLabelText('Search game plays'), {target: {value: 'not-a-play'}});
  expect(screen.getByText('No recorded game plays match this search.')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Return to cited play'}));
  expect(screen.getByRole('region', {name: /play 20/})).toBeTruthy();
  expect(cited.evidence_role).toBe('supports_change');
});

it('ignores stale game responses and keeps the cited schematic visible during a retryable failure', async () => {
  let resolveOld!: (value: {plays: Evidence[]; coverage: string}) => void;
  const fetch = vi.spyOn(api, 'nflPlays').mockImplementationOnce(() => new Promise(resolve => {resolveOld = resolve;}))
    .mockRejectedValueOnce(new Error('Game data unavailable')).mockResolvedValueOnce({plays: [opponent], coverage: 'Current game'});
  const view = render(NFLGameTablet, {play: cited, investigationId: 'report', onclose: vi.fn()});
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await view.rerender({play: opponent, investigationId: 'report', onclose: vi.fn()});
  await screen.findByRole('button', {name: 'Retry game plays'});
  resolveOld({plays: [cited], coverage: 'Stale game'});
  await waitFor(() => expect(screen.queryByText('Stale game')).toBeNull());
  expect(screen.getByRole('region', {name: /play 30/})).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Retry game plays'}));
  await screen.findByText(/Current game/);
});
