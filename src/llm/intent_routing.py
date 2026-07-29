"""Deterministic hints and direct plans for obvious single-tool requests."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, Mapping, Optional, Sequence

from src.data.discovery import normalize_name
from src.llm.scope import ScopeDecision
from src.tools.registry import ToolRegistry

MONTHS = {
    name.casefold(): index for index, name in enumerate(calendar.month_name) if name
}
MONTHS.update(
    {name.casefold(): index for index, name in enumerate(calendar.month_abbr) if name}
)


@dataclass(frozen=True)
class ToolPlan:
    tool_name: str
    arguments: Dict[str, Any]
    basis: str


def direct_tool_plan(
    question: str,
    decision: ScopeDecision,
    registry: ToolRegistry,
    *,
    today: date,
    history: Optional[Sequence[Mapping[str, str]]] = None,
) -> Optional[ToolPlan]:
    plans = direct_tool_plans(
        question,
        decision,
        registry,
        today=today,
        history=history,
    )
    return plans[0] if len(plans) == 1 else None


def direct_tool_plans(
    question: str,
    decision: ScopeDecision,
    registry: ToolRegistry,
    *,
    today: date,
    history: Optional[Sequence[Mapping[str, str]]] = None,
) -> list[ToolPlan]:
    special = _multi_entity_plans(question, decision, registry)
    if special:
        return special
    plan = _single_tool_plan(
        question,
        decision,
        registry,
        today=today,
        history=history,
    )
    return [plan] if plan is not None else []


def _single_tool_plan(
    question: str,
    decision: ScopeDecision,
    registry: ToolRegistry,
    *,
    today: date,
    history: Optional[Sequence[Mapping[str, str]]] = None,
) -> Optional[ToolPlan]:
    tool_name = decision.suggested_tool
    if not tool_name or tool_name in {"compare_periods", "compare_entities"}:
        return None
    combined = _context_text(question, history)
    lowered = combined.casefold()
    if any(
        marker in lowered
        for marker in (
            "between the two",
            "between both",
            "each organization",
            "each site",
            "compare organizations",
        )
    ):
        return None

    entities = _resolve_entities(combined, registry)
    filters = {
        "organization": entities.get("organization"),
        "site": entities.get("site"),
        "meter": entities.get("meter"),
    }
    period = _parse_period(combined, today)
    if period is None and tool_name in {
        "get_consumption_summary",
        "estimate_baseload",
        "get_peak_demand",
        "calculate_load_factor",
        "compare_weekday_weekend",
        "rank_sites",
        "detect_anomalies",
        "get_load_profile",
    }:
        period = _latest_closed_month_for_filters(registry, filters)

    if tool_name == "get_data_quality":
        arguments: Dict[str, Any] = {
            **filters,
            "start_date": period[0].isoformat() if period else None,
            "end_date": period[1].isoformat() if period else None,
        }
    else:
        if period is None:
            return None
        arguments = {
            **filters,
            "start_date": period[0].isoformat(),
            "end_date": period[1].isoformat(),
        }
        if tool_name == "get_consumption_summary":
            arguments["resolution"] = _resolution(lowered)
        elif tool_name == "estimate_baseload":
            arguments.update(
                {
                    "group_by": "meter" if "each meter" in lowered else "site",
                    "percentile": 10.0,
                    "minimum_observations": 96,
                }
            )
        elif tool_name == "compare_weekday_weekend":
            arguments["include_hourly_profile"] = "hour" in lowered
        elif tool_name == "rank_sites":
            arguments["metric"] = _ranking_metric(lowered)
        elif tool_name == "detect_anomalies":
            arguments.update(
                {
                    "threshold": 3.5,
                    "minimum_samples": 4,
                    "max_results": 100,
                }
            )
        elif tool_name == "get_load_profile":
            arguments["normalized"] = any(
                term in lowered for term in ("normalize", "normalise", "shape")
            )
    try:
        prepared = registry.prepare(tool_name, arguments)
    except Exception:
        return None
    return ToolPlan(
        tool_name=tool_name,
        arguments=prepared,
        basis="deterministic intent, entity alias, and period resolution",
    )


def _multi_entity_plans(
    question: str,
    decision: ScopeDecision,
    registry: ToolRegistry,
) -> list[ToolPlan]:
    lowered = question.casefold()
    try:
        hierarchy = registry.tools.cache.load_hierarchy()
    except Exception:
        return []

    if (
        decision.suggested_tool == "compare_periods"
        and "week-over-week" in lowered
        and any(
            term in lowered
            for term in ("organization", "organisations", "organizations")
        )
    ):
        plans = []
        for organization in hierarchy.organizations:
            window = _latest_complete_week_window(registry, organization.id)
            if window is None:
                return []
            previous_start, current_start, current_end = window
            arguments = registry.prepare(
                "compare_periods",
                {
                    "organization": organization.id,
                    "site": None,
                    "meter": None,
                    "current_start_date": current_start.isoformat(),
                    "current_end_date": current_end.isoformat(),
                    "previous_start_date": previous_start.isoformat(),
                    "previous_end_date": current_start.isoformat(),
                },
            )
            plans.append(
                ToolPlan(
                    tool_name="compare_periods",
                    arguments=arguments,
                    basis=(
                        "deterministic week-over-week comparison using each "
                        "organization's latest two complete cached weeks"
                    ),
                )
            )
        return plans

    weekend_comparison = (
        decision.suggested_tool == "compare_weekday_weekend"
        and "between" in lowered
        and "organization" in lowered
    )
    site_baseload = (
        decision.suggested_tool == "estimate_baseload" and "each site" in lowered
    )
    if not weekend_comparison and not site_baseload:
        return []
    common_period = _latest_common_complete_month(registry)
    if common_period is None:
        return []
    start, end = common_period
    if weekend_comparison:
        arguments = registry.prepare(
            "compare_entities",
            {
                "entity_kind": "organization",
                "metric": "weekday_weekend_ratio",
                "organization": None,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        return [
            ToolPlan(
                tool_name="compare_entities",
                arguments=arguments,
                basis=(
                    "deterministic cross-organization weekend-profile "
                    "comparison over the latest common complete cached month"
                ),
            )
        ]
    if site_baseload:
        arguments = registry.prepare(
            "estimate_baseload",
            {
                "organization": None,
                "site": None,
                "meter": None,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "group_by": "site",
                "percentile": 10.0,
                "minimum_observations": 96,
            },
        )
        return [
            ToolPlan(
                tool_name="estimate_baseload",
                arguments=arguments,
                basis=(
                    "deterministic per-site baseload over the latest common "
                    "complete cached month"
                ),
            )
        ]
    return []


def _latest_complete_week_window(
    registry: ToolRegistry, organization_id: str
) -> Optional[tuple[date, date, date]]:
    data = registry.tools.cache.read_energy(organization=organization_id)
    dates = _all_local_dates(data)
    if not dates:
        return None
    latest = max(dates)
    current_end = latest - timedelta(days=latest.weekday())
    for _ in range(60):
        current_start = current_end - timedelta(days=7)
        previous_start = current_start - timedelta(days=7)
        required = {previous_start + timedelta(days=offset) for offset in range(14)}
        if required <= dates:
            return previous_start, current_start, current_end
        current_end -= timedelta(days=7)
    return None


def _latest_common_complete_month(
    registry: ToolRegistry,
) -> Optional[tuple[date, date]]:
    hierarchy = registry.tools.cache.load_hierarchy()
    ranges = []
    for organization in hierarchy.organizations:
        data = registry.tools.cache.read_energy(organization=organization.id)
        if data.empty:
            continue
        local_dates = _all_local_dates(data)
        if local_dates:
            ranges.append((min(local_dates), max(local_dates)))
    if not ranges:
        return None
    earliest = max(row[0] for row in ranges)
    latest = min(row[1] for row in ranges)
    start = latest.replace(day=1)
    end = _next_month(start)
    if latest < end - timedelta(days=1):
        end = start
        start = (start - timedelta(days=1)).replace(day=1)
    if start < earliest or end <= start:
        return None
    return start, end


def _latest_closed_month_for_filters(
    registry: ToolRegistry,
    filters: Mapping[str, Optional[str]],
) -> Optional[tuple[date, date]]:
    try:
        data = registry.tools.cache.read_energy(
            organization=filters.get("organization"),
            site=filters.get("site"),
            meter=filters.get("meter"),
        )
    except (AttributeError, OSError, ValueError):
        return None
    dates = _all_local_dates(data)
    if not dates:
        return None
    earliest = min(dates)
    latest = max(dates)
    candidate = latest.replace(day=1)
    if latest < _next_month(candidate) - timedelta(days=1):
        candidate = (candidate - timedelta(days=1)).replace(day=1)
    for _ in range(24):
        end = _next_month(candidate)
        if candidate >= earliest and end - timedelta(days=1) <= latest:
            return candidate, end
        candidate = (candidate - timedelta(days=1)).replace(day=1)
    return None


def _latest_local_date(data: Any) -> Optional[date]:
    dates = _all_local_dates(data)
    return max(dates) if dates else None


def _all_local_dates(data: Any) -> set[date]:
    if data.empty:
        return set()
    dates: set[date] = set()
    for timezone_name, group in data.groupby("timezone"):
        local = group["timestamp"].dt.tz_convert(str(timezone_name))
        dates.update(local.dt.date.tolist())
    return dates


def constrained_tool_choice(tool_name: Optional[str]) -> Optional[dict]:
    if not tool_name:
        return None
    return {"type": "function", "name": tool_name}


def _context_text(
    question: str,
    history: Optional[Sequence[Mapping[str, str]]],
) -> str:
    if not history:
        return question
    relevant = [
        item.get("content", "")
        for item in history[-6:]
        if item.get("role") in {"user", "assistant"}
    ]
    return "\n".join([*relevant, question])


def _resolve_entities(text: str, registry: ToolRegistry) -> Dict[str, Optional[str]]:
    found: Dict[str, Optional[str]] = {
        "organization": None,
        "site": None,
        "meter": None,
    }
    try:
        hierarchy = registry.tools.cache.load_hierarchy()
    except Exception:
        return found
    normalized_text = f" {normalize_name(text)} "
    for kind, collection in (
        ("organization", hierarchy.organizations),
        ("site", hierarchy.sites),
        ("meter", hierarchy.meters),
    ):
        candidates = []
        for entity in collection:
            normalized = normalize_name(entity.name)
            variants = {normalized}
            variants.add(
                normalized[:-1] if normalized.endswith("s") else normalized + "s"
            )
            if any(f" {variant} " in normalized_text for variant in variants):
                candidates.append(entity.id)
        if len(set(candidates)) == 1:
            found[kind] = candidates[0]
        elif not candidates and kind != "meter":
            found[kind] = _fuzzy_entity_mention(
                normalized_text.strip(),
                collection,
            )
    if found["organization"] is None:
        if " food corp " in normalized_text:
            found["organization"] = registry.tools.cache.resolve_entity_ids(
                "organization", "Food Corp."
            )[0]
        elif " best resorts hotel " in normalized_text:
            found["organization"] = registry.tools.cache.resolve_entity_ids(
                "organization", "Best Resorts Hotel"
            )[0]
    return found


def _fuzzy_entity_mention(text: str, collection: Sequence[Any]) -> Optional[str]:
    words = text.split()
    scored: list[tuple[float, str]] = []
    for entity in collection:
        entity_text = normalize_name(entity.name)
        entity_words = entity_text.split()
        if not entity_words or len(words) < len(entity_words):
            continue
        window_size = len(entity_words)
        score = max(
            SequenceMatcher(
                None,
                " ".join(words[index : index + window_size]),
                entity_text,
            ).ratio()
            for index in range(len(words) - window_size + 1)
        )
        if score >= 0.86:
            scored.append((score, str(entity.id)))
    scored.sort(reverse=True)
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None
    return scored[0][1]


def _parse_period(text: str, today: date) -> Optional[tuple[date, date]]:
    lowered = text.casefold()
    if "last month" in lowered or "previous month" in lowered:
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        return start, end
    if "this month" in lowered or "current month" in lowered:
        start = today.replace(day=1)
        return start, _next_month(start)
    if "last week" in lowered or "previous week" in lowered:
        current_week = today - timedelta(days=today.weekday())
        return current_week - timedelta(days=7), current_week
    if "this week" in lowered or "current week" in lowered:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7)

    for month_text, month_number in sorted(
        MONTHS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        match = re.search(
            rf"\b{re.escape(month_text)}\b(?:\s+of)?(?:\s+(\d{{4}}))?",
            lowered,
        )
        if not match:
            continue
        year = int(match.group(1)) if match.group(1) else today.year
        start = date(year, month_number, 1)
        if start > today and match.group(1) is None:
            start = date(year - 1, month_number, 1)
        return start, _next_month(start)

    explicit = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", lowered)
    if len(explicit) >= 2:
        return date.fromisoformat(explicit[0]), date.fromisoformat(explicit[1])
    return None


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _resolution(text: str) -> str:
    for value in ("hourly", "daily", "weekly", "monthly"):
        if value in text:
            return value
    return "monthly"


def _ranking_metric(text: str) -> str:
    if "complete" in text or "quality" in text:
        return "completeness"
    if "load factor" in text:
        return "load_factor"
    if "daily" in text:
        return "average_daily_consumption"
    return "total_consumption"
