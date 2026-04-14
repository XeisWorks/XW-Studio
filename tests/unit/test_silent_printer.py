from __future__ import annotations

from PySide6.QtCore import QRectF

from xw_studio.services.printing.silent_printer import _aspect_fit_rect


def test_aspect_fit_rect_preserves_a4_proportions_inside_landscape_paint_rect() -> None:
    paint_rect = QRectF(0.0, 0.0, 7016.0, 4961.0)

    target = _aspect_fit_rect(paint_rect, 2480.0, 3508.0)

    assert abs(target.height() - 4961.0) < 0.1
    assert abs(target.width() - 3507.2) < 0.2
    assert abs(target.x() - ((7016.0 - target.width()) / 2.0)) < 0.1
    assert abs(target.y()) < 0.1
