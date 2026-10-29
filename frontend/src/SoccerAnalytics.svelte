<script lang="ts">
  export let rows: Array<Record<string, unknown>> = [];
  export let showShots = true;
  type RecordValue = Record<string, unknown>;
  function records(value: unknown): RecordValue[] {
    try {const parsed = JSON.parse(String(value ?? '[]')); return Array.isArray(parsed) ? parsed.filter(v => v && typeof v === 'object') : [];}
    catch {return [];}
  }
  function context(value: unknown): RecordValue {
    try {const parsed = JSON.parse(String(value ?? '{}')); return parsed && !Array.isArray(parsed) ? parsed : {};}
    catch {return {};}
  }
  const label = (key: string) => key.replaceAll('_', ' ');
  const format = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString(undefined, {maximumFractionDigits: 3}) : '—';
  let tab = 'shots';
  $: if (!showShots && tab === 'shots') tab = 'teams';
  let team = 'all';
  let player = '';
  let selected = 0;
  let provider = '';
  $: providers = [...new Set(rows.map(row => String(row.provider ?? 'fotmob')))];
  $: selectedProvider = providers.includes(provider) ? provider : providers[0];
  $: sourceRows = rows.filter(row => String(row.provider ?? 'fotmob') === selectedProvider);
  $: shots = sourceRows.flatMap(row => records(row.shots_json)).filter(shot => team === 'all' || shot.espn_team_id === team);
  $: positioned = shots.filter(s => typeof s.x === 'number' && s.x >= 0 && s.x <= 105
    && typeof s.y === 'number' && s.y >= 0 && s.y <= 68);
  $: players = sourceRows.flatMap(row => records(row.players_json)).filter(p => team === 'all' || p.team_id === team);
  $: chosenPlayer = players.find(p => p.provider_player_id === player) ?? players[0];
  $: selectedShot = positioned[selected] ?? positioned[0];
  $: fields = [...new Set(sourceRows.flatMap(row => Object.keys(row).filter(key => typeof row[key] === 'number')))];
  $: contexts = sourceRows.map(row => ({name: row.team_name, ...context(row.context_json)} as RecordValue));
</script>

