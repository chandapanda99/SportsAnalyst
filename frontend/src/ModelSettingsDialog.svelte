<script lang="ts">
  import { createEventDispatcher, tick } from 'svelte';
  import { api } from './api';
  import type { ModelProviderId, ModelSettings, ModelSettingsUpdate } from './types';

  export let open = false;

  const dispatch = createEventDispatcher<{
    checking: boolean;
    applied: ModelSettings;
    failed: string;
    close: void;
  }>();

  let dialog: HTMLDialogElement;
  let settings: ModelSettings | null = null;
  let loadError = '';
  let error = '';
  let errorField: string | null = null;
  let notice = '';
  let saving = false;
  let wasOpen = false;

  let provider: ModelProviderId = 'azure_foundry';
  let endpoint = '';
  let model = '';
  let chatModel = '';
  let reasoningEffort = '';
  let chatReasoningEffort = '';
  let authentication: 'api_key' | 'azure_identity' = 'api_key';
  let apiKey = '';
  let ollamaBaseUrl = '';
  let ollamaModel = '';

  $: if (open !== wasOpen) {
    wasOpen = open;
    if (open) void show(); else hide();
  }
  $: editable = settings?.editable ?? false;
  $: providerLabel = settings?.providers.find(item => item.id === provider)?.label ?? provider;

  function fill(next: ModelSettings) {
    settings = next;
    provider = next.provider === 'ollama' ? 'ollama' : 'azure_foundry';
    endpoint = next.foundry_endpoint;
    model = next.model;
    chatModel = next.chat_model;
    reasoningEffort = next.reasoning_effort;
    chatReasoningEffort = next.chat_reasoning_effort;
    authentication = next.foundry_authentication;
    apiKey = '';
    ollamaBaseUrl = next.ollama_base_url;
    ollamaModel = next.ollama_model;
  }

  async function show() {
    error = loadError = notice = '';
    errorField = null;
    await tick();
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
    }
    try {
      fill(await api.modelSettings());
    } catch (reason) {
      loadError = reason instanceof Error ? reason.message : String(reason);
    }
  }

  function hide() {
    if (dialog?.open) {
      if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open');
    }
  }

  function close() {
    if (saving) return;
    open = false;
    dispatch('close');
  }

  function update(): ModelSettingsUpdate {
    if (provider === 'ollama') return {provider, ollama_base_url: ollamaBaseUrl, ollama_model: ollamaModel};
    return {
      provider, foundry_endpoint: endpoint, model, chat_model: chatModel,
      reasoning_effort: reasoningEffort, chat_reasoning_effort: chatReasoningEffort,
      ...(authentication === 'api_key' && apiKey.trim() ? {foundry_api_key: apiKey.trim()} : {}),
      ...(authentication === 'azure_identity' && settings?.foundry_api_key_set ? {clear_api_key: true} : {})
    };
  }

  async function save() {
    if (saving || !editable) return;
    error = notice = '';
    errorField = null;
    saving = true;
    dispatch('checking', true);
    try {
      const result = await api.saveModelSettings(update());
      if (result.ok) {
        fill(result.settings);
        notice = result.warning || `Connected to ${result.settings.provider_label}. New reports will use these settings.`;
        dispatch('applied', result.settings);
      } else {
        error = result.error || 'The connection check failed.';
        errorField = result.field ?? null;
        dispatch('failed', error);
        await tick();
        dialog?.querySelector<HTMLElement>(errorField ? `[data-field="${errorField}"]` : '.model-settings-error')?.focus();
      }
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
      dispatch('failed', error);
    } finally {
      saving = false;
      dispatch('checking', false);
    }
  }
</script>

