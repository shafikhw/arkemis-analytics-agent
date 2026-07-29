"""Strict Responses API function schemas for deterministic analytics."""

from __future__ import annotations

from typing import Any, Dict, List


def nullable_string(description: str) -> Dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


def date_string(description: str) -> Dict[str, Any]:
    return {
        "type": "string",
        "format": "date",
        "description": description + " Use YYYY-MM-DD.",
    }


def nullable_date(description: str) -> Dict[str, Any]:
    return {
        "type": ["string", "null"],
        "description": description + " Use YYYY-MM-DD or null.",
    }


def strict_tool(
    name: str, description: str, properties: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


ENTITY_FILTERS = {
    "organization": nullable_string(
        "Exact organization name or stable API ID; null means all organizations."
    ),
    "site": nullable_string(
        "Exact site name or stable API ID; null means all sites in scope."
    ),
    "meter": nullable_string(
        "Exact meter name or stable API ID; null means all meters in scope."
    ),
}

PERIOD_FILTERS = {
    **ENTITY_FILTERS,
    "start_date": date_string(
        "First local operational date included in the calculation."
    ),
    "end_date": date_string(
        "First local operational date excluded from the calculation."
    ),
}


def build_tool_schemas() -> List[Dict[str, Any]]:
    return [
        strict_tool(
            "list_organizations",
            "List cached organizations by exact API ID and name. Use before analytics when an organization name is unknown or ambiguous. Returns no energy values.",
            {},
        ),
        strict_tool(
            "list_sites",
            "List cached sites and their stable IDs, optionally within one organization. Use for entity discovery, not for consumption calculations.",
            {"organization": ENTITY_FILTERS["organization"]},
        ),
        strict_tool(
            "list_meters",
            "List cached meters, measurement types, units, sampling intervals, and parent entities. Use to discover valid meter filters or inspect supported measurements.",
            {
                "organization": ENTITY_FILTERS["organization"],
                "site": ENTITY_FILTERS["site"],
            },
        ),
        strict_tool(
            "get_data_availability",
            "Return cached UTC date ranges and observation counts by meter. Use to choose a valid analysis period; it does not calculate consumption.",
            ENTITY_FILTERS,
        ),
        strict_tool(
            "get_data_quality",
            "Return deterministic gap, duplicate, invalid-record, timezone-assumption, and completeness metrics. Dates are an inclusive start and exclusive end; pass both as null for the full cached summary.",
            {
                **ENTITY_FILTERS,
                "start_date": nullable_date("Optional first local date included."),
                "end_date": nullable_date("Optional first local date excluded."),
            },
        ),
        strict_tool(
            "get_consumption_summary",
            "Calculate total and average energy for an explicit period and filters. Use for consumption questions; all values come from cached deterministic records. Resolution controls the returned series.",
            {
                **PERIOD_FILTERS,
                "resolution": {
                    "type": "string",
                    "enum": ["hourly", "daily", "weekly", "monthly"],
                    "description": (
                        "Aggregation resolution for the returned series. Native "
                        "interval rows are intentionally unavailable to the LLM."
                    ),
                },
            },
        ),
        strict_tool(
            "compare_periods",
            "Compare total consumption in a current period with a previous period. If both previous dates are null, code uses the immediately preceding equivalent-duration period. Handles zero and incomplete periods explicitly.",
            {
                **ENTITY_FILTERS,
                "current_start_date": date_string("Current period start, included."),
                "current_end_date": date_string("Current period end, excluded."),
                "previous_start_date": nullable_date(
                    "Previous period start, included; null for automatic equivalent period."
                ),
                "previous_end_date": nullable_date(
                    "Previous period end, excluded; null for automatic equivalent period."
                ),
            },
        ),
        strict_tool(
            "compare_entities",
            "Compare organizations or sites on a specified defensible metric. Raw consumption metrics are scale-dependent and never establish efficiency.",
            {
                "entity_kind": {
                    "type": "string",
                    "enum": ["organization", "site"],
                    "description": "Entity level to compare.",
                },
                "metric": {
                    "type": "string",
                    "enum": [
                        "total_consumption",
                        "average_daily_consumption",
                        "load_factor",
                        "completeness",
                        "weekday_weekend_ratio",
                    ],
                    "description": "Metric calculated independently for each entity.",
                },
                "organization": ENTITY_FILTERS["organization"],
                "start_date": PERIOD_FILTERS["start_date"],
                "end_date": PERIOD_FILTERS["end_date"],
            },
        ),
        strict_tool(
            "estimate_baseload",
            "Estimate statistical low load per site or meter using a low percentile of valid interval demand. It is not a directly measured physical value and does not assume shared operating hours.",
            {
                **PERIOD_FILTERS,
                "group_by": {
                    "type": "string",
                    "enum": ["site", "meter"],
                    "description": "Level at which estimates are returned.",
                },
                "percentile": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 49.9,
                    "description": "Low-load percentile calculated separately per meter.",
                },
                "minimum_observations": {
                    "type": "integer",
                    "minimum": 4,
                    "description": "Minimum valid intervals for a reliable estimate.",
                },
            },
        ),
        strict_tool(
            "get_peak_demand",
            "Return the maximum valid demand, timestamp, entity, interval, source, and completeness. Clearly identifies demand derived from documented active power.",
            PERIOD_FILTERS,
        ),
        strict_tool(
            "calculate_load_factor",
            "Calculate average demand divided by peak demand for explicit filters and period, returning both inputs and safe zero handling.",
            PERIOD_FILTERS,
        ),
        strict_tool(
            "compare_weekday_weekend",
            "Compare weekday and weekend energy using each record's local operational date. Returns totals, average day values, complete-day counts, and optionally a local-hour profile.",
            {
                **PERIOD_FILTERS,
                "include_hourly_profile": {
                    "type": "boolean",
                    "description": "Whether to include average interval energy by local hour and day type.",
                },
            },
        ),
        strict_tool(
            "rank_sites",
            "Rank sites on one explicit metric with direction, units, completeness, and limitation. Consumption rankings do not imply efficiency.",
            {
                **PERIOD_FILTERS,
                "metric": {
                    "type": "string",
                    "enum": [
                        "total_consumption",
                        "average_daily_consumption",
                        "load_factor",
                        "completeness",
                    ],
                    "description": "Metric used to rank sites.",
                },
            },
        ),
        strict_tool(
            "detect_anomalies",
            "Detect explainable interval-energy anomalies relative to the same local hour of week using median and scaled MAD/IQR. Missing data is excluded and remains a quality event.",
            {
                **PERIOD_FILTERS,
                "threshold": {
                    "type": "number",
                    "minimum": 0.1,
                    "description": "Absolute robust score required for an anomaly.",
                },
                "minimum_samples": {
                    "type": "integer",
                    "minimum": 4,
                    "description": "Minimum comparable samples per hour-of-week group.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum anomalies returned in descending score order.",
                },
            },
        ),
        strict_tool(
            "get_load_profile",
            "Return average interval energy by local hour. Set normalized true to compare profile shape without claiming performance or efficiency.",
            {
                **PERIOD_FILTERS,
                "normalized": {
                    "type": "boolean",
                    "description": "Also return each hour's share of the profile total.",
                },
            },
        ),
    ]
