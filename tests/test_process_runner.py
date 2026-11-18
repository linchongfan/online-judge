"""Process-runner lifecycle regressions (cross-platform).

These pin the exact ordering and signalling contracts between the runner and
sandbox backends; the Linux isolate backend depends on all of them.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

from judge.linux_isolate import LinuxIsolateBackend, _OutputProxy
from judge.process import ProcessLimits, ProcessRunner
from judge.sandbox import (
    LocalSubprocessBackend,
    SandboxExecutionInfo,
    SandboxPolicy,
    SandboxTerminationReason,
)


class _OrderRecordingBackend(LocalSubprocessBackend):
    """Records backend call order; simulates state released by cleanup()."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state_deleted = False

    def cleanup(self, process: subprocess.Popen[bytes]) -> None:
        self.calls.append("cleanup")
        self.state_deleted = True

    def execution_info(self, process: subprocess.Popen[bytes]) -> SandboxExecutionInfo:
        if self.state_deleted:
            raise RuntimeError("sandbox state already deleted by cleanup")
        self.calls.append("execution_info")
        return SandboxExecutionInfo()


def test_execution_info_is_collected_before_cleanup(tmp_path: Path) -> None:
    backend = _OrderRecordingBackend()
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True), backend)
    result = runner.run(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        env=dict(os.environ),
        stdin_data=b"",
        limits=ProcessLimits(wall_timeout_ms=5_000, output_limit_bytes=4096),
    )
    assert result.exit_code == 0
    assert backend.calls == ["execution_info", "cleanup"]


class _TrippedOutputBackend(LocalSubprocessBackend):
    """Simulates a supervising backend whose hard output cap tripped."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._event.set()

    def spawn(self, **kwargs):
        process = super().spawn(**kwargs)
        return process

    def output_stop_event(self, process: subprocess.Popen[bytes]) -> threading.Event:
        return self._event


def test_runner_terminates_when_backend_output_cap_trips(tmp_path: Path) -> None:
    backend = _TrippedOutputBackend()
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True), backend)
    started = time.monotonic()
    result = runner.run(
        # Writes nothing on the runner-visible pipes; the tripped backend event
        # must still stop the supervised sleep immediately.
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env=dict(os.environ),
        stdin_data=b"",
        limits=ProcessLimits(wall_timeout_ms=30_000, output_limit_bytes=4096),
    )
    elapsed = time.monotonic() - started
    assert result.output_exceeded is True
    assert result.timed_out is False
    assert elapsed < 10, f"run was not terminated promptly: {elapsed:.1f}s"


class _RecordingProxy:
    """Proxy stub that records whether finish() ran before snapshot()."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._finished = False

    def finish(self, timeout_seconds: float = 5.0) -> None:
        self._finished = True
        self.calls.append("finish")

    def snapshot(self) -> tuple[bool, str]:
        self.calls.append("snapshot")
        return False, ""


def _backend_for_state(state: types.SimpleNamespace) -> LinuxIsolateBackend:
    backend = object.__new__(LinuxIsolateBackend)
    backend._state_for = lambda process: state  # type: ignore[method-assign]
    return backend


def test_execution_info_drains_proxy_before_snapshot(tmp_path: Path) -> None:
    meta = tmp_path / "meta.txt"
    meta.write_text("exitcode:0\n", encoding="utf-8")
    proxy = _RecordingProxy()
    state = types.SimpleNamespace(meta_file=meta, proxy=proxy, isolate=types.SimpleNamespace(returncode=0))
    info = _backend_for_state(state).execution_info(types.SimpleNamespace(pid=1))
    assert proxy.calls == ["finish", "snapshot"]
    assert info.exit_code == 0


def test_execution_info_catches_output_limit_detected_only_at_finish(tmp_path: Path) -> None:
    # The pump may not have processed the file at all before execution_info
    # runs; finishing the proxy inside execution_info must surface the cap.
    meta = tmp_path / "meta.txt"
    meta.write_text("exitcode:0\n", encoding="utf-8")
    out = tmp_path / "out"
    out.write_bytes(b"x" * 65536)
    err = tmp_path / "err"
    err.write_bytes(b"")
    proxy = _OutputProxy(
        stdout=io.BytesIO(),
        stderr=io.BytesIO(),
        limit_bytes=16,
        stop_event=threading.Event(),
    )
    proxy.start({"stdout": out, "stderr": err})
    state = types.SimpleNamespace(meta_file=meta, proxy=proxy, isolate=types.SimpleNamespace(returncode=0))
    info = _backend_for_state(state).execution_info(types.SimpleNamespace(pid=4))
    assert info.output_exceeded is True


def test_meta_missing_after_runner_requested_kill_is_neutral(tmp_path: Path) -> None:
    meta = tmp_path / "meta.txt"
    meta.write_text("", encoding="utf-8")  # empty -> parsed as missing
    state = types.SimpleNamespace(
        meta_file=meta,
        proxy=None,
        isolate=types.SimpleNamespace(returncode=-9),
        termination_requested=True,
    )
    info = _backend_for_state(state).execution_info(types.SimpleNamespace(pid=2))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.infrastructure_error == ""


