import type {PlayVisualization, SpecialTeamsContext} from './types';
import type {PlaySchematic, SchematicMarker, SchematicPath, SchematicPlayer} from './playSchematic';
import {footballWidth} from './surfaceGeometry';

const middle = footballWidth / 2;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const spot = (value: unknown): value is number => finite(value) && value >= -10 && value <= 110;
const xFor = (value: number) => Math.max(.8, Math.min(119.2, 110 - value));
const names = {field_goal: 'Field goal', extra_point: 'Extra point', punt: 'Punt', kickoff: 'Kickoff'};

/** Structured fields take precedence; narrative fallback supports older saved reports. */
export function resolveSpecialTeams(v: PlayVisualization, text = ''): SpecialTeamsContext | undefined {
  const type = (v.play_type ?? '').toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ');
  const kind = v.special_teams?.kind ?? (/field goal/.test(type) ? 'field_goal' : /extra point|^pat$/.test(type) ? 'extra_point'
    : /punt/.test(type) ? 'punt' : /kickoff|kick off/.test(type) ? 'kickoff' : undefined);
  if (!kind || (/fake/.test(type) && /pass|rush|run/.test(type))) return;
  const data = v.special_teams ?? {kind};
  const distanceText = kind === 'field_goal' || kind === 'extra_point'
    ? text.match(/\b(\d+)\s*(?:yard|yd)\s+(?:field goal|fg|extra point)/i)
    : text.match(/\b(?:punts?|kicks?|kickoff)\s+(?:for\s+)?(\d+)\s*(?:yards?|yds?)/i);
  const returnText = text.match(/\breturn(?:ed|s)?\s+(?:for\s+)?(-?\d+)\s*(?:yards?|yds?)/i);
  const blocked = data.blocked ?? (/\bblocked\b/i.test(type + ' ' + text) || data.result === 'blocked');
  const result = data.result ?? (blocked ? 'blocked' : /\bno good\b|\bmiss(?:ed)?\b|\bfailed\b/i.test(type + ' ' + text) ? 'missed'
    : /\bgood\b|\bmade\b/i.test(type + ' ' + text) ? 'made' : undefined);
  const receiving = data.receiving_team ?? (kind === 'kickoff' && v.sport !== 'cfb' ? v.possession_team : v.defensive_team);
  const touchbackPlacement = text.match(/\btouchback\s+to\s+(?:the\s+)?([A-Z]{2,5})\s*(\d{1,2})\b/i);
  const placement = touchbackPlacement && receiving && touchbackPlacement[1].toUpperCase() === receiving.toUpperCase()
    && Number(touchbackPlacement[2]) <= 50 && !/penalty/i.test(text) ? Number(touchbackPlacement[2]) : undefined;
  return {...data, kind, result, blocked,
    no_play: data.no_play === true || /\bno play\b|play nullified/i.test(text),
    kicking_team: data.kicking_team ?? (kind === 'kickoff' && v.sport !== 'cfb' ? v.defensive_team : v.possession_team),
    receiving_team: receiving,
    end_yards_to_goal: data.end_yards_to_goal ?? placement,
    start_yards_to_goal: data.start_yards_to_goal ?? (spot(v.yardline_100)
      ? kind === 'kickoff' && v.sport !== 'cfb' ? 100 - v.yardline_100 : v.yardline_100 : undefined),
    kick_distance: data.kick_distance ?? (distanceText ? Number(distanceText[1]) : undefined),
    return_yards: data.return_yards ?? v.return_yards ?? (returnText ? Number(returnText[1]) : undefined),
    touchback: data.touchback ?? /\btouchback\b/i.test(type + ' ' + text),
    fair_catch: data.fair_catch ?? /\bfair catch\b/i.test(type + ' ' + text),
    out_of_bounds: data.out_of_bounds ?? /\bout of bounds\b/i.test(text),
    downed: data.downed ?? /\bdowned\b/i.test(text),
    onside: data.onside ?? /\bonside\b/i.test(type + ' ' + text),
    return_touchdown: data.return_touchdown ?? /return.*touchdown/i.test(type),
    source: data.source ?? 'Recorded play type and explicitly stated narrative distances/results'};
}

export function specialTeamsResult(kick: SpecialTeamsContext) {
  if (kick.no_play) return 'No play · attempt nullified';
  if (kick.blocked) return 'Blocked';
  if (kick.own_recovery) return 'Recovered by kicking team';
  if (kick.touchback) return 'Touchback';
  if (kick.fair_catch) return 'Fair catch';
  if (kick.out_of_bounds) return 'Out of bounds';
  if (kick.downed) return 'Downed';
  if (kick.return_touchdown) return 'Return touchdown';
  if (kick.onside) return 'Onside kick · recovery not recorded';
  if (/^(made|good|success|successful)$/i.test(kick.result ?? '')) return 'Good';
  if (/miss|fail|no good/i.test(kick.result ?? '')) return 'Missed';
  if (finite(kick.return_yards) && kick.return_yards !== 0) return `${kick.return_yards} yd return`;
  return 'Outcome not recorded';
}

