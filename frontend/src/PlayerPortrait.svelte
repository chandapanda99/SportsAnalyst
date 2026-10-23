<script lang="ts">
  import {playerPortrait} from './sportsBranding';
  export let id: string;
  export let sport: string;
  export let name: string;
  export let historical = false;
  let url: string | null = null;
  let request = 0;
  let failed = '';
  $: initials = name.trim().split(/\s+/).map(part => part[0]).slice(0, 2).join('').toUpperCase() || '?';
  $: void resolve(id, sport, historical);
  async function resolve(identity: string, league: string, gameTime: boolean) {
    const version = ++request; url = null;
    if (gameTime) return; // Provider photos are mutable and not season-versioned.
    const result = await playerPortrait(identity, league);
    if (version === request) url = result;
  }
</script>
<span class="player-portrait" title={historical ? `${name} · No verified game-time portrait available` : name} aria-hidden="true">
  <span>{initials}</span>
  {#if url && failed !== url}<img src={url} alt="" loading="lazy" decoding="async" on:error={() => failed = url ?? ''}/>{/if}
</span>
<style>
  .player-portrait {display:inline-grid; place-items:center; position:relative; width:2.4rem; height:2.4rem; flex:0 0 2.4rem; border-radius:50%; overflow:hidden; background:var(--color-surface-control, #193345); color:var(--color-text-primary, #edf7ff); border:1px solid var(--line, #315063); vertical-align:middle; font-size:.7rem;}
  img {position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:var(--color-surface-control, #193345);}
</style>
