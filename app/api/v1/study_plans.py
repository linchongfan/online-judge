from fastapi import APIRouter

from app.api.deps import CurrentUser, Db, OptionalUser
from app.schemas.common import MessageResponse
from app.schemas.study_plan import StudyPlanDetail, StudyPlanSummary
from app.services.study_plans import (
    get_study_plan,
    join_study_plan,
    leave_study_plan,
    list_published_study_plans,
    serialize_study_plan,
)

router = APIRouter()


@router.get("", response_model=list[StudyPlanSummary])
def study_plans(db: Db, user: OptionalUser):
    return list_published_study_plans(db, user)


@router.get("/{plan_id}", response_model=StudyPlanDetail)
def study_plan_detail(plan_id: int, db: Db, user: OptionalUser):
    return serialize_study_plan(db, get_study_plan(db, plan_id), user, include_problems=True)


@router.put("/{plan_id}/enrollment", response_model=MessageResponse)
def join(plan_id: int, db: Db, user: CurrentUser):
    plan = get_study_plan(db, plan_id)
    join_study_plan(db, plan, user)
    db.commit()
    return {"message": "已加入学习计划"}


@router.delete("/{plan_id}/enrollment", response_model=MessageResponse)
def leave(plan_id: int, db: Db, user: CurrentUser):
    plan = get_study_plan(db, plan_id)
    leave_study_plan(db, plan, user)
    db.commit()
    return {"message": "已退出学习计划"}
