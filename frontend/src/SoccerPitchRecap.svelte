<script lang="ts">
  import {onDestroy} from 'svelte';
  import {surface} from '@sportsdataverse/sporty';
  import {toSVG} from '@sportsdataverse/sporty/svg';
  import {soccerPitch} from './surfaceGeometry';
  import ShotGoalView from './ShotGoalView.svelte';
  import ShotMarker from './ShotMarker.svelte';
  import {eventClock, recapSources, sourceName, staticRecap, type SourceRecord, type RecapEvent} from './soccerRecap';

  export let actions: SourceRecord[] = [];
  export let analytics: SourceRecord[] = [];
  export let total = 0;
  export let matchKey = '';
  export let timeline: SourceRecord[] = [];
  export let focusTimelineKey = '';
  export let focusRevision = 0;

  const scene = surface('soccer', 'fifa', {updates: soccerPitch, colorUpdates: {plot_background: '#0b211d'}});
  // Only trusted package geometry enters this markup; event data use SVG bindings.
  const geometry = toSVG(scene, {width: 920, arcs: 'svg'}).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '');
  const [x0, y0, x1, y1] = scene.bbox;
  const viewBox = `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`;
  let provider = '';
  let team = 'all';
  let kind = 'all';
  let possession = 'all';
  let selected = 0;
  let playing = false;
  let speed = 1500;
  let timer: ReturnType<typeof setInterval> | undefined;
  let dataKey: unknown;
  let appliedFocus = '';

  $: resetData(matchKey, actions, analytics, timeline);
  $: sources = recapSources(actions, analytics, timeline);
  $: providers = [...sources.keys()];
  $: source = providers.includes(provider) ? provider : providers[0] ?? '';
  $: events = sources.get(source) ?? [];
  $: teams = [...new Map(events.filter(e => e.team).map(e => [e.team, e.teamName] as const))];
  $: kinds = [...new Set(events.map(e => e.kind))];
  $: possessions = [...new Set(events.map(e => e.possession).filter(Boolean))];
  $: filtered = events.filter(e => (team === 'all' || e.team === team) && (kind === 'all' || e.kind === kind)
    && (possession === 'all' || e.possession === possession));
  $: current = filtered[selected] ?? filtered[0];
  $: recap = staticRecap(current);
  $: shotEndpoint = current?.shot?.endpoint;
  $: fotmobShots = sources.get('fotmob') ?? [];
  $: visibleCount = source === 'statsbomb' ? Math.max(total, events.length) : events.length;
  $: if (selected >= filtered.length) {selected = 0; pause();}
  // Keep assignments visible to Svelte's dependency ordering so source and
  // filtered events update together, including the initial timeline selection.
  $: if (focusTimelineKey && appliedFocus !== `${focusTimelineKey}:${focusRevision}`) {
    const index = (sources.get('espn') ?? []).findIndex(event => event.qualifiers.timeline_key === focusTimelineKey);
    if (index >= 0) {
      pause(); provider = 'espn'; team = 'all'; kind = 'all'; possession = 'all'; selected = index;
      appliedFocus = `${focusTimelineKey}:${focusRevision}`;
    }
  }
  $: if (current && selected === filtered.length - 1 && playing) pause();

  function pause() {
    playing = false;
    if (timer !== undefined) clearInterval(timer);
    timer = undefined;
  }
  function resetData(key: string, nextActions: SourceRecord[], nextAnalytics: SourceRecord[], nextTimeline: SourceRecord[]) {
    const next = [key, nextActions, nextAnalytics, nextTimeline];
    if (!next.some((v, i) => !Array.isArray(dataKey) || dataKey[i] !== v)) return;
    dataKey = next;
    pause(); selected = 0; provider = ''; team = 'all'; kind = 'all'; possession = 'all'; appliedFocus = '';
  }
  function restartFilters() {pause(); selected = 0;}
  function changeSource() {team = 'all'; kind = 'all'; possession = 'all'; restartFilters();}
  function step(delta: number) {pause(); selected = Math.max(0, Math.min(filtered.length - 1, selected + delta));}
  function toggle() {
    if (playing) {pause(); return;}
    if (filtered.length < 2) return;
    if (selected >= filtered.length - 1) selected = 0;
    playing = true;
    timer = setInterval(() => {
      if (selected >= filtered.length - 1) {pause(); return;}
      selected += 1;
    }, speed);
  }
  function select(index: number) {pause(); selected = index;}
  function arrow(event: RecapEvent) {
    if (!event.start || !event.end) return '';
    const angle = Math.atan2(event.end.y - event.start.y, event.end.x - event.start.x);
    if (event.start.x === event.end.x && event.start.y === event.end.y) return '';
    const a = angle + .45, b = angle - .45;
    const tx = event.end.x - 1.5 * Math.cos(angle), ty = event.end.y - 1.5 * Math.sin(angle);
    return `M${tx - 3 * Math.cos(a)},${ty - 3 * Math.sin(a)} L${tx},${ty} L${tx - 3 * Math.cos(b)},${ty - 3 * Math.sin(b)}Z`;
  }
  onDestroy(pause);
