"""UI test: DOWNLOAD-LINKS action opens Wix dashboard URL."""
from __future__ import annotations

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.ui.modules.rechnungen.view import RechnungenView


class _FakeWixOrdersClient:
    def __init__(self, url: str) -> None:
        self._url = url

    def resolve_order_dashboard_url(self, reference: str) -> str:
        _ = reference
        return self._url


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def test_download_links_action_opens_url(qtbot: object, monkeypatch: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    summary = InvoiceSummary.model_validate(
        {
            "id": "42",
            "invoiceNumber": "RE-42",
            "order_reference": "10023",
        }
    )

    expected_url = "https://manage.wix.com/dashboard/site/order/abc123"
    fake_wix = _FakeWixOrdersClient(expected_url)

    original_resolve = container.resolve

    def resolve_override(service_type: type):
        if service_type is WixOrdersClient:
            return fake_wix
        return original_resolve(service_type)

    monkeypatch.setattr(container, "resolve", resolve_override)

    called: dict[str, str] = {"url": ""}

    def open_url_spy(qurl):
        called["url"] = qurl.toString()
        return True

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.view.QDesktopServices.openUrl", open_url_spy)

    view._open_wix_download_links(summary)  # noqa: SLF001

    assert called["url"] == expected_url
