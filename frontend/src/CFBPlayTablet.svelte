<script lang="ts">
  import type {CFBParticipant, CFBRecordedPlay, CFBTeamContext} from './types';
  import {colorContrastRatio} from './teamPalettes';
  import FootballField from './FootballField.svelte';
  import FootballTablet from './FootballTablet.svelte';
  import FootballTooltip from './FootballTooltip.svelte';
  export let event: CFBRecordedPlay;
  export let teams: CFBTeamContext[] = [];
  let focused: string | null = null;
  const width = 160 / 3;
  $: home = teams.find(team => team.side === 'home');
  $: offense = teams.find(team => team.id === event.team_id);
  $: los = coordinate(event.yards_to_goal);
  $: end = event.end_yards_to_goal == null || !event.team_id || !event.end_team_id ? null
      : event.team_id === event.end_team_id ? coordinate(event.end_yards_to_goal) : 120 - (coordinate(event.end_yards_to_goal) ?? 60);
  $: target = los == null || event.distance == null || event.distance < 0 ? null : Math.min(110, los + event.distance);
  $: actors = involved(event.participants ?? []);
  $: markers = actors.map((actor, i) => ({...actor, x: Math.max(12, Math.min(108,
      (los ?? 60) + (actor.roles.includes('passer') ? -5 : actor.roles.includes('rusher') ? -9 : actor.roles.includes('receiver') ? -1 : 4))),
      y: actor.roles.includes('passer') ? width / 2 : 6 + i * (width - 12) / Math.max(1, actors.length - 1)}));
  $: focus = markers.find(actor => actor.athlete_id === focused);
  $: if (event.id) focused = null;
  function coordinate(value: number | null | undefined) { return value != null && value >= 0 && value <= 100 ? 110 - value : null; }
  function involved(participants: CFBParticipant[]) {
    const unique = new Map<string, CFBParticipant & {roles: string[]}>();
    for (const actor of participants) {
      const existing = unique.get(actor.athlete_id);
      if (existing) { if (!existing.roles.includes(actor.role)) existing.roles.push(actor.role); }
      else unique.set(actor.athlete_id, {...actor, roles: [actor.role]});
    }
    return [...unique.values()];
  }
  function color(actor: CFBParticipant) { return teams.find(team => team.id === actor.team_id)?.color ?? '#536575'; }
  function textColor(background: string) { return colorContrastRatio(background, '#ffffff') >= 4.5 ? '#ffffff' : '#07121d'; }
  function label(actor: CFBParticipant & {roles: string[]}) {
    return `${actor.name ?? `ESPN athlete ${actor.athlete_id}`} · ${actor.position ?? actor.roles.join('/')} · illustrative placement`;
  }
  function short(actor: CFBParticipant & {roles: string[]}) { return actor.position ?? actor.roles[0].slice(0, 3).toUpperCase(); }
</script>

