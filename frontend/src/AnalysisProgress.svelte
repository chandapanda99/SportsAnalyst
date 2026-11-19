<script lang="ts">
  import BasketballLoadingAnimation from './BasketballLoadingAnimation.svelte';
  import SoccerLoadingAnimation from './SoccerLoadingAnimation.svelte';

  export let activeSport: string;
  /** True while data downloads; otherwise an analysis is running. */
  export let syncing: boolean;
  export let stage: string;
  export let progress: number;
  export let runningInvestigationId: string;
  export let cancelling: boolean;
  export let cancelRun: () => Promise<void>;
  export let progressHeading: HTMLElement | null = null;
  /** The question being answered; empty while data downloads. */
  export let question = '';
</script>

<section class="working" aria-busy="true">
  {#if question}
    <div class="working-question">
      <span class="eyebrow">Report in progress</span>
      <p class="report-question"><span>Your question</span>{question}</p>
    </div>
  {/if}
  <div class="field-lines" aria-hidden="true"></div>
  <div class="working-layout">
    <div class="working-copy">
      <span class="eyebrow">{syncing ? 'Downloading data' : 'Analysis in progress'}</span>
      <div class="progress-message" class:long-message={stage.length > 44} class:dense-message={stage.length > 88}
           class:extra-dense-message={stage.length > 140} role="status" aria-live="polite" aria-atomic="true">
        <small>Current update</small>
        <h2 bind:this={progressHeading} tabindex="-1">{stage}</h2>
      </div>
      <div class="progress" role="progressbar" aria-label={syncing ? 'Download progress' : 'Analysis progress'} aria-valuemin="0" aria-valuemax="100"
           aria-valuenow={Math.round(progress * 100)}><i style={`width:${Math.max(4, progress * 100)}%`}></i></div>
      <p>{syncing ? 'Each source is downloaded and checked before it is added to your library.' : progress < 0.1 ? 'Preparing the analysis service and checking your data. The comparison has not started yet.' : 'Comparing your periods and checking the evidence behind each finding.'}</p>
      <p class="working-note">You can keep using the app. {syncing ? 'Your Data library updates' : 'This report opens here'} when it’s ready.</p>
      {#if !syncing}
        <button class="cancel-run" type="button" disabled={!runningInvestigationId || cancelling} on:click={cancelRun}>
          {cancelling ? 'Cancelling…' : 'Cancel analysis'}
        </button>
      {/if}
    </div>
    <div class="play-visual" class:nba-loading={activeSport === 'nba'} class:soccer-loading={activeSport === 'soccer'} aria-hidden="true">
      <div class="play-caption">
        <span>{activeSport === 'nba' ? 'Live possession' : activeSport === 'soccer' ? 'Live buildup' : 'Live drive'}</span><b>{Math.round(progress * 100)}
        %</b></div>
      {#if activeSport === 'nba'}
        <BasketballLoadingAnimation/>
      {:else if activeSport === 'soccer'}
        <SoccerLoadingAnimation/>
      {:else}
        <img class="catch-scene" src="/open-sports-analyst-loader.svg" alt=""/>
      {/if}
      <div class="analysis-live"><i></i><span>{syncing ? 'Download still running…' : 'Analysis still running…'}</span></div>
    </div>
  </div>
</section>
