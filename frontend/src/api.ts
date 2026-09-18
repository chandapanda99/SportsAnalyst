import type { AnalysisOptions, Capabilities, DatasetManifest, Evidence, Investigation, InvestigationRequest, InvestigationSummary, PlayerOption, SportOption } from './types';

let progressTransport: 'stream' | 'poll' = 'stream';
const pendingKey = 'sports-analyst:pending-job:v1';
type PendingJob = { id: string; kind: 'sync' | 'investigation' };

export function pendingJob(): PendingJob | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
    return value && typeof value.id === 'string' && ['sync', 'investigation'].includes(value.kind) ? value : null;
  } catch { return null; }
}

export function pollingStream(job: PendingJob, timeoutSeconds?: number): EventStreamResponse {
  try { sessionStorage.setItem(pendingKey, JSON.stringify(job)); } catch { /* Optional storage. */ }
  const encoder = new TextEncoder();
  let stopped = false;
  return {
    investigationId: job.kind === 'investigation' ? job.id : undefined,
    jobId: job.kind === 'sync' ? job.id : undefined,
    timeoutSeconds,
    body: new ReadableStream<Uint8Array>({
      async start(controller) {
        let delay = 1000;
        const deadline = Date.now() + 6 * 60 * 60_000;
        while (!stopped && Date.now() < deadline) {
          try {
            const path = job.kind === 'sync' ? 'dataset-jobs' : 'investigations';
            const status = await json<{stage: string; message: string; progress: number}>(`/api/${path}/${encodeURIComponent(job.id)}/status`);
            if (stopped) return;
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(status)}\n\n`));
            if (['complete', 'failed'].includes(status.stage)) {
              try { sessionStorage.removeItem(pendingKey); } catch { /* Optional storage. */ }
              controller.close();
              return;
            }
          } catch { /* A transient outage does not resubmit work. */ }
          await new Promise(resolve => setTimeout(resolve, delay));
          delay = Math.min(5000, delay * 1.5);
        }
        if (!stopped) controller.error(new Error('Progress polling timed out; refresh to resume this job.'));
      },
      cancel() { stopped = true; }
    })
  };
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json() as Promise<T>;
}

async function empty(url: string, init?: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
}

export interface EventStreamResponse {
  body: ReadableStream<Uint8Array>;
  investigationId?: string;
  jobId?: string;
  timeoutSeconds?: number;
}

async function eventStream(url: string, init: RequestInit, label: string): Promise<EventStreamResponse> {
  if (progressTransport === 'poll') {
    const endpoint = url.replace(/\/sync-stream$/, '/sync').replace(/\/stream$/, '');
    const queued = await json<{job_id?: string; investigation_id?: string; timeout_seconds?: number}>(endpoint, init);
    const id = queued.job_id || queued.investigation_id;
    if (!id) throw new Error('The server did not return a job identifier.');
    return pollingStream({id, kind: queued.job_id ? 'sync' : 'investigation'}, queued.timeout_seconds);
  }
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  if (!response.body) throw new Error(`${label} progress streaming is not supported by this browser.`);
  return {
    body: response.body,
    investigationId: response.headers.get('x-investigation-id') || undefined,
    jobId: response.headers.get('x-job-id') || undefined,
    timeoutSeconds: Number(response.headers.get('x-job-timeout-seconds')) || undefined
  };
}

export const api = {
  ready: async () => {
    try {
      return (await fetch('/api/health')).ok;
    } catch {
      return false;
    }
  },
  capabilities: async () => {
    const result = await json<Capabilities>('/api/capabilities');
    progressTransport = result.job_progress_transport ?? 'stream';
    return result;
  },
  sports: () => json<SportOption[]>('/api/sports'),
  analysisOptions: (sport = 'nfl') => json<AnalysisOptions>(`/api/sports/${sport}/options`),
  players: (sport: string, query = '') => json<PlayerOption[]>(`/api/sports/${sport}/players?query=${encodeURIComponent(query)}`),
  datasets: (sport?: string) => json<DatasetManifest[]>(sport ? `/api/datasets?sport=${sport}` : '/api/datasets'),
  investigations: (limit?: number, offset = 0, sport?: string) => {
    const params = new URLSearchParams();
    if (limit != null) { params.set('limit', String(limit)); params.set('offset', String(offset)); }
    if (sport) params.set('sport', sport);
    const query = params.toString();
    return json<InvestigationSummary[]>(`/api/investigations${query ? `?${query}` : ''}`);
  },
  investigation: (id: string) => json<Investigation>(`/api/investigations/${id}`),
  investigationStatus: (id: string) => json<{ stage: string; message: string; progress: number }>(
    `/api/investigations/${id}/status`
  ),
  datasetJobStatus: (id: string) => json<{ stage: string; message: string; progress: number }>(
    `/api/dataset-jobs/${id}/status`
  ),
  investigationThread: (id: string) => json<Investigation[]>(`/api/investigations/${id}/thread`),
  deleteInvestigation: (id: string) => empty(`/api/investigations/${id}`, { method: 'DELETE' }),
  evidence: (id: string, evidence: string) => json(`/api/investigations/${id}/evidence/${evidence}`),
  evidenceBatch: (id: string, evidenceIds: string[]) => json<Evidence[]>(`/api/investigations/${id}/evidence/batch`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ evidence_ids: evidenceIds })
  }),
  sync: (sport: string, seasons: number[], datasets: string[]) => json<{ job_id: string; timeout_seconds: number }>(`/api/datasets/${sport}/sync`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ seasons, datasets })
  }),
  syncStream: (sport: string, seasons: number[], datasets: string[]) =>
    eventStream(`/api/datasets/${sport}/sync-stream`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ seasons, datasets })
    }, 'Dataset'),
  investigate: (request: InvestigationRequest) =>
    json<{ investigation_id: string }>('/api/investigations', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request)
    }),
  investigateStream: (request: InvestigationRequest) =>
    eventStream('/api/investigations/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request)
    }, 'Investigation'),
  followUp: (id: string, question: string) => json<{ investigation_id: string }>(`/api/investigations/${id}/follow-ups`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question })
  }),
  followUpStream: (id: string, question: string) => eventStream(`/api/investigations/${id}/follow-ups/stream`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question })
  }, 'Follow-up')
};
