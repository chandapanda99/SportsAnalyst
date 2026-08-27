import type {PlayVisualization} from './types';

export type SchematicPlayer = {
  id: string;
  name: string;
  label: string;
  position: string;
  side: 'offense' | 'defense';
  x: number;
  y: number;
  recorded: boolean;
};

export type SchematicPath = {
  id: string;
  d: string;
  kind: 'pass' | 'carry' | 'after-catch' | 'return';
  label: string;
  endX: number;
  endY: number;
};

export type SchematicMarker = {
  kind: 'catch' | 'turnover' | 'recovery' | 'touchdown';
  label: string;
  x: number;
  y: number;
};

export type PlaySchematic = {
  startX: number;
  lineToGainX: number;
  hashY: number;
  players: SchematicPlayer[];
  paths: SchematicPath[];
  markers: SchematicMarker[];
  lineupMode: 'recorded' | 'template';
};

const FIELD_MIN = 10;
const FIELD_MAX = 110;
const FIELD_MIDDLE = 26.65;

const clamp = (value: number, minimum = FIELD_MIN, maximum = FIELD_MAX) =>
  Math.max(minimum, Math.min(maximum, value));

function hashY(value?: string) {
  const normalized = value?.trim().toLowerCase() ?? '';
  if (normalized.startsWith('l')) return 18;
  if (normalized.startsWith('r')) return 35.3;
  return FIELD_MIDDLE;
}

function targetY(location?: string, origin = FIELD_MIDDLE) {
  const normalized = location?.trim().toLowerCase() ?? '';
  if (normalized === 'left') return 10;
  if (normalized === 'right') return 43.3;
  return origin;
}

function shortName(name: string, position: string) {
  const clean = name.trim();
  if (!clean) return position;
  const pieces = clean.split(/\s+/);
  const compact = pieces.length > 1 ? pieces.at(-1)! : clean;
  return compact.length > 10 ? `${compact.slice(0, 9)}…` : compact;
}

function normalizedPosition(position: string) {
  const value = position.toUpperCase().replace(/[^A-Z]/g, '');
  if (value === 'OT') return 'T';
  if (value === 'OG') return 'G';
  if (['LT', 'LG', 'C', 'RG', 'RT', 'OL', 'G', 'T'].includes(value)) return value;
  if (['QB'].includes(value)) return 'QB';
  if (['RB', 'HB', 'FB'].includes(value)) return value;
  if (['TE'].includes(value)) return 'TE';
  if (['WR'].includes(value)) return 'WR';
  if (['DT', 'NT', 'DE', 'DL', 'EDGE'].includes(value)) return value;
  if (['LB', 'ILB', 'OLB', 'MLB'].includes(value)) return value;
  if (['CB', 'DB', 'S', 'FS', 'SS'].includes(value)) return value;
  return value || '—';
}

function playerRecords(names: string[] = [], positions: string[] = []) {
  return names.map((name, index) => ({name, position: normalizedPosition(positions[index] ?? '—')}));
}

function genericOffense(visualization: PlayVisualization) {
  const formation = visualization.formation?.toLowerCase() ?? '';
  const spread = formation.includes('empty') || formation.includes('shotgun');
  const positions = spread
    ? ['LT', 'LG', 'C', 'RG', 'RT', 'QB', 'WR', 'WR', 'WR', 'WR', 'TE']
    : ['LT', 'LG', 'C', 'RG', 'RT', 'QB', 'RB', 'WR', 'WR', 'TE', formation.includes('i form') ? 'FB' : 'WR'];
  return positions.map((position, index) => ({name: position, position, genericIndex: index}));
}

function genericDefense(visualization: PlayVisualization) {
  const box = visualization.defenders_in_box ?? visualization.defense_box_count ?? 7;
  const front = Math.max(3, Math.min(5, Math.round(box * 0.58)));
  const positions = [
    ...Array.from({length: front}, () => 'DL'),
    ...Array.from({length: Math.max(2, box - front)}, () => 'LB'),
    ...Array.from({length: Math.max(0, 11 - box)}, (_, index) => index < 2 ? 'CB' : 'S'),
  ].slice(0, 11);
  return positions.map((position, index) => ({name: position, position, genericIndex: index}));
}

function distribute(index: number, total: number, minimum: number, maximum: number) {
  return total <= 1 ? (minimum + maximum) / 2 : minimum + index * ((maximum - minimum) / (total - 1));
}

