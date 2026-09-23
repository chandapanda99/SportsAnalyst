"""Open Sports Analyst public package."""

from importlib.metadata import version
from pathlib import Path
from tomllib import loads

_project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
if _project_file.is_file():
    __version__ = loads(_project_file.read_text(encoding="utf-8"))["project"]["version"]
else:
    # Frozen and installed applications use the packaged distribution metadata.
    __version__ = version("open-sports-analyst")
