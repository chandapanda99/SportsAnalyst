import {teamLogoUrl} from './teamPalettes';
import type {Investigation, InvestigationSummary} from './types';

type SavedReport = Investigation | InvestigationSummary;

/** The original report a follow-up belongs to, following parents through the saved history. */
export function rootIdFor(investigation: SavedReport, history: SavedReport[]) {
  let current = investigation;
  const visited = new Set<string>();
  while (current.run.parent_investigation_id && !visited.has(current.run.investigation_id)) {
    visited.add(current.run.investigation_id);
    const parent = history.find((item) => item.run.investigation_id === current.run.parent_investigation_id);
    if (!parent) return current.run.parent_investigation_id;
    current = parent;
  }
  return current.run.investigation_id;
}

/** A report and its follow-ups, oldest first. */
export function threadFor(investigation: SavedReport, history: SavedReport[]) {
  const rootId = rootIdFor(investigation, history);
  return history
      .filter((item) => rootIdFor(item, history) === rootId)
      .sort((left, right) => new Date(left.run.created_at).getTime() - new Date(right.run.created_at).getTime());
}

export function investigationTeamLogo(item: SavedReport) {
  const subject = item.run.subject;
  const team = subject?.type === 'team' ? subject.id : subject?.team_id || item.run.scope.team;
  return teamLogoUrl(team, item.run.sport ?? 'nfl', item.run.scope.comparison.season);
}

/** Tells apart saved reports that share a subject, question and window. */
export function savedOn(item: SavedReport) {
  const saved = new Date(item.run.created_at);
  if (Number.isNaN(saved.getTime())) return '';
  const sameYear = saved.getFullYear() === new Date().getFullYear();
  return saved.toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...(sameYear ? {} : {year: 'numeric'})});
}