/** A kick/return diagram, not an invented 22-player special-teams formation. */
export function buildSpecialTeamsSchematic(kick: SpecialTeamsContext, v: PlayVisualization, hashFromSideline: number): PlaySchematic {
  const known = spot(kick.start_yards_to_goal);
  const startX = known ? xFor(kick.start_yards_to_goal!) : 60;
  const originY = /^l/i.test(v.starting_hash ?? '') ? hashFromSideline : /^r/i.test(v.starting_hash ?? '') ? footballWidth - hashFromSideline : middle;
  const goalKick = kick.kind === 'field_goal' || kick.kind === 'extra_point';
  const distance = finite(kick.kick_distance) && kick.kick_distance >= 0 && kick.kick_distance <= 120 ? kick.kick_distance : undefined;
  // Goal-kick distance is measured to the posts, NOT from the scrimmage line.
  const launchX = goalKick && distance != null ? Math.max(.8, 120 - distance)
    : kick.kind === 'punt' ? Math.max(.8, startX - 14) : startX;
  let landing = spot(kick.landing_yards_to_goal) ? kick.landing_yards_to_goal : undefined;
  if (!goalKick && !kick.blocked && landing == null && known && distance != null && spot(kick.start_yards_to_goal! - distance)) {
    landing = kick.start_yards_to_goal! - distance;
  }
  const paths: SchematicPath[] = [], markers: SchematicMarker[] = [], players: SchematicPlayer[] = [];
  function actor(role: 'K' | 'P' | 'RET', name: string | null | undefined, x: number, y: number, side: 'offense' | 'defense') {
    players.push({id: `special-${role}`, name: name || role, label: name || role, position: role, side, x, y,
      recorded: Boolean(name), inferredPlacement: true, inBox: false, placementBasis: 'Recorded kick/return context; illustrative actor placement'});
  }
  const outcome = kick.no_play || kick.blocked ? specialTeamsResult(kick)
    : v.fumble_lost ? 'Fumble lost on return' : v.fumble ? 'Fumble on return' : specialTeamsResult(kick);
  if (!kick.no_play && (known || goalKick && distance != null)) {
    actor(kick.kind === 'punt' ? 'P' : 'K', kick.kicker, launchX, originY, 'offense');
    if (goalKick) {
      if (!kick.blocked && outcome === 'Good') {
        paths.push({id: 'kick', kind: 'kick', label: 'Illustrative kick to the goalposts',
          d: `M ${launchX} ${originY} Q ${(launchX + 119.2) / 2} ${originY - 5}, 119.2 ${middle}`, endX: 119.2, endY: middle});
        markers.push({kind: 'kick-result', label: outcome, x: 119.2, y: middle});
      } else {
        markers.push({kind: 'kick-result', label: `${outcome} · endpoint not recorded`, x: launchX, y: originY + 3});
      }
    } else if (!kick.blocked && landing != null) {
      const landingX = xFor(landing);
      if (Math.abs(landingX - startX) > .1) paths.push({id: 'kick', kind: 'kick', label: 'Illustrative kick flight',
        d: `M ${launchX} ${originY} Q ${(launchX + landingX) / 2} ${originY - 5}, ${landingX} ${originY}`, endX: landingX, endY: originY});
      markers.push({kind: 'kick-result', label: kick.touchback ? 'Kick endpoint · touchback' : kick.fair_catch ? 'Fair catch' : kick.out_of_bounds ? 'Out of bounds' : kick.downed ? 'Downed' : 'Kick endpoint', x: landingX, y: originY});
      if (kick.returner && !kick.touchback) actor('RET', kick.returner, landingX, originY + 3, 'defense');
      const canReturn = !kick.touchback && !kick.fair_catch && !kick.downed && !kick.out_of_bounds && !kick.own_recovery && !kick.onside;
      if (canReturn && finite(kick.return_yards) && kick.return_yards !== 0 && spot(landing + kick.return_yards)) {
        const returnX = xFor(landing + kick.return_yards);
        paths.push({id: 'kick-return', kind: 'return', label: `${kick.return_yards} yd kick return`,
          d: `M ${landingX} ${originY} Q ${(landingX + returnX) / 2} ${originY + 4}, ${returnX} ${originY + 2}`, endX: returnX, endY: originY + 2});
        markers.push({kind: v.fumble_lost ? 'turnover' : v.fumble ? 'recovery' : kick.return_touchdown ? 'touchdown' : 'kick-result', label: outcome, x: returnX, y: originY + 2});
      }
      if (kick.touchback && spot(kick.end_yards_to_goal)) {
        markers.push({kind: 'placement', label: 'Recorded touchback placement · not a return', x: xFor(kick.end_yards_to_goal), y: originY + 4});
      }
    } else {
      markers.push({kind: 'kick-result', label: `${outcome} · kick endpoint not recorded`, x: startX, y: originY + 3});
    }
  }
  return {startX, hashY: originY, lineToGainX: startX, players, paths, markers,
    lineupMode: players.every(player => player.recorded) ? 'recorded' : 'template',
    specialTeams: {kind: kick.kind, label: names[kick.kind], result: outcome, startKnown: known,
      note: kick.no_play ? 'Nullified attempt: no live kick or return is reconstructed.'
        : 'Kick and return symbols use recorded distances where available. Lateral placement and curves are illustrative; no full lineup or blocking assignments are inferred. '
          + (!known && distance == null ? 'Starting location is unavailable; no positioned movement is shown. ' : '')
          + (goalKick && outcome !== 'Good' ? 'Miss or block location is not inferred. ' : '')
          + (kick.kind === 'punt' ? 'Punter depth is illustrative; recorded punt distance is measured from scrimmage, not the punter icon. ' : '')
          + (kick.touchback ? 'Touchback placement is shown only when explicitly recorded; no season-specific rule is assumed.' : '')},
    context: {formation: 'Special teams', offensivePersonnel: 'Not reconstructed', defensivePersonnel: 'Not reconstructed',
      boxCount: 0, boxCountRecorded: false, passRusherCount: 0, passRusherCountRecorded: false,
      blitzerCount: 0, blitzerCountRecorded: false, coverage: 'Not reconstructed'}};
}
