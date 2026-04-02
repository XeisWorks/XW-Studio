"""Provisionen / Kalkulation module."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xw_studio.core.worker import BackgroundWorker
from xw_studio.services.calculation.service import (
    ArticleEntry,
    CalculationService,
    calculate_royalty,
)

if TYPE_CHECKING:
    from xw_studio.core.container import Container

logger = logging.getLogger(__name__)

_ARTICLE_HEADERS = ["Titel", "Brutto EUR", "MwSt %", "Provision %", "Netto EUR", "MwSt EUR", "Provision EUR", "Notiz"]


class CalculationView(QWidget):
    """Royalty and cost calculation — article table + manual calculator."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._articles: list[ArticleEntry] = []
        self._worker: BackgroundWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_articles_tab(), "Artikelliste")
        tabs.addTab(self._build_calc_tab(), "Schnellrechner")
        root.addWidget(tabs)

        self._load_articles()

    # ------------------------------------------------------------------
    # Tab 1: Article list with computed royalties
    # ------------------------------------------------------------------

    def _build_articles_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._art_status = QLabel("Artikelliste laden...")
        bar.addWidget(self._art_status)
        bar.addStretch()
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.clicked.connect(self._load_articles)
        bar.addWidget(refresh_btn)
        lay.addLayout(bar)

        self._art_table = QTableWidget(0, len(_ARTICLE_HEADERS))
        self._art_table.setHorizontalHeaderLabels(_ARTICLE_HEADERS)
        self._art_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._art_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._art_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._art_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._art_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._art_table)

        info = QLabel("Artikelliste in DB: Einstellungen > Schluessel-Verwaltung > calculation.articles (JSON-Array).")
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        lay.addWidget(info)
        return page

    def _load_articles(self) -> None:
        svc: CalculationService = self._container.resolve(CalculationService)

        def job() -> list[ArticleEntry]:
            return svc.load_articles()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_articles_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_articles_loaded(self, rows: object) -> None:
        if not isinstance(rows, list):
            return
        self._articles = rows  # type: ignore[assignment]
        if not self._articles:
            self._art_status.setText("Keine Artikel — bitte calculation.articles in Einstellungen befuellen.")
        else:
            self._art_status.setText(f"{len(self._articles)} Artikel geladen")
        self._populate_articles(self._articles)

    def _populate_articles(self, items: list[ArticleEntry]) -> None:
        tbl = self._art_table
        tbl.setRowCount(0)
        for art in items:
            res = calculate_royalty(art.gross_price, vat_pct=art.vat_pct, royalty_pct=art.royalty_pct)
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(art.title))

            def _eur(v: float) -> QTableWidgetItem:
                item = QTableWidgetItem(f"{v:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                return item

            def _pct(v: float) -> QTableWidgetItem:
                item = QTableWidgetItem(f"{v:.1f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                return item

            tbl.setItem(r, 1, _eur(art.gross_price))
            tbl.setItem(r, 2, _pct(art.vat_pct))
            tbl.setItem(r, 3, _pct(art.royalty_pct))
            tbl.setItem(r, 4, _eur(res.net))
            tbl.setItem(r, 5, _eur(res.vat_amount))
            tbl.setItem(r, 6, _eur(res.royalty_amount))
            tbl.setItem(r, 7, QTableWidgetItem(art.note))
        for col in range(1, 7):
            tbl.resizeColumnToContents(col)

    # ------------------------------------------------------------------
    # Tab 2: Quick calculator
    # ------------------------------------------------------------------

    def _build_calc_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        grp = QGroupBox("Eingabe")
        form = QFormLayout(grp)

        self._calc_gross = QDoubleSpinBox()
        self._calc_gross.setRange(0.0, 99999.99)
        self._calc_gross.setDecimals(2)
        self._calc_gross.setSuffix(" EUR")
        self._calc_gross.setValue(10.00)
        form.addRow("Bruttopreis:", self._calc_gross)

        self._calc_vat = QDoubleSpinBox()
        self._calc_vat.setRange(0.0, 100.0)
        self._calc_vat.setDecimals(1)
        self._calc_vat.setSuffix(" %")
        self._calc_vat.setValue(10.0)
        form.addRow("MwSt-Satz:", self._calc_vat)

        self._calc_royalty = QDoubleSpinBox()
        self._calc_royalty.setRange(0.0, 100.0)
        self._calc_royalty.setDecimals(2)
        self._calc_royalty.setSuffix(" %")
        self._calc_royalty.setValue(0.0)
        form.addRow("Provisionssatz (auf Netto):", self._calc_royalty)

        lay.addWidget(grp)

        calc_btn = QPushButton("Berechnen")
        calc_btn.clicked.connect(self._run_calc)
        lay.addWidget(calc_btn)

        res_grp = QGroupBox("Ergebnis")
        res_lay = QFormLayout(res_grp)

        self._res_net = QLabel("—")
        res_lay.addRow("Nettobetrag:", self._res_net)
        self._res_vat = QLabel("—")
        res_lay.addRow("MwSt-Betrag:", self._res_vat)
        self._res_provision = QLabel("—")
        res_lay.addRow("Provision:", self._res_provision)
        self._res_net_after = QLabel("—")
        res_lay.addRow("Netto nach Provision:", self._res_net_after)
        lay.addWidget(res_grp)

        lay.addStretch()
        return page

    def _run_calc(self) -> None:
        gross = self._calc_gross.value()
        vat = self._calc_vat.value()
        prov = self._calc_royalty.value()
        res = calculate_royalty(gross, vat_pct=vat, royalty_pct=prov)
        self._res_net.setText(f"{res.net:.4f} EUR")
        self._res_vat.setText(f"{res.vat_amount:.4f} EUR")
        self._res_provision.setText(f"{res.royalty_amount:.4f} EUR")
        self._res_net_after.setText(f"{res.net_after_royalty:.4f} EUR")

    def _on_error(self, exc: BaseException) -> None:
        logger.exception("CalculationView error: %s", exc)
        QMessageBox.critical(self, "Fehler", str(exc))
