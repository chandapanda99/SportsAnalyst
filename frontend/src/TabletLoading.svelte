<script lang="ts">
  export let sport = 'nfl';
  export let message = 'Rendering Tablet…';
  export let detail = 'Preparing the recorded play and its schematic.';
  export let compact = false;
  let position = 45;
  $: basketball = sport === 'nba';
  $: soccer = sport === 'soccer';
  $: ballX = 24 + position * 2.72;
  $: ballY = 77 - Math.sin(position / 100 * Math.PI) * 35;
</script>

<section class="tablet-loading" class:compact aria-label="Tablet loading">
  <div class="loading-copy" role="status" aria-live="polite">
    <span class="loading-eyebrow">PLAY TABLET</span>
    <strong><i aria-hidden="true"></i>{message}</strong>
    <p>{detail}</p>
  </div>
  <div class="preview">
    <svg viewBox="0 0 320 112" aria-hidden="true" focusable="false">
      <rect x="4" y="4" width="312" height="100" rx="9" class="surface"/>
      {#if basketball}
        <path d="M160 4V104 M4 26H43V82H4 M316 26H277V82H316" class="marking"/>
        <circle cx="160" cy="54" r="22" class="marking"/>
      {:else if soccer}
        <path d="M160 4V104 M4 24H48V84H4 M316 24H272V84H316" class="marking"/>
        <circle cx="160" cy="54" r="20" class="marking"/>
      {:else}
        {#each [42, 81, 120, 160, 200, 239, 278] as x}
          <path d={`M${x} 5V103`} class="marking"/>
        {/each}
      {/if}
      <path d="M24 77 Q160 7 296 77" class="route"/>
      <circle cx="24" cy="77" r="9" class="actor"/>
      <circle cx="296" cy="77" r="9" class="actor"/>
      <g transform={`translate(${ballX} ${ballY})`}>
        {#if !basketball && !soccer}<ellipse rx="9" ry="5.5" class="ball football"/><path d="M-4 0H4 M-2-2V2 M1-2V2" class="stitch"/>
        {:else}<circle r="7" class="ball" class:basketball/>{/if}
      </g>
    </svg>
    <label>Interactive preview · drag the ball
      <input type="range" min="0" max="100" bind:value={position} aria-label="Move preview ball"/>
    </label>
    <small>Preview only · does not change the play</small>
  </div>
</section>

<style>
  .tablet-loading {display:flex;align-items:center;justify-content:space-between;gap:28px;min-height:260px;padding:28px;box-sizing:border-box;border:1px solid #315063;border-radius:12px;background:linear-gradient(130deg,#0b1d2c,#102b39);margin-top:12px;color:#e6f3fa;}
  .loading-copy {flex:1;min-width:0;}.loading-eyebrow {font:11px monospace;letter-spacing:.16em;color:#80e7d1;}
  strong {display:flex;align-items:center;gap:10px;font-size:23px;margin-top:14px;}
  strong i {width:9px;height:9px;border-radius:50%;background:#80e7d1;box-shadow:0 0 16px #80e7d160;animation:pulse 1.6s ease-in-out infinite;flex-shrink:0;}
  p {color:#a7becd;font-size:14px;line-height:1.5;margin:12px 0 0;max-width:38ch;}
  .preview {width:320px;max-width:48%;}svg {display:block;width:100%;height:auto;}.surface {fill:#102e36;stroke:#52727c;stroke-width:1;}
  .marking {fill:none;stroke:#9dbabd;stroke-width:1;opacity:.35;}.route {fill:none;stroke:#80e7d1;stroke-dasharray:5 5;stroke-width:1.5;animation:route 2s linear infinite;}
  .actor {fill:#162f40;stroke:#80e7d1;stroke-width:1.5;}.ball {fill:#f4f8fa;stroke:#102331;stroke-width:1.4;}.football {fill:#d7894a;}.basketball {fill:#ef9148;}.stitch {stroke:#fff;stroke-width:1;}
  label {display:flex;flex-direction:column;gap:4px;margin-top:8px;font-size:12px;color:#c3d6df;}input {width:100%;height:28px;margin:0;accent-color:#80e7d1;cursor:ew-resize;}small {font-size:10px;color:#94afbf;}
  .compact {min-height:155px;padding:16px 20px;}.compact strong {font-size:18px;margin-top:6px;}.compact p {margin-top:6px;}.compact .preview {width:230px;}
  @keyframes pulse {50% {opacity:.35;}}@keyframes route {to {stroke-dashoffset:-20;}}
  @media(prefers-reduced-motion:reduce) {strong i,.route {animation:none;}}
  @media(max-width:600px) {.tablet-loading {flex-direction:column;align-items:stretch;gap:16px;padding:20px;}.preview,.compact .preview {width:100%;max-width:360px;align-self:center;}strong {font-size:20px;}}
</style>
