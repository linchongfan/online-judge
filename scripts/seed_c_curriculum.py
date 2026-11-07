"""导入 C 语言培养方案题库（10 个模块 × 10 题，幂等）。

用法：
    .venv/bin/python scripts/seed_c_curriculum.py
    # 或指定数据文件
    .venv/bin/python scripts/seed_c_curriculum.py scripts/curriculum_problems.json

题目 ID 范围 2000-2099，已存在的题目会跳过。每题包含 1 个公开样例与 3 个隐藏测试点，
参考解使用 C 语言，已通过本地编译与线上判题验证。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import (
    Difficulty,
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
)
from app.services.test_data import TestDataService
from scripts.seed import zip_data

STATEMENT_PREFIX = "【{topic}】"


def build_zip(cases: list[dict]) -> bytes:
    samples = [(c["input"], c["output"]) for c in cases if c["is_sample"]]
    hidden = [(c["input"], c["output"]) for c in cases if not c["is_sample"]]
    return zip_data(samples, hidden)


def ensure_tag(db, name: str) -> Tag:
    tag = db.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def import_problem(db, admin: User, item: dict) -> str:
    existing = db.get(Problem, item["id"])
    if existing is not None:
        return f"skip {item['id']} {item['title']}"

    problem = Problem(
        id=item["id"],
        title=item["title"],
        difficulty=Difficulty(item["difficulty"]),
        description=[STATEMENT_PREFIX.format(topic=item["topic"])] + list(item["description"]),
        input_description=item["input_description"],
        output_description=item["output_description"],
        constraints_json=list(item["constraints"]),
        time_limit_ms=1000,
        memory_limit_mb=256,
        status=ProblemStatus.PUBLISHED,
        created_by=admin.id,
    )
    problem.tags = [ensure_tag(db, name) for name in dict.fromkeys(item["tags"])]
    db.add(problem)
    db.flush()

    solution = ProblemSolution(
        problem_id=problem.id,
        title=f"{item['title']}参考解法",
        summary=f"使用 C 语言完成{item['topic']}相关练习。",
        steps=["读入数据", "按题意处理", "输出结果"],
        time_complexity="O(n)",
        space_complexity="O(1)",
    )
    db.add(solution)
    db.flush()
    db.add(SolutionCode(solution_id=solution.id, language=Language.C, code=item["solution_c"]))

    content = build_zip(item["cases"])
    version = TestDataVersion(
        problem_id=problem.id,
        version=1,
        status=TestDataStatus.VALID,
        is_current=True,
        storage_path="",
        original_filename=f"c-curriculum-{problem.id}.zip",
        compressed_size=len(content),
        created_by=admin.id,
    )
    db.add(version)
    db.flush()
    destination = (
        get_settings().storage_root.resolve()
        / "test-data"
        / f"problem-{problem.id}"
        / version.id
    )
    result = TestDataService().store(content, destination)
    version.storage_path = str(destination)
    version.uncompressed_size = sum(f.size for f in result.files)
    version.test_case_count = result.test_count
    version.sample_count = result.sample_count
    version.content_hash = f"c-curriculum-{problem.id}"
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
    db.commit()
    return f"create {item['id']} {item['title']} ({result.test_count} cases)"


def main() -> None:
    default = Path(__file__).with_name("curriculum_problems.json")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    items = json.loads(path.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == "admin@123321"))
        if admin is None:
            raise SystemExit("admin@123321 not found")
        for item in items:
            print(import_problem(db, admin, item))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"done: {len(items)} problems")


if __name__ == "__main__":
    main()
