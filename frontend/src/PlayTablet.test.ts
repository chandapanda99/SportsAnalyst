import {cleanup, render} from '@testing-library/svelte';
import {afterEach, describe, expect, it} from 'vitest';
import PlayTablet from './PlayTablet.svelte';

afterEach(cleanup);

describe('football evidence tablet venue styling', () => {
  it('uses the home venue for field branding and each team for its player markers', () => {
    const {container} = render(PlayTablet, {
      props: {
        play: {
          evidence_id: 'nfl-play', game_id: '2025_01_KC_BUF', play_id: 12, team: 'KC',
          description: 'Recorded pass play.', epa: 0.4,
          visualization: {
            possession_team: 'KC', defensive_team: 'BUF', home_team_abbreviation: 'BUF', away_team_abbreviation: 'KC',
            yardline_100: 50, offense_names: ['Quarterback', 'Generic Tackle'], offense_positions: ['QB', 'T'],
            defense_names: ['Cornerback'], defense_positions: ['CB'], play_type: 'pass', formation: 'SHOTGUN',
            personnel: '11', defensive_personnel: '2 DL, 4 LB, 5 DB', defenders_in_box: 6,
            pass_rushers: 4, blitzers: 1, coverage_type: 'COVER_1', man_zone: 'MAN', starting_hash: 'L', qb_location: 'S',
          },
        },
        onclose: () => undefined,
      },
    });

    expect((container.querySelector('.field') as SVGElement).style.getPropertyValue('--venue-primary')).toBe('#00338D');
    expect(container.querySelector('.midfield-brand image')?.getAttribute('href')).toContain('/nfl/500/buf.png');
    expect([...container.querySelectorAll('.endzone-name')].map(node => node.textContent)).toEqual(['BILLS', 'BILLS']);
    expect((container.querySelector('.field') as SVGElement).style.getPropertyValue('--venue-endzone-text')).toBe('#F4F8FA');
    expect(container.querySelector('[aria-label^="Generic Tackle · LT"]')?.classList.contains('resolved')).toBe(true);
    expect(container.querySelector('[aria-label^="LT · Identity not recorded"]')).toBeNull();
    expect(container.querySelector('[aria-label^="LG · Identity not recorded"]')).toBeTruthy();
    expect(container.querySelectorAll('.yard-line')).toHaveLength(19);
    expect(container.querySelectorAll('.major-yard-line')).toHaveLength(9);
    expect(container.querySelectorAll('.inbound-hash')).toHaveLength(160);
    expect(container.querySelectorAll('.sideline-tick')).toHaveLength(160);
    expect(container.querySelectorAll('.yard-direction')).toHaveLength(16);
    expect(container.querySelector('.yard-direction.top[data-yard-number="10"]')?.getAttribute('d')).toContain('11.8');
    expect(container.querySelector('.field-player.offense circle')?.getAttribute('style')).not.toBe(
      container.querySelector('.field-player.defense circle')?.getAttribute('style')
    );
    expect(container.querySelectorAll('.rush-ring')).toHaveLength(4);
    expect(container.querySelectorAll('.rush-ring.blitzer')).toHaveLength(1);
    expect(container.textContent).toContain('11 personnel · 1 RB, 1 TE, 3 WR');
    expect(container.textContent).toContain('2 DL, 4 LB, 5 DB');
    expect(container.textContent).toContain('Cover 1 · Man');
  });
});
