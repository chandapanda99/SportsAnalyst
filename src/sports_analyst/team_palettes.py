from __future__ import annotations

from dataclasses import dataclass

NFL_TEAM_PALETTES: dict[str, tuple[str, str]] = {
    "ARI": ("#97233F", "#FFB612"),
    "ATL": ("#A71930", "#A5ACAF"),
    "BAL": ("#241773", "#9E7C0C"),
    "BUF": ("#00338D", "#C60C30"),
    "CAR": ("#0085CA", "#BFC0BF"),
    "CHI": ("#0B162A", "#E64100"),
    "CIN": ("#FB4F14", "#A5ACAF"),
    "CLE": ("#311D00", "#FF3C00"),
    "DAL": ("#041E42", "#869397"),
    "DEN": ("#FB4F14", "#002244"),
    "DET": ("#0076B6", "#B0B7BC"),
    "GB": ("#203731", "#FFB612"),
    "HOU": ("#03202F", "#A71930"),
    "IND": ("#002C5F", "#A2AAAD"),
    "JAX": ("#00A5B5", "#D7A22A"),
    "KC": ("#E31837", "#FFB81C"),
    "LV": ("#A5ACAF", "#FFFFFF"),
    "LAC": ("#0080C6", "#FFC20E"),
    "LA": ("#003594", "#FFD100"),
    "MIA": ("#008E97", "#FC4C02"),
    "MIN": ("#4F2683", "#FFC62F"),
    "NE": ("#002244", "#C60C30"),
    "NO": ("#D3BC8D", "#101820"),
    "NYG": ("#0B2265", "#A71930"),
    "NYJ": ("#125740", "#FFFFFF"),
    "PHI": ("#004C54", "#A5ACAF"),
    "PIT": ("#FFB612", "#A5ACAF"),
    "SF": ("#AA0000", "#B3995D"),
    "SEA": ("#002244", "#69BE28"),
    "TB": ("#D50A0A", "#FF7900"),
    "TEN": ("#0C2340", "#4B92DB"),
    "WAS": ("#5A1414", "#FFB612"),
}

# Reference: NBA Colors (Community), Figma page 0:1.
# Primary and secondary follow the first two palette cards after each team's logo card.
NBA_TEAM_PALETTES: dict[str, tuple[str, str]] = {
    "ATL": ("#E03A3E", "#F9A01B"),
    "BOS": ("#007A33", "#BA9653"),
    "BKN": ("#000000", "#FFFFFF"),
    "CHA": ("#1D1160", "#00788C"),
    "CHI": ("#CE1141", "#000000"),
    "CLE": ("#860038", "#041E42"),
    "DAL": ("#00538C", "#002B5E"),
    "DEN": ("#0E2240", "#FEC524"),
    "DET": ("#C8102E", "#1D42BA"),
    "GSW": ("#1D428A", "#FFC72C"),
    "HOU": ("#CE1141", "#000000"),
    "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"),
    "LAL": ("#552583", "#FDB927"),
    "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"),
    "MIL": ("#00471B", "#EEE1C6"),
    "MIN": ("#0C2340", "#236192"),
    "NOP": ("#0C2340", "#C8102E"),
    "NYK": ("#006BB6", "#F58426"),
    "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"),
    "PHI": ("#006BB6", "#ED174C"),
    "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#000000"),
    "SAC": ("#5A2D81", "#63727A"),
    "SAS": ("#C4CED4", "#000000"),
    "TOR": ("#CE1141", "#000000"),
    "UTA": ("#002B5C", "#00471B"),
    "WSH": ("#002B5C", "#E31837"),
}

# Retained for callers that import the original NFL-only constant.
TEAM_PALETTES = NFL_TEAM_PALETTES
NBA_TEAM_ALIASES = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA"}
DEFAULT_PALETTE = ("#6F9FD1", "#78DCCA")
REPORT_BACKGROUND = "#09111D"


@dataclass(frozen=True)
class TeamReportPalette:
    primary: str
    secondary: str
    display_primary: str
    display_secondary: str


def _rgb(color: str) -> tuple[int, int, int]:
    value = int(color.removeprefix("#"), 16)
    return (value >> 16 & 255, value >> 8 & 255, value & 255)


def _luminance(color: str) -> float:
    channels = []
    for channel in _rgb(color):
        normalized = channel / 255
        channels.append(normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _mix_with_white(color: str, amount: float) -> str:
    channels = [round(channel + (255 - channel) * amount) for channel in _rgb(color)]
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _accessible_accent(color: str) -> str:
    if contrast_ratio(color, REPORT_BACKGROUND) >= 4.5:
        return color
    for step in range(1, 21):
        candidate = _mix_with_white(color, step * 0.04)
        if contrast_ratio(candidate, REPORT_BACKGROUND) >= 4.5:
            return candidate
    return "#E7EDF6"


def team_report_palette(team: str, sport: str = "nfl") -> TeamReportPalette:
    normalized = team.upper()
    palettes = NFL_TEAM_PALETTES
    if sport.lower() == "nba":
        palettes = NBA_TEAM_PALETTES
        normalized = NBA_TEAM_ALIASES.get(normalized, normalized)
    primary, secondary = palettes.get(normalized, DEFAULT_PALETTE)
    return TeamReportPalette(primary, secondary, _accessible_accent(primary), _accessible_accent(secondary))


def rgb_csv(color: str) -> str:
    return ",".join(str(channel) for channel in _rgb(color))
