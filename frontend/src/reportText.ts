import type {Evidence} from './types';

export type TextSegment = {text: string; strong?: boolean; emphasis?: boolean};

const INLINE_MARKUP = /(\*\*|__)(?=\S)(.+?)(?<=\S)\1|(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|`([^`\n]+)`/g;

/** Models sometimes answer in Markdown; show its meaning, never its punctuation. */
export function modelTextSegments(text: string): TextSegment[] {
  const cleaned = text.replace(/^#{1,6}\s+/gm, '').replace(/^\s*[-*]\s+/gm, '• ');
  const segments: TextSegment[] = [];
  let position = 0;
  for (const match of cleaned.matchAll(INLINE_MARKUP)) {
    if (match.index > position) segments.push({text: cleaned.slice(position, match.index)});
    if (match[2] !== undefined) segments.push({text: match[2], strong: true});
    else if (match[3] !== undefined) segments.push({text: match[3], emphasis: true});
    else segments.push({text: match[4]});
    position = match.index + match[0].length;
  }
  if (position < cleaned.length) segments.push({text: cleaned.slice(position)});
  return segments;
}

/** nflverse ids such as 2023_14_DET_CHI read as "Week 14 · DET at CHI"; other providers' ids are opaque. */
export function gameLabel(play: Pick<Evidence, 'game_id' | 'season'>) {
  const nfl = play.game_id?.match(/^\d{4}_(\d{2})_([A-Z]{2,3})_([A-Z]{2,3})$/);
  if (nfl) return `Week ${Number(nfl[1])} · ${nfl[2]} at ${nfl[3]}`;
  return play.season ? `${play.season} game` : 'Recorded game';
}

