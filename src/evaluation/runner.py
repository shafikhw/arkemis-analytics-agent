"""Mocked end-to-end evaluation runner using the real cache and tool layer."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from src.data.cache import EnergyCache
from src.llm.orchestrator import EnergyAssistant
from src.llm.usage_tracking import PricingConfiguration
from src.tools.energy_tools import EnergyTools
from src.tools.registry import ToolRegistry


class ScriptedEvaluationResponses:
    def __init__(
        self,
        tool_calls: Sequence[Mapping[str, Any]],
        *,
        scenario: Optional[str] = None,
    ) -> None:
        self.tool_calls = list(tool_calls)
        self.scenario = scenario
        self.calls: list[dict] = []
        self.planned = False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        tools = kwargs.get("tools") or []
        if self.scenario == "synthesis_api_error" and not tools:
            raise RuntimeError("simulated synthesis API outage")
        if not self.planned and tools and self.tool_calls:
            self.planned = True
            calls = []
            for index, specification in enumerate(self.tool_calls, start=1):
                arguments = specification.get("arguments_json")
                if arguments is None:
                    arguments = json.dumps(specification.get("arguments") or {})
                calls.append(
                    SimpleNamespace(
                        type="function_call",
                        name=specification["name"],
                        arguments=arguments,
                        call_id=f"eval-call-{index}",
                    )
                )
            return _response(calls, "")
        return _response([], "not-valid-structured-json")


def run_mock_evaluations(
    dataset_path: Path,
    cache_root: Path,
) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    registry = ToolRegistry(EnergyTools(EnergyCache(cache_root)))
    records = []
    for case in _expanded_single_cases(dataset["single_cases"]):
        records.append(_run_case(case, registry, history=[]))
    for sequence in dataset["multi_turn_sequences"]:
        history: list[dict[str, str]] = []
        for index, turn in enumerate(sequence["turns"], start=1):
            case = dict(turn)
            case["id"] = f"{sequence['id']}_turn_{index}"
            case["category"] = "multi_turn"
            record = _run_case(case, registry, history=history)
            records.append(record)
            history.extend(
                [
                    {"role": "user", "content": case["question"]},
                    {
                        "role": "assistant",
                        "content": record["answer_for_context"],
                    },
                ]
            )
    return _aggregate(records)


def _run_case(
    case: Mapping[str, Any],
    registry: ToolRegistry,
    *,
    history: Sequence[Mapping[str, str]],
) -> dict:
    tool_calls = list(case.get("tool_calls") or [])
    if not tool_calls:
        tool_calls = _default_tool_calls(case)
    responses = ScriptedEvaluationResponses(
        tool_calls,
        scenario=case.get("scenario"),
    )
    assistant = EnergyAssistant(
        SimpleNamespace(responses=responses),
        model="gpt-5.6-terra",
        service_tier="standard",
        pricing=PricingConfiguration.terra_standard(),
        registry=registry,
        today_provider=lambda: date(2026, 7, 29),
    )
    started = time.perf_counter()
    result = assistant.ask(case["question"], history=history)
    latency = time.perf_counter() - started
    expected_tools = list(case.get("expected_tools") or [])
    actual_tools = [entry.name for entry in result.trace]
    expected_status = case.get("expected_status")
    if expected_status is None:
        expected_status = {
            "in_scope": "answered",
            "energy_but_unsupported": "unsupported",
            "out_of_scope": "out_of_scope",
            "needs_clarification": "clarification_needed",
        }[case["expected_scope"]]
    scope_correct = result.scope.get("state") == case["expected_scope"]
    selection_correct = not expected_tools or actual_tools == expected_tools
    argument_correct = (
        True
        if case.get("check_arguments") is False
        else _arguments_correct(case.get("tool_calls") or [], result.trace, registry)
    )
    status_correct = result.status == expected_status
    required_fragments = [
        str(value) for value in case.get("required_answer_fragments") or []
    ]
    forbidden_fragments = [
        str(value) for value in case.get("forbidden_answer_fragments") or []
    ]
    answer_content_correct = all(
        fragment.casefold() in result.answer.casefold()
        for fragment in required_fragments
    ) and not any(
        fragment.casefold() in result.answer.casefold()
        for fragment in forbidden_fragments
    )
    safe_calls = _calls_exclude_raw_data(responses.calls)
    supported = case["expected_scope"] == "in_scope"
    numeric_pass = (
        not supported
        or result.status != "answered"
        or result.grounding_status
        in {
            "passed",
            "passed_after_retry",
            "deterministic_fallback",
            "deterministic_render",
        }
    )
    return {
        "id": case["id"],
        "category": case.get("category"),
        "expected_scope": case["expected_scope"],
        "actual_scope": result.scope.get("state"),
        "scope_correct": scope_correct,
        "expected_status": expected_status,
        "actual_status": result.status,
        "status_correct": status_correct,
        "answer_content_correct": answer_content_correct,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "tool_selection_correct": selection_correct,
        "tool_arguments_correct": argument_correct,
        "grounding_status": result.grounding_status,
        "numeric_provenance_pass": numeric_pass,
        "fallback_used": result.fallback_used,
        "latency_seconds": latency,
        "tokens": result.usage.get("total_tokens") or 0,
        "estimated_cost_usd": result.usage.get("estimated_cost_usd") or 0.0,
        "raw_dataset_excluded": safe_calls,
        "unhandled_exception": False,
        "answer_for_context": result.answer,
    }


def _expanded_single_cases(cases: Iterable[Mapping[str, Any]]) -> Iterable[dict]:
    for case in cases:
        repeat = int(case.get("repeat", 1))
        for index in range(1, repeat + 1):
            expanded = dict(case)
            if repeat > 1:
                expanded["id"] = f"{case['id']}_{index:02d}"
            yield expanded


def _default_tool_calls(case: Mapping[str, Any]) -> list[dict]:
    expected = list(case.get("expected_tools") or [])
    if not expected:
        return []
    question = str(case["question"]).casefold()
    organization = (
        "Food Corp."
        if "food corp" in question
        else "Best Resorts Hotel"
        if "hotel" in question
        else None
    )
    period = (
        ("2026-06-01", "2026-07-01")
        if "june" in question or "last month" in question or "same month" in question
        else ("2026-03-01", "2026-04-01")
        if "march" in question
        else ("2030-08-01", "2030-09-01")
        if "august 2030" in question
        else ("2026-03-01", "2026-04-01")
    )
    calls = []
    for name in expected:
        filters = {
            "organization": organization,
            "site": None,
            "meter": None,
        }
        arguments: Dict[str, Any]
        if name == "get_data_quality":
            arguments = {
                **filters,
                "start_date": period[0],
                "end_date": period[1],
            }
        elif name == "compare_periods":
            arguments = {
                **filters,
                "current_start_date": "2026-06-01",
                "current_end_date": "2026-07-01",
                "previous_start_date": "2026-03-01",
                "previous_end_date": "2026-04-01",
            }
        elif name == "compare_entities":
            arguments = {
                "entity_kind": "organization",
                "metric": "total_consumption",
                "organization": None,
                "start_date": period[0],
                "end_date": period[1],
            }
        else:
            arguments = {
                **filters,
                "start_date": period[0],
                "end_date": period[1],
            }
            if name == "get_consumption_summary":
                arguments["resolution"] = "monthly"
            elif name == "estimate_baseload":
                arguments.update(
                    {
                        "group_by": "site",
                        "percentile": 10.0,
                        "minimum_observations": 96,
                    }
                )
            elif name == "compare_weekday_weekend":
                arguments["include_hourly_profile"] = False
            elif name == "rank_sites":
                arguments["metric"] = "total_consumption"
            elif name == "detect_anomalies":
                arguments.update(
                    {
                        "threshold": 3.5,
                        "minimum_samples": 4,
                        "max_results": 100,
                    }
                )
            elif name == "get_load_profile":
                arguments["normalized"] = False
        calls.append({"name": name, "arguments": arguments})
    return calls


def _arguments_correct(
    expected_calls: Sequence[Mapping[str, Any]],
    trace: Sequence[Any],
    registry: ToolRegistry,
) -> bool:
    if not expected_calls:
        return True
    if len(expected_calls) != len(trace):
        return False
    for expected, actual in zip(expected_calls, trace):
        if "arguments" not in expected:
            continue
        try:
            prepared = registry.prepare(expected["name"], expected["arguments"])
        except Exception:
            return False
        if prepared != actual.arguments:
            return False
    return True


def _calls_exclude_raw_data(calls: Sequence[Mapping[str, Any]]) -> bool:
    serialized = json.dumps(calls, default=str).casefold()
    banned = (
        '"original_value"',
        '"extraction_timestamp"',
        '"source": "wattics_api',
        '"raw_rows"',
    )
    return not any(value in serialized for value in banned)


def _aggregate(records: list[dict]) -> dict:
    count = len(records)
    supported = [row for row in records if row["expected_scope"] == "in_scope"]
    unrelated = [row for row in records if row["expected_scope"] == "out_of_scope"]
    unsupported = [
        row for row in records if row["expected_scope"] == "energy_but_unsupported"
    ]
    peak = [row for row in records if row["id"].startswith("peak_regression")]
    failures = [
        {
            "id": row["id"],
            "scope_correct": row["scope_correct"],
            "status_correct": row["status_correct"],
            "answer_content_correct": row["answer_content_correct"],
            "tool_selection_correct": row["tool_selection_correct"],
            "tool_arguments_correct": row["tool_arguments_correct"],
            "numeric_provenance_pass": row["numeric_provenance_pass"],
            "raw_dataset_excluded": row["raw_dataset_excluded"],
        }
        for row in records
        if not all(
            (
                row["scope_correct"],
                row["status_correct"],
                row["answer_content_correct"],
                row["tool_selection_correct"],
                row["tool_arguments_correct"],
                row["numeric_provenance_pass"],
                row["raw_dataset_excluded"],
            )
        )
    ]
    metrics = {
        "case_count": count,
        "tool_selection_accuracy": _rate(
            row["tool_selection_correct"] for row in supported
        ),
        "tool_argument_accuracy": _rate(
            row["tool_arguments_correct"] for row in supported
        ),
        "answer_success_rate": _rate(
            row["actual_status"] in {"answered", "data_unavailable", "tool_error"}
            for row in supported
        ),
        "answer_content_accuracy": _rate(
            row["answer_content_correct"] for row in records
        ),
        "numeric_grounding_pass_rate": _rate(
            row["numeric_provenance_pass"] for row in supported
        ),
        "false_refusal_rate": _rate(
            row["actual_status"] in {"out_of_scope", "unsupported"} for row in supported
        ),
        "out_of_scope_refusal_precision": _rate(
            row["actual_status"] == "out_of_scope" for row in unrelated
        ),
        "unsupported_handling_accuracy": _rate(
            row["actual_status"] == "unsupported" for row in unsupported
        ),
        "deterministic_fallback_usage_rate": _rate(
            row["fallback_used"] for row in supported
        ),
        "peak_regression_successes": sum(
            row["actual_status"] == "answered"
            and row["actual_tools"] == ["get_peak_demand"]
            for row in peak
        ),
        "peak_regression_runs": len(peak),
        "raw_dataset_exclusion_rate": _rate(
            row["raw_dataset_excluded"] for row in records
        ),
        "unhandled_exception_count": sum(row["unhandled_exception"] for row in records),
        "average_latency_seconds": (
            sum(row["latency_seconds"] for row in records) / count if count else 0.0
        ),
        "average_tokens_per_query": (
            sum(row["tokens"] for row in records) / count if count else 0.0
        ),
        "average_estimated_cost_usd": (
            sum(row["estimated_cost_usd"] for row in records) / count if count else 0.0
        ),
        "total_estimated_cost_usd": sum(row["estimated_cost_usd"] for row in records),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "mocked_llm_real_cache_and_tools",
        "metrics": metrics,
        "failures": failures,
        "cases": [
            {key: value for key, value in row.items() if key != "answer_for_context"}
            for row in records
        ],
    }


def _rate(values: Iterable[bool]) -> float:
    rows = list(values)
    return sum(bool(value) for value in rows) / len(rows) if rows else 1.0


def _response(output: list[Any], output_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        output=output,
        output_text=output_text,
        model="gpt-5.6-terra",
        service_tier="standard",
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=20,
            total_tokens=520,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0,
                cache_write_tokens=0,
            ),
        ),
    )
