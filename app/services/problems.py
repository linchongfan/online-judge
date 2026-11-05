import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    JudgeStatus,
    Problem,
    ProblemSolution,
    ProblemStatus,
    SolutionCode,
    Submission,
    Tag,
    TestDataStatus,
    TestDataVersion,
    User,
)
from app.schemas.problem import ProblemWriteRequest


def current_test_data(db: Session, problem_id: int) -> TestDataVersion | None:
    return db.scalar(
        select(TestDataVersion).where(
            TestDataVersion.problem_id == problem_id,
            TestDataVersion.is_current.is_(True),
            TestDataVersion.status == TestDataStatus.VALID,
        )
    )


def get_problem(db: Session, problem_id: int, user: User | None = None, include_unpublished: bool = False) -> Problem:
    problem = db.get(Problem, problem_id)
    if problem is None or (not include_unpublished and problem.status != ProblemStatus.PUBLISHED):
        raise AppError(404, "PROBLEM_NOT_FOUND", "题目不存在或尚未发布")
    return problem


def problem_stats(db: Session, problem_id: int, user_id: int | None) -> dict:
    submission_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.problem_id == problem_id, Submission.is_sample_run.is_(False)
            )
        )
        or 0
    )
    accepted_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.problem_id == problem_id,
                Submission.status == JudgeStatus.AC,
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    judged_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.problem_id == problem_id,
                Submission.status.not_in([JudgeStatus.PENDING, JudgeStatus.JUDGING, JudgeStatus.SE]),
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    solved_count = (
        db.scalar(
            select(func.count(func.distinct(Submission.user_id))).where(
                Submission.problem_id == problem_id,
                Submission.status == JudgeStatus.AC,
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    progress = "untouched"
    if user_id is not None:
        statuses = db.scalars(
            select(Submission.status).where(
                Submission.problem_id == problem_id,
                Submission.user_id == user_id,
                Submission.is_sample_run.is_(False),
            )
        ).all()
        if JudgeStatus.AC in statuses:
            progress = "solved"
        elif statuses:
            progress = "attempted"
    return {
        "submission_count": submission_count,
        "solved_count": solved_count,
        "acceptance": round(accepted_count / judged_count * 100, 1) if judged_count else 0.0,
        "progress": progress,
    }


def serialize_list_item(db: Session, problem: Problem, user_id: int | None) -> dict:
    return {
        "id": problem.id,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "tags": [tag.name for tag in problem.tags],
        **problem_stats(db, problem.id, user_id),
    }


def serialize_detail(db: Session, problem: Problem, user_id: int | None) -> dict:
    samples = []
    version = current_test_data(db, problem.id)
    if version:
        sample_cases = [case for case in version.cases if case.is_sample]
        for case in sorted(sample_cases, key=lambda item: item.case_number):
            base = Path(version.storage_path)
            try:
                input_text = (base / case.input_key).read_text(encoding="utf-8")
                output_text = (base / case.output_key).read_text(encoding="utf-8")
            except OSError as exc:
                raise AppError(503, "TEST_DATA_UNAVAILABLE", "公开样例暂时不可用") from exc
            samples.append({"input": input_text, "output": output_text, "explanation": None})
    return {
        **serialize_list_item(db, problem, user_id),
        "description": problem.description,
        "input_description": problem.input_description,
        "output_description": problem.output_description,
        "constraints": problem.constraints_json,
        "samples": samples,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "updated_at": problem.updated_at,
    }


def list_problems(
    db: Session,
    user: User | None,
    page: int,
    page_size: int,
    keyword: str | None,
    difficulty: str | None,
    tag: str | None,
    progress: str | None,
) -> tuple[list[Problem], int]:
    query = select(Problem).where(Problem.status == ProblemStatus.PUBLISHED)
    count_query = select(func.count(Problem.id)).where(Problem.status == ProblemStatus.PUBLISHED)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.where(Problem.title.like(pattern))
        count_query = count_query.where(Problem.title.like(pattern))
    if difficulty:
        query = query.where(Problem.difficulty == difficulty)
        count_query = count_query.where(Problem.difficulty == difficulty)
    if tag:
        tag_filter = Problem.tags.any(Tag.name == tag)
        query = query.where(tag_filter)
        count_query = count_query.where(tag_filter)
    if progress and user:
        submissions = select(Submission.problem_id).where(
            Submission.user_id == user.id, Submission.is_sample_run.is_(False)
        )
        solved = submissions.where(Submission.status == JudgeStatus.AC)
        condition: Any
        if progress == "solved":
            condition = Problem.id.in_(solved)
        elif progress == "attempted":
            condition = Problem.id.in_(submissions) & Problem.id.not_in(solved)
        else:
            condition = Problem.id.not_in(submissions)
        query = query.where(condition)
        count_query = count_query.where(condition)
    total = db.scalar(count_query) or 0
    problems = list(db.scalars(query.order_by(Problem.id).offset((page - 1) * page_size).limit(page_size)).all())
    return problems, total


def random_problem(db: Session) -> Problem:
    ids = db.scalars(select(Problem.id).where(Problem.status == ProblemStatus.PUBLISHED)).all()
    if not ids:
        raise AppError(404, "NO_PUBLISHED_PROBLEM", "暂无已发布题目")
    return get_problem(db, secrets.choice(ids))


def upsert_problem(db: Session, data: ProblemWriteRequest, actor_id: int, problem: Problem | None = None) -> Problem:
    if problem is None:
        if data.id is not None and db.get(Problem, data.id) is not None:
            raise AppError(409, "PROBLEM_ID_EXISTS", "题目编号已存在")
        values = data.model_dump(exclude={"tags", "solution", "constraints"}, by_alias=False)
        values["constraints_json"] = data.constraints
        problem = Problem(**values, created_by=actor_id)
        db.add(problem)
        db.flush()
    else:
        problem.title = data.title.strip()
        problem.difficulty = data.difficulty
        problem.description = data.description
        problem.input_description = data.input_description
        problem.output_description = data.output_description
        problem.constraints_json = data.constraints
        problem.time_limit_ms = data.time_limit_ms
        problem.memory_limit_mb = data.memory_limit_mb
    tags = []
    for name in data.tags:
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    problem.tags = tags
    if data.solution is not None:
        solution = problem.solution
        if solution is None:
            solution = ProblemSolution(problem_id=problem.id)
            db.add(solution)
        solution.title = data.solution.title
        solution.summary = data.solution.summary
        solution.steps = data.solution.steps
        solution.time_complexity = data.solution.time_complexity
        solution.space_complexity = data.solution.space_complexity
        solution.enabled = data.solution.enabled
        db.flush()
        solution.code_variants = [
            SolutionCode(solution_id=solution.id, language=code.language, code=code.code)
            for code in data.solution.codes
        ]
    db.flush()
    return problem


def change_problem_status(db: Session, problem: Problem, status: ProblemStatus) -> None:
    if status == ProblemStatus.PUBLISHED and current_test_data(db, problem.id) is None:
        raise AppError(409, "VALID_TEST_DATA_REQUIRED", "发布前必须上传并校验通过测试数据")
    problem.status = status


def activate_test_data(db: Session, version: TestDataVersion) -> None:
    db.execute(
        update(TestDataVersion)
        .where(TestDataVersion.problem_id == version.problem_id, TestDataVersion.id != version.id)
        .values(is_current=False)
    )
    version.is_current = True
