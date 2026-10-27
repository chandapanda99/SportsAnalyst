import {cleanup, render} from '@testing-library/svelte';
import {afterEach, expect, it} from 'vitest';
import PlayTablet from './PlayTablet.svelte';
import CFBPlayTablet from './CFBPlayTablet.svelte';
import {buildPlaySchematic} from './playSchematic';
import type {SpecialTeamsContext, CFBRecordedPlay} from './types';

afterEach(cleanup);

it('renders NFL kicks and returns with specialist roles, correct direction, and no scrimmage formation', async () => {
  const base = {evidence_id: 'kick', game_id: '2025_01_ARI_NO', play_id: 1, team: 'ARI',
    visualization: {sport: 'nfl', possession_team: 'ARI', defensive_team: 'NO', yards_to_go: 10}};
  const fieldGoal: SpecialTeamsContext = {kind: 'field_goal', start_yards_to_goal: 24, kick_distance: 42,
    kicker: 'Recorded Kicker', result: 'made', kicking_team: 'ARI', receiving_team: 'NO'};
  const view = render(PlayTablet, {play: {...base, visualization: {...base.visualization, special_teams: fieldGoal}}, onclose: () => {}});
  expect(document.querySelector('.play-path.kick')).toBeTruthy();
  expect(document.querySelector('.goalposts')).toBeTruthy();
  expect(view.getByText('Field goal · Good')).toBeTruthy();
  expect(view.getByRole('button', {name: 'Recorded Kicker · K'})).toBeTruthy();
  const punt: SpecialTeamsContext = {kind: 'punt', start_yards_to_goal: 76, kick_distance: 60, return_yards: 7, kicker: 'Punter', returner: 'Returner'};
  const kickoff: SpecialTeamsContext = {kind: 'kickoff', start_yards_to_goal: 65, kick_distance: 65, return_yards: 22, kicking_team: 'NO', receiving_team: 'ARI'};
  for (const kick of [punt, kickoff]) {
    const visual = {...base.visualization, special_teams: kick};
    await view.rerender({play: {...base, visualization: visual}, onclose: () => {}});
    const diagram = buildPlaySchematic(visual);
    const flight = diagram.paths.find(path => path.kind === 'kick')!;
    const returned = diagram.paths.find(path => path.kind === 'return')!;
    expect(flight.endX).toBeGreaterThan(diagram.startX);
    expect(returned.endX).toBeLessThan(flight.endX);
    if (kick.kind === 'punt') expect(diagram.players.find(player => player.position === 'P')!.x).toBeLessThan(diagram.startX);
    expect(document.querySelectorAll('.field-player').length).toBeLessThanOrEqual(2);
    expect(document.querySelector('.box-area, .line-to-gain, .rush-ring, .play-path.carry')).toBeNull();
  }
  expect(view.getByText('NO kicking team')).toBeTruthy();
  // A saved report with no new metadata still renders its explicitly stated kick distance.
  await view.rerender({play: {...base, description: 'Punter punts 60 yards, fair catch.',
    visualization: {...base.visualization, play_type: 'punt', yardline_100: 76}}, onclose: () => {}});
  expect(view.getByText('Punt · Fair catch')).toBeTruthy();
  expect(document.querySelector('.play-path.kick')).toBeTruthy();
  expect(document.querySelector('.play-path.return')).toBeNull();
  await view.rerender({play: {...base, description: 'Kicker kicks 65 yards. Touchback to the ARI 35.',
    visualization: {...base.visualization, play_type: 'kickoff', yardline_100: 35}}, onclose: () => {}});
  expect(document.querySelector('.event-marker.placement')?.getAttribute('transform')).toContain('translate(75 ');
  expect(document.querySelector('.play-path.return')).toBeNull();
});

