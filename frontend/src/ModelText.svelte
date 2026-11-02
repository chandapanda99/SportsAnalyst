<script lang="ts">
  import {modelTextSegments} from './reportText';

  export let text: string;
</script>

<span class="model-text">{#each modelTextSegments(text) as segment}{#if segment.strong}<strong>{segment.text}</strong>{:else if segment.emphasis}<em>{segment.text}</em>{:else}{segment.text}{/if}{/each}</span>

<style>
  .model-text {white-space:pre-line;}
</style>
