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
  inferredPlacement: boolean;
  inBox: boolean;
  rushRole?: 'rusher' | 'blitzer';
  placementBasis: string;
};

type PlayerRecord = {
  name: string;
  position: string;
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
  lineupMode: 'recorded' | 'hybrid' | 'template';
  context: {
    formation: string;
    offensivePersonnel: string;
    defensivePersonnel: string;
    boxCount: number;
    boxCountRecorded: boolean;
    passRusherCount: number;
    passRusherCountRecorded: boolean;
    blitzerCount: number;
    blitzerCountRecorded: boolean;
    coverage: string;
  };
};

export const FOOTBALL_FIELD_WIDTH = 160 / 3;
export const NFL_HASH_FROM_SIDELINE = (70 + 9 / 12) / 3;
const FIELD_MIN = 10;
const FIELD_MAX = 110;
const FIELD_MIDDLE = FOOTBALL_FIELD_WIDTH / 2;
export const OFFENSIVE_LINE_HALF_WIDTH = 7.2;

const clamp = (value: number, minimum = FIELD_MIN, maximum = FIELD_MAX) =>
  Math.max(minimum, Math.min(maximum, value));

function hashY(value?: string) {
  const normalized = value?.trim().toLowerCase() ?? '';
  if (normalized.startsWith('l')) return NFL_HASH_FROM_SIDELINE;
  if (normalized.startsWith('r')) return FOOTBALL_FIELD_WIDTH - NFL_HASH_FROM_SIDELINE;
  return FIELD_MIDDLE;
}

function targetY(location?: string, origin = FIELD_MIDDLE) {
  const normalized = location?.trim().toLowerCase() ?? '';
  if (normalized === 'left') return 10;
  if (normalized === 'right') return FOOTBALL_FIELD_WIDTH - 10;
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
  if (['CB', 'DB', 'NB', 'S', 'FS', 'SS'].includes(value)) return value;
  return value || '—';
}

function playerRecords(names: string[] = [], positions: string[] = []) {
  return names.map((name, index) => ({name, position: normalizedPosition(positions[index] ?? '—'), recorded: true}));
}

type PositionCounts = Record<string, number>;

function formationKey(visualization: PlayVisualization) {
  const value = (visualization.formation ?? visualization.qb_location ?? '').trim().toUpperCase().replace(/[ -]+/g, '_');
  if (value.includes('EMPTY')) return 'EMPTY';
  if (value.includes('I_FORM') || value === 'I') return 'I_FORM';
  if (value.includes('SINGLEBACK') || value.includes('SINGLE_BACK')) return 'SINGLEBACK';
  if (value.includes('PISTOL') || value === 'P') return 'PISTOL';
  if (value.includes('JUMBO')) return 'JUMBO';
  if (value.includes('WILDCAT')) return 'WILDCAT';
  if (value.includes('SHOTGUN') || ['S', 'SG'].includes(value) || visualization.shotgun) return 'SHOTGUN';
  if (value.includes('UNDER_CENTER') || ['U', 'UC'].includes(value)) return 'UNDER_CENTER';
  return 'UNKNOWN';
}

export function describeFormation(visualization: PlayVisualization) {
  const labels: Record<string, string> = {
    EMPTY: 'Empty shotgun', I_FORM: 'I formation', SINGLEBACK: 'Singleback', PISTOL: 'Pistol',
    JUMBO: 'Jumbo', WILDCAT: 'Wildcat', SHOTGUN: 'Shotgun', UNDER_CENTER: 'Under center', UNKNOWN: 'Not recorded',
  };
  return labels[formationKey(visualization)];
}

export function describeHash(value?: string) {
  const normalized = value?.trim().toUpperCase() ?? '';
  if (normalized.startsWith('L')) return 'Left hash';
  if (normalized.startsWith('R')) return 'Right hash';
  if (normalized.startsWith('C') || normalized.includes('MIDDLE')) return 'Middle of field';
  return 'Hash not recorded';
}

