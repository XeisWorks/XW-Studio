"""Register application services on the DI container."""
from __future__ import annotations

from xw_studio.core.container import Container
from xw_studio.services.calculation.service import CalculationService
from xw_studio.services.clearing.service import PaymentClearingService
from xw_studio.services.crm.service import CrmService
from xw_studio.services.expenses.service import ExpenseAuditService
from xw_studio.services.finanzonline import FinanzOnlineClient, UvaService
from xw_studio.services.http_client import SevdeskConnection, build_sevdesk_connection
from xw_studio.services.ideas.stores import (
    MarketingIdeasStore,
    NotationIdeasStore,
    default_marketing_ideas_path,
    default_notation_ideas_path,
)
from xw_studio.services.inventory.service import InventoryService
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.layout.service import LayoutToolsService
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient
from xw_studio.services.statistics.service import StatisticsService


def register_default_services(container: Container) -> None:
    """Wire default singletons (Phase 1–6 baseline)."""
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

    container.register(FinanzOnlineClient, lambda c: FinanzOnlineClient(c.config))
    container.register(
        UvaService,
        lambda c: UvaService(c.config, c.resolve(FinanzOnlineClient)),
    )
    container.register(PaymentClearingService, lambda c: PaymentClearingService())
    container.register(ExpenseAuditService, lambda c: ExpenseAuditService())
    container.register(StatisticsService, lambda c: StatisticsService())
    container.register(CrmService, lambda c: CrmService(c.config))
    container.register(LayoutToolsService, lambda c: LayoutToolsService())
    container.register(CalculationService, lambda c: CalculationService())
    container.register(InventoryService, lambda c: InventoryService())

    container.register(
        MarketingIdeasStore,
        lambda c: MarketingIdeasStore(default_marketing_ideas_path()),
    )
    container.register(
        NotationIdeasStore,
        lambda c: NotationIdeasStore(default_notation_ideas_path()),
    )
