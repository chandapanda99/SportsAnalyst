<script lang="ts">
  /** The step number shown on the card, such as "5". */
  export let step: string;
  export let question: string;
  /** The example most recently copied into the question, so a domain change can swap it for a matching one. */
  export let lastSuggestedQuestion: string;
  export let questionExamples: string[];
  export let showAllQuestionExamples: boolean;
</script>

<div class="question-field">
  <div class="scope-heading">
    <div><span class="eyebrow step-label"><b class="step-number">{step}</b>Question</span>
      <h3 id="question-heading"><label for="investigation-question">What do you want to know?</label></h3></div>
  </div>
  <p class="section-help">Ask what changed or why. Naming a situation, such as third downs, focuses the report.</p>
  <textarea id="investigation-question" bind:value={question} rows="3" placeholder="Type your question, or start from an example below"></textarea>
  <span class="question-examples-label" id="question-examples-label">Examples</span>
  <div class="question-examples" role="group" aria-labelledby="question-examples-label">
    {#each questionExamples.slice(0, showAllQuestionExamples ? questionExamples.length : 3) as example}
      <button type="button" on:click={() => { question = example; lastSuggestedQuestion = example; }}>{example}</button>
    {/each}
    {#if questionExamples.length > 3}
      <button class="question-more" type="button" aria-expanded={showAllQuestionExamples}
              on:click={() => showAllQuestionExamples = !showAllQuestionExamples}>
        {showAllQuestionExamples ? 'Show fewer examples' : `Show ${questionExamples.length - 3} more examples`}
      </button>
    {/if}
  </div>
</div>
