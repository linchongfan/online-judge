"""Unit tests for the Windows sandbox backend.

Every Win32 call is mocked at the ``_advapi32()`` / ``_kernel32()`` loader
boundary, so the suite runs on any Windows machine without administrator
rights, real restricted tokens, or real job objects. Harmful end-to-end
verification belongs in the acceptance script, not here.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from judge import windows_sandbox as ws
from judge.config import SANDBOX_BACKEND_ENV, JudgeConfig, ToolchainConfigurationError
from judge.process import ProcessLimits, ProcessRunner
from judge.sandbox import (
    IsolationCapabilities,
    LocalSubprocessBackend,
    SandboxConfigurationError,
    SandboxPolicy,
)
from judge.windows_sandbox import WindowsSandboxBackend

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only backend")

RESTRICTED_TOKEN_HANDLE = 222
SOURCE_TOKEN_HANDLE = 111
JOB_HANDLE = 500
PROCESS_HANDLE = 700
THREAD_HANDLE = 701
FAKE_PID = 4321
WINDOWS_FIREWALL_HINT = (
    "For the windows backend, run scripts/setup_judge_firewall.ps1 -Enable "
    "and set JUDGE_FIREWALL_ACTIVE=1."
)


def _write_handle(out: Any, value: int) -> None:
    ctypes.cast(out, ctypes.POINTER(ctypes.wintypes.HANDLE)).contents.value = value


def _write_dword(out: Any, value: int) -> None:
    ctypes.cast(out, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = value


def _successful_advapi32() -> types.SimpleNamespace:
    """Fake advapi32 implementing the happy path for every call the backend makes."""

    def open_process_token(process: int, access: int, out: Any) -> bool:
        _write_handle(out, SOURCE_TOKEN_HANDLE)
        return True

    def get_token_information(token: int, info_class: int, buffer: Any, size: int, out_size: Any) -> bool:
        if buffer is None:
            _write_dword(out_size, 128)
            return False
        if info_class == ws._TOKEN_USER:
            user = ctypes.cast(buffer, ctypes.POINTER(ws._TOKEN_USER)).contents
            user.User.Sid = ctypes.cast(8080, ctypes.POINTER(ctypes.c_byte))
            user.User.Attributes = 0
        else:
            groups = ctypes.cast(buffer, ctypes.POINTER(ws._TOKEN_GROUPS)).contents
            groups.GroupCount = 1
            groups.Groups[0].Sid = ctypes.cast(9090, ctypes.POINTER(ctypes.c_byte))
            groups.Groups[0].Attributes = ws._SE_GROUP_ENABLED
        _write_dword(out_size, 128)
        return True

    def create_restricted_token(
        token: int,
        flags: int,
        deleted_count: int,
        deleted_groups: Any,
        restricted_count: int,
        restricted_sids: Any,
        privilege_count: int,
        privileges: Any,
        out: Any,
    ) -> bool:
        assert flags == ws._DISABLE_MAX_PRIVILEGE
        assert deleted_count == 1  # one enabled, non-mandatory group is removed
        _write_handle(out, RESTRICTED_TOKEN_HANDLE)
        return True

    def allocate_and_initialize_sid(authority: Any, count: int, sub1: int, sub2: int, *rest: Any) -> bool:
        out = rest[-1]
        ctypes.cast(out, ctypes.POINTER(ctypes.wintypes.LPVOID)).contents.value = 7070
        return True

    def set_entries_in_acl(count: int, entries: Any, old_acl: Any, new_acl: Any) -> int:
        ctypes.cast(new_acl, ctypes.POINTER(ctypes.wintypes.LPVOID)).contents.value = 6060
        return 0

    def create_process_with_token(
        token: int,
        logon_flags: int,
        application: Any,
        command_line: Any,
        creation_flags: int,
        environment: Any,
        cwd: Any,
        startup_info: Any,
        process_information: Any,
    ) -> bool:
        info = ctypes.cast(process_information, ctypes.POINTER(ws._PROCESS_INFORMATION)).contents
        info.hProcess = PROCESS_HANDLE
        info.hThread = THREAD_HANDLE
        info.dwProcessId = FAKE_PID
        info.dwThreadId = 8
        return True

    return types.SimpleNamespace(
        OpenProcessToken=open_process_token,
        GetTokenInformation=get_token_information,
        CreateRestrictedToken=create_restricted_token,
        AllocateAndInitializeSid=allocate_and_initialize_sid,
        FreeSid=lambda sid: None,
        SetEntriesInAclW=set_entries_in_acl,
        SetNamedSecurityInfoW=lambda *args: 0,
        CreateProcessWithTokenW=create_process_with_token,
    )


def _successful_kernel32() -> types.SimpleNamespace:
    """Fake kernel32 implementing the happy path, with call recording."""
    return types.SimpleNamespace(
        GetCurrentProcess=lambda: 100,
        CloseHandle=lambda handle: True,
        TerminateProcess=lambda handle, code: True,
        CreateJobObjectW=lambda security_attributes, name: JOB_HANDLE,
        SetInformationJobObject=lambda job, info_class, info, size: True,
        QueryInformationJobObject=lambda *args: True,
        AssignProcessToJobObject=lambda job, process: True,
        TerminateJobObject=lambda job, code: True,
        SetHandleInformation=lambda handle, mask, flags: True,
        LocalFree=lambda pointer: None,
    )


@pytest.fixture
def win32_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[types.SimpleNamespace, types.SimpleNamespace]:
    advapi32 = _successful_advapi32()
    kernel32 = _successful_kernel32()
    monkeypatch.setattr(ws, "_advapi32", lambda: advapi32)
    monkeypatch.setattr(ws, "_kernel32", lambda: kernel32)
    return advapi32, kernel32


class _FakeProcess:
    """Minimal stand-in for Popen exposing only what the backend uses."""

    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self._returncode = 1


@pytest.fixture
def stdio_files(tmp_path: Path) -> Iterator[tuple[Any, Any, Any]]:
    with (
        tempfile.TemporaryFile(dir=tmp_path) as stdin_file,
        tempfile.TemporaryFile(dir=tmp_path) as stdout_file,
        tempfile.TemporaryFile(dir=tmp_path) as stderr_file,
    ):
        yield stdin_file, stdout_file, stderr_file


def _spawn(
    backend: WindowsSandboxBackend,
    work_dir: Path,
    stdio: tuple[Any, Any, Any],
    limits: ProcessLimits | None = None,
) -> subprocess.Popen[bytes]:
    return backend.spawn(
        argv=["prog.exe", "arg"],
        cwd=work_dir,
        env={"PATH": r"C:\Windows"},
        stdin=stdio[0],
        stdout=stdio[1],
        stderr=stdio[2],
        creationflags=0,
        start_new_session=False,
        limits=limits,
    )


# ---------------------------------------------------------------- capabilities


def test_capabilities_declaration_matches_implementation() -> None:
    backend = WindowsSandboxBackend(work_root=Path("C:/judge-work"))
    assert backend.capabilities == IsolationCapabilities(
        process_group_termination=True,
        hard_wall_time_limit=True,
        hard_output_limit=True,
        hard_memory_limit=True,
        filesystem_isolation=True,
        network_disabled=False,
        low_privilege=True,
    )
    # Every claimed capability has a matching code path.
    assert callable(backend.terminate)  # process_group_termination via TerminateJobObject
    info = ws._JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    assert hasattr(info.BasicLimitInformation, "PerProcessUserTimeLimit")  # hard_wall_time_limit
    assert hasattr(info, "ProcessMemoryLimit")  # hard_memory_limit
    assert hasattr(info, "PeakProcessMemoryUsed")  # memory accounting
    assert hasattr(ProcessRunner, "_combined_output_size")  # hard_output_limit
    assert hasattr(backend, "_tighten_directory_acl")  # filesystem_isolation
    assert hasattr(backend, "_create_restricted_token")  # low_privilege
    assert hasattr(ws, "_SECURITY_ATTRIBUTES")
    assert hasattr(ws, "_STARTUPINFOW")
    assert hasattr(ws, "_PROCESS_INFORMATION")
    # Network is deliberately delegated, never claimed.
    assert backend.capabilities.network_disabled is False


def test_missing_production_capabilities_remains_backward_compatible() -> None:
    missing = IsolationCapabilities().missing_production_capabilities()
    assert "network_disabled" in missing
    assert "hard_memory_limit" in missing


def test_create_job_sets_hard_time_and_memory_limits(
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
) -> None:
    backend = WindowsSandboxBackend(work_root=Path("C:/judge-work"))
    captured: dict[str, Any] = {}

    def set_information(job: int, info_class: int, info: Any, size: int) -> bool:
        # Copy the bytes: ``info`` points at a stack struct that is freed once
        # _create_job returns, so a live POINTER.contents view would dangle.
        captured["info"] = ws._JOBOBJECT_EXTENDED_LIMIT_INFORMATION.from_buffer_copy(ctypes.string_at(info, size))
        return True

    win32_mocks[1].SetInformationJobObject = set_information
    job = backend._create_job(ProcessLimits(wall_timeout_ms=2_000, output_limit_bytes=64, memory_limit_kb=1_024))
    assert job == JOB_HANDLE
    info = captured["info"]
    flags = info.BasicLimitInformation.LimitFlags
    assert flags & ws._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert flags & ws._JOB_OBJECT_LIMIT_PROCESS_TIME
    assert flags & ws._JOB_OBJECT_LIMIT_PROCESS_MEMORY
    assert info.BasicLimitInformation.PerProcessUserTimeLimit == 2_000 * 10_000  # 100-ns units
    assert info.ProcessMemoryLimit == 1_024 * 1024


# ------------------------------------------------------------- policy/config


def test_production_rejects_default_local_backend(tmp_path: Path) -> None:
    config = JudgeConfig.from_env({"JUDGE_ENV": "production", "JUDGE_WORK_ROOT": str(tmp_path)})
    assert config.sandbox_backend is None
    with pytest.raises(SandboxConfigurationError, match="Production execution refused") as error:
        SandboxPolicy.production().ensure_execution_allowed(LocalSubprocessBackend())
    message = str(error.value)
    assert "network_disabled" in message
    assert "low_privilege" in message
    assert "hard_memory_limit" in message


def test_production_windows_backend_without_firewall_is_refused(tmp_path: Path) -> None:
    config = JudgeConfig.from_env(
        {"JUDGE_ENV": "production", SANDBOX_BACKEND_ENV: "windows", "JUDGE_WORK_ROOT": str(tmp_path)}
    )
    backend = config.sandbox_backend
    assert isinstance(backend, WindowsSandboxBackend)
    with pytest.raises(SandboxConfigurationError) as error:
        SandboxPolicy.production().ensure_execution_allowed(backend)
    assert "network_disabled" in str(error.value)
    assert "host firewall" in str(error.value)


def test_windows_backend_can_supply_network_configuration_hint(tmp_path: Path) -> None:
    config = JudgeConfig.from_env(
        {"JUDGE_ENV": "production", SANDBOX_BACKEND_ENV: "windows", "JUDGE_WORK_ROOT": str(tmp_path)}
    )
    backend = config.sandbox_backend
    assert isinstance(backend, WindowsSandboxBackend)
    policy = SandboxPolicy.production(
        network_source="host firewall (JUDGE_FIREWALL_ACTIVE)",
        network_hint=WINDOWS_FIREWALL_HINT,
    )
    with pytest.raises(SandboxConfigurationError) as error:
        policy.ensure_execution_allowed(backend)
    assert "JUDGE_FIREWALL_ACTIVE" in str(error.value)
    assert "setup_judge_firewall.ps1" in str(error.value)


def test_production_windows_backend_with_firewall_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_FIREWALL_ACTIVE", "1")
    config = JudgeConfig.from_env(
        {"JUDGE_ENV": "production", SANDBOX_BACKEND_ENV: "windows", "JUDGE_WORK_ROOT": str(tmp_path)}
    )
    backend = config.sandbox_backend
    assert isinstance(backend, WindowsSandboxBackend)
    assert backend.firewall_configured() is True
    policy = SandboxPolicy.production(
        network_source="host firewall (JUDGE_FIREWALL_ACTIVE)",
        network_hint=WINDOWS_FIREWALL_HINT,
    )
    policy.ensure_execution_allowed(backend)  # Must not raise.


def test_unknown_sandbox_backend_name_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolchainConfigurationError, match=SANDBOX_BACKEND_ENV):
        JudgeConfig.from_env({SANDBOX_BACKEND_ENV: "bubblewrap", "JUDGE_WORK_ROOT": str(tmp_path)})


def test_firewall_configured_reads_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = WindowsSandboxBackend()
    monkeypatch.delenv("JUDGE_FIREWALL_ACTIVE", raising=False)
    assert backend.firewall_configured() is False
    monkeypatch.setenv("JUDGE_FIREWALL_ACTIVE", "0")
    assert backend.firewall_configured() is False
    monkeypatch.setenv("JUDGE_FIREWALL_ACTIVE", "1")
    assert backend.firewall_configured() is True


# -------------------------------------------------------------------- spawn


def test_spawn_success_path_registers_job_and_terminates_tree(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    backend = WindowsSandboxBackend(work_root=tmp_path)
    closed: list[int] = []
    terminated_jobs: list[tuple[int, int]] = []

    def close_handle(handle: Any) -> bool:
        closed.append(int(handle or 0))
        return True

    def terminate_job_object(job: Any, code: Any) -> bool:
        terminated_jobs.append((int(job), int(code)))
        return True

    win32_mocks[1].CloseHandle = close_handle
    win32_mocks[1].TerminateJobObject = terminate_job_object

    popen = _spawn(backend, work_dir, stdio_files)
    assert popen.pid == FAKE_PID
    assert popen.args == ["prog.exe", "arg"]
    assert backend._jobs[FAKE_PID] == JOB_HANDLE
    # The source token and the thread handle are released after spawn.
    assert RESTRICTED_TOKEN_HANDLE in closed
    assert THREAD_HANDLE in closed

    process = _FakeProcess(FAKE_PID)
    backend.terminate(cast("subprocess.Popen[bytes]", process))
    assert terminated_jobs == [(JOB_HANDLE, 1)]
    backend.cleanup(cast("subprocess.Popen[bytes]", process))
    assert JOB_HANDLE in closed
    assert FAKE_PID not in backend._jobs


def test_spawn_refuses_cwd_outside_work_root(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    work_root = tmp_path / "work-root"
    work_root.mkdir()
    backend = WindowsSandboxBackend(work_root=work_root)
    with pytest.raises(SandboxConfigurationError, match="JUDGE_WORK_ROOT"):
        _spawn(backend, outside, stdio_files)


def test_spawn_raises_configuration_error_when_token_creation_fails(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    win32_mocks[0].OpenProcessToken = lambda process, access, out: False
    backend = WindowsSandboxBackend(work_root=tmp_path)
    with pytest.raises(SandboxConfigurationError, match="OpenProcessToken"):
        _spawn(backend, work_dir, stdio_files)


def test_spawn_raises_configuration_error_when_restricted_token_fails(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    win32_mocks[0].CreateRestrictedToken = lambda *args: False
    backend = WindowsSandboxBackend(work_root=tmp_path)
    with pytest.raises(SandboxConfigurationError, match="CreateRestrictedToken"):
        _spawn(backend, work_dir, stdio_files)


def test_spawn_raises_configuration_error_when_job_creation_fails(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    win32_mocks[1].CreateJobObjectW = lambda security_attributes, name: None
    backend = WindowsSandboxBackend(work_root=tmp_path)
    with pytest.raises(SandboxConfigurationError, match="CreateJobObjectW"):
        _spawn(backend, work_dir, stdio_files)


def test_spawn_raises_configuration_error_when_process_creation_fails(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    closed: list[int] = []
    win32_mocks[0].CreateProcessWithTokenW = lambda *args: False

    def close_handle(handle: Any) -> bool:
        closed.append(int(handle or 0))
        return True

    win32_mocks[1].CloseHandle = close_handle
    backend = WindowsSandboxBackend(work_root=tmp_path)
    with pytest.raises(SandboxConfigurationError, match="CreateProcessWithTokenW"):
        _spawn(backend, work_dir, stdio_files)
    # The job handle must be released instead of leaking after the failure.
    assert JOB_HANDLE in closed


def test_spawn_raises_and_kills_process_when_job_assignment_fails(
    tmp_path: Path,
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
    stdio_files: tuple[Any, Any, Any],
) -> None:
    work_dir = tmp_path / "case1"
    work_dir.mkdir()
    terminated: list[tuple[int, int]] = []
    closed: list[int] = []
    win32_mocks[1].AssignProcessToJobObject = lambda job, process: False

    def terminate_process(handle: Any, code: Any) -> bool:
        terminated.append((int(handle), int(code)))
        return True

    def close_handle(handle: Any) -> bool:
        closed.append(int(handle or 0))
        return True

    win32_mocks[1].TerminateProcess = terminate_process
    win32_mocks[1].CloseHandle = close_handle
    backend = WindowsSandboxBackend(work_root=tmp_path)
    with pytest.raises(SandboxConfigurationError, match="AssignProcessToJobObject"):
        _spawn(backend, work_dir, stdio_files)
    assert terminated == [(PROCESS_HANDLE, 1)]
    assert PROCESS_HANDLE in closed
    assert THREAD_HANDLE in closed
    assert JOB_HANDLE in closed


def test_memory_usage_kb_reads_job_peak_process_memory(
    win32_mocks: tuple[types.SimpleNamespace, types.SimpleNamespace],
) -> None:
    def query_information(job: int, info_class: int, info: Any, size: int, return_length: Any) -> bool:
        captured = ctypes.cast(info, ctypes.POINTER(ws._JOBOBJECT_EXTENDED_LIMIT_INFORMATION)).contents
        captured.PeakProcessMemoryUsed = 2_048 * 1024
        return True

    win32_mocks[1].QueryInformationJobObject = query_information
    backend = WindowsSandboxBackend()
    process = _FakeProcess(FAKE_PID)
    backend._jobs[FAKE_PID] = JOB_HANDLE
    assert backend.memory_usage_kb(cast("subprocess.Popen[bytes]", process)) == 2_048


def test_terminate_falls_back_to_popen_terminate_without_job() -> None:
    backend = WindowsSandboxBackend()
    process = _FakeProcess(9999)
    backend.terminate(cast("subprocess.Popen[bytes]", process))
    assert process.poll() == 1
