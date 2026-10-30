"""NFL source package metadata, independent of connectors and analytical plugins."""

LATEST_SYNCABLE_SEASON = 2026

SOURCE_TEMPLATES = {
    "play_by_play": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet",
    "player_stats": "https://github.com/nflverse/nflverse-data/releases/tag/player_stats",
    "rosters": "https://github.com/nflverse/nflverse-data/releases/tag/rosters",
    "injuries": "https://github.com/nflverse/nflverse-data/releases/tag/injuries",
    "schedules": "https://github.com/nflverse/nflverse-data/releases/tag/schedules",
    "snap_counts": "https://github.com/nflverse/nflverse-data/releases/tag/snap_counts",
    "nextgen_passing": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "participation": "https://github.com/nflverse/nflverse-data/releases/tag/pbp_participation",
    "weekly_rosters": "https://github.com/nflverse/nflverse-data/releases/tag/weekly_rosters",
    "depth_charts": "https://github.com/nflverse/nflverse-data/releases/tag/depth_charts",
    "nextgen_receiving": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "nextgen_rushing": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "ftn_charting": "https://github.com/nflverse/nflverse-data/releases/tag/ftn_charting",
    "pfr_passing": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_rushing": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_receiving": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_defense": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "players": "https://github.com/nflverse/nflverse-data/releases/tag/players",
    "teams": "https://github.com/nflverse/nflverse-data/releases/tag/teams",
}
SUPPORTED_DATASETS = tuple(SOURCE_TEMPLATES)
REFERENCE_DATASETS = {"players", "teams"}
DIRECT_PARQUET_PATHS = {
    "play_by_play": "pbp/play_by_play_{season}.parquet",
    "player_stats": "stats_player/stats_player_week_{season}.parquet",
    "rosters": "rosters/roster_{season}.parquet",
    "injuries": "injuries/injuries_{season}.parquet",
    "snap_counts": "snap_counts/snap_counts_{season}.parquet",
    "participation": "pbp_participation/pbp_participation_{season}.parquet",
    "weekly_rosters": "weekly_rosters/roster_weekly_{season}.parquet",
    "depth_charts": "depth_charts/depth_charts_{season}.parquet",
    "ftn_charting": "ftn_charting/ftn_charting_{season}.parquet",
    "pfr_passing": "pfr_advstats/advstats_week_pass_{season}.parquet",
    "pfr_rushing": "pfr_advstats/advstats_week_rush_{season}.parquet",
    "pfr_receiving": "pfr_advstats/advstats_week_rec_{season}.parquet",
    "pfr_defense": "pfr_advstats/advstats_week_def_{season}.parquet",
}
NFLVERSE_RELEASE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/"
DATASET_MIN_SEASONS = {
    "play_by_play": 1999,
    "player_stats": 1999,
    "rosters": 1920,
    "injuries": 2009,
    "schedules": 1920,
    "snap_counts": 2012,
    "nextgen_passing": 2016,
    "participation": 2016,
    "weekly_rosters": 2002,
    "depth_charts": 2001,
    "nextgen_receiving": 2016,
    "nextgen_rushing": 2016,
    "ftn_charting": 2022,
    "pfr_passing": 2018,
    "pfr_rushing": 2018,
    "pfr_receiving": 2018,
    "pfr_defense": 2018,
}

