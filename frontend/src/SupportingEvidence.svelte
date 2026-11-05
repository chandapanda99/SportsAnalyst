<script lang="ts">
  import type {Evidence} from './types';
  import {metricFormatter} from './metricFormat';

  export let items: Evidence[] = [];
  export let loading = false;
  export let error = '';
  export let periods = {baseline: 'Starting point', comparison: 'Compared to'};
  // Set for head-to-head reports: names the side that leads on a metric, or '' when the metric has no better direction.
  export let leader: ((item: Evidence) => string) | null = null;
  export let retry: () => void = () => {
  };
  const number = (value: number | undefined) => value == null ? 'Not recorded' : new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(value);
</script>

<section class="supporting-evidence" aria-label="Supporting evidence" aria-live="polite" aria-busy={loading}>
  <h3>Supporting evidence</h3>
  {#if loading}<p>Loading the records behind this finding…</p>
  {:else if error}<p role="alert">{error}</p>
    <button type="button" on:click={retry}>Retry supporting evidence</button>
  {:else}
    {#each items as item}
      {@const format = metricFormatter(item)}
      <article class="evidence-record">
        <h4>{item.label || `Play ${item.play_id ?? ''}`}</h4>
        {#if item.description}<p>{item.description}</p>{/if}
        <dl>
          {#if item.baseline_value != null}
            <dt>{periods.baseline}</dt>
            <dd>{format.value(item.baseline_value)}</dd>
          {/if}
          {#if item.comparison_value != null}
            <dt>{periods.comparison}</dt>
            <dd>{format.value(item.comparison_value)}</dd>
          {/if}
          {#if item.baseline_value != null && item.comparison_value != null && leader}
            {@const ahead = leader(item)}
            <dt>{ahead ? 'Lead' : 'Difference'}</dt>
            <dd>{ahead ? `${ahead} by ${format.change(Math.abs(item.value ?? 0)).replace(/^\+/, '')}` : format.change(item.value)}</dd>
          {:else if item.baseline_value != null && item.comparison_value != null}
            <dt>Change</dt>
            <dd>{format.change(item.value)}</dd>
          {:else}
            <dt>Value</dt>
            <dd>{number(item.value ?? item.epa ?? item.metric_value)} {(item.unit ?? '').replaceAll('_', ' ')}</dd>
          {/if}
          {#if leader && item.context?.baseline_sample != null && item.context?.comparison_sample != null}
            <dt>Samples</dt>
            <dd>{number(Number(item.context.baseline_sample))} · {number(Number(item.context.comparison_sample))}</dd>
          {:else}
            <dt>Sample</dt>
            <dd>{item.sample_size != null ? number(item.sample_size) : item.play_id != null ? '1 play' : 'Not recorded'}</dd>
          {/if}
          {#if item.context?.players}
            <dt>Players</dt>
            <dd>{Array.isArray(item.context.players) ? item.context.players.join(', ') : item.context.players}</dd>
          {/if}
          {#if item.context?.status}
            <dt>Unit status</dt>
            <dd>{item.context.status}</dd>
          {/if}
          {#if item.context?.possessions != null}
            <dt>Possessions</dt>
            <dd>{item.context.possessions}</dd>
          {/if}
          {#if item.context?.minutes != null}
            <dt>Minutes</dt>
            <dd>{item.context.minutes}</dd>
          {/if}
          {#if item.context?.estimated_net_points != null}
            <dt>Estimated net points</dt>
            <dd>{number(Number(item.context.estimated_net_points))}</dd>
          {/if}
        </dl>
        {#each item.caveats ?? [] as caveat}<p class="caveat">{caveat}</p>{/each}
        <details>
          <summary>Source reference</summary>
          <code>{item.evidence_id}</code></details>
      </article>
    {:else}<p>No evidence records were returned for this finding. Try loading again, or check the report’s methodology and sources.</p>
      <button type="button" on:click={retry}>Reload evidence</button>
    {/each}
  {/if}
</section>
