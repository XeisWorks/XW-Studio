"""Typed exception hierarchy for XeisWorks Studio."""


class XwStudioError(Exception):
    """Base exception for all XeisWorks Studio errors."""


class ApiError(XwStudioError):
    """Base for all API communication errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SevdeskApiError(ApiError):
    """Error communicating with sevDesk API."""


class WixApiError(ApiError):
    """Error communicating with Wix API."""


class MollieApiError(ApiError):
    """Error communicating with Mollie API."""


class PrintError(XwStudioError):
    """Error during printing operations."""


class ConfigError(XwStudioError):
    """Error in configuration loading or validation."""


class DatabaseError(XwStudioError):
    """Error in database operations."""
