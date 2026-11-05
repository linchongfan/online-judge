from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from judge.config import build_clean_environment
from judge.process import ProcessLimits, ProcessRunner
from judge.sandbox import (
    SandboxBackend,
    SandboxConfigurationError,
    SandboxExecutionInfo,
    SandboxPolicy,
    SandboxTerminationReason,
)


def _run_python(runner: ProcessRunner, tmp_path: Path, source: str, limits: ProcessLimits, stdin: bytes = b""):
    return runner.run(
        [sys.executable, "-I", "-c", source],
        cwd=tmp_path,
        env=build_clean_environment(None, tmp_path),
        stdin_data=stdin,
        limits=limits,
    )


def test_controlled_stdin_stdout_round_trip(tmp_path: Path) -> None:
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True))
    result = _run_python(
        runner,
        tmp_path,
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ProcessLimits(wall_timeout_ms=2_000, output_limit_bytes=1_024),
        b"hello\x00world",
    )
    assert result.exit_code == 0
    assert result.stdout == b"hello\x00world"
    assert not result.timed_out
    assert result.runtime_ms is not None
    assert result.memory_kb is None  # Local test backend does not fake accounting.


def test_controlled_wall_timeout_terminates_process(tmp_path: Path) -> None:
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True))
    started = time.monotonic()
    result = _run_python(
        runner,
        tmp_path,
        "import time; time.sleep(30)",
        ProcessLimits(wall_timeout_ms=50, output_limit_bytes=1_024),
    )
    assert result.timed_out
    assert result.exit_code is not None
    assert time.monotonic() - started < 10


def test_output_limit_is_enforced_even_for_fast_exit(tmp_path: Path) -> None:
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True))
    result = _run_python(
        runner,
        tmp_path,
        "print('x' * 128)",
        ProcessLimits(wall_timeout_ms=2_000, output_limit_bytes=16),
    )
    assert result.output_exceeded
    assert len(result.stdout) <= 17


def test_process_execution_is_denied_before_spawn_by_default(tmp_path: Path) -> None:
    runner = ProcessRunner(SandboxPolicy.development())
    with pytest.raises(SandboxConfigurationError):
        runner.run(
            ["this-command-must-not-be-started"],
            cwd=tmp_path,
            env={},
            stdin_data=b"",
            limits=ProcessLimits(wall_timeout_ms=10, output_limit_bytes=1),
        )


class _MetaBackend(SandboxBackend):
    """Backend fixture that reports authoritative sandbox execution metadata."""

    def __init__(self, info: SandboxExecutionInfo):
        self._info = info

    @property
    def capabilities(self):
        return None

    def spawn(self, **kwargs):
        return _FakePopen(returncode=0)

    def terminate(self, process) -> None:
        return None

    def memory_usage_kb(self, process):
        return self._info.peak_memory_kb

    def execution_info(self, process) -> SandboxExecutionInfo:
        return self._info


class _FakePopen:
    def __init__(self, returncode: int | None = 0):
        self.returncode = returncode
        self.pid = 12345

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0

    def kill(self):
        self.returncode = -9


def test_backend_wall_time_reason_is_preserved_as_timeout(tmp_path: Path) -> None:
    backend = _MetaBackend(
        SandboxExecutionInfo(
            termination_reason=SandboxTerminationReason.WALL_TIME_LIMIT,
            runtime_ms=50,
            wall_time_exceeded=True,
        )
    )
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True), backend)
    result = runner.run(
        ["ignored"],
        cwd=tmp_path,
        env={},
        stdin_data=b"",
        limits=ProcessLimits(wall_timeout_ms=1000, output_limit_bytes=128),
    )
    assert result.timed_out is True
    assert result.runtime_ms == 50
    assert result.exit_code == 0


def test_backend_memory_reason_is_preserved_as_memory_exceeded(tmp_path: Path) -> None:
    backend = _MetaBackend(
        SandboxExecutionInfo(
            termination_reason=SandboxTerminationReason.MEMORY_LIMIT,
            peak_memory_kb=2048,
            memory_exceeded=True,
        )
    )
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True), backend)
    result = runner.run(
        ["ignored"],
        cwd=tmp_path,
        env={},
        stdin_data=b"",
        limits=ProcessLimits(wall_timeout_ms=1000, output_limit_bytes=128, memory_limit_kb=1024),
    )
    assert result.memory_exceeded is True
    assert result.memory_kb == 2048
    assert result.infrastructure_error == ""
