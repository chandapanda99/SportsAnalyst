import type { AnalysisOptions, Capabilities, DatasetManifest, Evidence, Investigation, InvestigationRequest, InvestigationSummary, PlayerOption, SportOption } from './types';

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json() as Promise<T>;
}

async function empty(url: string, init?: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
}

export const api = {
  ready: async () => {
    try {
      return (await fetch('/api/health')).ok;
    } catch {
      return false;
    }
  },
  capabilities: () => json<Capabilities>('/api/capabilities'),
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
  investigationThread: (id: string) => json<Investigation[]>(`/api/investigations/${id}/thread`),
  deleteInvestigation: (id: string) => empty(`/api/investigations/${id}`, { method: 'DELETE' }),
  evidence: (id: string, evidence: string) => json(`/api/investigations/${id}/evidence/${evidence}`),
  evidenceBatch: (id: string, evidenceIds: string[]) => json<Evidence[]>(`/api/investigations/${id}/evidence/batch`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ evidence_ids: evidenceIds })
  }),
  sync: (sport: string, seasons: number[], datasets: string[]) => json<{ job_id: string; timeout_seconds: number }>(`/api/datasets/${sport}/sync`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ seasons, datasets })
  }),
  investigate: (request: InvestigationRequest) =>
    json<{ investigation_id: string }>('/api/investigations', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request)
    }),
  followUp: (id: string, question: string) => json<{ investigation_id: string }>(`/api/investigations/${id}/follow-ups`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question })
  })
};
