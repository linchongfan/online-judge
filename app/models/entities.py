import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class StrEnum(enum.StrEnum):
    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Difficulty(StrEnum):
    EASY = "简单"
    MEDIUM = "中等"
    HARD = "困难"


class ProblemStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Language(StrEnum):
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    PYTHON = "python"


class JudgeStatus(StrEnum):
    PENDING = "PENDING"
    JUDGING = "JUDGING"
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    MLE = "MLE"
    RE = "RE"
    CE = "CE"
    SE = "SE"


TERMINAL_JUDGE_STATUSES = {
    JudgeStatus.AC,
    JudgeStatus.WA,
    JudgeStatus.TLE,
    JudgeStatus.MLE,
    JudgeStatus.RE,
    JudgeStatus.CE,
    JudgeStatus.SE,
}
PENALTY_STATUSES = {JudgeStatus.WA, JudgeStatus.TLE, JudgeStatus.MLE, JudgeStatus.RE}


class TestDataStatus(StrEnum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"


class ContestPublication(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RegistrationStatus(StrEnum):
    REGISTERED = "registered"
    CANCELLED = "cancelled"


class StudyPlanStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WorkerStatus(StrEnum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    school: Mapped[str] = mapped_column(String(100), default="")
    bio: Mapped[str] = mapped_column(String(500), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False), default=UserRole.USER)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, native_enum=False), default=UserStatus.ACTIVE)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def joined_at(self) -> datetime:
        return self.created_at


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship()


class Problem(Base, TimestampMixin):
    __tablename__ = "problem"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    difficulty: Mapped[Difficulty] = mapped_column(Enum(Difficulty, native_enum=False), index=True)
    description: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_description: Mapped[str] = mapped_column(Text)
    output_description: Mapped[str] = mapped_column(Text)
    constraints_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_limit_ms: Mapped[int] = mapped_column(default=1000)
    memory_limit_mb: Mapped[int] = mapped_column(default=256)
    status: Mapped[ProblemStatus] = mapped_column(
        Enum(ProblemStatus, native_enum=False), default=ProblemStatus.DRAFT, index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))

    tags: Mapped[list["Tag"]] = relationship(secondary="problem_tag", lazy="selectin", back_populates="problems")
    solution: Mapped["ProblemSolution | None"] = relationship(back_populates="problem", uselist=False)


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    problems: Mapped[list[Problem]] = relationship(secondary="problem_tag", back_populates="tags")


