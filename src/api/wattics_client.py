"""Small validated client for the documented Wattics API v1 endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.api.exceptions import (
    WatticsAuthenticationError,
    WatticsError,
    WatticsNotFoundError,
    WatticsPermissionError,
    WatticsRateLimitError,
    WatticsResponseError,
    WatticsServerError,
)

LOGGER = logging.getLogger(__name__)


class WatticsClient:
    """Read-only Wattics client with retries, timeouts, and response validation."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.wattics.com/api/v1",
        timeout_seconds: float = 30,
        max_retries: int = 4,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not token or not token.strip():
            raise WatticsAuthenticationError("WATTICS_API_TOKEN is required.")
        self._token = token.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=0.75,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "Authorization": self._token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "ark-energy-assessment/1.0",
            }
        )

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "WatticsClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_organizations(self) -> List[Dict[str, Any]]:
        return self._list_resources("/organizations", required=("id", "name"))

    def list_sites(self, organization_id: Any) -> List[Dict[str, Any]]:
        return self._list_resources(
            "/sites",
            params={"organization_id": str(organization_id)},
            required=("id", "name"),
        )

    def list_meters(self, organization_id: Any, site_id: Any) -> List[Dict[str, Any]]:
        return self._list_resources(
            "/meters",
            params={
                "organization_id": str(organization_id),
                "site_id": str(site_id),
            },
            required=("id", "name"),
        )

    def get_meter(self, meter_id: Any) -> Dict[str, Any]:
        result = self._request_json("GET", f"/meters/{meter_id}")
        return dict(_require_mapping(result, f"/meters/{meter_id}", ("id", "name")))

    def list_paginated_resources(
        self,
        endpoint: str,
        *,
        params: Optional[Mapping[str, str]] = None,
        required: Iterable[str] = ("id", "name"),
        page_size: int = 100,
        maximum_pages: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Read documented partner-style pageSize/pageNumber list endpoints."""
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000.")
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be positive.")
        rows: List[Dict[str, Any]] = []
        base_params = dict(params or {})
        for page_number in range(1, maximum_pages + 1):
            page_params = {
                **base_params,
                "pageSize": str(page_size),
                "pageNumber": str(page_number),
            }
            result = self._request_json("GET", endpoint, params=page_params)
            page = _extract_resource_list(result, endpoint)
            for index, row in enumerate(page):
                rows.append(
                    dict(
                        _require_mapping(
                            row, f"{endpoint}[page={page_number}][{index}]", required
                        )
                    )
                )
            if len(page) < page_size:
                return rows
        raise WatticsResponseError(
            "Pagination exceeded the configured maximum page count.",
            endpoint=endpoint,
        )

    def get_raw_data(
        self,
        meter_id: Any,
        *,
        start_utc: datetime,
        end_utc: datetime,
        data_type: str = "active_power",
        show_phases: bool = False,
        detailed: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve one documented <=90-day UTC raw-data window."""
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("start_utc and end_utc must be timezone-aware.")
        if end_utc <= start_utc:
            raise ValueError("end_utc must be after start_utc.")
        if (end_utc - start_utc).days > 90:
            raise ValueError("Wattics raw-data requests cannot exceed 90 days.")
        endpoint = f"/meters/{meter_id}/raw_data"
        result = self._request_json(
            "GET",
            endpoint,
            params={
                "from": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "to": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "data_type": data_type,
                "show_phases": str(show_phases).lower(),
                "detailed": str(detailed).lower(),
            },
        )
        rows = _require_list(result, endpoint)
        for index, row in enumerate(rows):
            _require_mapping(row, f"{endpoint}[{index}]", ("timestamp",))
        return rows

    def _list_resources(
        self,
        endpoint: str,
        *,
        params: Optional[Mapping[str, str]] = None,
        required: Iterable[str],
    ) -> List[Dict[str, Any]]:
        """Read a list endpoint; paginate only when page metadata is present."""
        result = self._request_json("GET", endpoint, params=params)
        rows = _extract_resource_list(result, endpoint)
        validated = []
        for index, row in enumerate(rows):
            validated.append(
                dict(_require_mapping(row, f"{endpoint}[{index}]", required))
            )
        return validated

    def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Mapping[str, str]] = None,
    ) -> Any:
        url = urljoin(self.base_url, endpoint.lstrip("/"))
        safe_endpoint = "/" + endpoint.lstrip("/")
        LOGGER.debug(
            "Wattics request", extra={"method": method, "endpoint": safe_endpoint}
        )
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise WatticsError(
                "Wattics request timed out.", endpoint=safe_endpoint
            ) from exc
        except requests.RequestException as exc:
            raise WatticsError(
                "Wattics request failed before a response was received.",
                endpoint=safe_endpoint,
            ) from exc

        if response.status_code == 401:
            raise WatticsAuthenticationError(
                "Wattics rejected the API token.",
                status_code=401,
                endpoint=safe_endpoint,
            )
        if response.status_code == 403:
            raise WatticsPermissionError(
                "The API token is not permitted to access this resource.",
                status_code=403,
                endpoint=safe_endpoint,
            )
        if response.status_code == 404:
            raise WatticsNotFoundError(
                "The requested Wattics resource was not found.",
                status_code=404,
                endpoint=safe_endpoint,
            )
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            raise WatticsRateLimitError(
                "Wattics rate limit exceeded after retries"
                + (
                    f"; retry after about {retry_after} seconds."
                    if retry_after
                    else "."
                ),
                status_code=429,
                endpoint=safe_endpoint,
            )
        if response.status_code >= 500:
            raise WatticsServerError(
                "Wattics returned a server error after retries.",
                status_code=response.status_code,
                endpoint=safe_endpoint,
            )
        if response.status_code >= 400:
            raise WatticsError(
                "Wattics returned an unsuccessful response.",
                status_code=response.status_code,
                endpoint=safe_endpoint,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise WatticsResponseError(
                "Wattics returned non-JSON content.",
                status_code=response.status_code,
                endpoint=safe_endpoint,
            ) from exc


def _require_list(value: Any, endpoint: str) -> List[Any]:
    if not isinstance(value, list):
        raise WatticsResponseError(
            "Expected a JSON list response.",
            endpoint=endpoint,
            details=type(value).__name__,
        )
    return value


def _extract_resource_list(value: Any, endpoint: str) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        return value["data"]
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        return value["results"]
    raise WatticsResponseError(
        "Expected a JSON list response.",
        endpoint=endpoint,
        details=type(value).__name__,
    )


def _require_mapping(
    value: Any, endpoint: str, required: Iterable[str]
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WatticsResponseError(
            "Expected a JSON object.", endpoint=endpoint, details=type(value).__name__
        )
    missing = [field for field in required if field not in value]
    if missing:
        raise WatticsResponseError(
            f"Response object is missing required field(s): {', '.join(missing)}.",
            endpoint=endpoint,
        )
    return value


def _retry_after_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(
                0,
                int(
                    (
                        parsedate_to_datetime(value) - datetime.now().astimezone()
                    ).total_seconds()
                ),
            )
        except (TypeError, ValueError):
            return None
