"""Pure-data protocols exchanged with the independent judge worker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar


class JudgeStatus(StrEnum):
    PENDING = "PENDING"
    JUDGING = "JUDGING"
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    MLE = "MLE"
    RE = "RE"
    CE = "CE"
    SE = "SE"


# A short alias is convenient for callers that use ``Status.AC``.
Status = JudgeStatus


@dataclass(frozen=True, slots=True)
class TestCase:
    __test__: ClassVar[bool] = False  # Prevent pytest from collecting this data class.

    case_id: str
    input_data: str
    expected_output: str
    is_sample: bool = False


# Alternative domain name kept as an alias, not a second protocol.
JudgeCase = TestCase


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    request_id: str
    language: str
    source_code: str
    cases: tuple[TestCase, ...]
    time_limit_ms: int = 1_000
    memory_limit_kb: int = 262_144
    compile_time_limit_ms: int = 10_000
    output_limit_bytes: int = 1_048_576
    compile_output_limit_bytes: int = 65_536

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    status: JudgeStatus
    runtime_ms: int | None = None
    memory_kb: int | None = None
    diagnostic: str = ""

    @property
    def runtimeMs(self) -> int | None:  # noqa: N802 - wire-format spelling
        return self.runtime_ms

    @property
    def memoryKb(self) -> int | None:  # noqa: N802 - wire-format spelling
        return self.memory_kb

    def to_dict(self) -> dict[str, Any]:
        return {
            "caseId": self.case_id,
            "status": self.status.value,
            "runtimeMs": self.runtime_ms,
            "memoryKb": self.memory_kb,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True, slots=True)
class JudgeResult:
    request_id: str
    status: JudgeStatus
    case_results: tuple[CaseResult, ...] = ()
    runtime_ms: int | None = None
    memory_kb: int | None = None
    diagnostic: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_results", tuple(self.case_results))

    @property
    def runtimeMs(self) -> int | None:  # noqa: N802 - wire-format spelling
        return self.runtime_ms

    @property
    def memoryKb(self) -> int | None:  # noqa: N802 - wire-format spelling
        return self.memory_kb

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "status": self.status.value,
            "caseResults": [case.to_dict() for case in self.case_results],
            "runtimeMs": self.runtime_ms,
            "memoryKb": self.memory_kb,
            "diagnostic": self.diagnostic,
        }
