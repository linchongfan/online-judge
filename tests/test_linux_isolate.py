"""Unit tests for the Linux isolate sandbox adapter.

These tests mock the isolate executable and the host-only setup checks. They
validate backend contracts and failure rollback without executing untrusted
code or requiring a configured Linux judge VM.
"""

from __future__ import annotations

import os
import types
from pathlib import Path
from typing import Any

import pytest

from judge.config import SANDBOX_BACKEND_ENV, JudgeConfig, ToolchainConfig
from judge.linux_isolate import META_ROOT_ENV, ROOTFS_ENV, LinuxIsolateBackend
from judge.process import ProcessLimits
from judge.sandbox import (
    IsolationCapabilities,
    SandboxConfigurationError,
    SandboxTerminationReason,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux-only backend")


@pytest.fixture
def toolchain(tmp_path: Path) -> ToolchainConfig:
    root = tmp_path / "toolchains"
    root.mkdir()
    paths = {}
    for name in ("gcc", "g++", "javac", "java", "python3"):
        path = root / f"{name}.bin"
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        paths[name] = path
    return ToolchainConfig(
        gcc_path=paths["gcc"],
        gxx_path=paths["g++"],
        javac_path=paths["javac"],
        java_path=paths["java"],
        user_python_path=paths["python3"],
    )


@pytest.fixture
def runtime_dirs(tmp_path: Path, toolchain: ToolchainConfig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    meta_root = tmp_path / "meta"
    meta_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    (cgroup_root / "cgroup.controllers").parent.mkdir(parents=True, exist_ok=True)
    (cgroup_root / "cgroup.controllers").write_text("cpu memory pids io\n", encoding="utf-8")
    (cgroup_root / "cgroup.subtree_control").write_text("", encoding="utf-8")
    isolate = tmp_path / "isolate"
    isolate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    monkeypatch.setattr("judge.linux_isolate.LinuxIsolateBackend._validate_cgroup_v2", lambda self: None)
    return {"rootfs": rootfs, "meta_root": meta_root, "isolate": isolate}


def _backend(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> LinuxIsolateBackend:
    env = {
        "JUDGE_ISOLATE_PATH": str(runtime_dirs["isolate"]),
        ROOTFS_ENV: str(runtime_dirs["rootfs"]),
        META_ROOT_ENV: str(runtime_dirs["meta_root"]),
        "JUDGE_TOOLCHAIN_ROOT": str(toolchain.gcc_path.parent),
    }
    return LinuxIsolateBackend(toolchain=toolchain, work_root=tmp_path, env=env)


def _stdio(tmp_path: Path) -> tuple[Any, Any, Any]:
    import tempfile

    stdin = tempfile.TemporaryFile(dir=tmp_path)
    stdout = tempfile.TemporaryFile(dir=tmp_path)
    stderr = tempfile.TemporaryFile(dir=tmp_path)
    return stdin, stdout, stderr


class _FakePopen:
    def __init__(self, pid: int, returncode: int | None = None):
        self.pid = pid
        self.returncode = returncode
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.killed = True
        self.returncode = -sig

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_capabilities_are_declared_only_for_real_backend_contract() -> None:
    backend = object.__new__(LinuxIsolateBackend)
    assert backend.capabilities == IsolationCapabilities(
        process_group_termination=True,
        hard_wall_time_limit=True,
        hard_output_limit=True,
        hard_memory_limit=True,
        filesystem_isolation=True,
        network_disabled=True,
        low_privilege=True,
    )


def test_rejects_non_posix_runtime(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("POSIX-only negative test")

    with pytest.raises(SandboxConfigurationError, match="POSIX"):
        LinuxIsolateBackend(toolchain=ToolchainConfig(), work_root=tmp_path, env={})


def test_maps_host_toolchain_paths_into_sandbox(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    assert backend._sandbox_argv([str(toolchain.gcc_path), "-std=c99", "Main.c"], tmp_path) == [
        "/toolchains/gcc.bin",
        "-std=c99",
        "Main.c",
    ]


def test_maps_case_directory_paths_into_sandbox_box(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    case_dir = tmp_path / "case-1"
    argv = backend._sandbox_argv([str(case_dir / "program"), "arg"], case_dir)
    assert argv == ["/box/program", "arg"]


def test_spawn_uses_isolate_with_expected_limits(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    calls: list[list[str]] = []
    processes: list[_FakePopen] = []

    def fake_run(argv: list[str], **kwargs: Any) -> types.SimpleNamespace:
        calls.append(argv)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakePopen:
        calls.append(argv)
        process = _FakePopen(pid=9000 + len(processes))
        processes.append(process)
        return process

    monkeypatch.setattr("judge.linux_isolate.subprocess.run", fake_run)
    monkeypatch.setattr("judge.linux_isolate.subprocess.Popen", fake_popen)
    monkeypatch.setattr(backend, "_allocate_box_id", lambda: 7)

    work_dir = tmp_path / "task"
    work_dir.mkdir()
    stdin, stdout, stderr = _stdio(tmp_path)
    process = backend.spawn(
        argv=[str(toolchain.user_python_path), "-I", "-B", "Main.py"],
        cwd=work_dir,
        env={"PATH": "/usr/bin:/bin", "SECRET_KEY": "must-not-pass"},
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=0,
        start_new_session=True,
        limits=ProcessLimits(wall_timeout_ms=2000, output_limit_bytes=4096, memory_limit_kb=65536),
    )

    assert process.pid == 9000
    init_call = calls[0]
    run_call = calls[1]
    assert init_call[:4] == [str(runtime_dirs["isolate"]), "--box-id", "7", "--init"]
    assert "--cg" in init_call
    assert any(arg.startswith("--quota=51200,4096") for arg in init_call)
    assert run_call[:4] == [str(runtime_dirs["isolate"]), "--box-id", "7", "--run"]
    assert "--cg" in run_call
    # Host system directories must never be visible: the default ruleset is
    # disabled and system dirs are sourced from the pinned rootfs instead.
    assert "--no-default-dirs" in run_call
    rootfs = runtime_dirs["rootfs"]
    for rule in (
        f"--dir=/box={work_dir}:rw",
        f"--dir=/bin={rootfs}/bin",
        f"--dir=/lib={rootfs}/lib",
        f"--dir=/usr={rootfs}/usr",
        f"--dir=/sbin={rootfs}/sbin:maybe",
        f"--dir=/etc={rootfs}/etc:maybe",
        f"--dir=/toolchains={toolchain.gcc_path.parent}",
        "--dir=/dev=/dev:dev",
        "--dir=/proc=proc:fs",
        "--dir=tmp:tmp",
    ):
        assert rule in run_call, rule
    # isolate 2.0 has no "ro" flag; binds are read-only by default.
    assert not any(arg.endswith(":ro") for arg in run_call)
    assert "--env=HOME=/box" in run_call
    assert "--env=PATH=/usr/bin:/bin" in run_call
    assert any(arg.startswith("--wall-time=2") for arg in run_call)
    assert any(arg.startswith("--processes=64") for arg in run_call)
    assert any(arg.startswith("--fsize=4") for arg in run_call)
    assert any(arg.startswith("--cg-mem=65536") for arg in run_call)
    # stdin/stdout/stderr are opened by isolate INSIDE the chrooted box, so the
    # command line must use /box paths; the host staging files live in the
    # task directory for the output proxy.
    assert "--stdin=/box/.judge-sandbox-stdin" in run_call
    assert "--stdout=/box/.judge-sandbox-stdout" in run_call
    assert "--stderr=/box/.judge-sandbox-stderr" in run_call
    # spawn stages stdin on the host; isolate creates the output files inside
    # the box at runtime.
    assert (work_dir / ".judge-sandbox-stdin").is_file()
    assert not (work_dir / ".judge-sandbox-stdout").exists()
    assert run_call[-5:] == ["--", "/toolchains/python3.bin", "-I", "-B", "Main.py"]


def _meta_state(backend: LinuxIsolateBackend, meta_root: Path, text: str) -> types.SimpleNamespace:
    state = types.SimpleNamespace(meta_file=meta_root / "meta.txt", proxy=None)
    state.meta_file.write_text(text, encoding="utf-8")
    return state


def test_meta_mapping_reports_time_limit_and_peak_memory(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    # Real isolate 2.0 key:value format — parsed, never mocked away.
    state = _meta_state(backend, runtime_dirs["meta_root"], "status:TO\ntime-wall:0.250\ncg-mem:12288\n")
    monkeypatch.setattr(backend, "_state_for", lambda process: state)

    info = backend.execution_info(_FakePopen(pid=123))
    assert info.termination_reason is SandboxTerminationReason.WALL_TIME_LIMIT
    assert info.wall_time_exceeded is True
    assert info.peak_memory_kb == 12288
    assert info.runtime_ms == 250


def test_meta_signal_status_maps_program_exit_code(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    state = _meta_state(backend, runtime_dirs["meta_root"], "status:SG\nexitsig:11\ntime:0.010\n")
    monkeypatch.setattr(backend, "_state_for", lambda process: state)

    info = backend.execution_info(_FakePopen(pid=124))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.exit_code == -11
    assert info.runtime_ms == 10


def test_meta_success_status_has_no_status_line(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    state = _meta_state(backend, runtime_dirs["meta_root"], "time:0.042\ntime-wall:0.100\ncg-mem:2048\nexitcode:0\n")
    monkeypatch.setattr(backend, "_state_for", lambda process: state)

    info = backend.execution_info(_FakePopen(pid=125))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.exit_code == 0
    assert info.runtime_ms == 42
    assert info.peak_memory_kb == 2048


def test_meta_oom_kill_maps_to_memory_limit(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    state = _meta_state(backend, runtime_dirs["meta_root"], "cg-mem:1048576\ncg-oom-killed:1\n")
    monkeypatch.setattr(backend, "_state_for", lambda process: state)

    info = backend.execution_info(_FakePopen(pid=126))
    assert info.memory_exceeded is True
    assert info.termination_reason is SandboxTerminationReason.MEMORY_LIMIT


def test_unknown_meta_status_is_sandbox_error_not_a_guess(
    tmp_path: Path,
    toolchain: ToolchainConfig,
    runtime_dirs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, toolchain, runtime_dirs, monkeypatch)
    state = _meta_state(backend, runtime_dirs["meta_root"], "status:??\n")
    monkeypatch.setattr(backend, "_state_for", lambda process: state)
    info = backend.execution_info(_FakePopen(pid=321))
    assert info.termination_reason is SandboxTerminationReason.SANDBOX_ERROR
    assert "isolate status=??" in info.infrastructure_error


def test_unknown_backend_name_still_fails_closed(tmp_path: Path) -> None:
    from judge.config import ToolchainConfigurationError

    with pytest.raises(ToolchainConfigurationError, match="isolate"):
        JudgeConfig.from_env({SANDBOX_BACKEND_ENV: "bubblewrap", "JUDGE_WORK_ROOT": str(tmp_path)})
