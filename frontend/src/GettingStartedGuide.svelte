<script lang="ts">
  import Icon from './Icon.svelte';

  /** Shown on first use and from How it works; once hidden, the form starts straight away. */
  export let showGuidance: boolean;
  export let dismissGuidance: () => void;

  // The same five steps, with the same numbers, as the cards below.
  const steps = [
    {title: 'Report type', detail: 'Pick a team or a player, and change over time or head-to-head.'},
    {title: 'Subject', detail: 'Choose who the report is about.'},
    {title: 'Time frame', detail: 'Choose the seasons or parts of a season to compare.'},
    {title: 'Focus', detail: 'Keep the recommended metrics, or choose your own.'},
    {title: 'Question', detail: 'Ask what changed or why, then run the analysis.'}
  ];
</script>

{#if showGuidance}
  <div class="ask-copy">
    <h2>See what changed. Understand why.</h2>
    <p>Ask about the growth or decline of a team or player across time, then explore the numbers and plays behind the answer.</p>
  </div>
  <section class="getting-started" id="getting-started" tabindex="-1" aria-label="How it works">
    <div class="section-heading">
      <div>
        <h3>How a report is built</h3>
        <p>Work down the five steps below. Any data the analysis is missing downloads when you run it.</p>
      </div>
      <button type="button" on:click={dismissGuidance}>Hide guide</button>
    </div>
    <ol class="guide-steps">
      {#each steps as step, index}
        <li>
          <div><small>Step {index + 1}</small><b>{step.title}</b>
            <p>{step.detail}</p></div>
        </li>
      {/each}
    </ol>
    <div class="guide-outcome">
      <Icon name="sparkles" size={19}/>
      <p><strong>What a strong report includes</strong><span>A direct answer, the most important drivers, counterevidence, charts, and source-backed examples.</span>
      </p>
    </div>
  </section>
{:else}
  <h2 class="sr-only">Build your analysis</h2>
{/if}
