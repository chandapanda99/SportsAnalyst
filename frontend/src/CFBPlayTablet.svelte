<script lang="ts">
  import type {CFBGameRosterPlayer, CFBParticipant, CFBRecordedPlay, CFBTeamContext} from './types';
  import {colorContrastRatio, teamChartPalette, teamLogoUrl} from './teamPalettes';
  import PlayerPortrait from './PlayerPortrait.svelte';
  import {footballHash} from './surfaceGeometry';
  import FootballSchematic from './FootballSchematic.svelte';
  import {adaptCollegePlay, collegeProviderContext} from './cfbSchematic';
  import {buildPlaySchematic} from './playSchematic';
  import FootballTablet from './FootballTablet.svelte';

  export let event: CFBRecordedPlay;
  export let teams: CFBTeamContext[] = [];
  export let season: number | undefined = undefined;
  export let roster: CFBGameRosterPlayer[] = [];
  let showProjected = false;
  $: home = teams.find(team => team.side === 'home');
  $: offense = teams.find(team => team.id === event.team_id);
  $: defense = offense ? teams.find(team => team.id !== offense.id) : undefined;
  $: actors = involved(event.participants ?? []);
  $: adapted = adaptCollegePlay(event, teams, roster, showProjected);
  $: projectionAvailable = adaptCollegePlay(event, teams, roster, true).projectedCount > 0;
  $: providerFields = Object.entries(collegeProviderContext(event));
  $: sourceFields = fieldSources(event.source_provenance_json);
  $: sourceDetail = sourceDetails(event.source_provenance_json);
  $: conflicts = Object.entries(sourceDetail.conflicts ?? {});
  $: sourceStatuses = Object.entries(sourceDetail.secondary_status ?? {});
  $: secondaryCoverage = coverageDetails(event.secondary_coverage_json);
  function sourceDetails(payload?: string | null): {
    conflicts?: Record<string, Array<{provider_id: string; value: unknown}>>;
    secondary_status?: Record<string, string>;
    alignment?: Record<string, {clock_disagreement?: boolean}>;
    source_policy?: {version?: string; feature?: string; decisions?: Record<string, {selected_provider?: string; reason: string}>};
  } {
    try { return JSON.parse(payload ?? '{}'); } catch { return {}; }
  }
  function coverageDetails(payload?: string | null): Array<[string, {
    matched_plays: number; unmatched: number; primary_overtime_plays: number; matched_overtime_plays: number;
  }]> {
    try { return Object.entries(JSON.parse(payload ?? '{}')); } catch { return []; }
  }
  function fieldSources(payload?: string | null): Array<[string, {provider_id: string; method: string; processing_version: string}]> {
    try { return Object.entries(JSON.parse(payload ?? '{}').provenance ?? {}); }
    catch { return []; }
  }
  $: schematic = buildPlaySchematic(adapted.visualization, footballHash(true));
  $: schematicPlay = {evidence_id: 'cfb-' + event.id, visualization: adapted.visualization};
  $: homePalette = teamChartPalette(home?.id ?? '', 'cfb', season, [home?.color ?? '#142c3d', home?.alternate_color ?? '#edf7ff']);
  $: offensePalette = teamChartPalette(offense?.id ?? '', 'cfb', season, [offense?.color ?? '#536575', offense?.alternate_color ?? '#edf7ff']);
  $: defensePalette = teamChartPalette(defense?.id ?? '', 'cfb', season, [defense?.color ?? '#364e68', defense?.alternate_color ?? '#edf7ff']);
  function involved(participants: CFBParticipant[]) {
    const unique = new Map<string, CFBParticipant & {roles: string[]}>();
    for (const actor of participants) {
      const existing = unique.get(actor.athlete_id);
      if (existing) { if (!existing.roles.includes(actor.role)) existing.roles.push(actor.role); }
      else unique.set(actor.athlete_id, {...actor, roles: [actor.role]});
    }
    return [...unique.values()];
  }
  function textColor(background: string) { return colorContrastRatio(background, '#ffffff') >= 4.5 ? '#ffffff' : '#07121d'; }
</script>

