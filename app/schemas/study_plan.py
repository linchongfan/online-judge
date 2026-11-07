from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models import Difficulty, ProblemStatus, StudyPlanStatus
from app.schemas.common import ApiSchema

StudyPlanAccent = Literal["blue", "green", "purple", "orange", "rose", "teal"]


class StudyPlanProblemInput(ApiSchema):
    problem_id: int = Field(ge=1)
    position: int = Field(ge=1)
    group_name: str | None = Field(default=None, max_length=50)


class StudyPlanWriteRequest(ApiSchema):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=50_000)
    accent: StudyPlanAccent = "blue"
    problems: list[StudyPlanProblemInput] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_plan(self) -> "StudyPlanWriteRequest":
        self.title = self.title.strip()
        self.subtitle = self.subtitle.strip()
        if not self.title:
            raise ValueError("学习计划名称不能为空")
        if len({item.problem_id for item in self.problems}) != len(self.problems):
            raise ValueError("学习计划不能重复包含同一道题")
        if len({item.position for item in self.problems}) != len(self.problems):
            raise ValueError("题目排序位置不能重复")
        for item in self.problems:
            item.group_name = item.group_name.strip() if item.group_name else None
            if item.group_name and len(item.group_name) > 50:
                raise ValueError("分组名称不能超过 50 个字符")
        return self


class StudyPlanProblemResponse(ApiSchema):
    problem_id: int
    title: str
    difficulty: Difficulty
    tags: list[str]
    position: int
    group_name: str | None = None
    progress: Literal["solved", "attempted", "untouched"] = "untouched"


class StudyPlanSummary(ApiSchema):
    id: int
    title: str
    subtitle: str
    accent: str
    problem_count: int
    solved_count: int
    enrolled: bool
    completed: bool


class StudyPlanDetail(StudyPlanSummary):
    description: str
    problems: list[StudyPlanProblemResponse] = Field(default_factory=list)


class AdminStudyPlanProblemResponse(ApiSchema):
    problem_id: int
    title: str
    difficulty: Difficulty
    problem_status: ProblemStatus
    position: int
    group_name: str | None = None


class AdminStudyPlanSummary(ApiSchema):
    id: int
    title: str
    subtitle: str
    accent: str
    status: StudyPlanStatus
    problem_count: int
    enrolled_count: int
    updated_at: datetime


class AdminStudyPlanDetail(ApiSchema):
    id: int
    title: str
    subtitle: str
    description: str
    accent: str
    status: StudyPlanStatus
    problems: list[AdminStudyPlanProblemResponse] = Field(default_factory=list)
