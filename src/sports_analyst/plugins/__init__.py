"""Compatible plugin exports without importing every sport as a side effect."""


def __getattr__(name: str):
    if name == "NBAPlugin":
        from sports_analyst.plugins.nba import NBAPlugin
        return NBAPlugin
    if name == "NFLPlugin":
        from sports_analyst.plugins.nfl import NFLPlugin
        return NFLPlugin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["NBAPlugin", "NFLPlugin"]
