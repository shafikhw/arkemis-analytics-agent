"""Deterministic consultant-facing renderers for validated analytics results."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Sequence

from dateutil import parser as date_parser

from src.llm.result_validation import ValidatedToolResult

Renderer = Callable[[Mapping[str, Any], int], str]


def render_fallback(
    results: Sequence[ValidatedToolResult],
    *,
    decimal_places: int = 3,
) -> str:
    factual = [item for item in results if item.status == "ok"]
    if not factual:
        messages = [
            str(item.result.get("message") or "No factual result is available.")
            for item in results
        ]
        return "\n\n".join(messages) or "No factual result is available."
    rendered = []
    for item in factual:
        renderer = RENDERERS.get(item.name, _render_generic)
        section = renderer(item.result, decimal_places)
        if len(factual) > 1:
            section = f"### {item.name}\n\n{section}"
        rendered.append(section)
    return "\n\n".join(rendered)


def _render_consumption(result: Mapping[str, Any], places: int) -> str:
    return _join(
        f"Consumption for {_period(result)}:",
        f"Total consumption: {_fmt(result.get('total_energy_kwh'), places)} kWh",
        (
            "Average interval consumption: "
            f"{_fmt(result.get('average_interval_energy_kwh'), places)} kWh/interval"
        ),
        (
            f"Average demand: {_fmt(result.get('average_demand_kw'), places)} kW"
            if result.get("average_demand_kw") is not None
            else None
        ),
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_period_comparison(result: Mapping[str, Any], places: int) -> str:
    current = result.get("current_period") or {}
    previous = result.get("previous_period") or {}
    percentage = result.get("percentage_difference")
    return _join(
        "Period comparison:",
        (f"Current ({_period(current)}): {_fmt(current.get('value_kwh'), places)} kWh"),
        (
            f"Previous ({_period(previous)}): "
            f"{_fmt(previous.get('value_kwh'), places)} kWh"
        ),
        (
            "Absolute difference: "
            f"{_fmt(result.get('absolute_difference_kwh'), places)} kWh"
        ),
        (
            f"Percentage difference: {_fmt(percentage, places)}%"
            if percentage is not None
            else "Percentage difference: unavailable"
        ),
        _warnings(result),
    )


def _render_entity_comparison(result: Mapping[str, Any], places: int) -> str:
    kind = str(result.get("entity_kind") or "entity")
    rows = []
    for row in result.get("entities") or []:
        name = row.get(f"{kind}_name") or row.get(f"{kind}_id")
        rows.append(
            f"- {name}: {_fmt(row.get('value'), places)} {row.get('unit') or ''}".rstrip()
        )
    return _join(
        f"{str(result.get('metric') or 'Metric').replace('_', ' ').title()} "
        f"comparison for {_period(result)}:",
        "\n".join(rows),
        _warnings(result),
    )


def _render_baseload(result: Mapping[str, Any], places: int) -> str:
    rows = []
    group_by = str(result.get("group_by") or "site")
    for row in result.get("estimates") or []:
        name = row.get(f"{group_by}_name") or row.get(f"{group_by}_id")
        rows.append(
            f"- {name}: {_fmt(row.get('baseload_estimate_kw'), places)} kW baseload; "
            f"{_fmt(row.get('baseload_energy_kwh'), places)} kWh baseload energy; "
            f"{_fmt(row.get('operational_energy_above_baseline_kwh'), places)} kWh "
            f"operational energy above baseline; reliable: {row.get('reliable')}."
        )
    method = result.get("method") or {}
    return _join(
        f"Baseload estimates for {_period(result)}:",
        "\n".join(rows),
        (
            f"Method: {method.get('name')}; percentile: "
            f"{_fmt(method.get('percentile'), places)}; minimum observations: "
            f"{_fmt(method.get('minimum_observations'), places)}."
        ),
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_peak(result: Mapping[str, Any], places: int) -> str:
    organization = (result.get("organization") or {}).get("name") or "Selection"
    site = (result.get("site") or {}).get("name") or "Unavailable"
    meter = (result.get("meter") or {}).get("name") or "Unavailable"
    timestamp = result.get("timestamp_local") or result.get("timestamp_utc")
    basis = "measured" if result.get("is_measured_directly") is True else "derived"
    quality = result.get("data_completeness") or {}
    return _join(
        (
            f"{organization} reached its peak demand in {_period(result)} at "
            f"{_format_timestamp(timestamp)}."
        ),
        f"Peak demand: {_fmt(result.get('peak_demand_kw'), places)} {result.get('unit') or 'kW'}",
        f"Site: {site}",
        f"Meter: {meter}",
        f"Interval: {_fmt(result.get('interval_minutes'), places)} minutes",
        f"Demand basis: {basis} ({result.get('demand_source')})",
        (
            "Data completeness: "
            f"{_fmt(quality.get('completeness_percentage'), places)}% "
            f"({_fmt(quality.get('observation_count'), places)} of "
            f"{_fmt(quality.get('expected_observation_count'), places)} observations)"
        ),
        _warnings(result),
    )


def _render_load_factor(result: Mapping[str, Any], places: int) -> str:
    percentage = result.get("load_factor_percentage")
    return _join(
        f"Load factor for {_period(result)}:",
        f"Load factor: {_fmt(result.get('load_factor'), places)}",
        (
            f"Load factor percentage: {_fmt(percentage, places)}%"
            if percentage is not None
            else None
        ),
        f"Average demand: {_fmt(result.get('average_demand_kw'), places)} kW",
        f"Peak demand: {_fmt(result.get('peak_demand_kw'), places)} kW",
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_weekday_weekend(result: Mapping[str, Any], places: int) -> str:
    return _join(
        f"Weekday versus weekend consumption for {_period(result)}:",
        f"Weekday total: {_fmt(result.get('weekday_total_kwh'), places)} kWh",
        f"Weekend total: {_fmt(result.get('weekend_total_kwh'), places)} kWh",
        (
            "Average weekday: "
            f"{_fmt(result.get('average_weekday_consumption_kwh'), places)} kWh"
        ),
        (
            "Average weekend day: "
            f"{_fmt(result.get('average_weekend_day_consumption_kwh'), places)} kWh"
        ),
        (
            "Weekend relative to weekday: "
            f"{_fmt(result.get('percentage_difference_average_day'), places)}%"
            if result.get("percentage_difference_average_day") is not None
            else None
        ),
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_ranking(result: Mapping[str, Any], places: int) -> str:
    rows = [
        (
            f"- Rank {_fmt(row.get('rank'), places)}: {row.get('site_name')} "
            f"({row.get('organization_name')}) — "
            f"{_fmt(row.get('metric_value'), places)} {row.get('unit') or ''}"
        ).rstrip()
        for row in result.get("ranked_sites") or []
    ]
    return _join(
        f"Site ranking for {_period(result)}:",
        "\n".join(rows),
        f"Basis: {result.get('ranking_metric')} ({result.get('ranking_direction')}).",
        f"Limitation: {result.get('justification_or_limitation')}",
        _warnings(result),
    )


def _render_anomalies(result: Mapping[str, Any], places: int) -> str:
    rows = []
    for row in result.get("anomalies") or []:
        rows.append(
            f"- {_format_timestamp(row.get('timestamp_local') or row.get('timestamp_utc'))}: "
            f"{row.get('direction')} anomaly at "
            f"{_fmt(row.get('actual_energy_kwh'), places)} kWh; baseline "
            f"{_fmt(row.get('baseline_energy_kwh'), places)} kWh; score "
            f"{_fmt(row.get('anomaly_score'), places)}; meter {row.get('meter_name')}."
        )
    method = result.get("method") or {}
    return _join(
        f"Anomaly analysis for {_period(result)}:",
        f"Anomalies detected: {_fmt(result.get('anomaly_count'), places)}",
        "\n".join(rows) if rows else "No anomaly records were returned.",
        (
            f"Method: {method.get('name')}; threshold: "
            f"{_fmt(method.get('threshold'), places)}."
        ),
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_quality(result: Mapping[str, Any], places: int) -> str:
    return _join(
        "Data quality summary:",
        f"Rows: {_fmt(result.get('row_count'), places)}",
        f"Meters: {_fmt(result.get('meter_count'), places)}",
        f"Missing intervals: {_fmt(result.get('missing_interval_count'), places)}",
        f"Duplicates: {_fmt(result.get('duplicate_count'), places)}",
        (
            "Completeness: "
            f"{_fmt(result.get('completeness_percentage'), places)}% "
            f"({_fmt(result.get('row_count'), places)} observed rows; "
            f"{_fmt(result.get('expected_observation_count'), places)} expected observations)"
        ),
        (
            "Data range: "
            f"{(result.get('date_range') or {}).get('start')} to "
            f"{(result.get('date_range') or {}).get('end')}"
        ),
    )


def _render_profile(result: Mapping[str, Any], places: int) -> str:
    rows = []
    for row in result.get("profile") or []:
        line = (
            f"- Local hour {_fmt(row.get('local_hour'), places)}: "
            f"{_fmt(row.get('average_interval_energy_kwh'), places)} kWh/interval"
        )
        if row.get("profile_share") is not None:
            line += f"; profile share {_fmt(row.get('profile_share'), places)}"
        rows.append(line)
    return _join(
        f"Load profile for {_period(result)}:",
        "\n".join(rows),
        _completeness(result.get("data_completeness"), places),
        _warnings(result),
    )


def _render_generic(result: Mapping[str, Any], places: int) -> str:
    rows = []
    for key, value in result.items():
        if key in {"status", "warnings"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append(f"- {key.replace('_', ' ').title()}: {_fmt(value, places)}")
    return _join("\n".join(rows), _warnings(result))


RENDERERS: Dict[str, Renderer] = {
    "get_consumption_summary": _render_consumption,
    "compare_periods": _render_period_comparison,
    "compare_entities": _render_entity_comparison,
    "estimate_baseload": _render_baseload,
    "get_peak_demand": _render_peak,
    "calculate_load_factor": _render_load_factor,
    "compare_weekday_weekend": _render_weekday_weekend,
    "rank_sites": _render_ranking,
    "detect_anomalies": _render_anomalies,
    "get_data_quality": _render_quality,
    "get_load_profile": _render_profile,
}


def _period(result: Mapping[str, Any]) -> str:
    period = result.get("period") or {}
    start = period.get("start_date_inclusive")
    end = period.get("end_date_exclusive")
    if not start and not end:
        return "the available period"
    return f"{start} through {end} (end exclusive)"


def _format_timestamp(value: Any) -> str:
    if value is None:
        return "timestamp unavailable"
    try:
        parsed: datetime = date_parser.isoparse(str(value))
    except (ValueError, TypeError):
        return str(value)
    zone = parsed.tzname() or ""
    hour = parsed.hour % 12 or 12
    meridiem = "AM" if parsed.hour < 12 else "PM"
    display = (
        f"{parsed.strftime('%B')} {parsed.day}, {parsed.year} at "
        f"{hour}:{parsed.minute:02d} {meridiem}"
    )
    return f"{display} {zone}".strip()


def _fmt(value: Any, places: int) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        rounded = round(value, places)
        return f"{rounded:,.{places}f}".rstrip("0").rstrip(".")
    return str(value)


def _completeness(value: Any, places: int) -> str:
    quality = value if isinstance(value, Mapping) else {}
    if not quality:
        return ""
    return (
        "Data completeness: "
        f"{_fmt(quality.get('completeness_percentage'), places)}% "
        f"({_fmt(quality.get('observation_count'), places)} of "
        f"{_fmt(quality.get('expected_observation_count'), places)} observations)"
    )


def _warnings(result: Mapping[str, Any]) -> str:
    warnings = [str(value) for value in result.get("warnings") or []]
    return (
        "Warnings:\n" + "\n".join(f"- {value}" for value in warnings)
        if warnings
        else ""
    )


def _join(*values: Any) -> str:
    return "\n".join(str(value) for value in values if value not in {None, ""})
