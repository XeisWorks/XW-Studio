"""Smoke tests for the Rechnungen daily-business view."""
from __future__ import annotations

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView
from xw_studio.ui.modules.rechnungen.view import RechnungenView


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def test_tagesgeschaeft_tabs_exist(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    expected = ["Rechnungen", "Mollie", "Gutscheine", "Downloads", "Refunds"]
    actual = [view._tabs.tabText(i) for i in range(view._tabs.count())]  # noqa: SLF001
    for label in expected:
        assert any(label in tab for tab in actual)


def test_rechnungen_toolbar_controls_exist(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    assert view._btn_more.text() == "Weitere laden"  # noqa: SLF001
    assert view._btn_print.text() == "PDF drucken…"  # noqa: SLF001
    assert view._btn_print_label.text() == "Label drucken…"  # noqa: SLF001
    assert view._btn_print_music.text() == "Noten drucken…"  # noqa: SLF001
    assert not view._btn_print.isEnabled()  # noqa: SLF001
    assert not view._btn_print_label.isEnabled()  # noqa: SLF001
    assert not view._btn_print_music.isEnabled()  # noqa: SLF001
