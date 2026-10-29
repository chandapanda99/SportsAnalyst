<script lang="ts">
  import {onDestroy} from 'svelte';
  import {api} from './api';
  import type {DownloadSelection, DownloadCatalog, TeamOption} from './types';
  export let sport: string;
  export let season: number;
  export let competition: string | undefined = undefined;
  export let teams: TeamOption[] = [];
  export let disabled = false;
  export let onchange: (selection: DownloadSelection) => void;
  let kind: DownloadSelection['kind'] = 'league';
  let identity = '';
  let catalog: DownloadCatalog | null = null;
  let loading = false;
  let error = '';
  let loadedKey = '';
  let version = 0;
  $: key = `${sport}:${competition ?? ''}:${season}`;
  $: choices = kind === 'team' ? catalog?.teams ?? teams : kind === 'conference' ? catalog?.conferences ?? [] : catalog?.divisions ?? [];
  $: if (kind !== 'league' && key !== loadedKey) void load(key);
  $: notify(kind, identity, choices, loading, error);

  function notify(mode: typeof kind, value: string, options: TeamOption[], pending: boolean, problem: string) {
    const ready = mode === 'league' || Boolean(value && options.some(item => item.value === value) && !pending
      && (!problem || mode === 'team'));
    onchange({kind: mode, ready, label: mode === 'league' ? (sport === 'soccer' ? 'Entire Competition' : 'Entire League')
      : options.find(item => item.value === value)?.label ?? 'Choose a download scope',
      ...(mode === 'team' && value ? {team_ids: [value]} : {}),
      ...(mode === 'conference' && value ? {conference_id: value} : {}),
      ...(mode === 'division' && value ? {division_id: value} : {})});
  }

  async function load(nextKey: string) {
    loadedKey = nextKey;
    const current = ++version;
    loading = true; error = ''; catalog = null; identity = '';
    try {
      const result = await api.downloadCatalog(sport, season, competition);
      if (current === version) catalog = result;
    } catch (problem) {
      if (current === version) error = String(problem);
    } finally {if (current === version) loading = false;}
  }
  onDestroy(() => {version += 1;});
</script>

<section class="download-scope" aria-label="Download Scope" aria-busy={loading}>
  <div class="scope-intro"><strong>Download Scope</strong><p>Choose the teams to prepare. Their games against opponents outside the selected group are included.</p></div>
  <div class="scope-fields">
    <label>Download By<select bind:value={kind} disabled={disabled} on:change={() => {identity = '';}}>
      <option value="league">{sport === 'soccer' ? 'Entire Competition' : 'Entire League'}</option>
      <option value="team">Team</option>
      <option value="conference">{sport === 'soccer' ? 'Conference / Group' : 'Conference'}</option>
      {#if sport !== 'soccer'}<option value="division">Division</option>{/if}
    </select></label>
    {#if kind !== 'league'}
      <label>{kind === 'team' ? 'Download Team' : kind === 'division' ? 'Download Division' : sport === 'soccer' ? 'Download Conference / Group' : 'Download Conference'}
        <select bind:value={identity} disabled={disabled || loading || !choices.length}>
          <option value="">Choose {kind === 'team' ? 'a team' : kind === 'division' ? 'a division' : 'a conference or group'}</option>
          {#each choices as option}<option value={option.value}>{option.label}</option>{/each}
        </select>
      </label>
    {/if}
  </div>
  {#if loading}<p role="status">Checking groups and teams for the selected season…</p>{/if}
  {#if error}<div class="scope-error" role="status"><span>{error}{kind === 'team' && teams.length ? ' You can still select a listed team.' : ''}</span>
    <button type="button" disabled={disabled || loading} on:click={() => void load(key)}>Retry Groups</button></div>{/if}
  {#if !loading && !error && catalog && kind !== 'league' && kind !== 'team' && !choices.length}
    <p role="status">No {kind === 'division' ? 'divisions' : 'conferences or groups'} are recorded for this competition and season. Choose Team or Entire Competition.</p>
  {/if}
  <small>{sport === 'soccer' ? 'Only selected teams’ match details are fetched. Groups follow the recorded standings for each selected season.'
    : 'The source publishes full-season files, which are fetched and cached once. Your library keeps separate team snapshots. League ranks require a full-league snapshot.'}</small>
  {#if kind === 'conference' || kind === 'division'}<small>Membership is resolved separately for every selected season, including historical realignments.</small>{/if}
</section>

<style>
  .download-scope {display:grid; gap:.85rem; margin:1rem 0; padding:1rem; border:1px solid var(--line); border-radius:.6rem; background:var(--color-surface-low); min-width:0;}
  .scope-intro strong {font-size:1rem;}
  p {margin:.35rem 0 0; color:var(--color-text-secondary); font-size:.9rem; line-height:1.5;}
  .scope-fields {display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr)); gap:1rem;}
  label {display:grid; gap:.5rem; font-size:.85rem; font-weight:600;}
  select {width:100%; min-width:0; min-height:44px; padding:.65rem; border:1px solid var(--line); border-radius:.4rem; color:var(--color-text-primary); background:var(--color-surface-control); font:inherit;}
  small {color:var(--color-text-secondary); font-size:.8rem; line-height:1.5;}
  .scope-error {display:flex; flex-wrap:wrap; align-items:center; gap:.75rem; font-size:.85rem;}
  .scope-error button {min-height:44px; padding:.5rem .8rem; color:var(--color-text-primary); background:var(--color-surface-control); border:1px solid var(--line); border-radius:.4rem;}
</style>
