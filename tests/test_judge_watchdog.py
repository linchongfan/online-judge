"""Tests for scripts/judge_watchdog.py (no admin rights required)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import judge_watchdog  # noqa: E402


def _make_config(tmp_path: Path, log_file: Path) -> judge_watchdog.WatchdogConfig:
    return judge_watchdog.WatchdogConfig(
        work_root=tmp_path / "judge-work",
        worker_pid_file=tmp_path / "logs" / "judge_worker.pid",
        watchdog_pid_file=tmp_path / "logs" / "watchdog.pid",
        python_exe=Path(sys.executable),
        worker_script=Path("scripts") / "run_judge_worker.py",
        max_mb=2048.0,
        max_age_seconds=3600,
        interval_seconds=30,
    )


@pytest.fixture
def watchdog_config(tmp_path: Path) -> tuple[judge_watchdog.WatchdogConfig, Path]:
    log_file = tmp_path / "logs" / "judge_watchdog.log"
    config = _make_config(tmp_path, log_file)
    config.work_root.mkdir(parents=True, exist_ok=True)
    config.worker_pid_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("judge_watchdog")
    logger.handlers.clear()
    judge_watchdog.setup_logging(log_file)
    return config, log_file


class TestCleanupStaleWorkDirs:
    def test_removes_old_dirs_and_keeps_new(self, watchdog_config: tuple) -> None:
        config, _ = watchdog_config
        old_dir = config.work_root / "old-submission"
        new_dir = config.work_root / "new-submission"
        old_dir.mkdir()
        new_dir.mkdir()
        old_time = time.time() - 7200
        os.utime(old_dir, (old_time, old_time))

        removed = judge_watchdog.cleanup_stale_work_dirs(config.work_root, config.max_age_seconds)

        assert removed == 1
        assert not old_dir.exists()
        assert new_dir.exists()

    def test_empty_root_returns_zero(self, watchdog_config: tuple) -> None:
        config, _ = watchdog_config
        assert judge_watchdog.cleanup_stale_work_dirs(config.work_root) == 0

    def test_missing_root_returns_zero(self, watchdog_config: tuple) -> None:
        config, _ = watchdog_config
        assert judge_watchdog.cleanup_stale_work_dirs(config.work_root / "does-not-exist") == 0


class TestWorkerRestart:
    def test_pid_file_missing_triggers_restart(self, watchdog_config: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
        config, _ = watchdog_config
        popen_calls: list[list[str]] = []

        class FakeProcess:
            pid = 4242

            def __init__(self, args: list[str], **kwargs: object) -> None:
                popen_calls.append([str(a) for a in args])

        monkeypatch.setattr(subprocess, "Popen", FakeProcess)

        status = judge_watchdog.check_worker(config)

        assert status == "started"
        assert len(popen_calls) == 1
        assert popen_calls[0][1].endswith("run_judge_worker.py")
        assert judge_watchdog.read_pid_file(config.worker_pid_file) == 4242

    def test_memory_over_threshold_restarts(self, watchdog_config: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
        config, _ = watchdog_config
        judge_watchdog.write_pid_file(config.worker_pid_file, 1234)
        popen_calls: list[list[str]] = []
        terminated: list[int] = []

        def fake_terminate(pid: int) -> bool:
            terminated.append(pid)
            return True

        class FakeProcess:
            pid = 5678

            def __init__(self, args: list[str], **kwargs: object) -> None:
                popen_calls.append([str(a) for a in args])

        monkeypatch.setattr(judge_watchdog, "process_executable_name", lambda pid: "python.exe")
        monkeypatch.setattr(judge_watchdog, "process_memory_mb", lambda pid: 3000.0)
        monkeypatch.setattr(judge_watchdog, "terminate_pid", fake_terminate)
        monkeypatch.setattr(subprocess, "Popen", FakeProcess)

        status = judge_watchdog.check_worker(config)

        assert status == "restarted"
        assert terminated == [1234]
        assert len(popen_calls) == 1
        assert judge_watchdog.read_pid_file(config.worker_pid_file) == 5678

    def test_healthy_worker_not_restarted(self, watchdog_config: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
        config, _ = watchdog_config
        judge_watchdog.write_pid_file(config.worker_pid_file, 1234)
        monkeypatch.setattr(judge_watchdog, "process_executable_name", lambda pid: "python.exe")
        monkeypatch.setattr(judge_watchdog, "process_memory_mb", lambda pid: 512.0)
        monkeypatch.setattr(
            subprocess,
            "Popen",
            lambda *args, **kwargs: pytest.fail("Popen should not be called for a healthy worker"),
        )

        assert judge_watchdog.check_worker(config) == "running"


class TestLogPrivacy:
    def test_log_does_not_leak_source_code_in_dir_names(self, watchdog_config: tuple) -> None:
        config, log_file = watchdog_config
        fake_code = "int main(){return 0;}"
        malicious_dir = config.work_root / fake_code
        malicious_dir.mkdir()
        old_time = time.time() - 7200
        os.utime(malicious_dir, (old_time, old_time))

        judge_watchdog.cleanup_stale_work_dirs(config.work_root)

        assert not malicious_dir.exists()
        assert log_file.exists()
        log_text = log_file.read_text(encoding="utf-8")
        assert fake_code not in log_text
        assert "int main" not in log_text

    def test_restart_log_does_not_leak_env_values(
        self, watchdog_config: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, log_file = watchdog_config
        monkeypatch.setenv("JUDGE_WATCHDOG_MAX_MB", "4096")
        monkeypatch.setattr(judge_watchdog, "process_executable_name", lambda pid: None)

        class FakeProcess:
            pid = 9999

            def __init__(self, args: list[str], **kwargs: object) -> None:
                pass

        monkeypatch.setattr(subprocess, "Popen", FakeProcess)
        judge_watchdog.check_worker(config)

        log_text = log_file.read_text(encoding="utf-8")
        assert "4096" not in log_text


class TestPidFileIO:
    def test_read_missing_pid_file(self, tmp_path: Path) -> None:
        assert judge_watchdog.read_pid_file(tmp_path / "nope.pid") is None

    def test_read_malformed_pid_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pid"
        bad.write_text("not-a-number", encoding="utf-8")
        assert judge_watchdog.read_pid_file(bad) is None

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "test.pid"
        judge_watchdog.write_pid_file(pid_file, 4321)
        assert judge_watchdog.read_pid_file(pid_file) == 4321
