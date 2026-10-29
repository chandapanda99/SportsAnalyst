export type SourceRecord = Record<string, unknown>;
export type PitchPoint = {x: number; y: number};
export type ShotDiagram = {outcome: 'goal' | 'saved' | 'blocked' | 'missed'; goal: {across: number; height: number} | null;
  intervention: PitchPoint | null; endpoint: PitchPoint | null; provider: string; id: string};
export type RecapEvent = {
  key: string; id: string; provider: string; kind: string; player: string; team: string; teamName: string;
  minute: number | null; second: number | null; period: number | null; sequence: number | null;
  possession: string; outcome: string; start: PitchPoint | null; end: PitchPoint | null;
  xg: number | null; xgot: number | null; xt: number | null; orientation: string;
  uncertainOrder: boolean; qualifiers: SourceRecord; index: number;
  shot: ShotDiagram | null;
};

export function shotDiagram(raw: SourceRecord, provider: string): ShotDiagram | null {
  if (provider !== 'fotmob') return null;
  const outcome = raw.isBlocked === true || /blocked/i.test(String(raw.eventType)) ? 'blocked' : raw.eventType === 'Goal' ? 'goal'
    : /saved/i.test(String(raw.eventType)) ? 'saved' : 'missed';
  const y = recordedNumber(raw.goalCrossedY), z = recordedNumber(raw.goalCrossedZ);
  // FotMob goal-plane metres: pitch centre y=34; posts at 34 ± 3.66.
  // Keep wide/high attempts outside the frame rather than clamping to the net.
  const goal = outcome !== 'blocked' && raw.isOwnGoal !== true && y !== null && z !== null
    && y >= 20 && y <= 48 && z >= 0 && z <= 12
    && (outcome !== 'goal' || (y >= 30.23 && y <= 37.77 && z <= 2.55)) ? {across: y - 30.34, height: z} : null;
  const intervention = (outcome === 'blocked' || outcome === 'saved') ? point(raw.blockedX, raw.blockedY) : null;
  return {outcome, goal, intervention, endpoint: intervention ?? (goal ? {x:105, y:y!} : null), provider, id:String(raw.id ?? '')};
}

export function recordedNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function point(x: unknown, y: unknown): PitchPoint | null {
  const px = recordedNumber(x), py = recordedNumber(y);
  return px !== null && py !== null && px >= 0 && px <= 105 && py >= 0 && py <= 68 ? {x: px, y: py} : null;
}

