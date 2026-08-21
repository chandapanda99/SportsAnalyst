from __future__ import annotations

import logging

from sports_analyst.log_config import configure_logging


def test_logging_configuration_respects_level_without_duplicate_handlers() -> None:
    package_logger = logging.getLogger("sports_analyst")
    original_handlers = list(package_logger.handlers)
    original_level = package_logger.level
    original_propagate = package_logger.propagate
    try:
        package_logger.handlers.clear()
        configure_logging("debug")
        configure_logging("DEBUG")

        assert package_logger.level == logging.DEBUG
        assert len(package_logger.handlers) == 1
        assert package_logger.handlers[0].level == logging.DEBUG
        assert not package_logger.propagate
    finally:
        package_logger.handlers.clear()
        package_logger.handlers.extend(original_handlers)
        package_logger.setLevel(original_level)
        package_logger.propagate = original_propagate
