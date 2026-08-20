import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.svelte';

describe('Open Sports Analyst workbench', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith('/capabilities')
        ? { providers: ['azure_foundry', 'ollama'], configured_provider: 'azure_foundry', model_configured: false, custom_analysis: false, sports: ['nfl'] }
        : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the scoped investigation entry point without model credentials', async () => {
    render(App);
    expect(await screen.findByText('Ask a better football question.')).toBeTruthy();
    expect(screen.getByText('Deterministic mode')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Run investigation/ })).toBeTruthy();
  });
});