export function describeQbAlignment(visualization: PlayVisualization) {
  const value = (visualization.qb_location ?? '').trim().toUpperCase().replace(/[ -]+/g, '_');
  if (value.includes('SHOTGUN') || ['S', 'SG'].includes(value)) return 'Shotgun';
  if (value.includes('PISTOL') || value === 'P') return 'Pistol';
  if (value.includes('UNDER_CENTER') || ['U', 'UC'].includes(value)) return 'Under center';
  if (visualization.shotgun) return 'Shotgun';
  return 'QB alignment not recorded';
}

export function describeCoverage(visualization: PlayVisualization) {
  const shell = (visualization.coverage_type ?? '').trim().replaceAll('_', ' ').toLowerCase()
    .replace(/\b\w/g, letter => letter.toUpperCase());
  const family = (visualization.man_zone ?? '').trim().toUpperCase();
  const familyLabel = family.includes('MAN') ? 'Man' : family.includes('ZONE') ? 'Zone' : '';
  return [shell, familyLabel].filter(Boolean).join(' · ') || 'Not recorded';
}

function explicitPositionCounts(value?: string): PositionCounts {
  const counts: PositionCounts = {};
  const text = value?.trim().toUpperCase() ?? '';
  for (const match of text.matchAll(/(\d+)\s*(DL|DB|LB|WR|TE|RB|HB|FB|OL|QB)\b/g)) {
    const position = ['HB', 'FB'].includes(match[2]) ? 'RB' : match[2];
    counts[position] = (counts[position] ?? 0) + Number(match[1]);
  }
  return counts;
}

function offensivePersonnelCounts(value?: string): PositionCounts {
  const text = value?.trim().toUpperCase() ?? '';
  const compact = text.match(/^(\d)(\d)(?:\s*(?:PERSONNEL|PERS))?$/);
  if (compact) {
    const rb = Number(compact[1]);
    const te = Number(compact[2]);
    return {RB: rb, TE: te, WR: Math.max(0, 5 - rb - te)};
  }
  return explicitPositionCounts(value);
}

function countsLabel(counts: PositionCounts, order: string[]) {
  return order.filter(position => counts[position] != null)
    .map(position => `${counts[position]} ${position}`)
    .join(', ');
}

export function describeOffensivePersonnel(value?: string) {
  const counts = offensivePersonnelCounts(value);
  const compact = value?.trim().match(/^(\d)(\d)/);
  if (!Object.keys(counts).length) return 'Not recorded';
  const detail = countsLabel(counts, ['OL', 'RB', 'TE', 'WR']);
  return compact ? `${compact[1]}${compact[2]} personnel · ${detail}` : detail;
}

export function describeDefensivePersonnel(value?: string) {
  const counts = explicitPositionCounts(value);
  return Object.keys(counts).length ? countsLabel(counts, ['DL', 'LB', 'DB']) : 'Not recorded';
}

function genericOffense(visualization: PlayVisualization) {
  const formation = formationKey(visualization);
  const recordedCounts = offensivePersonnelCounts(visualization.personnel);
  const defaults: Record<string, PositionCounts> = {
    EMPTY: {OL: 5, QB: 1, RB: 0, TE: 1, WR: 4},
    I_FORM: {OL: 5, QB: 1, RB: 2, TE: 1, WR: 2},
    JUMBO: {OL: 6, QB: 1, RB: 1, TE: 2, WR: 1},
    SHOTGUN: {OL: 5, QB: 1, RB: 1, TE: 1, WR: 3},
    PISTOL: {OL: 5, QB: 1, RB: 1, TE: 1, WR: 3},
    SINGLEBACK: {OL: 5, QB: 1, RB: 1, TE: 1, WR: 3},
    WILDCAT: {OL: 5, QB: 1, RB: 2, TE: 1, WR: 2},
    UNDER_CENTER: {OL: 5, QB: 1, RB: 1, TE: 1, WR: 3},
    UNKNOWN: {OL: 5, QB: 1, RB: 1, TE: 1, WR: 3},
  };
  const counts: PositionCounts = Object.keys(recordedCounts).length
    ? {OL: recordedCounts.OL ?? 5, QB: recordedCounts.QB ?? 1, ...recordedCounts}
    : {...defaults[formation]};
  if (!Object.keys(recordedCounts).length && visualization.offense_backfield_count != null) {
    counts.RB = Math.max(0, Math.min(3, visualization.offense_backfield_count));
  }
  const committed = (counts.OL ?? 5) + (counts.QB ?? 1) + (counts.RB ?? 0) + (counts.TE ?? 0);
  counts.WR = Math.max(0, Math.min(counts.WR ?? 11 - committed, 11 - committed));
  const positions = [
    ...(counts.OL === 5 ? ['LT', 'LG', 'C', 'RG', 'RT'] : Array.from({length: counts.OL ?? 5}, () => 'OL')),
    ...Array.from({length: counts.QB ?? 1}, () => 'QB'),
    ...Array.from({length: counts.RB ?? 0}, (_, index) => formation === 'I_FORM' && index === 1 ? 'FB' : 'RB'),
    ...Array.from({length: counts.TE ?? 0}, () => 'TE'),
    ...Array.from({length: counts.WR ?? 0}, () => 'WR'),
  ].slice(0, 11);
  while (positions.length < 11) positions.push('WR');
  return positions.map(position => ({name: `${position} not recorded`, position, recorded: false}));
}

