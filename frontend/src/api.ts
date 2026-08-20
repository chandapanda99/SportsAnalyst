import type { AnalysisOptions, Capabilities, DatasetManifest, Investigation, InvestigationRequest } from './types';

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json() as Promise<T>;
}

export const api = {
  capabilities: () => json<Capabilities>('/api/capabilities'),
  analysisOptions: () => json<AnalysisOptions>('/api/sports/nfl/options'),
  datasets: () => json<DatasetManifest[]>('/api/datasets'),
  investigations: () => json<Investigation[]>('/api/investigations'),
  investigation: (id: string) => json<Investigation>(`/api/investigations/${id}`),
  evidence: (id: string, evidence: string) => json(`/api/investigations/${id}/evidence/${evidence}`),
  sync: (seasons: number[], datasets: string[]) => json<{ job_id: string }>('/api/datasets/nfl/sync', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ seasons, datasets })
  }),
  investigate: (request: InvestigationRequest) =>
    json<{ investigation_id: string }>('/api/investigations', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request)
    }),
  followUp: (id: string, question: string) => json<Investigation>(`/api/investigations/${id}/follow-ups`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question })
  })
};
