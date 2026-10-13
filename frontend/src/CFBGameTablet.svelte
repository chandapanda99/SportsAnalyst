<script lang="ts">
  import {onMount, onDestroy} from 'svelte';
  import type {Evidence} from './types';
  import {api} from './api';
  import CFBPlayTablet from './CFBPlayTablet.svelte';
  export let play: Evidence;
  export let investigationId: string;
  export let onclose: () => void;
  let loading = false;
  let detailError = '';
  let detail: Awaited<ReturnType<typeof api.cfbPlays>> | null = null;
  let mounted = false;
  let loadedEvidenceId = '';
  let requestVersion = 0;
  let selectedId = '';
  let filter = '';
  onMount(() => {mounted = true;});
  onDestroy(() => {requestVersion += 1;});
  async function loadPlays() {
    const evidenceId = play.evidence_id;
    const version = ++requestVersion;
    loading = true; detailError = '';
    try {
      const response = await api.cfbPlays(investigationId, evidenceId);
      if (play.evidence_id === evidenceId && version === requestVersion) {
        detail = response;
        selectedId = (response.plays.find(event => event.down != null && event.down > 0 && !/kickoff|punt|field goal|extra point/i.test(event.play_type ?? '')) ?? response.plays[0])?.id ?? '';
      }
    } catch (problem) { if (play.evidence_id === evidenceId && version === requestVersion) detailError = String(problem); }
    finally { if (play.evidence_id === evidenceId && version === requestVersion) loading = false; }
  }
  $: if (mounted && play.evidence_id !== loadedEvidenceId) {
    loadedEvidenceId = play.evidence_id; detail = null; detailError = ''; selectedId = ''; filter = ''; void loadPlays();
  }
  $: context = play.visualization;
  $: rows = context?.cfb_statistics?.rows ?? [];
  $: events = context?.cfb_scoring_events ?? [];
  $: visiblePlays = detail?.plays.filter(event => `${event.text} ${event.play_type} ${event.id}`.toLowerCase().includes(filter.toLowerCase())) ?? [];
  $: if (visiblePlays.length && !visiblePlays.some(event => event.id === selectedId)) selectedId = visiblePlays[0].id;
  $: selected = detail?.plays.find(event => event.id === selectedId);
  $: selectedIndex = visiblePlays.findIndex(event => event.id === selectedId);
  $: leaderboard = context?.cfb_statistics?.covered_team_epa ?? [];
</script>
<section class="cfb-game" aria-label="College-football game evidence">
  <header><div><small>COLLEGE FOOTBALL · RECORDED GAME CONTEXT</small><h3>{play.description}</h3>
    <p>{context?.game_date?.slice(0, 10)} · {play.window} · Game {play.game_id}</p></div>
    <button type="button" aria-label="Close game evidence" on:click={onclose}>×</button></header>
  <p>These are recorded box-score statistics and scoring events, not tracking data or an inferred formation.</p>
  {#each rows as row}
    <p>Recorded school: {context?.cfb_statistics?.schools?.[String(row.team_id)] ?? `ESPN team ${row.team_id ?? 'not recorded'}`}</p>
    <dl>{#each Object.entries(row).filter(([key]) => !['game_id', 'season', 'team_id', 'athlete_id'].includes(key)) as [key, value]}
      <div><dt>{key.replaceAll('_', ' ')}</dt><dd>{value ?? 'Not recorded'}</dd></div>
    {/each}</dl>
  {/each}
  <h4>Recorded scoring events</h4>
  {#if events.length}<ol>{#each events as event}<li>Q{event.quarter ?? '?'} {event.clock ?? ''} · {event.text}</li>{/each}</ol>
  {:else}<p>No scoring-event section was recorded in this snapshot.</p>{/if}
  {#if loading}<p role="status">Loading recorded plays and participants…</p>{/if}
  {#if detailError}<p role="alert">{detailError} <button type="button" on:click={() => void loadPlays()}>Retry play detail</button></p>{/if}
  {#if detail}
    <p>{detail.coverage}. {detail.message ?? ''}</p>
    <div class="play-controls">
      <label>Search recorded plays<input bind:value={filter} placeholder="Player, play type or description"/></label>
      <label>Select recorded play<select bind:value={selectedId}>
        {#each visiblePlays as event}<option value={event.id}>Q{event.quarter ?? '?'} {event.clock ?? ''} · {(event.text ?? event.play_type ?? event.id).slice(0, 110)}</option>{/each}
      </select></label>
      <button type="button" disabled={selectedIndex <= 0} on:click={() => selectedId = visiblePlays[selectedIndex - 1].id}>Previous play</button>
      <button type="button" disabled={selectedIndex < 0 || selectedIndex >= visiblePlays.length - 1} on:click={() => selectedId = visiblePlays[selectedIndex + 1].id}>Next play</button>
    </div>
    {#if !visiblePlays.length}<p>No recorded plays match this filter.</p>{/if}
    {#if selected && visiblePlays.some(event => event.id === selected.id)}<CFBPlayTablet event={selected} teams={detail.teams ?? []}/>{/if}
  {/if}
  {#if leaderboard.length}
    <h4>Offensive EPA/play · prepared game sample</h4>
    <p>Only covered scrimmage plays in this comparison window. Not a national or conference ranking; sample sizes and opposition differ.</p>
    <table><thead><tr><th>School</th><th>Modeled EPA/play</th><th>Qualifying plays</th><th>Covered games</th></tr></thead>
      <tbody>{#each leaderboard as entry}<tr><td>{entry.team_name ?? detail?.teams?.find(team => team.id === entry.team_id)?.name ?? context?.cfb_statistics?.schools?.[entry.team_id] ?? `ESPN team ${entry.team_id}`}</td>
        <td>{entry.epa_per_play.toFixed(3)}</td><td>{entry.plays}</td><td>{entry.games}</td></tr>{/each}</tbody></table>
  {:else}<p>EPA comparison context appears when advanced play metrics have been prepared. Opening recorded play detail does not run the modeling pipeline.</p>{/if}
</section>
<style>
  .cfb-game {padding: 20px; border: 1px solid #315063; background: #071724; margin-top: 12px;}
  header {display: flex; justify-content: space-between; gap: 20px;} h3 {margin: 8px 0;} p, small, dt {color: #94afbf;}
  dl {display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px;} dl div {padding: 10px; background: #102336;}
  dd {margin: 6px 0 0;} li {margin: 8px 0;}
  .play-controls {display: flex; flex-wrap: wrap; gap: 12px; align-items: end;}
  label {display: flex; flex-direction: column; gap: 6px; font-size: 12px; min-width: 180px; max-width: 100%;}
  select, input {padding: 9px; background: #102336; color: #e6f3fa; border: 1px solid #315063; max-width: 100%;}
  table {width: 100%; border-collapse: collapse; font-size: 13px;} th, td {padding: 9px; text-align: left; border-bottom: 1px solid #315063;}
</style>
