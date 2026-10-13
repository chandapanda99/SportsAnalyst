<script lang="ts">
  import type {CFBParticipant, CFBRecordedPlay, CFBTeamContext} from './types';
  import {colorContrastRatio} from './teamPalettes';
  export let event: CFBRecordedPlay;
  export let teams: CFBTeamContext[] = [];
  let focused: string | null = null;
  const width = 160 / 3;
  const ticks = Array.from({length: 99}, (_, i) => 11 + i);
  const lines = Array.from({length: 19}, (_, i) => 15 + 5 * i);
  const numbers = Array.from({length: 9}, (_, i) => 20 + 10 * i);
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

<section class="cfb-play-tablet" aria-label={`College-football schematic for play ${event.id}`}>
  <header><h4>{event.play_type ?? 'Recorded play'} · Q{event.quarter ?? '?'} {event.clock ?? ''}</h4>
    <p>{event.down != null && event.down > 0 ? `${event.down} & ${event.distance ?? '?'}` : 'Down unavailable'} · {offense?.name ?? 'Possession team unavailable'}
      {#if event.yards_gained != null} · {event.yards_gained} recorded yards{/if}</p></header>
  <p class="scope">Recorded play context; actor locations are illustrative. No full lineup, formation, routes, or coverage assignments are implied.</p>
  <svg viewBox={`0 0 120 ${width}`} role="img" aria-label="College football field with recorded field position and illustrative involved-player markers">
    <rect width="120" height={width} fill="#2d7756"/>
    <rect width="10" height={width} fill={home?.color ?? '#142c3d'}/><rect x="110" width="10" height={width} fill={home?.color ?? '#142c3d'}/>
    <text transform={`translate(5 ${width / 2}) rotate(-90)`} text-anchor="middle" fill={textColor(home?.color ?? '#142c3d')} class="venue">{home?.abbreviation ?? 'HOME'}</text>
    <text transform={`translate(115 ${width / 2}) rotate(90)`} text-anchor="middle" fill={textColor(home?.color ?? '#142c3d')} class="venue">{home?.abbreviation ?? 'HOME'}</text>
    {#if home?.logo}<image href={home.logo} x="55" y={width / 2 - 5} width="10" height="10" opacity=".55"/>{/if}
    {#each lines as x}<line x1={x} x2={x} y1="0" y2={width} stroke="#ecfaf0" stroke-opacity=".35" stroke-width=".12"/>{/each}
    {#each ticks as x}{#each [0, 20, width - 20, width - .65] as y}<line x1={x} x2={x} y1={y} y2={y + .65} stroke="#ecfaf0" stroke-opacity=".6" stroke-width=".13"/>{/each}{/each}
    {#each numbers as x}{#each [10, width - 10] as y}<text x={x} {y} text-anchor="middle" fill="#e7f6ea" opacity=".65" class="yard">{Math.min(x - 10, 110 - x)}</text>{/each}{/each}
    <rect x=".2" y=".2" width="119.6" height={width - .4} fill="none" stroke="#f6fafa" stroke-width=".4"/>
    {#if los != null}<line x1={los} x2={los} y1="0" y2={width} stroke="#45b5ff" stroke-dasharray=".8 .6" stroke-width=".3"/>{/if}
    {#if target != null}<line x1={target} x2={target} y1="0" y2={width} stroke="#ffd061" stroke-dasharray=".8 .6" stroke-width=".3"/>{/if}
    {#if los != null && end != null}<line x1={los} x2={end} y1={width / 2 + 2} y2={width / 2 + 2} stroke="#eefbf7" stroke-width=".4" stroke-dasharray=".7 .4"/>
      <circle cx={end} cy={width / 2 + 2} r=".6" fill="#eefbf7"/>{/if}
    {#each markers as actor}
      <g role="button" tabindex="0" aria-label={label(actor)} on:mouseenter={() => focused = actor.athlete_id} on:mouseleave={() => focused = null}
         on:focus={() => focused = actor.athlete_id} on:blur={() => focused = null} on:click={() => focused = actor.athlete_id}
         on:keydown={(e) => {if (['Enter', ' '].includes(e.key)) {e.preventDefault(); focused = actor.athlete_id;}}}>
        <circle cx={actor.x} cy={actor.y} r="1.25" fill={color(actor)} stroke="#eefbf7" stroke-width=".1"/>
        <text x={actor.x} y={actor.y + .22} text-anchor="middle" fill={textColor(color(actor))} class="actor">{short(actor)}</text>
      </g>
    {/each}
    {#if focus}<g class="tooltip" pointer-events="none"><rect x="18" y=".9" width="84" height="3.7" rx=".5" fill="#061522" stroke="#b1e7df" stroke-width=".13"/>
      <text x="60" y="3.2" text-anchor="middle" fill="#effbf7">{label(focus).length > 110 ? `${label(focus).slice(0, 107)}…` : label(focus)}</text></g>{/if}
  </svg>
  <p class="legend">Blue: recorded starting field position · Gold: recorded distance to gain · White: recorded longitudinal start/end, not a route.
    Attack direction is normalized left-to-right; lateral position is not recorded. College hashes are 20 yards from each sideline.</p>
  <p>{event.text}</p>
  <div class="values"><span>Recorded score after play: {event.away_score ?? '—'}–{event.home_score ?? '—'} (away–home)</span>
    <span>Modeled EPA: {event.epa == null ? 'Not prepared/available' : event.epa.toFixed(3)}</span>
    <span>Spread-free WPA: {event.wpa == null ? 'Not prepared/available' : `${(event.wpa * 100).toFixed(2)} pp`}</span></div>
  <h4>Recorded involved players ({actors.length})</h4>
  {#if actors.length}<ul>{#each actors as actor}<li>{actor.name ?? `ESPN athlete ${actor.athlete_id}`} · {actor.roles.join(', ')}
    {#if actor.position} · {actor.position}{/if} · {teams.find(team => team.id === actor.team_id)?.name ?? 'School not verified'} · ESPN ID {actor.athlete_id}</li>{/each}</ul>
  {:else}<p>No participant IDs recorded for this play. This does not mean no players were on the field.</p>{/if}
</section>
<style>
  .cfb-play-tablet {border: 1px solid #315063; padding: 14px; margin-top: 16px; background: #071724;}
  h4 {margin: 6px 0;} p {color: #abc1cd;} .scope, .legend {font-size: 12px;} svg {display: block; width: 100%;}
  .venue {font-size: 2.8px; font-weight: 700;} .yard {font-size: 2.2px;} .actor {font-size: .65px; font-weight: 700;} .tooltip text {font-size: 1.15px;}
  .values {display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px;} li {margin: 5px 0; font-size: 13px;}
</style>
