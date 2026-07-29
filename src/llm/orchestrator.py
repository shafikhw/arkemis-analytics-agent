"""Deterministic-first, fallback-safe Responses API orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import ValidationError

from src.llm.answer_models import AnswerEnvelope, render_answer
from src.llm.fallback_renderers import render_fallback
from src.llm.intent_routing import (
    constrained_tool_choice,
    direct_tool_plans,
)
from src.llm.response_validation import (
    NumericTolerance,
    NumericValidation,
    validate_numeric_grounding,
)
from src.llm.result_validation import (
    ToolResultValidationError,
    ValidatedToolResult,
    validate_tool_result,
)
from src.llm.scope import ScopeDecision, ScopeGuard, ScopeState
from src.llm.system_prompt import build_system_prompt
from src.llm.usage_tracking import (
    PricingConfiguration,
    empty_usage,
    extract_usage,
    merge_usage,
)
from src.tools.registry import ToolRegistry


@dataclass
class ToolTraceEntry:
    name: str
    arguments: Dict[str, Any]
    status: str
    result_summary: Any
    error: Optional[str] = None


@dataclass
class AssistantResult:
    answer: str
    status: str = "answered"
    trace: List[ToolTraceEntry] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    scope: Dict[str, Any] = field(default_factory=dict)
    grounding_status: str = "not_applicable"
    fallback_used: bool = False
    provenance: List[Dict[str, str]] = field(default_factory=list)
    cache_freshness: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class EnergyAssistant:
    def __init__(
        self,
        client: Any,
        *,
        model: str,
        registry: ToolRegistry,
        max_tool_rounds: int = 6,
        today_provider=date.today,
        service_tier: str = "standard",
        pricing: Optional[PricingConfiguration] = None,
        numeric_tolerance: NumericTolerance = NumericTolerance(),
        answer_decimal_places: int = 3,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be positive.")
        self.client = client
        self.model = model
        self.registry = registry
        self.max_tool_rounds = max_tool_rounds
        self.today_provider = today_provider
        self.service_tier = service_tier
        self.pricing = pricing
        self.numeric_tolerance = numeric_tolerance
        self.answer_decimal_places = answer_decimal_places
        self.scope_guard = ScopeGuard(registry)

    def ask(
        self,
        question: str,
        *,
        history: Optional[Sequence[Mapping[str, str]]] = None,
    ) -> AssistantResult:
        usage = empty_usage(
            self.pricing,
            model=self.model,
            service_tier=self.service_tier,
        )
        if not question or not question.strip():
            decision = ScopeDecision(
                state=ScopeState.NEEDS_CLARIFICATION,
                confidence=1.0,
                reason="The request is empty.",
                missing_information=("energy analytics question",),
            )
            return AssistantResult(
                answer="What energy analytics question would you like me to answer?",
                status="clarification_needed",
                usage=usage,
                scope=decision.as_dict(),
                error="empty_question",
            )

        question = question.strip()
        decision = self.scope_guard.classify(question, history=history)
        guarded = self._guardrail_response(decision)
        if guarded is not None:
            guarded.usage = usage
            guarded.scope = decision.as_dict()
            return guarded

        trace: List[ToolTraceEntry] = []
        validated_results: List[ValidatedToolResult] = []
        instructions = build_system_prompt(self.today_provider())
        plans = direct_tool_plans(
            question,
            decision,
            self.registry,
            today=self.today_provider(),
            history=history,
        )

        try:
            if plans:
                for plan in plans:
                    self._execute_tool(
                        plan.tool_name,
                        plan.arguments,
                        trace,
                        validated_results,
                    )
                return self._answer_from_results(
                    question,
                    history,
                    decision,
                    instructions,
                    trace,
                    validated_results,
                    usage,
                )

            input_items = _history_input(history)
            input_items.append({"role": "user", "content": question})
            first_round = True
            for _round in range(self.max_tool_rounds):
                request: Dict[str, Any] = {
                    "model": self.model,
                    "service_tier": _api_service_tier(self.service_tier),
                    "instructions": instructions,
                    "input": input_items,
                    "tools": self.registry.schemas,
                    "parallel_tool_calls": True,
                }
                if first_round:
                    tool_choice = constrained_tool_choice(decision.suggested_tool)
                    if tool_choice is not None:
                        request["tool_choice"] = tool_choice
                if validated_results:
                    request["text"] = _structured_text_format()
                response = self.client.responses.create(**request)
                merge_usage(
                    usage,
                    extract_usage(response),
                    pricing=self.pricing,
                )
                output_items = list(getattr(response, "output", []))
                input_items.extend(output_items)
                calls = [
                    item
                    for item in output_items
                    if getattr(item, "type", None) == "function_call"
                ]
                if not calls:
                    if validated_results:
                        if not any(item.status == "ok" for item in validated_results):
                            return self._answer_from_results(
                                question,
                                history,
                                decision,
                                instructions,
                                trace,
                                validated_results,
                                usage,
                            )
                        return self._answer_from_candidate_or_retry(
                            candidate=str(
                                getattr(response, "output_text", "") or ""
                            ).strip(),
                            question=question,
                            history=history,
                            decision=decision,
                            instructions=instructions,
                            trace=trace,
                            results=validated_results,
                            usage=usage,
                        )
                    text = str(getattr(response, "output_text", "") or "").strip()
                    return AssistantResult(
                        answer=text
                        or (
                            "Which organization, site, meter, and period should I "
                            "use for this energy analysis?"
                        ),
                        status="clarification_needed",
                        trace=trace,
                        usage=usage,
                        scope=decision.as_dict(),
                        grounding_status="no_tool_result",
                    )

                for call in calls:
                    arguments: Dict[str, Any] = {}
                    try:
                        decoded = json.loads(call.arguments)
                        if not isinstance(decoded, dict):
                            raise ValueError("Arguments decoded to a non-object value.")
                        arguments = self._prepare_arguments(str(call.name), decoded)
                    except Exception as exc:
                        result = {
                            "status": "error",
                            "error_type": exc.__class__.__name__,
                            "message": str(exc),
                        }
                        validated = validate_tool_result(
                            str(call.name), arguments, result
                        )
                        validated_results.append(validated)
                        trace.append(
                            ToolTraceEntry(
                                name=str(call.name),
                                arguments=arguments,
                                status="error",
                                result_summary=_summarize(result),
                                error=str(exc),
                            )
                        )
                    else:
                        self._execute_tool(
                            str(call.name),
                            arguments,
                            trace,
                            validated_results,
                        )
                        result = validated_results[-1].result
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(
                                result, ensure_ascii=False, default=str
                            ),
                        }
                    )
                first_round = False

            if any(item.status == "ok" for item in validated_results):
                return self._fallback_result(
                    decision,
                    trace,
                    validated_results,
                    usage,
                    error="max_tool_rounds_exceeded_after_factual_result",
                )
            return AssistantResult(
                answer=(
                    "The tool plan did not produce a factual result before reaching "
                    "the configured round limit. Please narrow the entity or period."
                ),
                status="tool_error",
                trace=trace,
                usage=usage,
                scope=decision.as_dict(),
                error="max_tool_rounds_exceeded",
            )
        except Exception as exc:
            if any(item.status == "ok" for item in validated_results):
                return self._fallback_result(
                    decision,
                    trace,
                    validated_results,
                    usage,
                    error=f"synthesis_service_error:{exc.__class__.__name__}",
                )
            return AssistantResult(
                answer=(
                    "The language-model service is currently unavailable and no "
                    "validated factual tool result was produced."
                ),
                status="tool_error",
                trace=trace,
                usage=usage,
                scope=decision.as_dict(),
                error=f"{exc.__class__.__name__}: {exc}",
            )

    def _execute_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        trace: List[ToolTraceEntry],
        results: List[ValidatedToolResult],
    ) -> None:
        prepared = dict(arguments)
        try:
            prepared = self._prepare_arguments(name, prepared)
            raw = self.registry.execute(name, prepared)
            validated = validate_tool_result(name, prepared, raw)
            results.append(validated)
            trace.append(
                ToolTraceEntry(
                    name=name,
                    arguments=prepared,
                    status="success" if validated.status == "ok" else validated.status,
                    result_summary=_summarize(validated.result),
                    error=(
                        str(validated.result.get("message"))
                        if validated.status == "error"
                        else None
                    ),
                )
            )
        except (Exception, ToolResultValidationError) as exc:
            payload = {
                "status": "error",
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }
            results.append(validate_tool_result(name, prepared, payload))
            trace.append(
                ToolTraceEntry(
                    name=name,
                    arguments=prepared,
                    status="error",
                    result_summary=_summarize(payload),
                    error=str(exc),
                )
            )

    def _prepare_arguments(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Dict[str, Any]:
        prepare = getattr(self.registry, "prepare", None)
        if callable(prepare):
            return dict(prepare(name, arguments))
        return dict(arguments)

    def _answer_from_results(
        self,
        question: str,
        history: Optional[Sequence[Mapping[str, str]]],
        decision: ScopeDecision,
        instructions: str,
        trace: List[ToolTraceEntry],
        results: List[ValidatedToolResult],
        usage: Dict[str, Any],
    ) -> AssistantResult:
        if not any(item.status == "ok" for item in results):
            empty = [item for item in results if item.status == "empty"]
            message = (
                str(empty[0].result.get("message"))
                if empty
                else "The analytics tool did not produce a factual result."
            )
            return AssistantResult(
                answer=message,
                status="data_unavailable" if empty else "tool_error",
                trace=trace,
                usage=usage,
                scope=decision.as_dict(),
                grounding_status="no_factual_result",
                error=None if empty else "tool_execution_failed",
            )
        response = self._synthesis_call(
            question,
            history,
            instructions,
            results,
            usage,
            retry_reason=None,
        )
        candidate = str(getattr(response, "output_text", "") or "").strip()
        return self._answer_from_candidate_or_retry(
            candidate=candidate,
            question=question,
            history=history,
            decision=decision,
            instructions=instructions,
            trace=trace,
            results=results,
            usage=usage,
        )

    def _answer_from_candidate_or_retry(
        self,
        *,
        candidate: str,
        question: str,
        history: Optional[Sequence[Mapping[str, str]]],
        decision: ScopeDecision,
        instructions: str,
        trace: List[ToolTraceEntry],
        results: List[ValidatedToolResult],
        usage: Dict[str, Any],
    ) -> AssistantResult:
        parsed, validation, parse_error = self._validate_candidate(
            candidate, question, results
        )
        if parsed is not None and validation is not None and validation.valid:
            return self._successful_result(
                parsed,
                validation,
                decision,
                trace,
                usage,
                grounding_status="passed",
            )

        reason = parse_error or (
            "Unsupported values: " + ", ".join(validation.unsupported_numbers)
            if validation is not None
            else "Structured answer validation failed."
        )
        try:
            retry_response = self._synthesis_call(
                question,
                history,
                instructions,
                results,
                usage,
                retry_reason=reason,
            )
            retry_candidate = str(
                getattr(retry_response, "output_text", "") or ""
            ).strip()
            parsed, validation, _ = self._validate_candidate(
                retry_candidate, question, results
            )
            if parsed is not None and validation is not None and validation.valid:
                return self._successful_result(
                    parsed,
                    validation,
                    decision,
                    trace,
                    usage,
                    grounding_status="passed_after_retry",
                )
        except Exception:
            pass
        return self._fallback_result(
            decision,
            trace,
            results,
            usage,
            error="synthesis_validation_failed_fallback_used",
        )

    def _synthesis_call(
        self,
        question: str,
        history: Optional[Sequence[Mapping[str, str]]],
        instructions: str,
        results: Sequence[ValidatedToolResult],
        usage: Dict[str, Any],
        *,
        retry_reason: Optional[str],
    ) -> Any:
        payload = [
            {
                "source_tool": item.name,
                "arguments": item.arguments,
                "result": item.result,
            }
            for item in results
        ]
        synthesis_instruction = (
            "Create the final consultant-facing answer from the validated tool "
            "outputs below. Do not call tools and do not perform arithmetic. Every "
            "analytic number and timestamp must be copied or harmlessly formatted "
            "from one exact source field. Facts must use the exact source tool name "
            "and a JSONPath such as $.peak_demand_kw. Set status to answered when an "
            "ok result exists. Keep warnings and limitations factual."
        )
        if retry_reason:
            synthesis_instruction += (
                "\nThe previous synthesis was rejected: "
                + retry_reason
                + ". Correct only the synthesis using the same outputs."
            )
        input_items = _history_input(history)
        input_items.extend(
            [
                {"role": "user", "content": question},
                {
                    "role": "developer",
                    "content": synthesis_instruction
                    + "\nValidated outputs:\n"
                    + json.dumps(payload, ensure_ascii=False, default=str),
                },
            ]
        )
        response = self.client.responses.create(
            model=self.model,
            service_tier=_api_service_tier(self.service_tier),
            instructions=instructions,
            input=input_items,
            tools=[],
            text=_structured_text_format(),
        )
        merge_usage(
            usage,
            extract_usage(response),
            pricing=self.pricing,
        )
        return response

    def _validate_candidate(
        self,
        candidate: str,
        question: str,
        results: Sequence[ValidatedToolResult],
    ) -> tuple[
        Optional[AnswerEnvelope],
        Optional[NumericValidation],
        Optional[str],
    ]:
        if not candidate:
            return None, None, "The model returned an empty structured answer."
        try:
            envelope = AnswerEnvelope.model_validate_json(candidate)
        except ValidationError as exc:
            return None, None, f"Invalid answer schema: {exc.errors()[0]['type']}"
        if envelope.status != "answered":
            envelope.status = "answered"
        fact_error = _validate_fact_references(envelope, results)
        if fact_error:
            return None, None, fact_error
        rendered = render_answer(envelope)
        validation = validate_numeric_grounding(
            rendered,
            [item.provenance_payload() for item in results],
            allowed_context=question + "\n" + self.today_provider().isoformat(),
            tolerance=self.numeric_tolerance,
        )
        return envelope, validation, None

    def _successful_result(
        self,
        envelope: AnswerEnvelope,
        validation: NumericValidation,
        decision: ScopeDecision,
        trace: List[ToolTraceEntry],
        usage: Dict[str, Any],
        *,
        grounding_status: str,
    ) -> AssistantResult:
        rendered = _normalize_display_precision(
            render_answer(envelope),
            validation,
            decimal_places=self.answer_decimal_places,
        )
        return AssistantResult(
            answer=rendered,
            status="answered",
            trace=trace,
            usage=usage,
            scope=decision.as_dict(),
            grounding_status=grounding_status,
            provenance=[
                {
                    "answer_value": match.answer_value,
                    "source_tool": match.source_tool,
                    "source_field": match.source_field,
                    "transformation": match.transformation,
                }
                for match in validation.provenance
            ],
        )

    def _fallback_result(
        self,
        decision: ScopeDecision,
        trace: List[ToolTraceEntry],
        results: Sequence[ValidatedToolResult],
        usage: Dict[str, Any],
        *,
        error: str,
    ) -> AssistantResult:
        return AssistantResult(
            answer=render_fallback(results, decimal_places=self.answer_decimal_places),
            status="answered",
            trace=trace,
            usage=usage,
            scope=decision.as_dict(),
            grounding_status="deterministic_fallback",
            fallback_used=True,
            error=error,
        )

    def _guardrail_response(self, decision: ScopeDecision) -> Optional[AssistantResult]:
        if decision.state == ScopeState.IN_SCOPE:
            return None
        if decision.state == ScopeState.OUT_OF_SCOPE:
            return AssistantResult(
                answer=(
                    "I’m limited to Ark Energy consumption analytics. I can help "
                    "with consumption summaries, peak demand and timestamps, or "
                    "data quality and missing intervals."
                ),
                status="out_of_scope",
            )
        if decision.state == ScopeState.ENERGY_BUT_UNSUPPORTED:
            return AssistantResult(
                answer=(
                    f"{decision.reason} The closest supported analysis is historical "
                    "consumption, demand/profile comparison, anomaly detection, or "
                    "data-quality assessment using the cached Ark Energy data."
                ),
                status="unsupported",
            )
        missing = (
            decision.missing_information[0]
            if decision.missing_information
            else "organization, site, meter, or period"
        )
        return AssistantResult(
            answer=f"Which {missing} should I use for this energy analysis?",
            status="clarification_needed",
        )


def _structured_text_format() -> dict:
    return {
        "format": {
            "type": "json_schema",
            "name": "ark_energy_answer",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "answered",
                            "clarification_needed",
                            "unsupported",
                            "out_of_scope",
                            "data_unavailable",
                            "tool_error",
                        ],
                    },
                    "answer": {"type": "string"},
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "source_tool": {"type": "string"},
                                "source_field": {"type": "string"},
                            },
                            "required": [
                                "label",
                                "value",
                                "source_tool",
                                "source_field",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "limitations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "status",
                    "answer",
                    "facts",
                    "warnings",
                    "limitations",
                ],
                "additionalProperties": False,
            },
        }
    }


def _api_service_tier(value: str) -> str:
    """Map the pricing label 'standard' to the Responses API label 'default'."""
    return "default" if value.casefold() == "standard" else value


def _history_input(
    history: Optional[Sequence[Mapping[str, str]]],
) -> List[dict]:
    items = []
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            items.append({"role": role, "content": content})
    return items


def _validate_fact_references(
    envelope: AnswerEnvelope,
    results: Sequence[ValidatedToolResult],
) -> Optional[str]:
    by_name: Dict[str, List[ValidatedToolResult]] = {}
    for item in results:
        by_name.setdefault(item.name, []).append(item)
    for fact in envelope.facts:
        candidates = by_name.get(fact.source_tool)
        if not candidates:
            return f"Unknown fact source tool: {fact.source_tool}"
        resolved = False
        for candidate in candidates:
            try:
                value = _resolve_json_path(candidate.result, fact.source_field)
            except (KeyError, IndexError, ValueError):
                continue
            if not re.search(r"\d", fact.value):
                source_text = str(value).strip().casefold()
                fact_text = fact.value.strip().casefold()
                if source_text and (
                    source_text in fact_text or fact_text in source_text
                ):
                    resolved = True
                    break
                continue
            validation = validate_numeric_grounding(
                fact.value,
                [
                    {
                        "source_tool": candidate.name,
                        "result": {_source_field_leaf_name(fact.source_field): value},
                    }
                ],
            )
            if validation.valid:
                resolved = True
                break
        if not resolved:
            return (
                f"Fact {fact.label!r} does not map to "
                f"{fact.source_tool}:{fact.source_field}."
            )
    return None


def _source_field_leaf_name(path: str) -> str:
    keys = re.findall(r"\.([A-Za-z0-9_]+)", path)
    return keys[-1] if keys else "value"


def _resolve_json_path(value: Any, path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError("source_field must start with $.")
    current = value
    for key, index in re.findall(r"\.([A-Za-z0-9_]+)|\[(\d+)\]", path[1:]):
        if key:
            current = current[key]
        else:
            current = current[int(index)]
    return current


def _normalize_display_precision(
    answer: str,
    validation: NumericValidation,
    *,
    decimal_places: int,
) -> str:
    normalized = answer
    for match in validation.provenance:
        token = match.answer_value
        if match.transformation == "equivalent_timestamp_format":
            continue
        numeric = token.replace(",", "").rstrip("%")
        if "." not in numeric:
            continue
        if len(numeric.rsplit(".", 1)[1]) <= decimal_places:
            continue
        try:
            value = float(numeric)
        except ValueError:
            continue
        replacement = f"{value:,.{decimal_places}f}".rstrip("0").rstrip(".")
        if token.endswith("%"):
            replacement += "%"
        normalized = normalized.replace(token, replacement, 1)
    return normalized


def _summarize(value: Any, *, max_items: int = 5, depth: int = 0) -> Any:
    if depth >= 3:
        return "..."
    if isinstance(value, dict):
        return {
            str(key): _summarize(item, max_items=max_items, depth=depth + 1)
            for key, item in list(value.items())[:12]
        }
    if isinstance(value, list):
        summarized = [
            _summarize(item, max_items=max_items, depth=depth + 1)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            summarized.append({"truncated_items": len(value) - max_items})
        return summarized
    return value
