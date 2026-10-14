<script lang="ts">
  export let label: string;
  export let x: number;
  export let y: number;
  export let width: number | null = null;
  export let event = false;
  $: bubbleWidth = width ?? Math.min(44, Math.max(10, label.length * .62 + 1.6));
  $: safeX = Math.max(bubbleWidth / 2 + .8, Math.min(120 - bubbleWidth / 2 - .8, x));
</script>

<g class:player-tooltip={!event} class:event-tooltip={event} class="tooltip visible"
   transform={`translate(${safeX} ${y})`} aria-hidden="true" pointer-events="none">
  <rect x={-bubbleWidth / 2} y={y < 7 ? 2.25 : -5.45} width={bubbleWidth} height="3.2" rx=".55"/>
  <text class="name-label" y={y < 7 ? 4.42 : -3.28}
        textLength={Math.min(bubbleWidth - 1.6, label.length * .56)} lengthAdjust="spacingAndGlyphs">{label}</text>
</g>
