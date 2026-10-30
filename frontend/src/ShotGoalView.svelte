<script lang="ts">
  import ShotMarker from './ShotMarker.svelte';
  import type {ShotDiagram} from './soccerRecap';
  export let shot: ShotDiagram;
  $: position = shot.goal;
  $: left = Math.min(-.8, (position?.across ?? 0) - .7);
  $: right = Math.max(8.12, (position?.across ?? 7.32) + .7);
  $: top = Math.min(-.7, 2.44 - (position?.height ?? 2.44) - .7);
</script>
<section class="goal-view" aria-label="Shot goal-mouth view">
  <h5>{shot.outcome === 'goal' ? 'Where the goal crossed the line' : 'Projected goal-plane placement'}</h5>
  {#if position && shot.outcome !== 'blocked'}
    <svg viewBox={`${left} ${top} ${right-left} ${3.2-top}`} role="img" aria-label="Front view of the goal with recorded shot placement">
      <rect x="0" y="0" width="7.32" height="2.44" fill="#153f39"/>
      {#each Array(15) as _, i}<path d={`M${i*7.32/14} 0V2.44`} stroke="#608579" stroke-width=".012"/>{/each}
      {#each Array(6) as _, i}<path d={`M0 ${i*2.44/5}H7.32`} stroke="#608579" stroke-width=".012"/>{/each}
      <path d="M0 2.44V0H7.32V2.44" fill="none" stroke="white" stroke-width=".07"/>
      <path d={`M${left} 2.44H${right}`} stroke="#a2c2ac" stroke-width=".025"/>
      <ShotMarker x={position.across} y={2.44-position.height} size={.48} outcome={shot.outcome}/>
    </svg>
    <p>{shot.outcome === 'saved' ? 'Glove marks projected placement, not the goalkeeper’s actual save location.' : shot.outcome === 'goal' ? 'Recorded lateral position and height at the goal line.' : 'A wide or high placement remains outside the goal frame.'}</p>
  {:else}<p>{shot.outcome === 'blocked' ? 'Blocked before the goal line. No goal crossing is shown.' : 'Goal-mouth placement was not recorded for this shot.'}</p>{/if}
  <small>Goal: 7.32 m wide × 2.44 m high · FotMob</small>
</section>
<style>
  .goal-view {margin-top:14px;padding:14px;background:#0b211d;border:1px solid #31564c;border-radius:8px;}
  h5 {margin:0 0 10px;color:#e6f3fa;font-size:1rem;}svg {display:block;width:100%;max-height:240px;animation:goal-reveal .5s ease-out;}
  @keyframes goal-reveal {from {opacity:0;clip-path:inset(0 0 100% 0);}to {opacity:1;clip-path:inset(0);}}
  @media(prefers-reduced-motion:reduce) {svg {animation:none;}}
  p,small {color:#bcd2cd;font-size:.8rem;line-height:1.5;}p {margin:8px 0;}
</style>
