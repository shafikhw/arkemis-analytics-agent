"""Semantic numeric and timestamp provenance validation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from dateutil import parser as date_parser

NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"
)
ISO_TIMESTAMP_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|UTC|[+-]\d{2}:\d{2})?)?\b",
    re.IGNORECASE,
)
MONTH_TIMESTAMP_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:,\s*|\s+)\d{4}"
    r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?"
    r"(?:\s*(?:UTC|Z|[+-]\d{2}:\d{2}))?)?\b",
    re.IGNORECASE,
)
DAY_MONTH_TIMESTAMP_PATTERN = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}"
    r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?"
    r"(?:\s*(?:UTC|Z|[+-]\d{2}:\d{2}))?)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumericTolerance:
    relative: float = 0.0005
    absolute: float = 0.005
    percentage_points: float = 0.05


@dataclass(frozen=True)
class ProvenanceMatch:
    answer_value: str
    source_tool: str
    source_field: str
    transformation: str


@dataclass(frozen=True)
class NumericValidation:
    valid: bool
    unsupported_numbers: List[str]
    provenance: List[ProvenanceMatch] = field(default_factory=list)


@dataclass(frozen=True)
class _NumericSource:
    value: float
    source_tool: str
    source_field: str
    transformation: str = "identity_or_rounding"
    percentage: bool = False


@dataclass(frozen=True)
class _TimestampSource:
    value: datetime
    source_tool: str
    source_field: str


def validate_numeric_grounding(
    answer: str,
    tool_results: Sequence[Any],
    *,
    allowed_context: str = "",
    tolerance: NumericTolerance = NumericTolerance(),
) -> NumericValidation:
    """Validate that displayed analytic values map to structured source fields.

    Allowed transformations are representational only: decimal rounding, commas,
    ratio/percentage formatting, and equivalent timestamp formatting. No arithmetic
    combination of source fields is accepted.
    """
    numeric_sources, timestamp_sources = _collect_sources(tool_results)
    if allowed_context:
        context_numeric, context_timestamps = _collect_sources(
            [{"source_tool": "user_context", "result": allowed_context}]
        )
        numeric_sources.extend(context_numeric)
        timestamp_sources.extend(context_timestamps)

    substantive_answer = re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer)
    masked = list(substantive_answer)
    unsupported: List[str] = []
    provenance: List[ProvenanceMatch] = []

    timestamp_matches = _answer_timestamp_matches(substantive_answer)
    for start, end, token, parsed, has_time in timestamp_matches:
        timestamp_source = _match_timestamp(parsed, has_time, timestamp_sources)
        if timestamp_source is None:
            unsupported.append(token)
        else:
            provenance.append(
                ProvenanceMatch(
                    answer_value=token,
                    source_tool=timestamp_source.source_tool,
                    source_field=timestamp_source.source_field,
                    transformation="equivalent_timestamp_format",
                )
            )
        for index in range(start, end):
            masked[index] = " "

    for match in NUMBER_PATTERN.finditer("".join(masked)):
        token = match.group(0)
        value = _parse_number(token)
        percentage = token.endswith("%")
        numeric_source = _match_number(value, percentage, numeric_sources, tolerance)
        if numeric_source is None:
            unsupported.append(token)
            continue
        provenance.append(
            ProvenanceMatch(
                answer_value=token,
                source_tool=numeric_source.source_tool,
                source_field=numeric_source.source_field,
                transformation=numeric_source.transformation,
            )
        )

    return NumericValidation(
        valid=not unsupported,
        unsupported_numbers=unsupported,
        provenance=provenance,
    )


def _collect_sources(
    tool_results: Sequence[Any],
) -> Tuple[List[_NumericSource], List[_TimestampSource]]:
    numeric: List[_NumericSource] = []
    timestamps: List[_TimestampSource] = []
    for index, item in enumerate(tool_results):
        tool_name, result = _unwrap_result(item, index)
        for path, value in _flatten(result):
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                number = float(value)
                if not math.isfinite(number):
                    continue
                numeric.append(_NumericSource(number, tool_name, path))
                if _ratio_field(path) and 0 <= abs(number) <= 1:
                    numeric.append(
                        _NumericSource(
                            number * 100.0,
                            tool_name,
                            path,
                            transformation="ratio_to_percentage",
                            percentage=True,
                        )
                    )
                if _percentage_field(path):
                    numeric.append(
                        _NumericSource(
                            number / 100.0,
                            tool_name,
                            path,
                            transformation="percentage_to_ratio",
                        )
                    )
                continue
            if isinstance(value, (datetime, date)):
                parsed_datetime: Optional[datetime] = _as_datetime(value)
            elif isinstance(value, str):
                parsed_datetime = _parse_source_datetime(value, path)
                for token in NUMBER_PATTERN.findall(value):
                    numeric.append(
                        _NumericSource(
                            _parse_number(token),
                            tool_name,
                            path,
                            transformation="source_text",
                        )
                    )
            else:
                parsed_datetime = None
            if parsed_datetime is not None:
                timestamps.append(_TimestampSource(parsed_datetime, tool_name, path))
    return numeric, timestamps


def _unwrap_result(item: Any, index: int) -> Tuple[str, Any]:
    if isinstance(item, Mapping) and "source_tool" in item and "result" in item:
        return str(item["source_tool"]), item["result"]
    if hasattr(item, "name") and hasattr(item, "result"):
        return str(item.name), item.result
    return f"tool_result_{index + 1}", item


def _flatten(value: Any, path: str = "$") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _flatten(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{path}[{index}]")
    else:
        yield path, value


def _answer_timestamp_matches(
    text: str,
) -> List[Tuple[int, int, str, datetime, bool]]:
    candidates: List[Tuple[int, int, str, datetime, bool]] = []
    occupied: List[Tuple[int, int]] = []
    for pattern in (
        MONTH_TIMESTAMP_PATTERN,
        DAY_MONTH_TIMESTAMP_PATTERN,
        ISO_TIMESTAMP_PATTERN,
    ):
        for match in pattern.finditer(text):
            if any(
                match.start() < end and match.end() > start for start, end in occupied
            ):
                continue
            token = match.group(0)
            parsed = _parse_answer_datetime(token)
            if parsed is None:
                continue
            has_time = bool(re.search(r"\d{1,2}:\d{2}", token))
            candidates.append((match.start(), match.end(), token, parsed, has_time))
            occupied.append((match.start(), match.end()))
    return sorted(candidates, key=lambda row: row[0])


def _parse_answer_datetime(value: str) -> Optional[datetime]:
    cleaned = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bat\b", " ", cleaned, flags=re.IGNORECASE)
    try:
        parsed = date_parser.parse(cleaned, fuzzy=False)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None and re.search(r"\b(?:UTC|Z)\b", cleaned, re.IGNORECASE):
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_source_datetime(value: str, path: str) -> Optional[datetime]:
    if not any(word in path.casefold() for word in ("timestamp", "date", "time")):
        return None
    try:
        return date_parser.isoparse(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time())


def _match_timestamp(
    answer: datetime,
    has_time: bool,
    sources: Sequence[_TimestampSource],
) -> Optional[_TimestampSource]:
    for source in sources:
        candidate = source.value
        if not has_time and answer.date() == candidate.date():
            return source
        normalized_answer = _normalize_datetime(answer, candidate)
        normalized_candidate = _normalize_datetime(candidate, answer)
        if normalized_answer is None or normalized_candidate is None:
            continue
        if abs((normalized_answer - normalized_candidate).total_seconds()) <= 1:
            return source
    return None


def _normalize_datetime(value: datetime, other: datetime) -> Optional[datetime]:
    if value.tzinfo is None:
        if other.tzinfo is None:
            return value
        return value.replace(tzinfo=other.tzinfo).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _match_number(
    value: float,
    percentage: bool,
    sources: Sequence[_NumericSource],
    tolerance: NumericTolerance,
) -> Optional[_NumericSource]:
    for source in sources:
        absolute = (
            tolerance.percentage_points
            if percentage or source.percentage
            else tolerance.absolute
        )
        if math.isclose(
            value,
            source.value,
            rel_tol=tolerance.relative,
            abs_tol=absolute,
        ):
            return source
    return None


def _parse_number(token: str) -> float:
    return float(token.replace(",", "").rstrip("%"))


def _ratio_field(path: str) -> bool:
    lowered = path.casefold()
    return (
        any(
            name in lowered
            for name in ("ratio", "load_factor", "profile_share", "completeness")
        )
        and "percentage" not in lowered
    )


def _percentage_field(path: str) -> bool:
    return "percentage" in path.casefold() or "percent" in path.casefold()