function defensiveBackPositions(count: number) {
  if (count <= 0) return [];
  if (count === 1) return ['S'];
  if (count === 2) return ['CB', 'S'];
  if (count === 3) return ['CB', 'CB', 'S'];
  const middle = Array.from({length: Math.max(0, count - 4)}, (_, index) => index === 0 ? 'NB' : 'DB');
  return ['CB', 'CB', ...middle, 'FS', 'SS'];
}

function genericDefense(visualization: PlayVisualization) {
  const parsed = explicitPositionCounts(visualization.defensive_personnel);
  const counts = Object.keys(parsed).length ? parsed : {DL: 4, LB: 3, DB: 4};
  const total = (counts.DL ?? 0) + (counts.LB ?? 0) + (counts.DB ?? 0);
  if (total < 11) counts.DB = (counts.DB ?? 0) + 11 - total;
  const positions = [
    ...Array.from({length: counts.DL ?? 0}, () => 'DL'),
    ...Array.from({length: counts.LB ?? 0}, () => 'LB'),
    ...defensiveBackPositions(counts.DB ?? 0),
  ].slice(0, 11);
  return positions.map(position => ({name: `${position} not recorded`, position, recorded: false}));
}

function positionGroup(position: string, side: 'offense' | 'defense') {
  if (side === 'offense') {
    if (['LT', 'LG', 'C', 'RG', 'RT', 'OL', 'G', 'T'].includes(position)) return 'OL';
    if (['RB', 'HB', 'FB'].includes(position)) return 'RB';
  } else {
    if (['DT', 'NT', 'DE', 'DL', 'EDGE'].includes(position)) return 'DL';
    if (['LB', 'ILB', 'OLB', 'MLB'].includes(position)) return 'LB';
    if (['CB', 'DB', 'NB', 'S', 'FS', 'SS'].includes(position)) return 'DB';
  }
  return position;
}

function completeLineup(recorded: PlayerRecord[], template: PlayerRecord[], side: 'offense' | 'defense') {
  if (!recorded.length) return template;
  const remaining = [...template];
  for (const record of recorded) {
    let index = remaining.findIndex(item => item.position === record.position);
    if (index < 0) index = remaining.findIndex(item => positionGroup(item.position, side) === positionGroup(record.position, side));
    if (index < 0) index = remaining.length - 1;
    if (index >= 0) remaining.splice(index, 1);
  }
  return [...recorded, ...remaining].slice(0, 11);
}

function distribute(index: number, total: number, minimum: number, maximum: number) {
  return total <= 1 ? (minimum + maximum) / 2 : minimum + index * ((maximum - minimum) / (total - 1));
}

