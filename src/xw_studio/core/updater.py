"""Auto-update mechanism: git pull + pip install at app start."""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    updated: bool = False
    needs_restart: bool = False
    error: str | None = None


def find_repo_root() -> Path:
    """Walk up from this file to find the git root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return current.parents[3]


def check_and_update(*, enabled: bool = True) -> UpdateResult:
    """Check for updates from origin/main and apply if available."""
    if not enabled:
        return UpdateResult()

    repo = find_repo_root()
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(repo), capture_output=True, timeout=15,
        )
        diff = subprocess.run(
            ["git", "diff", "HEAD", "origin/main", "--quiet"],
            cwd=str(repo), capture_output=True, timeout=10,
        )
        if diff.returncode == 0:
            logger.info("No updates available.")
            return UpdateResult()

        logger.info("Updates found, pulling...")
        subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(repo), capture_output=True, timeout=30,
        )

        req_diff = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", "--", "requirements.txt", "pyproject.toml"],
            cwd=str(repo), capture_output=True, timeout=10,
        )
        if req_diff.stdout:
            logger.info("Dependencies changed, running pip install...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", ".[dev]", "--quiet"],
                cwd=str(repo), capture_output=True, timeout=120,
            )

        return UpdateResult(updated=True, needs_restart=True)

    except Exception as exc:
        logger.warning("Auto-update failed: %s", exc)
        return UpdateResult(error=str(exc))
