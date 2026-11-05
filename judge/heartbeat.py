"""Signed heartbeat client for the independent judge host.

Also carries the local execution state (active/completed counters and the
admin "accepting" switch) so the Celery worker can pause before picking up
new work when an operator stops it from the admin console.
"""

import hashlib
import hmac
import json
import os
import platform
import threading
import time
import urllib.request
from typing import Any

_lock = threading.Lock()
_accepting = True
_active_tasks = 0
_completed = 0


def is_accepting() -> bool:
    with _lock:
        return _accepting


def task_started() -> None:
    global _active_tasks
    with _lock:
        _active_tasks += 1


def task_finished() -> None:
    global _active_tasks, _completed
    with _lock:
        _active_tasks = max(0, _active_tasks - 1)
        _completed += 1


def wait_if_paused(poll_seconds: float = 5.0, max_hold_seconds: float = 3600.0) -> bool:
    """Block while the admin switch has stopped this worker. Returns False on timeout."""
    deadline = time.monotonic() + max_hold_seconds
    while not is_accepting():
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)
    return True


def _process_metrics() -> tuple[float | None, float | None]:
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(os.getpid())
        cpu = min(100.0, process.cpu_percent(interval=None))
        memory = min(100.0, process.memory_percent())
        return cpu, memory
    except Exception:
        return None, None


def send_heartbeat() -> None:
    api_url = os.environ.get("JUDGE_HEARTBEAT_URL", "http://127.0.0.1:8000/api/v1/internal/judge/heartbeat")
    secret = os.environ.get("JUDGE_RESULT_SECRET", "")
    if len(secret) < 16:
        raise RuntimeError("JUDGE_RESULT_SECRET must be configured")
    with _lock:
        active = _active_tasks
        completed = _completed
    cpu, memory = _process_metrics()
    payload: dict[str, Any] = {
        "worker_id": os.environ.get("JUDGE_WORKER_ID", platform.node()),
        "host": platform.node(),
        "active_tasks": active,
        "completed": completed,
        "cpu": cpu,
        "memory": memory,
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Judge-Signature": signature},
    )
    global _accepting
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Heartbeat failed with HTTP {response.status}")
        result = json.loads(response.read().decode("utf-8"))
    # A missing flag keeps the previous state: heartbeat responses from older
    # servers (or proxies) must not silently change the control switch.
    if isinstance(result, dict) and isinstance(result.get("accepting"), bool):
        with _lock:
            _accepting = result["accepting"]


def main() -> None:
    interval = max(2, int(os.environ.get("JUDGE_HEARTBEAT_INTERVAL", "10")))
    while True:
        try:
            send_heartbeat()
        except Exception:
            # Keep the last known switch state; a network blip must not stall
            # or silently re-enable a stopped worker.
            pass
        time.sleep(interval)


if __name__ == "__main__":
    main()