function placeOffensiveLine(
  records: PlayerRecord[],
  startX: number,
  centerY: number,
) {
  const spacing = 3.6;
  const positions = [
    {position: 'LT', y: centerY - spacing * 2},
    {position: 'LG', y: centerY - spacing},
    {position: 'C', y: centerY},
    {position: 'RG', y: centerY + spacing},
    {position: 'RT', y: centerY + spacing * 2},
  ];
  const assigned = new Map<number, {record: PlayerRecord; inferredPlacement: boolean}>();
  const remaining: PlayerRecord[] = [];
  const extras: PlayerRecord[] = [];
  const exactSlots: Record<string, number> = {LT: 0, LG: 1, C: 2, RG: 3, RT: 4};

  for (const record of records) {
    const exact = exactSlots[record.position];
    if (exact != null && !assigned.has(exact)) assigned.set(exact, {record, inferredPlacement: false});
    else remaining.push(record);
  }
  const unresolved: PlayerRecord[] = [];
  for (const record of remaining) {
    const preferences = record.position === 'T' ? [0, 4]
      : record.position === 'G' ? [1, 3]
      : record.position === 'OL' ? [2, 1, 3, 0, 4]
      : [];
    const slot = preferences.find(index => !assigned.has(index));
    if (slot != null) assigned.set(slot, {record, inferredPlacement: true});
    else unresolved.push(record);
  }
  for (const record of unresolved) {
    const slot = ['T', 'G', 'OL'].includes(record.position)
      ? positions.findIndex((_, index) => !assigned.has(index))
      : -1;
    if (slot >= 0) assigned.set(slot, {record, inferredPlacement: true});
    else extras.push(record);
  }
  positions.forEach(({position}, slot) => {
    if (!assigned.has(slot)) assigned.set(slot, {
      record: {name: `${position} not recorded`, position, recorded: false},
      inferredPlacement: true,
    });
  });
  const standardLine = positions.map((slot, index) => ({
    ...assigned.get(index)!,
    displayPosition: slot.position,
    x: startX - .7,
    y: slot.y,
  }));
  const extraLine = extras.map((record, index) => {
    const edge = Math.floor(index / 2) + 3;
    return {
      record,
      inferredPlacement: true,
      displayPosition: record.position === 'OL' ? 'T' : record.position,
      x: startX - .7,
      y: centerY + (index % 2 === 0 ? 1 : -1) * spacing * edge,
    };
  });
  return [...standardLine, ...extraLine];
}

function placeOffense(
  records: PlayerRecord[],
  startX: number,
  centerY: number,
  visualization: PlayVisualization,
): SchematicPlayer[] {
  const formation = formationKey(visualization);
  const groups = new Map<string, PlayerRecord[]>();
  for (const record of records) {
    const group = ['LT', 'LG', 'C', 'RG', 'RT', 'OL', 'G', 'T'].includes(record.position) ? 'OL'
      : ['RB', 'HB', 'FB'].includes(record.position) ? 'BACK'
      : record.position;
    groups.set(group, [...(groups.get(group) ?? []), record]);
  }
  const slots: Array<{record: PlayerRecord; x: number; y: number; displayPosition?: string; inferredPlacement?: boolean}> = [];
  const line = groups.get('OL') ?? [];
  slots.push(...placeOffensiveLine(line, startX, centerY));
  const quarterbackDepth = formation === 'SHOTGUN' || formation === 'EMPTY' ? 5.4
    : formation === 'PISTOL' ? 4
      : formation === 'WILDCAT' ? 4.8
        : 1.7;
  (groups.get('QB') ?? []).forEach((record, index) => slots.push({record, x: startX - quarterbackDepth - index * 1.5, y: centerY}));
  const backs = groups.get('BACK') ?? [];
  backs.forEach((record, index) => {
    if (formation === 'EMPTY') {
      slots.push({record, x: startX - .8, y: index % 2 ? 10 : FOOTBALL_FIELD_WIDTH - 10, inferredPlacement: true});
    } else if (formation === 'I_FORM') {
      slots.push({record, x: startX - 4.8 - index * 2.7, y: centerY, inferredPlacement: true});
    } else if (formation === 'SHOTGUN') {
      slots.push({record, x: startX - 5.2, y: centerY + (index % 2 ? -4.2 : 4.2), inferredPlacement: true});
    } else if (formation === 'PISTOL') {
      slots.push({record, x: startX - 7.3 - index * 2, y: centerY, inferredPlacement: true});
    } else {
      slots.push({record, x: startX - 5.8 - index * 2.4, y: centerY, inferredPlacement: true});
    }
  });
  const receivers = groups.get('WR') ?? [];
  const receiverYs = [5.5, 47.8, 13, 40.3, 19, 34.3];
  receivers.forEach((record, index) => slots.push({record, x: startX - (index > 1 ? 2.2 : .8), y: receiverYs[index] ?? distribute(index, receivers.length, 5.5, 47.8)}));
  const tightEnds = groups.get('TE') ?? [];
  tightEnds.forEach((record, index) => slots.push({record, x: startX - .8, y: index % 2 ? centerY + 12 : centerY - 12}));
  const assigned = new Set(slots.map(({record}) => record));
  records.filter(record => !assigned.has(record)).forEach((record, index) =>
    slots.push({record, x: startX - 5.5, y: distribute(index, records.length, 8, 45.3)}));
  return slots.map(({record, x, y, displayPosition, inferredPlacement}, index) => ({
    id: `offense-${index}`, name: record.name, label: shortName(record.name, displayPosition ?? record.position), position: displayPosition ?? record.position,
    side: 'offense', x: clamp(x, 2, 117), y, recorded: record.recorded,
    inferredPlacement: true,
    inBox: false,
    placementBasis: inferredPlacement
      ? `${describeFormation(visualization)} template; identity/role recorded where available`
      : 'Recorded position mapped to a formation-template location',
  }));
}

