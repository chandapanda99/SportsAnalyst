<script lang="ts">
  import {surface} from '@sportsdataverse/sporty';
  import {toSVG} from '@sportsdataverse/sporty/svg';
  import {soccerPitch} from './surfaceGeometry';
  // Generated from trusted package geometry, with no user-provided SVG/markup.
  const svg = toSVG(surface('soccer', 'fifa', {updates: soccerPitch,
    colorUpdates: {plot_background: '#102a20'}}), {width: 640, arcs: 'svg'});
</script>
<details class="pitch-reference"><summary>Pitch Reference</summary>
  <p>Illustrative 105 × 68 m pitch, not measured venue dimensions. The match timeline does not record player locations; no events are placed on this reference.</p>
  <div aria-label="Illustrative soccer pitch dimensions" role="img">{@html svg}</div>
</details>
<style>
  .pitch-reference {margin:1rem 0; border:1px solid var(--line); border-radius:.6rem; padding:1rem;}
  summary {cursor:pointer; font-weight:600;} p {color:var(--color-text-secondary); font-size:.85rem; line-height:1.5;}
  div {max-width:45rem; margin:auto;} div :global(svg) {display:block; width:100%; height:auto;}
</style>
