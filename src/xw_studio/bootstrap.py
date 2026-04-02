"""Register application services on the DI container."""
from __future__ import annotations

from xw_studio.core.container import Container
from xw_studio.services.http_client import SevdeskConnection, build_sevdesk_connection
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient


def register_default_services(container: Container) -> None:
    """Wire default singletons for Phase 1+."""
    container.register(SevdeskConnection, lambda c: build_sevdesk_connection(c.config))
    container.register(
        InvoiceClient,
        lambda c: InvoiceClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        ContactClient,
        lambda c: ContactClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        InvoiceProcessingService,
        lambda c: InvoiceProcessingService(c.resolve(InvoiceClient)),
    )
