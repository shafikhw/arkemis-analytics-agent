"""OpenAI usage extraction and configurable token-cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional

MILLION = Decimal("1000000")


@dataclass(frozen=True)
class PricingConfiguration:
    model: str
    service_tier: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    cache_write_per_million: Decimal
    output_per_million: Decimal
    source: str
    configured_on: date

    @classmethod
    def terra_standard(cls) -> "PricingConfiguration":
        return cls(
            model="gpt-5.6-terra",
            service_tier="standard",
            input_per_million=Decimal("2.50"),
            cached_input_per_million=Decimal("0.25"),
            cache_write_per_million=Decimal("3.125"),
            output_per_million=Decimal("15.00"),
            source=(
                "https://developers.openai.com/api/docs/pricing?latest-pricing=standard"
            ),
            configured_on=date(2026, 7, 29),
        )


def pricing_from_settings(settings: Any) -> PricingConfiguration:
    return PricingConfiguration(
        model=str(settings.openai_model or ""),
        service_tier=str(settings.openai_service_tier),
        input_per_million=Decimal(settings.openai_input_price_per_million),
        cached_input_per_million=Decimal(
            settings.openai_cached_input_price_per_million
        ),
        cache_write_per_million=Decimal(settings.openai_cache_write_price_per_million),
        output_per_million=Decimal(settings.openai_output_price_per_million),
        source=str(settings.openai_pricing_source),
        configured_on=settings.openai_pricing_config_date,
    )


def empty_usage(
    pricing: Optional[PricingConfiguration],
    *,
    model: Optional[str] = None,
    service_tier: Optional[str] = None,
) -> Dict[str, Any]:
    selected_model = model or (pricing.model if pricing else None)
    selected_tier = service_tier or (pricing.service_tier if pricing else None)
    return {
        "model": selected_model,
        "service_tier": selected_tier,
        "input_tokens": None,
        "uncached_input_tokens": None,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "estimated_cost_usd_exact": None,
        "pricing_source": pricing.source if pricing else None,
        "pricing_configuration_date": (
            pricing.configured_on.isoformat() if pricing else None
        ),
        "assumptions": [],
    }


def extract_usage(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    response_model = getattr(response, "model", None)
    response_tier = getattr(response, "service_tier", None)
    if usage is None:
        return {
            "model": response_model,
            "service_tier": _display_service_tier(response_tier),
            "input_tokens": None,
            "cached_input_tokens": None,
            "cache_write_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cached_input_reported": False,
            "cache_write_reported": False,
        }

    details = _get(usage, "input_tokens_details")
    if details is None:
        details = _get(usage, "prompt_tokens_details")
    cached = _get(details, "cached_tokens")
    cache_write = _get(details, "cache_write_tokens")
    input_tokens = _first(
        _get(usage, "input_tokens"),
        _get(usage, "prompt_tokens"),
    )
    output_tokens = _first(
        _get(usage, "output_tokens"),
        _get(usage, "completion_tokens"),
    )
    total_tokens = _get(usage, "total_tokens")
    return {
        "model": response_model,
        "service_tier": _display_service_tier(response_tier),
        "input_tokens": _optional_int(input_tokens),
        "cached_input_tokens": _optional_int(cached),
        "cache_write_tokens": _optional_int(cache_write),
        "output_tokens": _optional_int(output_tokens),
        "total_tokens": _optional_int(total_tokens),
        "cached_input_reported": cached is not None,
        "cache_write_reported": cache_write is not None,
    }


def merge_usage(
    total: Dict[str, Any],
    addition: Mapping[str, Any],
    *,
    pricing: Optional[PricingConfiguration] = None,
) -> None:
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "total_tokens",
    ):
        value = addition.get(key)
        if value is not None:
            total[key] = int(total.get(key) or 0) + int(value)

    if addition.get("model"):
        total["model"] = str(addition["model"])
    if addition.get("service_tier"):
        total["service_tier"] = str(addition["service_tier"])

    assumptions = list(total.get("assumptions") or [])
    if not addition.get("cached_input_reported", False):
        assumption = "Cached-input tokens were not reported and are treated as zero."
        if assumption not in assumptions:
            assumptions.append(assumption)
    if not addition.get("cache_write_reported", False):
        assumption = "Cache-write tokens were not reported and are treated as zero."
        if assumption not in assumptions:
            assumptions.append(assumption)
    total["assumptions"] = assumptions
    apply_pricing(total, pricing)


def apply_pricing(
    usage: Dict[str, Any],
    pricing: Optional[PricingConfiguration],
) -> None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if usage.get("total_tokens") is None and (
        input_tokens is not None or output_tokens is not None
    ):
        usage["total_tokens"] = int(input_tokens or 0) + int(output_tokens or 0)
    if input_tokens is None or output_tokens is None or pricing is None:
        usage["estimated_cost_usd"] = None
        usage["estimated_cost_usd_exact"] = None
        usage["uncached_input_tokens"] = None
        return

    configured_model = pricing.model.casefold()
    actual_model = str(usage.get("model") or pricing.model).casefold()
    if configured_model and not actual_model.startswith(configured_model):
        usage["estimated_cost_usd"] = None
        usage["estimated_cost_usd_exact"] = None
        usage["uncached_input_tokens"] = None
        return

    cached = int(usage.get("cached_input_tokens") or 0)
    cache_write = int(usage.get("cache_write_tokens") or 0)
    uncached = max(int(input_tokens) - cached, 0)
    cost = (
        Decimal(uncached) / MILLION * pricing.input_per_million
        + Decimal(cached) / MILLION * pricing.cached_input_per_million
        + Decimal(cache_write) / MILLION * pricing.cache_write_per_million
        + Decimal(int(output_tokens)) / MILLION * pricing.output_per_million
    )
    usage["uncached_input_tokens"] = uncached
    usage["estimated_cost_usd_exact"] = format(cost.normalize(), "f")
    usage["estimated_cost_usd"] = float(cost)
    usage["pricing_source"] = pricing.source
    usage["pricing_configuration_date"] = pricing.configured_on.isoformat()


def _get(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def _display_service_tier(value: Any) -> Any:
    return "standard" if value == "default" else value