<FootballTablet label={`College-football schematic for play ${event.id}`}>
  <header><div><span>PLAY-BY-PLAY SCHEMATIC</span><h3>{event.play_type ?? 'Recorded play'} · Q{event.quarter ?? '?'} {event.clock ?? ''}</h3>
    <p>{event.down != null && event.down > 0 ? `${event.down} & ${event.distance ?? '?'}` : 'Down unavailable'} · {offense?.name ?? 'Possession team unavailable'}
      {#if event.yards_gained != null} · {event.yards_gained} recorded yards{/if}</p></div><div class="tablet-actions"><span>Recorded Play Context</span></div></header>
  <p class="scope reconstruction-meta">Recorded play context with illustrative football reconstruction; a full lineup is a template, not verified on-field personnel.</p>
  <p class="scope">Formation: {event.formation ?? 'Not recorded in this play narrative'}
    {#if event.formation_source} · {event.formation_source}{/if}. A formation label does not establish exact alignment.</p>
  {#if event.personnel_context}
    <p class="scope">Personnel source: {event.personnel_context.status.replaceAll('_', ' ')}
      {#if event.personnel_context.entries?.length} · {event.personnel_context.entries.length} recorded entries{/if}.
      {event.personnel_context.scope}</p>
  {/if}
  {#if adapted.reconstruct}
    <div class="reconstruction-meta"><div><strong>{showProjected && adapted.projectedCount ? 'Recorded participants + projected starters' : 'Recorded identities · illustrative formation'}</strong>
      <span>{schematic.context.formation} · {schematic.context.boxCount} in box (estimated) · {schematic.context.passRusherCount} rushers (estimated)</span>
    </div><div class="source-badges"><span>ESPN PBP</span><span>INFERRED ALIGNMENT</span></div></div>
    {#if projectionAvailable}
      <div class="lineup-controls">
        <label><input type="checkbox" bind:checked={showProjected}/> Show Projected Starters</label>
        <p>Optional game-starter projection. Substitutions and exact alignment are not confirmed for this snap; recorded participants always take priority.</p>
      </div>
    {/if}
    <p class="scope identity-key">{schematic.players.filter(player => player.recorded).length} recorded participants · {adapted.projectedCount} projected starters · {schematic.players.filter(player => !player.recorded && !player.projected).length} identities not recorded.
      {#if adapted.projectedCount}Dotted outlines identify projected starters. {/if}Hover or focus a player for identity and inference details.</p>
  {/if}
  {#if adapted.inference.airYardsAvailable || adapted.inference.yardsAfterCatchAvailable || event.pass_direction || event.rush_direction || event.pass_depth}
    <div class="situation">
      {#if adapted.inference.airYardsAvailable}<span title={event.air_yards_source ?? 'Provider-derived from recorded catch/target spot text'}>Air yards: {event.air_yards} · provider-derived</span>{/if}
      {#if adapted.inference.yardsAfterCatchAvailable}<span title={event.yards_after_catch_source ?? 'Provider-derived from play text'}>YAC: {event.yards_after_catch} · provider-derived</span>{/if}
      {#if event.pass_direction || event.rush_direction}<span title={event.pass_direction_source || event.rush_direction_source || undefined}>Direction: {event.pass_direction || event.rush_direction} · play text</span>{/if}
      {#if event.pass_depth}<span title={event.pass_depth_source ?? undefined}>Pass depth: {event.pass_depth} · play text</span>{/if}
    </div>
  {/if}
  <FootballSchematic play={schematicPlay}
    homeTeamName={home?.name ?? home?.abbreviation ?? 'Home'} homeTeam={home?.abbreviation ?? 'HOME'}
    homeLogo={home ? teamLogoUrl(home.id, 'cfb', season) ?? home.logo ?? null : null} {homePalette} {offensePalette} {defensePalette}
    endzoneTextColor={textColor(homePalette[0])} hashFromSideline={20}
    fieldLabel="College football field with recorded field position and illustrative involved-player markers"
    illustrative showPlayers={adapted.reconstruct} showMovement={adapted.movement}
    movementLabel={adapted.inference.airYardsAvailable ? 'Ball flight · provider-derived distance' : 'Illustrative movement (net yards)'}
    showFieldPosition={event.yards_to_goal != null && event.yards_to_goal >= 0 && event.yards_to_goal <= 100}/>
  <p class="legend">{adapted.note} College hashes are 20 yards from each sideline. Attack direction is normalized left-to-right.</p>
  <div class="play-details"><p>{event.text}</p></div>
  <div class="values situation"><span>Recorded score after play: {event.away_score ?? '—'}–{event.home_score ?? '—'} (away–home)</span>
    <span>Modeled EPA: {event.epa == null ? 'Not prepared/available' : event.epa.toFixed(3)}</span>
    <span>Spread-free WPA: {event.wpa == null ? 'Not prepared/available' : `${(event.wpa * 100).toFixed(2)} pp`}</span></div>
  <h4>Recorded involved players ({actors.length})</h4>
  <p class="scope">Schools reflect the selected game, not current player profiles. Photos are omitted because no game-time headshot is verified.</p>
  {#if actors.length}<ul>{#each actors as actor}<li><PlayerPortrait id={actor.athlete_id} sport="cfb" name={actor.name ?? 'Player'} historical/>{actor.name ?? `ESPN athlete ${actor.athlete_id}`} · {actor.roles.join(', ')}
    {#if actor.position}<span title={actor.position_source ?? 'Recorded roster position'}> · {actor.position}</span>{/if} · {teams.find(team => team.id === actor.team_id)?.name ?? 'School not verified'} · ESPN ID {actor.athlete_id}
    {#if actor.name_source}<span class="identity-source"> · {actor.name_source}</span>{/if}</li>{/each}</ul>
  {:else}<p>No participant IDs recorded for this play. This does not mean no players were on the field.</p>{/if}
  {#if providerFields.length}
    <details class="play-details provider-context">
      <summary>Available Provider Context ({providerFields.length} fields)</summary>
      <p>SportsDataverse {event.render_provider_version ?? ''}: parsed play text and modeled game state, not tracking coordinates. EPA, EP, WP and completion probabilities are models. False and zero are preserved; missing fields are not filled.</p>
      <dl>{#each providerFields as [key, value]}<div><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>{/each}</dl>
    </details>
  {/if}
  {#if sourceFields.length}
    <details class="play-details provider-context">
      <summary>Sources and field provenance</summary>
      <p>Recorded values, parsed text and models are distinguished below. Actor placement remains illustrative; these sources do not verify routes or coverage assignments.</p>
      <dl>{#each sourceFields as [field, source]}<div><dt>{field.replaceAll('_', ' ')}</dt>
        <dd>{source.provider_id} · {source.method.replaceAll('_', ' ')} · version {source.processing_version}</dd></div>{/each}</dl>
      {#each sourceStatuses as [provider, status]}<p>{provider}: {status}</p>{/each}
      {#each secondaryCoverage as [provider, coverage]}
        <p>{provider}: {coverage.matched_plays} corroborated play matches; {coverage.unmatched} primary plays not supplemented.</p>
        {#if coverage.primary_overtime_plays > coverage.matched_overtime_plays}
          <p>Overtime: primary ESPN plays retained. {provider} overtime context is incomplete; no missing period or possession is inferred.</p>
        {/if}
      {/each}
      {#if Object.values(sourceDetail.alignment ?? {}).some(value => value.clock_disagreement)}
        <p>The sources disagree on this play's clock. Other matching context corroborates the link; the primary clock is unchanged.</p>
      {/if}
      {#if sourceDetail.source_policy?.version}<p>Source policy: {sourceDetail.source_policy.version} · {sourceDetail.source_policy.feature}</p>
        <dl>{#each Object.entries(sourceDetail.source_policy.decisions ?? {}) as [field, decision]}
          <div><dt>{field.replaceAll('_', ' ')}</dt><dd>{decision.selected_provider ?? 'Unresolved'} · {decision.reason}</dd></div>
        {/each}</dl>
      {/if}
      {#if conflicts.length}<h4>Source disagreements — resolved by field policy</h4>
        <dl>{#each conflicts as [field, values]}<div><dt>{field.replaceAll('_', ' ')}</dt>
          <dd>{values.map(value => `${value.provider_id}: ${String(value.value)}`).join(' · ')}</dd></div>{/each}</dl>
      {/if}
      {#if event.resolution_version}<p>Resolution: {event.resolution_version}. Raw inputs and manifest IDs are retained with this snapshot.</p>{/if}
      {#if event.model_identity}<p>Current model bundle: {event.model_identity}. Secondary-source EPA/WPA are not substituted.</p>{/if}
    </details>
  {/if}
  {#if event.personnel_context?.entries?.length}
    <details class="play-details provider-context"><summary>Recorded Personnel Source Entries</summary>
      <pre>{JSON.stringify(event.personnel_context.entries, null, 2)}</pre>
    </details>
  {/if}
</FootballTablet>
<style>
  h4 {margin: 12px 20px;} p {color: var(--color-text-secondary);} .scope, .legend {font-size: 12px;} .legend {margin: 0; padding: 0 20px 12px;} ul {padding: 0 20px 0 40px;}
  .values {flex-wrap: wrap; gap: 16px;} li {margin: 5px 0; font-size: 13px;}
  .provider-context {margin: 12px 20px; border: 1px solid var(--line); border-radius: 6px; padding: 12px;}
  .provider-context summary {cursor: pointer; font-weight: 600;}
  .provider-context dd, pre {overflow-wrap: anywhere; white-space: pre-wrap;}
  .lineup-controls {margin: 12px 20px; padding: 12px 16px; border: 1px solid var(--line); border-radius: 6px;}
  .lineup-controls label {display: flex; align-items: center; gap: 8px; font-weight: 600; cursor: pointer;}
  .lineup-controls input {width: 16px; height: 16px; accent-color: var(--mint);}
  .lineup-controls p {margin: 8px 0 0; font-size: 12px; line-height: 1.5;}
  .identity-key {padding: 0 20px; line-height: 1.5;}
  .identity-source {font-size: 12px; color: var(--color-text-secondary);}
</style>
