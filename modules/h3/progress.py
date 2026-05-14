from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

H3_PROGRESS_LOCK = threading.Lock()
H3_PROGRESS: Dict[str, Dict[str, Any]] = {}
H3_PROGRESS_TTL_SEC = 3600


def cleanup_h3_progress(now_ts: Optional[float] = None) -> None:
    now_value = float(now_ts if now_ts is not None else time.time())
    stale_ids = []
    for run_id, item in H3_PROGRESS.items():
        updated_at = float(item.get("updated_at") or 0.0)
        if (now_value - updated_at) > float(H3_PROGRESS_TTL_SEC):
            stale_ids.append(run_id)
    for run_id in stale_ids:
        H3_PROGRESS.pop(run_id, None)


def update_h3_progress(
    run_id: str,
    *,
    status: str = "running",
    stage: str = "",
    message: str = "",
    step: Optional[int] = None,
    total: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now_ts = float(time.time())
    run_key = str(run_id or "").strip()
    if not run_key:
        run_key = uuid.uuid4().hex
    with H3_PROGRESS_LOCK:
        cleanup_h3_progress(now_ts)
        existing = H3_PROGRESS.get(run_key) or {}
        started_at = float(existing.get("started_at") or now_ts)
        try:
            step_value = int(step) if step is not None else None
        except (TypeError, ValueError):
            step_value = None
        try:
            total_value = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_value = None
        payload = {
            "run_id": run_key,
            "status": str(status or "running"),
            "stage": str(stage or ""),
            "message": str(message or ""),
            "step": step_value,
            "total": total_value,
            "started_at": started_at,
            "updated_at": now_ts,
            "elapsed_sec": round(max(0.0, now_ts - started_at), 1),
            "extra": dict(extra or {}),
        }
        H3_PROGRESS[run_key] = payload
        return dict(payload)


def get_h3_progress(run_id: str) -> Optional[Dict[str, Any]]:
    run_key = str(run_id or "").strip()
    if not run_key:
        return None
    now_ts = float(time.time())
    with H3_PROGRESS_LOCK:
        cleanup_h3_progress(now_ts)
        payload = H3_PROGRESS.get(run_key)
        if not payload:
            return None
        data = dict(payload)
        started_at = float(data.get("started_at") or now_ts)
        data["elapsed_sec"] = round(max(0.0, now_ts - started_at), 1)
        return data
