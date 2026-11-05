from pathlib import Path
from secrets import token_urlsafe

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import JudgeStatus, JudgeTask, OutboxMessage, OutboxStatus, Submission, TestDataVersion, utcnow
from app.tasks.celery_app import celery_app


def _build_payload(db: Session, task: JudgeTask) -> dict:
    submission = db.get(Submission, task.submission_id)
    version = db.get(TestDataVersion, submission.test_data_version_id) if submission else None
    if submission is None or version is None:
        raise ValueError("Submission or test-data version is missing")
    cases = version.cases
    if submission.is_sample_run:
        cases = [case for case in cases if case.is_sample]
        if submission.sample_case_id:
            cases = [case for case in cases if case.id == submission.sample_case_id]
    serialized_cases = []
    for case in cases:
        base = Path(version.storage_path)
        serialized_cases.append(
            {
                "case_id": str(case.id),
                "input_data": (base / case.input_key).read_text(encoding="utf-8"),
                "expected_output": (base / case.output_key).read_text(encoding="utf-8"),
                "is_sample": bool(case.is_sample),
            }
        )
    if not serialized_cases:
        raise ValueError("No runnable test cases")
    return {
        "task_id": task.id,
        "submission_id": submission.id,
        "attempt": task.attempt,
        "test_data_version_id": version.id,
        "nonce": token_urlsafe(24),
        "language": submission.language.value,
        "source_code": submission.source_code,
        "cases": serialized_cases,
        "time_limit_ms": submission.problem.time_limit_ms,
        "memory_limit_kb": submission.problem.memory_limit_mb * 1024,
    }


def dispatch_outbox(task_id: str) -> bool:
    db = SessionLocal()
    try:
        task = db.get(JudgeTask, task_id)
        outbox = db.scalar(select(OutboxMessage).where(OutboxMessage.task_id == task_id))
        if task is None or outbox is None or outbox.status == OutboxStatus.DISPATCHED:
            return True
        try:
            payload = _build_payload(db, task)
            celery_app.send_task("judge.execute", kwargs={"payload": payload}, queue="judge")
            now = utcnow()
            # A successful send only means the task is queued: JUDGING starts
            # when a worker publishes a signed "started" event (see
            # app/tasks/results.py), which also opens the execution lease.
            task.status = JudgeStatus.PENDING
            task.queued_at = now
            task.started_at = None
            task.lease_expires_at = None
            outbox.status = OutboxStatus.DISPATCHED
            outbox.dispatched_at = now
            outbox.last_error = None
            db.commit()
            return True
        except Exception as exc:
            outbox.attempts += 1
            outbox.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            db.commit()
            return False
    finally:
        db.close()


def process_outbox(limit: int = 100) -> dict[str, int]:
    db = SessionLocal()
    try:
        ids = db.scalars(
            select(JudgeTask.id)
            .join(OutboxMessage, OutboxMessage.task_id == JudgeTask.id)
            .where(OutboxMessage.status == OutboxStatus.PENDING)
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        ).all()
    finally:
        db.close()
    dispatched = sum(dispatch_outbox(task_id) for task_id in ids)
    return {"selected": len(ids), "dispatched": dispatched, "failed": len(ids) - dispatched}
