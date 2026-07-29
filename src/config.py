"""Centralized, side-effect-free application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required or invalid configuration prevents an operation."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    wattics_api_token: Optional[str]
    wattics_api_base_url: str
    openai_api_key: Optional[str]
    openai_model: Optional[str]
    default_timezone: str
    cache_root: Path
    wattics_timeout_seconds: float
    wattics_max_retries: int
    max_tool_rounds: int
    cache_stale_hours: float
    data_auto_sync: bool
    data_sync_interval_minutes: int
    data_sync_on_startup: bool
    data_sync_before_query_if_stale: bool
    data_sync_max_retries: int
    data_sync_initial_lookback_days: int
    data_sync_lock_timeout_seconds: int
    openai_service_tier: str
    openai_input_price_per_million: Decimal
    openai_cached_input_price_per_million: Decimal
    openai_cache_write_price_per_million: Decimal
    openai_output_price_per_million: Decimal
    openai_pricing_source: str
    openai_pricing_config_date: date
    numeric_relative_tolerance: float
    numeric_absolute_tolerance: float
    percentage_tolerance: float
    answer_decimal_places: int

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Settings":
        load_dotenv(dotenv_path=env_file, override=False)
        settings = cls(
            wattics_api_token=_empty_to_none(os.getenv("WATTICS_API_TOKEN")),
            wattics_api_base_url=os.getenv(
                "WATTICS_API_BASE_URL", "https://api.wattics.com/api/v1"
            ).rstrip("/"),
            openai_api_key=_empty_to_none(os.getenv("OPENAI_API_KEY")),
            openai_model=_empty_to_none(os.getenv("OPENAI_MODEL", "gpt-5.6-terra")),
            default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC"),
            cache_root=Path(os.getenv("CACHE_ROOT", "data")),
            wattics_timeout_seconds=_positive_float(
                "WATTICS_TIMEOUT_SECONDS", os.getenv("WATTICS_TIMEOUT_SECONDS", "30")
            ),
            wattics_max_retries=_nonnegative_int(
                "WATTICS_MAX_RETRIES", os.getenv("WATTICS_MAX_RETRIES", "4")
            ),
            max_tool_rounds=_positive_int(
                "MAX_TOOL_ROUNDS", os.getenv("MAX_TOOL_ROUNDS", "6")
            ),
            cache_stale_hours=_positive_float(
                "CACHE_STALE_HOURS", os.getenv("CACHE_STALE_HOURS", "24")
            ),
            data_auto_sync=_boolean(
                "DATA_AUTO_SYNC", os.getenv("DATA_AUTO_SYNC", "true")
            ),
            data_sync_interval_minutes=_positive_int(
                "DATA_SYNC_INTERVAL_MINUTES",
                os.getenv("DATA_SYNC_INTERVAL_MINUTES", "60"),
            ),
            data_sync_on_startup=_boolean(
                "DATA_SYNC_ON_STARTUP", os.getenv("DATA_SYNC_ON_STARTUP", "true")
            ),
            data_sync_before_query_if_stale=_boolean(
                "DATA_SYNC_BEFORE_QUERY_IF_STALE",
                os.getenv("DATA_SYNC_BEFORE_QUERY_IF_STALE", "true"),
            ),
            data_sync_max_retries=_positive_int(
                "DATA_SYNC_MAX_RETRIES", os.getenv("DATA_SYNC_MAX_RETRIES", "3")
            ),
            data_sync_initial_lookback_days=_positive_int(
                "DATA_SYNC_INITIAL_LOOKBACK_DAYS",
                os.getenv("DATA_SYNC_INITIAL_LOOKBACK_DAYS", "365"),
            ),
            data_sync_lock_timeout_seconds=_positive_int(
                "DATA_SYNC_LOCK_TIMEOUT_SECONDS",
                os.getenv("DATA_SYNC_LOCK_TIMEOUT_SECONDS", "900"),
            ),
            openai_service_tier=os.getenv("OPENAI_SERVICE_TIER", "standard").strip(),
            openai_input_price_per_million=_decimal(
                "OPENAI_INPUT_PRICE_PER_MILLION",
                os.getenv("OPENAI_INPUT_PRICE_PER_MILLION", "2.50"),
            ),
            openai_cached_input_price_per_million=_decimal(
                "OPENAI_CACHED_INPUT_PRICE_PER_MILLION",
                os.getenv("OPENAI_CACHED_INPUT_PRICE_PER_MILLION", "0.25"),
            ),
            openai_cache_write_price_per_million=_decimal(
                "OPENAI_CACHE_WRITE_PRICE_PER_MILLION",
                os.getenv("OPENAI_CACHE_WRITE_PRICE_PER_MILLION", "3.125"),
            ),
            openai_output_price_per_million=_decimal(
                "OPENAI_OUTPUT_PRICE_PER_MILLION",
                os.getenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "15.00"),
            ),
            openai_pricing_source=os.getenv(
                "OPENAI_PRICING_SOURCE",
                "https://developers.openai.com/api/docs/pricing?latest-pricing=standard",
            ).strip(),
            openai_pricing_config_date=_date(
                "OPENAI_PRICING_CONFIG_DATE",
                os.getenv("OPENAI_PRICING_CONFIG_DATE", "2026-07-29"),
            ),
            numeric_relative_tolerance=_nonnegative_float(
                "NUMERIC_RELATIVE_TOLERANCE",
                os.getenv("NUMERIC_RELATIVE_TOLERANCE", "0.0005"),
            ),
            numeric_absolute_tolerance=_nonnegative_float(
                "NUMERIC_ABSOLUTE_TOLERANCE",
                os.getenv("NUMERIC_ABSOLUTE_TOLERANCE", "0.005"),
            ),
            percentage_tolerance=_nonnegative_float(
                "PERCENTAGE_TOLERANCE",
                os.getenv("PERCENTAGE_TOLERANCE", "0.05"),
            ),
            answer_decimal_places=_nonnegative_int(
                "ANSWER_DECIMAL_PLACES",
                os.getenv("ANSWER_DECIMAL_PLACES", "3"),
            ),
        )
        settings.validate_timezone()
        return settings

    def validate_timezone(self) -> None:
        try:
            ZoneInfo(self.default_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(
                f"DEFAULT_TIMEZONE={self.default_timezone!r} is not an IANA timezone."
            ) from exc

    def require(self, names: Iterable[str]) -> None:
        missing = []
        for name in names:
            value = {
                "WATTICS_API_TOKEN": self.wattics_api_token,
                "OPENAI_API_KEY": self.openai_api_key,
                "OPENAI_MODEL": self.openai_model,
            }.get(name)
            if not value:
                missing.append(name)
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(
                f"Missing required configuration: {joined}. "
                "Copy .env.example to .env and set the required value(s)."
            )

    @property
    def raw_dir(self) -> Path:
        return self.cache_root / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.cache_root / "processed"

    @property
    def metadata_dir(self) -> Path:
        return self.cache_root / "metadata"


def _empty_to_none(value: Optional[str]) -> Optional[str]:
    value = value.strip() if value else ""
    return value or None


def _positive_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric.") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return parsed


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return parsed


def _nonnegative_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must not be negative.")
    return parsed


def _nonnegative_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric.") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must not be negative.")
    return parsed


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _decimal(name: str, value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigurationError(f"{name} must be a decimal number.") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must not be negative.")
    return parsed


def _date(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must use YYYY-MM-DD.") from exc
