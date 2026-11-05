from datetime import datetime

from pydantic import Field

from app.models import JudgeStatus, Language
from app.schemas.common import ApiSchema


class SubmissionCreate(ApiSchema):
    problem_id: int = Field(ge=1)
    contest_id: int | None = Field(default=None, ge=1)
    language: Language
    source: str = Field(min_length=1, max_length=65_536)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class SampleRunCreate(ApiSchema):
    language: Language
    source: str = Field(min_length=1, max_length=65_536)
    sample_id: int | None = Field(default=None, ge=1)
    contest_id: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class SubmissionResponse(ApiSchema):
    id: str
    problem_id: int
    problem_title: str
    contest_id: int | None
    contest_title: str | None
    language: Language
    status: JudgeStatus
    runtime_ms: int | None
    memory_kb: int | None
    diagnostic: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    is_sample_run: bool = False


class SubmissionAccepted(ApiSchema):
    id: str
    status: JudgeStatus
    poll_after_ms: int = 800


class JudgeResultMessage(ApiSchema):
    task_id: str
    submission_id: str
    status: JudgeStatus
    runtime_ms: int | None = Field(default=None, ge=0)
    memory_kb: int | None = Field(default=None, ge=0)
    diagnostic: str | None = Field(default=None, max_length=1000)
    attempt: int = Field(ge=1)
    test_data_version_id: str
    nonce: str = Field(min_length=8, max_length=100)


class JudgeStartedMessage(ApiSchema):
    """Signed notification that a worker actually began executing a task."""

    event: str = Field(default="started", pattern=r"^started$")
    task_id: str
    submission_id: str
    attempt: int = Field(ge=1)
    test_data_version_id: str
    nonce: str = Field(min_length=8, max_length=100)
    worker_id: str = Field(min_length=1, max_length=100)
    lease_seconds: int = Field(default=120, ge=10)
