"""Centralized logging configuration."""
import logging
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> None:
    """Configure root logger with console + optional file handler."""
    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "xw_studio.log", encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
