from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.data.cache import EnergyCache
from src.data.extraction import synchronize
from src.data.schemas import Hierarchy, Meter, Organization, Site
from src.data.sync_manager import (
    AutoSyncManager,
    FileSyncLock,
    SyncAlreadyRunning,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def settings(**overrides):
    values = {
        "data_sync_interval_minutes": 60,
        "data_auto_sync": True,
        "data_sync_initial_lookback_days": 365,
        "data_sync_max_retries": 3,
        "data_sync_lock_timeout_seconds": 900,
        "wattics_api_token": "test-token",
        "wattics_api_base_url": "https://example.test",
        "wattics_timeout_seconds": 1,
        "wattics_max_retries": 0,
        "default_timezone": "UTC",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeClientContext:
    def __init__(self, client=None, error=None):
        self.client = client or object()
        self.error = error

    def __enter__(self):
        if self.error:
            raise self.error
        return self.client

    def __exit__(self, exc_type, exc, traceback):
        return None


def empty_hierarchy(*args, **kwargs):
    return Hierarchy(discovered_at=NOW.isoformat())


def successful_sync(client, cache, hierarchy, **kwargs):
    cache.write_sync_state({"last_successful_sync": NOW.isoformat(), "meters": {}})
    return {
        "failed_meter_count": 0,
        "failures": [],
        "successful_meter_count": 0,
    }


def test_empty_cache_triggers_incremental_update(tmp_path):
    cache = EnergyCache(tmp_path)
    manager = AutoSyncManager(
        settings(),
        cache,
        now_provider=lambda: NOW,
        client_factory=lambda: FakeClientContext(),
        discover_callable=empty_hierarchy,
        sync_callable=successful_sync,
    )
    result = manager.ensure_fresh(reason="startup")
    assert result["status"] == "success"
    assert result["synchronized"] is True
    assert manager.freshness().fresh is True


def test_fresh_cache_does_not_contact_api(tmp_path):
    cache = EnergyCache(tmp_path)
    cache.write_sync_state({"last_successful_sync": NOW.isoformat(), "meters": {}})
    assert cache.status()["synchronization_status"] == "idle"

    def should_not_run():
        raise AssertionError("API client should not be constructed for a fresh cache")

    manager = AutoSyncManager(
        settings(),
        cache,
        now_provider=lambda: NOW,
        client_factory=should_not_run,
    )
    result = manager.ensure_fresh(reason="before_query")
    assert result["status"] == "fresh"
    assert result["synchronized"] is False
    assert cache.status()["synchronization_status"] == "fresh"
    assert cache.status()["last_sync_attempt"] == NOW.isoformat()


def test_stale_cache_receives_incremental_not_full_refresh(tmp_path):
    cache = EnergyCache(tmp_path)
    cache.write_sync_state(
        {
            "last_successful_sync": (NOW - timedelta(hours=2)).isoformat(),
            "meters": {},
        }
    )
    observed = {}

    def checked_sync(client, cache, hierarchy, **kwargs):
        observed.update(kwargs)
        return successful_sync(client, cache, hierarchy, **kwargs)

    manager = AutoSyncManager(
        settings(),
        cache,
        now_provider=lambda: NOW,
        client_factory=lambda: FakeClientContext(),
        discover_callable=empty_hierarchy,
        sync_callable=checked_sync,
    )
    result = manager.ensure_fresh(reason="before_query")
    assert result["status"] == "success"
    assert observed["full_refresh"] is False
    assert observed["end_utc"] == NOW
    assert observed["start_utc"] == NOW - timedelta(days=365)


def test_failed_api_keeps_valid_old_cache_and_reports_stale(tmp_path):
    cache = EnergyCache(tmp_path)
    previous = (NOW - timedelta(hours=4)).isoformat()
    cache.write_sync_state({"last_successful_sync": previous, "meters": {}})
    manager = AutoSyncManager(
        settings(data_sync_max_retries=2),
        cache,
        now_provider=lambda: NOW,
        client_factory=lambda: FakeClientContext(
            error=ConnectionError("API unavailable")
        ),
    )
    result = manager.ensure_fresh(reason="before_query")
    assert result["status"] == "failed"
    assert result["used_stale_cache"] is True
    assert cache.read_sync_state()["last_successful_sync"] == previous
    assert "API unavailable" in result["last_error"]


def test_simultaneous_refresh_is_rejected_without_corrupting_lock(tmp_path):
    cache = EnergyCache(tmp_path)
    manager = AutoSyncManager(
        settings(),
        cache,
        now_provider=lambda: NOW,
        client_factory=lambda: FakeClientContext(),
        discover_callable=empty_hierarchy,
        sync_callable=successful_sync,
    )
    with FileSyncLock(
        cache.sync_lock_path,
        stale_after_seconds=900,
        now_provider=lambda: NOW,
    ):
        result = manager.ensure_fresh(reason="manual_refresh", force=True)
        assert result["status"] == "already_running"
        assert cache.sync_lock_path.exists()
    assert not cache.sync_lock_path.exists()


def test_orphaned_lock_is_reclaimed_immediately(tmp_path):
    cache = EnergyCache(tmp_path)
    cache.sync_lock_path.parent.mkdir(parents=True, exist_ok=True)
    cache.sync_lock_path.write_text(
        json.dumps(
            {
                "pid": 999_999,
                "hostname": socket.gethostname(),
                "acquired_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    with patch("src.data.sync_manager._process_is_running", return_value=False):
        with FileSyncLock(
            cache.sync_lock_path,
            stale_after_seconds=900,
            now_provider=lambda: NOW,
        ):
            current = json.loads(cache.sync_lock_path.read_text(encoding="utf-8"))
            assert current["pid"] != 999_999
            assert current["hostname"] == socket.gethostname()
    assert not cache.sync_lock_path.exists()


def test_live_lock_is_not_reclaimed_before_timeout(tmp_path):
    cache = EnergyCache(tmp_path)
    cache.sync_lock_path.parent.mkdir(parents=True, exist_ok=True)
    cache.sync_lock_path.write_text(
        json.dumps(
            {
                "pid": 999_998,
                "hostname": socket.gethostname(),
                "acquired_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("src.data.sync_manager._process_is_running", return_value=True),
        pytest.raises(SyncAlreadyRunning),
    ):
        with FileSyncLock(
            cache.sync_lock_path,
            stale_after_seconds=900,
            now_provider=lambda: NOW,
        ):
            pass
    assert cache.sync_lock_path.exists()


def one_meter_hierarchy():
    organization = Organization(id="o1", name="Food Corp.")
    site = Site(
        id="s1",
        name="Factory",
        organization_id="o1",
        organization_name="Food Corp.",
        timezone="UTC",
        timezone_assumed=False,
    )
    meter = Meter(
        id="m1",
        name="Main",
        site_id="s1",
        site_name="Factory",
        organization_id="o1",
        organization_name="Food Corp.",
        measurement_type="electricity",
        unit="W",
        reading_type="Interval",
        interval_minutes=15,
        timezone="UTC",
        timezone_assumed=False,
    )
    return Hierarchy(
        organizations=[organization],
        sites=[site],
        meters=[meter],
        discovered_at=NOW.isoformat(),
    )


class DuplicateClient:
    def get_raw_data(self, *args, **kwargs):
        return [
            {"timestamp": "2026-07-01T00:00:00Z", "total": 4000},
            {"timestamp": "2026-07-01T00:00:00Z", "total": 4000},
            {"timestamp": "2026-07-01T00:15:00Z", "total": 5000},
        ]


def test_duplicate_intervals_are_deduplicated_during_update(tmp_path):
    cache = EnergyCache(tmp_path)
    result = synchronize(
        DuplicateClient(),
        cache,
        one_meter_hierarchy(),
        start_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )
    data = cache.read_meter("m1")
    assert result["failed_meter_count"] == 0
    assert len(data) == 2
    cleaning = cache.read_sync_state()["meters"]["m1"]["cleaning"]
    assert cleaning["exact_duplicate_count"] == 1


class FailingClient:
    def get_raw_data(self, *args, **kwargs):
        raise ConnectionError("interrupted")


def test_interrupted_update_preserves_previous_meter_partition(tmp_path, energy_frame):
    cache = EnergyCache(tmp_path)
    cache.write_meter("m1", energy_frame)
    before = cache.read_meter("m1")
    result = synchronize(
        FailingClient(),
        cache,
        one_meter_hierarchy(),
        start_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
        end_utc=datetime(2026, 3, 20, tzinfo=timezone.utc),
    )
    after = cache.read_meter("m1")
    assert result["failed_meter_count"] == 1
    assert len(after) == len(before)
    assert after["energy_kwh"].equals(before["energy_kwh"])
