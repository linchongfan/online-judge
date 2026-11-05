from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Db, OptionalUser
from app.core.exceptions import AppError
from app.models import Contest, ContestPublication, ContestResult, utcnow
from app.schemas.common import MessageResponse, Page, make_page
from app.schemas.contest import ContestResponse, ContestResultResponse, RankingResponse
from app.services.contests import (
    cancel_registration,
    contest_lifecycle,
    get_contest,
    ranking,
    register_for_contest,
    serialize_contest,
)

router = APIRouter()


@router.get("", response_model=Page[ContestResponse])
def contests(
    db: Db,
    user: OptionalUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(ongoing|upcoming|ended)$"),
):
    query = select(Contest).where(Contest.status == ContestPublication.PUBLISHED)
    count_query = select(func.count(Contest.id)).where(Contest.status == ContestPublication.PUBLISHED)
    now = utcnow()
    condition: Any
    if status == "upcoming":
        condition = Contest.start_time > now
    elif status == "ongoing":
        condition = (Contest.start_time <= now) & (Contest.end_time > now)
    elif status == "ended":
        condition = Contest.end_time <= now
    else:
        condition = True
    query = query.where(condition)
    count_query = count_query.where(condition)
    total = db.scalar(count_query) or 0
    items = db.scalars(query.order_by(Contest.start_time.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return make_page([serialize_contest(db, item, user) for item in items], total, page, page_size)


@router.get("/{contest_id}", response_model=ContestResponse)
def contest_detail(contest_id: int, db: Db, user: OptionalUser):
    return serialize_contest(db, get_contest(db, contest_id), user, include_problems=True)


@router.get("/{contest_id}/problems")
def contest_problems(contest_id: int, db: Db, user: OptionalUser):
    data = serialize_contest(db, get_contest(db, contest_id), user, include_problems=True)
    return {"serverTime": data["server_time"], "items": data["problems"]}


@router.put("/{contest_id}/registration", response_model=MessageResponse)
def register(contest_id: int, db: Db, user: CurrentUser):
    contest = get_contest(db, contest_id)
    register_for_contest(db, contest, user)
    db.commit()
    return {"message": "报名成功"}


@router.delete("/{contest_id}/registration", response_model=MessageResponse)
def unregister(contest_id: int, db: Db, user: CurrentUser):
    contest = get_contest(db, contest_id)
    cancel_registration(db, contest, user)
    db.commit()
    return {"message": "已取消报名"}


@router.get("/{contest_id}/ranking", response_model=RankingResponse)
def contest_ranking(contest_id: int, db: Db):
    contest = get_contest(db, contest_id)
    if contest_lifecycle(contest) == "upcoming":
        raise AppError(409, "CONTEST_NOT_STARTED", "竞赛开始后才能查看排行榜")
    return {"contest_id": contest.id, "server_time": utcnow(), "entries": ranking(db, contest)}


@router.get("/{contest_id}/my-result", response_model=ContestResultResponse)
def my_result(contest_id: int, db: Db, user: CurrentUser):
    contest = get_contest(db, contest_id)
    result = db.scalar(
        select(ContestResult).where(ContestResult.contest_id == contest.id, ContestResult.user_id == user.id)
    )
    return {
        "contest_id": contest.id,
        "solved_count": result.solved_count if result else 0,
        "penalty_seconds": result.penalty_seconds if result else 0,
        "rank": result.rank if result else None,
    }
