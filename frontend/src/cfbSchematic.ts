import type {CFBRecordedPlay, CFBTeamContext, PlayVisualization} from './types';

export function collegeProviderContext(event: CFBRecordedPlay): Record<string, string | number | boolean> {
  try {
    const data = JSON.parse(event.provider_context_json || '{}');
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
    const result: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(data)) {
      if (typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) result[key] = value;
    }
    return result;
  } catch { return {}; }
}

/** Adapt recorded college inputs without promoting template choices to measured facts. */
export function adaptCollegePlay(event: CFBRecordedPlay, teams: CFBTeamContext[]) {
  const text = event.text ?? '';
  const kind = (event.play_type ?? '').toLowerCase();
  const provider = collegeProviderContext(event);
  const noPlay = event.no_play === true || provider.penalty_negated_play === true
    || provider.penalty_enforcement === 'no_play' || kind === 'penalty' || /\bno play\b|play nullified/i.test(text);
  const isPass = event.pass === true || /pass|sack|intercept/i.test(kind)
    || (event.participants ?? []).some(actor => ['passer', 'receiver'].includes(actor.role.toLowerCase()));
  const isRush = event.rush === true || /rush|\brun\b/i.test(kind)
    || (event.participants ?? []).some(actor => actor.role.toLowerCase() === 'rusher');
  const validPosition = event.yards_to_goal != null && event.yards_to_goal >= 0 && event.yards_to_goal <= 100;
  const specialTeams = /kickoff|punt|field goal|extra point|conversion|two.point/i.test(kind);
  const reconstruct = validPosition && !noPlay && !specialTeams && (isPass || isRush);
  const offense = teams.find(team => team.id === event.team_id);
  const defense = offense ? teams.find(team => team.id !== offense.id) : undefined;
  const offenseNames: string[] = [], offensePositions: string[] = [];
  const defenseNames: string[] = [], defensePositions: string[] = [];
  const seen = new Set<string>();
  const actors: Record<string, string> = {};
  for (const actor of event.participants ?? []) {
    const role = actor.role.toLowerCase();
    const name = actor.name || `ESPN athlete ${actor.athlete_id}`;
    const offensiveRole = ['passer', 'receiver', 'rusher'].includes(role);
    const defensiveRole = ['tackler', 'sacker', 'interceptor'].includes(role);
    actors[role] ??= name;
    if (seen.has(actor.athlete_id)) continue;
    const side = actor.team_id && offense && defense
      ? actor.team_id === offense.id ? 'offense' : actor.team_id === defense.id ? 'defense' : null
      : offensiveRole ? 'offense' : defensiveRole ? 'defense' : null;
    if (!side) continue;
    seen.add(actor.athlete_id);
    // Role-derived slots are schematic positions, not verified roster positions.
    const position = actor.position?.toUpperCase() || ({passer: 'QB', receiver: 'WR', rusher: 'RB', tackler: 'LB', sacker: 'DE', interceptor: 'DB'}[role] ?? (side === 'offense' ? 'WR' : 'DB'));
    (side === 'offense' ? offenseNames : defenseNames).push(name);
    (side === 'offense' ? offensePositions : defensePositions).push(position);
  }
  const gain = event.yards_gained ?? (validPosition && event.end_yards_to_goal != null && event.end_team_id === event.team_id
    ? event.yards_to_goal! - event.end_yards_to_goal : undefined);
  const visualization: PlayVisualization = {
    sport: 'cfb', yardline_100: validPosition ? event.yards_to_goal! : undefined,
    yards_to_go: event.distance ?? undefined, down: event.down ?? undefined,
    quarter: event.quarter ?? undefined, clock: event.clock ?? undefined,
    formation: event.formation ?? undefined, shotgun: /shotgun/i.test(event.formation ?? ''),
    play_type: isPass ? 'pass' : isRush ? 'run' : undefined,
    yards_gained: gain, passer: actors.passer, receiver: actors.receiver, rusher: actors.rusher,
    air_yards: event.air_yards ?? undefined, yards_after_catch: event.yards_after_catch ?? undefined,
    suppress_inferred_yac: event.yards_after_catch == null,
    pass_location: event.pass_direction ?? undefined, run_location: event.rush_direction ?? undefined,
    pass_length: event.pass_depth ?? undefined,
    sack: /sack/i.test(kind), interception: event.interception ?? /intercept/i.test(kind),
    complete_pass: event.complete ?? (/pass reception|pass completion|passing touchdown/i.test(kind)
      || (/\bcomplete(?:d)? to\b/i.test(text) && !/\bincomplete\b|intercept/i.test(text))),
    touchdown: event.touchdown ?? /touchdown/i.test(kind),
    pressure: typeof provider.qb_hurry === 'boolean' ? provider.qb_hurry : undefined,
    fumble: typeof provider.fumble_vec === 'boolean' ? provider.fumble_vec : undefined,
    fumble_lost: typeof provider.fumble_lost === 'boolean' ? provider.fumble_lost : undefined,
    turnover_player: actors.interceptor,
    offense_names: offenseNames, offense_positions: offensePositions,
    defense_names: defenseNames, defense_positions: defensePositions,
    possession_team: offense?.abbreviation ?? offense?.name ?? 'Offense',
    defensive_team: defense?.abbreviation ?? defense?.name ?? 'Defense',
  };
  const airYardsAvailable = event.air_yards != null && Number.isFinite(event.air_yards);
  const yardsAfterCatchAvailable = event.yards_after_catch != null && Number.isFinite(event.yards_after_catch);
  const returnYards = typeof provider.yds_int_return === 'number' && provider.yds_int_return >= 0 ? provider.yds_int_return : undefined;
  const verifiedInterceptionPath = visualization.interception && airYardsAvailable && returnYards != null;
  if (verifiedInterceptionPath) visualization.return_yards = returnYards;
  const movement = reconstruct && (gain != null || airYardsAvailable) && !visualization.fumble_lost
    && (verifiedInterceptionPath || (!visualization.interception && !event.turnover));
  return {visualization, reconstruct, movement,
    inference: {lineup: reconstruct, alignment: reconstruct, box: reconstruct, rushAssignments: reconstruct,
      trajectory: movement, airYardsAvailable, yardsAfterCatchAvailable},
    note: noPlay ? 'Nullified or penalty-only play: no live-play trajectory or lineup is reconstructed.'
      : !validPosition ? 'Starting field position is unavailable: no lineup or trajectory is reconstructed.'
        : !reconstruct ? 'Special-teams or unclassified play: no scrimmage formation is assumed.'
          : 'Illustrative reconstruction: unrecorded players use generic formation slots. Alignment, box and rush assignments are inferred, not tracking data. Role-based positions are schematic. '
            + (airYardsAvailable ? 'Pass distance uses provider-derived air yards from the recorded catch/target spot.' : 'Air yards are unavailable; movement uses net yards, not a measured catch location.')
            + (yardsAfterCatchAvailable ? ' After-catch distance uses provider-derived YAC.' : ' Yards after catch are unavailable.')
            + ' Lateral coordinates and curve shapes remain illustrative.'
            + (!movement ? ' No trajectory is shown because the endpoint or turnover path cannot be established.' : '')};
}
