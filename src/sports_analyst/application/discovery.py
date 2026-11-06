"""Small identity projections for player discovery, separate from analysis data."""
from __future__ import annotations

PLAYER_COLUMNS = {
    "nfl": {
        "gsis_id", "full_name", "team", "position", "display_name", "latest_team",
        "player_id", "player_name", "recent_team", "passer_player_id", "passer_player_name",
        "receiver_player_id", "receiver_player_name", "rusher_player_id", "rusher_player_name",
        "posteam", "attempts", "targets", "carries",
        # Defenders: credited play-by-play roles and weekly defensive production.
        "defteam", "def_tackles_solo", "def_tackle_assists", "def_sacks", "def_qb_hits", "def_pass_defended", "def_interceptions",
        *(f"{prefix}_player_{suffix}" for prefix in (
            "sack", "half_sack_1", "half_sack_2", "qb_hit_1", "qb_hit_2", "pass_defense_1", "pass_defense_2", "interception",
            "tackle_for_loss_1", "tackle_for_loss_2", "solo_tackle_1", "solo_tackle_2", "tackle_with_assist_1",
            "tackle_with_assist_2", "assist_tackle_1", "assist_tackle_2") for suffix in ("id", "name")),
        "forced_fumble_player_1_player_id", "forced_fumble_player_1_player_name",
        "forced_fumble_player_2_player_id", "forced_fumble_player_2_player_name",
    },
    "nba": {
        "athlete_id", "espn_athlete_id", "player_id", "nba_player_id", "nba_id", "person_id",
        "display_name", "athlete_display_name", "espn_full_name", "player_name", "player",
        "full_name", "nba_player_name", "name", "first_name", "last_name",
        "team_abbreviation", "team_name", "team_id", "athlete_position_abbreviation",
        "athlete_position", "position_abbreviation", "position", "nba_position",
    },
    "soccer": {"athlete_id", "athlete", "team_id", "position"},
}


def player_sources(app, connector, manifests, sport):
    """Yield one projected season at a time; never retain full multi-season PBP."""
    for manifest in manifests:
        fields = PLAYER_COLUMNS[sport].intersection(manifest.columns)
        if fields:
            frame = app._load_dataset(connector, manifest, fields)
            yield manifest.season, frame.unique(maintain_order=True)
