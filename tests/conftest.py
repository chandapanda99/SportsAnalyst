from __future__ import annotations

import polars as pl
import pytest


def synthetic_pbp(season: int, epa_shift: float = 0.0) -> pl.DataFrame:
    rows = []
    formations = ["SHOTGUN", "SINGLEBACK"]
    personnel = ["11", "12"]
    for game in range(1, 5):
        for play in range(1, 41):
            epa = 0.18 + epa_shift + (play % 7 - 3) * 0.08 - (0.3 if play % 13 == 0 else 0)
            yards = 22 if play % 9 == 0 else 5 + play % 8
            receiver = "Travis Kelce" if play % 3 else "Rashee Rice"
            receiver_id = "00-0030506" if receiver == "Travis Kelce" else "00-0039064"
            rows.append(
                {
                    "season": season,
                    "season_type": "REG",
                    "week": game,
                    "game_id": f"{season}_0{game}_KC_BUF",
                    "play_id": play,
                    "posteam": "KC",
                    "defteam": "BUF",
                    "qb_dropback": 1,
                    "play_type": "pass",
                    "epa": epa,
                    "success": int(epa > 0),
                    "cpoe": 1.5 + epa_shift * 5,
                    "yards_gained": yards,
                    "sack": int(play % 13 == 0),
                    "interception": int(play % 37 == 0),
                    "air_yards": 7 + play % 5,
                    "yards_after_catch": 3 + play % 4,
                    "passer_player_id": "00-0033873",
                    "passer_player_name": "Patrick Mahomes",
                    "receiver_player_id": receiver_id,
                    "receiver_player_name": receiver,
                    "down": 1 + play % 3,
                    "offense_formation": formations[play % 2],
                    "offense_personnel": personnel[play % 2],
                    "yardline_100": 20 + play % 70,
                    "score_differential": -7 + play % 15,
                    "desc": f"Synthetic pass play {play} in game {game}",
                }
            )
    return pl.DataFrame(rows)


@pytest.fixture
def pbp_pair() -> dict[int, pl.DataFrame]:
    return {2024: synthetic_pbp(2024), 2025: synthetic_pbp(2025, -0.10)}
