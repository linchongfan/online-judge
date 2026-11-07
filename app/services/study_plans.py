from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    JudgeStatus,
    Problem,
    ProblemStatus,
    StudyPlan,
    StudyPlanEnrollment,
    StudyPlanProblem,
    StudyPlanStatus,
    Submission,
    User,
)
from app.schemas.study_plan import StudyPlanWriteRequest


def get_study_plan(db: Session, plan_id: int, include_unpublished: bool = False) -> StudyPlan:
    plan = db.get(StudyPlan, plan_id)
    if plan is None or (not include_unpublished and plan.status != StudyPlanStatus.PUBLISHED):
        raise AppError(404, "STUDY_PLAN_NOT_FOUND", "学习计划不存在或尚未发布")
    return plan


def enrollment_for(db: Session, plan_id: int, user_id: int | None) -> StudyPlanEnrollment | None:
    if user_id is None:
        return None
    return db.scalar(
        select(StudyPlanEnrollment).where(
            StudyPlanEnrollment.plan_id == plan_id, StudyPlanEnrollment.user_id == user_id
        )
    )


def visible_plan_problems(plan: StudyPlan) -> list[StudyPlanProblem]:
    return [entry for entry in plan.problems if entry.problem.status == ProblemStatus.PUBLISHED]


def _progress_sets(
    db: Session, user_id: int, problem_ids: Iterable[int]
) -> tuple[set[int], set[int]]:
    """Return solved and attempted problem ids for one user in a single query.

    Mirrors the problem-list progress rule: sample runs are ignored and any
    accepted non-sample submission counts, including contest submissions.
    """
    ids = list(dict.fromkeys(problem_ids))
    if not ids:
        return set(), set()
    rows = db.execute(
        select(Submission.problem_id, Submission.status)
        .where(
            Submission.user_id == user_id,
            Submission.problem_id.in_(ids),
            Submission.is_sample_run.is_(False),
        )
        .distinct()
    ).all()
    solved: set[int] = set()
    attempted: set[int] = set()
    for problem_id, status in rows:
        attempted.add(problem_id)
        if status == JudgeStatus.AC:
            solved.add(problem_id)
    return solved, attempted


def _progress_label(problem_id: int, solved: set[int], attempted: set[int]) -> str:
    if problem_id in solved:
        return "solved"
    if problem_id in attempted:
        return "attempted"
    return "untouched"


def _summary_values(plan: StudyPlan, visible_ids: list[int], solved: set[int], enrolled: bool) -> dict:
    total = len(visible_ids)
    solved_count = sum(1 for problem_id in visible_ids if problem_id in solved)
    return {
        "id": plan.id,
        "title": plan.title,
        "subtitle": plan.subtitle,
        "accent": plan.accent,
        "problem_count": total,
        "solved_count": solved_count,
        "enrolled": enrolled,
        "completed": total > 0 and solved_count >= total,
    }


def list_published_study_plans(db: Session, user: User | None) -> list[dict]:
    plans = db.scalars(
        select(StudyPlan).where(StudyPlan.status == StudyPlanStatus.PUBLISHED).order_by(StudyPlan.id)
    ).all()
    if not plans:
        return []

    visible_by_plan = {plan.id: [entry.problem_id for entry in visible_plan_problems(plan)] for plan in plans}
    all_problem_ids = {problem_id for ids in visible_by_plan.values() for problem_id in ids}
    solved, _ = _progress_sets(db, user.id, all_problem_ids) if user else (set(), set())
    enrolled_ids: set[int] = set()
    if user is not None:
        enrolled_ids = set(
            db.scalars(
                select(StudyPlanEnrollment.plan_id).where(
                    StudyPlanEnrollment.user_id == user.id,
                    StudyPlanEnrollment.plan_id.in_([plan.id for plan in plans]),
                )
            ).all()
        )
    return [
        _summary_values(plan, visible_by_plan[plan.id], solved, plan.id in enrolled_ids) for plan in plans
    ]


def serialize_study_plan(db: Session, plan: StudyPlan, user: User | None, include_problems: bool = False) -> dict:
    visible = visible_plan_problems(plan)
    problem_ids = [entry.problem_id for entry in visible]
    solved, attempted = _progress_sets(db, user.id, problem_ids) if user else (set(), set())
    enrolled = (enrollment_for(db, plan.id, user.id) is not None) if user else False
    data = _summary_values(plan, problem_ids, solved, enrolled)
    if not include_problems:
        return data
    data["description"] = plan.description
    data["problems"] = [
        {
            "problem_id": entry.problem_id,
            "title": entry.problem.title,
            "difficulty": entry.problem.difficulty,
            "tags": [tag.name for tag in entry.problem.tags],
            "position": entry.position,
            "group_name": entry.group_name,
            "progress": _progress_label(entry.problem_id, solved, attempted),
        }
        for entry in visible
    ]
    return data


