"""Celery entry point for the isolated judge host.

This module intentionally imports no business application, ORM, or database.
Configure JUDGE_RESULT_SECRET and JUDGE_RESULT_REDIS_URL independently.
"""

import hashlib
import hmac
import json
import os
import time
from typing import Any

import redis
from celery import Celery

from judge.protocol import JudgeRequest, TestCase
from judge.worker import judge

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
celery_app = Celery("xinbaoyan-judge", broker=broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_publish_retry=False,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _publish_result(payload: dict[str, Any]) -> None:
    secret = os.environ.get("JUDGE_RESULT_SECRET", "")
    if len(secret) < 16:
        raise RuntimeError("JUDGE_RESULT_SECRET must be configured")
    result_url = os.environ.get("JUDGE_RESULT_REDIS_URL") or "redis://127.0.0.1:6379/0"
    queue = os.environ.get("JUDGE_RESULT_QUEUE", "judge:results")
    signature = hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()
    client = redis.Redis.from_url(result_url, socket_connect_timeout=2, socket_timeout=2)
    client.rpush(queue, json.dumps({"payload": payload, "signature": signature}, ensure_ascii=False))


def _publish_result_with_retry(payload: dict[str, Any], attempts: int = 5) -> None:
    # A lost result would leave the submission stuck in JUDGING; retry with
    # backoff and finally let Celery redeliver (acks_late) if Redis stays down.
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            _publish_result(payload)
            return
        except Exception as exc:  # noqa: BLE001 - report the last failure below.
            last_error = exc
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Unable to publish judge result after {attempts} attempts: {last_error}")


def _worker_id() -> str:
    return os.environ.get("JUDGE_WORKER_ID") or os.environ.get("COMPUTERNAME") or "judge-worker"


def _execution_lease_seconds(payload: dict[str, Any], case_count: int) -> int:
    # Generous upper bound so a healthy worker is never reaped mid-run: compile
    # limit once, then several multiples of the per-case time limit plus slack.
    compile_ms = int(payload.get("compile_time_limit_ms", 10_000))
    per_case_ms = int(payload.get("time_limit_ms", 1_000))
    return max(120, compile_ms // 1000 + case_count * max(5, per_case_ms // 1000 * 3) + 120)


@celery_app.task(name="judge.execute", bind=True, ignore_result=True)
def execute(self, payload: dict[str, Any]) -> None:
    from judge import heartbeat

    # Honor the admin "stop accepting" switch before touching new work; the
    # message stays unacknowledged (acks_late) so only this worker is held.
    if not heartbeat.wait_if_paused():
        raise RuntimeError("Worker held task too long while stopped")
    heartbeat.task_started()
    try:
        _execute(payload)
    finally:
        heartbeat.task_finished()


def _execute(payload: dict[str, Any]) -> None:
    case_count = len(payload["cases"])
    _publish_result_with_retry(
        {
            "event": "started",
            "task_id": payload["task_id"],
            "submission_id": payload["submission_id"],
            "attempt": payload["attempt"],
            "test_data_version_id": payload["test_data_version_id"],
            "nonce": payload["nonce"],
            "worker_id": _worker_id(),
            "lease_seconds": _execution_lease_seconds(payload, case_count),
        }
    )
    request = JudgeRequest(
        request_id=payload["task_id"],
        language=payload["language"],
        source_code=payload["source_code"],
        cases=tuple(
            TestCase(
                case_id=str(case["case_id"]),
                input_data=case["input_data"],
                expected_output=case["expected_output"],
                is_sample=bool(case.get("is_sample", False)),
            )
            for case in payload["cases"]
        ),
        time_limit_ms=payload["time_limit_ms"],
        memory_limit_kb=payload["memory_limit_kb"],
    )
    from judge.config import JudgeConfig

    result = judge(request, JudgeConfig.from_env())
    result_payload = {
        "task_id": payload["task_id"],
        "submission_id": payload["submission_id"],
        "status": result.status.value,
        "runtime_ms": result.runtime_ms,
        "memory_kb": result.memory_kb,
        "diagnostic": result.diagnostic[:1000],
        "attempt": payload["attempt"],
        "test_data_version_id": payload["test_data_version_id"],
        "nonce": payload["nonce"],
    }
    _publish_result_with_retry(result_payload)
