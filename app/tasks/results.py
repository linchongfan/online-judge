"""Judge result/event handling shared by consumers.

All messages on the result queue are HMAC-signed by the worker and validated
before they reach this module. Two message kinds exist:

* ``started`` — a worker actually began executing a task; opens the
  execution lease and moves the task/submission from queued to JUDGING.
* terminal result — the outcome of a task attempt.
"""

from datetime import timedelta
from hashlib import sha256

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.exceptions import AppError
from app.core.signing import canonical_payload
from app.db import SessionLocal
from app.models import (
    TERMINAL_JUDGE_STATUSES,
    Contest,
    JudgeStatus,
    JudgeTask,
    Submission,
    utcnow,
)
from app.schemas.submission import JudgeResultMessage, JudgeStartedMessage
from app.services.contests import recompute_contest_results

SUPERSEDED_ERROR = "Superseded by a newer judge attempt"


def process_judge_started(data: dict) -> bool:
    try:
        message = JudgeStartedMessage.model_validate(data)
    except ValidationError as exc:
        raise AppError(400, "INVALID_JUDGE_EVENT", "判题事件格式无效") from exc
    db = SessionLocal()
    try:
        task = db.get(JudgeTask, message.task_id)
        submission = db.get(Submission, message.submission_id) if task else None
        if (
            task is None
            or submission is None
            or task.submission_id != submission.id
            or task.attempt != message.attempt
            or submission.test_data_version_id != message.test_data_version_id
        ):
            raise AppError(400, "RESULT_IDENTITY_MISMATCH", "判题事件与任务不匹配")
        latest_attempt = db.scalar(select(func.max(JudgeTask.attempt)).where(JudgeTask.submission_id == submission.id))
        if latest_attempt != task.attempt or task.status in TERMINAL_JUDGE_STATUSES:
            # Stale attempt or already finished: nothing to start.
            return False
        if task.status not in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
            raise AppError(409, "INVALID_STATE_TRANSITION", "判题任务状态流转无效")
        now = utcnow()
        task.status = JudgeStatus.JUDGING
        task.started_at = task.started_at or now
        task.lease_owner = message.worker_id[:100]
        task.lease_expires_at = now + timedelta(seconds=message.lease_seconds)
        submission.status = JudgeStatus.JUDGING
        submission.started_at = submission.started_at or now
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _mark_superseded(task: JudgeTask) -> None:
    task.status = JudgeStatus.SE
    task.last_error = SUPERSEDED_ERROR
    task.finished_at = utcnow()


def process_judge_result(data: dict) -> bool:
    try:
        message = JudgeResultMessage.model_validate(data)
    except ValidationError as exc:
        raise AppError(400, "INVALID_JUDGE_RESULT", "判题结果格式无效") from exc
    if message.status not in TERMINAL_JUDGE_STATUSES:
        raise AppError(400, "INVALID_JUDGE_STATUS", "结果消费者只接受终态结果")
    db = SessionLocal()
    try:
        task = db.get(JudgeTask, message.task_id)
        submission = db.get(Submission, message.submission_id) if task else None
        if (
            task is None
            or submission is None
            or task.submission_id != submission.id
            or task.attempt != message.attempt
            or submission.test_data_version_id != message.test_data_version_id
        ):
            raise AppError(400, "RESULT_IDENTITY_MISMATCH", "判题结果与任务不匹配")
        latest_attempt = db.scalar(select(func.max(JudgeTask.attempt)).where(JudgeTask.submission_id == submission.id))
        if latest_attempt != task.attempt:
            # Late result for an old attempt: end the old task so it cannot be
            # re-dispatched by the sweeper or picked up by batch rejudges.
            if task.status not in TERMINAL_JUDGE_STATUSES:
                _mark_superseded(task)
                db.commit()
            return False
        result_hash = sha256(canonical_payload(message.model_dump())).hexdigest()
        if task.status in TERMINAL_JUDGE_STATUSES:
            if task.status is JudgeStatus.SE and task.last_error == SUPERSEDED_ERROR:
                return False
            if task.result_hash == result_hash:
                return False
            raise AppError(409, "CONFLICTING_JUDGE_RESULT", "同一任务不能上报不同终态")
        if task.status not in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
            raise AppError(409, "INVALID_STATE_TRANSITION", "判题任务状态流转无效")
        now = utcnow()
        task.status = message.status
        task.runtime_ms = message.runtime_ms
        task.memory_kb = message.memory_kb
        task.diagnostic = message.diagnostic[:1000] if message.diagnostic else None
        task.result_hash = result_hash
        task.finished_at = now
        submission.status = message.status
        submission.runtime_ms = message.runtime_ms
        submission.memory_kb = message.memory_kb
        submission.diagnostic = message.diagnostic[:1000] if message.diagnostic else None
        submission.started_at = submission.started_at or task.started_at or now
        submission.finished_at = now
        if submission.contest_id and not submission.is_sample_run:
            contest = db.get(Contest, submission.contest_id)
            if contest:
                recompute_contest_results(db, contest)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
