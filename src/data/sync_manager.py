"""Freshness-aware incremental synchronization with a cross-process file lock."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from src.api.wattics_client import WatticsClient
from src.data.cache import EnergyCache
from src.data.discovery import TARGET_ORGANIZATIONS, discover_hierarchy
from src.data.extraction import synchronize


class SyncAlreadyRunning(RuntimeError):
    """Another process currently owns the synchronization lock."""


@dataclass(frozen=True)
class Freshness:
    state: str
    last_successful_sync: Optional[str]
    age_minutes: Optional[float]
    interval_minutes: int

    @property
    def fresh(self) -> bool:
        return self.state == "fresh"

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "fresh": self.fresh,
            "last_successful_sync": self.last_successful_sync,
            "age_minutes": self.age_minutes,
            "interval_minutes": self.interval_minutes,
        }


class FileSyncLock:
    def __init__(
        self,
        path: Path,
        *,
        stale_after_seconds: int,
        now_provider: Callable[[], datetime],
    ) -> None:
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
        self.now_provider = now_provider
        self.acquired = False

    def __enter__(self) -> "FileSyncLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            descriptor = os.open(str(self.path), flags)
        except FileExistsError as exc:
            raise SyncAlreadyRunning(
                "A synchronization process already holds the cache lock."
            ) from exc
        try:
            payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "acquired_at": self.now_provider()
                    .astimezone(timezone.utc)
                    .isoformat(),
                }
            ).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

    def _remove_stale_lock(self) -> None:
        if not self.path.exists():
            return
        try:
            initial_stat = self.path.stat()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
            try:
                initial_stat = self.path.stat()
            except FileNotFoundError:
                return

        owner_pid = payload.get("pid")
        owner_hostname = payload.get("hostname")
        owner_is_local = not owner_hostname or owner_hostname == socket.gethostname()
        owner_is_dead = (
            owner_is_local
            and isinstance(owner_pid, int)
            and not _process_is_running(owner_pid)
        )
        age = self.now_provider().timestamp() - initial_stat.st_mtime
        if owner_is_dead or age > self.stale_after_seconds:
            self._unlink_if_unchanged(initial_stat.st_mtime_ns)

    def _unlink_if_unchanged(self, expected_mtime_ns: int) -> None:
        """Remove only the exact lock inspected, never a newly replaced lock."""
        try:
            if self.path.stat().st_mtime_ns != expected_mtime_ns:
                return
            self.path.unlink()
        except FileNotFoundError:
            pass


def _process_is_running(pid: int) -> bool:
    """Check lock ownership without signaling or terminating the process."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Access denied indicates a protected but live process.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AutoSyncManager:
    def __init__(
        self,
        settings: Any,
        cache: EnergyCache,
        *,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        client_factory: Optional[Callable[[], Any]] = None,
        discover_callable: Callable[..., Any] = discover_hierarchy,
        sync_callable: Callable[..., dict] = synchronize,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.now_provider = now_provider
        self.client_factory = client_factory or self._default_client_factory
        self.discover_callable = discover_callable
        self.sync_callable = sync_callable

    def freshness(self) -> Freshness:
        status = self.cache.status()
        last = status.get("last_successful_sync")
        interval = int(self.settings.data_sync_interval_minutes)
        if not last:
            return Freshness("missing", None, None, interval)
        try:
            parsed = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except ValueError:
            return Freshness("stale", str(last), None, interval)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = max(
            0.0,
            (
                self.now_provider().astimezone(timezone.utc)
                - parsed.astimezone(timezone.utc)
            ).total_seconds()
            / 60.0,
        )
        return Freshness(
            "fresh" if age <= interval else "stale",
            str(last),
            age,
            interval,
        )

    def ensure_fresh(
        self,
        *,
        reason: str,
        force: bool = False,
    ) -> dict:
        before = self.freshness()
        if not force and not self.settings.data_auto_sync:
            outcome = self._outcome("disabled", reason, before, synchronized=False)
            self.cache.write_sync_runtime(outcome)
            return outcome
        if not force and before.fresh:
            outcome = self._outcome("fresh", reason, before, synchronized=False)
            self.cache.write_sync_runtime(outcome)
            return outcome
        if not self.settings.wattics_api_token:
            outcome = self._outcome(
                "failed",
                reason,
                before,
                synchronized=False,
                error="WATTICS_API_TOKEN is not configured.",
            )
            self.cache.write_sync_runtime(outcome)
            return outcome

        try:
            with FileSyncLock(
                self.cache.sync_lock_path,
                stale_after_seconds=int(self.settings.data_sync_lock_timeout_seconds),
                now_provider=self.now_provider,
            ):
                return self._synchronize_with_retries(reason, before)
        except SyncAlreadyRunning as exc:
            outcome = self._outcome(
                "already_running",
                reason,
                before,
                synchronized=False,
                error=str(exc),
            )
            self.cache.write_sync_runtime(outcome)
            return outcome

    def _synchronize_with_retries(self, reason: str, before: Freshness) -> dict:
        now = self.now_provider().astimezone(timezone.utc)
        start = now - timedelta(days=int(self.settings.data_sync_initial_lookback_days))
        last_error: Optional[str] = None
        result: Optional[dict] = None
        attempts = int(self.settings.data_sync_max_retries)
        for attempt in range(1, attempts + 1):
            running = self._outcome(
                "running",
                reason,
                before,
                synchronized=False,
                attempt=attempt,
            )
            self.cache.write_sync_runtime(running)
            try:
                with self.client_factory() as client:
                    hierarchy = self.discover_callable(
                        client,
                        default_timezone=self.settings.default_timezone,
                        target_names=TARGET_ORGANIZATIONS,
                    )
                    result = self.sync_callable(
                        client,
                        self.cache,
                        hierarchy,
                        start_utc=start,
                        end_utc=now,
                        full_refresh=False,
                    )
                if not result.get("failed_meter_count"):
                    after = self.freshness()
                    outcome = self._outcome(
                        "success",
                        reason,
                        after,
                        synchronized=True,
                        attempt=attempt,
                        result=result,
                    )
                    self.cache.write_sync_runtime(outcome)
                    return outcome
                last_error = (
                    f"{result.get('failed_meter_count')} meter update(s) failed."
                )
            except Exception as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"

        after = self.freshness()
        outcome = self._outcome(
            "partial_failure" if result else "failed",
            reason,
            after,
            synchronized=bool(result),
            attempt=attempts,
            result=result,
            error=last_error,
        )
        self.cache.write_sync_runtime(outcome)
        return outcome

    def _default_client_factory(self) -> WatticsClient:
        return WatticsClient(
            self.settings.wattics_api_token or "",
            base_url=self.settings.wattics_api_base_url,
            timeout_seconds=self.settings.wattics_timeout_seconds,
            max_retries=self.settings.wattics_max_retries,
        )

    def _outcome(
        self,
        status: str,
        reason: str,
        freshness: Freshness,
        *,
        synchronized: bool,
        attempt: Optional[int] = None,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> dict:
        failed_meters = (
            list((result or {}).get("failures") or [])
            if result is not None
            else self.cache.read_failed_meters()
        )
        return {
            "status": status,
            "reason": reason,
            "last_attempt": self.now_provider().astimezone(timezone.utc).isoformat(),
            "last_error": error,
            "attempt": attempt,
            "synchronized": synchronized,
            "freshness": freshness.as_dict(),
            "last_successful_sync": freshness.last_successful_sync,
            "failed_meter_count": len(failed_meters),
            "failed_meters": failed_meters,
            "used_stale_cache": not freshness.fresh,
        }