</script>

<section class="pitch-recap" aria-label="Soccer pitch event recap">
  <header><div><small>RECORDED EVENT RECAP</small><h4>On the pitch</h4></div>
    <span class="source">{sourceName(source) || 'No spatial source acquired'}</span></header>
  {#if providers.length}
    <div class="filters">
      <label>Recap source <select value={source} on:change={event => {provider = event.currentTarget.value; changeSource();}}>
        {#each providers as name}<option value={name}>{sourceName(name)}</option>{/each}
      </select></label>
      <label>Recap team <select bind:value={team} on:change={restartFilters}><option value="all">Both teams</option>
        {#each teams as [id, name]}<option value={id}>{name === 'Recorded team' ? `Team ${id}` : name}</option>{/each}
      </select></label>
      <label>Event type <select bind:value={kind} on:change={restartFilters}><option value="all">All recorded types</option>
        {#each kinds as value}<option value={value}>{value}</option>{/each}
      </select></label>
      {#if possessions.length}<label>Possession <select bind:value={possession} on:change={restartFilters}>
        <option value="all">All recorded possessions</option>{#each possessions as value}<option value={value}>{value}</option>{/each}
      </select></label>{/if}
    </div>
    <p class="coverage">{events.length} of {visibleCount} source events available in this visual · {filtered.length} match the filters.
      {#if visibleCount > events.length}This recap is incomplete; omitted events are not reconstructed.{/if}</p>
  {:else}<p class="coverage">No spatial event dataset is attached to this match. Recorded timeline context remains available below.</p>{/if}
  <div class="recap-grid">
    <div class="pitch-wrap">
      {#if current?.start || recap.zone}
      <svg {viewBox} class:playing role="img" aria-label="Recorded action start and end locations">
        {@html geometry}
        <g transform="translate(-52.5,-34)">
          {#if current?.start && shotEndpoint}
            <line class="shot-path" x1={current.start.x} y1={current.start.y} x2={shotEndpoint.x} y2={shotEndpoint.y}/>
            <ShotMarker x={shotEndpoint.x} y={shotEndpoint.y} outcome={current.shot?.outcome}/>
          {/if}
          {#if !current?.start && recap.zone}
            <rect class="commentary-zone" x={recap.zone.x} y={recap.zone.y} width={recap.zone.width} height={recap.zone.height}/>
          {/if}
          {#if current?.start}
            {#if current.end}
              <line class="action-path" x1={current.start.x} y1={current.start.y} x2={current.end.x} y2={current.end.y}/>
              <path class="arrow" d={arrow(current)}/>
              <circle class="endpoint" cx={current.end.x} cy={current.end.y} r="1.2"/>
            {/if}
            <circle class="halo" cx={current.start.x} cy={current.start.y} r="3.5"/>
            <circle class="event-point" class:goal={current.outcome === 'Goal'} cx={current.start.x} cy={current.start.y}
              r={current.xg === null ? 1.4 : 1.4 + Math.sqrt(Math.max(0, Math.min(1, current.xg))) * 1.7}/>
          {/if}
        </g>
      </svg>
      {#if !current?.start && recap.zone}<p class="location-gap">From commentary: {recap.zone.label}. Shaded area is a broad zone, not an exact position.</p>{/if}
      {:else if current}
        <div class="static-event" class:discipline={recap.category === 'card'} aria-label="Event summary visual">
          <span class="event-icon" aria-hidden="true">{recap.category === 'substitution' ? '⇄' : recap.category === 'card' ? '▮' : recap.category === 'goal' || recap.category === 'shot' ? '⚽' : '◷'}</span>
          <strong>{current.kind}</strong><span>{eventClock(current)} · {current.teamName}</span>
          {#if recap.category === 'substitution'}
            <div class="replacement"><span>↑ ON<br/><strong>{String(current.qualifiers.player_in || 'Not recorded')}</strong></span>
              <span>↓ OFF<br/><strong>{String(current.qualifiers.player_out || 'Not recorded')}</strong></span></div>
          {:else}<strong>{current.player === 'Not recorded' ? 'Player not recorded' : current.player}</strong>{/if}
          {#if recap.assist}<span>Assist · {recap.assist}</span>{/if}
          <small>No spatial location was recorded for this event.</small>
        </div>
      {/if}
      {#if current?.provider === 'espn' && !current.start && !recap.zone}<p class="location-gap">The selected timeline event has no recorded pitch coordinates.</p>{/if}
      {#if source === 'espn' && !current?.shot && fotmobShots.length && (recap.category === 'goal' || recap.category === 'shot')}
        <p class="location-gap">FotMob has {fotmobShots.length} shots for this match, but this timeline event has no uniquely verified shot match.</p>
        <button type="button" on:click={() => {provider = 'fotmob'; changeSource();}}>Browse recorded FotMob shots</button>
      {/if}
      {#if focusTimelineKey && source !== 'espn'}<p class="coverage">Browsing a separate source stream. Select a timeline event to return to its recap.</p>{/if}
      {#if current?.qualifiers.spatial_provider}<p class="coverage">Spatial context: {sourceName(String(current.qualifiers.spatial_provider))} · matched event {String(current.qualifiers.spatial_event_id)}.</p>{/if}
      {#if current?.shot}
        <p class="shot-caption"><strong>{current.shot.outcome === 'saved' ? 'Saved' : current.shot.outcome === 'blocked' ? 'Blocked' : current.shot.outcome === 'goal' ? 'Goal' : 'Missed / other shot'}</strong>
          · Point = shot origin. Dashed line = static connection between recorded positions, not ball flight.</p>
        {#if !shotEndpoint && (current.shot.outcome === 'blocked' || current.shot.outcome === 'saved')}
          <svg class="outcome-badge" viewBox="0 0 24 24"><ShotMarker x={12} y={12} size={22} outcome={current.shot.outcome}/></svg>
          <p class="location-gap">The {current.shot.outcome === 'blocked' ? 'block' : 'save'} location was not recorded.</p>
        {/if}
        <ShotGoalView shot={current.shot}/>
      {:else if current?.start && !current.end}<p class="location-gap">Point-only event: no usable endpoint was recorded.</p>{/if}
      {#if !focusTimelineKey || source !== 'espn'}
      <div class="transport" aria-label="Recap playback controls">
        <button type="button" aria-label="Previous action" disabled={!current || selected <= 0} on:click={() => step(-1)}>← Previous</button>
        {#if !focusTimelineKey}<button type="button" class="play" disabled={filtered.length < 2} aria-pressed={playing} on:click={toggle}>
          {playing ? 'Pause recap' : 'Play recap'}</button>
        {/if}
        <button type="button" aria-label="Next action" disabled={!current || selected >= filtered.length - 1} on:click={() => step(1)}>Next →</button>
        {#if !focusTimelineKey}<label>Playback pace <select bind:value={speed} on:change={pause}>
          <option value={3000}>Slow</option><option value={1500}>Normal</option><option value={750}>Fast</option>
        </select></label>{/if}
      </div>
      {#if !focusTimelineKey}<small>Playback steps between recorded events at a presentation pace, not real match speed. No movement is inferred between events.</small>{/if}
      {/if}
    </div>
    <div class="event-context">
      {#if current}
        <div class="event-title"><span>{eventClock(current)}</span><span>{selected + 1} / {filtered.length}</span></div>
        <h5>{current.kind} · {current.player}</h5>
        {#if current.qualifiers.text}<p>{String(current.qualifiers.text)}</p>{/if}
        <p>{current.period === null ? 'Period not recorded' : `Period ${current.period}`} · {current.teamName === 'Recorded team' ? `Team ${current.team || 'not recorded'}` : current.teamName}</p>
        {#if current.uncertainOrder}<p class="gap">Ordering at this recorded time is not established. Source listing order is preserved.</p>{/if}
        <dl><div><dt>Outcome</dt><dd>{current.outcome}</dd></div>
          {#if !focusTimelineKey || current.xg !== null}<div><dt>Shot xG</dt><dd>{current.xg === null ? 'Not recorded' : current.xg.toFixed(3)}</dd></div>{/if}
          {#if !focusTimelineKey || current.xgot !== null}<div><dt>xGOT</dt><dd>{current.xgot === null ? 'Not recorded' : current.xgot.toFixed(3)}</dd></div>{/if}
          {#if !focusTimelineKey || current.xt !== null}<div><dt>xT added</dt><dd>{current.xt === null ? 'Not recorded' : current.xt.toFixed(3)}</dd></div>{/if}
          {#if !focusTimelineKey || current.possession}<div><dt>Source possession</dt><dd>{current.possession || 'Not recorded'}</dd></div>{/if}
          {#each ['player_in', 'player_out', 'play_pattern', 'body_part', 'technique', 'under_pressure', 'pass_recipient_name', 'situation', 'shot_type', 'duel_type'] as field}
            {#if current.qualifiers[field] != null}<div><dt>{field.replaceAll('_', ' ')}</dt><dd>{String(current.qualifiers[field])}</dd></div>{/if}
          {/each}
        </dl>
        <small>{current.orientation} Player identity: {sourceName(source)}{current.shot ? `; shot data: ${sourceName(current.shot.provider)}` : ''}.</small>
        <p class="source-id">Source event: {current.id.startsWith('unidentified-') ? 'ID not recorded' : current.id}</p>
      {:else}<p>No recorded events match this selection.</p>{/if}
    </div>
  </div>
  {#if filtered.length && (!focusTimelineKey || source !== 'espn')}
    <label class="event-picker">Recorded action <select value={selected} on:change={event => select(Number(event.currentTarget.value))}>
      {#each filtered as event, index}<option value={index}>{eventClock(event)} · {event.kind} · {event.player}</option>{/each}
    </select></label>
    <input class="scrubber" type="range" min="0" max={Math.max(0, filtered.length - 1)} value={selected}
      aria-label="Recap event position" aria-valuetext={current ? `${eventClock(current)} ${current.kind}` : ''}
      on:input={event => select(Number(event.currentTarget.value))}/>
  {/if}
  <footer>Illustrative 105 × 68 m pitch. Lines connect only a recorded event's own endpoints; no tracked ball flight, full-player positions,
    or links across missing events are implied. Source streams remain separate.</footer>
</section>

<style>
  .pitch-recap {margin:18px 0;border:1px solid #315063;border-radius:12px;background:#0c202c;overflow:hidden;color:#e6f3fa;}
  header,.filters,.coverage,.event-picker,footer {padding:16px 20px;}header {display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #315063;}
  h4 {margin:4px 0 0;font-size:1.3rem;}small,dt,.coverage,footer,.source-id {color:#a7becd;line-height:1.5;}header small {color:#80e7d1;letter-spacing:.12em;font-size:.65rem;}
  .source {border:1px solid #426376;border-radius:30px;padding:5px 12px;font-size:.8rem;}.filters {display:flex;gap:12px;flex-wrap:wrap;padding-bottom:0;}
  label {display:flex;flex-direction:column;gap:6px;min-width:0;font-size:.8rem;}button,select {border:1px solid #426376;background:#102c3b;color:#e6f3fa;border-radius:6px;padding:9px;max-width:100%;}
  button {cursor:pointer;}button:disabled {opacity:.4;cursor:default;}button:focus-visible,select:focus-visible,input:focus-visible {outline:2px solid #80e7d1;outline-offset:3px;}
  .play {border-color:#80e7d1;color:#80e7d1;}.coverage {margin:0;font-size:.8rem;}.recap-grid {display:grid;grid-template-columns:minmax(0,1.8fr) minmax(240px,1fr);border-top:1px solid #315063;}
  .pitch-wrap {padding:12px;min-width:0;}svg {display:block;width:100%;background:#0b211d;border-radius:8px;}.transport {display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0;}
  .static-event {min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:24px;text-align:center;background:radial-gradient(ellipse at top,#1c4a3d,#0b211d);border-radius:8px;}
  .event-icon {font-size:3rem;color:#91f2d5;}.discipline .event-icon {color:#ffc680;}.replacement {display:grid;grid-template-columns:1fr 1fr;gap:28px;line-height:1.8;}
  svg .commentary-zone {fill:#ffc680;fill-opacity:.25;stroke:#ffc680;stroke-width:.5;stroke-dasharray:2 1;}
  .transport label {margin-left:auto;}svg .action-path,svg .arrow {fill:none;stroke:#91f2d5;stroke-width:.8;}svg .endpoint {fill:#ffc680;stroke:#071e22;stroke-width:.6;}
  svg .arrow {fill:#91f2d5;stroke-width:.3;}
  svg .shot-path {stroke:#ffd188;stroke-width:.65;stroke-dasharray:2 1.5;}
  .outcome-badge {width:42px;background:transparent;}.shot-caption {font-size:.8rem;color:#bcd2cd;line-height:1.5;}
  svg .event-point {fill:#91f2d5;stroke:white;stroke-width:.5;}svg .goal {fill:#ffc680;}svg .halo {fill:none;stroke:#91f2d5;stroke-width:.5;opacity:.5;}
  svg.playing .halo {animation:recap-focus 1s ease-in-out infinite;}@keyframes recap-focus {50% {opacity:1;stroke-width:1;}}
  @media(prefers-reduced-motion:reduce) {svg.playing .halo {animation:none;}}
  .event-context {padding:18px;border-left:1px solid #315063;min-width:0;}.event-title {display:flex;justify-content:space-between;gap:10px;color:#91f2d5;font-size:.8rem;}
  h5 {font-size:1.05rem;margin:14px 0 8px;}.event-context p {font-size:.8rem;line-height:1.5;}.gap,.location-gap {color:#ffc680;font-size:.8rem;}
  dl {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0;}dt {font-size:.7rem;}dd {margin:4px 0 0;overflow-wrap:anywhere;}
  .event-picker {padding-bottom:8px;}.scrubber {display:block;width:calc(100% - 40px);margin:4px 20px 18px;accent-color:#80e7d1;}footer {border-top:1px solid #315063;font-size:.75rem;}
  @media(max-width:760px) {.recap-grid {grid-template-columns:minmax(0,1fr);}.event-context {border-left:0;border-top:1px solid #315063;}header,.filters,.coverage,.event-picker,footer {padding-left:12px;padding-right:12px;}.filters label {flex:1 1 120px;}.transport label {margin-left:0;}.source {font-size:.7rem;}}
</style>
