"""Framework-independent schemas for uploaded test-data archives."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TestDataCategory = Literal["default", "sample", "hidden"]
TestDataFileKind = Literal["input", "output"]


class TestDataLimits(BaseModel):
    """Resource limits applied before and while decompressing an archive."""

    model_config = ConfigDict(frozen=True)

    max_test_cases: int = Field(default=100, gt=0)
    max_file_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    max_total_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    max_archive_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    max_compression_ratio: float = Field(default=200.0, gt=1.0)


class TestDataError(BaseModel):
    """A validation error tied to an archive member or logical test case."""

    model_config = ConfigDict(frozen=True)

    code: str
    path: str
    message: str


class TestDataFile(BaseModel):
    """Metadata for one validated input or output file."""

    model_config = ConfigDict(frozen=True)

    path: str
    stored_path: str
    category: TestDataCategory
    number: int = Field(ge=1)
    kind: TestDataFileKind
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TestDataCase(BaseModel):
    """A consecutively numbered, matched input/output pair."""

    model_config = ConfigDict(frozen=True)

    category: TestDataCategory
    number: int = Field(ge=1)
    input: TestDataFile
    output: TestDataFile


class TestDataResult(BaseModel):
    """Successful validation result; file metadata is available per case."""

    model_config = ConfigDict(frozen=True)

    test_count: int = Field(gt=0)
    sample_count: int = Field(ge=0)
    hidden_count: int = Field(ge=0)
    cases: tuple[TestDataCase, ...]

    @property
    def files(self) -> tuple[TestDataFile, ...]:
        """Return every file in deterministic storage order."""

        return tuple(file for case in self.cases for file in (case.input, case.output))