it('does not invent returns, touchback placement, miss locations, or action on blocked/nullified kicks', async () => {
  const view = render(PlayTablet, {play: {evidence_id: 'edge', game_id: 'game', play_id: 1}, onclose: () => {}});
  for (const kick of [
    {kind: 'kickoff', start_yards_to_goal: 65, kick_distance: 65, touchback: true, return_yards: 0},
    {kind: 'punt', start_yards_to_goal: 76, kick_distance: 45, fair_catch: true, return_yards: 0},
    {kind: 'punt', start_yards_to_goal: 76, kick_distance: 45, downed: true},
    {kind: 'punt', start_yards_to_goal: 76, kick_distance: 45, out_of_bounds: true},
    {kind: 'kickoff', start_yards_to_goal: 65, kick_distance: 12, onside: true, own_recovery: true},
    {kind: 'field_goal', start_yards_to_goal: 40, kick_distance: 58, result: 'missed'},
    {kind: 'punt', start_yards_to_goal: 70, kick_distance: 0, blocked: true},
    {kind: 'kickoff', kick_distance: 65},
    {kind: 'field_goal', start_yards_to_goal: 24, kick_distance: 42, result: 'made', no_play: true},
  ] satisfies SpecialTeamsContext[]) {
    const visual = {special_teams: kick};
    await view.rerender({play: {evidence_id: 'edge', game_id: 'game', play_id: 1, visualization: visual}, onclose: () => {}});
    expect(document.querySelector('.play-path.return, .play-path.carry, .box-area')).toBeNull();
    if (kick.kind === 'field_goal' || kick.blocked || !('start_yards_to_goal' in kick)) {
      expect(document.querySelector('.play-path.kick')).toBeNull();
    }
    expect(document.querySelector('.event-marker.placement')).toBeNull(); // No hardcoded touchback rule.
  }
});

it('uses CFB recorded kick distances and actor identities without using net yards as kick or return distance', async () => {
  const teams = [{id: '1', name: 'Home', abbreviation: 'HOME', side: 'home', color: '#751D4A'},
    {id: '2', name: 'Away', abbreviation: 'AWAY', side: 'away', color: '#5e0009'}];
  const event: CFBRecordedPlay = {id: 'punt', team_id: '1', end_team_id: '2', yards_to_goal: 70, end_yards_to_goal: 35,
    play_type: 'Punt', text: 'Punter punts 50 yards, Returner return 15 yards.', yards_gained: 0,
    participants: [{athlete_id: '7', role: 'punter', name: 'College Punter', team_id: '1'},
      {athlete_id: '8', role: 'punt_returner', name: 'College Returner', team_id: '2'}]};
  const view = render(CFBPlayTablet, {event, teams});
  expect(view.getByText('Punt · 15 yd return')).toBeTruthy();
  expect(document.querySelector('.play-path.kick')).toBeTruthy();
  expect(document.querySelector('.play-path.return')).toBeTruthy();
  expect(document.querySelectorAll('.field-player')).toHaveLength(2);
  expect(document.querySelector('.box-area')).toBeNull();
  await view.rerender({event: {...event, id: 'provider-punt', text: 'Punt', yards_gained: 99,
    provider_context_json: JSON.stringify({yds_punted: 50, yds_punt_return: 0, punt_fair_catch: true})}, teams});
  expect(view.getByText('Punt · Fair catch')).toBeTruthy();
  expect(view.getByText('Kick distance: 50 yd')).toBeTruthy();
  expect(document.querySelector('.play-path.return')).toBeNull();
  await view.rerender({event: {...event, id: 'fg', play_type: 'Field Goal Good', text: 'Recorded kicker 42 yd field goal GOOD.',
    yards_to_goal: 24, participants: [{athlete_id: '9', name: 'College Kicker', role: 'kicker', team_id: '1'}]}, teams});
  expect(view.getByText('Field goal · Good')).toBeTruthy();
  expect(document.querySelector('.goalposts')).toBeTruthy();
  await view.rerender({event: {...event, id: 'unknown', play_type: 'Kickoff', text: 'Kickoff', yards_gained: 60, participants: []}, teams});
  expect(view.getByText('Kickoff · Outcome not recorded')).toBeTruthy();
  expect(document.querySelector('.play-path')).toBeNull();
  await view.rerender({event: {...event, id: 'no-play', text: 'Punt NO PLAY', no_play: true}, teams});
  expect(document.querySelector('.play-path')).toBeNull();
});
