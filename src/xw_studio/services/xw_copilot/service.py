"""Persisted settings and templates for Outlook add-in integration."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_CONFIG_KEY = "xw_copilot.config"
_TEMPLATES_KEY = "xw_copilot.templates"


@dataclass(frozen=True)
class XWCopilotConfig:
    enabled: bool = False
    mode: str = "dry_run"
    outlook_tenant_id: str = ""
    outlook_client_id: str = ""
    mailbox_address: str = ""
    webhook_url: str = ""
    default_project: str = ""


class XWCopilotService:
    """Read/write XW-Copilot settings and prompt blocks via SettingKvRepository."""

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    def has_storage(self) -> bool:
        return self._repo is not None

    def load_config(self) -> XWCopilotConfig:
        if self._repo is None:
            return XWCopilotConfig()
        raw = self._repo.get_value_json(_CONFIG_KEY)
        if not raw:
            return XWCopilotConfig()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _CONFIG_KEY)
            return XWCopilotConfig()
        if not isinstance(data, dict):
            return XWCopilotConfig()
        return XWCopilotConfig(
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode") or "dry_run"),
            outlook_tenant_id=str(data.get("outlook_tenant_id") or ""),
            outlook_client_id=str(data.get("outlook_client_id") or ""),
            mailbox_address=str(data.get("mailbox_address") or ""),
            webhook_url=str(data.get("webhook_url") or ""),
            default_project=str(data.get("default_project") or ""),
        )

    def save_config(self, config: XWCopilotConfig) -> None:
        if self._repo is None:
            return
        payload = {
            "enabled": config.enabled,
            "mode": config.mode,
            "outlook_tenant_id": config.outlook_tenant_id,
            "outlook_client_id": config.outlook_client_id,
            "mailbox_address": config.mailbox_address,
            "webhook_url": config.webhook_url,
            "default_project": config.default_project,
        }
        self._repo.set_value_json(_CONFIG_KEY, json.dumps(payload, ensure_ascii=False, indent=2))

    def load_templates(self) -> list[dict[str, str]]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_TEMPLATES_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _TEMPLATES_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or "snippet"),
                    "content": str(item.get("content") or ""),
                }
            )
        return rows

    def save_templates(self, templates: list[dict[str, str]]) -> None:
        if self._repo is None:
            return
        clean: list[dict[str, str]] = []
        for item in templates:
            if not isinstance(item, dict):
                continue
            clean.append(
                {
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or "snippet"),
                    "content": str(item.get("content") or ""),
                }
            )
        self._repo.set_value_json(_TEMPLATES_KEY, json.dumps(clean, ensure_ascii=False, indent=2))
