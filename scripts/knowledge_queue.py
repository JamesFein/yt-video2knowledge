#!/usr/bin/env python3
"""Core lock and status helpers for the local knowledge digest queue worker."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
LOCK_HEARTBEAT_TTL = timedelta(minutes=10)


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def write_worker_lock(
    lock_path: Path,
    *,
    pid: int | None = None,
    started_at: datetime | None = None,
    heartbeat: datetime | None = None,
) -> dict[str, Any]:
    now = beijing_now()
    payload = {
        "pid": pid or os.getpid(),
        "started_at": (started_at or now).isoformat(),
        "heartbeat": (heartbeat or now).isoformat(),
    }
    _write_json(lock_path, payload)
    return payload


def inspect_worker_lock(
    lock_path: Path,
    *,
    clock=beijing_now,
    pid_exists=is_pid_alive,
    heartbeat_ttl: timedelta = LOCK_HEARTBEAT_TTL,
) -> dict[str, Any]:
    if not lock_path.exists():
        return {"status": "missing", "is_stale": False, "is_running": False}

    payload = _read_json(lock_path, {})
    try:
        pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        pid = None
    heartbeat = _parse_datetime(payload.get("heartbeat"))
    process_alive = pid_exists(pid)
    heartbeat_expired = heartbeat is None or clock() - heartbeat > heartbeat_ttl
    is_stale = not process_alive or heartbeat_expired
    reason = None
    if not process_alive:
        reason = "pid_not_running"
    elif heartbeat_expired:
        reason = "heartbeat_expired"
    return {
        "status": "stale" if is_stale else "running",
        "is_stale": is_stale,
        "is_running": not is_stale,
        "reason": reason,
        "lock": payload,
    }


def acquire_worker_lock(
    lock_path: Path,
    *,
    pid: int | None = None,
    clock=beijing_now,
    pid_exists=is_pid_alive,
) -> bool:
    inspection = inspect_worker_lock(lock_path, clock=clock, pid_exists=pid_exists)
    if inspection["is_running"]:
        return False
    write_worker_lock(lock_path, pid=pid, started_at=clock(), heartbeat=clock())
    return True


def release_worker_lock(lock_path: Path, *, pid: int | None = None, force: bool = False) -> bool:
    if not lock_path.exists():
        return True
    payload = _read_json(lock_path, {})
    owner_pid = pid if pid is not None else os.getpid()
    try:
        lock_pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        lock_pid = None
    if force or lock_pid == owner_pid:
        lock_path.unlink(missing_ok=True)
        return True
    return False


def record_worker_interrupted(
    state_path: Path,
    lock_path: Path,
    *,
    target_date: str | None = None,
    request_path: Path | None = None,
    clock=beijing_now,
) -> dict[str, Any]:
    state = _read_json(state_path, {})
    state.update(
        {
            "status": "interrupted",
            "interrupted_at": clock().isoformat(),
        }
    )
    if target_date:
        state["target_date"] = target_date
    if request_path:
        state["request_path"] = str(request_path)
    _write_json(state_path, state)
    release_worker_lock(lock_path, force=True)
    return state


def classify_digest_manifest(manifest: dict[str, Any]) -> str:
    failed_count = int(manifest.get("failed_count") or 0)
    pending_summary_count = int(manifest.get("pending_summary_count") or 0)
    return "success" if failed_count == 0 and pending_summary_count == 0 else "partial"


def format_worker_status(
    state_path: Path,
    lock_path: Path,
    *,
    manifest_path: Path | None = None,
    clock=beijing_now,
    pid_exists=is_pid_alive,
) -> str:
    state = _read_json(state_path, {})
    lock = inspect_worker_lock(lock_path, clock=clock, pid_exists=pid_exists)
    status = state.get("status") or "idle"
    action = "wait"
    if lock["status"] == "stale":
        status = "stale lock"
        action = "recover"
    elif status == "interrupted":
        action = "retry request"

    lines = [
        f"status: {status}",
        f"lock: {lock['status']}",
        f"action: {action}",
    ]
    if state.get("target_date"):
        lines.append(f"target_date: {state['target_date']}")
    if manifest_path and manifest_path.exists():
        manifest = _read_json(manifest_path, {})
        digest_status = classify_digest_manifest(manifest)
        lines.append(f"digest: {digest_status}")
        lines.append(f"failed_count: {int(manifest.get('failed_count') or 0)}")
        lines.append(f"pending_summary_count: {int(manifest.get('pending_summary_count') or 0)}")
    return "\n".join(lines)
