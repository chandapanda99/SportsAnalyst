"""Major feature-boundary behavior, without requiring native provider libraries."""
import pytest

from sports_analyst.config import Settings
from sports_analyst.datasets.optional import OptionalDependencyError, optional_dependencies
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector


def test_soccer_sync_reports_blocked_provider_instead_of_missing_fixtures(tmp_path, monkeypatch):
    connector = SportsDataverseSoccerConnector(Settings(data_dir=tmp_path, _env_file=None))

    def blocked_import(module):
        raise ImportError("DLL load failed: An Application Control policy has blocked this file")

    monkeypatch.setattr("sports_analyst.datasets.optional.importlib.import_module", blocked_import)
    with pytest.raises(OptionalDependencyError, match="Soccer dataset sync.*Windows blocked") as error:
        connector.sync([2025], ["play_by_play"], competition="eng.1")
    assert "existing downloaded data" in str(error.value)
    # The connector and core app stay usable; retry is allowed after repairing the dependency.
    assert connector._parse_scoreboard({"events": []}).is_empty()


def test_dependency_boundary_keeps_network_errors_distinct():
    with pytest.raises(OSError, match="network unavailable"):
        with optional_dependencies("NBA dataset sync"):
            raise OSError("network unavailable")
