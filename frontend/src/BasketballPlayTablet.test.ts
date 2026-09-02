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
          description: 'Jayson Tatum makes a 26-foot three-point jump shot.', supporting: true,
          visualization: {
            sport: 'nba', period: 4, clock: '00:18', home_team_abbreviation: 'BOS', away_team_abbreviation: 'LAL',
            home_score: 108, away_score: 105, player_name: 'Jayson Tatum', shot_x: 9, shot_y: 24,
            scoring_play: true, shooting_play: true, shot_result: 'Made', shot_value: 3, shot_distance: 26,
            shot_coordinate_system: 'court_feet',
            offense_player_ids: ['4065648', '4433134'], defense_player_ids: ['2544', '1641709']
          }
        },
        onclose: () => undefined
      }
    });

    expect(screen.getByText('Jayson Tatum makes a 26-foot three-point jump shot.')).toBeTruthy();
    expect(screen.getByText(/BOS 108/)).toBeTruthy();
    expect(container.querySelector('.shot')).toBeTruthy();
    expect(container.querySelector('.shot')?.getAttribute('transform')).toBe('translate(9 24)');
    expect(container.querySelector('.shot.made .made-dot')).toBeTruthy();
    expect(container.querySelector('.shot path')).toBeNull();
    expect(screen.getByText('26 ft')).toBeTruthy();
    expect(screen.getAllByText(/4065648/)).toHaveLength(2);
    expect((container.querySelector('.basketball') as HTMLElement).style.getPropertyValue('--home-primary')).toBe('#007A33');
    expect(container.querySelector('.court-brand image')?.getAttribute('href')).toContain('/nba/500/bos.png');
    expect(container.querySelectorAll('.court-player.offense')).toHaveLength(2);
    expect(container.querySelectorAll('.court-player.defense')).toHaveLength(2);
    expect(container.querySelector('.court-player.offense circle')?.getAttribute('style')).not.toBe(
      container.querySelector('.court-player.defense circle')?.getAttribute('style')
    );
  });

  it('surfaces recorded names, credits, margin, possession, and game clock context when available', () => {
    const { container } = render(BasketballPlayTablet, {
      props: {
        play: {
          evidence_id: 'nba-play-rich', season: 2026, game_id: '401809245', play_id: 355, team: 'BOS',
          description: 'Jayson Tatum makes 26-foot three point jumper (Derrick White assists)', supporting: true,
          visualization: {
            sport: 'nba', period: 4, clock: '00:18', home_team_abbreviation: 'BOS', away_team_abbreviation: 'LAL',
            home_score: 108, away_score: 105, player_name: 'Jayson Tatum', shot_x: 9, shot_y: 24,
            scoring_play: true, shooting_play: true, shot_result: 'Made', shot_value: 3, shot_distance: 26,
            shot_coordinate_system: 'court_feet', game_date: '2025-11-01',
            quarter_seconds_remaining: 18, game_seconds_remaining: 18, possession_number: 87,
            secondary_player_name: 'Derrick White', secondary_player_role: 'assist',
            offense_player_ids: ['4065648', '4433134'], defense_player_ids: ['2544', '1641709'],
            offense_names: ['Jayson Tatum', 'Derrick White'], offense_positions: ['SF', 'SG'],
            defense_names: ['LeBron James', 'Austin Reaves'], defense_positions: ['SF', 'SG'],
            source_packages: ['play_by_play', 'possessions_v3', 'game_rosters']
          }
        },
        onclose: () => undefined
      }
    });

    expect(screen.getByText('BOS +3')).toBeTruthy();
    expect(screen.getByText('0:18 game left')).toBeTruthy();
    expect(screen.getByText(/NOV 1, 2025/)).toBeTruthy();
    expect(screen.getByText('Assist')).toBeTruthy();
    expect(screen.getByText('Derrick White')).toBeTruthy();
    expect(screen.getByText('#87')).toBeTruthy();
    expect(screen.getByText('Jayson Tatum (SF) · Derrick White (SG)')).toBeTruthy();
    expect(screen.getByText('LeBron James (SF) · Austin Reaves (SG)')).toBeTruthy();
    const offenseLabels = [...container.querySelectorAll('.court-player.offense text')].map(node => node.textContent);
    expect(offenseLabels).toEqual(['JT', 'DW']);
    expect(screen.getByText(/game_rosters/)).toBeTruthy();
  });
});