class ProblemTag(Base):
    __tablename__ = "problem_tag"

    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class ProblemSolution(Base, TimestampMixin):
    __tablename__ = "problem_solution"

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_complexity: Mapped[str] = mapped_column(String(100))
    space_complexity: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    problem: Mapped[Problem] = relationship(back_populates="solution")
    code_variants: Mapped[list["SolutionCode"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class SolutionCode(Base):
    __tablename__ = "solution_code"
    __table_args__ = (UniqueConstraint("solution_id", "language", name="uq_solution_language"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    solution_id: Mapped[int] = mapped_column(ForeignKey("problem_solution.id", ondelete="CASCADE"))
    language: Mapped[Language] = mapped_column(Enum(Language, native_enum=False))
    code: Mapped[str] = mapped_column(Text)


class TestDataVersion(Base):
    __tablename__ = "test_data_version"
    __table_args__ = (
        UniqueConstraint("problem_id", "version", name="uq_problem_data_version"),
        Index("ix_current_problem_data", "problem_id", "is_current"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[TestDataStatus] = mapped_column(Enum(TestDataStatus, native_enum=False), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    compressed_size: Mapped[int] = mapped_column(Integer)
    uncompressed_size: Mapped[int] = mapped_column(Integer, default=0)
    test_case_count: Mapped[int] = mapped_column(default=0)
    sample_count: Mapped[int] = mapped_column(default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cases: Mapped[list["TestCase"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class TestCase(Base):
    __tablename__ = "test_case"
    __table_args__ = (UniqueConstraint("version_id", "case_number", "is_sample", name="uq_test_case_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("test_data_version.id", ondelete="CASCADE"), index=True)
    case_number: Mapped[int] = mapped_column(Integer)
    input_key: Mapped[str] = mapped_column(String(255))
    output_key: Mapped[str] = mapped_column(String(255))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    input_size: Mapped[int] = mapped_column(Integer)
    output_size: Mapped[int] = mapped_column(Integer)


class Contest(Base, TimestampMixin):
    __tablename__ = "contest"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text)
    organizer: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ContestPublication] = mapped_column(
        Enum(ContestPublication, native_enum=False), default=ContestPublication.DRAFT, index=True
    )
    scoring: Mapped[str] = mapped_column(String(20), default="ACM")
    accent: Mapped[str] = mapped_column(String(20), default="blue")
    expected_participants: Mapped[int | None] = mapped_column(Integer)

    problems: Mapped[list["ContestProblem"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ContestProblem.position"
    )


class ContestProblem(Base):
    __tablename__ = "contest_problem"
    __table_args__ = (
        UniqueConstraint("contest_id", "problem_id", name="uq_contest_problem"),
        UniqueConstraint("contest_id", "label", name="uq_contest_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contest.id", ondelete="CASCADE"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="RESTRICT"), index=True)
    label: Mapped[str] = mapped_column(String(8))
    position: Mapped[int] = mapped_column(Integer)

    problem: Mapped[Problem] = relationship(lazy="joined")


class ContestRegistration(Base):
    __tablename__ = "contest_registration"
    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_contest_registration"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contest.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus, native_enum=False), default=RegistrationStatus.REGISTERED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StudyPlan(Base, TimestampMixin):
    __tablename__ = "study_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), index=True)
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    accent: Mapped[str] = mapped_column(String(20), default="blue")
    status: Mapped[StudyPlanStatus] = mapped_column(
        Enum(StudyPlanStatus, native_enum=False), default=StudyPlanStatus.DRAFT, index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)

    problems: Mapped[list["StudyPlanProblem"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="StudyPlanProblem.position"
    )


class StudyPlanProblem(Base):
    __tablename__ = "study_plan_problem"
    __table_args__ = (
        UniqueConstraint("plan_id", "problem_id", name="uq_study_plan_problem"),
        Index("ix_study_plan_problem_order", "plan_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plan.id", ondelete="CASCADE"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    problem: Mapped[Problem] = relationship(lazy="joined")


class StudyPlanEnrollment(Base):
    __tablename__ = "study_plan_enrollment"
    __table_args__ = (UniqueConstraint("plan_id", "user_id", name="uq_study_plan_enrollment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plan.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Submission(Base):
    __tablename__ = "submission"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_submission_idempotency"),
        Index("ix_submission_user_created", "user_id", "created_at"),
        Index("ix_submission_problem_status", "problem_id", "status"),
        Index("ix_submission_contest_user", "contest_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="RESTRICT"))
    contest_id: Mapped[int | None] = mapped_column(ForeignKey("contest.id", ondelete="RESTRICT"), nullable=True)
    language: Mapped[Language] = mapped_column(Enum(Language, native_enum=False))
    source_code: Mapped[str] = mapped_column(Text)
    status: Mapped[JudgeStatus] = mapped_column(Enum(JudgeStatus, native_enum=False), default=JudgeStatus.PENDING)
    runtime_ms: Mapped[int | None] = mapped_column(Integer)
    memory_kb: Mapped[int | None] = mapped_column(Integer)
    diagnostic: Mapped[str | None] = mapped_column(String(1000))
    test_data_version_id: Mapped[str] = mapped_column(ForeignKey("test_data_version.id", ondelete="RESTRICT"))
    is_sample_run: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sample_case_id: Mapped[int | None] = mapped_column(ForeignKey("test_case.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    problem: Mapped[Problem] = relationship(lazy="joined")
    contest: Mapped[Contest | None] = relationship(lazy="joined")


class JudgeTask(Base):
    __tablename__ = "judge_task"
    __table_args__ = (
        UniqueConstraint("submission_id", "attempt", name="uq_submission_attempt"),
        Index("ix_judge_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[JudgeStatus] = mapped_column(Enum(JudgeStatus, native_enum=False), default=JudgeStatus.PENDING)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    runtime_ms: Mapped[int | None] = mapped_column(Integer)
    memory_kb: Mapped[int | None] = mapped_column(Integer)
    diagnostic: Mapped[str | None] = mapped_column(String(1000))
    result_hash: Mapped[str | None] = mapped_column(String(64))


class JudgeWorker(Base, TimestampMixin):
    __tablename__ = "judge_worker"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    status: Mapped[WorkerStatus] = mapped_column(Enum(WorkerStatus, native_enum=False), default=WorkerStatus.OFFLINE)
    accepting: Mapped[bool] = mapped_column(Boolean, default=True)
    active_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    cpu: Mapped[float | None] = mapped_column()
    memory: Mapped[float | None] = mapped_column()
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def heartbeat(self) -> datetime | None:
        return self.heartbeat_at


class OutboxMessage(Base):
    __tablename__ = "outbox_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("judge_task.id", ondelete="CASCADE"), unique=True)
    status: Mapped[OutboxStatus] = mapped_column(Enum(OutboxStatus, native_enum=False), default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class ContestProblemResult(Base):
    __tablename__ = "contest_problem_result"
    __table_args__ = (UniqueConstraint("contest_id", "user_id", "problem_id", name="uq_contest_user_problem_result"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contest.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problem.id", ondelete="CASCADE"))
    solved: Mapped[bool] = mapped_column(Boolean, default=False)
    first_ac_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wrong_attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ContestResult(Base):
    __tablename__ = "contest_result"
    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_contest_user_result"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contest.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    solved_count: Mapped[int] = mapped_column(Integer, default=0)
    penalty_seconds: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_audit_created_target", "created_at", "target_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(30), default="success")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
