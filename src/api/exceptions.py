"""Typed exceptions for safe API error handling."""

from __future__ import annotations

from typing import Any, Optional


class WatticsError(RuntimeError):
    """Base class for Wattics client errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        endpoint: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.details = details

    def as_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": str(self),
            "status_code": self.status_code,
            "endpoint": self.endpoint,
        }


class WatticsAuthenticationError(WatticsError):
    """The API token is missing or invalid."""


class WatticsPermissionError(WatticsError):
    """The token is valid but cannot access the requested resource."""


class WatticsNotFoundError(WatticsError):
    """The requested resource does not exist or is not visible."""


class WatticsRateLimitError(WatticsError):
    """The API rate limit remained exhausted after retries."""


class WatticsServerError(WatticsError):
    """The remote service failed after retries."""


class WatticsResponseError(WatticsError):
    """The response did not match the documented/validated structure."""