<FootballTablet label={`College-football schematic for play ${event.id}`}>
  <header><div><span>PLAY-BY-PLAY SCHEMATIC</span><h3>{event.play_type ?? 'Recorded play'} · Q{event.quarter ?? '?'} {event.clock ?? ''}</h3>
    <p>{event.down != null && event.down > 0 ? `${event.down} & ${event.distance ?? '?'}` : 'Down unavailable'} · {offense?.name ?? 'Possession team unavailable'}
      {#if event.yards_gained != null} · {event.yards_gained} recorded yards{/if}</p></div><div class="tablet-actions"><span>Recorded Play Context</span></div></header>
  <p class="scope reconstruction-meta">Recorded play context; actor locations are illustrative. No full lineup, formation, routes, or coverage assignments are implied.</p>
  <p class="scope">Formation: {event.formation ?? 'Not recorded in this play narrative'}
    {#if event.formation_source} · {event.formation_source}{/if}. A formation label does not establish exact alignment.</p>
  {#if event.personnel_context}
    <p class="scope">Personnel source: {event.personnel_context.status.replaceAll('_', ' ')}
      {#if event.personnel_context.entries?.length} · {event.personnel_context.entries.length} recorded entries{/if}.
      {event.personnel_context.scope}</p>
  {/if}
  <div class="field-wrap">
  <FootballField venueName={home?.name ?? home?.abbreviation ?? "Home"} venueAbbreviation={home?.abbreviation ?? "HOME"} venueLogo={home?.logo ?? null}
    primary={home?.color ?? "#142c3d"} secondary="#edf7ff" textColor={textColor(home?.color ?? "#142c3d")} hashFromSideline={20}
    label="College football field with recorded field position and illustrative involved-player markers">
    {#if los != null}<line x1={los} x2={los} y1="0" y2={width} stroke="#45b5ff" stroke-dasharray=".8 .6" stroke-width=".3"/>{/if}
    {#if target != null}<line x1={target} x2={target} y1="0" y2={width} stroke="#ffd061" stroke-dasharray=".8 .6" stroke-width=".3"/>{/if}
    {#if los != null && end != null}<line x1={los} x2={end} y1={width / 2 + 2} y2={width / 2 + 2} stroke="#eefbf7" stroke-width=".4" stroke-dasharray=".7 .4"/>
      <circle cx={end} cy={width / 2 + 2} r=".6" fill="#eefbf7"/>{/if}
    {#each markers as actor}
      <g class="field-player" role="button" tabindex="0" aria-label={label(actor)} on:mouseenter={() => focused = actor.athlete_id} on:mouseleave={() => focused = null}
         on:focus={() => focused = actor.athlete_id} on:blur={() => focused = null} on:click={() => focused = actor.athlete_id}
         on:keydown={(e) => {if (['Enter', ' '].includes(e.key)) {e.preventDefault(); focused = actor.athlete_id;}}}>
        <circle cx={actor.x} cy={actor.y} r="1.42" fill={color(actor)} stroke="#eefbf7" stroke-width=".1"/>
        <text x={actor.x} y={actor.y + .22} text-anchor="middle" fill={textColor(color(actor))} class="actor">{short(actor)}</text>
      </g>
    {/each}
    {#if focus}<FootballTooltip label={label(focus)} x={focus.x} y={focus.y}/>{/if}
  </FootballField>
  </div>
  <p class="legend field-legend">Blue: recorded starting field position · Gold: recorded distance to gain · White: recorded longitudinal start/end, not a route.
    Attack direction is normalized left-to-right; lateral position is not recorded. College hashes are 20 yards from each sideline.</p>
  <div class="play-details"><p>{event.text}</p></div>
  <div class="values situation"><span>Recorded score after play: {event.away_score ?? '—'}–{event.home_score ?? '—'} (away–home)</span>
    <span>Modeled EPA: {event.epa == null ? 'Not prepared/available' : event.epa.toFixed(3)}</span>
    <span>Spread-free WPA: {event.wpa == null ? 'Not prepared/available' : `${(event.wpa * 100).toFixed(2)} pp`}</span></div>
  <h4>Recorded involved players ({actors.length})</h4>
  {#if actors.length}<ul>{#each actors as actor}<li>{actor.name ?? `ESPN athlete ${actor.athlete_id}`} · {actor.roles.join(', ')}
    {#if actor.position} · {actor.position}{/if} · {teams.find(team => team.id === actor.team_id)?.name ?? 'School not verified'} · ESPN ID {actor.athlete_id}</li>{/each}</ul>
  {:else}<p>No participant IDs recorded for this play. This does not mean no players were on the field.</p>{/if}
</FootballTablet>
<style>
  h4 {margin: 12px 20px;} p {color: var(--color-text-secondary);} .scope, .legend {font-size: 12px;} .legend {margin: 0; padding: 0 20px 12px;} ul {padding: 0 20px 0 40px;}
  .actor {font-size: .65px; font-weight: 700;}
  .values {flex-wrap: wrap; gap: 16px;} li {margin: 5px 0; font-size: 13px;}
</style>
