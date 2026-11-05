import hashlib
import io
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, Db
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import request_ip, utc_datetime
from app.models import (
    AdminAuditLog,
    Contest,
    ContestPublication,
    ContestRegistration,
    JudgeStatus,
    JudgeTask,
    JudgeWorker,
    OutboxMessage,
    Problem,
    ProblemStatus,
    RegistrationStatus,
    Submission,
    TestCase,
    TestDataStatus,
    TestDataVersion,
    User,
    UserRole,
    UserStatus,
    WorkerStatus,
    utcnow,
)
from app.schemas.admin import (
    AbnormalJudgeTaskResponse,
    AdminUserResponse,
    AdminUserUpdate,
    AuditLogResponse,
    BatchJudgeTaskRejudge,
    DashboardResponse,
    JudgeTaskRejudge,
    WorkerResponse,
    WorkerUpdate,
)
from app.schemas.common import MessageResponse, Page, make_page
from app.schemas.contest import ContestResponse, ContestWriteRequest
from app.schemas.problem import AdminProblemResponse, ProblemWriteRequest
from app.schemas.test_data import TestDataLimits
from app.services.audit import record_audit
from app.services.auth import revoke_user_sessions, send_reset_code
from app.services.contests import (
    get_contest,
    publish_contest,
    recompute_contest_results,
    serialize_contest,
    upsert_contest,
)
from app.services.problems import (
    change_problem_status,
    current_test_data,
    get_problem,
    problem_stats,
    serialize_detail,
    upsert_problem,
)
from app.services.test_data import TestDataService, TestDataValidationError

router = APIRouter()


def admin_problem_dict(db: Session, problem: Problem) -> dict:
    version = current_test_data(db, problem.id)
    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [tag.name for tag in problem.tags],
        "status": problem.status,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "test_data_version": version.id if version else None,
        "test_case_count": version.test_case_count if version else 0,
        "test_data_size": version.uncompressed_size if version else 0,
        "solution_language_count": len(problem.solution.code_variants) if problem.solution else 0,
        **problem_stats(db, problem.id, None),
        "updated_at": problem.updated_at,
    }


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: Db, admin: AdminUser):
    submission_count = db.scalar(select(func.count(Submission.id)).where(Submission.is_sample_run.is_(False))) or 0
    accepted_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.is_sample_run.is_(False), Submission.status == JudgeStatus.AC
            )
        )
        or 0
    )
    judged_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.is_sample_run.is_(False),
                Submission.status.not_in([JudgeStatus.PENDING, JudgeStatus.JUDGING, JudgeStatus.SE]),
            )
        )
        or 0
    )
    return {
        "user_count": db.scalar(select(func.count(User.id))) or 0,
        "problem_count": db.scalar(select(func.count(Problem.id))) or 0,
        "submission_count": submission_count,
        "contest_count": db.scalar(select(func.count(Contest.id))) or 0,
        "pending_count": db.scalar(
            select(func.count(Submission.id)).where(Submission.status.in_([JudgeStatus.PENDING, JudgeStatus.JUDGING]))
        )
        or 0,
        "accepted_count": accepted_count,
        "acceptance": round(accepted_count / judged_count * 100, 1) if judged_count else 0.0,
        "active_worker_count": db.scalar(
            select(func.count(JudgeWorker.id)).where(JudgeWorker.status != WorkerStatus.OFFLINE)
        )
        or 0,
        "abnormal_task_count": db.scalar(select(func.count(JudgeTask.id)).where(JudgeTask.status == JudgeStatus.SE))
        or 0,
    }


@router.get("/dashboard/trends")
def dashboard_trends(db: Db, admin: AdminUser, days: int = Query(7, ge=1, le=30)):
    start = utcnow() - timedelta(days=days - 1)
    rows = db.execute(
        select(func.date(Submission.created_at), func.count(Submission.id))
        .where(Submission.created_at >= start, Submission.is_sample_run.is_(False))
        .group_by(func.date(Submission.created_at))
        .order_by(func.date(Submission.created_at))
    ).all()
    return [{"date": day, "submissions": count} for day, count in rows]


@router.get("/dashboard/status-distribution")
def status_distribution(db: Db, admin: AdminUser):
    rows = db.execute(
        select(Submission.status, func.count(Submission.id))
        .where(Submission.is_sample_run.is_(False))
        .group_by(Submission.status)
    ).all()
    return [{"status": status_value, "count": count} for status_value, count in rows]


