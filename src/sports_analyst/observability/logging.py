from __future__ import annotations

import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_HANDLER_NAME = "sports-analyst-console"
_FILE_HANDLER_NAME = "sports-analyst-file"


class RedactedFormatter(logging.Formatter):
    """Redact formatted messages and exception chains (never record locals)."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for name, value in os.environ.items():
            if len(value) >= 4 and re.search(r"(?:KEY|TOKEN|PASSWORD|SECRET|CONNECTION_STRING)", name, re.I):
                text = text.replace(value, "[redacted]")
        text = re.sub(r"https?://[^\s<>\"']+", "[redacted URL]", text, flags=re.I)
        text = re.sub(r"\bBearer\s+\S+", "Bearer [redacted]", text, flags=re.I)
        return re.sub(r"\b(api[_-]?key|password|token|secret|authorization)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
                      r"\1=[redacted]", text, flags=re.I)


def configure_logging(level: str, *, log_path: Path | None = None) -> None:
    """Configure concise application logs without changing third-party loggers."""
    numeric_level = getattr(logging, level.strip().upper(), logging.INFO)
    package_logger = logging.getLogger("sports_analyst")
    package_logger.propagate = False

    handler = next((item for item in package_logger.handlers if item.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        formatter = RedactedFormatter("[%(asctime)sZ] (%(levelname)s) %(name)s => %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    handler.setLevel(numeric_level)
    file_handler = next((item for item in package_logger.handlers if item.get_name() == _FILE_HANDLER_NAME), None)
    if log_path is not None and (file_handler is None or Path(file_handler.baseFilename) != log_path.resolve()):
        if file_handler is not None:
            package_logger.removeHandler(file_handler)
            file_handler.close()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.set_name(_FILE_HANDLER_NAME)
        file_handler.setFormatter(handler.formatter)
        file_handler.setLevel(logging.DEBUG)
        package_logger.addHandler(file_handler)
    package_logger.setLevel(min(numeric_level, logging.DEBUG) if file_handler is not None else numeric_level)
