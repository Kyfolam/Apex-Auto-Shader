from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "apex_auto_shader"

_log: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _log
    if _log is not None:
        return _log
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[Apex Auto Shader] %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.INFO)
    _log = logger
    return logger


log = get_logger()


def safe_path(value: object) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        import bpy

        abspath = getattr(getattr(bpy, "path", None), "abspath", None)
        if callable(abspath):
            text = str(abspath(text))
    except Exception:
        pass
    try:
        return Path(text).expanduser()
    except (OSError, ValueError, TypeError):
        return None


def existing_dir(value: object) -> Path | None:
    path = safe_path(value)
    if path is not None and path.is_dir():
        return path
    return None


def existing_file(value: object) -> Path | None:
    path = safe_path(value)
    if path is not None and path.is_file():
        return path
    return None
