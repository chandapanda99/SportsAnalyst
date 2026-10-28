import {loadLeague, resolveSync, logoUrlSync, teamColorsSync, headshotUrl, nbaHeadshotUrl, loadGsis, type LeagueData} from '@sportsdataverse/sdvplot';

const leagues = ['nfl', 'nba', 'cfb', 'soccer'] as const;
type Sport = typeof leagues[number];
const loaded = new Set<string>();
const cache = new Map<string, {logo?: string; name?: string; colors?: readonly [string, string]}>();
const leagueData = new Map<string, LeagueData>();
let initialization: Promise<void> | undefined;

// Only the four supported league shards are loaded; no manifest download, fuzzy
// name matching, or blocking image requests are needed to open the workspace.
export function initializeBranding() {
  return initialization ??= Promise.allSettled(leagues.map(async sport => {
    leagueData.set(sport, await loadLeague(sport)); loaded.add(sport);
  })).then(() => undefined);
}

export function branding(team: string, sport: string, season?: number) {
  if (!loaded.has(sport) || !team.trim()) return {};
  const key = `${sport}:${team}:${season ?? ''}`;
  if (cache.has(key)) return cache.get(key)!;
  try {
    const league = sport as Sport;
    const options = {season, ...(sport === 'nfl' && !/^\d+$/.test(team) ? {idSystem: 'nflverse' as const} : {})};
    const primary = teamColorsSync(league, team, options);
    const secondary = teamColorsSync(league, team, {...options, which: 'secondary'});
    const id = resolveSync(team, league, options);
    const identity = leagueData.get(sport)?.teams.find(row => row.team_id === id);
    const result = {logo: logoUrlSync(team, league, options), name: identity?.name ?? identity?.short_name ?? undefined,
      colors: primary && secondary ? [primary, secondary] as const : undefined};
    cache.set(key, result);
    return result;
  } catch { return {}; } // Unknown identity/season: use the application's fallback.
}

export async function playerPortrait(id: string, sport: string): Promise<string | null> {
  try {
    if (sport === 'nfl' && /^00-\d+$/.test(id)) {
      await loadGsis(); return headshotUrl(id, 'nfl', {idSystem: 'gsis'}) ?? null;
    }
    if (!/^\d+$/.test(id)) return null;
    // NBA discovery uses nba_api IDs, not ESPN IDs. Never cross those namespaces.
    if (sport === 'nba') return nbaHeadshotUrl(id);
    if (sport === 'cfb' || sport === 'nfl') return headshotUrl(id, sport) ?? null;
    return null; // Soccer portraits are not supported by the package.
  } catch { return null; }
}
