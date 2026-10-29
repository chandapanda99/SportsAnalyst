import {cleanup, fireEvent, render, screen} from '@testing-library/svelte';
import {afterEach, expect, it} from 'vitest';
import SoccerAnalytics from './SoccerAnalytics.svelte';

afterEach(cleanup);

it('keeps Understat and FotMob shot models separate and does not infer xGOT', async () => {
  render(SoccerAnalytics, {rows: [
    {provider: 'fotmob', team_id: '1', shots_json: JSON.stringify([{x: 90, y: 34, expectedGoals: .1}])},
    {provider: 'understat', team_id: '1', team_name: 'Home', shots_json: JSON.stringify([
      {x: 94.5, y: 34, min: 8, expectedGoals: .25, playerName: 'Recorded forward', eventType: 'Goal'}])},
  ]});
  await fireEvent.change(screen.getByLabelText('Data source'), {target: {value: 'understat'}});
  expect(screen.getByText(/1 recorded shots · 1/)).toBeTruthy();
  expect(screen.getByText('0.25')).toBeTruthy();
  expect(document.querySelector('dl')?.textContent).toContain('xGOT—');
  expect(screen.queryByText('0.1')).toBeNull();
});

it('opens recorded shots, team counters, native player statistics and formation context without inventing missing values', async () => {
  const rows = [{team_id: '1', team_name: 'Home', expected_goals: 1.2, accurate_passes: 90, total_passes: 100,
    shots_json: JSON.stringify([{id: 1, x: 95, y: 30, min: 8, playerName: 'Recorded forward', eventType: 'Goal',
      expectedGoals: .2, expectedGoalsOnTarget: .6, situation: 'RegularPlay', shotType: 'RightFoot'},
      {id: 2, x: 85, y: 40, min: 15, playerName: 'Recorded midfielder', eventType: 'Miss', expectedGoals: .1},
      {id: 3, min: 20, eventType: 'Miss'}]),
    players_json: JSON.stringify([{provider_player_id: 'native7', name: 'Recorded forward', shirt_number: '9',
      team_id: '1', minutes_played: 90, interceptions: 2}]), context_json: JSON.stringify({formation: '4-3-3', coverage_level: 'xG'})}];
  const view = render(SoccerAnalytics, {rows});
  expect(screen.getByText(/3 recorded shots · 2/)).toBeTruthy();
  expect(screen.getByRole('img', {name: /Recorded shot locations/})).toBeTruthy();
  expect(screen.getByText('0.6')).toBeTruthy();
  await fireEvent.change(screen.getByLabelText('Recorded shot'), {target: {value: '1'}});
  expect(view.container.querySelector('dl')?.textContent).toContain('xGOT—');
  await fireEvent.click(screen.getByRole('button', {name: 'Team statistics'}));
  expect(screen.getByRole('region', {name: 'Recorded team statistics'}).textContent).toContain('accurate passes90');
  await fireEvent.click(screen.getByRole('button', {name: 'Player statistics'}));
  expect(screen.getByText('interceptions')).toBeTruthy();
  expect(screen.getByText(/Recorded player-match values/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name: 'Match context'}));
  expect(screen.getByText(/Formation: 4-3-3/)).toBeTruthy();
});
