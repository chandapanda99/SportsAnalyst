import {describe, expect, it} from 'vitest';
import {gameLabel, modelTextSegments} from './reportText';

describe('modelTextSegments', () => {
  it('turns inline markdown into styled text', () => {
    expect(modelTextSegments('Across *all qualifying offensive plays*, EPA **rose** by `0.128`.')).toEqual([
      {text: 'Across '}, {text: 'all qualifying offensive plays', emphasis: true}, {text: ', EPA '},
      {text: 'rose', strong: true}, {text: ' by '}, {text: '0.128'}, {text: '.'}
    ]);
  });

  it('leaves arithmetic and identifiers alone', () => {
    expect(modelTextSegments('EPA * plays = 2 * 3 for snake_case_name')).toEqual([{text: 'EPA * plays = 2 * 3 for snake_case_name'}]);
  });

  it('removes heading and bullet markers', () => {
    expect(modelTextSegments('## Summary\n- First\n* Second')).toEqual([{text: 'Summary\n• First\n• Second'}]);
  });
});

describe('gameLabel', () => {
  it('reads NFL game ids as a week and matchup', () => {
    expect(gameLabel({game_id: '2023_14_DET_CHI', season: 2023})).toBe('Week 14 · DET at CHI');
  });

  it('never shows an opaque provider id', () => {
    expect(gameLabel({game_id: '401520194', season: 2023})).toBe('2023 game');
    expect(gameLabel({game_id: '401520194'})).toBe('Recorded game');
  });
});

