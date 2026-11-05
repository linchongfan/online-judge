"""Bounded, timed subprocess execution used by compilation and test runs."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from .sandbox import (
    LocalSubprocessBackend,
    SandboxBackend,
    SandboxPolicy,
    SandboxTerminationReason,
)


class ProcessStartError(RuntimeError):
    """The operating system or isolation backend failed to start a process."""


@dataclass(frozen=True, slots=True)
class ProcessLimits:
    wall_timeout_ms: int
    output_limit_bytes: int
    memory_limit_kb: int | None = None

    def __post_init__(self) -> None:
        if self.wall_timeout_ms <= 0:
            raise ValueError("wall_timeout_ms must be positive")
        if self.output_limit_bytes < 0:
            raise ValueError("output_limit_bytes cannot be negative")
        if self.memory_limit_kb is not None and self.memory_limit_kb <= 0:
            raise ValueError("memory_limit_kb must be positive")


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int | None
    runtime_ms: int
    memory_kb: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_exceeded: bool = False
    memory_exceeded: bool = False
    infrastructure_error: str = ""


class ProcessRunner:
    """Run with wall/output supervision and process-tree cleanup.

    These controls are useful for tests but are not production resource
    isolation. Production policy requires a backend with hard-limit support.
    """

    def __init__(
        self,
        policy: SandboxPolicy,
        backend: SandboxBackend | None = None,
        *,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        self.policy = policy
        self.backend = LocalSubprocessBackend() if backend is None else backend
        self.poll_interval_seconds = poll_interval_seconds

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        stdin_data: bytes,
        limits: ProcessLimits,
    ) -> ProcessResult:
        if not argv:
            raise ValueError("argv cannot be empty")
        self.policy.ensure_execution_allowed(self.backend)
        backend = self.backend
        assert backend is not None  # Narrowed by ensure_execution_allowed.

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        start_new_session = os.name != "nt"
        with (
            tempfile.TemporaryFile(dir=cwd) as stdin_file,
            tempfile.TemporaryFile(dir=cwd) as stdout_file,
            tempfile.TemporaryFile(dir=cwd) as stderr_file,
        ):
            stdin_file.write(stdin_data)
            stdin_file.seek(0)
            process: subprocess.Popen[bytes] | None = None
            started = time.monotonic()
            timed_out = False
            output_exceeded = False
            memory_exceeded = False
            infrastructure_error = ""
            peak_memory_kb: int | None = None
            try:
                try:
                    process = backend.spawn(
                        argv=argv,
                        cwd=cwd,
                        env=env,
                        stdin=cast(BinaryIO, stdin_file),
                        stdout=cast(BinaryIO, stdout_file),
                        stderr=cast(BinaryIO, stderr_file),
                        creationflags=creationflags,
                        start_new_session=start_new_session,
                        limits=limits,
                    )
                except Exception as exc:
                    raise ProcessStartError(f"Unable to start process with {type(exc).__name__}: {exc}") from exc

                while process.poll() is None:
                    elapsed_ms = (time.monotonic() - started) * 1_000
                    if elapsed_ms >= limits.wall_timeout_ms:
                        timed_out = True
                        break
                    if (
                        self._combined_output_size(cast(BinaryIO, stdout_file), cast(BinaryIO, stderr_file))
                        > limits.output_limit_bytes
                    ):
                        output_exceeded = True
                        break
                    memory_kb = backend.memory_usage_kb(process)
                    if memory_kb is not None:
                        peak_memory_kb = max(peak_memory_kb or 0, memory_kb)
                        if limits.memory_limit_kb is not None and memory_kb > limits.memory_limit_kb:
                            memory_exceeded = True
                            break
                    time.sleep(self.poll_interval_seconds)

                # Output produced immediately before exit is still subject to the cap.
                if (
                    self._combined_output_size(cast(BinaryIO, stdout_file), cast(BinaryIO, stderr_file))
                    > limits.output_limit_bytes
                ):
                    output_exceeded = True

                if process.poll() is None and (timed_out or output_exceeded or memory_exceeded):
                    try:
                        backend.terminate(process)
                    except Exception as exc:
                        infrastructure_error = f"Process-tree termination failed with {type(exc).__name__}: {exc}"
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        infrastructure_error = infrastructure_error or (
                            "Process did not stop after backend termination; fallback kill was used."
                        )
                else:
                    process.wait()

                # Give an accounting backend one final opportunity to report peak usage.
                final_memory_kb = backend.memory_usage_kb(process)
                if final_memory_kb is not None:
                    peak_memory_kb = max(peak_memory_kb or 0, final_memory_kb)
                    if limits.memory_limit_kb is not None and final_memory_kb > limits.memory_limit_kb:
                        memory_exceeded = True
            finally:
                if process is not None:
                    if process.poll() is None:
                        try:
                            backend.terminate(process)
                            process.wait(timeout=5)
                        except Exception:
                            process.kill()
                            process.wait()
                    backend.cleanup(process)

            runtime_ms = max(0, round((time.monotonic() - started) * 1_000))
            info = backend.execution_info(process)
            if info.infrastructure_error and not infrastructure_error:
                infrastructure_error = info.infrastructure_error
            if info.peak_memory_kb is not None:
                peak_memory_kb = max(peak_memory_kb or 0, info.peak_memory_kb)
                if limits.memory_limit_kb is not None and info.peak_memory_kb > limits.memory_limit_kb:
                    memory_exceeded = True
            if info.runtime_ms is not None:
                runtime_ms = info.runtime_ms
            if info.wall_time_exceeded or info.termination_reason in (
                SandboxTerminationReason.WALL_TIME_LIMIT,
                SandboxTerminationReason.CPU_TIME_LIMIT,
            ):
                timed_out = True
            if info.memory_exceeded or info.termination_reason is SandboxTerminationReason.MEMORY_LIMIT:
                memory_exceeded = True
            if info.output_exceeded or info.termination_reason is SandboxTerminationReason.OUTPUT_LIMIT:
                output_exceeded = True
            stdout = self._read_bounded(cast(BinaryIO, stdout_file), limits.output_limit_bytes)
            stderr = self._read_bounded(cast(BinaryIO, stderr_file), limits.output_limit_bytes)
            return ProcessResult(
                exit_code=process.returncode if process is not None else None,
                runtime_ms=runtime_ms,
                memory_kb=peak_memory_kb,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                output_exceeded=output_exceeded,
                memory_exceeded=memory_exceeded,
                infrastructure_error=infrastructure_error,
            )

    @staticmethod
    def _combined_output_size(stdout: BinaryIO, stderr: BinaryIO) -> int:
        return os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size

    @staticmethod
    def _read_bounded(stream: BinaryIO, limit: int) -> bytes:
        stream.seek(0)
        return stream.read(limit + 1)
