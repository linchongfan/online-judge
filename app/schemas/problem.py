from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models import Difficulty, Language, ProblemStatus
from app.schemas.common import ApiSchema


class SampleResponse(ApiSchema):
    input: str
    output: str
    explanation: str | None = None


class ProblemListItem(ApiSchema):
    id: int
    title: str
    difficulty: Difficulty
    tags: list[str]
    acceptance: float
    submission_count: int
    solved_count: int
    progress: Literal["solved", "attempted", "untouched"]


class ProblemDetail(ProblemListItem):
    description: list[str]
    input_description: str
    output_description: str
    constraints: list[str]
    samples: list[SampleResponse]
    time_limit_ms: int
    memory_limit_mb: int
    updated_at: datetime


class SolutionCodeResponse(ApiSchema):
    language: Language
    code: str


class SolutionResponse(ApiSchema):
    title: str
    summary: str
    steps: list[str]
    time_complexity: str = Field(serialization_alias="time")
    space_complexity: str = Field(serialization_alias="space")
    codes: list[SolutionCodeResponse]


class SolutionCodeInput(ApiSchema):
    language: Language
    code: str = Field(min_length=1, max_length=100_000)


class SolutionInput(ApiSchema):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=20_000)
    steps: list[str] = Field(min_length=1, max_length=30)
    time_complexity: str = Field(min_length=1, max_length=100)
    space_complexity: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    codes: list[SolutionCodeInput] = Field(default_factory=list, max_length=4)


class ProblemWriteRequest(ApiSchema):
    id: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=200)
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list, max_length=12)
    description: list[str] = Field(min_length=1, max_length=100)
    input_description: str = Field(min_length=1, max_length=20_000)
    output_description: str = Field(min_length=1, max_length=20_000)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    time_limit_ms: int = Field(default=1000, ge=100, le=30_000)
    memory_limit_mb: int = Field(default=256, ge=16, le=1024)
    solution: SolutionInput | None = None

    @model_validator(mode="after")
    def validate_tags(self) -> "ProblemWriteRequest":
        self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip()))
        if any(len(tag) > 40 for tag in self.tags):
            raise ValueError("单个标签不能超过 40 个字符")
        return self


class AdminProblemResponse(ApiSchema):
    id: int
    title: str
    difficulty: Difficulty
    tags: list[str]
    status: ProblemStatus
    time_limit_ms: int
    memory_limit_mb: int
    test_data_version: str | None
    test_case_count: int
    test_data_size: int = 0
    acceptance: float
    submission_count: int
    solution_language_count: int = 0
    updated_at: datetime


class TagResponse(ApiSchema):
    id: int
    name: str
    problem_count: int = 0
