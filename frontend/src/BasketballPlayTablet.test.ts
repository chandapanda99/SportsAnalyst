import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import BasketballPlayTablet from './BasketballPlayTablet.svelte';

afterEach(cleanup);

describe('basketball evidence tablet', () => {
  it('renders recorded shot, score, and lineup context without inventing it', () => {
    const { container } = render(BasketballPlayTablet, {
      props: {
        play: {
          evidence_id: 'nba-play', season: 2025, game_id: '401', play_id: 12, team: 'BOS',
          description: 'Jayson Tatum makes a three-point jump shot.', supporting: true,
          visualization: {
            sport: 'nba', period: 4, clock: '00:18', home_team_abbreviation: 'BOS', away_team_abbreviation: 'LAL',
            home_score: 108, away_score: 105, player_name: 'Jayson Tatum', shot_x: 9, shot_y: 24,
            offense_player_ids: ['4065648', '4433134'], defense_player_ids: ['2544', '1641709']
          }
        },
        onclose: () => undefined
      }
    });

    expect(screen.getByText('Jayson Tatum makes a three-point jump shot.')).toBeTruthy();
    expect(screen.getByText(/BOS 108/)).toBeTruthy();
    expect(container.querySelector('.shot')).toBeTruthy();
    expect(screen.getByText(/4065648/)).toBeTruthy();
    expect(container.querySelector('.basketball')?.getAttribute('style')).toContain('--nba-primary:');
  });
});
