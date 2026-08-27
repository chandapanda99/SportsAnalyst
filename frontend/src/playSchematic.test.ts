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

    expect(schematic.lineupMode).toBe('recorded');
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
});
