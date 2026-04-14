"""SMTP-backed mail delivery for invoice/customer messages."""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import html
import os
import re
import smtplib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService


@dataclass(frozen=True)
class MailAttachment:
    """One binary attachment for a mail message."""

    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass(frozen=True)
class SmtpConfig:
    """Resolved SMTP configuration from DB/env secrets."""

    host: str
    port: int
    username: str
    password: str
    sender: str
    use_starttls: bool
    use_ssl: bool


class MailDeliveryService:
    """Render and send multipart customer mails via SMTP."""

    def __init__(self, *, secret_service: "SecretService | None" = None) -> None:
        self._secrets = secret_service

    def is_configured(self) -> bool:
        try:
            config = self.load_smtp_config()
        except RuntimeError:
            return False
        return bool(config.host and config.sender)

    def load_smtp_config(self) -> SmtpConfig:
        host = self._secret_or_env("SMTP_HOST")
        port_raw = self._secret_or_env("SMTP_PORT", "587")
        username = self._secret_or_env("SMTP_USERNAME")
        password = self._secret_or_env("SMTP_PASSWORD")
        sender = self._secret_or_env("SMTP_FROM", username)
        use_starttls = self._secret_or_env("SMTP_STARTTLS", "1").lower() not in {"0", "false", "no"}
        use_ssl = self._secret_or_env("SMTP_SSL", "0").lower() in {"1", "true", "yes"}

        missing = [name for name, value in (("SMTP_HOST", host), ("SMTP_FROM", sender)) if not value]
        if missing:
            raise RuntimeError(f"SMTP-Konfiguration fehlt: {', '.join(missing)}")

        try:
            port = int(port_raw)
        except ValueError:
            port = 587

        return SmtpConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            sender=sender,
            use_starttls=use_starttls,
            use_ssl=use_ssl,
        )

    def send_mail(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str = "",
        attachments: list[MailAttachment] | None = None,
    ) -> None:
        config = self.load_smtp_config()
        message = EmailMessage()
        message["From"] = config.sender
        message["To"] = str(to_email or "").strip()
        message["Subject"] = str(subject or "").strip()
        message.set_content(str(text_body or "").strip())

        html_content = str(html_body or "").strip()
        if html_content:
            message.add_alternative(html_content, subtype="html")

        for attachment in attachments or []:
            if not attachment.content:
                continue
            maintype, _, subtype = str(attachment.mime_type or "application/octet-stream").partition("/")
            if not maintype or not subtype:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=str(attachment.filename or "attachment.bin"),
            )

        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=20) as smtp:
                if config.username:
                    smtp.login(config.username, config.password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(config.host, config.port, timeout=20) as smtp:
            if config.use_starttls:
                smtp.starttls()
            if config.username:
                smtp.login(config.username, config.password)
            smtp.send_message(message)

    @staticmethod
    def plain_text_to_html(value: str) -> str:
        normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return "<p></p>"
        paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()]
        html_parts: list[str] = []
        for paragraph in paragraphs:
            escaped = html.escape(paragraph).replace("\n", "<br>")
            html_parts.append(f"<p>{escaped}</p>")
        return "\n".join(html_parts)

    def _secret_or_env(self, key: str, default: str = "") -> str:
        value = ""
        if self._secrets is not None:
            value = str(self._secrets.get_secret(key) or "").strip()
        if value:
            return value
        return str(os.getenv(key) or default).strip()