<dialog bind:this={dialog} class="model-settings" aria-labelledby="model-settings-title" aria-describedby="model-settings-summary"
        on:cancel|preventDefault={close}
        on:click={(event) => { if (event.target === dialog) close(); }}>
  <form method="dialog" on:submit|preventDefault={save} aria-busy={saving}>
    <header>
      <div>
        <span class="eyebrow">AI model</span>
        <h2 id="model-settings-title">Model connection</h2>
      </div>
      <button class="text-button" type="button" on:click={close} disabled={saving}>Close</button>
    </header>
    <p id="model-settings-summary" class="model-settings-help">
      Choose the AI provider that plans and writes your reports. Saving checks the connection with one short request first;
      if it fails, the current connection stays in use. Reports already running finish with the model they started with.
    </p>

    {#if loadError}
      <div class="error model-settings-error" role="alert" tabindex="-1">Couldn't load the model settings. {loadError}</div>
    {:else if !settings}
      <p class="model-settings-help" role="status">Loading the current settings…</p>
    {:else}
      {#if !editable}
        <p class="model-settings-note" role="note">{settings.read_only_reason}</p>
      {/if}
      <fieldset disabled={!editable || saving}>
        <label>Provider
          <select bind:value={provider} data-field="provider">
            {#each settings.providers as option}<option value={option.id}>{option.label}</option>{/each}
          </select>
        </label>

        {#if provider === 'azure_foundry'}
          <label>Endpoint
            <input type="url" bind:value={endpoint} data-field="foundry_endpoint" required autocomplete="off" spellcheck="false"
                   placeholder="https://your-resource.openai.azure.com/openai/v1/"
                   aria-invalid={errorField === 'foundry_endpoint'} aria-describedby="endpoint-hint"/>
            <small id="endpoint-hint">The resource's OpenAI v1 address, ending in /openai/v1/.</small>
          </label>
          <div class="model-settings-pair">
            <label>Analysis deployment
              <input bind:value={model} data-field="model" required autocomplete="off" spellcheck="false"
                     aria-invalid={errorField === 'model'}/>
            </label>
            <label>Reasoning effort
              <select bind:value={reasoningEffort} data-field="reasoning_effort" aria-invalid={errorField === 'reasoning_effort'}>
                <option value="">Model default</option>
                {#each settings.reasoning_efforts as effort}<option value={effort}>{effort}</option>{/each}
              </select>
            </label>
          </div>
          <div class="model-settings-pair">
            <label>Wording deployment <span class="optional">optional</span>
              <input bind:value={chatModel} data-field="chat_model" autocomplete="off" spellcheck="false"
                     placeholder="Same as analysis" aria-invalid={errorField === 'chat_model'} aria-describedby="chat-hint"/>
              <small id="chat-hint">Used for summaries and follow-up wording only.</small>
            </label>
            <label>Wording reasoning
              <select bind:value={chatReasoningEffort} data-field="chat_reasoning_effort" disabled={!chatModel.trim()}
                      aria-invalid={errorField === 'chat_reasoning_effort'}>
                <option value="">Model default</option>
                {#each settings.reasoning_efforts as effort}<option value={effort}>{effort}</option>{/each}
              </select>
            </label>
          </div>
          <fieldset class="model-settings-auth">
            <legend>Sign-in</legend>
            <label class="choice"><input type="radio" bind:group={authentication} value="api_key"/> API key</label>
            <label class="choice"><input type="radio" bind:group={authentication} value="azure_identity"/> Microsoft Entra (Azure CLI sign-in)</label>
          </fieldset>
          {#if authentication === 'api_key'}
            <label>API key
              <input type="password" bind:value={apiKey} data-field="foundry_api_key" autocomplete="new-password" spellcheck="false"
                     placeholder={settings.foundry_api_key_set ? 'Saved key — leave blank to keep it' : 'Paste the resource key'}
                     aria-invalid={errorField === 'foundry_api_key'} aria-describedby="key-hint"/>
              <small id="key-hint">{settings.foundry_api_key_set ? 'A key is saved. It is never shown; enter a new one to replace it.' : 'No key is saved.'}</small>
            </label>
          {/if}
        {:else}
          <label>Ollama address
            <input type="url" bind:value={ollamaBaseUrl} data-field="ollama_base_url" autocomplete="off" spellcheck="false"
                   placeholder="http://127.0.0.1:11434" aria-invalid={errorField === 'ollama_base_url'}/>
          </label>
          <label>Model
            <input bind:value={ollamaModel} data-field="ollama_model" required autocomplete="off" spellcheck="false"
                   placeholder="qwen3:8b" aria-invalid={errorField === 'ollama_model'} aria-describedby="ollama-hint"/>
            <small id="ollama-hint">The model must already be pulled and support tool calling.</small>
          </label>
        {/if}
      </fieldset>

      <div aria-live="polite">
        {#if error}<div class="error model-settings-error" role="alert" tabindex="-1">{error}</div>{/if}
        {#if notice && !error}<p class="model-settings-success" role="status">{notice}</p>{/if}
      </div>
      <p class="model-settings-help">{settings.persistence_detail}</p>
      <button class="primary" type="submit" disabled={!editable || saving}>
        {#if saving}<span class="button-spinner" aria-hidden="true"></span>Testing {providerLabel}…{:else}Test & save{/if}
      </button>
    {/if}
  </form>
</dialog>

<style>
  .model-settings {
    width: min(560px, calc(100vw - 32px));
    max-height: calc(100vh - 48px);
    padding: 0;
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    background: var(--color-surface-panel);
    color: var(--color-text-primary);
    overflow: auto;
  }

  .model-settings::backdrop {
    background: color-mix(in srgb, var(--color-canvas) 70%, transparent);
  }

  form {
    display: grid;
    gap: 16px;
    padding: 24px;
  }

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  h2 {
    margin: 6px 0 0;
    font-size: var(--text-lg, 20px);
  }

  fieldset {
    display: grid;
    gap: 14px;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  label, legend {
    display: block;
    font: 12px var(--font-mono);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: .08em;
  }

  input:not([type="radio"]), select {
    display: block;
    width: 100%;
    margin-top: 8px;
    background: var(--color-surface-input);
    border: 1px solid var(--color-border-control);
    color: var(--color-text-primary);
    border-radius: var(--radius-md);
    min-height: 46px;
    padding: 13px 14px;
    font: var(--text-md) var(--font-sans);
    letter-spacing: normal;
    text-transform: none;
  }

  input[aria-invalid="true"], select[aria-invalid="true"] {
    border-color: var(--color-status-danger-border);
  }

  input:disabled, select:disabled {
    opacity: .6;
  }

  small, .optional {
    display: block;
    margin-top: 6px;
    font: var(--text-sm) var(--font-sans);
    color: var(--muted);
    letter-spacing: normal;
    text-transform: none;
  }

  .optional {
    display: inline;
    margin: 0 0 0 4px;
  }

  .model-settings-pair {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
    gap: 14px;
  }

  .model-settings-auth {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 20px;
  }

  .model-settings-auth legend {
    margin-bottom: 8px;
  }

  .choice {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font: var(--text-sm) var(--font-sans);
    color: var(--color-text-primary);
    text-transform: none;
    letter-spacing: normal;
    cursor: pointer;
  }

  .model-settings-help, .model-settings-note {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--muted);
    line-height: 1.5;
  }

  .model-settings-note {
    padding: 12px 14px;
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
  }

  .model-settings-error {
    margin: 0;
  }

  .model-settings-success {
    margin: 0;
    color: var(--mint);
    font-size: var(--text-sm);
  }

  .primary {
    margin-top: 0;
  }

  .primary:disabled {
    opacity: .5;
    cursor: not-allowed;
  }

  @media (max-width: 520px) {
    .model-settings-pair {
      grid-template-columns: 1fr;
    }
  }
</style>
