<script lang="ts">
  import {onMount, onDestroy, tick} from 'svelte';
  import type {Evidence} from './types';
  import TabletLoading from './TabletLoading.svelte';
  import {loadTablet, paintTabletPlaceholder} from './tabletLoader';
  export let play: Evidence;
  export let investigationId: string;
  export let onclose: () => void;
  let component: Awaited<ReturnType<typeof loadTablet>> | null = null;
  let loading = true;
  let error = '';
  let mounted = false;
  let version = 0;
  let loadedKey = '';
  $: sport = play.visualization?.sport ?? 'nfl';
  $: key = `${investigationId}:${sport}:${play.evidence_id}`;
  async function renderTablet() {
    const current = ++version;
    const selectedSport = sport;
    loading = true; error = ''; component = null;
    try {
      await tick();
      await paintTabletPlaceholder();
      if (current !== version) return;
      const next = await loadTablet(selectedSport);
      if (current !== version) return;
      component = next;
      loading = false;
    } catch (problem) {
      if (current !== version) return;
      error = problem instanceof Error ? problem.message : String(problem);
      loading = false;
    }
  }
  onMount(() => {mounted = true;});
  onDestroy(() => {version += 1;});
  $: if (mounted && key !== loadedKey) {loadedKey = key; void renderTablet();}
</script>

<div class="tablet-panel">
  {#if loading}
    <TabletLoading {sport}/>
    <button type="button" class="close-loading" on:click={onclose}>Close tablet</button>
  {:else if error}
    <div class="tablet-error" role="alert"><strong>Unable to render the tablet.</strong><p>{error}</p>
      <button type="button" on:click={() => void renderTablet()}>Retry tablet</button>
      <button type="button" on:click={onclose}>Close tablet</button>
    </div>
  {:else if component}
    {#if component.kind === 'nfl' || component.kind === 'cfb'}
      <svelte:component this={component.component} {play} {investigationId} {onclose}/>
    {:else}
      <svelte:component this={component.component} {play} {onclose}/>
    {/if}
  {/if}
</div>

<style>
  .tablet-panel {position:relative;min-width:0;}.close-loading {display:block;margin:8px 0 0 auto;}
  .tablet-error {padding:24px;border:1px solid #b27171;border-radius:10px;background:#291b27;margin-top:12px;color:#f8e4e4;}
  button {padding:8px 12px;border:1px solid #315063;border-radius:6px;background:#102638;color:#e6f3fa;cursor:pointer;}.tablet-error button+button {margin-left:8px;}
</style>
