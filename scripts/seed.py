"""Idempotent development seed data. Never run this seed in production."""

import io
import zipfile
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (
    Contest,
    ContestProblem,
    ContestPublication,
    Difficulty,
    JudgeWorker,
    Language,
    Problem,
    ProblemSolution,
    ProblemStatus,
    SolutionCode,
    Tag,
    TestCase,
    TestDataStatus,
    TestDataVersion,
    User,
    UserRole,
    WorkerStatus,
    utcnow,
)
from app.services.test_data import TestDataService


def zip_data(samples, hidden):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (input_text, output_text) in enumerate(samples, 1):
            archive.writestr(f"sample/{index}.in", input_text)
            archive.writestr(f"sample/{index}.out", output_text)
        for index, (input_text, output_text) in enumerate(hidden, 1):
            archive.writestr(f"hidden/{index}.in", input_text)
            archive.writestr(f"hidden/{index}.out", output_text)
    return content.getvalue()


def ensure_user(db, username, email, nickname, password, role=UserRole.USER):
    user = db.scalar(select(User).where(User.username == username))
    if user:
        return user
    user = User(
        username=username,
        email=email,
        nickname=nickname,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def ensure_problem(db, admin, problem_id, title, samples, hidden, tags, solution_code):
    problem = db.get(Problem, problem_id)
    if problem is None:
        problem = Problem(
            id=problem_id,
            title=title,
            difficulty=Difficulty.EASY,
            description=[f"请完成题目：{title}。"],
            input_description="按照题面从标准输入读入数据。",
            output_description="将答案输出到标准输出。",
            constraints_json=["输入均为题目规定范围内的合法数据。"],
            time_limit_ms=1000,
            memory_limit_mb=256,
            status=ProblemStatus.PUBLISHED,
            created_by=admin.id,
        )
        db.add(problem)
        db.flush()
    if not problem.tags:
        problem.tags = [ensure_tag(db, name) for name in tags]
    if problem.solution is None:
        solution = ProblemSolution(
            problem_id=problem.id,
            title=f"{title}参考解法",
            summary="使用标准输入输出完成计算。",
            steps=["读取标准输入", "计算并输出答案"],
            time_complexity="O(n)",
            space_complexity="O(1)",
        )
        db.add(solution)
        db.flush()
        solution.code_variants = [
            SolutionCode(solution_id=solution.id, language=Language.PYTHON, code=solution_code),
            SolutionCode(solution_id=solution.id, language=Language.CPP, code="// 请按题面实现完整 main 程序。\n"),
        ]
    current = db.scalar(
        select(TestDataVersion).where(TestDataVersion.problem_id == problem.id, TestDataVersion.is_current.is_(True))
    )
    if current is None:
        content = zip_data(samples, hidden)
        version = TestDataVersion(
            problem_id=problem.id,
            version=1,
            status=TestDataStatus.VALID,
            is_current=True,
            storage_path="",
            original_filename="seed.zip",
            compressed_size=len(content),
            created_by=admin.id,
        )
        db.add(version)
        db.flush()
        destination = get_settings().storage_root.resolve() / "test-data" / f"problem-{problem.id}" / version.id
        result = TestDataService().store(content, destination)
        version.storage_path = str(destination)
        version.uncompressed_size = sum(item.size for item in result.files)
        version.test_case_count = result.test_count
        version.sample_count = result.sample_count
        version.content_hash = "seed-" + str(problem.id)
        for case in result.cases:
            db.add(
                TestCase(
                    version_id=version.id,
                    case_number=case.number,
                    input_key=case.input.stored_path,
                    output_key=case.output.stored_path,
                    is_sample=case.category == "sample",
                    input_size=case.input.size,
                    output_size=case.output.size,
                )
            )
    return problem


def ensure_tag(db, name):
    tag = db.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def main():
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("Development seed refused in production")
    db = SessionLocal()
    try:
        admin = ensure_user(db, "admin", "admin@example.com", "系统管理员", "Admin12345", UserRole.ADMIN)
        ensure_user(db, "demo", "demo@example.com", "演示用户", "Demo12345")
        add = ensure_problem(
            db,
            admin,
            1000,
            "A+B 问题",
            [("1 2\n", "3\n")],
            [("10 20\n", "30\n"), ("-5 8\n", "3\n")],
            ["入门", "模拟"],
            "a, b = map(int, input().split())\nprint(a + b)\n",
        )
        two_sum = ensure_problem(
            db,
            admin,
            1001,
            "两数之和",
            [("4 9\n2 7 11 15\n", "0 1\n")],
            [("3 6\n3 2 4\n", "1 2\n")],
            ["数组", "哈希表"],
            (
                "n, target = map(int, input().split())\n"
                "nums = list(map(int, input().split()))\n"
                "seen = {}\n"
                "for i, value in enumerate(nums):\n"
                "    if target - value in seen:\n"
                "        print(seen[target - value], i)\n"
                "        break\n"
                "    seen[value] = i\n"
            ),
        )
        if db.get(Contest, 1) is None:
            contest = Contest(
                id=1,
                title="新生程序设计体验赛",
                subtitle="ACM 计分体验",
                description="熟悉在线判题与 ACM 排名规则。",
                organizer="新保研",
                start_time=utcnow() + timedelta(days=1),
                end_time=utcnow() + timedelta(days=1, hours=2),
                status=ContestPublication.PUBLISHED,
            )
            db.add(contest)
            db.flush()
            contest.problems = [
                ContestProblem(contest_id=contest.id, problem_id=add.id, label="A", position=1),
                ContestProblem(contest_id=contest.id, problem_id=two_sum.id, label="B", position=2),
            ]
        if db.get(JudgeWorker, "development-worker") is None:
            db.add(JudgeWorker(id="development-worker", host="127.0.0.1", status=WorkerStatus.OFFLINE, accepting=False))
        db.commit()
        print("Seed complete. Development accounts: admin/Admin12345, demo/Demo12345")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