function coverageDepth(visualization: PlayVisualization) {
  const value = `${visualization.coverage_type ?? ''} ${visualization.man_zone ?? ''}`.toUpperCase();
  if (/COVER[_ -]?0/.test(value)) return 0;
  if (/COVER[_ -]?1/.test(value)) return 1;
  if (/COVER[_ -]?2/.test(value)) return 2;
  if (/COVER[_ -]?3/.test(value)) return 3;
  if (/COVER[_ -]?4/.test(value)) return 4;
  if (/COVER[_ -]?6/.test(value)) return 3;
  return 2;
}

function coverageShell(visualization: PlayVisualization) {
  const value = `${visualization.coverage_type ?? ''} ${visualization.man_zone ?? ''}`.toUpperCase();
  const match = value.match(/COVER[_ -]?([0-6])/);
  return match ? Number(match[1]) : null;
}

function symmetricOffsets(count: number, outer: number) {
  if (count <= 0) return [];
  if (count === 1) return [0];
  return Array.from({length: count}, (_, index) => -outer + index * ((outer * 2) / (count - 1)));
}

function assignOffsets(
  target: Map<PlayerRecord, number>,
  records: PlayerRecord[],
  centerY: number,
  outer: number,
) {
  symmetricOffsets(records.length, outer).forEach((offset, index) => target.set(records[index], centerY + offset));
}

function assignEdgeOffsets(
  target: Map<PlayerRecord, number>,
  records: PlayerRecord[],
  centerY: number,
  distance: number,
) {
  records.forEach((record, index) => {
    const side = index % 2 === 0 ? -1 : 1;
    const stepInward = Math.floor(index / 2) * 1.5;
    target.set(record, centerY + side * Math.max(2, distance - stepInward));
  });
}

