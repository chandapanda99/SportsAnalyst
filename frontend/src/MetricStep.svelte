<script lang="ts">
  import Icon from './Icon.svelte';
  import type {AnalysisOptions, MetricExplanation, MetricOption, PlayerOption} from './types';

  /** The step number shown on the card, such as "4". */
  export let step: string;
  export let activeSport: string;
  export let analysisOptions: AnalysisOptions | null;
  export let subjectType: 'team' | 'player';
  export let analysisDomain: string;
  export let visibleDomains: AnalysisOptions['analysis_domains'];
  export let domainMetrics: MetricOption[];
  export let availableMetrics: MetricOption[];
  export let availableMetricIds: Set<string>;
  export let recommendedMetricIds: string[];
  export let selectedMetrics: string[];
  export let selectedAvailableMetricCount: number;
  export let allAvailableMetricsSelected: boolean;
  export let customizeMetrics: boolean;
  export let metricsEdited: boolean;
  export let selectedSplits: string[];
  export let requiredSeasons: number[];
  export let metricInfo: MetricExplanation | null;
  export let metricInfoLoading: boolean;
  export let metricInfoError: string;
  export let metricInfoElement: HTMLElement | null;
  export let selectAnalysisDomain: (domain: string, force?: boolean, player?: PlayerOption | null) => void;
  export let toggleMetric: (metric: string) => void;
  export let selectAllMetrics: () => void;
  export let useRecommendedMetrics: () => void;
  export let explainMetric: (metric: MetricOption) => Promise<void>;
  export let closeMetricInfo: () => void;
  export let splitAvailable: (availableSeasons: number[], seasons?: number[]) => boolean;
  export let toggleSplit: (split: string) => void;
</script>

<section class="metric-card" aria-labelledby="metric-heading">
  <div class="scope-heading">
    <div><span class="eyebrow step-label"><b class="step-number">{step}</b>Focus</span>
      <h3 id="metric-heading" tabindex="-1">Choose {subjectType === 'player' ? 'player metrics' : 'what to measure'}</h3></div>
    <div class="metric-actions">
      <button type="button" aria-expanded={customizeMetrics} on:click={() => customizeMetrics = !customizeMetrics}>Customize metrics</button>
      {#if customizeMetrics}
        <button class="text-button" type="button" on:click={selectAllMetrics} disabled={allAvailableMetricsSelected || !availableMetrics.length}>
          <Icon name="clipboard-plus" size={16}/>
          {allAvailableMetricsSelected ? 'All available selected' : 'Select all metrics'}
        </button>
        <button class="text-button" type="button" on:click={useRecommendedMetrics}>
          <Icon name="sparkles" size={16}/>
          Use recommended metrics
        </button>
      {/if}
    </div>
  </div>
  <div class="domain-selector" role="group" aria-label="Analysis domain">
    {#each visibleDomains as domain}
      <button type="button" class:active={analysisDomain === domain.value} aria-pressed={analysisDomain === domain.value}
              on:click={() => selectAnalysisDomain(domain.value)}>
        <strong>{domain.label}</strong><span>{domain.description}</span>
      </button>
    {/each}
  </div>
  <p class="section-help">
    {subjectType === 'player' ? 'Only metrics that apply to players are shown.' : 'Recommended metrics are already selected.'}
    Use About to see how each one is calculated.</p>
  <div class="metric-groups">
    {#each [...new Set(domainMetrics.filter(metric => customizeMetrics || recommendedMetricIds.includes(metric.value) || selectedMetrics.includes(metric.value)).map(metric => metric.category))] as category}
      <section class="metric-group" role="group" aria-label={category}>
        <h4 class="metric-group-title">{category}</h4>
        {#each domainMetrics.filter((metric) => metric.category === category && (customizeMetrics || recommendedMetricIds.includes(metric.value) || selectedMetrics.includes(metric.value))) as metric}
          <label class:unavailable={!availableMetricIds.has(metric.value)} title={metric.description}>
            <input type="checkbox" checked={selectedMetrics.includes(metric.value)} disabled={!availableMetricIds.has(metric.value)}
                   on:change={() => toggleMetric(metric.value)}/>
            <span><strong>{metric.label}</strong><small>{metric.description}</small>
              {#if !availableMetricIds.has(metric.value)}<small>Unavailable for one or more selected periods. Check data sources or choose another metric.</small>{/if}</span>
          </label>
          <button class="metric-explain" type="button" aria-label={`About ${metric.label}`} on:click={() => explainMetric(metric)}>
            <Icon name="info-circle" size={14}/>About</button>
        {/each}
      </section>
    {/each}
  </div>
  {#if metricInfoLoading || metricInfo || metricInfoError}
    <section class="metric-info" bind:this={metricInfoElement} tabindex="-1" aria-label="Metric explanation" aria-live="polite">
      <button type="button" on:click={closeMetricInfo}>Close
        explanation
      </button>
      {#if metricInfoLoading}<p>Loading metric explanation…</p>{:else if metricInfoError}<p role="alert">{metricInfoError}</p>{:else if metricInfo}
        <h4>{metricInfo.label}</h4>
        <p>{metricInfo.interpretation}</p>
        <dl>
          <dt>Included sample</dt>
          <dd>{metricInfo.qualifying_plays}</dd>
          <dt>Direction</dt>
          <dd>{metricInfo.higher_is_better == null ? 'Depends on context' : metricInfo.higher_is_better ? 'Higher is generally better' : 'Lower is generally better'}</dd>
          <dt>Formula</dt>
          <dd><code>{metricInfo.formula}</code></dd>
        </dl>
        {#each metricInfo.limitations ?? [] as limitation}<p>{limitation}</p>{/each}
      {/if}
    </section>
  {/if}
  {#if customizeMetrics}
    <button class="text-button clear-metrics" type="button" on:click={() => { metricsEdited = true; selectedMetrics = []; }}>
      <Icon name="wand" size={16}/>
      Clear all metrics
    </button>
  {/if}
  {#if analysisOptions && selectedAvailableMetricCount === 0}
    <p class="selection-warning">Choose at least one available metric to run your analysis.</p>
  {/if}
  <details class="breakdown-details">
    <summary>Optional breakdowns</summary>
    {#if activeSport === 'nfl' && subjectType === 'player'}
      <div class="split-selector player-diagnostic-note">
        <div><h4>Player context</h4>
          <p>Player comparisons use attributed plays plus compatible synced player statistics. Team-oriented diagnostic cuts are disabled for
            player analyses.</p></div>
      </div>
    {:else}
      <div class="split-selector">
        <div><h4>Explore situations</h4>
          <p>Leave these empty for automatic recommendations. Select specific situations to include only those breakdowns.</p></div>
        <div class="split-options">
          {#each analysisOptions?.split_dimensions ?? [] as split}
            <label class:unavailable={!splitAvailable(split.available_seasons, requiredSeasons)} title={split.description}>
              <input type="checkbox" checked={selectedSplits.includes(split.value)} disabled={!splitAvailable(split.available_seasons, requiredSeasons)}
                     on:change={() => toggleSplit(split.value)}/>
              <span>{split.label}</span>
            </label>
          {/each}
        </div>
      </div>
    {/if}
  </details>
</section>
