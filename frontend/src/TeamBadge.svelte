<script lang="ts">
  export let logo: string | null = null;
  export let label: string;
  export let initials: string;

  let loadedLogo = '';
  let failedLogo = '';
</script>

<span class="recent-subject-badge" title={label}>
  <span class:hidden={Boolean(logo && loadedLogo === logo && failedLogo !== logo)}>{initials}</span>
  {#if logo && failedLogo !== logo}
    <img src={logo} alt="" width="26" height="26" loading="lazy" decoding="async"
         class:loaded={loadedLogo === logo}
         on:load={() => loadedLogo = logo ?? ''} on:error={() => failedLogo = logo ?? ''}/>
  {/if}
</span>

<style>
  .recent-subject-badge { position: relative; display: inline-grid; place-items: center; flex: 0 0 30px; width: 30px; height: 30px; line-height: 1; }
  .hidden { visibility: hidden; }
  img { position: absolute; inset: 0; margin: auto; width: 26px; height: 26px; object-fit: contain; opacity: 0; }
  img.loaded { opacity: 1; }
</style>