@router.get("/users", response_model=Page[AdminUserResponse])
def users(
    db: Db,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    role: UserRole | None = None,
    user_status: UserStatus | None = Query(None, alias="status"),
):
    filters: list[Any] = []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(User.username.like(pattern) | User.nickname.like(pattern) | User.email.like(pattern))
    if role:
        filters.append(User.role == role)
    if user_status:
        filters.append(User.status == user_status)
    total = db.scalar(select(func.count(User.id)).where(*filters)) or 0
    items = db.scalars(
        select(User).where(*filters).order_by(User.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    result = []
    for item in items:
        solved = (
            db.scalar(
                select(func.count(func.distinct(Submission.problem_id))).where(
                    Submission.user_id == item.id,
                    Submission.status == JudgeStatus.AC,
                    Submission.contest_id.is_(None),
                    Submission.is_sample_run.is_(False),
                )
            )
            or 0
        )
        result.append(
            {
                "id": item.id,
                "username": item.username,
                "nickname": item.nickname,
                "email": item.email,
                "role": item.role,
                "status": item.status,
                "solved": solved,
                "last_active": item.last_active_at,
            }
        )
    return make_page(result, total, page, page_size)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(user_id: int, data: AdminUserUpdate, request: Request, db: Db, admin: AdminUser):
    target = db.get(User, user_id)
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if target.id == admin.id and (data.role is not None or data.status is not None):
        raise AppError(409, "SELF_MODIFICATION_DENIED", "不能修改自己的角色或账号状态")
    removes_admin = target.role == UserRole.ADMIN and (
        (data.role is not None and data.role != UserRole.ADMIN)
        or (data.status is not None and data.status != UserStatus.ACTIVE)
    )
    if removes_admin:
        active_admins = (
            db.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE))
            or 0
        )
        if active_admins <= 1:
            raise AppError(409, "LAST_ADMIN_REQUIRED", "必须保留至少一名可用管理员")
    changes = data.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(target, key, value)
    if changes:
        revoke_user_sessions(db, target.id)
    record_audit(db, admin.id, "user.update", "user", target.id, details=changes, ip_address=request_ip(request))
    db.commit()
    solved = (
        db.scalar(
            select(func.count(func.distinct(Submission.problem_id))).where(
                Submission.user_id == target.id,
                Submission.status == JudgeStatus.AC,
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    return {
        **{key: getattr(target, key) for key in ("id", "username", "nickname", "email", "role", "status")},
        "solved": solved,
        "last_active": target.last_active_at,
    }


@router.post("/users/{user_id}/password-reset", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def admin_password_reset(user_id: int, request: Request, db: Db, admin: AdminUser):
    target = db.get(User, user_id)
    if target is None:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    send_reset_code(target.email, request_ip(request))
    record_audit(db, admin.id, "user.password_reset", "user", target.id, ip_address=request_ip(request))
    db.commit()
    return {"message": "密码重置验证码已发送"}


@router.get("/problems", response_model=Page[AdminProblemResponse])
def admin_problems(
    db: Db,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    problem_status: ProblemStatus | None = Query(None, alias="status"),
):
    filters: list[Any] = []
    if keyword:
        filters.append(Problem.title.like(f"%{keyword}%"))
    if problem_status:
        filters.append(Problem.status == problem_status)
    total = db.scalar(select(func.count(Problem.id)).where(*filters)) or 0
    items = db.scalars(
        select(Problem).where(*filters).order_by(Problem.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return make_page([admin_problem_dict(db, item) for item in items], total, page, page_size)


@router.post("/problems", response_model=AdminProblemResponse, status_code=status.HTTP_201_CREATED)
def create_problem(data: ProblemWriteRequest, request: Request, db: Db, admin: AdminUser):
    problem = upsert_problem(db, data, admin.id)
    record_audit(db, admin.id, "problem.create", "problem", problem.id, ip_address=request_ip(request))
    db.commit()
    return admin_problem_dict(db, problem)


@router.get("/problems/{problem_id}")
def admin_problem_detail(problem_id: int, db: Db, admin: AdminUser):
    problem = get_problem(db, problem_id, admin, include_unpublished=True)
    return {**serialize_detail(db, problem, admin.id), **admin_problem_dict(db, problem), "solution": problem.solution}


@router.put("/problems/{problem_id}", response_model=AdminProblemResponse)
def edit_problem(problem_id: int, data: ProblemWriteRequest, request: Request, db: Db, admin: AdminUser):
    problem = get_problem(db, problem_id, admin, include_unpublished=True)
    upsert_problem(db, data, admin.id, problem)
    record_audit(db, admin.id, "problem.update", "problem", problem.id, ip_address=request_ip(request))
    db.commit()
    return admin_problem_dict(db, problem)


def _change_problem_status(problem_id: int, action: str, request: Request, db: Session, admin: User):
    mapping = {"publish": ProblemStatus.PUBLISHED, "unpublish": ProblemStatus.DRAFT, "archive": ProblemStatus.ARCHIVED}
    problem = get_problem(db, problem_id, admin, include_unpublished=True)
    change_problem_status(db, problem, mapping[action])
    record_audit(db, admin.id, f"problem.{action}", "problem", problem.id, ip_address=request_ip(request))
    db.commit()
    return admin_problem_dict(db, problem)


@router.post("/problems/{problem_id}/publish", response_model=AdminProblemResponse)
def publish_problem(problem_id: int, request: Request, db: Db, admin: AdminUser):
    return _change_problem_status(problem_id, "publish", request, db, admin)


@router.post("/problems/{problem_id}/unpublish", response_model=AdminProblemResponse)
def unpublish_problem(problem_id: int, request: Request, db: Db, admin: AdminUser):
    return _change_problem_status(problem_id, "unpublish", request, db, admin)


@router.post("/problems/{problem_id}/archive", response_model=AdminProblemResponse)
def archive_problem(problem_id: int, request: Request, db: Db, admin: AdminUser):
    return _change_problem_status(problem_id, "archive", request, db, admin)


@router.get("/test-data/template")
def test_data_template(admin: AdminUser):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample/1.in", "1 2\n")
        archive.writestr("sample/1.out", "3\n")
        archive.writestr("hidden/1.in", "10 20\n")
        archive.writestr("hidden/1.out", "30\n")
    content.seek(0)
    return StreamingResponse(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=test-data-template.zip"},
    )


@router.get("/problems/{problem_id}/test-data")
def test_data_versions(problem_id: int, db: Db, admin: AdminUser):
    get_problem(db, problem_id, admin, include_unpublished=True)
    versions = db.scalars(
        select(TestDataVersion).where(TestDataVersion.problem_id == problem_id).order_by(TestDataVersion.version.desc())
    ).all()
    return [
        {
            "id": item.id,
            "version": item.version,
            "status": item.status,
            "isCurrent": item.is_current,
            "filename": item.original_filename,
            "compressedSize": item.compressed_size,
            "uncompressedSize": item.uncompressed_size,
            "testCaseCount": item.test_case_count,
            "sampleCount": item.sample_count,
            "validationErrors": item.validation_errors,
            "createdAt": item.created_at,
        }
        for item in versions
    ]


@router.post("/problems/{problem_id}/test-data", status_code=status.HTTP_201_CREATED)
async def upload_test_data(problem_id: int, upload: UploadFile, request: Request, db: Db, admin: AdminUser):
    get_problem(db, problem_id, admin, include_unpublished=True)
    settings = get_settings()
    content = await upload.read(settings.test_data_max_compressed_bytes + 1)
    if len(content) > settings.test_data_max_compressed_bytes:
        raise AppError(413, "TEST_DATA_TOO_LARGE", "测试数据压缩包超过大小限制")
    latest = db.scalar(select(func.max(TestDataVersion.version)).where(TestDataVersion.problem_id == problem_id)) or 0
    filename = Path(upload.filename or "test-data.zip").name[:255]
    version = TestDataVersion(
        problem_id=problem_id,
        version=latest + 1,
        status=TestDataStatus.VALIDATING,
        storage_path="",
        original_filename=filename,
        compressed_size=len(content),
        created_by=admin.id,
    )
    db.add(version)
    db.flush()
    destination = settings.storage_root.resolve() / "test-data" / f"problem-{problem_id}" / version.id
    service = TestDataService(
        TestDataLimits(
            max_test_cases=settings.test_data_max_files // 2,
            max_total_bytes=settings.test_data_max_uncompressed_bytes,
            max_archive_bytes=settings.test_data_max_compressed_bytes,
        )
    )
    try:
        result = service.store(content, destination)
    except TestDataValidationError as exc:
        version.status = TestDataStatus.INVALID
        version.validation_errors = [item.model_dump() for item in exc.errors]
        db.commit()
        raise AppError(
            422,
            "TEST_DATA_VALIDATION_FAILED",
            "测试数据校验失败",
            {"versionId": version.id, "errors": version.validation_errors},
        ) from exc
    version.status = TestDataStatus.VALID
    version.storage_path = str(destination)
    version.uncompressed_size = sum(item.size for item in result.files)
    version.test_case_count = result.test_count
    version.sample_count = sum(case.category != "hidden" for case in result.cases)
    version.content_hash = hashlib.sha256("".join(item.sha256 for item in result.files).encode()).hexdigest()
    for case in result.cases:
        db.add(
            TestCase(
                version_id=version.id,
                case_number=case.number,
                input_key=case.input.stored_path,
                output_key=case.output.stored_path,
                is_sample=case.category != "hidden",
                input_size=case.input.size,
                output_size=case.output.size,
            )
        )
    db.execute(
        update(TestDataVersion)
        .where(TestDataVersion.problem_id == problem_id, TestDataVersion.id != version.id)
        .values(is_current=False)
    )
    version.is_current = True
    record_audit(
        db,
        admin.id,
        "test_data.upload",
        "problem",
        problem_id,
        details={"versionId": version.id, "sha256": version.content_hash},
        ip_address=request_ip(request),
    )
    db.commit()
    return {
        "id": version.id,
        "status": version.status,
        "testCaseCount": version.test_case_count,
        "sampleCount": version.sample_count,
    }


@router.get("/contests", response_model=Page[ContestResponse])
def admin_contests(
    db: Db,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    contest_status: str | None = Query(None, alias="status", pattern="^(ongoing|upcoming|ended)$"),
    publication_status: ContestPublication | None = Query(None, alias="publicationStatus"),
):
    filters: list[Any] = []
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(Contest.title.like(pattern) | Contest.subtitle.like(pattern) | Contest.organizer.like(pattern))
    if publication_status:
        filters.append(Contest.status == publication_status)
    now = utcnow()
    if contest_status == "upcoming":
        filters.append(Contest.start_time > now)
    elif contest_status == "ongoing":
        filters.append((Contest.start_time <= now) & (Contest.end_time > now))
    elif contest_status == "ended":
        filters.append(Contest.end_time <= now)
    total = db.scalar(select(func.count(Contest.id)).where(*filters)) or 0
    items = db.scalars(
        select(Contest)
        .where(*filters)
        .order_by(Contest.start_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return make_page(
        [serialize_contest(db, item, admin, include_problems=True) for item in items], total, page, page_size
    )


@router.post("/contests", response_model=ContestResponse, status_code=status.HTTP_201_CREATED)
def create_contest(data: ContestWriteRequest, request: Request, db: Db, admin: AdminUser):
    contest = upsert_contest(db, data)
    record_audit(db, admin.id, "contest.create", "contest", contest.id, ip_address=request_ip(request))
    db.commit()
    return serialize_contest(db, contest, admin, include_problems=True)


@router.put("/contests/{contest_id}", response_model=ContestResponse)
def edit_contest(contest_id: int, data: ContestWriteRequest, request: Request, db: Db, admin: AdminUser):
    contest = get_contest(db, contest_id, include_unpublished=True)
    upsert_contest(db, data, contest)
    record_audit(db, admin.id, "contest.update", "contest", contest.id, ip_address=request_ip(request))
    db.commit()
    return serialize_contest(db, contest, admin, include_problems=True)


def _contest_action(contest_id: int, action: str, request: Request, db: Session, admin: User):
    contest = get_contest(db, contest_id, include_unpublished=True)
    if action == "publish":
        publish_contest(db, contest)
    else:
        contest.status = ContestPublication.CANCELLED if action == "cancel" else ContestPublication.ARCHIVED
    record_audit(db, admin.id, f"contest.{action}", "contest", contest.id, ip_address=request_ip(request))
    db.commit()
    return serialize_contest(db, contest, admin, include_problems=True)


@router.post("/contests/{contest_id}/publish", response_model=ContestResponse)
def publish_contest_route(contest_id: int, request: Request, db: Db, admin: AdminUser):
    return _contest_action(contest_id, "publish", request, db, admin)


@router.post("/contests/{contest_id}/cancel", response_model=ContestResponse)
def cancel_contest_route(contest_id: int, request: Request, db: Db, admin: AdminUser):
    return _contest_action(contest_id, "cancel", request, db, admin)


@router.post("/contests/{contest_id}/archive", response_model=ContestResponse)
def archive_contest_route(contest_id: int, request: Request, db: Db, admin: AdminUser):
    return _contest_action(contest_id, "archive", request, db, admin)


@router.get("/contests/{contest_id}/participants")
def contest_participants(contest_id: int, db: Db, admin: AdminUser):
    get_contest(db, contest_id, include_unpublished=True)
    rows = db.execute(
        select(User, ContestRegistration)
        .join(ContestRegistration, ContestRegistration.user_id == User.id)
        .where(
            ContestRegistration.contest_id == contest_id, ContestRegistration.status == RegistrationStatus.REGISTERED
        )
    ).all()
    return [
        {"id": user.id, "username": user.username, "nickname": user.nickname, "registeredAt": registration.created_at}
        for user, registration in rows
    ]


@router.post("/contests/{contest_id}/recompute", response_model=MessageResponse)
def recompute_contest(contest_id: int, request: Request, db: Db, admin: AdminUser):
    contest = get_contest(db, contest_id, include_unpublished=True)
    recompute_contest_results(db, contest)
    record_audit(db, admin.id, "contest.recompute", "contest", contest.id, ip_address=request_ip(request))
    db.commit()
    return {"message": "竞赛成绩已从提交明细重算"}


WORKER_HEARTBEAT_TIMEOUT_SECONDS = 60


@router.get("/judge/workers", response_model=list[WorkerResponse])
def workers(db: Db, admin: AdminUser):
    rows = db.scalars(select(JudgeWorker).order_by(JudgeWorker.id)).all()
    now = utcnow()
    result = []
    for worker in rows:
        stale = (
            worker.heartbeat_at is None
            or (now - utc_datetime(worker.heartbeat_at)).total_seconds() > WORKER_HEARTBEAT_TIMEOUT_SECONDS
        )
        if stale:
            # Reported, not persisted: the next real heartbeat restores state.
            worker.status = WorkerStatus.OFFLINE
            worker.active_tasks = 0
        result.append(worker)
    return result


@router.patch("/judge/workers/{worker_id}", response_model=WorkerResponse)
def update_worker(worker_id: str, data: WorkerUpdate, request: Request, db: Db, admin: AdminUser):
    worker = db.get(JudgeWorker, worker_id)
    if worker is None:
        raise AppError(404, "WORKER_NOT_FOUND", "判题 Worker 不存在")
    worker.accepting = data.accepting
    record_audit(
        db,
        admin.id,
        "worker.accepting",
        "worker",
        worker.id,
        details={"accepting": data.accepting},
        ip_address=request_ip(request),
    )
    db.commit()
    return worker


def _rejudge(db: Session, task: JudgeTask, admin: User, reason: str, request: Request) -> str:
    if task.status in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
        raise AppError(409, "TASK_STILL_ACTIVE", "进行中任务不能重判")
    submission = db.get(Submission, task.submission_id)
    if submission is None:
        raise AppError(404, "SUBMISSION_NOT_FOUND", "提交不存在")
    latest_task = db.scalar(
        select(JudgeTask)
        .where(JudgeTask.submission_id == submission.id)
        .order_by(JudgeTask.attempt.desc())
        .limit(1)
    )
    if latest_task is not None and latest_task.status in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
        raise AppError(409, "SUBMISSION_STILL_ACTIVE", "该提交已有正在判题的任务，不能重复重判")
    latest = latest_task.attempt if latest_task is not None else task.attempt
    new_task = JudgeTask(submission_id=submission.id, attempt=latest + 1)
    db.add(new_task)
    db.flush()
    db.add(OutboxMessage(task_id=new_task.id))
    submission.status = JudgeStatus.PENDING
    submission.runtime_ms = None
    submission.memory_kb = None
    submission.diagnostic = None
    submission.finished_at = None
    record_audit(
        db,
        admin.id,
        "judge.rejudge",
        "submission",
        submission.id,
        details={"reason": reason, "previousTaskId": task.id, "newTaskId": new_task.id},
        ip_address=request_ip(request),
    )
    db.commit()
    from app.tasks.dispatcher import dispatch_outbox

    dispatch_outbox(new_task.id)
    return new_task.id


@router.post("/judge/tasks/{task_id}/rejudge")
def rejudge_task(task_id: str, data: JudgeTaskRejudge, request: Request, db: Db, admin: AdminUser):
    task = db.get(JudgeTask, task_id)
    if task is None:
        raise AppError(404, "TASK_NOT_FOUND", "判题任务不存在")
    return {"taskId": _rejudge(db, task, admin, data.reason, request)}


@router.post("/judge/tasks/batch-rejudge")
def batch_rejudge(data: BatchJudgeTaskRejudge, request: Request, db: Db, admin: AdminUser):
    # Deduplicate by submission: multiple historical tasks of one submission
    # must not create parallel attempts.
    candidates: dict[str, JudgeTask] = {}
    for task_id in dict.fromkeys(data.task_ids):
        task = db.get(JudgeTask, task_id)
        if task is None or task.status in (JudgeStatus.PENDING, JudgeStatus.JUDGING):
            continue
        current = candidates.get(task.submission_id)
        if current is None or task.attempt > current.attempt:
            candidates[task.submission_id] = task
    task_ids = []
    for task in candidates.values():
        try:
            task_ids.append(_rejudge(db, task, admin, data.reason, request))
        except AppError as exc:
            if exc.code != "SUBMISSION_STILL_ACTIVE":
                raise
    return {"taskIds": task_ids, "count": len(task_ids)}


@router.get("/judge/abnormal", response_model=list[AbnormalJudgeTaskResponse])
def abnormal_tasks(db: Db, admin: AdminUser):
    rows = db.execute(
        select(JudgeTask, Submission, Problem, User)
        .join(Submission, Submission.id == JudgeTask.submission_id)
        .join(Problem, Problem.id == Submission.problem_id)
        .join(User, User.id == Submission.user_id)
        .where(JudgeTask.status == JudgeStatus.SE)
        .order_by(JudgeTask.finished_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "task_id": task.id,
            "submission_id": task.submission_id,
            "problem_id": problem.id,
            "problem_title": problem.title,
            "username": user.username,
            "language": submission.language,
            "worker_id": task.lease_owner,
            "judge_status": task.status,
            "created_at": submission.created_at,
            "finished_at": task.finished_at,
            "reason": task.last_error or task.diagnostic,
            "attempt": task.attempt,
        }
        for task, submission, problem, user in rows
    ]


@router.get("/judge/settings")
def judge_settings(db: Db, admin: AdminUser):
    from app.services.settings import get_setting

    return {
        "submissionsEnabled": get_setting(db, "submissions_enabled"),
        "globalQueueLimit": get_setting(db, "global_queue_limit"),
    }


@router.put("/judge/settings")
def update_judge_settings(data: dict, request: Request, db: Db, admin: AdminUser):
    from app.services.settings import set_setting

    enabled = data.get("submissionsEnabled")
    queue_limit = data.get("globalQueueLimit")
    if not isinstance(enabled, bool) or not isinstance(queue_limit, int) or not 10 <= queue_limit <= 100_000:
        raise AppError(422, "INVALID_JUDGE_SETTINGS", "判题设置无效")
    set_setting(db, "submissions_enabled", enabled)
    set_setting(db, "global_queue_limit", queue_limit)
    record_audit(
        db,
        admin.id,
        "judge.settings",
        "system",
        "judge",
        details={"submissionsEnabled": enabled, "globalQueueLimit": queue_limit},
        ip_address=request_ip(request),
    )
    db.commit()
    return {"submissionsEnabled": enabled, "globalQueueLimit": queue_limit}


@router.get("/audit", response_model=Page[AuditLogResponse])
def audit_logs(db: Db, admin: AdminUser, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    total = db.scalar(select(func.count(AdminAuditLog.id))) or 0
    items = db.scalars(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return make_page(list(items), total, page, page_size)
