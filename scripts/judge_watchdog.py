"""Watchdog for the local judge Celery worker (Windows, Python 3.12, stdlib only).

Responsibilities:
- Detect a dead/missing judge worker via ``logs/judge_worker.pid`` and restart it.
- Detect excessive worker memory usage and restart the worker.
- Periodically purge stale subdirectories under ``JUDGE_WORK_ROOT`` (default
  ``./data/judge-work``) older than one hour.

The log file (``logs/judge_watchdog.log``) intentionally records only counts,
PIDs and decisions -- never directory names, source code, test data or
environment variable values.

Usage:
    python scripts/judge_watchdog.py start
    python scripts/judge_watchdog.py stop
    python scripts/judge_watchdog.py status
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import logging
import logging.handlers
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "judge_watchdog.log"
WATCHDOG_PID_FILE = LOGS_DIR / "watchdog.pid"
DEFAULT_WORKER_PID_FILE = LOGS_DIR / "judge_worker.pid"
DEFAULT_WORK_ROOT = PROJECT_ROOT / "data" / "judge-work"
DEFAULT_PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "run_judge_worker.py"

DEFAULT_MAX_MB = 2048.0
DEFAULT_MAX_AGE_SECONDS = 3600
DEFAULT_INTERVAL_SECONDS = 30

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259

_is_windows = sys.platform == "win32"
_kernel32: ctypes.WinDLL | None = None
_psapi: ctypes.WinDLL | None = None

if _is_windows:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    _kernel32.GetExitCodeProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    _psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]

try:  # optional fallback, not required
    import psutil  # type: ignore[import-not-found,import-untyped]
except ImportError:  # pragma: no cover - depends on local environment
    psutil = None  # type: ignore[assignment]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class WatchdogConfig:
    """Paths and thresholds for one watchdog run. All values are injectable for tests."""

    work_root: Path = DEFAULT_WORK_ROOT
    worker_pid_file: Path = DEFAULT_WORKER_PID_FILE
    watchdog_pid_file: Path = WATCHDOG_PID_FILE
    python_exe: Path = DEFAULT_PYTHON_EXE
    worker_script: Path = WORKER_SCRIPT
    max_mb: float = DEFAULT_MAX_MB
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS


def build_config() -> WatchdogConfig:
    """Build runtime config from environment (values are never logged)."""

    def _env_path(name: str, default: Path) -> Path:
        raw = os.environ.get(name)
        return Path(raw) if raw else default

    def _env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    python_exe = DEFAULT_PYTHON_EXE if DEFAULT_PYTHON_EXE.is_file() else Path(sys.executable)
    return WatchdogConfig(
        work_root=_env_path("JUDGE_WORK_ROOT", DEFAULT_WORK_ROOT),
        max_mb=_env_float("JUDGE_WATCHDOG_MAX_MB", DEFAULT_MAX_MB),
        interval_seconds=_env_int("JUDGE_WATCHDOG_INTERVAL", DEFAULT_INTERVAL_SECONDS),
        python_exe=python_exe,
    )


def setup_logging(log_file: Path = LOG_FILE) -> logging.Logger:
    logger = logging.getLogger("judge_watchdog")
    if logger.handlers:
        return logger
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Process helpers (ctypes first, psutil as optional fallback)
# ---------------------------------------------------------------------------


def _open_process(pid: int, access: int) -> int | None:
    if not (_is_windows and _kernel32 is not None):
        return None
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        return None
    return int(handle)


def process_executable_name(pid: int) -> str | None:
    """Return the lowercased executable basename for ``pid``, or None if unknown."""

    handle = _open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is not None and _kernel32 is not None:
        try:
            size = ctypes.wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name.lower()
        finally:
            _kernel32.CloseHandle(handle)
    if psutil is not None:
        try:
            return Path(psutil.Process(pid).exe()).name.lower()
        except Exception:  # noqa: BLE001 - any psutil failure means "unknown"
            return None
    return None


def process_memory_mb(pid: int) -> float | None:
    """Return private memory usage of ``pid`` in MB, or None if unavailable."""

    handle = _open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is not None and _psapi is not None and _kernel32 is not None:
        try:
            counters = _PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
            if _psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return float(counters.PrivateUsage) / (1024.0 * 1024.0)
        finally:
            _kernel32.CloseHandle(handle)
    if psutil is not None:
        try:
            return float(psutil.Process(pid).memory_info().vms) / (1024.0 * 1024.0)
        except Exception:  # noqa: BLE001
            return None
    return None


def process_alive(pid: int) -> bool:
    """Best-effort check that ``pid`` refers to a live process."""

    handle = _open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is not None and _kernel32 is not None:
        try:
            exit_code = ctypes.wintypes.DWORD(0)
            if _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return int(exit_code.value) == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid(pid: int) -> bool:
    """Terminate ``pid`` (TerminateProcess on Windows, SIGTERM elsewhere)."""

    handle = _open_process(pid, _PROCESS_TERMINATE)
    if handle is not None and _kernel32 is not None:
        try:
            return bool(_kernel32.TerminateProcess(handle, 1))
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def read_pid_file(path: Path) -> int | None:
    """Read a PID from ``path``; return None when missing or malformed."""

    try:
        text = path.read_text(encoding="utf-8").strip()
        pid = int(text)
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Work-root cleanup and worker (re)start
# ---------------------------------------------------------------------------


def cleanup_stale_work_dirs(
    root: Path, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS, now: float | None = None
) -> int:
    """Remove subdirectories of ``root`` whose mtime is older than ``max_age_seconds``.

    Logs only aggregate counts -- never directory names or contents.
    """

    logger = logging.getLogger("judge_watchdog")
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    if now is None:
        now = time.time()
    removed = 0
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            if now - entry.stat().st_mtime <= max_age_seconds:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    if removed:
        logger.info("cleanup: removed %d stale work directories (age>%ds)", removed, max_age_seconds)
    return removed


def start_worker(config: WatchdogConfig) -> subprocess.Popen[bytes]:
    """Launch the judge worker and record its PID in the worker PID file."""

    logger = logging.getLogger("judge_watchdog")
    process = subprocess.Popen(
        [str(config.python_exe), str(config.worker_script)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    write_pid_file(config.worker_pid_file, process.pid)
    logger.info("worker started: pid=%d", process.pid)
    return process


def restart_worker(config: WatchdogConfig) -> str:
    """Start a fresh worker process and persist its PID."""

    start_worker(config)
    return "restarted"


def check_worker(config: WatchdogConfig) -> str:
    """One worker health check: start / restart / memory-kill as needed.

    Returns a short status string: "started", "restarted" or "running".
    """

    logger = logging.getLogger("judge_watchdog")
    pid = read_pid_file(config.worker_pid_file)
    if pid is None:
        logger.info("worker pid file missing; assuming worker is not running")
        cleanup_stale_work_dirs(config.work_root, config.max_age_seconds)
        restart_worker(config)
        return "started"

    exe = process_executable_name(pid)
    if exe is None or exe != "python.exe":
        logger.info("worker pid=%d is gone or not python.exe (exe=%r); restarting", pid, exe)
        cleanup_stale_work_dirs(config.work_root, config.max_age_seconds)
        restart_worker(config)
        return "restarted"

    memory_mb = process_memory_mb(pid)
    if memory_mb is not None and memory_mb > config.max_mb:
        logger.info(
            "worker pid=%d memory %.0f MB exceeds threshold %.0f MB; terminating and restarting",
            pid,
            memory_mb,
            config.max_mb,
        )
        terminate_pid(pid)
        restart_worker(config)
        return "restarted"

    return "running"


def watchdog_tick(config: WatchdogConfig) -> str:
    """One full watchdog iteration: worker check plus defensive work-root scan."""

    status = check_worker(config)
    cleanup_stale_work_dirs(config.work_root, config.max_age_seconds)
    return status


# ---------------------------------------------------------------------------
# CLI: start / stop / status
# ---------------------------------------------------------------------------


def cmd_start(config: WatchdogConfig) -> int:
    logger = setup_logging()
    stop_requested = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info("watchdog received signal %d; stopping", signum)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    write_pid_file(config.watchdog_pid_file, os.getpid())
    logger.info(
        "watchdog started: pid=%d interval=%ds max_mb=%.0f", os.getpid(), config.interval_seconds, config.max_mb
    )
    try:
        while not stop_requested:
            try:
                watchdog_tick(config)
            except Exception:  # noqa: BLE001 - the watchdog must never die silently
                logger.exception("watchdog tick failed")
            deadline = time.monotonic() + config.interval_seconds
            while not stop_requested and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
    finally:
        try:
            config.watchdog_pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        logger.info("watchdog stopped: pid=%d", os.getpid())
    return 0


def cmd_stop(config: WatchdogConfig) -> int:
    pid = read_pid_file(config.watchdog_pid_file)
    if pid is None:
        print("watchdog is not running (no pid file)")
        return 1
    if not process_alive(pid):
        print(f"watchdog pid {pid} is not alive; removing stale pid file")
        try:
            config.watchdog_pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        return 1
    if terminate_pid(pid):
        print(f"watchdog stop signal sent to pid {pid}")
        return 0
    print(f"failed to terminate watchdog pid {pid}")
    return 2


def cmd_status(config: WatchdogConfig) -> int:
    watchdog_pid = read_pid_file(config.watchdog_pid_file)
    watchdog_running = watchdog_pid is not None and process_alive(watchdog_pid)
    if watchdog_running:
        print(f"watchdog: running (pid {watchdog_pid})")
    else:
        print("watchdog: not running")

    worker_pid = read_pid_file(config.worker_pid_file)
    if worker_pid is None:
        print("worker: not running (no pid file)")
    else:
        exe = process_executable_name(worker_pid)
        memory_mb = process_memory_mb(worker_pid)
        if exe is None:
            print(f"worker: pid {worker_pid} not found")
        else:
            memory_text = f", memory {memory_mb:.0f} MB" if memory_mb is not None else ""
            print(f"worker: running (pid {worker_pid}, exe {exe}{memory_text})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge worker watchdog")
    parser.add_argument("command", choices=["start", "stop", "status"])
    args = parser.parse_args(argv)
    config = build_config()

    if args.command == "start":
        return cmd_start(config)
    if args.command == "stop":
        return cmd_stop(config)
    return cmd_status(config)


if __name__ == "__main__":
    sys.exit(main())
