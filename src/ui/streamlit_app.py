"""Simple explainable consultant UI with cache synchronization controls."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import streamlit as st

from src.config import ConfigurationError, Settings
from src.data.cache import EnergyCache
from src.data.sync_manager import AutoSyncManager
from src.llm.client import build_openai_client
from src.llm.orchestrator import EnergyAssistant
from src.llm.response_validation import NumericTolerance
from src.llm.usage_tracking import pricing_from_settings
from src.tools.energy_tools import EnergyTools
from src.tools.registry import ToolRegistry


def main() -> None:
    st.set_page_config(
        page_title="Ark Energy Analytics Assistant",
        page_icon="⚡",
        layout="wide",
    )
    st.title("Ark Energy Analytics Assistant")
    st.caption(
        "The LLM interprets questions; deterministic local tools compute every "
        "energy value and preserve numeric provenance."
    )

    try:
        settings = Settings.from_env(Path(".env"))
    except ConfigurationError as exc:
        st.error(str(exc))
        return
    cache = EnergyCache(settings.cache_root)
    manager = AutoSyncManager(settings, cache)

    if (
        settings.data_auto_sync
        and settings.data_sync_on_startup
        and not st.session_state.get("startup_sync_attempted")
    ):
        st.session_state.startup_sync_attempted = True
        with st.spinner("Checking the local energy cache..."):
            st.session_state.last_sync_outcome = manager.ensure_fresh(
                reason="application_startup"
            )

    status = cache.status()
    freshness = manager.freshness()
    configured = bool(settings.openai_api_key and settings.openai_model)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Processed meters", status["processed_meter_files"])
    col2.metric(
        "LLM connection",
        "Configured" if configured else "Configuration required",
    )
    col3.metric(
        "Synchronization",
        status.get("synchronization_status") or "unknown",
    )
    col4.metric(
        "Cache freshness",
        freshness.state,
        delta=(
            f"{freshness.age_minutes:.1f} min old"
            if freshness.age_minutes is not None
            else None
        ),
        delta_color="inverse" if not freshness.fresh else "normal",
    )

    refresh_col, metadata_col = st.columns([1, 3])
    with refresh_col:
        refresh_clicked = st.button(
            "Refresh data",
            disabled=not bool(settings.wattics_api_token),
            use_container_width=True,
        )
    if refresh_clicked:
        with st.spinner("Incrementally refreshing changed meter data..."):
            st.session_state.last_sync_outcome = manager.ensure_fresh(
                reason="manual_refresh", force=True
            )
        st.rerun()
    with metadata_col:
        st.caption(
            "Last successful synchronization: "
            f"{status.get('last_successful_sync') or 'none'} · "
            "Latest cached observation: "
            f"{status.get('latest_cached_observation') or 'none'} · "
            f"Failed meters: {status.get('failed_meter_count', 0)}"
        )

    if not freshness.fresh:
        st.warning(
            "The cache is missing or stale. Existing validated cache files remain "
            "available if the API refresh fails."
        )
    if status["failed_meter_count"]:
        failed_names = [
            str(row.get("meter_name") or row.get("meter_id"))
            for row in status.get("failed_meters") or []
        ]
        st.warning("Failed meter updates: " + ", ".join(failed_names))
    if not status["processed_meter_files"]:
        st.info(
            "No processed cache is available. Use Refresh data or run "
            "`python scripts/sync_data.py`."
        )
    if not configured:
        st.info("Set OPENAI_API_KEY and OPENAI_MODEL in .env to enable questions.")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("trace"):
                _render_trace(message["trace"])
            if message.get("scope"):
                _render_scope(message["scope"])
            if message.get("usage"):
                st.caption(_usage_caption(message["usage"]))
            if message.get("cache_freshness"):
                st.caption(_freshness_caption(message["cache_freshness"]))

    question = st.chat_input(
        "Ask about consumption, peaks, baseload, profiles, data quality, or anomalies...",
        disabled=not configured or not status["processed_meter_files"],
    )
    if not question:
        return

    prior_history = [
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.messages
    ]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Running deterministic analytics..."):
            if (
                settings.data_auto_sync
                and settings.data_sync_before_query_if_stale
                and not manager.freshness().fresh
            ):
                st.session_state.last_sync_outcome = manager.ensure_fresh(
                    reason="before_query"
                )
            assistant = EnergyAssistant(
                build_openai_client(settings.openai_api_key or ""),
                model=settings.openai_model or "",
                service_tier=settings.openai_service_tier,
                pricing=pricing_from_settings(settings),
                registry=ToolRegistry(EnergyTools(cache)),
                max_tool_rounds=settings.max_tool_rounds,
                numeric_tolerance=NumericTolerance(
                    relative=settings.numeric_relative_tolerance,
                    absolute=settings.numeric_absolute_tolerance,
                    percentage_points=settings.percentage_tolerance,
                ),
                answer_decimal_places=settings.answer_decimal_places,
            )
            result = assistant.ask(question, history=prior_history)
            current_status = cache.status()
            current_freshness = manager.freshness().as_dict()
            current_freshness.update(
                {
                    "synchronization_status": current_status.get(
                        "synchronization_status"
                    ),
                    "latest_cached_observation": current_status.get(
                        "latest_cached_observation"
                    ),
                    "failed_meter_count": current_status.get("failed_meter_count"),
                    "used_stale_cache": not current_freshness["fresh"],
                }
            )
            result.cache_freshness = current_freshness
        st.markdown(result.answer)
        trace = [asdict(item) for item in result.trace]
        if trace:
            _render_trace(trace)
        _render_scope(result.scope)
        st.caption(_usage_caption(result.usage))
        st.caption(_freshness_caption(result.cache_freshness))
        if result.fallback_used:
            st.caption(
                "A validated deterministic renderer produced this answer after "
                "model synthesis did not pass provenance validation."
            )
        if result.error and not result.fallback_used:
            st.caption("The request completed with a handled application warning.")
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.answer,
            "trace": trace,
            "scope": result.scope,
            "usage": result.usage,
            "cache_freshness": result.cache_freshness,
        }
    )


def _render_trace(trace) -> None:
    with st.expander("Tool trace", expanded=False):
        for index, entry in enumerate(trace, start=1):
            st.markdown(f"**{index}. `{entry['name']}` — {entry['status']}**")
            st.json(
                {
                    "arguments": entry["arguments"],
                    "result_summary": entry["result_summary"],
                    "error": entry.get("error"),
                },
                expanded=False,
            )


def _render_scope(scope) -> None:
    if not scope:
        return
    with st.expander("Scope decision", expanded=False):
        st.json(scope, expanded=False)


def _usage_caption(usage) -> str:
    if not usage or usage.get("total_tokens") is None:
        return (
            f"Model: {usage.get('model') if usage else 'unknown'} · "
            "Token usage and cost unavailable because the API returned no usage."
        )
    cost = usage.get("estimated_cost_usd")
    cost_text = f"${cost:.4f}" if cost is not None else "unavailable"
    assumptions = " ".join(usage.get("assumptions") or [])
    return (
        f"Model: {usage.get('model')} · tier: {usage.get('service_tier')} · "
        f"input: {usage.get('input_tokens')} · cached input: "
        f"{usage.get('cached_input_tokens')} · cache writes: "
        f"{usage.get('cache_write_tokens')} · output: "
        f"{usage.get('output_tokens')} · total: {usage.get('total_tokens')} · "
        f"estimated cost: {cost_text} · pricing configured "
        f"{usage.get('pricing_configuration_date')} · "
        f"source: {usage.get('pricing_source')}. {assumptions}"
    )


def _freshness_caption(value) -> str:
    if not value:
        return "Cache freshness unavailable."
    state = "stale cached data" if value.get("used_stale_cache") else "fresh cache"
    return (
        f"Answer used {state}. Data is current through "
        f"{value.get('latest_cached_observation') or 'an unknown timestamp'}; "
        f"sync status: {value.get('synchronization_status') or 'unknown'}; "
        f"failed meters: {value.get('failed_meter_count', 0)}."
    )


if __name__ == "__main__":
    main()
