"""Printer discovery and traffic-light status for multi-PC support."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from xw_studio.core.types import PrinterStatus

logger = logging.getLogger(__name__)


@dataclass
class PrinterInfo:
    name: str
    is_default: bool = False
    is_network: bool = False


def discover_printers() -> list[PrinterInfo]:
    """List available printers on this machine."""
    try:
        import win32print  # type: ignore[import-untyped]
        printers = []
        default_name = win32print.GetDefaultPrinter()
        for flags, _desc, name, _comment in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        ):
            printers.append(PrinterInfo(
                name=name,
                is_default=(name == default_name),
                is_network=bool(flags & win32print.PRINTER_ENUM_CONNECTIONS),
            ))
        return printers
    except ImportError:
        logger.warning("pywin32 not available — printer detection disabled")
        return []
    except Exception as exc:
        logger.error("Printer discovery failed: %s", exc)
        return []


def evaluate_printer_status(
    available: list[PrinterInfo],
    configured_names: list[str],
) -> PrinterStatus:
    """Determine traffic-light status based on available vs configured printers."""
    if not configured_names:
        return PrinterStatus.GREEN

    available_names = {p.name for p in available}
    matched = [n for n in configured_names if n in available_names]

    if not matched:
        return PrinterStatus.RED
    if len(matched) < len(configured_names):
        return PrinterStatus.YELLOW
    return PrinterStatus.GREEN
