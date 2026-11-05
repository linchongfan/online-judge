from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import Db
from app.models import utcnow

router = APIRouter()


@router.get("/health/live")
def live():
    return {"status": "ok", "serverTime": utcnow()}


@router.get("/health/ready")
def ready(db: Db):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "serverTime": utcnow()}
