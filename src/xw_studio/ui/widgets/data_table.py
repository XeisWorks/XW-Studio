"""Generic sortable, filterable QTableView with search integration."""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtGui import QBrush, QColor
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QHeaderView, QTableView, QWidget


class SimpleTableModel(QAbstractTableModel):
    """Table model backed by a list of dicts."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._rows: list[dict[str, Any]] = []

    def set_data(self, rows: Sequence[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def append_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        """Append rows without clearing existing data."""
        row_list = list(rows)
        if not row_list:
            return
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n + len(row_list) - 1)
        self._rows.extend(row_list)
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row.get(col, ""))
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = row.get(f"__tooltip__{col}")
            if tip:
                return str(tip)
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            color = row.get(f"__fg__{col}")
            if isinstance(color, str) and color.strip():
                return QBrush(QColor(color))
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            color = row.get(f"__bg__{col}")
            if isinstance(color, str) and color.strip():
                return QBrush(QColor(color))
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = row.get(f"__align__{col}")
            if align == "center":
                return int(Qt.AlignmentFlag.AlignCenter)
            if align == "right":
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            return None
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def row_data(self, row: int) -> dict[str, Any]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return {}


class DataTable(QTableView):
    """Pre-configured QTableView with sorting, alternating rows, and selection."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = SimpleTableModel(columns)
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self._proxy)

        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setHighlightSections(False)

    def set_data(self, rows: Sequence[dict[str, Any]]) -> None:
        self._model.set_data(rows)

    def append_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        """Append rows to the underlying model."""
        self._model.append_rows(rows)

    def set_filter(self, text: str, column: int = 0) -> None:
        self._proxy.setFilterKeyColumn(column)
        self._proxy.setFilterFixedString(text)

    def selected_row_data(self) -> dict[str, Any] | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        source_idx = self._proxy.mapToSource(indexes[0])
        return self._model.row_data(source_idx.row())

    def selected_source_row(self) -> int | None:
        """0-based row index in the source model (proxy sort/filter aware)."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return int(self._proxy.mapToSource(indexes[0]).row())
