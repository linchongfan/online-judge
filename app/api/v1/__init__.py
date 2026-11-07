from fastapi import APIRouter

from app.api.v1 import admin, auth, contests, health, internal, me, problems, study_plans, submissions

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(problems.router, prefix="/problems", tags=["problems"])
api_router.include_router(problems.tags_router, prefix="/tags", tags=["problems"])
api_router.include_router(study_plans.router, prefix="/study-plans", tags=["study-plans"])
api_router.include_router(submissions.router, prefix="/submissions", tags=["submissions"])
api_router.include_router(contests.router, prefix="/contests", tags=["contests"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(internal.router, prefix="/internal", tags=["internal"])