function placeOffensiveLine(
  records: Array<{name: string; position: string}>,
  startX: number,
  centerY: number,
) {
  const positions = [
    {position: 'LT', y: centerY - 10},
    {position: 'LG', y: centerY - 5},
    {position: 'C', y: centerY},
    {position: 'RG', y: centerY + 5},
    {position: 'RT', y: centerY + 10},
  ];
  const assigned = new Map<number, {name: string; position: string}>();
  const remaining: Array<{name: string; position: string}> = [];
  const exactSlots: Record<string, number> = {LT: 0, LG: 1, C: 2, RG: 3, RT: 4};

  for (const record of records) {
    const exact = exactSlots[record.position];
    if (exact != null && !assigned.has(exact)) assigned.set(exact, record);
    else remaining.push(record);
  }
  for (const record of remaining) {
    const preferences = record.position === 'T' ? [0, 4] : record.position === 'G' ? [1, 3] : [2, 1, 3, 0, 4];
    const slot = preferences.find(index => !assigned.has(index));
    if (slot != null) assigned.set(slot, record);
  }
  return [...assigned.entries()]
    .sort(([left], [right]) => left - right)
    .map(([slot, record]) => ({record, x: startX - .7, y: positions[slot].y}));
}

function placeOffense(
  records: Array<{name: string; position: string}>,
  startX: number,
  centerY: number,
  recorded: boolean,
): SchematicPlayer[] {
  const groups = new Map<string, Array<{name: string; position: string}>>();
  for (const record of records) {
    const group = ['LT', 'LG', 'C', 'RG', 'RT', 'OL', 'G', 'T'].includes(record.position) ? 'OL'
      : ['RB', 'HB', 'FB'].includes(record.position) ? 'BACK'
      : record.position;
    groups.set(group, [...(groups.get(group) ?? []), record]);
  }
  const slots: Array<{record: {name: string; position: string}; x: number; y: number}> = [];
  const line = groups.get('OL') ?? [];
  slots.push(...placeOffensiveLine(line, startX, centerY));
  (groups.get('QB') ?? []).forEach((record, index) => slots.push({record, x: startX - 4.6 - index * 1.5, y: centerY}));
  const backs = groups.get('BACK') ?? [];
  backs.forEach((record, index) => slots.push({record, x: startX - 8, y: distribute(index, backs.length, centerY - 4, centerY + 4)}));
  const receivers = groups.get('WR') ?? [];
  const receiverYs = [5.5, 47.8, 13, 40.3, 19, 34.3];
  receivers.forEach((record, index) => slots.push({record, x: startX - (index > 1 ? 2.2 : .8), y: receiverYs[index] ?? distribute(index, receivers.length, 5.5, 47.8)}));
  const tightEnds = groups.get('TE') ?? [];
  tightEnds.forEach((record, index) => slots.push({record, x: startX - .8, y: index % 2 ? centerY + 12 : centerY - 12}));
  const assigned = new Set(slots.map(({record}) => record));
  records.filter(record => !assigned.has(record)).forEach((record, index) =>
    slots.push({record, x: startX - 5.5, y: distribute(index, records.length, 8, 45.3)}));
  return slots.map(({record, x, y}, index) => ({
    id: `offense-${index}`, name: record.name, label: shortName(record.name, record.position), position: record.position,
    side: 'offense', x: clamp(x, 2, 117), y, recorded,
  }));
}

function placeDefense(
  records: Array<{name: string; position: string}>,
  startX: number,
  centerY: number,
  recorded: boolean,
): SchematicPlayer[] {
  const fronts = records.filter(record => ['DT', 'NT', 'DE', 'DL', 'EDGE'].includes(record.position));
  const linebackers = records.filter(record => ['LB', 'ILB', 'OLB', 'MLB'].includes(record.position));
  const backs = records.filter(record => ['CB', 'DB', 'S', 'FS', 'SS'].includes(record.position));
  const assigned = new Set([...fronts, ...linebackers, ...backs]);
  const slots: Array<{record: {name: string; position: string}; x: number; y: number}> = [];
  fronts.forEach((record, index) => slots.push({record, x: startX + 1.5, y: distribute(index, fronts.length, centerY - 11, centerY + 11)}));
  linebackers.forEach((record, index) => slots.push({record, x: startX + 5.5, y: distribute(index, linebackers.length, centerY - 13, centerY + 13)}));
  backs.forEach((record, index) => {
    const isSafety = ['S', 'FS', 'SS'].includes(record.position);
    slots.push({record, x: startX + (isSafety ? 13 : 8), y: isSafety ? distribute(index, backs.length, 14, 39.3) : distribute(index, backs.length, 5, 48.3)});
  });
  records.filter(record => !assigned.has(record)).forEach((record, index) =>
    slots.push({record, x: startX + 7, y: distribute(index, records.length, 7, 46.3)}));
  return slots.map(({record, x, y}, index) => ({
    id: `defense-${index}`, name: record.name, label: shortName(record.name, record.position), position: record.position,
    side: 'defense', x: clamp(x, 2, 117), y, recorded,
  }));
}

