"""Transactional outbox dispatcher for judge tasks.

Delivery model: **at-least-once**. A conditional UPDATE claims a pending
outbox row before sending; a crash after the broker accepts the message but
before the claim is confirmed is recovered by the sweeper, and duplicate
deliveries are harmless because every attempt carries one stable ``nonce`` —
identical payloads produce identical signed results, which the result
consumer deduplicates.

Error taxonomy:

* permanent payload problems (missing submission/version, no runnable cases)
  fail the task immediately — retrying can never succeed;
* transient broker problems back off exponentially and give up after a
  bounded number of attempts, instead of hot-looping every few seconds.
"""

from datetime import timedelta
from pathlib import Path
from secrets import token_urlsafe

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import JudgeStatus, JudgeTask, OutboxMessage, OutboxStatus, Submission, TestDataVersion, utcnow
from app.tasks.celery_app import celery_app

MAX_TRANSIENT_ATTEMPTS = 8
# Cap backoff at five minutes; the sweeper provides crash recovery anyway.
MAX_BACKOFF_SECONDS = 300


class PermanentDispatchError(ValueError):
    """The payload can never be delivered successfully (data problem)."""


def _build_payload(db: Session, task: JudgeTask, nonce: str) -> dict:
    submission = db.get(Submission, task.submission_id)
    version = db.get(TestDataVersion, submission.test_data_version_id) if submission else None
    if submission is None or version is None:
        raise PermanentDispatchError("Submission or test-data version is missing")
    cases = version.cases
    if submission.is_sample_run:
        cases = [case for case in cases if case.is_sample]
        if submission.sample_case_id:
            cases = [case for case in cases if case.id == submission.sample_case_id]
    serialized_cases = []
    for case in cases:
        base = Path(version.storage_path)
        try:
            input_data = (base / case.input_key).read_text(encoding="utf-8")
            expected_output = (base / case.output_key).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            # Missing or corrupt test files can never be fixed by redelivery.
            raise PermanentDispatchError(f"Test data file unreadable: {type(exc).__name__}") from exc
        serialized_cases.append(
            {
                "case_id": str(case.id),
                "input_data": input_data,
                "expected_output": expected_output,
                "is_sample": bool(case.is_sample),
            }
        )
    if not serialized_cases:
        raise PermanentDispatchError("No runnable test cases")
    return {
        "task_id": task.id,
        "submission_id": submission.id,
        "attempt": task.attempt,
        "test_data_version_id": version.id,
        "nonce": nonce,
        "language": submission.language.value,
        "source_code": submission.source_code,
        "cases": serialized_cases,
        "time_limit_ms": submission.problem.time_limit_ms,
        "memory_limit_kb": submission.problem.memory_limit_mb * 1024,
        # Security boundary for runtime diagnostics: the worker only returns
        # sanitized user-program stderr for interactive sample runs.
        "is_sample_run": bool(submission.is_sample_run),
    }


def _fail_permanently(db: Session, task: JudgeTask, outbox: OutboxMessage, reason: str) -> None:
    """Terminal failure: no retry can ever succeed."""
    now = utcnow()
    outbox.status = OutboxStatus.FAILED
    outbox.last_error = reason[:500]
    task.status = JudgeStatus.SE
    task.last_error = reason[:500]
    task.finished_at = now
    submission = db.get(Submission, task.submission_id)
    if submission is not None and submission.status in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
        submission.status = JudgeStatus.SE
        submission.diagnostic = reason[:1000]
        submission.finished_at = now
    from app.services.queue_capacity import queue_capacity

    if submission is not None:
        queue_capacity.release(submission.id)


def _claim(db: Session, task_id: str) -> tuple[JudgeTask, OutboxMessage, str] | None:
    """Atomically claim a dispatchable outbox row; None if not dispatchable."""
    now = utcnow()
    nonce = token_urlsafe(24)
    result = db.execute(
        update(OutboxMessage)
        .where(
            OutboxMessage.task_id == task_id,
            OutboxMessage.status == OutboxStatus.PENDING,
            (OutboxMessage.next_attempt_at.is_(None)) | (OutboxMessage.next_attempt_at <= now),
        )
        .values(
            status=OutboxStatus.DISPATCHED,
            dispatched_at=now,
            nonce=func.coalesce(OutboxMessage.nonce, nonce),
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        return None
    outbox = db.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task_id))
    task = db.get(JudgeTask, task_id)
    if task is None or outbox is None or outbox.nonce is None:
        return None
    db.commit()
    return task, outbox, outbox.nonce


def dispatch_outbox(task_id: str) -> bool:
    db = SessionLocal()
    try:
        claimed = _claim(db, task_id)
        if claimed is None:
            return True
        task, outbox, nonce = claimed
        db.commit()
        try:
            payload = _build_payload(db, task, nonce)
        except PermanentDispatchError as exc:
            db.close()
            db = SessionLocal()
            failed_task = db.get(JudgeTask, task_id)
            failed_outbox = db.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task_id))
            if failed_task is not None and failed_outbox is not None:
                _fail_permanently(db, failed_task, failed_outbox, str(exc))
                db.commit()
            return True
        try:
            celery_app.send_task("judge.execute", kwargs={"payload": payload}, queue="judge")
        except Exception as exc:  # noqa: BLE001 - broker errors are transient by nature.
            db.close()
            db = SessionLocal()
            retry_outbox = db.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task_id))
            retry_task = db.get(JudgeTask, task_id)
            if retry_outbox is not None and retry_task is not None:
                retry_outbox.attempts += 1
                retry_outbox.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                if retry_outbox.attempts >= MAX_TRANSIENT_ATTEMPTS:
                    _fail_permanently(db, retry_task, retry_outbox, "Judge dispatch failed repeatedly")
                    db.commit()
                    return True  # Terminal failure is handled; stop retrying.
                else:
                    # Requeue with exponential backoff; only rows still in the
                    # claimed state are touched (a concurrent sweeper may have
                    # moved on already).
                    db.execute(
                        update(OutboxMessage)
                        .where(OutboxMessage.task_id == task_id, OutboxMessage.status == OutboxStatus.DISPATCHED)
                        .values(
                            status=OutboxStatus.PENDING,
                            dispatched_at=None,
                            next_attempt_at=utcnow()
                            + timedelta(seconds=min(MAX_BACKOFF_SECONDS, 2 ** outbox.attempts)),
                        )
                    )
                db.commit()
            return False
        now = utcnow()
        # A successful send only means the task is queued: JUDGING starts when a
        # worker publishes a signed "started" event (see app/tasks/results.py),
        # which also opens the execution lease.
        task.status = JudgeStatus.PENDING
        task.queued_at = now
        task.started_at = None
        task.lease_expires_at = None
        outbox.last_error = None
        db.commit()
        return True
    finally:
        db.close()


def process_outbox(limit: int = 100) -> dict[str, int]:
    db = SessionLocal()
    try:
        now = utcnow()
        ids = db.scalars(
            select(JudgeTask.id)
            .join(OutboxMessage, OutboxMessage.task_id == JudgeTask.id)
            .where(
                OutboxMessage.status == OutboxStatus.PENDING,
                (OutboxMessage.next_attempt_at.is_(None)) | (OutboxMessage.next_attempt_at <= now),
            )
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        ).all()
    finally:
        db.close()
    dispatched = sum(dispatch_outbox(task_id) for task_id in ids)
    return {"selected": len(ids), "dispatched": dispatched, "failed": len(ids) - dispatched}
