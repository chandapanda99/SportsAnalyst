import {afterEach, expect, it, vi} from 'vitest';
import {api, pendingJob, pollingStream} from './api';

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

it('submits polling jobs once and restores progress from a saved ID after refresh', async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({job_progress_transport: 'poll'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({job_id: 'sync-1'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({stage: 'complete', progress: 1, message: 'Ready'})));
  vi.stubGlobal('fetch', fetcher);
  await api.capabilities();
  const response = await api.syncStream('nba', [2025], ['play_by_play']);
  const reader = response.body.getReader();
  expect(new TextDecoder().decode((await reader.read()).value)).toContain('complete');
  expect(fetcher.mock.calls[1][0]).toBe('/api/datasets/nba/sync');
  expect(pendingJob()).toBeNull();
  sessionStorage.setItem('sports-analyst:pending-job:v1', JSON.stringify({id: 'analysis-1', kind: 'investigation'}));
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({stage: 'complete', progress: 1, message: 'Ready'})));
  const resumed = pollingStream(pendingJob()!);
  expect(resumed.investigationId).toBe('analysis-1');
  await resumed.body.getReader().read();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
});
