from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Db
from app.models import JudgeStatus, Language
from app.schemas.common import Page, make_page
from app.schemas.submission import SubmissionAccepted, SubmissionCreate, SubmissionResponse
from app.services.submissions import create_submission, get_submission, list_submissions, serialize_submission

router = APIRouter()


@router.post("", response_model=SubmissionAccepted, status_code=status.HTTP_202_ACCEPTED)
def submit(data: SubmissionCreate, db: Db, user: CurrentUser):
    return create_submission(db, data, user)


@router.get("", response_model=Page[SubmissionResponse])
def submissions(
    db: Db,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    submission_status: JudgeStatus | None = Query(None, alias="status"),
    language: Language | None = None,
    problem_id: int | None = Query(None, ge=1, alias="problemId"),
):
    items, total = list_submissions(
        db, user, page, page_size, keyword, submission_status, language, problem_id=problem_id
    )
    return make_page([serialize_submission(item) for item in items], total, page, page_size)


@router.get("/{submission_id}", response_model=SubmissionResponse)
def submission_detail(submission_id: str, db: Db, user: CurrentUser):
    return serialize_submission(get_submission(db, submission_id, user))


@router.get("/{submission_id}/source")
def submission_source(submission_id: str, db: Db, user: CurrentUser):
    item = get_submission(db, submission_id, user)
    return {"id": item.id, "language": item.language, "source": item.source_code}
