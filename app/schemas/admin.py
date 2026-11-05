from datetime import datetime

from pydantic import EmailStr, Field

from app.models import JudgeStatus, Language, UserRole, UserStatus, WorkerStatus
from app.schemas.common import ApiSchema


class AdminUserResponse(ApiSchema):
    id: int
    username: str
    nickname: str
    email: EmailStr
    role: UserRole
    status: UserStatus
    solved: int = 0
    last_active: datetime | None


class AdminUserUpdate(ApiSchema):
    role: UserRole | None = None
    status: UserStatus | None = None


class AdminPasswordReset(ApiSchema):
    send_email: bool = True


class WorkerUpdate(ApiSchema):
    accepting: bool


class JudgeTaskRejudge(ApiSchema):
    reason: str = Field(min_length=3, max_length=300)


class BatchJudgeTaskRejudge(JudgeTaskRejudge):
    task_ids: list[str] = Field(min_length=1, max_length=100)


class DashboardResponse(ApiSchema):
    user_count: int
    problem_count: int
    submission_count: int
    contest_count: int
    pending_count: int
    accepted_count: int
    acceptance: float
    active_worker_count: int
    abnormal_task_count: int


class AbnormalJudgeTaskResponse(ApiSchema):
    task_id: str
    submission_id: str
    problem_id: int
    problem_title: str
    username: str
    language: Language
    worker_id: str | None
    judge_status: JudgeStatus
    created_at: datetime
    finished_at: datetime | None
    reason: str | None
    attempt: int


class AuditLogResponse(ApiSchema):
    id: int
    actor_id: int | None
    action: str
    target_type: str
    target_id: str
    result: str
    details: dict
    ip_address: str | None
    created_at: datetime


class WorkerResponse(ApiSchema):
    id: str
    host: str
    status: WorkerStatus
    accepting: bool
    active_tasks: int
    completed: int
    cpu: float | None
    memory: float | None
    heartbeat: datetime | None
