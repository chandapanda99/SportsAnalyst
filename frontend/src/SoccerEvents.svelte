<script lang="ts">
  export let actions: Array<Record<string, unknown>> = [];
  export let total = 0;
  let kind = 'all';
  let selected = 0;
  $: kinds = [...new Set(actions.map(a => String(a.event_type)))].sort();
  $: filtered = actions.filter(a => kind === 'all' || a.event_type === kind);
  $: action = filtered[selected] ?? filtered[0];
  function point(x: unknown, y: unknown): x is number {
    return typeof x === 'number' && Number.isFinite(x) && x >= 0 && x <= 105
      && typeof y === 'number' && Number.isFinite(y) && y >= 0 && y <= 68;
  }
  const format = (value: unknown) => typeof value === 'number' ? value.toFixed(3) : 'Not recorded';
</script>

<section class="events" aria-label="Recorded open-event actions">
  <h4>Recorded match actions · StatsBomb open data</h4>
  <p>{actions.length} of {total || actions.length} source events available in this visual.
    Analysis uses the complete acquired event sample. Source player IDs remain separate from ESPN.</p>
  <div class="controls"><label>Event type <select bind:value={kind} on:change={() => selected = 0}>
    <option value="all">All recorded types</option>{#each kinds as value}<option value={value}>{value}</option>{/each}
  </select></label>
  <label>Recorded action <select bind:value={selected}>{#each filtered as item, index}
    <option value={index}>{item.minute ?? '?'}:{String(item.second ?? 0).padStart(2, '0')} · {item.event_type} · {item.player_name ?? 'No player recorded'}</option>
  {/each}</select></label></div>
  <button type="button" disabled={selected <= 0} on:click={() => selected -= 1}>Previous action</button>
  <button type="button" disabled={selected >= filtered.length - 1} on:click={() => selected += 1}>Next action</button>
  {#if action}
    {#if point(action.start_x, action.start_y)}
      <svg viewBox="-2 -2 109 72" role="img" aria-label="Recorded action start and end locations">
        <rect width="105" height="68"/><path d="M52.5 0V68 M0 13.84H16.5V54.16H0 M105 13.84H88.5V54.16H105"/>
        <circle cx="52.5" cy="34" r="9.15"/>
        {#if point(action.end_x, action.end_y)}
          <line x1={Number(action.start_x)} y1={Number(action.start_y)} x2={Number(action.end_x)} y2={Number(action.end_y)}/>
          <circle class="end" cx={Number(action.end_x)} cy={Number(action.end_y)} r="1.4"/>
        {/if}
        <circle class="start" cx={Number(action.start_x)} cy={Number(action.start_y)} r="1.4"/>
      </svg>
    {:else}<p>No spatial location was recorded for this event.</p>{/if}
    <dl><div><dt>Action</dt><dd>{action.event_type}</dd></div><div><dt>Player</dt><dd>{action.player_name ?? 'Not recorded'}</dd></div>
      <div><dt>Outcome</dt><dd>{action.outcome ?? 'No explicit outcome field'}</dd></div>
      <div><dt>xT added</dt><dd>{format(action.xt)}</dd></div><div><dt>Shot xG</dt><dd>{format(action.xg)}</dd></div>
      <div><dt>Source possession</dt><dd>{action.possession ?? 'Not recorded'}</dd></div>
      {#each ['play_pattern', 'body_part', 'technique', 'under_pressure', 'pass_height', 'pass_length', 'pass_recipient_name', 'shot_type', 'duel_type', 'spadl_result'] as field}
        {#if action[field] != null}<div><dt>{field.replaceAll('_', ' ')}</dt><dd>{String(action[field])}</dd></div>{/if}
      {/each}
    </dl>
  {/if}
  <small>Recorded event endpoints, scaled to 105 × 68 in the source's executing-team orientation.
    Connecting lines illustrate actions; they are not tracked ball paths or full-player replay.</small>
</section>

<style>
  .events {padding:20px;margin:18px 0;border:1px solid #315063;border-radius:10px;background:#102333;min-width:0;}
  p,small,dt {color:#a7becd;line-height:1.5;}.controls {display:flex;gap:12px;flex-wrap:wrap;}label {display:flex;flex-direction:column;gap:5px;max-width:100%;}
  button,select {padding:8px;margin:6px 4px 6px 0;max-width:100%;background:#0b1d2c;color:#e6f3fa;border:1px solid #426376;border-radius:5px;}button:disabled {opacity:.4;}
  svg {display:block;width:100%;max-width:750px;background:#163d35;margin:12px auto;}svg rect,svg path,svg circle {fill:none;stroke:#a4c1b5;stroke-width:.4;}
  svg line {stroke:#80e7d1;stroke-width:.8;stroke-dasharray:2 1;}svg .start {fill:#80e7d1;}svg .end {fill:#ffb76b;}
  dl {display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}dl div {background:#0b1d2c;padding:10px;}dd {margin:5px 0 0;}
</style>
