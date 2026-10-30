"""Soccer competition identity and package metadata, independent of acquisition."""

SOCCER_COMPETITIONS = {
    "eng.1": ("Premier League", False),
    "usa.1": ("MLS", True),
    "esp.1": ("La Liga", False),
    "ger.1": ("Bundesliga", False),
    "ita.1": ("Serie A", False),
    "fra.1": ("Ligue 1", False),
    "usa.nwsl": ("NWSL", True),
    "uefa.champions": ("UEFA Champions League", False),
}
SOCCER_DATASETS = ("play_by_play", "team_stats", "lineups", "key_events", "match_analytics", "asa_analytics", "open_events", "match_players",
                   "understat_team_matches", "understat_player_matches", "understat_shots", "whoscored_events")
SOCCER_DEFAULT_DATASETS = ["play_by_play", "team_stats", "lineups", "key_events"]


def soccer_season_label(competition: str, season: int) -> str:
    return str(season) if SOCCER_COMPETITIONS[competition][1] else f"{season - 1}–{str(season)[-2:]}"

