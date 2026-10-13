import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/svelte';
import {afterEach, expect, it, vi} from 'vitest';
import CFBDiscovery from './CFBDiscovery.svelte';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('loads only selected conference metadata, ignores stale responses, and exposes retryable errors', async () => {
  let stale: (value: Response) => void;
  const changes = vi.fn();
  const json = (value: unknown) => new Response(JSON.stringify(value), {headers: {'content-type': 'application/json'}});
  const fetch = vi.fn((input: string) => {
    const url = new URL(input, 'http://localhost');
    if (!url.searchParams.has('season')) return Promise.resolve(json({seasons: [2025, 2024], conferences: [], teams: []}));
    if (!url.searchParams.has('subdivision')) return Promise.resolve(json({subdivisions: [{value: 'fbs', label: 'FBS'}, {value: 'fcs', label: 'FCS'}]}));
    const conference = url.searchParams.get('conference_id');
    if (conference === '8') return new Promise<Response>(resolve => { stale = resolve; });
    if (conference === '9') return Promise.resolve(json({conferences: [{value: '8', label: 'Old Conference'}, {value: '9', label: 'Independents'}],
                                                       teams: [{value: '2', label: 'Selected School'}], cached: true}));
    return Promise.resolve(json({conferences: [{value: '8', label: 'Old Conference'}, {value: '9', label: 'Independents'}], teams: [], cached: false}));
  });
  vi.stubGlobal('fetch', fetch);
  render(CFBDiscovery, {initialSeason: 2025, onchange: changes});
  await screen.findByRole('option', {name: 'Old Conference'});
  expect(fetch.mock.calls.some(([url]) => String(url).includes('/players'))).toBe(false);
  await fireEvent.change(screen.getByLabelText('Conference'), {target: {value: '8'}});
  await waitFor(() => expect(stale!).toBeTypeOf('function'));
  await fireEvent.change(screen.getByLabelText('Browse season'), {target: {value: '2024'}});
  await waitFor(() => expect((screen.getByLabelText('Conference') as HTMLSelectElement).disabled).toBe(false));
  await fireEvent.change(screen.getByLabelText('Conference'), {target: {value: '9'}});
  await screen.findByRole('option', {name: 'Selected School'});
  stale!(json({conferences: [], teams: [{value: '1', label: 'Stale School'}]}));
  await waitFor(() => expect(screen.queryByRole('option', {name: 'Stale School'})).toBeNull());
  await fireEvent.change(screen.getByLabelText('School'), {target: {value: '2'}});
  expect(changes.mock.calls.at(-1)?.[0]).toMatchObject({season: 2024, team: '2'});
  fetch.mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({detail: 'Directory unavailable'}), {status: 503})));
  await fireEvent.change(screen.getByLabelText('Browse season'), {target: {value: '2025'}});
  await screen.findByRole('alert');
  expect((screen.getByRole('button', {name: 'Retry'}) as HTMLButtonElement).disabled).toBe(false);
});
