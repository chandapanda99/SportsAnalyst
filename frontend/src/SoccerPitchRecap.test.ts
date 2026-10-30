import {cleanup, fireEvent, render, screen, within} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import SoccerPitchRecap from './SoccerPitchRecap.svelte';
import SoccerMatchTablet from './SoccerMatchTablet.svelte';
import type {Evidence} from './types';
import fotmobCapture from '../../tests/fixtures/soccer/fotmob_match.json';

afterEach(() => {cleanup(); vi.useRealTimers();});

it('renders captured shot origin and goal placement, a save glove, and a blocked ball without a false goal crossing', async () => {
  const shots = fotmobCapture.content.shotmap.shots;
  const goal = shots.find(s => s.eventType === 'Goal')!;
  const analytics = [{provider:'fotmob', game_id:'123', team_id:'1', shots_json:JSON.stringify(shots)}];
  const timeline = [{id:'espn-goal', timeline_key:'g', clock:"6'", type:'Goal', text:'Recorded goal',
    side:'home', athlete_name:goal.playerName, spatial_provider:'fotmob', spatial_event_id:String(goal.id),
    spatial_context:{shot:goal}}];
  const view = render(SoccerPitchRecap, {analytics, timeline, focusTimelineKey:'g'});
  expect(view.container.querySelector('.event-point')?.getAttribute('cx')).toBe(String(goal.x));
  expect(screen.queryByLabelText('Shot goal-mouth view')).toBeNull();
  expect(screen.getByText('Final third · vertical view')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name:'Show full pitch'}));
  expect(view.container.querySelector('.event-pitch')?.classList.contains('focused')).toBe(false);
  await fireEvent.click(screen.getByRole('button', {name:'Focus on shot'}));
  expect(view.container.querySelector('.shot-path')?.getAttribute('y2')).toBe(String(goal.goalCrossedY));
  await fireEvent.keyDown(screen.getByRole('button', {name:'Open shot detail'}), {key:'Enter'});
  expect(screen.getByText('Where the goal crossed the line')).toBeTruthy();
  expect(screen.getByRole('button', {name:'← Back to pitch'})).toBe(document.activeElement);
  expect(screen.getAllByLabelText('Goal: ball').length).toBe(1);
  expect(screen.getByText(goal.expectedGoalsOnTarget.toFixed(3))).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', {name:'← Back to pitch'}));
  expect(screen.getByRole('button', {name:'Open shot detail'})).toBe(document.activeElement);
  await fireEvent.change(screen.getByLabelText('Recap source'), {target:{value:'fotmob'}});
  expect(screen.getAllByLabelText('Saved shot: glove').length).toBeGreaterThan(0);
  await fireEvent.click(screen.getByRole('button', {name:'Open shot detail'}));
  expect(screen.getByText(/Glove marks projected placement/)).toBeTruthy();
  const blocked = {...shots[0], id:77, isBlocked:true, blockedX:98, blockedY:32};
  await view.rerender({timeline:[], focusTimelineKey:'', analytics:[{provider:'fotmob', shots_json:JSON.stringify([blocked])}]});
  expect(screen.getByLabelText('Blocked shot: ball with red X')).toBeTruthy();
  expect(view.container.querySelector('.shot-path')?.getAttribute('x2')).toBe('98');
  expect(screen.queryByLabelText('Selected shot detail')).toBeNull();
  await fireEvent.click(screen.getByRole('button', {name:'Open shot detail'}));
  expect(screen.getByText('Blocked before the goal line. No goal crossing is shown.')).toBeTruthy();
  expect(screen.queryByLabelText('Front view of the goal with recorded shot placement')).toBeNull();
  await view.rerender({analytics:[{provider:'fotmob', shots_json:JSON.stringify([{...goal, goalCrossedY:null, goalCrossedZ:null}])}]});
  await fireEvent.click(screen.getByRole('button', {name:'Open shot detail'}));
  expect(screen.getByText('Goal-mouth placement was not recorded for this shot.')).toBeTruthy();
  expect(view.container.querySelector('.shot-path')).toBeNull();
  await view.rerender({analytics:[{provider:'fotmob', shots_json:JSON.stringify([{...goal, x:60}])}]});
  expect(screen.getByText('Full pitch')).toBeTruthy();
  expect(screen.queryByRole('button', {name:'Show full pitch'})).toBeNull();
});

const actions = [
  {id: 'b', provider: 'statsbomb', event_type: 'Substitution', sequence: 2, minute: 65},
  {id: 'a', provider: 'statsbomb', event_type: 'Pass', sequence: 1, minute: 2, second: 15, period: 1,
    player_name: 'Native player', team_id: '1', start_x: 0, start_y: 30, end_x: 55, end_y: 32, xt: .03, possession: 2},
];

