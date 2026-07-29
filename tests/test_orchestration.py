from __future__ import annotations

import json
from types import SimpleNamespace

from src.llm.orchestrator import EnergyAssistant


class FakeResponses:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeRegistry:
    schemas = [{"type": "function", "name": "get_total", "parameters": {}}]

    def execute(self, name, arguments):
        assert name == "get_total"
        return {
            "status": "ok",
            "total_energy_kwh": 24.0,
            "period": {
                "start_date_inclusive": "2026-03-01",
                "end_date_exclusive": "2026-03-02",
            },
        }


def response(output, text=""):
    return SimpleNamespace(output=output, output_text=text, usage=None)


def function_call(arguments='{"organization":"Food Corp."}'):
    return SimpleNamespace(
        type="function_call",
        name="get_total",
        arguments=arguments,
        call_id="call-1",
    )


def structured_answer(answer, value):
    return json.dumps(
        {
            "status": "answered",
            "answer": answer,
            "facts": [
                {
                    "label": "Consumption",
                    "value": value,
                    "source_tool": "get_total",
                    "source_field": "$.total_energy_kwh",
                }
            ],
            "warnings": [],
            "limitations": [],
        }
    )


def test_mocked_tool_call_and_final_answer():
    fake = SimpleNamespace(
        responses=FakeResponses(
            [
                response([function_call()]),
                response(
                    [],
                    structured_answer("Consumption was 24.0 kWh.", "24.0 kWh"),
                ),
            ]
        )
    )
    assistant = EnergyAssistant(
        fake, model="test-model", registry=FakeRegistry(), max_tool_rounds=3
    )
    result = assistant.ask("What was consumption?")
    assert result.answer == "Consumption was 24.0 kWh."
    assert result.trace[0].status == "success"
    assert result.grounding_status == "passed"


def test_numeric_grounding_retry():
    fake = SimpleNamespace(
        responses=FakeResponses(
            [
                response([function_call()]),
                response(
                    [],
                    structured_answer("Consumption was 999 kWh.", "999 kWh"),
                ),
                response(
                    [],
                    structured_answer("Consumption was 24.0 kWh.", "24.0 kWh"),
                ),
            ]
        )
    )
    assistant = EnergyAssistant(
        fake, model="test-model", registry=FakeRegistry(), max_tool_rounds=3
    )
    result = assistant.ask("What was consumption?")
    assert result.answer == "Consumption was 24.0 kWh."
    assert result.grounding_status == "passed_after_retry"
    assert fake.responses.calls[-1]["tools"] == []
    assert len(result.trace) == 1


def test_failed_synthesis_uses_successful_tool_result_without_reexecution():
    fake = SimpleNamespace(
        responses=FakeResponses(
            [
                response([function_call()]),
                response([], "not-json"),
                response([], "still-not-json"),
            ]
        )
    )
    registry = FakeRegistry()
    calls = []
    original = registry.execute

    def counted(name, arguments):
        calls.append((name, arguments))
        return original(name, arguments)

    registry.execute = counted
    assistant = EnergyAssistant(
        fake, model="test-model", registry=registry, max_tool_rounds=3
    )
    result = assistant.ask("What was consumption?")
    assert result.status == "answered"
    assert result.fallback_used is True
    assert "24" in result.answer
    assert calls == [("get_total", {"organization": "Food Corp."})]
    assert len(result.trace) == 1


def test_timestamp_fact_maps_to_exact_timestamp_source_field():
    class PeakRegistry:
        schemas = [{"type": "function", "name": "get_peak_demand"}]

        def execute(self, name, arguments):
            return {
                "status": "ok",
                "timestamp_utc": "2026-06-12T16:25:00+00:00",
                "peak_demand_kw": 188.70695999999998,
            }

    candidate = json.dumps(
        {
            "status": "answered",
            "answer": ("The peak was June 12, 2026 at 4:25 PM UTC at 188.707 kW."),
            "facts": [
                {
                    "label": "Peak timestamp",
                    "value": "2026-06-12T16:25:00+00:00",
                    "source_tool": "get_peak_demand",
                    "source_field": "$.timestamp_utc",
                }
            ],
            "warnings": [],
            "limitations": [],
        }
    )
    fake = SimpleNamespace(
        responses=FakeResponses(
            [
                response(
                    [
                        SimpleNamespace(
                            type="function_call",
                            name="get_peak_demand",
                            arguments="{}",
                            call_id="peak-call",
                        )
                    ]
                ),
                response([], candidate),
            ]
        )
    )
    result = EnergyAssistant(
        fake,
        model="test-model",
        registry=PeakRegistry(),
    ).ask("When was peak demand?")
    assert result.grounding_status == "passed"
    assert result.fallback_used is False


def test_malformed_arguments_become_tool_error():
    fake = SimpleNamespace(
        responses=FakeResponses(
            [
                response([function_call("{bad json")]),
                response([], "The analytics request could not be executed."),
            ]
        )
    )
    assistant = EnergyAssistant(
        fake, model="test-model", registry=FakeRegistry(), max_tool_rounds=3
    )
    result = assistant.ask("What was consumption?")
    assert result.trace[0].status == "error"
    assert "JSONDecodeError" in result.trace[0].result_summary["error_type"]
