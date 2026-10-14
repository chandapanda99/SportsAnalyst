<script lang="ts">
  import {onMount, onDestroy} from 'svelte';
  import {api} from './api';
  import type {Evidence} from './types';
  import PlayTablet from './PlayTablet.svelte';
  import {NFL_TEAM_NAMES} from './teamPalettes';
  export let play: Evidence;
  export let investigationId: string;
  export let onclose: () => void;
  let mounted = false;
  let version = 0;
  let loadedKey = '';
  let loading = false;
  let error = '';
  let detail: Awaited<ReturnType<typeof api.nflPlays>> | null = null;
  let selectedId = '';
  let filter = '';
  onMount(() => { mounted = true; });
  onDestroy(() => { version += 1; });
  async function load() {
    const current = ++version;
    const evidence = play;
    loading = true; error = '';
    try {
      const response = await api.nflPlays(investigationId, evidence.evidence_id);
      if (current !== version) return;
      detail = response;
      selectedId = String(evidence.play_id);
    } catch (problem) { if (current === version) error = String(problem); }
    finally { if (current === version) loading = false; }
  }
  $: key = `${investigationId}:${play.evidence_id}`;
  $: if (mounted && key !== loadedKey) {
    loadedKey = key; detail = null; filter = ''; selectedId = String(play.play_id); void load();
  }
  $: allPlays = detail?.plays ?? [play];
  $: visible = allPlays.filter(item => `${item.description} ${item.play_id} ${item.visualization?.possession_team ?? ''} ${item.visualization?.play_type ?? ''} ${item.visualization?.passer ?? ''} ${item.visualization?.receiver ?? ''} ${item.visualization?.rusher ?? ''}`.toLowerCase().includes(filter.toLowerCase()));
  $: if (visible.length && !visible.some(item => String(item.play_id) === selectedId)) selectedId = String(visible[0].play_id);
  $: selected = allPlays.find(item => String(item.play_id) === selectedId) ?? play;
  $: index = visible.findIndex(item => String(item.play_id) === selectedId);
  $: home = play.visualization?.home_team_abbreviation ?? play.game_id?.split('_')[3];
  $: away = play.visualization?.away_team_abbreviation ?? play.game_id?.split('_')[2];
  $: matchup = home && away ? `${NFL_TEAM_NAMES[away] ?? away} at ${NFL_TEAM_NAMES[home] ?? home}` : `Game ${play.game_id}`;
  $: metrics = [
    {label: 'Down', value: selected.visualization?.down},
    {label: 'Yards to go', value: selected.visualization?.yards_to_go},
    {label: 'Yards gained', value: selected.visualization?.yards_gained},
    {label: 'EPA', value: selected.epa},
    {label: 'WPA', value: selected.visualization?.win_probability_added}
  ];
  function metricValue(value: number | null | undefined) {
    return value == null || !Number.isFinite(value) ? 'Not recorded' : Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
</script>

<section class="nfl-game-browser" aria-label="NFL game play browser">
  <header><div><small>NFL · RECORDED GAME CONTEXT</small><h3>{matchup}</h3>
    <p>{play.season ?? ''}{play.visualization?.week != null ? ` · Week ${play.visualization.week}` : ''}
      {play.window ? ` · ${play.window}` : ''} · Game {play.game_id}</p></div>
    <button class="close-browser" type="button" on:click={onclose} aria-label="Close NFL game browser">×</button></header>
  <p class="context-note">Browse both teams’ recorded plays, including plays outside the analysis filters. The saved report and its evidence stay unchanged.</p>
  {#if visible.length}
    <div class="selection-heading"><strong>{selected.play_id === play.play_id ? 'Cited analysis play' : 'Game browsing context · not selected as report evidence'}</strong>
      <button class="return-cited" type="button" on:click={() => { filter = ''; selectedId = String(play.play_id); }}>Return to cited play</button></div>
    <dl aria-label="Selected NFL play metrics">{#each metrics as metric}<div><dt>{metric.label}</dt><dd>{metricValue(metric.value)}</dd></div>{/each}</dl>
  {/if}
  {#if loading}<p role="status"><span class="button-spinner" aria-hidden="true"></span> Loading recorded NFL game plays…</p>{/if}
  {#if error}<p role="alert">{error} <button type="button" on:click={() => void load()}>Retry game plays</button></p>{/if}
  {#if detail}<p>{detail.coverage}. {detail.message ?? ''}
    {#if detail.retryable}<button type="button" on:click={() => void load()}>Retry game plays</button>{/if}</p>{/if}
  <div class="play-controls">
    <label>Search game plays<input bind:value={filter} placeholder="Player, team, play type or description"/></label>
    <label>Select game play<select bind:value={selectedId} disabled={loading || !visible.length}>
      {#each visible as item}<option value={String(item.play_id)}>Q{item.visualization?.quarter ?? '?'} {item.visualization?.clock ?? ''} · #{item.play_id} · {(item.description ?? 'Recorded play').slice(0, 110)}</option>{/each}
    </select></label>
    <button type="button" disabled={loading || index <= 0} on:click={() => selectedId = String(visible[index - 1].play_id)}>Previous play</button>
    <button type="button" disabled={loading || index < 0 || index >= visible.length - 1} on:click={() => selectedId = String(visible[index + 1].play_id)}>Next play</button>
  </div>
  {#if !visible.length}<p>No recorded game plays match this search.</p>
    <button class="return-cited" type="button" on:click={() => { filter = ''; selectedId = String(play.play_id); }}>Return to cited play</button>
  {:else}
    <PlayTablet play={selected} {onclose}/>
  {/if}
</section>

<style>
  .nfl-game-browser { padding: 20px; border: 1px solid #315063; background: #071724; margin-top: 12px; min-width: 0; }
  header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
  header > div { min-width: 0; }
  h3 { margin: 8px 0; font-size: 18px; line-height: 1.4; }
  p, small, dt { color: #94afbf; }
  p { font-size: 13px; line-height: 1.6; }
  header p { margin: 8px 0 0; }
  small { font-size: 11px; letter-spacing: .08em; }
  .context-note { margin: 20px 0; }
  .selection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; font-size: 13px; }
  dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin: 12px 0 20px; }
  dl > div { padding: 12px; background: #102336; min-width: 0; }
  dt { font-size: 12px; }
  dd { margin: 6px 0 0; font-size: 15px; color: #e6f3fa; font-variant-numeric: tabular-nums; }
  .play-controls { display: grid; grid-template-columns: minmax(160px, .8fr) minmax(240px, 2.4fr) auto auto; gap: 12px; align-items: end; margin: 18px 0; }
  label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; min-width: 0; color: #e6f3fa; }
  select, input { box-sizing: border-box; width: 100%; min-width: 0; height: 40px; padding: 9px; background: #102336; color: #e6f3fa; border: 1px solid #315063; border-radius: 4px; font: inherit; }
  button { min-height: 36px; padding: 8px 12px; border: 1px solid #315063; border-radius: 4px; background: #102336; color: #e6f3fa; font: inherit; font-size: 12px; cursor: pointer; }
  .play-controls > button { height: 40px; white-space: nowrap; }
  button:hover:not(:disabled) { border-color: var(--mint, #7ce1c4); background: #173346; }
  button:disabled { opacity: .4; cursor: default; }
  input:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid var(--mint, #7ce1c4); outline-offset: 2px; }
  .close-browser { width: 36px; height: 36px; flex: 0 0 36px; padding: 0; font-size: 20px; }
  .return-cited { color: var(--mint, #7ce1c4); }
  @media (max-width: 850px) { .play-controls { grid-template-columns: 1fr 1fr; } .play-controls label { grid-column: 1 / -1; } }
  @media (max-width: 480px) { .nfl-game-browser { padding: 12px; } .play-controls { gap: 10px; } .play-controls label:first-child { grid-column: 1 / -1; } dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