it('orders native events and clears the pitch for missing coordinates, without inventing a connecting path', async () => {
  const view = render(SoccerPitchRecap, {actions, total: 2500});
  expect(screen.getByText(/2 of 2500 source events/)).toBeTruthy();
  expect(screen.getByText(/This recap is incomplete/)).toBeTruthy();
  expect(screen.getByText('0.030')).toBeTruthy();
  expect(view.container.querySelector('.action-path')?.getAttribute('x1')).toBe('0');
  expect(view.container.querySelector('.action-path')?.getAttribute('x2')).toBe('55');
  // Shared vendor geometry includes both penalty areas, not an invented field outline.
  expect(view.container.querySelectorAll('svg path').length).toBeGreaterThan(10);
  await fireEvent.click(screen.getByRole('button', {name: 'Next action'}));
  expect(screen.getByText('No spatial location was recorded for this event.')).toBeTruthy();
  expect(view.container.querySelector('.action-path')).toBeNull();
  expect(view.container.querySelector('.event-point')).toBeNull();
  await fireEvent.change(screen.getByLabelText('Event type'), {target: {value: 'Pass'}});
  expect(view.container.querySelector('.action-path')).not.toBeNull();
  expect(screen.getByText('Source event: a')).toBeTruthy();
});

it('keeps shot models and minute-only ordering separate from a possession stream', async () => {
  const analytics = [{provider: 'understat', team_id: '1', team_name: 'Home', shots_json: JSON.stringify([
    {id: 's1', x: 94.5, y: 34, min: 23, playerName: 'Forward', eventType: 'Goal', expectedGoals: .25},
    {id: 's2', x: 999, y: 34, min: 23, playerName: 'Forward', eventType: 'Miss', expectedGoals: .05},
  ])}];
  const view = render(SoccerPitchRecap, {actions, analytics, total: 3000});
  await fireEvent.change(screen.getByLabelText('Recap source'), {target: {value: 'understat'}});
  expect(screen.getByText('0.250')).toBeTruthy();
  expect(screen.getByText(/Ordering at this recorded time is not established/)).toBeTruthy();
  expect(screen.getByText('23′ · minute precision')).toBeTruthy();
  expect(screen.queryByLabelText('Possession')).toBeNull();
  expect(view.container.querySelector('.action-path')).toBeNull();
  expect(view.container.querySelector('.event-point')?.getAttribute('cx')).toBe('94.5');
  expect(screen.getAllByText('Not recorded').length).toBeGreaterThan(0);
  await fireEvent.click(screen.getByRole('button', {name: 'Next action'}));
  expect(screen.getByText('No spatial location was recorded for this event.')).toBeTruthy();
  await fireEvent.change(screen.getByLabelText('Recap source'), {target: {value: 'statsbomb'}});
  expect(screen.getByText('Source event: a')).toBeTruthy();
  expect(screen.getByLabelText('Possession')).toBeTruthy();
});