function defensiveLateralPreferences(
  fronts: PlayerRecord[],
  linebackers: PlayerRecord[],
  backs: PlayerRecord[],
  centerY: number,
  offensePlayers: SchematicPlayer[],
) {
  const preferred = new Map<PlayerRecord, number>();
  const frontEdges = fronts.filter(record => ['DE', 'EDGE'].includes(record.position));
  const nose = fronts.filter(record => record.position === 'NT');
  const tackles = fronts.filter(record => record.position === 'DT');
  const genericFront = fronts.filter(record => record.position === 'DL');
  const outsideBackers = linebackers.filter(record => record.position === 'OLB');
  assignEdgeOffsets(preferred, [...frontEdges, ...outsideBackers], centerY, OFFENSIVE_LINE_HALF_WIDTH);
  assignOffsets(preferred, nose, centerY, nose.length > 1 ? 1.4 : 0);
  assignOffsets(preferred, tackles, centerY, tackles.length > 1 ? 2.8 : 0);
  assignOffsets(preferred, genericFront, centerY, genericFront.length <= 2 ? 3.2 : 6.8);

  const insideBackers = linebackers.filter(record => record.position === 'ILB');
  const middleBackers = linebackers.filter(record => record.position === 'MLB');
  const genericBackers = linebackers.filter(record => record.position === 'LB');
  assignOffsets(preferred, insideBackers, centerY, insideBackers.length > 1 ? 2.8 : 0);
  assignOffsets(preferred, middleBackers, centerY, middleBackers.length > 1 ? 1.8 : 0);
  assignOffsets(preferred, genericBackers, centerY, genericBackers.length <= 2 ? 3.2 : 6.8);

  const corners = backs.filter(record => record.position === 'CB');
  const nickels = backs.filter(record => ['NB', 'DB'].includes(record.position));
  const safeties = backs.filter(record => ['S', 'FS', 'SS'].includes(record.position));
  const receiverAlignments = offensePlayers
    .filter(player => ['WR', 'TE'].includes(player.position))
    .map(player => player.y)
    .filter((value, index, values) => values.findIndex(other => Math.abs(other - value) < .2) === index)
    .sort((left, right) => left - right);
  const wideReceiverAlignments = receiverAlignments.length >= 2
    ? [receiverAlignments[0], receiverAlignments.at(-1)!]
    : receiverAlignments;
  corners.forEach((record, index) => {
    const fallback = centerY + (index % 2 === 0 ? -1 : 1) * (FIELD_MIDDLE - 5.4);
    if (corners.length <= 2) preferred.set(record, wideReceiverAlignments[index] ?? fallback);
    else preferred.set(record, receiverAlignments[index] ?? fallback);
  });
  const slotAlignments = receiverAlignments
    .filter(value => !wideReceiverAlignments.some(wide => Math.abs(wide - value) < .2))
    .sort((left, right) => Math.abs(left - centerY) - Math.abs(right - centerY));
  nickels.forEach((record, index) => preferred.set(record,
    slotAlignments[index] ?? centerY + (index % 2 === 0 ? -11 : 11)));
  assignOffsets(preferred, safeties, centerY, safeties.length > 1 ? 10 : 0);
  return preferred;
}

function deepDefenders(backs: PlayerRecord[], visualization: PlayVisualization) {
  const count = Math.min(backs.length, coverageDepth(visualization));
  const corners = backs.filter(record => record.position === 'CB');
  const safeties = backs.filter(record => ['S', 'FS', 'SS'].includes(record.position));
  const remaining = backs.filter(record => !corners.includes(record) && !safeties.includes(record));
  const shell = coverageShell(visualization);
  const ordered = shell === 3
    ? [...corners.slice(0, 2), ...safeties, ...corners.slice(2), ...remaining]
    : shell === 4
      ? [...corners.slice(0, 2), ...safeties.slice(0, 2), ...corners.slice(2), ...safeties.slice(2), ...remaining]
      : shell === 6
        ? [...safeties.slice(0, 2), ...corners, ...safeties.slice(2), ...remaining]
        : [...safeties, ...corners, ...remaining];
  return ordered.slice(0, count);
}

function deepLateralPreferences(
  records: PlayerRecord[],
  preferred: Map<PlayerRecord, number>,
  centerY: number,
) {
  const result = new Map<PlayerRecord, number>();
  const safeties = records.filter(record => ['S', 'FS', 'SS'].includes(record.position));
  const other = records.filter(record => !safeties.includes(record));
  assignOffsets(result, safeties, centerY, safeties.length > 1 ? 9.5 : 0);
  other.forEach((record, index) => result.set(record,
    preferred.get(record) ?? centerY + symmetricOffsets(other.length, 16)[index]));
  return result;
}

