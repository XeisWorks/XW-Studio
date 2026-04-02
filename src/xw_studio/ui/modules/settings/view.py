"""App-wide settings (Phase 5+ links DB and secrets)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from xw_studio.core.container import Container


class SettingsView(QWidget):
    """Placeholder; extend with printer tokens, ClickUp, DB status."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        db = (container.config.database_url or "").strip()
        fernet = bool((container.config.fernet_master_key or "").strip())
        masked = "gesetzt" if db else "nicht gesetzt"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Einstellungen"))
        layout.addWidget(QLabel(f"DATABASE_URL: {masked}"))
        layout.addWidget(QLabel(f"FERNET_MASTER_KEY: {'gesetzt' if fernet else 'fehlt'}"))
        layout.addWidget(
            QLabel(
                "Vollstaendige Token- und Druckerverwaltung folgt in Phase 5/6 — "
                "siehe docs/copilot_migration_plan.md und .env.example."
            )
        )
        layout.addStretch()
