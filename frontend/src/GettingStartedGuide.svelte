<script lang="ts">
  import Icon from './Icon.svelte';

  export let activeSport: string;
  /** First use shows the pitch and the guide; once dismissed the form starts straight away. */
  export let showGuidance: boolean;
  export let dismissGuidance: () => void;
  export let focusSection: (id: string) => Promise<void>;
</script>

{#if showGuidance}
  <div class="ask-copy">
    <h2>See what changed. Understand why.</h2>
    <p>Ask about the growth or decline of a team or player across time, then explore the numbers and plays behind the answer.</p>
  </div>
{:else}
  <h2 class="sr-only">Build your analysis</h2>
{/if}
{#if showGuidance}
  <section class="getting-started" id="getting-started" tabindex="-1" aria-label="How it works">
    <div class="section-heading">
      <div>
        <h3>Build an evidence-backed report</h3>
        <p>Start with a focused comparison. You can refine it or ask follow-up questions after the first answer.</p>
      </div>
      <button type="button" on:click={dismissGuidance}>Dismiss guide</button>
    </div>
    <ol class="guide-steps">
      <li>
        <span class="guide-icon"><Icon name={activeSport === 'cfb' ? 'clipboard-plus' : 'database'} size={22}/></span>
        <div><small>Step 1</small><b>{activeSport === 'cfb' ? 'Choose Your Subject' : 'Set Up and Sync Data'}</b>
          <p>{activeSport === 'cfb' ? 'Browse a season, subdivision, conference, and school, then choose a team or player. Selecting a conference filters schools; it does not download them.' : 'Sync the seasons you want to analyze. Required sources power the analysis; recommended sources add player names and context. Anything still missing prepares when you run.'}</p>
          <button type="button" class="guide-step-action" on:click={() => focusSection(activeSport === 'cfb' ? 'scope-heading' : 'data-setup')}>
            {activeSport === 'cfb' ? 'Choose a subject' : 'Open Data Setup'}
            <Icon name="arrow-right" size={15}/>
          </button>
        </div>
      </li>
      <li>
        <span class="guide-icon"><Icon name="clipboard-plus" size={22}/></span>
        <div><small>Step 2</small><b>{activeSport === 'cfb' ? 'Prepare Your Comparison' : 'Define a Focused Comparison'}</b>
          <p>{activeSport === 'cfb' ? 'Review data for your selected school, then choose two periods and the metrics to compare. Sync now, or missing data prepares when you run.' : 'Choose one team or player, two distinct periods, and the metrics that best match what you want to understand.'}</p>
          <button type="button" class="guide-step-action" on:click={() => focusSection(activeSport === 'cfb' ? 'data-setup' : 'scope-heading')}>
            {activeSport === 'cfb' ? 'Open Data Setup' : 'Choose a subject'}
            <Icon name="arrow-right" size={15}/>
          </button>
        </div>
      </li>
      <li>
        <span class="guide-icon"><Icon name="search" size={22}/></span>
        <div><small>Step 3</small><b>Ask, Run, and Inspect</b>
          <p>Ask what changed or why. Then open any finding to inspect its calculations, representative plays, and limitations.</p>
          <button type="button" class="guide-step-action" on:click={() => focusSection('investigation-question')}>
            Write your question
            <Icon name="arrow-right" size={15}/>
          </button>
        </div>
      </li>
    </ol>
    <div class="guide-outcome">
      <Icon name="sparkles" size={19}/>
      <p><strong>What a strong report includes</strong><span>A direct answer, the most important drivers, counterevidence, charts, and source-backed examples.</span>
      </p>
    </div>
  </section>
{/if}
