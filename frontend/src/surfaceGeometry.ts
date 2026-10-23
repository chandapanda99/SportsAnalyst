import {FOOTBALL_SPECS, BASKETBALL_SPECS, SOCCER_SPECS} from '@sportsdataverse/sporty/specs';
const yard = (value: number) => Math.round(value * 36) / 36; // specs round repeating yard fractions
export const footballWidth = yard(FOOTBALL_SPECS.nfl.field_width);
export const footballHash = (college = false) => yard((footballWidth - FOOTBALL_SPECS[college ? 'ncaa' : 'nfl'].inbound_hashmark_separation) / 2);
export const nbaCourt = BASKETBALL_SPECS.nba;
export const soccerPitch = {...SOCCER_SPECS.fifa, pitch_length: 105, pitch_width: 68};
/** Explicit center-origin provider frame to our existing baseline-origin half court. */
export function nbaCenterToTablet(x: number, y: number) {
  return {x: nbaCourt.court_width / 2 - y, y: nbaCourt.court_length / 2 - nbaCourt.basket_center_to_baseline - x};
}