function probability(value: unknown): number | null {
  const number = recordedNumber(value);
  return number !== null && number >= 0 && number <= 1 ? number : null;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function array(value: unknown): SourceRecord[] {
  try {
    const result = JSON.parse(String(value ?? '[]'));
    return Array.isArray(result) ? result.filter(v => v && typeof v === 'object') : [];
  } catch {return [];}
}

function ordered(events: RecapEvent[]): RecapEvent[] {
  const sequenceKnown = events.length > 0 && events.every(e => e.sequence !== null)
    && new Set(events.map(e => e.sequence)).size === events.length;
  if (sequenceKnown) return events.sort((a, b) => a.sequence! - b.sequence!);
  // A minute-only event cannot be placed before/after a second-precision event
  // within that minute. Preserve source order and disclose the ambiguity.
  const groups = new Map<string, RecapEvent[]>();
  for (const event of events) {
    const key = `${event.period}:${event.minute}`;
    groups.set(key, [...(groups.get(key) ?? []), event]);
  }
  const periodsKnown = events.every(e => e.period !== null);
  return [...groups.values()].sort((a, b) =>
    (periodsKnown ? a[0].period! - b[0].period! : 0)
    || (a[0].minute ?? Infinity) - (b[0].minute ?? Infinity) || a[0].index - b[0].index)
    .flatMap(group => {
      const precise = group.every(e => e.second !== null);
      return group.sort((a, b) => precise ? a.second! - b.second! || a.index - b.index : a.index - b.index)
        .map(e => ({...e, uncertainOrder: group.length > 1 && (!precise
          || group.some(other => other !== e && other.second === e.second))}));
    });
}

export function recapSources(actions: SourceRecord[], analytics: SourceRecord[], timeline: SourceRecord[] = []): Map<string, RecapEvent[]> {
  const sources = new Map<string, RecapEvent[]>();
  function add(raw: SourceRecord, provider: string, shot: boolean, parent: SourceRecord = {}) {
    const events = sources.get(provider) ?? [];
    const index = events.length;
    const id = text(raw.id, `unidentified-${index}`);
    const event: RecapEvent = {
      key: `${provider}:${id}:${index}`, id, provider, index,
      kind: provider === 'fotmob' && shot ? ({goal:'Goal', saved:'Saved shot', blocked:'Blocked shot', missed:'Missed / other shot'}[shotDiagram(raw, provider)!.outcome]) : text(shot ? raw.eventType : raw.event_type, 'Event'),
      player: text(shot ? raw.playerName : raw.player_name, 'Not recorded'),
      team: text(shot ? raw.espn_team_id : raw.team_id, text(parent.team_id)),
      teamName: text(parent.team_name, text(raw.team_name, 'Recorded team')),
      minute: recordedNumber(shot ? raw.min : raw.minute), second: recordedNumber(raw.second),
      period: recordedNumber(raw.period) ?? (provider === 'fotmob' ? ({FirstHalf:1, SecondHalf:2, FirstExtra:3, SecondExtra:4}[String(raw.period)] ?? null) : null), sequence: recordedNumber(raw.sequence),
      possession: text(raw.possession), outcome: text(shot ? raw.eventType : raw.outcome, 'Not recorded'),
      start: point(shot ? raw.x : raw.start_x, shot ? raw.y : raw.start_y),
      end: shot ? null : point(raw.end_x, raw.end_y),
      xg: probability(shot ? raw.expectedGoals : raw.xg),
      xgot: probability(raw.expectedGoalsOnTarget), xt: recordedNumber(raw.xt),
      orientation: text(raw.coordinate_system, provider === 'statsbomb'
        ? 'Executing-team orientation, scaled from StatsBomb 120 × 80 to 105 × 68.'
        : provider === 'understat' ? 'Understat attacking-direction coordinates, scaled to 105 × 68.'
        : 'Provider event coordinates on 105 × 68; stadium attacking direction is unverified.'),
      uncertainOrder: false, qualifiers: shot ? {situation: raw.situation, body_part: raw.shotType} : raw,
      shot: shot ? shotDiagram(raw, provider) : null,
    };
    sources.set(provider, [...events, event]);
  }
  for (const action of actions) add(action, text(action.provider, 'statsbomb'), false);
  for (const row of analytics) {
    const provider = text(row.provider, 'fotmob');
    for (const shot of array(row.shots_json)) add(shot, provider, true, row);
  }
  for (const [index, event] of timeline.entries()) {
    const fx = recordedNumber(event.field_position_x), fy = recordedNumber(event.field_position_y);
    const side = event.side;
    const spatial = ['whoscored', 'fotmob'].includes(String(event.spatial_provider)) && event.spatial_event_id && event.spatial_context
      && typeof event.spatial_context === 'object' ? event.spatial_context as SourceRecord : {};
    const enrichedStart = point(spatial.start_x, spatial.start_y);
    const enrichedEnd = point(spatial.end_x, spatial.end_y);
    const valid = fx !== null && fy !== null && fx >= 0 && fx <= 2 && fy >= 0 && fy <= 1
      && (fx !== 0 || fy !== 0) && (side === 'home' || side === 'away');
    add({...event, id: event.id || `unidentified-timeline-${index}`,
      event_type: event.type, player_name: event.athlete_name, sequence: Number.isFinite(Number(event.sequence))
        && event.sequence != null && event.sequence !== '' ? Number(event.sequence) : index,
      minute: /^\d+/.test(text(event.clock)) ? Number(text(event.clock).match(/^\d+/)![0]) : null,
      start_x: valid ? side === 'home' ? 105 - 52.5 * fx : 52.5 * fx : enrichedStart?.x,
      start_y: valid ? side === 'home' ? 68 * (1 - fy) : 68 * fy : enrichedStart?.y,
      end_x: !valid && enrichedStart ? enrichedEnd?.x : null, end_y: !valid && enrichedStart ? enrichedEnd?.y : null,
      coordinate_system: !valid && enrichedStart ? spatial.coordinate_system : 'ESPN shot location relative to the attacked goal; home displayed attacking right, away left. Diagram convention, not tracked direction.',
      outcome: event.type}, 'espn', false);
    if (event.spatial_provider === 'fotmob' && spatial.shot && typeof spatial.shot === 'object') {
      const selected = sources.get('espn')!.at(-1)!;
      const raw = spatial.shot as SourceRecord;
      // Keep origin, goal plane, model values and orientation from one shot.
      selected.start = point(raw.x, raw.y);
      selected.shot = shotDiagram(raw, 'fotmob');
      selected.xg = probability(raw.expectedGoals);
      selected.xgot = probability(raw.expectedGoalsOnTarget);
      selected.orientation = 'FotMob shot diagram: normalized attacking goal at x=105 m. Static schematic, not tracked flight.';
      selected.qualifiers = {...selected.qualifiers, body_part:raw.shotType, situation:raw.situation};
    }
  }
  for (const [provider, events] of sources) sources.set(provider, ordered(events));
  return sources;
}

export function eventClock(event: RecapEvent): string {
  if (event.provider === 'espn' && event.qualifiers.clock) return text(event.qualifiers.clock);
  if (event.minute === null) return 'Time not recorded';
  return event.second === null ? `${event.minute}′ · minute precision`
    : `${event.minute}:${String(event.second).padStart(2, '0')}`;
}

export const sourceName = (value: string) => ({statsbomb: 'StatsBomb open data', understat: 'Understat', fotmob: 'FotMob',
  whoscored: 'WhoScored', espn: 'ESPN timeline'}[value] ?? value);

export function staticRecap(event: RecapEvent | undefined) {
  const description = text(event?.qualifiers.text);
  const kind = event?.kind.toLowerCase() ?? '';
  const category = /substitut|subbed/.test(kind) ? 'substitution' : /card/.test(kind) ? 'card'
    : /goal|scored/.test(kind) ? 'goal' : /shot|miss|save/.test(kind) ? 'shot' : 'event';
  const assist = description.match(/Assisted by ([^.]+)\./i)?.[1];
  // Only explicit shot-origin phrases establish a broad zone. Goal-mouth
  // phrases ("to the top left corner") never establish the shot's origin.
  const location = description.match(/from (?:the )?(centre|center|left side|right side) of the (six yard box|box)/i);
  let zone: {x: number; y: number; width: number; height: number; label: string} | null = null;
  if (location && (event?.qualifiers.side === 'home' || event?.qualifiers.side === 'away')) {
    const depth = /six/i.test(location[2]) ? 5.5 : 16.5;
    const width = /six/i.test(location[2]) ? 18.32 : 40.32;
    const home = event.qualifiers.side === 'home';
    const section = /left/i.test(location[1]) ? 0 : /right/i.test(location[1]) ? 2 : 1;
    zone = {x: home ? 105 - depth : 0, y: (68 - width) / 2 + (home ? section : 2 - section) * width / 3,
      width: depth, height: width / 3, label: location[0]};
  }
  return {category, assist, zone};
}
