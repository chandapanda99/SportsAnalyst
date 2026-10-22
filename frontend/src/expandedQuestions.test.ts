import {expect, it} from 'vitest';
import {expandedQuestions} from './expandedQuestions';

it('covers every CFB, soccer, and basketball analysis domain with distinct, subject-specific prompts', () => {
  const domains = {
    cfb: {team: ['results', 'offense'], player: ['quarterback', 'rushing', 'receiving']},
    soccer: {team: ['results', 'attack', 'defense', 'control'], player: ['usage', 'scoring', 'discipline']},
    nba: {team: ['offense', 'defense', 'shooting', 'playmaking', 'rebounding', 'turnovers', 'lineups'],
      player: ['scoring', 'shooting', 'playmaking', 'rebounding', 'turnovers', 'usage', 'impact', 'lineups']}
  };
  for (const [sport, subjects] of Object.entries(domains)) {
    for (const type of ['team', 'player'] as const) {
      expect(Object.keys(expandedQuestions[sport][type]).sort()).toEqual([...subjects[type]].sort());
      for (const domain of subjects[type]) {
        const questions = expandedQuestions[sport][type][domain];
        expect(questions.length).toBeGreaterThanOrEqual(sport === 'nba' ? 2 : 5);
        expect(new Set(questions).size).toBe(questions.length);
        expect(questions.every(question => question.endsWith('?'))).toBe(true);
      }
    }
  }
  expect(expandedQuestions.cfb.player.receiving.join(' ')).toMatch(/transfer/);
  expect(expandedQuestions.cfb.team.offense.join(' ')).toMatch(/Where modeled EPA is available/);
  expect(expandedQuestions.soccer.player.scoring.join(' ')).toMatch(/Where player xG is recorded/);
});
