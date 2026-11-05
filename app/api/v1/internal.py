from fastapi import APIRouter, Request
from pydantic import Field

from app.api.deps import Db
from app.core.exceptions import AppError
from app.core.signing import verify_result_signature
from app.models import JudgeWorker, WorkerStatus, utcnow
from app.schemas.common import ApiSchema, MessageResponse

router = APIRouter()


class WorkerHeartbeat(ApiSchema):
    worker_id: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    active_tasks: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    cpu: float | None = Field(default=None, ge=0, le=100)
    memory: float | None = Field(default=None, ge=0, le=100)


class WorkerHeartbeatResponse(MessageResponse):
    accepting: bool = True


@router.post("/judge/heartbeat", response_model=WorkerHeartbeatResponse)
def heartbeat(data: WorkerHeartbeat, request: Request, db: Db):
    payload = data.model_dump()
    signature = request.headers.get("X-Judge-Signature", "")
    if not verify_result_signature(payload, signature):
        raise AppError(401, "INVALID_WORKER_SIGNATURE", "Worker 认证失败")
    worker = db.get(JudgeWorker, data.worker_id)
    if worker is None:
        worker = JudgeWorker(id=data.worker_id, host=data.host)
        db.add(worker)
    worker.host = data.host
    worker.status = WorkerStatus.BUSY if data.active_tasks else WorkerStatus.ONLINE
    worker.active_tasks = data.active_tasks
    worker.completed = data.completed
    worker.cpu = data.cpu
    worker.memory = data.memory
    worker.heartbeat_at = utcnow()
    db.commit()
    return {"message": "ok", "accepting": worker.accepting}
