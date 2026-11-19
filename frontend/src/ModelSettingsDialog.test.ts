import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ModelSettingsDialog from './ModelSettingsDialog.svelte';

const current = {
  provider: 'azure_foundry', provider_label: 'Azure AI Foundry', configured: true,
  model: 'analysis', chat_model: '', reasoning_effort: 'medium', chat_reasoning_effort: '',
  foundry_endpoint: 'https://old.openai.azure.com/openai/v1/', foundry_api_key_set: true, foundry_authentication: 'api_key',
  ollama_base_url: 'http://127.0.0.1:11434', ollama_model: 'qwen3:8b',
  status: {state: 'idle', message: null, model_id: null},
  providers: [{id: 'azure_foundry', label: 'Azure AI Foundry'}, {id: 'ollama', label: 'Ollama'}],
  reasoning_efforts: ['minimal', 'low', 'medium', 'high', 'xhigh'],
  editable: true, read_only_reason: null, persistence: 'session', persistence_detail: 'Applies until the app restarts.'
};

function reply(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}}));
}

describe('Model connection dialog', () => {
  let saved: Array<Record<string, unknown>>;
  let nextResult: (body: Record<string, unknown>) => unknown;

  beforeEach(() => {
    saved = [];
    nextResult = () => ({ok: true, error: null, settings: current});
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/model-settings') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        saved.push(body);
        return reply(nextResult(body));
      }
      return reply(current);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows the current settings without ever showing the key', async () => {
    render(ModelSettingsDialog, {open: true});
    const endpoint = await screen.findByLabelText(/Endpoint/) as HTMLInputElement;
    expect(endpoint.value).toBe(current.foundry_endpoint);
    const key = screen.getByPlaceholderText(/Saved key/) as HTMLInputElement;
    expect(key.type).toBe('password');
    expect(key.value).toBe('');
    expect(key.placeholder).toContain('leave blank to keep it');
  });

  it('keeps the stored key unless a new one is entered and reports success', async () => {
    const applied = vi.fn();
    render(ModelSettingsDialog, {props: {open: true}, events: {applied}} as never);
    const model = await screen.findByLabelText(/Analysis deployment/) as HTMLInputElement;
    await fireEvent.input(model, {target: {value: 'analysis-2'}});
    await fireEvent.click(screen.getByRole('button', {name: 'Test & save'}));
    await screen.findByText(/Connected to Azure AI Foundry/);
    expect(saved[0]).toMatchObject({provider: 'azure_foundry', model: 'analysis-2'});
    expect(saved[0]).not.toHaveProperty('foundry_api_key');
    expect(applied).toHaveBeenCalledOnce();
  });

  it('switches to Ollama fields and shows a failed check as an alert', async () => {
    nextResult = () => ({ok: false, error: 'Could not reach the service.', field: null, settings: current});
    const failed = vi.fn();
    render(ModelSettingsDialog, {props: {open: true}, events: {failed}} as never);
    const provider = await screen.findByLabelText('Provider') as HTMLSelectElement;
    await fireEvent.change(provider, {target: {value: 'ollama'}});
    expect(screen.queryByLabelText(/Endpoint/)).toBeNull();
    const ollamaModel = screen.getByPlaceholderText('qwen3:8b') as HTMLInputElement;
    await fireEvent.input(ollamaModel, {target: {value: 'llama3.1'}});
    await fireEvent.click(screen.getByRole('button', {name: 'Test & save'}));
    expect((await screen.findByRole('alert')).textContent).toContain('Could not reach the service.');
    expect(saved[0]).toEqual({provider: 'ollama', ollama_base_url: 'http://127.0.0.1:11434', ollama_model: 'llama3.1'});
    expect(failed).toHaveBeenCalledWith(expect.objectContaining({detail: 'Could not reach the service.'}));
  });

  it('is read-only when the deployment manages the model', async () => {
    vi.mocked(fetch).mockImplementation(() => reply({...current, editable: false, read_only_reason: 'Managed by the operator.'}));
    render(ModelSettingsDialog, {open: true});
    expect(await screen.findByText('Managed by the operator.')).toBeTruthy();
    await waitFor(() => expect((screen.getByRole('button', {name: 'Test & save'}) as HTMLButtonElement).disabled).toBe(true));
  });
});
