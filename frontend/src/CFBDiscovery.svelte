<script lang="ts">
  import {onMount, onDestroy} from 'svelte';
  import {api} from './api';
  import type {TeamOption} from './types';
  export let initialSeason: number;
  export let disabled = false;
  export let onchange: (selection: {season: number; seasons: number[]; teams: TeamOption[]; team: string; subdivision: string; conference: string; conferenceLabel: string; loading: boolean; error: string}) => void;
  let seasons: number[] = [];
  let season = initialSeason;
  let subdivision = 'fbs';
  let subdivisions: TeamOption[] = [];
  let conferences: TeamOption[] = [];
  let conference = '';
  let teams: TeamOption[] = [];
  let team = '';
  let loading = true;
  let error = '';
  let cached = false;
  let version = 0;
  function notify() { onchange({season, seasons, teams, team, subdivision, conference,
    conferenceLabel: conferences.find(option => option.value === conference)?.label ?? '', loading, error}); }
  async function load(reset: boolean) {
    const current = ++version;
    if (reset) { teams = []; team = ''; }
    loading = true; error = ''; notify();
    try {
      if (!seasons.length) {
        const catalog = await api.cfbCatalog();
        if (current !== version) return;
        seasons = catalog.seasons ?? [];
        if (!seasons.includes(season)) season = seasons[0];
        if (!season) throw new Error('No verified college-football seasons are available.');
      }
      const root = await api.cfbCatalog(season);
      if (current !== version) return;
      subdivisions = root.subdivisions ?? [];
      const catalog = await api.cfbCatalog(season, subdivision, conference || undefined);
      if (current !== version) return;
      conferences = catalog.conferences; teams = catalog.teams; cached = catalog.cached;
    } catch (problem) {
      if (current === version) error = String(problem);
    } finally {
      if (current === version) { loading = false; notify(); }
    }
  }
  onMount(() => { void load(true); });
  onDestroy(() => { version += 1; });
</script>

<div class="cfb-discovery" aria-busy={loading}>
  <label>Browse season<select bind:value={season} disabled={disabled || !seasons.length}
    on:change={() => { conference = ''; void load(true); }}>
    {#each seasons as year}<option value={year}>{year}</option>{/each}
  </select></label>
  <label>Subdivision<select bind:value={subdivision} disabled={disabled || !subdivisions.length}
    on:change={() => { conference = ''; void load(true); }}>
    {#each subdivisions as option}<option value={option.value}>{option.label}</option>{/each}
  </select></label>
  <label>Conference<select bind:value={conference} disabled={disabled || loading || !conferences.length} on:change={() => void load(true)}>
    <option value="">Choose a conference or independents</option>
    {#each conferences as option}<option value={option.value}>{option.label}</option>{/each}
  </select></label>
  <label>School<select bind:value={team} disabled={disabled || loading || !teams.length} on:change={notify}>
    <option value="">Choose a school</option>
    {#each teams as option}<option value={option.value}>{option.label}</option>{/each}
  </select></label>
  {#if loading}<p role="status">Loading the selected college-football directory…</p>
  {:else if error}<p role="alert">{error} <button type="button" on:click={() => void load(false)}>Retry</button></p>
  {:else}<p>{cached ? 'Using cached directory. ' : ''}Conference membership reflects {season}; analysis includes nonconference games. Only your selected subject’s missing game data will be prepared.</p>{/if}
</div>

<style>
  .cfb-discovery {display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 16px 0;}
  label {display: flex; flex-direction: column; gap: 6px; color: var(--text-muted, #94afbf); font-size: 12px;}
  select {padding: 10px; background: var(--surface-raised, #102336); color: var(--text-primary, #e6f3fa); border: 1px solid #315063; border-radius: 6px;}
  p {grid-column: 1 / -1; margin: 0; font-size: 12px; color: #94afbf;}
  button {margin-left: 8px;}
  @media (max-width: 640px) {.cfb-discovery {grid-template-columns: 1fr;}}
</style>