def serialize_admin_detail(plan: StudyPlan) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "subtitle": plan.subtitle,
        "description": plan.description,
        "accent": plan.accent,
        "status": plan.status,
        "problems": [
            {
                "problem_id": entry.problem_id,
                "title": entry.problem.title,
                "difficulty": entry.problem.difficulty,
                "problem_status": entry.problem.status,
                "position": entry.position,
                "group_name": entry.group_name,
            }
            for entry in plan.problems
        ],
    }


def list_admin_study_plans(
    db: Session,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: StudyPlanStatus | None = None,
) -> tuple[list[dict], int]:
    filters: list = []
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(StudyPlan.title.like(pattern) | StudyPlan.subtitle.like(pattern))
    if status is not None:
        filters.append(StudyPlan.status == status)
    total = db.scalar(select(func.count(StudyPlan.id)).where(*filters)) or 0
    plans = db.scalars(
        select(StudyPlan)
        .where(*filters)
        .order_by(StudyPlan.updated_at.desc(), StudyPlan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    counts: dict[int, int] = {}
    if plans:
        count_rows = db.execute(
            select(StudyPlanEnrollment.plan_id, func.count(StudyPlanEnrollment.id))
            .where(StudyPlanEnrollment.plan_id.in_([plan.id for plan in plans]))
            .group_by(StudyPlanEnrollment.plan_id)
        ).all()
        counts = {row[0]: row[1] for row in count_rows}
    return (
        [
            {
                "id": plan.id,
                "title": plan.title,
                "subtitle": plan.subtitle,
                "accent": plan.accent,
                "status": plan.status,
                "problem_count": len(plan.problems),
                "enrolled_count": counts.get(plan.id, 0),
                "updated_at": plan.updated_at,
            }
            for plan in plans
        ],
        total,
    )


def upsert_study_plan(
    db: Session, data: StudyPlanWriteRequest, actor_id: int, plan: StudyPlan | None = None
) -> StudyPlan:
    if plan is None:
        plan = StudyPlan(
            title=data.title,
            subtitle=data.subtitle,
            description=data.description,
            accent=data.accent,
            created_by=actor_id,
        )
        db.add(plan)
        db.flush()
    else:
        if plan.status == StudyPlanStatus.ARCHIVED:
            raise AppError(409, "STUDY_PLAN_ARCHIVED", "已归档的学习计划不能编辑")
        plan.title = data.title
        plan.subtitle = data.subtitle
        plan.description = data.description
        plan.accent = data.accent

    problem_ids = [item.problem_id for item in data.problems]
    problems: list[Problem] = []
    if problem_ids:
        problems = list(db.scalars(select(Problem).where(Problem.id.in_(problem_ids))).all())
        if {problem.id for problem in problems} != set(problem_ids):
            raise AppError(400, "INVALID_STUDY_PLAN_PROBLEMS", "学习计划包含不存在的题目")
        if plan.status == StudyPlanStatus.PUBLISHED and any(
            problem.status != ProblemStatus.PUBLISHED for problem in problems
        ):
            raise AppError(409, "STUDY_PLAN_PROBLEM_UNPUBLISHED", "已发布的学习计划只能包含已发布题目")

    # Replace all rows explicitly: SQLite enforces the (plan_id, problem_id)
    # unique key immediately, so delete-orphan flush ordering is not reliable.
    plan.problems.clear()
    db.flush()
    plan.problems = [
        StudyPlanProblem(
            plan_id=plan.id,
            problem_id=item.problem_id,
            position=item.position,
            group_name=item.group_name,
        )
        for item in sorted(data.problems, key=lambda item: item.position)
    ]
    db.flush()
    return plan


def publish_study_plan(db: Session, plan: StudyPlan) -> None:
    if plan.status == StudyPlanStatus.ARCHIVED:
        raise AppError(409, "STUDY_PLAN_ARCHIVED", "已归档的学习计划不能发布")
    if not plan.problems:
        raise AppError(409, "STUDY_PLAN_PROBLEMS_REQUIRED", "发布学习计划前必须配置题目")
    if any(entry.problem.status != ProblemStatus.PUBLISHED for entry in plan.problems):
        raise AppError(409, "STUDY_PLAN_PROBLEM_UNPUBLISHED", "学习计划包含未发布题目")
    plan.status = StudyPlanStatus.PUBLISHED


def join_study_plan(db: Session, plan: StudyPlan, user: User) -> None:
    if enrollment_for(db, plan.id, user.id) is None:
        db.add(StudyPlanEnrollment(plan_id=plan.id, user_id=user.id))
        db.flush()


def leave_study_plan(db: Session, plan: StudyPlan, user: User) -> None:
    enrollment = enrollment_for(db, plan.id, user.id)
    if enrollment is not None:
        db.delete(enrollment)
        db.flush()
