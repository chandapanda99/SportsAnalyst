<script lang="ts">
  import Icon from './Icon.svelte';
  import PlayerPortrait from './PlayerPortrait.svelte';
  import type {AnalysisOptions, MetricOption, PlayerOption} from './types';

  type ReadinessItem = {ready: boolean; label: string; target: string};

  export let activeSport: string;
  export let analysisOptions: AnalysisOptions | null;
  export let subjectType: 'team' | 'player';
  export let selectedPlayer: PlayerOption | null;
  export let resolvedTeam: string;
  export let teamInput: string;
  export let headToHead: boolean;
  export let compareSubjectLabel: string;
  export let periodBrief: string;
  export let analysisDomain: string;
  export let availableMetrics: MetricOption[];
  export let selectedMetrics: string[];
  export let selectedSplits: string[];
  export let readiness: ReadinessItem[];
  export let firstBlocker: ReadinessItem | undefined;
  export let canRun: boolean;
  export let displayDomain: (domain?: string) => string;
  export let focusSection: (id: string) => Promise<void>;
  export let runAnalysis: () => Promise<void>;
</script>

<aside class="analysis-brief" aria-label="Analysis brief">
  <div class="brief-details">
    <h3>Analysis brief</h3>
    <dl>
      <dt>Subject</dt>
      <dd>
        {#if subjectType === 'player' && selectedPlayer}
          <PlayerPortrait id={selectedPlayer.player_id} sport={activeSport} name={selectedPlayer.name}/>
        {/if}{subjectType === 'player' ? selectedPlayer?.name ?? 'Choose a player' : resolvedTeam ? teamInput : 'Choose a team'}{headToHead && compareSubjectLabel ? ` vs ${compareSubjectLabel}` : ''}</dd>
      <dt>{headToHead ? 'Seasons' : 'Time frame'}</dt>
      <dd>{periodBrief}</dd>
      <dt>Focus</dt>
      <dd>{displayDomain(analysisDomain)}</dd>
      <dt>Metrics</dt>
      <dd>{availableMetrics.filter(metric => selectedMetrics.includes(metric.value)).map(metric => metric.label).join(', ') || 'Choose metrics'}</dd>
      <dt>Breakdowns</dt>
      <dd>{selectedSplits.length ? selectedSplits.map(value => analysisOptions?.split_dimensions.find(item => item.value === value)?.label ?? value).join(', ') : 'Recommended automatically'}</dd>
    </dl>
    <h4>Ready to run?</h4>
    <ul class="readiness">
      {#each readiness as item}
        <li>
          <button type="button" class:ready={item.ready} on:click={() => focusSection(item.target)}><span
              aria-label={item.ready ? 'Complete' : 'Needed'}>{item.ready ? '✓' : '○'}</span>{item.label}</button>
        </li>
      {/each}
    </ul>
  </div>
  <div class="brief-run">
    <p class="readiness-message"
       aria-live="polite">{firstBlocker ? firstBlocker.label : 'Everything is ready. Your analysis will include supporting evidence.'}</p>
    <button class="primary" disabled={!canRun} on:click={runAnalysis}>Run analysis
      <Icon name="player-play" size={19}/>
    </button>
  </div>
</aside>
