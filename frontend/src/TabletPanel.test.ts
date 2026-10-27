import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import TabletPanel from './TabletPanel.svelte';
import * as loader from './tabletLoader';
import {api} from './api';
import type {Evidence} from './types';

afterEach(() => {cleanup(); vi.restoreAllMocks();});

it.each(['nfl', 'cfb', 'nba', 'soccer'])('shows an interactive placeholder before mounting the %s tablet', async sport => {
  const loaded = await loader.loadTablet(sport);
  let complete!: (value: typeof loaded) => void;
  const loading = vi.spyOn(loader, 'loadTablet').mockImplementationOnce(() => new Promise(resolve => {complete = resolve;}));
  const play: Evidence = {evidence_id: `play-${sport}`, game_id: '2025_01_KC_BUF', play_id: 1,
    description: 'Recorded play', visualization: {sport, yardline_100: 50, play_type: 'run'}};
  vi.spyOn(api, 'nflPlays').mockResolvedValue({plays: [play], coverage: '1 recorded play'});
  vi.spyOn(api, 'cfbPlays').mockResolvedValue({teams: [], plays: [{id: '1', play_type: 'Rush', text: 'Recorded play',
    yards_to_goal: 50, yards_gained: 2}], coverage: '1 recorded play'});
  const before = JSON.stringify(play);
  const view = render(TabletPanel, {play, investigationId: 'investigation', onclose: vi.fn()});
  expect(screen.getByText('Rendering Tablet…')).toBeTruthy();
  await waitFor(() => expect(loading).toHaveBeenCalledTimes(1));
  const marker = view.container.querySelector('.preview svg g')!;
  const initial = marker.getAttribute('transform');
  await fireEvent.input(screen.getByRole('slider', {name: 'Move preview ball'}), {target: {value: '85'}});
  expect(marker.getAttribute('transform')).not.toBe(initial);
  expect(JSON.stringify(play)).toBe(before);
  complete(loaded);
  await waitFor(() => expect(screen.queryByLabelText('Tablet loading')).toBeNull());
  expect(view.container.querySelector(sport === 'nba' ? '.tablet.basketball' : sport === 'soccer' ? '.soccer-match-tablet' : '.football-tablet')).toBeTruthy();
});

it('ignores stale tablet imports, supports retry, and cancels mounting after close', async () => {
  const basketball = await loader.loadTablet('nba');
  const soccer = await loader.loadTablet('soccer');
  let finishOld!: (value: typeof basketball) => void;
  let finishClosed!: (value: typeof soccer) => void;
  const loading = vi.spyOn(loader, 'loadTablet')
    .mockImplementationOnce(() => new Promise(resolve => {finishOld = resolve;}))
    .mockRejectedValueOnce(new Error('Tablet asset unavailable'))
    .mockResolvedValueOnce(soccer)
    .mockImplementationOnce(() => new Promise(resolve => {finishClosed = resolve;}));
  const onclose = vi.fn();
  const play: Evidence = {evidence_id: 'nba-old', game_id: 'game', play_id: 1, visualization: {sport: 'nba'}};
  const view = render(TabletPanel, {play, investigationId: 'report', onclose});
  await waitFor(() => expect(loading).toHaveBeenCalledTimes(1));
  await view.rerender({play: {...play, evidence_id: 'soccer-new', visualization: {sport: 'soccer'}}, investigationId: 'report', onclose});
  expect((await screen.findByRole('alert')).textContent).toContain('Tablet asset unavailable');
  await fireEvent.click(screen.getByRole('button', {name: 'Retry tablet'}));
  await screen.findByLabelText('Soccer match evidence');
  finishOld(basketball);
  await waitFor(() => expect(view.container.querySelector('.tablet.basketball')).toBeNull());
  await view.rerender({play: {...play, evidence_id: 'closed', visualization: {sport: 'soccer'}}, investigationId: 'report', onclose});
  await waitFor(() => expect(loading).toHaveBeenCalledTimes(4));
  await fireEvent.click(screen.getByRole('button', {name: 'Close tablet'}));
  expect(onclose).toHaveBeenCalledTimes(1);
  view.unmount();
  finishClosed(soccer);
  expect(screen.queryByLabelText('Soccer match evidence')).toBeNull();
});