it('plays at presentation pace, pauses on filtering or match changes, and releases playback on close', async () => {
  vi.useFakeTimers();
  const view = render(SoccerPitchRecap, {actions: [...actions,
    {id: 'c', event_type: 'Shot', sequence: 3, minute: 80}], matchKey: 'first'});
  await fireEvent.click(screen.getByRole('button', {name: 'Play recap'}));
  await vi.advanceTimersByTimeAsync(1500);
  expect(screen.getByText('Source event: b')).toBeTruthy();
  await fireEvent.change(screen.getByLabelText('Event type'), {target: {value: 'Pass'}});
  expect(screen.getByRole('button', {name: 'Play recap'}).getAttribute('aria-pressed')).toBe('false');
  await fireEvent.change(screen.getByLabelText('Event type'), {target: {value: 'all'}});
  await fireEvent.click(screen.getByRole('button', {name: 'Play recap'}));
  await view.rerender({actions, matchKey: 'second'});
  expect(screen.getByText('Source event: a')).toBeTruthy();
  expect(screen.getByRole('button', {name: 'Play recap'}).getAttribute('aria-pressed')).toBe('false');
  await fireEvent.click(screen.getByRole('button', {name: 'Play recap'}));
  await vi.advanceTimersByTimeAsync(1500);
  expect(screen.getByText('Source event: b')).toBeTruthy();
  expect(screen.getByRole('button', {name: 'Play recap'}).getAttribute('aria-pressed')).toBe('false');
  await fireEvent.click(screen.getByRole('button', {name: 'Play recap'}));
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('integrates one recap with match evidence while retaining the timeline and secondary statistics', async () => {
  const play = {evidence_id: 'match-1', game_id: 'g1', sport: 'soccer', season: 2025,
    visualization: {home_team_name: 'Home', away_team_name: 'Away', soccer_actions: actions,
      soccer_actions_count: 2, soccer_analytics: [{provider: 'understat', team_id: '1', team_name: 'Home', expected_goals: .5}],
      soccer_timeline: [{clock: "23'", type: 'Goal', text: 'Recorded goal', side: 'home', scoring_play: true}]}} as Evidence;
  render(SoccerMatchTablet, {play, onclose: vi.fn()});
  expect(screen.getAllByRole('region', {name: 'Soccer pitch event recap'})).toHaveLength(1);
  expect(screen.getByLabelText('Recorded match events in time order')).toBeTruthy();
  expect(screen.getByText('Additional recorded match statistics')).toBeTruthy();
  expect(screen.queryByRole('button', {name: 'Shots & chances'})).toBeNull();
});

it('clicking a timeline event selects that exact ESPN event and clears unrelated source/filter state', async () => {
  const play = {evidence_id: 'timeline-match', game_id: 'g2', sport: 'soccer', season: 2025,
    visualization: {home_team_name: 'Home', away_team_name: 'Away', soccer_actions: actions,
      soccer_analytics: [{provider: 'understat', team_id: '1', shots_json: JSON.stringify([
        {id: 'unrelated-goal', x: 90, y: 34, min: 33, eventType: 'Goal', playerName: 'Another player'}])}],
      soccer_timeline: [
        {id: 'goal-one', clock: "33'", type: 'Goal - Volley', text: 'First recorded goal.', side: 'home',
          sequence: '1', athlete_name: 'First scorer', field_position_x: .23, field_position_y: .2},
        {id: 'goal-two', clock: "33'", type: 'Goal - Header', text: 'Second recorded goal.', side: 'away',
          sequence: '2', athlete_name: 'Second scorer', field_position_x: .4, field_position_y: .5},
        {id: 'change', clock: "45'+5'", type: 'Substitution', text: 'Incoming replaces Outgoing.', side: 'home',
          sequence: '3', player_in: 'Incoming', player_out: 'Outgoing', field_position_x: 0, field_position_y: 0},
      ].reverse()}} as Evidence;
  const view = render(SoccerMatchTablet, {play, onclose: vi.fn()});
  const recap = screen.getByRole('region', {name: 'Soccer pitch event recap'});
  expect(within(recap).getByText('Source event: goal-one')).toBeTruthy();
  await fireEvent.change(within(recap).getByLabelText('Recap source'), {target: {value: 'understat'}});
  await fireEvent.click(screen.getByRole('button', {name: "33' Goal - Header — Away"}));
  expect(within(recap).getByText('Source event: goal-two')).toBeTruthy();
  expect(within(recap).getByRole('heading', {name: 'Goal - Header · Second scorer'})).toBeTruthy();
  expect(view.container.querySelector('.event-point')?.getAttribute('cx')).toBe('21');
  expect(within(recap).queryByText('Another player')).toBeNull();
  await fireEvent.click(screen.getByRole('button', {name: "45'+5' Substitution — Home"}));
  expect(within(recap).getByText('Source event: change')).toBeTruthy();
  expect(within(recap).getByText(/selected timeline event has no recorded pitch coordinates/)).toBeTruthy();
  expect(within(recap).getAllByText('Incoming').length).toBeGreaterThan(0);
  expect(view.container.querySelector('.event-point')).toBeNull();
  expect(view.container.querySelector('.action-path')).toBeNull();
  // A repeated click re-focuses the selection after independent source browsing.
  await fireEvent.change(within(recap).getByLabelText('Recap source'), {target: {value: 'statsbomb'}});
  await fireEvent.click(screen.getByRole('button', {name: "45'+5' Substitution — Home"}));
  expect(within(recap).getByText('Source event: change')).toBeTruthy();
});

it('renders static commentary zones, event cards and verified spatial enrichment without playback', async () => {
  const goal = {id: 'goal', timeline_key: 'g', clock: "33'", type: 'Goal', side: 'home',
    athlete_name: 'Alex Forward', text: 'Alex Forward left footed shot from the centre of the box to the top left corner. Assisted by Jamie Player.'};
  const view = render(SoccerPitchRecap, {timeline: [goal], focusTimelineKey: 'g'});
  expect(view.container.querySelector('.commentary-zone')).toBeTruthy();
  expect(view.container.querySelector('.event-point')).toBeNull();
  expect(screen.getByText(/From commentary: from the centre of the box/)).toBeTruthy();
  expect(screen.queryByRole('button', {name: 'Play recap'})).toBeNull();
  await view.rerender({timeline: [{...goal, text: 'Goal awarded after VAR review.'}], focusTimelineKey: 'g'});
  expect(screen.getByLabelText('Event summary visual')).toBeTruthy();
  expect(view.container.querySelector('.pitch-wrap svg')).toBeNull();
  await view.rerender({timeline: [{...goal, spatial_provider: 'whoscored', spatial_event_id: 'ws-1',
    spatial_context: {start_x: 90, start_y: 30, coordinate_system: 'WhoScored provider coordinates'}}], focusTimelineKey: 'g'});
  expect(view.container.querySelector('.event-point')?.getAttribute('cx')).toBe('90');
  expect(view.container.querySelector('.commentary-zone')).toBeNull();
  expect(screen.getByText(/matched event ws-1/)).toBeTruthy();
});
