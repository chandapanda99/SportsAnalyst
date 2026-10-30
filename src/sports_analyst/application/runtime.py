"""Construct sport components on first use, independently of API readiness."""
from __future__ import annotations

from collections.abc import Callable, Iterator, MutableMapping
from threading import RLock
from typing import Any, TypeVar

T = TypeVar("T")


class LazyRegistry(MutableMapping[str, T]):
    """A mutable registry whose discovery operations never initialize components.

    Factories run once under a lock, including concurrent first requests. Failed
    initialization is retryable; callers can still replace individual entries.
    """

    def __init__(self, factories: dict[str, Callable[[], T]]) -> None:
        self._factories = dict(factories)
        self._instances: dict[str, T] = {}
        self._lock = RLock()

    def __getitem__(self, key: str) -> T:
        with self._lock:
            if key not in self._instances:
                self._instances[key] = self._factories[key]()
            return self._instances[key]

    def __setitem__(self, key: str, value: T) -> None:
        with self._lock:
            self._factories.setdefault(key, lambda: value)
            self._instances[key] = value

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._factories[key]
            self._instances.pop(key, None)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._factories))

    def __len__(self) -> int:
        with self._lock:
            return len(self._factories)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._factories

    def initialized_values(self) -> tuple[T, ...]:
        with self._lock:
            return tuple(self._instances.values())

    def clear(self) -> None:
        with self._lock:
            self._instances.clear()
            self._factories.clear()


def sport_registries(settings, persistence) -> tuple[LazyRegistry[Any], LazyRegistry[Any]]:
    cache = None

    def cached(connector):
        nonlocal cache
        from sports_analyst.datasets.snapshots import SnapshotCache
        if cache is None:
            cache = SnapshotCache()
        connector._reader.cache = cache
        return connector

    # Explicit imports remain visible to the frozen desktop dependency scanner.
    def nfl_connector():
        from sports_analyst.datasets.nfl import NFLVerseConnector
        return cached(NFLVerseConnector(settings))

    def nba_connector():
        from sports_analyst.datasets.nba import SportsDataverseNBAConnector
        return cached(SportsDataverseNBAConnector(settings))

    def soccer_connector():
        from sports_analyst.datasets.cfb_source import CFBSource
        from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
        connector = SportsDataverseSoccerConnector(settings)
        connector.source_cache = CFBSource(settings.data_dir / "raw" / "soccer", persistence,
                                           concurrency=settings.dataset_sync_concurrency, namespace="soccer")
        return cached(connector)

    def cfb_connector():
        from sports_analyst.datasets.cfb import SportsDataverseCFBConnector
        connector = SportsDataverseCFBConnector(settings)
        connector.source.persistence = persistence
        return cached(connector)

    def nfl_plugin():
        from sports_analyst.plugins.nfl import NFLPlugin
        return NFLPlugin()

    def nba_plugin():
        from sports_analyst.plugins.nba import NBAPlugin
        return NBAPlugin()

    def soccer_plugin():
        from sports_analyst.plugins.soccer import SoccerPlugin
        return SoccerPlugin()

    def cfb_plugin():
        from sports_analyst.plugins.cfb import CFBPlugin
        return CFBPlugin()

    return (
        LazyRegistry({"nfl": nfl_connector, "nba": nba_connector, "soccer": soccer_connector, "cfb": cfb_connector}),
        LazyRegistry({"nfl": nfl_plugin, "nba": nba_plugin, "soccer": soccer_plugin, "cfb": cfb_plugin}),
    )
