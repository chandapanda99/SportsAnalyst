from __future__ import annotations

import logging
import time

_HANDLER_NAME = "sports-analyst-console"


def configure_logging(level: str) -> None:
    """Configure concise application logs without changing third-party loggers."""
    numeric_level = getattr(logging, level.strip().upper(), logging.INFO)
    package_logger = logging.getLogger("sports_analyst")
    package_logger.setLevel(numeric_level)
    package_logger.propagate = False

    handler = next((item for item in package_logger.handlers if item.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        formatter = logging.Formatter("[%(asctime)sZ] (%(levelname)s) %(name)s => %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    handler.setLevel(numeric_level)