function curve(startX: number, startY: number, endX: number, endY: number, bend = 0) {
  const controlX = startX + (endX - startX) * .52;
  const controlY = startY + (endY - startY) * .35 + bend;
  return `M ${startX} ${startY} Q ${controlX} ${controlY}, ${endX} ${endY}`;
}

function buildPaths(visualization: PlayVisualization, startX: number, originY: number) {
  const paths: SchematicPath[] = [];
  const markers: SchematicMarker[] = [];
  const location = visualization.pass_location ?? visualization.run_location;
  const destinationY = targetY(location, originY);
  const gain = visualization.yards_gained ?? 0;
  const finalX = clamp(startX + gain, 1.5, 118.5);
  const isPass = visualization.play_type === 'pass' || visualization.air_yards != null || Boolean(visualization.passer);

  if (isPass && !visualization.sack) {
    const airDistance = visualization.air_yards ?? gain;
    const exchangeX = clamp(startX + airDistance, 1.5, 118.5);
    paths.push({id: 'flight', d: curve(startX, originY, exchangeX, destinationY, -4), kind: 'pass', label: visualization.interception ? 'Pass to interception' : 'Ball flight', endX: exchangeX, endY: destinationY});
    if (visualization.interception) {
      markers.push({kind: 'turnover', label: visualization.turnover_player ? `INT · ${visualization.turnover_player}` : 'Interception', x: exchangeX, y: destinationY});
      const returnX = clamp(exchangeX - (visualization.return_yards ?? 0), 1.5, 118.5);
      if ((visualization.return_yards ?? 0) > 0) {
        paths.push({id: 'return', d: curve(exchangeX, destinationY, returnX, FIELD_MIDDLE, 4), kind: 'return', label: `${visualization.return_yards} yd return`, endX: returnX, endY: FIELD_MIDDLE});
      }
    } else if (visualization.complete_pass) {
      markers.push({kind: 'catch', label: visualization.receiver ? `Catch · ${visualization.receiver}` : 'Catch', x: exchangeX, y: destinationY});
      if (Math.abs(finalX - exchangeX) > .6) {
        paths.push({id: 'after-catch', d: curve(exchangeX, destinationY, finalX, destinationY + (destinationY < FIELD_MIDDLE ? -2 : 2)), kind: 'after-catch', label: `${visualization.yards_after_catch ?? Math.round(finalX - exchangeX)} YAC`, endX: finalX, endY: destinationY + (destinationY < FIELD_MIDDLE ? -2 : 2)});
      }
    }
  } else {
    const carrierStartX = visualization.sack ? startX - 4.6 : startX - 6.5;
    paths.push({id: 'carry', d: curve(carrierStartX, originY, finalX, destinationY, 2), kind: 'carry', label: visualization.sack ? 'QB movement' : 'Run path', endX: finalX, endY: destinationY});
  }

  const last = paths.at(-1);
  if (visualization.fumble && last) {
    markers.push({kind: visualization.fumble_lost ? 'turnover' : 'recovery', label: visualization.fumble_lost ? 'Fumble lost' : 'Fumble', x: last.endX, y: last.endY});
    if (visualization.recovery_player || visualization.recovery_team) {
      markers.push({kind: 'recovery', label: `Recovered · ${visualization.recovery_player ?? visualization.recovery_team}`, x: last.endX + 1.2, y: last.endY + 3});
    }
  }
  if (visualization.touchdown && last) {
    markers.push({kind: 'touchdown', label: 'Touchdown', x: last.endX, y: last.endY});
  }
  return {paths, markers};
}

export function buildPlaySchematic(visualization: PlayVisualization = {}): PlaySchematic {
  const startX = clamp(10 + (100 - (visualization.yardline_100 ?? 50)));
  const centerY = hashY(visualization.starting_hash);
  const offenseRecorded = playerRecords(visualization.offense_names, visualization.offense_positions);
  const defenseRecorded = playerRecords(visualization.defense_names, visualization.defense_positions);
  const recorded = offenseRecorded.length > 0 || defenseRecorded.length > 0;
  const offense = offenseRecorded.length ? offenseRecorded : genericOffense(visualization);
  const defense = defenseRecorded.length ? defenseRecorded : genericDefense(visualization);
  const {paths, markers} = buildPaths(visualization, startX, centerY);
  return {
    startX,
    lineToGainX: clamp(startX + (visualization.yards_to_go ?? 0)),
    hashY: centerY,
    players: [
      ...placeOffense(offense, startX, centerY, offenseRecorded.length > 0),
      ...placeDefense(defense, startX, centerY, defenseRecorded.length > 0),
    ],
    paths,
    markers,
    lineupMode: recorded ? 'recorded' : 'template',
  };
}