function constrainedRushLanes(records: PlayerRecord[], preferred: Map<PlayerRecord, number>, centerY: number) {
  const result = new Map<PlayerRecord, number>();
  const occupied: number[] = [];
  [...records]
    .sort((left, right) => Math.abs((preferred.get(right) ?? centerY) - centerY) - Math.abs((preferred.get(left) ?? centerY) - centerY))
    .forEach(record => {
      const desired = Math.max(centerY - OFFENSIVE_LINE_HALF_WIDTH, Math.min(centerY + OFFENSIVE_LINE_HALF_WIDTH, preferred.get(record) ?? centerY));
      const candidates = [desired, desired - 1.8, desired + 1.8, desired - 3.6, desired + 3.6, centerY]
        .map(value => Math.max(centerY - OFFENSIVE_LINE_HALF_WIDTH, Math.min(centerY + OFFENSIVE_LINE_HALF_WIDTH, value)));
      const lane = candidates.find(value => occupied.every(other => Math.abs(other - value) >= 1.7)) ?? desired;
      result.set(record, lane);
      occupied.push(lane);
    });
  return result;
}

function placeDefense(
  records: PlayerRecord[],
  startX: number,
  centerY: number,
  visualization: PlayVisualization,
  offensePlayers: SchematicPlayer[],
): SchematicPlayer[] {
  const fronts = records.filter(record => ['DT', 'NT', 'DE', 'DL', 'EDGE'].includes(record.position));
  const linebackers = records.filter(record => ['LB', 'ILB', 'OLB', 'MLB'].includes(record.position));
  const backs = records.filter(record => ['CB', 'DB', 'NB', 'S', 'FS', 'SS'].includes(record.position));
  const assigned = new Set([...fronts, ...linebackers, ...backs]);
  const boxCount = Math.max(0, Math.min(11, visualization.defenders_in_box ?? visualization.defense_box_count ?? 7));
  const rusherCount = Math.max(0, Math.min(11, visualization.pass_rushers ?? (visualization.play_type === 'pass' ? 4 : fronts.length)));
  const blitzerCount = Math.max(0, Math.min(rusherCount, visualization.blitzers ?? 0));
  const edgeBackers = linebackers.filter(record => record.position === 'OLB');
  const insideBackers = linebackers.filter(record => record.position !== 'OLB');
  const rushCandidates = [...fronts, ...edgeBackers, ...insideBackers, ...backs];
  const rushers = new Set(rushCandidates.slice(0, rusherCount));
  const nonLineRushers = [...rushers].filter(record => !fronts.includes(record));
  const blitzerPool = nonLineRushers.length >= blitzerCount ? nonLineRushers : [...rushers];
  const blitzers = new Set(blitzerCount ? blitzerPool.slice(-blitzerCount) : []);
  const deepRecords = deepDefenders(backs, visualization);
  const deep = new Set(deepRecords);
  const boxCandidates = [
    ...rushers,
    ...fronts,
    ...insideBackers,
    ...edgeBackers,
    ...backs.filter(record => ['NB', 'SS', 'S'].includes(record.position) && !deep.has(record)),
    ...backs.filter(record => !deep.has(record)),
    ...deep,
  ];
  const box = new Set<PlayerRecord>();
  for (const record of boxCandidates) {
    if (box.size >= boxCount) break;
    box.add(record);
  }
  const preferredY = defensiveLateralPreferences(fronts, linebackers, backs, centerY, offensePlayers);
  const deepY = deepLateralPreferences(deepRecords, preferredY, centerY);
  const slots: Array<{record: PlayerRecord; x: number; y: number; inBox: boolean; rushRole?: 'rusher' | 'blitzer'; basis: string}> = [];
  const rushing = [...rushers];
  const boxRushers = rushing.filter(record => box.has(record));
  const rushLanes = constrainedRushLanes(boxRushers, preferredY, centerY);
  rushing.forEach((record, index) => slots.push({
    record,
    x: startX + 1.35,
    y: box.has(record)
      ? rushLanes.get(record) ?? centerY
      : preferredY.get(record) ?? distribute(index, rushing.length, 5.5, FOOTBALL_FIELD_WIDTH - 5.5),
    inBox: box.has(record),
    rushRole: blitzers.has(record) ? 'blitzer' : 'rusher',
    basis: blitzers.has(record)
      ? 'Inferred blitz assignment; lane constrained by position and offensive-line width'
      : 'Inferred pass-rush assignment; lane constrained by position and offensive-line width',
  }));
  const boxCoverage = [...box].filter(record => !rushers.has(record));
  boxCoverage.forEach((record, index) => slots.push({
    record,
    x: startX + 4.8,
    y: Math.max(centerY - OFFENSIVE_LINE_HALF_WIDTH, Math.min(centerY + OFFENSIVE_LINE_HALF_WIDTH,
      preferredY.get(record) ?? distribute(index, boxCoverage.length, centerY - 4.8, centerY + 4.8))),
    inBox: true,
    basis: 'Aligned inside tackle width from the recorded box count and listed position',
  }));
  const underneath = records.filter(record => !rushers.has(record) && !box.has(record) && !deep.has(record));
  underneath.forEach((record, index) => slots.push({
    record,
    x: startX + (backs.includes(record) ? 7.5 : 6.2),
    y: preferredY.get(record) ?? distribute(index, underneath.length, 5.5, FOOTBALL_FIELD_WIDTH - 5.5),
    inBox: false,
    basis: backs.includes(record) ? 'Underneath coverage alignment inferred from personnel' : 'Second-level alignment inferred outside the box',
  }));
  const deepPlayers = [...deep].filter(record => !box.has(record));
  deepPlayers.forEach((record, index) => slots.push({
    record,
    x: startX + 14,
    y: deepY.get(record) ?? (deepPlayers.length === 1 ? centerY : distribute(index, deepPlayers.length, 10, FOOTBALL_FIELD_WIDTH - 10)),
    inBox: false,
    basis: `Deep alignment inferred from ${visualization.coverage_type ?? 'unrecorded coverage shell'}`,
  }));
  records.filter(record => !assigned.has(record)).forEach((record, index) =>
    slots.push({record, x: startX + 7, y: distribute(index, records.length, 7, FOOTBALL_FIELD_WIDTH - 7), inBox: false, basis: 'Unknown role placed outside the box'}));
  return slots.map(({record, x, y, inBox, rushRole, basis}, index) => ({
    id: `defense-${index}`, name: record.name, label: shortName(record.name, record.position), position: record.position,
    side: 'defense', x: clamp(x, 2, 117), y, recorded: record.recorded, inferredPlacement: true,
    inBox, rushRole, placementBasis: basis,
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
  const offense = completeLineup(offenseRecorded, genericOffense(visualization), 'offense');
  const defense = completeLineup(defenseRecorded, genericDefense(visualization), 'defense');
  const {paths, markers} = buildPaths(visualization, startX, centerY);
  const offensePlayers = placeOffense(offense, startX, centerY, visualization);
  const players = [
    ...offensePlayers,
    ...placeDefense(defense, startX, centerY, visualization, offensePlayers),
  ];
  const recordedCount = players.filter(player => player.recorded).length;
  const boxCount = Math.max(0, Math.min(11, visualization.defenders_in_box ?? visualization.defense_box_count ?? 7));
  const inferredFrontCount = defense.filter(record => ['DT', 'NT', 'DE', 'DL', 'EDGE'].includes(record.position)).length;
  const passRusherCount = Math.max(0, Math.min(11, visualization.pass_rushers ?? (visualization.play_type === 'pass' ? 4 : inferredFrontCount)));
  const blitzerCount = Math.max(0, Math.min(passRusherCount, visualization.blitzers ?? 0));
  return {
    startX,
    lineToGainX: clamp(startX + (visualization.yards_to_go ?? 0)),
    hashY: centerY,
    players,
    paths,
    markers,
    lineupMode: recordedCount === 0 ? 'template' : recordedCount === players.length ? 'recorded' : 'hybrid',
    context: {
      formation: describeFormation(visualization),
      offensivePersonnel: describeOffensivePersonnel(visualization.personnel),
      defensivePersonnel: describeDefensivePersonnel(visualization.defensive_personnel),
      boxCount,
      boxCountRecorded: visualization.defenders_in_box != null || visualization.defense_box_count != null,
      passRusherCount,
      passRusherCountRecorded: visualization.pass_rushers != null,
      blitzerCount,
      blitzerCountRecorded: visualization.blitzers != null,
      coverage: describeCoverage(visualization),
    },
  };
}
