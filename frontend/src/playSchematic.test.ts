import {describe, expect, it} from 'vitest';
import {
  defensiveLook, defensivePackage, describeDefensivePersonnel, describeFormation, describeOffensivePersonnel, describePlaymakers,
} from './playSchematic';
import {collegePlaymakers} from './cfbSchematic';

describe('play context labels', () => {
  it('gives listed and compact personnel the same backs-and-tight-ends code', () => {
    expect(describeOffensivePersonnel('11')).toBe('11 personnel · 1 RB, 1 TE, 3 WR');
    expect(describeOffensivePersonnel('1 RB, 2 TE, 2 WR')).toBe('12 personnel · 1 RB, 2 TE, 2 WR');
    // From 2023 participation lists all eleven players.
    expect(describeOffensivePersonnel('1 C, 2 G, 1 QB, 1 FB, 1 RB, 2 T, 1 TE, 2 WR')).toBe('21 personnel · 2 RB, 1 TE, 2 WR');
    expect(describeOffensivePersonnel(undefined)).toBe('Not recorded');
  });

  it('groups participation position lists into fronts and packages', () => {
    // Participation names specific positions rather than DL/LB/DB.
    expect(describeDefensivePersonnel('3 CB, 2 DE, 2 DT, 1 FS, 2 ILB, 1 SS')).toBe('4 DL, 2 LB, 5 DB');
    expect(defensivePackage('3 CB, 2 DE, 2 DT, 1 FS, 2 ILB, 1 SS')).toBe('Nickel (4-2-5)');
    expect(defensivePackage('2 CB, 2 DE, 2 DT, 2 FS, 2 ILB, 1 SS')).toBe('Nickel (4-2-5)');
    expect(defensivePackage('2 CB, 2 DE, 2 DT, 1 FS, 3 ILB, 1 SS')).toBe('Base (4-3-4)');
    expect(defensivePackage('4 CB, 1 DE, 2 DT, 1 FS, 1 OLB, 1 ILB, 1 SS')).toBe('Dime (3-2-6)');
    expect(defensivePackage(undefined)).toBeNull();
    // A standard five-man line is implied; a sixth lineman is named.
    expect(describeOffensivePersonnel('1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR')).toBe('11 personnel · 1 RB, 1 TE, 3 WR');
    expect(describeOffensivePersonnel('1 C, 2 G, 1 QB, 1 RB, 3 T, 1 TE, 2 WR')).toBe('11 personnel · 6 OL, 1 RB, 1 TE, 2 WR');
  });

  it('summarizes the recorded defensive look and who made the play', () => {
    const pass = {play_type: 'pass', defensive_personnel: '3 CB, 2 DE, 2 DT, 1 FS, 2 ILB, 1 SS', defenders_in_box: 6,
      pass_rushers: 5, blitzers: 1, coverage_type: 'COVER_3', man_zone: 'ZONE_COVERAGE', pressure: true, time_to_throw: 2.43};
    expect(defensiveLook(pass)).toEqual(['Nickel (4-2-5)', '6 in box', '5 rushers, 1 blitzing', 'Cover 3 · Zone', 'Pressured, 2.4s to throw']);
    // Runs leave out pass-rush, coverage and pressure fields, which are not charted on runs.
    expect(defensiveLook({play_type: 'run', defenders_in_box: 8, pass_rushers: 0, pressure: false, man_zone: ''})).toEqual(['8 in box']);
    expect(defensiveLook({})).toEqual([]);
    expect(defensiveLook({play_type: 'pass', coverage_type: '2_MAN', man_zone: 'MAN_COVERAGE'})).toEqual(['2 Man']);
    expect(describePlaymakers({defensive_playmakers: [{role: 'Sack', players: ['A.Hutchinson']}, {role: 'Tackle', players: ['J.Campbell', 'A.Anzalone']}]}))
      .toEqual(['Sack: A.Hutchinson', 'Tackle: J.Campbell, A.Anzalone']);
  });

  it('reads both participation formation vocabularies', () => {
    expect(describeFormation({formation: 'UNDER CENTER'} as never)).toBe('Under center');
    expect(describeFormation({formation: 'SINGLEBACK'} as never)).toBe('Singleback');
    expect(describeFormation({formation: 'SHOTGUN'} as never)).toBe('Shotgun');
  });
});

describe('collegePlaymakers', () => {
  const actor = (role: string, athlete_id: string, name: string, team_id: string | null) => ({role, athlete_id, name, team_id});

  it('credits only the defending team, most decisive play first', () => {
    expect(collegePlaymakers({id: '1', team_id: '2', provider_context_json: '{"sack": true, "fumble_vec": true}', participants: [
      actor('passer', '20', 'Quarterback', '2'), actor('sackedBy', '30', 'Edge Rusher', '1'),
      actor('forcedBy', '30', 'Edge Rusher', '1'), actor('recoverer', '33', 'Tackle', null), actor('tackler', '30', 'Edge Rusher', '1')
    ]})).toEqual(['Sack: Edge Rusher', 'Forced fumble: Edge Rusher', 'Fumble recovery: Tackle']);
  });

  it('turns an interception pass defense into an interception and ignores the offense logged as defenders', () => {
    expect(collegePlaymakers({id: '2', team_id: '2', interception: true, participants: [
      actor('passer', '20', 'Quarterback', '2'), actor('passDefender', '31', 'Corner', '1'), actor('tackler', '20', 'Quarterback', '2')
    ]})).toEqual(['Interception: Corner']);
    expect(collegePlaymakers({id: '3', team_id: '2', interception: true, participants: [
      actor('passer', '20', 'Quarterback', '2'), actor('passDefender', '21', 'Receiver', '2')
    ]})).toEqual([]);
    expect(collegePlaymakers({id: '4', team_id: '2', participants: [
      actor('rusher', '22', 'Runner', '2'), actor('tackler', '40', 'Linebacker', '1'), actor('assistedBy', '41', 'Safety', null)
    ]})).toEqual(['Tackle: Linebacker, Safety']);
    expect(collegePlaymakers({id: '5', team_id: '1', provider_context_json: '{"int": true, "interception_player_name": "Corner"}',
      participants: [actor('scorer', '31', 'Corner', '1')]})).toEqual(['Interception: Corner']);
  });
});