def test_meta_missing_after_external_sigkill_fails_closed(tmp_path: Path) -> None:
    # A negative exit code WITHOUT our terminate() must not be treated as an
    # expected kill: external SIGKILLs and supervisor crashes become SE.
    meta = tmp_path / "meta.txt"
    meta.write_text("", encoding="utf-8")
    state = types.SimpleNamespace(
        meta_file=meta,
        proxy=None,
        isolate=types.SimpleNamespace(returncode=-9),
        termination_requested=False,
    )
    info = _backend_for_state(state).execution_info(types.SimpleNamespace(pid=3))
    assert info.termination_reason is SandboxTerminationReason.SANDBOX_ERROR
    assert "meta file missing" in info.infrastructure_error


class _LateOutputBackend(LocalSubprocessBackend):
    """Appends output to the runner's stream during execution_info() — the
    supervising-proxy drain happens there, so the runner's final cap check
    must run afterwards."""

    def __init__(self, tail: bytes) -> None:
        self._tail = tail
        self._stream = None

    def spawn(self, *, stdout, **kwargs):
        self._stream = stdout
        return super().spawn(stdout=stdout, **kwargs)

    def execution_info(self, process: subprocess.Popen[bytes]) -> SandboxExecutionInfo:
        assert self._stream is not None
        self._stream.seek(0, os.SEEK_END)
        self._stream.write(self._tail)
        self._stream.flush()
        return SandboxExecutionInfo()


def test_runner_rechecks_output_cap_after_backend_accounting(tmp_path: Path) -> None:
    backend = _LateOutputBackend(tail=b"x" * 8192)
    runner = ProcessRunner(SandboxPolicy.development(allow_unsafe_tests=True), backend)
    result = runner.run(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        env=dict(os.environ),
        stdin_data=b"",
        limits=ProcessLimits(wall_timeout_ms=5_000, output_limit_bytes=4096),
    )
    assert result.output_exceeded is True


def test_isolate_cleanup_uses_cg_and_records_failures(tmp_path: Path) -> None:
    # The pinned isolate v2.0 only removes the per-run cgroup when --cleanup
    # is accompanied by --cg; failures must be recorded, not swallowed.
    from unittest.mock import patch

    backend = object.__new__(LinuxIsolateBackend)
    backend._isolate_path = Path("/usr/bin/isolate")

    state = types.SimpleNamespace(cleanup_started=False, box_id=7, cleanup_error="")
    with patch("judge.linux_isolate.subprocess.run") as run:
        run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        backend._isolate_cleanup(state)  # type: ignore[arg-type]
        argv = run.call_args.args[0]
    assert argv == [str(Path("/usr/bin/isolate")), "--box-id", "7", "--cleanup", "--cg"]
    assert state.cleanup_error == ""


def test_isolate_cleanup_records_nonzero_exit(tmp_path: Path) -> None:
    from unittest.mock import patch

    backend = object.__new__(LinuxIsolateBackend)
    backend._isolate_path = Path("/usr/bin/isolate")
    state = types.SimpleNamespace(cleanup_started=False, box_id=8, cleanup_error="")
    with patch("judge.linux_isolate.subprocess.run") as run:
        run.return_value = types.SimpleNamespace(returncode=1, stdout="", stderr="box busy")
        backend._isolate_cleanup(state)  # type: ignore[arg-type]
    assert "exited with 1" in state.cleanup_error
    assert "box busy" in state.cleanup_error


def test_isolate_cleanup_records_start_failure(tmp_path: Path) -> None:
    from unittest.mock import patch

    backend = object.__new__(LinuxIsolateBackend)
    backend._isolate_path = Path("/usr/bin/isolate")
    state = types.SimpleNamespace(cleanup_started=False, box_id=9, cleanup_error="")
    with patch("judge.linux_isolate.subprocess.run", side_effect=OSError("no such file")):
        backend._isolate_cleanup(state)  # type: ignore[arg-type]
    assert "OSError" in state.cleanup_error


def test_isolate_disk_quota_requires_explicit_tmpfs_opt_out() -> None:
    from unittest.mock import patch

    backend = object.__new__(LinuxIsolateBackend)
    backend._isolate_path = Path("/usr/bin/isolate")
    backend._disable_disk_quota = True
    with patch("judge.linux_isolate.subprocess.run") as run:
        run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        backend._init_box(10, 51200, 4096)
        argv = run.call_args.args[0]
    assert not any(str(arg).startswith("--quota=") for arg in argv)

    backend._disable_disk_quota = False
    with patch("judge.linux_isolate.subprocess.run") as run:
        run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        backend._init_box(10, 51200, 4096)
        argv = run.call_args.args[0]
    assert "--quota=51200,4096" in argv
