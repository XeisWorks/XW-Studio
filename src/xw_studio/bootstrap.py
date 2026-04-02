"""Register application services on the DI container."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker as SessionMaker

from xw_studio.core.container import Container
from xw_studio.core.database import create_session_factory
from xw_studio.services.calculation.service import CalculationService
from xw_studio.services.clearing.service import PaymentClearingService
from xw_studio.services.crm.service import CrmService
from xw_studio.services.daily_business.service import DailyBusinessService
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
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient
from xw_studio.services.sevdesk.part_client import PartClient
from xw_studio.services.statistics.service import StatisticsService
from xw_studio.services.wix.client import WixProductsClient
from xw_studio.services.clickup.client import ClickUpClient
from xw_studio.repositories import ApiSecretRepository, PcRegistryRepository, SettingKvRepository


def register_default_services(container: Container) -> None:
    """Wire default singletons (Phase 1–6 baseline)."""
    container.register(
        SecretService,
        lambda c: SecretService(
            c.config,
            c.resolve(ApiSecretRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        SevdeskConnection,
        lambda c: build_sevdesk_connection(
            c.config,
            api_token=c.resolve(SecretService).get_secret("SEVDESK_API_TOKEN"),
        ),
    )
    container.register(
        InvoiceClient,
        lambda c: InvoiceClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        ContactClient,
        lambda c: ContactClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        PartClient,
        lambda c: PartClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        InvoiceProcessingService,
        lambda c: InvoiceProcessingService(c.resolve(InvoiceClient)),
    )

    container.register(
        FinanzOnlineClient,
        lambda c: FinanzOnlineClient(
            c.config,
            secret_service=c.resolve(SecretService),
        ),
    )
    container.register(
        UvaService,
        lambda c: UvaService(c.config, c.resolve(FinanzOnlineClient)),
    )
    container.register(PaymentClearingService, lambda c: PaymentClearingService())
    container.register(ExpenseAuditService, lambda c: ExpenseAuditService())
    container.register(
        StatisticsService,
        lambda c: StatisticsService(c.resolve(InvoiceClient)),
    )
    container.register(
        WixProductsClient,
        lambda c: WixProductsClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        ClickUpClient,
        lambda c: ClickUpClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        CrmService,
        lambda c: CrmService(
            c.config,
            c.resolve(ContactClient) if (c.config.sevdesk.api_token or "").strip() else None,
        ),
    )
    container.register(LayoutToolsService, lambda c: LayoutToolsService())
    container.register(
        CalculationService,
        lambda c: CalculationService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        DailyBusinessService,
        lambda c: DailyBusinessService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        InventoryService,
        lambda c: InventoryService(
            c.config,
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )

    container.register(
        MarketingIdeasStore,
        lambda c: MarketingIdeasStore(default_marketing_ideas_path()),
    )
    container.register(
        NotationIdeasStore,
        lambda c: NotationIdeasStore(default_notation_ideas_path()),
    )

    # PostgreSQL persistence layer: only register when DATABASE_URL is configured.
    # This keeps local dev/test environments (no DB) working without needing env vars.
    if (container.config.database_url or "").strip():
        container.register(SessionMaker, lambda c: create_session_factory(c.config))
        container.register(PcRegistryRepository, lambda c: PcRegistryRepository(c.resolve(SessionMaker)))
        container.register(
            SettingKvRepository,
            lambda c: SettingKvRepository(c.resolve(SessionMaker)),
        )
        container.register(
            ApiSecretRepository,
            lambda c: ApiSecretRepository(c.resolve(SessionMaker)),
        )
