import {describe, expect, it} from 'vitest';
import {buildPlaySchematic} from './playSchematic';

describe('play schematic reconstruction', () => {
  it('uses recorded participants and separates an interception from its return', () => {
    const schematic = buildPlaySchematic({
      yardline_100: 45,
      yards_to_go: 10,
      play_type: 'pass',
      air_yards: -8,
      interception: true,
      turnover: true,
      turnover_player: 'J.Hunt',
      return_yards: 11,
      starting_hash: 'R',
      offense_names: ['C.Williams', 'K.Monangai', 'R.Wright', 'T.Jenkins', 'D.Wright', 'C.Shelton', 'J.Thuney'],
      offense_positions: ['QB', 'RB', 'RT', 'LG', 'LT', 'C', 'RG'],
      defense_names: ['J.Hunt'],
      defense_positions: ['LB'],
    });

    expect(schematic.lineupMode).toBe('hybrid');
    expect(schematic.players.some(player => player.name === 'J.Hunt' && player.side === 'defense')).toBe(true);
    expect(schematic.paths.map(path => path.kind)).toEqual(['pass', 'return']);
    expect(schematic.markers.some(marker => marker.label === 'INT · J.Hunt')).toBe(true);
    expect(schematic.paths[1].endX).toBeLessThan(schematic.paths[0].endX);
    const line = Object.fromEntries(
      schematic.players
        .filter(player => ['LT', 'LG', 'C', 'RG', 'RT'].includes(player.position))
        .map(player => [player.position, player.y]),
    );
    expect(line.LT).toBeLessThan(line.LG);
    expect(line.LG).toBeLessThan(line.C);
    expect(line.C).toBeLessThan(line.RG);
    expect(line.RG).toBeLessThan(line.RT);
    expect(line.C).toBe(schematic.hashY);
    expect(line.RG).toBeDefined();
    expect(Math.max(...Object.values(line)) - Math.min(...Object.values(line))).toBeLessThan(15);
    expect(new Set(
      schematic.players
        .filter(player => ['LT', 'LG', 'C', 'RG', 'RT'].includes(player.position))
        .map(player => player.x),
    ).size).toBe(1);
  });

  it('falls back to an eleven-player template with play-by-play alone', () => {
    const schematic = buildPlaySchematic({
      yardline_100: 58,
      play_type: 'pass',
      complete_pass: true,
      air_yards: 22,
      yards_after_catch: 36,
      yards_gained: 58,
      formation: 'SHOTGUN',
      pass_location: 'middle',
    });

    expect(schematic.lineupMode).toBe('template');
    expect(schematic.players.filter(player => player.side === 'offense')).toHaveLength(11);
    expect(schematic.players.filter(player => player.side === 'defense')).toHaveLength(11);
    expect(schematic.paths.map(path => path.kind)).toEqual(['pass', 'after-catch']);
  });

  it('uses every recorded generic lineman before creating inferred line placeholders', () => {
    const completeLine = buildPlaySchematic({
      offense_names: ['Center', 'Right Guard', 'Right Tackle', 'Tackle One', 'Tackle Two', 'Quarterback'],
      offense_positions: ['C', 'RG', 'RT', 'T', 'T', 'QB'],
    });
    const linemen = completeLine.players.filter(player =>
      player.side === 'offense' && ['LT', 'LG', 'C', 'RG', 'RT'].includes(player.position)
    );

    expect(linemen).toHaveLength(5);
    expect(linemen.every(player => player.recorded)).toBe(true);
    expect(linemen.find(player => player.name === 'Tackle One')).toMatchObject({position: 'LT', inferredPlacement: true});
    expect(linemen.find(player => player.name === 'Tackle Two')).toMatchObject({position: 'LG', inferredPlacement: true});

    const incompleteLine = buildPlaySchematic({
      offense_names: ['Center', 'Right Guard', 'Right Tackle', 'Left Tackle'],
      offense_positions: ['C', 'RG', 'RT', 'LT'],
    });
    expect(incompleteLine.players.find(player => player.side === 'offense' && player.position === 'LG'))
      .toMatchObject({recorded: false, inferredPlacement: true});
  });

  it('turns football terminology into consistent formation, box, rush, and coverage geometry', () => {
    const schematic = buildPlaySchematic({
      yardline_100: 52,
      play_type: 'pass',
      formation: 'SHOTGUN',
      personnel: '11',
      defensive_personnel: '2 DL, 4 LB, 5 DB',
      defenders_in_box: 6,
      pass_rushers: 4,
      blitzers: 1,
      coverage_type: 'COVER_3',
      man_zone: 'ZONE',
      starting_hash: 'L',
      qb_location: 'S',
      offense_backfield_count: 1,
      offense_names: ['Quarterback'],
      offense_positions: ['QB'],
    });

    const offense = schematic.players.filter(player => player.side === 'offense');
    const defense = schematic.players.filter(player => player.side === 'defense');
    expect(offense).toHaveLength(11);
    expect(defense).toHaveLength(11);
    expect(schematic.context).toEqual({
      formation: 'Shotgun',
      offensivePersonnel: '11 personnel · 1 RB, 1 TE, 3 WR',
      defensivePersonnel: '2 DL, 4 LB, 5 DB',
      boxCount: 6,
      boxCountRecorded: true,
      passRusherCount: 4,
      passRusherCountRecorded: true,
      blitzerCount: 1,
      blitzerCountRecorded: true,
      coverage: 'Cover 3 · Zone',
    });
    expect(defense.filter(player => player.inBox)).toHaveLength(6);
    expect(defense.filter(player => player.rushRole)).toHaveLength(4);
    expect(defense.filter(player => player.rushRole === 'blitzer')).toHaveLength(1);
    expect(defense.filter(player => player.placementBasis.startsWith('Deep alignment'))).toHaveLength(3);

    const line = offense.filter(player => ['LT', 'LG', 'C', 'RG', 'RT'].includes(player.position));
    const quarterback = offense.find(player => player.position === 'QB')!;
    expect(new Set(line.map(player => player.x)).size).toBe(1);
    expect(quarterback.x).toBeLessThan(line[0].x);
  });

  it('keeps the box inside tackle width and honors position-specific defensive landmarks', () => {
    const schematic = buildPlaySchematic({
      play_type: 'pass',
      starting_hash: 'C',
      defensive_personnel: '3 DL, 3 LB, 5 DB',
      defenders_in_box: 6,
      pass_rushers: 4,
      blitzers: 1,
      coverage_type: 'COVER_2',
      defense_names: ['Nose', 'End', 'Tackle', 'Mike', 'Inside', 'Sam', 'Corner A', 'Corner B', 'Nickel', 'Free', 'Strong'],
      defense_positions: ['NT', 'DE', 'DT', 'MLB', 'ILB', 'OLB', 'CB', 'CB', 'NB', 'FS', 'SS'],
    });

    const defense = schematic.players.filter(player => player.side === 'defense');
    const box = defense.filter(player => player.inBox);
    const middle = defense.find(player => player.position === 'MLB')!;
    const outside = defense.find(player => player.position === 'OLB')!;
    const interior = defense.find(player => player.position === 'NT')!;
    const corners = defense.filter(player => player.position === 'CB');
    const safeties = defense.filter(player => ['FS', 'SS'].includes(player.position));
    const receiverAlignments = schematic.players
      .filter(player => player.side === 'offense' && player.position === 'WR')
      .map(player => player.y);

    expect(box).toHaveLength(6);
    expect(box.every(player => Math.abs(player.y - schematic.hashY) <= 7.2)).toBe(true);
    expect(Math.abs(middle.y - schematic.hashY)).toBeLessThanOrEqual(1.8);
    expect(Math.abs(outside.y - schematic.hashY)).toBeGreaterThan(Math.abs(interior.y - schematic.hashY));
    expect(corners.every(player => receiverAlignments.some(receiverY => Math.abs(receiverY - player.y) < .2))).toBe(true);
    expect(corners.every(player => player.y >= 4 && player.y <= 49.3)).toBe(true);
    expect(safeties.every(player => player.x - schematic.startX >= 14)).toBe(true);
    expect(safeties.map(player => Math.round((player.y - schematic.hashY) * 10) / 10).sort((a, b) => a - b)).toEqual([-9.5, 9.5]);
  });

});
