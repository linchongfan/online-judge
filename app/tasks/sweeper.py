from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import (
    Contest,
    JudgeStatus,
    JudgeTask,
    JudgeWorker,
    OutboxMessage,
    OutboxStatus,
    Submission,
    WorkerStatus,
    utcnow,
)
from app.services.contests import recompute_contest_user_results
from app.services.queue_capacity import queue_capacity

# A heartbeat younger than this means the queue is actively being consumed;
# healthy workers must not have their queued tasks re-enqueued just because
# the backlog is large.
FRESH_WORKER_SECONDS = 120
HEALTHY_QUEUE_TIMEOUT_MULTIPLIER = 3


def _expire_and_retry(db, task: JudgeTask, settings, error: str) -> tuple[bool, bool]:
    """Mark an expired task and queue a retry attempt. Returns (recovered, failed)."""
    submission = db.get(Submission, task.submission_id)
    if submission is None:
        return False, False
    task.status = JudgeStatus.SE
    task.finished_at = utcnow()
    task.last_error = error
    if task.attempt < settings.judge_task_max_attempts:
        retry = JudgeTask(submission_id=submission.id, attempt=task.attempt + 1)
        db.add(retry)
        db.flush()
        db.add(OutboxMessage(task_id=retry.id))
        submission.status = JudgeStatus.PENDING
        return True, False
    submission.status = JudgeStatus.SE
    submission.diagnostic = "判题服务暂时异常，请稍后重试"
    submission.finished_at = utcnow()
    queue_capacity.release(submission.id)
    if submission.contest_id:
        contest = db.get(Contest, submission.contest_id)
        if contest:
            recompute_contest_user_results(db, contest, submission.user_id)
    return False, True


def _fresh_workers(db, now) -> int:
    return (
        db.scalar(
            select(func.count(JudgeWorker.id)).where(
                JudgeWorker.status == WorkerStatus.ONLINE,
                JudgeWorker.heartbeat_at > now - timedelta(seconds=FRESH_WORKER_SECONDS),
            )
        )
        or 0
    )


def sweep_expired_tasks(limit: int = 100) -> dict[str, int]:
    settings = get_settings()
    db = SessionLocal()
    retry_ids: list[str] = []
    recovered = 0
    failed = 0
    try:
        now = utcnow()
        fresh = _fresh_workers(db, now)
        effective_queue_timeout = settings.judge_task_queue_timeout_seconds * (
            HEALTHY_QUEUE_TIMEOUT_MULTIPLIER if fresh else 1
        )
        # Case A: dispatched but the worker never reported a start — the
        # message was lost in the broker queue.
        queue_deadline = now - timedelta(seconds=effective_queue_timeout)
        queued_tasks = db.scalars(
            select(JudgeTask)
            .join(OutboxMessage, OutboxMessage.task_id == JudgeTask.id)
            .where(
                JudgeTask.status == JudgeStatus.PENDING,
                OutboxMessage.status == OutboxStatus.DISPATCHED,
                OutboxMessage.dispatched_at < queue_deadline,
            )
            .order_by(OutboxMessage.dispatched_at)
            .limit(limit)
            .with_for_update()
        ).all()
        for task in queued_tasks:
            ok, bad = _expire_and_retry(db, task, settings, "Judge task lost in queue")
            recovered += ok
            failed += bad
            if ok:
                latest = db.scalar(
                    select(JudgeTask.id).where(
                        JudgeTask.submission_id == task.submission_id,
                        JudgeTask.attempt == task.attempt + 1,
                    )
                )
                if latest:
                    retry_ids.append(latest)

        # Case B: a worker started but its lease expired — the worker is lost
        # or hung. Remaining budget allows the queued sweep above to coexist.
        remaining = max(0, limit - len(queued_tasks))
        if remaining:
            judging_tasks = db.scalars(
                select(JudgeTask)
                .where(JudgeTask.status == JudgeStatus.JUDGING, JudgeTask.lease_expires_at < now)
                .order_by(JudgeTask.lease_expires_at)
                .limit(remaining)
                .with_for_update()
            ).all()
            for task in judging_tasks:
                ok, bad = _expire_and_retry(db, task, settings, "Judge lease expired")
                recovered += ok
                failed += bad
                if ok:
                    latest = db.scalar(
                        select(JudgeTask.id).where(
                            JudgeTask.submission_id == task.submission_id,
                            JudgeTask.attempt == task.attempt + 1,
                        )
                    )
                    if latest:
                        retry_ids.append(latest)
        db.commit()
    finally:
        db.close()
    from app.tasks.dispatcher import dispatch_outbox

    for task_id in retry_ids:
        dispatch_outbox(task_id)
    return {"recovered": recovered, "failed": failed}


if __name__ == "__main__":
    print(sweep_expired_tasks())
