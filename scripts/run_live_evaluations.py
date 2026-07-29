"""Controlled live-model workflow verification without persisting answer values."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings  # noqa: E402
from src.data.cache import EnergyCache  # noqa: E402
from src.llm.client import build_openai_client  # noqa: E402
from src.llm.orchestrator import EnergyAssistant  # noqa: E402
from src.llm.response_validation import NumericTolerance  # noqa: E402
from src.llm.usage_tracking import pricing_from_settings  # noqa: E402
from src.tools.energy_tools import EnergyTools  # noqa: E402
from src.tools.registry import ToolRegistry  # noqa: E402

ASSESSMENT_QUESTIONS = [
    "What was total consumption at Food Corp. last month?",
    "Which organization had the larger week-over-week increase?",
    "Was anything unusual about Best Resorts Hotel in March?",
    "How does weekend consumption compare between the two organizations?",
    "What is the baseload at each site?",
]
PEAK_QUESTION = "When did Food Corp. reach peak demand in June 2026?"
IN_SCOPE_REGRESSION_QUESTIONS = [
    "rank sites",
    "what is the baseload of beta resort & spa?",
    "what iwhat is the baseload of beta resort & spa site?",
    "what is the baseload of food crop",
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required: performs billable OpenAI API calls.",
    )
    parser.add_argument("--peak-runs", type=int, default=10)
    parser.add_argument("--include-assessment", action="store_true")
    parser.add_argument("--include-in-scope-regressions", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evaluation_results" / "live_latest.json",
    )
    args = parser.parse_args(argv)
    if not args.confirm_live:
        parser.error("--confirm-live is required for billable model evaluation.")

    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require(["OPENAI_API_KEY", "OPENAI_MODEL"])
    if settings.openai_model != "gpt-5.6-terra":
        raise SystemExit("Live evaluation requires OPENAI_MODEL=gpt-5.6-terra.")
    registry = ToolRegistry(EnergyTools(EnergyCache(settings.cache_root)))
    assistant = EnergyAssistant(
        build_openai_client(settings.openai_api_key or ""),
        model=settings.openai_model,
        service_tier=settings.openai_service_tier,
        pricing=pricing_from_settings(settings),
        registry=registry,
        max_tool_rounds=settings.max_tool_rounds,
        today_provider=lambda: date(2026, 7, 29),
        numeric_tolerance=NumericTolerance(
            relative=settings.numeric_relative_tolerance,
            absolute=settings.numeric_absolute_tolerance,
            percentage_points=settings.percentage_tolerance,
        ),
        answer_decimal_places=settings.answer_decimal_places,
    )
    questions = [PEAK_QUESTION] * args.peak_runs
    if args.include_assessment:
        questions.extend(ASSESSMENT_QUESTIONS)
    if args.include_in_scope_regressions:
        questions.extend(IN_SCOPE_REGRESSION_QUESTIONS)
    records: list[Dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        started = time.perf_counter()
        result = assistant.ask(question)
        records.append(
            {
                "run": index,
                "case": (
                    "peak_regression"
                    if question == PEAK_QUESTION
                    else "assessment_question"
                    if question in ASSESSMENT_QUESTIONS
                    else "in_scope_regression"
                ),
                "status": result.status,
                "scope": result.scope.get("state"),
                "tools": [entry.name for entry in result.trace],
                "tool_statuses": [entry.status for entry in result.trace],
                "grounding_status": result.grounding_status,
                "fallback_used": result.fallback_used,
                "error": result.error,
                "latency_seconds": time.perf_counter() - started,
                "tokens": result.usage.get("total_tokens"),
                "estimated_cost_usd": result.usage.get("estimated_cost_usd"),
            }
        )
    peak = [row for row in records if row["case"] == "peak_regression"]
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.openai_model,
        "service_tier": settings.openai_service_tier,
        "pricing_source": settings.openai_pricing_source,
        "answer_values_persisted": False,
        "metrics": {
            "run_count": len(records),
            "peak_runs": len(peak),
            "peak_successes": sum(
                row["status"] == "answered"
                and row["scope"] == "in_scope"
                and row["tools"] == ["get_peak_demand"]
                and row["grounding_status"]
                in {
                    "passed",
                    "passed_after_retry",
                    "deterministic_fallback",
                }
                for row in peak
            ),
            "answer_success_rate": sum(row["status"] == "answered" for row in records)
            / len(records),
            "false_refusal_count": sum(
                row["status"] in {"out_of_scope", "unsupported"} for row in records
            ),
            "fallback_usage_count": sum(row["fallback_used"] for row in records),
            "average_latency_seconds": sum(row["latency_seconds"] for row in records)
            / len(records),
            "total_tokens": sum(row["tokens"] or 0 for row in records),
            "total_estimated_cost_usd": sum(
                row["estimated_cost_usd"] or 0.0 for row in records
            ),
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report["metrics"], indent=2))
    success = (
        report["metrics"]["peak_successes"] == len(peak)
        and report["metrics"]["false_refusal_count"] == 0
        and report["metrics"]["answer_success_rate"] == 1.0
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
