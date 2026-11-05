from hashlib import sha256

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import (
    Contest,
    JudgeStatus,
    JudgeTask,
    Language,
    OutboxMessage,
    Problem,
    Submission,
    TestCase,
    User,
)
from app.schemas.submission import SampleRunCreate, SubmissionCreate
from app.services.contests import ensure_contest_submission_allowed, get_contest
from app.services.problems import current_test_data, get_problem
from app.services.rate_limit import rate_limiter
from app.services.settings import get_setting


def serialize_submission(item: Submission) -> dict:
    return {
        "id": item.id,
        "problem_id": item.problem_id,
        "problem_title": item.problem.title,
        "contest_id": item.contest_id,
        "contest_title": item.contest.title if item.contest else None,
        "language": item.language,
        "status": item.status,
        "runtime_ms": item.runtime_ms,
        "memory_kb": item.memory_kb,
        "diagnostic": item.diagnostic,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "is_sample_run": item.is_sample_run,
    }


def _check_source(source: str) -> None:
    if len(source.encode("utf-8")) > get_settings().source_code_max_bytes:
        raise AppError(413, "SOURCE_TOO_LARGE", "源代码大小超过限制")
    if "\x00" in source:
        raise AppError(422, "INVALID_SOURCE", "源代码不能包含 NUL 字符")


def _existing_submission(db: Session, user_id: int, key: str) -> Submission | None:
    return db.scalar(select(Submission).where(Submission.user_id == user_id, Submission.idempotency_key == key))


def _assert_same_request(
    existing: Submission, problem_id: int, contest_id: int | None, language: Language, source: str, sample: bool
) -> None:
    if (
        existing.problem_id != problem_id
        or existing.contest_id != contest_id
        or existing.language != language
        or existing.is_sample_run != sample
        or sha256(existing.source_code.encode()).digest() != sha256(source.encode()).digest()
    ):
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "相同幂等键已用于不同的提交内容")


def _check_submission_capacity(db: Session, user: User) -> None:
    settings = get_settings()
    if not get_setting(db, "submissions_enabled"):
        raise AppError(503, "SUBMISSIONS_PAUSED", "判题提交暂时关闭，浏览和登录不受影响")
    total_queued = (
        db.scalar(
            select(func.count(Submission.id)).where(Submission.status.in_([JudgeStatus.PENDING, JudgeStatus.JUDGING]))
        )
        or 0
    )
    if total_queued >= int(get_setting(db, "global_queue_limit")):
        raise AppError(503, "GLOBAL_QUEUE_FULL", "判题队列已满，请稍后再试")
    if not rate_limiter.allow(
        f"submission:{user.id}", settings.submission_rate_limit, settings.submission_rate_window_seconds
    ):
        raise AppError(429, "SUBMISSION_RATE_LIMITED", "提交过于频繁，请稍后再试")
    queued = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.user_id == user.id, Submission.status.in_([JudgeStatus.PENDING, JudgeStatus.JUDGING])
            )
        )
        or 0
    )
    if queued >= settings.max_queued_submissions_per_user:
        raise AppError(429, "USER_QUEUE_FULL", "等待判题的提交过多，请稍后提交")


def _create_record(
    db: Session,
    user: User,
    problem: Problem,
    language: Language,
    source: str,
    key: str,
    contest: Contest | None = None,
    sample_case: TestCase | None = None,
    sample_run: bool = False,
) -> Submission:
    version = current_test_data(db, problem.id)
    if version is None:
        raise AppError(409, "TEST_DATA_UNAVAILABLE", "题目尚无可用测试数据")
    submission = Submission(
        user_id=user.id,
        problem_id=problem.id,
        contest_id=contest.id if contest else None,
        language=language,
        source_code=source,
        idempotency_key=key,
        test_data_version_id=version.id,
        is_sample_run=sample_run,
        sample_case_id=sample_case.id if sample_case else None,
    )
    db.add(submission)
    db.flush()
    task = JudgeTask(submission_id=submission.id)
    db.add(task)
    db.flush()
    db.add(OutboxMessage(task_id=task.id))
    db.commit()
    from app.tasks.dispatcher import dispatch_outbox

    dispatch_outbox(task.id)
    return submission


def create_submission(db: Session, data: SubmissionCreate, user: User) -> dict:
    existing = _existing_submission(db, user.id, data.idempotency_key)
    if existing:
        _assert_same_request(existing, data.problem_id, data.contest_id, data.language, data.source, False)
        return {"id": existing.id, "status": existing.status}
    _check_source(data.source)
    _check_submission_capacity(db, user)
    contest = get_contest(db, data.contest_id) if data.contest_id else None
    if contest:
        ensure_contest_submission_allowed(db, contest, data.problem_id, user)
        problem = get_problem(db, data.problem_id, user, include_unpublished=True)
    else:
        problem = get_problem(db, data.problem_id, user)
    submission = _create_record(db, user, problem, data.language, data.source, data.idempotency_key, contest)
    return {"id": submission.id, "status": submission.status}


def create_sample_run(db: Session, problem_id: int, data: SampleRunCreate, user: User) -> dict:
    existing = _existing_submission(db, user.id, data.idempotency_key)
    if existing:
        _assert_same_request(existing, problem_id, data.contest_id, data.language, data.source, True)
        return {"id": existing.id, "status": existing.status}
    _check_source(data.source)
    _check_submission_capacity(db, user)
    contest = get_contest(db, data.contest_id) if data.contest_id else None
    if contest:
        ensure_contest_submission_allowed(db, contest, problem_id, user)
        problem = get_problem(db, problem_id, user, include_unpublished=True)
    else:
        problem = get_problem(db, problem_id, user)
    version = current_test_data(db, problem_id)
    if version is None:
        raise AppError(409, "TEST_DATA_UNAVAILABLE", "题目尚无可用测试数据")
    if data.sample_id:
        sample = db.get(TestCase, data.sample_id)
        if sample is None or sample.version_id != version.id or not sample.is_sample:
            raise AppError(404, "SAMPLE_NOT_FOUND", "公开样例不存在")
    else:
        sample = None
        if not any(case.is_sample for case in version.cases):
            raise AppError(404, "SAMPLE_NOT_FOUND", "该题暂无公开样例")
    submission = _create_record(
        db,
        user,
        problem,
        data.language,
        data.source,
        data.idempotency_key,
        contest=contest,
        sample_case=sample,
        sample_run=True,
    )
    return {"id": submission.id, "status": submission.status}


def list_submissions(
    db: Session,
    user: User,
    page: int,
    page_size: int,
    keyword: str | None,
    status: JudgeStatus | None,
    language: Language | None,
    problem_id: int | None = None,
) -> tuple[list[Submission], int]:
    filters = [Submission.user_id == user.id, Submission.is_sample_run.is_(False)]
    if problem_id is not None:
        filters.append(Submission.problem_id == problem_id)
    if keyword:
        filters.append(
            or_(Submission.id.like(f"%{keyword}%"), Submission.problem.has(Problem.title.like(f"%{keyword}%")))
        )
    if status:
        filters.append(Submission.status == status)
    if language:
        filters.append(Submission.language == language)
    total = db.scalar(select(func.count(Submission.id)).where(*filters)) or 0
    items = db.scalars(
        select(Submission)
        .where(*filters)
        .order_by(Submission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def get_submission(db: Session, submission_id: str, user: User) -> Submission:
    item = db.get(Submission, submission_id)
    if item is None or (item.user_id != user.id and user.role.value != "admin"):
        raise AppError(404, "SUBMISSION_NOT_FOUND", "提交记录不存在")
    return item
