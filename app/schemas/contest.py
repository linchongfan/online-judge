from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models import ContestPublication, Difficulty
from app.schemas.common import ApiSchema


class ContestProblemInput(ApiSchema):
    problem_id: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z][A-Z0-9]*$")
    position: int = Field(ge=1)


class ContestWriteRequest(ApiSchema):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=255)
    description: str = Field(min_length=1, max_length=50_000)
    organizer: str = Field(min_length=1, max_length=100)
    start_time: datetime
    end_time: datetime
    accent: str = Field(default="blue", max_length=20)
    expected_participants: int | None = Field(default=None, ge=0)
    problems: list[ContestProblemInput] = Field(default_factory=list, max_length=52)

    @model_validator(mode="after")
    def validate_schedule(self) -> "ContestWriteRequest":
        start = self.start_time.replace(tzinfo=self.start_time.tzinfo or UTC)
        end = self.end_time.replace(tzinfo=self.end_time.tzinfo or UTC)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        if len({item.problem_id for item in self.problems}) != len(self.problems):
            raise ValueError("竞赛不能重复包含同一道题")
        if len({item.label for item in self.problems}) != len(self.problems):
            raise ValueError("赛题标签不能重复")
        return self


class ContestProblemResponse(ApiSchema):
    label: str
    problem_id: int
    title: str
    difficulty: Difficulty
    solved: int = 0
    attempts: int = 0
    user_status: Literal["AC", "WA", "untouched"] = "untouched"


class ContestResponse(ApiSchema):
    id: int
    title: str
    subtitle: str
    description: str
    organizer: str
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    status: Literal["ongoing", "upcoming", "ended"]
    publication_status: ContestPublication
    participants: int
    expected_participants: int | None = None
    registered: bool
    accent: str
    server_time: datetime
    problems: list[ContestProblemResponse] = Field(default_factory=list)


class RankProblemResult(ApiSchema):
    status: Literal["AC", "WA", "none"]
    time_seconds: int | None = None
    attempts: int = 0
    wrong_attempts: int = 0


class RankEntryResponse(ApiSchema):
    rank: int
    username: str
    nickname: str
    solved: int
    penalty_seconds: int
    results: dict[str, RankProblemResult]


class RankingResponse(ApiSchema):
    contest_id: int
    server_time: datetime
    entries: list[RankEntryResponse]


class ContestResultResponse(ApiSchema):
    contest_id: int
    solved_count: int
    penalty_seconds: int
    rank: int | None
