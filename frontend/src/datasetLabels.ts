/** The name a person sees for a downloadable data package. */
export function datasetLabel(dataset: string, sport: string) {
  if (sport === 'soccer') {
    const soccerLabels: Record<string, string> = {
      play_by_play: 'Match Results', team_stats: 'Team Match Statistics',
      lineups: 'Match Lineups', key_events: 'Match Events', expected_goals: 'Expected Goals (xG)'
    };
    if (soccerLabels[dataset]) return soccerLabels[dataset];
  }
  const labels: Record<string, string> = {
    play_by_play: 'Play By Play',
    player_stats: 'Player Stats',
    rosters: 'Rosters',
    injuries: 'Injuries',
    schedules: 'Schedules',
    snap_counts: 'Snap Counts',
    nextgen_passing: 'Nextgen Passing',
    participation: 'Play Participation',
    weekly_rosters: 'Weekly Rosters',
    depth_charts: 'Depth Charts',
    nextgen_receiving: 'Nextgen Receiving',
    nextgen_rushing: 'Nextgen Rushing',
    ftn_charting: 'FTN Charting',
    pfr_passing: 'PFR Advanced Passing',
    pfr_rushing: 'PFR Advanced Rushing',
    pfr_receiving: 'PFR Advanced Receiving',
    pfr_defense: 'PFR Advanced Defense',
    players: 'Player Directory',
    teams: 'Team Directory',
    team_boxscores: 'Team Box Scores',
    player_boxscores: 'Player Box Scores',
    shots: 'Shots',
    game_rosters: 'Game Rosters',
    officials: 'Officials',
    standings: 'Standings',
    player_season_stats: 'Player Season Stats',
    team_season_stats: 'Team Season Stats',
    draft: 'Draft Results',
    stats_schedules: 'NBA Stats Schedules',
    stats_coaches: 'NBA Stats Coaches',
    stats_game_rosters: 'NBA Stats Game Rosters',
    lineups: 'Five-player Lineups',
    stats_officials: 'NBA Stats Officials',
    stats_play_by_play: 'NBA Stats Play By Play',
    stats_player_boxscores: 'NBA Stats Player Box Scores',
    stats_player_game_logs: 'NBA Stats Player Game Logs',
    stats_player_season_stats: 'NBA Stats Player Season Stats',
    stats_rosters: 'NBA Stats Rosters',
    stats_shots: 'NBA Stats Shots',
    stats_standings: 'NBA Stats Standings',
    stats_team_boxscores: 'NBA Stats Team Box Scores',
    stats_team_season_stats: 'NBA Stats Team Season Stats',
    player_crosswalk: 'Player Crosswalk',
    schedule_crosswalk: 'Schedule Crosswalk',
    team_crosswalk: 'Team Crosswalk',
    player_core: 'Player Identity Core',
    player_impact: 'Player Impact',
    match_analytics: 'Match Analytics (FotMob)',
    team_stats: 'Team Stats',
    scoring_events: 'Scoring Events',
    recorded_plays: 'Recorded Plays',
    enriched_plays: 'Modeled Play Values (EPA/WPA)'
  };
  return labels[dataset] ?? dataset.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