<section class="analytics" aria-label="Advanced recorded match analytics">
  <header><h4>Advanced match analytics</h4><span>{selectedProvider} · recorded source data</span></header>
  <p>Separately attributed from ESPN. Player identities use each provider's native IDs. Upstream model versions are undisclosed.</p>
  {#if providers.length > 1}<label>Data source <select bind:value={provider} on:change={() => {team = 'all'; player = ''; selected = 0;}}>
    {#each providers as name}<option value={name}>{name}</option>{/each}
  </select></label>{/if}
  <nav aria-label="Match analytics views">
    {#each [['shots', 'Shots & chances'], ['teams', 'Team statistics'], ['players', 'Player statistics'], ['context', 'Match context']] as [value, name]}
      {#if showShots || value !== 'shots'}
      <button type="button" aria-pressed={tab === value} on:click={() => tab = value}>{name}</button>
      {/if}
    {/each}
  </nav>
  <label>Team <select bind:value={team} on:change={() => {selected = 0; player = '';}}><option value="all">Both teams</option>
    {#each sourceRows as row}<option value={String(row.team_id)}>{row.team_name ?? row.team_id}</option>{/each}
  </select></label>
  {#if tab === 'shots'}
    <p>{shots.length} recorded shots · {positioned.length} with usable source coordinates. Positions are event locations, not player tracking.</p>
    {#if positioned.length}
      <svg viewBox="-2 -2 109 72" role="img" aria-label="Recorded shot locations on a 105 by 68 pitch">
        <rect width="105" height="68" class="pitch"/><path d="M52.5 0V68 M0 13.84H16.5V54.16H0 M105 13.84H88.5V54.16H105"/>
        <circle cx="52.5" cy="34" r="9.15"/>
        {#each positioned as shot, index}
          <g transform={`translate(${shot.x} ${shot.y})`} role="button" tabindex="0"
             aria-label={`${shot.min ?? '?'} minute ${shot.playerName ?? 'Unknown player'} ${shot.eventType ?? 'Shot'}`}
             aria-pressed={selectedShot === shot} on:click={() => selected = index}
             on:keydown={event => {if (['Enter', ' '].includes(event.key)) {event.preventDefault(); selected = index;}}}>
            <circle class="shot" class:goal={shot.eventType === 'Goal'} class:chosen={selectedShot === shot}
                    r={typeof shot.expectedGoals === 'number' ? 1.1 + Math.sqrt(Math.max(0, shot.expectedGoals)) * 1.5 : 1.1}/>
          </g>
        {/each}
      </svg>
      <label>Recorded shot <select bind:value={selected}>{#each positioned as shot, index}
        <option value={index}>{shot.min ?? '?'}′ · {shot.playerName ?? 'Unknown player'} · {shot.eventType ?? 'Shot'}</option>
      {/each}</select></label>
      {#if selectedShot}<dl>
        <div><dt>Player</dt><dd>{selectedShot.playerName ?? 'Not recorded'}</dd></div>
        <div><dt>xG</dt><dd>{format(selectedShot.expectedGoals)}</dd></div>
        <div><dt>xGOT</dt><dd>{format(selectedShot.expectedGoalsOnTarget)}</dd></div>
        <div><dt>Situation</dt><dd>{selectedShot.situation ?? 'Not recorded'}</dd></div>
        <div><dt>Body part</dt><dd>{selectedShot.shotType ?? 'Not recorded'}</dd></div>
        <div><dt>Result</dt><dd>{selectedShot.eventType ?? 'Not recorded'}</dd></div>
      </dl>{/if}
      <small>Marker size reflects recorded xG where supplied. Provider coordinates are displayed as supplied; this is not a replay trajectory.</small>
    {:else}<p>No usable shot locations were recorded for this selection.</p>{/if}
  {:else if tab === 'teams'}
    <div class="table-wrap" role="region" aria-label="Recorded team statistics"><table><thead><tr><th>Statistic</th>
      {#each sourceRows as row}<th>{row.team_name ?? row.team_id}</th>{/each}</tr></thead><tbody>
      {#each fields as field}<tr><th>{label(field)}</th>{#each sourceRows as row}<td>{format(row[field])}</td>{/each}</tr>{/each}
    </tbody></table></div>
    <small>Recorded provider keys and raw units; “attempts” columns preserve supplied fraction denominators. Missing values stay unavailable.</small>
  {:else if tab === 'players'}
    {#if players.length}
      <label>Player <select bind:value={player}>{#each players as p}<option value={String(p.provider_player_id)}>{p.name} · #{p.shirt_number ?? '?'}</option>{/each}</select></label>
      <h5>{chosenPlayer?.name}</h5><dl>{#each Object.entries(chosenPlayer ?? {}) as [field, value]}
        {#if typeof value === 'number' && field !== 'position'}<div><dt>{label(field)}</dt><dd>{format(value)}</dd></div>{/if}
      {/each}</dl>
      <small>Recorded player-match values. Physical metrics and proprietary ratings retain provider definitions and units; they are not inferred from events.</small>
    {:else}<p>No player statistics were recorded.</p>{/if}
  {:else}
    {#each contexts as item}<p><strong>{item.name}</strong> · Formation: {item.formation ?? 'Not recorded'} · Coverage: {item.coverage_level ?? 'Not recorded'}</p>{/each}
    <p>Formation labels describe the source lineup. They do not establish tracked locations or tactical assignments.</p>
  {/if}
</section>

<style>
  .analytics {margin:18px 0;padding:20px;border:1px solid #315063;border-radius:10px;background:#102333;min-width:0;}
  header {display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;}h4 {margin:0;}p,small,header span {color:#a7becd;line-height:1.5;}
  nav {display:flex;gap:8px;flex-wrap:wrap;margin:14px 0;}button,select {padding:8px;border:1px solid #426376;background:#0b1d2c;color:#e6f3fa;border-radius:5px;max-width:100%;}
  button[aria-pressed=true] {border-color:#80e7d1;color:#80e7d1;}label {display:block;margin:12px 0;}
  svg {display:block;max-width:750px;width:100%;margin:12px auto;background:#163d35;}svg rect,svg path,svg circle {fill:none;stroke:#a4c1b5;stroke-width:.4;}
  svg .shot {fill:#8adcca;stroke:#07232a;stroke-width:.6;cursor:pointer;}svg .goal {fill:#ffb76b;}svg .chosen {stroke:white;stroke-width:1.2;}
  g:focus .shot {stroke:white;stroke-width:1.2;}dl {display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}
  dl div {padding:10px;background:#0b1d2c;}dt {color:#a7becd;font-size:12px;}dd {margin:5px 0 0;overflow-wrap:anywhere;}
  .table-wrap {overflow:auto;}table {width:100%;border-collapse:collapse;}td,th {padding:9px;text-align:left;border-bottom:1px solid #315063;}th {font-weight:500;}
  @media(max-width:600px) {.analytics {padding:12px;}nav button {flex:1 1 40%;}}
</style>
