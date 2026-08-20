<script lang="ts">
  import { afterUpdate } from 'svelte';
  export let specification: Record<string, unknown>;
  let target: HTMLDivElement;
  let rendered = '';
  afterUpdate(async () => {
    const signature = JSON.stringify(specification);
    if (!target || signature === rendered) return;
    rendered = signature;
    const { default: embed } = await import('vega-embed');
    await embed(target, specification, { actions: false, theme: 'dark', renderer: 'svg' });
  });
</script>
<div class="chart" bind:this={target}></div>
