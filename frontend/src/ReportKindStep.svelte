<script lang="ts">
  /** The step number shown on the card, such as "1". */
  export let step: string;
  export let subjectType: 'team' | 'player';
  export let headToHead: boolean;
  export let headToHeadAvailable: boolean;
  /** Whether the sport analyzes players as well as teams. */
  export let playersAvailable: boolean;
  export let chooseHeadToHead: (on: boolean) => void;
  export let selectSubjectType: (type: 'team' | 'player') => void;
</script>

<section class="scope-card" aria-labelledby="kind-heading">
  <div class="scope-heading">
    <div><span class="eyebrow step-label"><b class="step-number">{step}</b>Report type</span>
      <h3 id="kind-heading" tabindex="-1">What kind of report?</h3></div>
  </div>
  {#if playersAvailable}
    <div class="scope-controls">
      <div class="subject-toggle" role="group" aria-label="Analysis subject">
        <span>Analyze</span>
        <button type="button" class:active={subjectType === 'team'} aria-pressed={subjectType === 'team'}
                on:click={() => selectSubjectType('team')}>Team</button>
        <button type="button" class:active={subjectType === 'player'} aria-pressed={subjectType === 'player'}
                on:click={() => selectSubjectType('player')}>Player</button>
      </div>
    </div>
  {/if}
  {#if headToHeadAvailable}
    <div class="question-kind" role="group" aria-label="Kind of question">
      <button type="button" aria-pressed={!headToHead} on:click={() => chooseHeadToHead(false)}>
        <strong>Change over time</strong><span>Follow one {subjectType} across seasons or parts of a season.</span>
      </button>
      <button type="button" aria-pressed={headToHead} on:click={() => chooseHeadToHead(true)}>
        <strong>Head-to-head</strong><span>Compare two {subjectType === 'player' ? 'players' : 'teams'} over the same seasons.</span>
      </button>
    </div>
  {/if}
</section>
