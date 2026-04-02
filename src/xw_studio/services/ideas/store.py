"""Append-only JSON idea list for Marketing / Notensatz modules."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class IdeaEntry:
    title: str
    body: str


class IdeasStore:
    """Thread-safe file-backed store (local until Phase 5 sync)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    def _read_all(self) -> list[IdeaEntry]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ideas file unreadable %s: %s", self._path, exc)
            return []
        out: list[IdeaEntry] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    out.append(
                        IdeaEntry(
                            title=str(item.get("title", "")),
                            body=str(item.get("body", "")),
                        )
                    )
        return out

    def list_ideas(self) -> list[IdeaEntry]:
        with self._lock:
            return self._read_all()

    def add_idea(self, entry: IdeaEntry) -> None:
        with self._lock:
            rows = self._read_all()
            rows.append(entry)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(r) for r in rows]
            self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
