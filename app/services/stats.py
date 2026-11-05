from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ContestRegistration,
    ContestResult,
    Difficulty,
    JudgeStatus,
    Problem,
    ProblemStatus,
    RegistrationStatus,
    Submission,
    User,
    utcnow,
)


def user_stats(db: Session, user: User) -> dict:
    submission_count = (
        db.scalar(
            select(func.count(Submission.id)).where(Submission.user_id == user.id, Submission.is_sample_run.is_(False))
        )
        or 0
    )
    accepted_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.user_id == user.id,
                Submission.status == JudgeStatus.AC,
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    solved_count = (
        db.scalar(
            select(func.count(func.distinct(Submission.problem_id)))
            .join(Problem, Problem.id == Submission.problem_id)
            .where(
                Submission.user_id == user.id,
                Submission.status == JudgeStatus.AC,
                Submission.is_sample_run.is_(False),
                Submission.contest_id.is_(None),
                Problem.status == ProblemStatus.PUBLISHED,
            )
        )
        or 0
    )
    judged_count = (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.user_id == user.id,
                Submission.status.not_in([JudgeStatus.PENDING, JudgeStatus.JUDGING, JudgeStatus.SE]),
                Submission.is_sample_run.is_(False),
            )
        )
        or 0
    )
    days = db.scalars(
        select(func.date(Submission.created_at))
        .where(Submission.user_id == user.id, Submission.is_sample_run.is_(False))
        .group_by(func.date(Submission.created_at))
    ).all()
    day_set = set(days)
    today = utcnow().date()
    cursor = today
    if cursor not in day_set:
        from datetime import timedelta

        cursor -= timedelta(days=1)
    streak = 0
    from datetime import timedelta

    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)

    higher_ranked = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.id.in_(
                    select(Submission.user_id)
                    .where(
                        Submission.status == JudgeStatus.AC,
                        Submission.contest_id.is_(None),
                        Submission.is_sample_run.is_(False),
                    )
                    .group_by(Submission.user_id)
                    .having(func.count(func.distinct(Submission.problem_id)) > solved_count)
                )
            )
        )
        or 0
    )

    difficulty_progress = []
    for difficulty in Difficulty:
        total = (
            db.scalar(
                select(func.count(Problem.id)).where(
                    Problem.difficulty == difficulty, Problem.status == ProblemStatus.PUBLISHED
                )
            )
            or 0
        )
        solved = (
            db.scalar(
                select(func.count(func.distinct(Submission.problem_id)))
                .join(Problem, Problem.id == Submission.problem_id)
                .where(
                    Submission.user_id == user.id,
                    Submission.status == JudgeStatus.AC,
                    Submission.is_sample_run.is_(False),
                    Submission.contest_id.is_(None),
                    Problem.difficulty == difficulty,
                    Problem.status == ProblemStatus.PUBLISHED,
                )
            )
            or 0
        )
        # Archived problems may leave solved above total; report a consistent ratio.
        difficulty_progress.append(
            {"difficulty": difficulty, "total": total, "solved": min(solved, total)}
        )
    return {
        "submissionCount": submission_count,
        "acceptedCount": accepted_count,
        "solvedCount": solved_count,
        "acceptance": round(accepted_count / judged_count * 100, 1) if judged_count else 0.0,
        "streak": streak,
        "ranking": higher_ranked + 1 if submission_count else 0,
        "difficultyProgress": difficulty_progress,
    }


def user_contest_records(db: Session, user_id: int) -> list[dict]:
    rows = db.execute(
        select(ContestRegistration, ContestResult)
        .outerjoin(
            ContestResult,
            (ContestResult.contest_id == ContestRegistration.contest_id) & (ContestResult.user_id == user_id),
        )
        .where(ContestRegistration.user_id == user_id, ContestRegistration.status == RegistrationStatus.REGISTERED)
        .order_by(ContestRegistration.created_at.desc())
    ).all()
    return [
        {
            "contestId": registration.contest_id,
            "registeredAt": registration.created_at,
            "solvedCount": result.solved_count if result else 0,
            "penaltySeconds": result.penalty_seconds if result else 0,
            "rank": result.rank if result else None,
        }
        for registration, result in rows
    ]
