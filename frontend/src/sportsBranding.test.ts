import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render} from '@testing-library/svelte';
import {initializeBranding, branding, playerPortrait} from './sportsBranding';
import {teamChartDisplayPalette, colorContrastRatio, CHART_SURFACE_COLOR} from './teamPalettes';
import {footballHash, footballWidth, nbaCenterToTablet, nbaCourt, soccerPitch} from './surfaceGeometry';
import PlayerPortrait from './PlayerPortrait.svelte';

afterEach(() => {cleanup(); vi.unstubAllGlobals();});

it('resolves all four sports offline with season-aware branding and readable chart colors', async () => {
  const fetch = vi.fn(() => Promise.reject(new Error('Offline')));
  vi.stubGlobal('fetch', fetch);
  await initializeBranding();
  for (const [sport, team] of [['nfl', 'KC'], ['nba', 'BOS'], ['cfb', '66'], ['soccer', '359']]) {
    const result = branding(team, sport, 2025);
    expect(result.logo).toMatch(/^https:\/\/sdv.nyc3.cdn.digitaloceanspaces.com\//);
    expect(result.colors).toHaveLength(2);
    expect(branding(team, sport, 2025)).toBe(result);
    for (const color of teamChartDisplayPalette(team, sport)) expect(colorContrastRatio(color, CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(3);
  }
  expect(branding('unresolvable team', 'soccer', 2025).colors).toBeUndefined();
  expect(fetch).not.toHaveBeenCalled();
  expect(footballWidth).toBeCloseTo(160 / 3);
  expect(footballHash()).toBeCloseTo(23 + 7 / 12);
  expect(footballHash(true)).toBe(20);
  expect(nbaCourt.court_length).toBe(94);
  expect(nbaCenterToTablet(41.75, 0)).toEqual({x:25, y:0});
  expect([soccerPitch.pitch_length, soccerPitch.pitch_width]).toEqual([105, 68]);
});

it('uses verified player ID namespaces and gracefully falls back when portraits fail or are unsupported', async () => {
  expect(await playerPortrait('2544', 'nba')).toContain('cdn.nba.com');
  expect(await playerPortrait('4432722', 'cfb')).toContain('college-football');
  expect(await playerPortrait('3139477', 'nfl')).toContain('3139477');
  expect(await playerPortrait('359', 'soccer')).toBeNull();
  expect(await playerPortrait('not-an-id', 'cfb')).toBeNull();
  const view = render(PlayerPortrait, {id:'4432722', sport:'cfb', name:'Recorded Player'});
  await vi.waitFor(() => expect(view.container.querySelector('img')).not.toBeNull());
  await fireEvent.error(view.container.querySelector('img')!);
  expect(view.container.querySelector('img')).toBeNull();
  expect(view.container.textContent).toContain('RP');
  await view.rerender({id:'5080403', sport:'cfb', name:'Jaylen Raynor', historical:true});
  expect(view.container.querySelector('img')).toBeNull();
  expect(view.container.querySelector('[title]')?.getAttribute('title')).toContain('No verified game-time portrait');
  await view.rerender({id:'359', sport:'soccer', name:'Soccer Player'});
  expect(view.container.textContent).toContain('SP');
});
