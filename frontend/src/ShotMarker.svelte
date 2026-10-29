<script lang="ts">
  export let x = 0;
  export let y = 0;
  export let size = 5;
  export let outcome = 'goal';
</script>
<g transform={`translate(${x-size/2},${y-size/2}) scale(${size/24})`} role="img"
  aria-label={outcome === 'saved' ? 'Saved shot: glove' : outcome === 'blocked' ? 'Blocked shot: ball with red X' : outcome === 'goal' ? 'Goal: ball' : 'Missed shot: ball'}>
  {#if outcome === 'saved'}
    <path d="M8 22 5 16 2 12Q1 9 4 10L7 13 5 4Q5 1 7 3L10 10 9 2Q10-1 12 2L13 10 14 3Q16 1 16 4L16 11 18 6Q21 5 20 8L19 18 16 22Z"
      fill="#ffd188" stroke="#07202c" stroke-width="1"/>
    <path d="M8 18 16 18M11 12 15 14" fill="none" stroke="#8e5116" stroke-width="1.3"/>
  {:else}
    <circle cx="12" cy="12" r="9" fill="white" stroke="#07202c" stroke-width="1.2"/>
    <path d="m12 7 5 4-2 6H9l-2-6zM12 7V3m5 8 4-2m-6 8 2 3M9 17l-2 3m0-9L3 9" fill="#17383c" stroke="#17383c" stroke-width="1"/>
    {#if outcome === 'blocked'}<path d="m3 3 18 18M21 3 3 21" stroke="#ff5265" stroke-width="3.5" stroke-linecap="round"/>{/if}
  {/if}
</g>
