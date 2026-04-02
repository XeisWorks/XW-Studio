"""Main application window with sidebar navigation and stacked content."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from xw_studio.core.printer_detect import discover_printers, evaluate_printer_status
from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey, PrinterStatus
from xw_studio.ui.sidebar import Sidebar
from xw_studio.ui.status_bar import StudioStatusBar

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """XeisWorks Studio main window: sidebar + content area."""

    def __init__(self, container: Container) -> None:
        super().__init__()
        self._container = container
        self._pages: dict[str, QWidget] = {}
        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._apply_printer_status()
        self._schedule_preload()

    def _setup_window(self) -> None:
        cfg = self._container.config.app.window
        self.setWindowTitle(self._container.config.app.name)
        self.resize(cfg.width, cfg.height)
        self.setMinimumSize(1024, 700)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = Sidebar(self._container)
        self._sidebar.module_selected.connect(self._navigate_to)
        layout.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._status_bar = StudioStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Bereit", 5000)

        from xw_studio.ui.home_view import HomeView

        self._register_page(ModuleKey.HOME, HomeView(self._container))

        from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView

        self._register_page(ModuleKey.RECHNUNGEN, TagesgeschaeftView(self._container))

        from xw_studio.ui.modules.products.view import ProductsView

        self._register_page(ModuleKey.PRODUCTS, ProductsView(self._container))

        from xw_studio.ui.modules.crm.view import CrmView

        self._register_page(ModuleKey.CRM, CrmView(self._container))

        from xw_studio.ui.modules.taxes.view import TaxesView

        self._register_page(ModuleKey.TAXES, TaxesView(self._container))

        from xw_studio.ui.modules.statistics.view import StatisticsView

        self._register_page(ModuleKey.STATISTICS, StatisticsView(self._container))

        from xw_studio.ui.modules.calculation.view import CalculationView

        self._register_page(ModuleKey.CALCULATION, CalculationView(self._container))

        from xw_studio.ui.modules.layout.view import LayoutView

        self._register_page(ModuleKey.LAYOUT, LayoutView(self._container))

        from xw_studio.ui.modules.wuedaramusi.view import WuedaraMusiView

        self._register_page(ModuleKey.WUEDARAMUSI, WuedaraMusiView(self._container))

        from xw_studio.ui.modules.travel_costs.view import TravelCostsView

        self._register_page(ModuleKey.TRAVEL_COSTS, TravelCostsView(self._container))

        from xw_studio.ui.modules.marketing.view import MarketingView

        self._register_page(ModuleKey.MARKETING, MarketingView(self._container))

        from xw_studio.ui.modules.notation.view import NotationView

        self._register_page(ModuleKey.NOTATION, NotationView(self._container))

        from xw_studio.ui.modules.xw_copilot.view import XWCopilotView

        self._register_page(ModuleKey.XW_COPILOT, XWCopilotView(self._container))

        from xw_studio.ui.modules.settings.view import SettingsView

        self._register_page(ModuleKey.SETTINGS, SettingsView(self._container))

        home = self._pages[ModuleKey.HOME.value]
        self._stack.setCurrentWidget(home)

    def _connect_signals(self) -> None:
        """Wire global signals to navigation."""
        signals = self._container.resolve(AppSignals)
        signals.navigate_to_module.connect(self._navigate_to)
        signals.show_home.connect(lambda: self._navigate_to(ModuleKey.HOME.value))
        signals.status_message.connect(self._status_bar.showMessage)

    def _apply_printer_status(self) -> None:
        """Traffic light in status bar; gate print actions via AppSignals."""
        names = list(self._container.config.printing.configured_printer_names)
        discovered = discover_printers()
        status = evaluate_printer_status(discovered, names)

        if status == PrinterStatus.GREEN:
            color, tooltip = "green", "Drucker: bereit (Ampel gruen)"
        elif status == PrinterStatus.YELLOW:
            color, tooltip = "yellow", "Drucker: teilweise (Ampel gelb)"
        else:
            color, tooltip = "red", "Drucker: nicht verfuegbar – Druck deaktiviert (Ampel rot)"

        self._status_bar.set_printer_status(color, tooltip)
        signals = self._container.resolve(AppSignals)
        signals.printer_status_changed.emit(status != PrinterStatus.RED)

    def _register_page(self, key: str | ModuleKey, widget: QWidget) -> None:
        key_str = key.value if isinstance(key, ModuleKey) else key
        self._pages[key_str] = widget
        self._stack.addWidget(widget)

    def _navigate_to(self, module_key: str) -> None:
        if module_key in self._pages:
            self._stack.setCurrentWidget(self._pages[module_key])
            logger.debug("Navigated to %s", module_key)
            return

        placeholder = self._create_placeholder(module_key)
        self._register_page(module_key, placeholder)
        self._stack.setCurrentWidget(placeholder)

    def _create_placeholder(self, module_key: str) -> QWidget:
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(f"Modul '{module_key}' wird geladen...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: #888;")
        layout.addWidget(label)
        return page

    def _schedule_preload(self) -> None:
        QTimer.singleShot(500, self._preload_modules)

    def _preload_modules(self) -> None:
        logger.debug("Pre-loading modules in background...")
