"""Phase-5 performance regressions: constant query counts and incremental scoring."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event, select

from app.models import (
    Contest,
    ContestResult,
    Difficulty,
    JudgeStatus,
    Language,
    Problem,
    ProblemStatus,
    Submission,
    utcnow,
)
from app.services.contests import recompute_contest_results
from app.services.problems import problem_stats, problem_stats_batch
from app.tasks.results import process_judge_result
from tests.test_contest_api import contest_payload, result_for
from tests.test_problem_api import create_published_problem


def _count_selects(engine, action) -> int:
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return len(statements)


def _add_published_problems(db_session, count: int) -> None:
    for index in range(count):
        db_session.add(
            Problem(
                title=f"批量统计题 {index}",
                difficulty=Difficulty.EASY,
                description=[],
                input_description="",
                output_description="",
                constraints_json=[],
                status=ProblemStatus.PUBLISHED,
            )
        )
    db_session.commit()


def test_problem_list_query_count_does_not_grow_with_page_size(client, db_session):
    _add_published_problems(db_session, 3)
    engine = db_session.get_bind()
    small = _count_selects(engine, lambda: client.get("/api/v1/problems?pageSize=100"))

    _add_published_problems(db_session, 25)
    large = _count_selects(engine, lambda: client.get("/api/v1/problems?pageSize=100"))

    # Stats are aggregated per page, not per problem: the count must not scale
    # with the number of rows returned.
    assert large <= small + 1, f"query count grew with page size: {small} -> {large}"


def test_batch_stats_match_single_problem_stats(client, admin_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    user_id = 4242
    from app.models import TestDataVersion

    version_id = db_session.scalar(
        select(TestDataVersion.id).where(TestDataVersion.problem_id == problem_id, TestDataVersion.is_current.is_(True))
    )
    for index, (status, sample) in enumerate(
        ((JudgeStatus.AC, False), (JudgeStatus.WA, False), (JudgeStatus.AC, True))
    ):
        db_session.add(
            Submission(
                idempotency_key=f"stats-{index}",
                user_id=user_id,
                problem_id=problem_id,
                language=Language("python"),
                source_code="print(1)",
                status=status,
                test_data_version_id=version_id,
                is_sample_run=sample,
            )
        )
    db_session.commit()

    batch = problem_stats_batch(db_session, [problem_id], user_id)[problem_id]
    single = problem_stats(db_session, problem_id, user_id)
    assert batch == single
    assert batch["submission_count"] == 2  # sample runs are excluded
    assert batch["solved_count"] == 1
    assert batch["progress"] == "solved"


def test_incremental_contest_result_matches_full_recompute(client, admin_headers, user_headers, db_session):
    problem_id = create_published_problem(client, admin_headers)
    created = client.post("/api/v1/admin/contests", json=contest_payload(problem_id), headers=admin_headers)
    assert created.status_code == 201, created.text
    contest_id = created.json()["id"]
    assert client.post(f"/api/v1/admin/contests/{contest_id}/publish", headers=admin_headers).status_code == 200
    assert client.put(f"/api/v1/contests/{contest_id}/registration", headers=user_headers).status_code == 200

    contest = db_session.get(Contest, contest_id)
    contest.start_time = utcnow() - timedelta(minutes=30)
    contest.end_time = utcnow() + timedelta(hours=2)
    db_session.commit()

    for index, status in enumerate(("WA", "AC")):
        accepted = client.post(
            "/api/v1/submissions",
            headers=user_headers,
            json={
                "problemId": problem_id,
                "contestId": contest_id,
                "language": "python",
                "source": f"print({index})",
                "idempotencyKey": f"incremental-{index}",
            },
        )
        assert accepted.status_code == 202, accepted.text
        db_session.expire_all()
        assert process_judge_result(result_for(db_session, accepted.json()["id"], status)) is True

    def snapshot():
        db_session.expire_all()
        rows = db_session.scalars(select(ContestResult).where(ContestResult.contest_id == contest_id)).all()
        return {row.user_id: (row.solved_count, row.penalty_seconds, row.rank) for row in rows}

    incremental = snapshot()
    assert incremental, "incremental recompute produced no contest result"

    recompute_contest_results(db_session, db_session.get(Contest, contest_id))
    db_session.commit()
    full = snapshot()

    assert incremental == full
    solved, _penalty, rank = full[next(iter(full))]
    assert solved == 1
    assert rank == 1
