"""Linux production sandbox backend built on IOI isolate.

Isolation enforced here, before untrusted code runs:

* A fresh isolate box per spawn, with separate network and mount namespaces.
* cgroup v2 accounting for wall time, CPU time, peak memory, process count,
  task directory blocks/inodes, and sandbox-internal cleanup.
* ``--no-default-dirs`` with an explicit rule set so the box sees only the
  minimal rootfs (``/usr``, ``/lib``, ``/bin``, ...) built by
  ``deploy/judge-linux/build-rootfs.sh`` — never the host system directories.
  Only the per-spawn task directory is writable inside the box.
* Hard combined stdout/stderr output enforcement through a supervising proxy.
* Whole-box termination and box cleanup on every path, including failures.

The backend never claims an isolation capability that it has not positively
verified. Unsupported cgroup features fail closed instead of falling back to
local subprocess execution.

The meta parser targets the pinned IOI isolate v2.0 format: plain
``key: value`` lines (e.g. ``status: RE`` is *not* used — v2.0 emits
``status:RE``), numeric values as integers/floats in seconds or KiB.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import ToolchainConfig
from .process import ProcessLimits
from .sandbox import (
    IsolationCapabilities,
    SandboxBackend,
    SandboxConfigurationError,
    SandboxExecutionInfo,
    SandboxTerminationReason,
)

SANDBOX_PATH_ENV = "JUDGE_ISOLATE_PATH"
META_ROOT_ENV = "JUDGE_META_ROOT"
ROOTFS_ENV = "JUDGE_LINUX_ROOTFS"
CGROUP_ROOT_ENV = "JUDGE_CGROUP_ROOT"
FIRST_UID_ENV = "JUDGE_ISOLATE_FIRST_UID"
FIRST_GID_ENV = "JUDGE_ISOLATE_FIRST_GID"
USER_IDS_ENV = "JUDGE_ISOLATE_USER_IDS"
TOOLCHAIN_ROOT_ENV = "JUDGE_TOOLCHAIN_ROOT"
PROCS_ENV = "JUDGE_PROCESS_LIMIT"
COMPILE_PROCS_ENV = "JUDGE_COMPILE_PROCESS_LIMIT"
DISK_BLOCKS_ENV = "JUDGE_DISK_BLOCKS"
DISK_INODES_ENV = "JUDGE_DISK_INODES"
COMPILE_DISK_BLOCKS_ENV = "JUDGE_COMPILE_DISK_BLOCKS"
COMPILE_DISK_INODES_ENV = "JUDGE_COMPILE_DISK_INODES"
DISABLE_DISK_QUOTA_ENV = "JUDGE_DISABLE_DISK_QUOTA"

DEFAULT_ISOLATE_PATH = "/usr/bin/isolate"
DEFAULT_META_ROOT = "/var/lib/xinbaoyan-judge/meta"
DEFAULT_ROOTFS = "/var/lib/xinbaoyan-judge/rootfs"
DEFAULT_CGROUP_ROOT = "/sys/fs/cgroup"
DEFAULT_FIRST_UID = 60000
DEFAULT_FIRST_GID = 60000
DEFAULT_USER_IDS = 100
DEFAULT_TOOLCHAIN_ROOT = "/opt/judge-toolchains"
DEFAULT_PROCESS_LIMIT = 64
DEFAULT_DISK_BLOCKS = 51200  # 50 MiB in 1 KiB blocks.
DEFAULT_DISK_INODES = 4096

_BOX_PATH = "/box"
_TOOLCHAIN_PATH = "/toolchains"
_REQUIRED_CGROUP_CONTROLLERS = ("cpu", "memory", "pids", "io")

logger = logging.getLogger(__name__)

# isolate v2.0 meta files are plain "key: value" lines. Values are integers
# (cg-mem, exitcode, ...), decimals in seconds (time, time-wall) or strings
# (status, message). The line regex is anchored and non-greedy on the key so
# message text may itself contain colons.
_META_LINE_RE = re.compile(r"^([A-Za-z0-9_-]+):[ \t]*(.*)$")
_META_SECOND_MS = 1_000

# isolate v2.0 cannot bind a rule at "/" (sanitize_dir_path rejects it), so the
# rootfs is exposed through the same system-directory rules the default ruleset
# uses — but sourced from the rootfs instead of the host.
_ROOTFS_SYSTEM_DIRS: tuple[tuple[str, str], ...] = (
    ("bin", ""),
    ("lib", ""),
    ("lib64", ":maybe"),
    ("sbin", ":maybe"),
    ("etc", ":maybe"),
    ("usr", ""),
)


def _meta_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def parse_isolate_meta(text: str) -> dict[str, object]:
    """Parse an isolate v2.0 meta file (``key: value`` lines).

    Blank lines and lines that do not match the ``key: value`` shape are
    ignored; numeric values are converted to int/float. A duplicated key keeps
    the last occurrence, matching plain assignment semantics.
    """
    meta: dict[str, object] = {}
    for line in text.splitlines():
        match = _META_LINE_RE.match(line.strip())
        if match is None:
            continue
        key, raw = match.group(1), match.group(2).strip()
        value: object = raw
        if raw:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
        meta[key] = value
    return meta


def classify_isolate_meta(
    meta: Mapping[str, object],
    *,
    proxy_exceeded: bool = False,
    proxy_error: str = "",
) -> SandboxExecutionInfo:
    """Map a parsed isolate v2.0 meta dict to authoritative execution info.

    Status mapping (isolate 2.0 emits no ``status:`` line on success):

    * ``TO``  -> wall/CPU time limit (TLE)
    * ``ML``  -> memory limit (kept for forward compatibility; v2.0 reports
      cgroup OOM via ``cg-oom-killed: 1`` instead)
    * ``cg-oom-killed`` -> memory limit
    * ``OL``  -> output limit (kept for forward compatibility)
    * ``RE``  -> program exit code from ``exitcode`` (non-zero -> RE downstream)
    * ``SG``  -> program killed by signal; ``exitsig`` becomes a negative exit
      code so downstream logic reports RE, never AC
    * ``XX``  -> isolate internal error -> SANDBOX_ERROR (SE downstream)
    * unknown status -> SANDBOX_ERROR (fail closed, never guess)
    * no status -> normal completion; ``exitcode``/``exitsig`` still applied
    """
    status = str(meta.get("status", "") or "")
    exit_code: int | None = None
    if "exitcode" in meta:
        code = _meta_number(meta["exitcode"])
        if code is not None:
            exit_code = int(code)
    if "exitsig" in meta:
        sig = _meta_number(meta["exitsig"])
        if sig is not None:
            exit_code = -int(sig)
    if status == "SG" and exit_code is None:
        # Signalled without a recorded signal: force a non-zero exit so the
        # result can never be mistaken for a clean run.
        exit_code = -1
    if status == "RE" and exit_code is None:
        exit_code = 1

    runtime_ms: int | None = None
    for key in ("time", "time-wall"):
        value = _meta_number(meta.get(key))
        if value is not None:
            runtime_ms = int(float(value) * _META_SECOND_MS)
            break

    peak_memory_kb: int | None = None
    for key in ("cg-mem", "max-rss", "cg-mem-peak-kib"):
        value = _meta_number(meta.get(key))
        if value is not None:
            peak_memory_kb = int(value)
            break

    oom_killed = _meta_number(meta.get("cg-oom-killed")) not in (None, 0)
    wall_exceeded = status == "TO"
    memory_exceeded = status == "ML" or oom_killed
    output_exceeded = status == "OL"

    infrastructure_error = proxy_error
    if status == "XX":
        message = str(meta.get("message", "") or "").strip()
        detail = f"isolate internal error: {message}" if message else "isolate internal error (status XX)"
        infrastructure_error = f"{infrastructure_error}; {detail}".lstrip("; ")
        termination = SandboxTerminationReason.SANDBOX_ERROR
    elif wall_exceeded:
        termination = SandboxTerminationReason.WALL_TIME_LIMIT
    elif memory_exceeded:
        termination = SandboxTerminationReason.MEMORY_LIMIT
    elif output_exceeded:
        termination = SandboxTerminationReason.OUTPUT_LIMIT
    elif status in ("", "OK", "RE", "SG"):
        termination = SandboxTerminationReason.NORMAL
    else:
        # Unknown status: fail closed instead of guessing a verdict.
        infrastructure_error = (infrastructure_error + f"; isolate status={status}").lstrip("; ")
        termination = SandboxTerminationReason.SANDBOX_ERROR

    return SandboxExecutionInfo(
        termination_reason=termination,
        runtime_ms=runtime_ms,
        peak_memory_kb=peak_memory_kb,
        wall_time_exceeded=wall_exceeded,
        memory_exceeded=memory_exceeded,
        output_exceeded=output_exceeded or proxy_exceeded,
        infrastructure_error=infrastructure_error,
        exit_code=exit_code,
    )


@dataclass(slots=True)
class _SpawnState:
    """Per-spawn resources that must be rolled back on every failure path."""

    box_id: int
    meta_dir: Path
    meta_file: Path
    stdin_file: Path
    stdout_file: Path
    stderr_file: Path
    proxy: _OutputProxy | None
    isolate: subprocess.Popen[bytes] | None
    cleanup_started: bool = False
    # Set only by terminate(): a negative isolate exit code is "expected, no
    # meta" exclusively when OUR runner requested the kill, never for an
    # external SIGKILL or a supervisor crash.
    termination_requested: bool = False
    # Populated when the isolate --cleanup pass fails; logged for operators
    # because cleanup runs after the run's accounting has been collected.
    cleanup_error: str = ""


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SandboxConfigurationError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise SandboxConfigurationError(f"{name} must be positive, got {raw!r}")
    return value


def _resolve_directory(env: Mapping[str, str], name: str, default: str) -> Path:
    raw = env.get(name, default)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SandboxConfigurationError(f"{name} must be an absolute path: {raw!r}")
    return path


class _OutputProxy:
    """Combined stdout/stderr proxy with a hard byte limit and backpressure.

    isolate creates the output files only after entering the box (chroot + fd
    setup), and a regular file that reaches EOF may still receive more output
    later. Pumps therefore wait for file creation and keep polling past EOF
    until ``finish()`` is called or the run stops.
    """

    def __init__(
        self,
        *,
        stdout: BinaryIO,
        stderr: BinaryIO,
        limit_bytes: int,
        stop_event: threading.Event,
    ):
        self._stdout = stdout
        self._stderr = stderr
        self._limit_bytes = max(0, limit_bytes)
        self._stop_event = stop_event
        self._finished = threading.Event()
        self._exceeded = threading.Event()
        self._errors: list[str] = []
        self._paths: dict[str, Path] = {}
        self._file_poll_seconds = 0.005
        self._file_ready_timeout_seconds = 10.0
        self._threads = [
            threading.Thread(target=self._pump, args=(name,), name=f"judge-output-{name}", daemon=True)
            for name in ("stdout", "stderr")
        ]

    @property
    def stop_event(self) -> threading.Event:
        """Set when the hard output cap trips; consumed by the process runner."""
        return self._stop_event

    def start(self, paths: Mapping[str, Path]) -> None:
        self._paths = dict(paths)
        for thread in self._threads:
            thread.start()

    def _pump(self, name: str) -> None:
        source = self._paths[name]
        written = 0
        try:
            ready_deadline = time.monotonic() + self._file_ready_timeout_seconds
            while not source.exists():
                if self._finished.is_set() or self._stop_event.is_set():
                    return
                if time.monotonic() > ready_deadline:
                    self._errors.append(f"{name} output file was never created")
                    return
                time.sleep(self._file_poll_seconds)
            with source.open("rb", buffering=0) as stream:
                while True:
                    chunk = stream.read(64 * 1024)
                    if chunk:
                        if written + len(chunk) > self._limit_bytes:
                            self._exceeded.set()
                            self._stop_event.set()
                            return
                        destination = self._stdout if name == "stdout" else self._stderr
                        destination.write(chunk)
                        destination.flush()
                        written += len(chunk)
                        continue
                    # EOF on a regular file is not final: the supervised
                    # process may append more output at any time.
                    if self._finished.is_set() or self._stop_event.is_set():
                        return
                    time.sleep(self._file_poll_seconds)
        except OSError as exc:
            self._errors.append(f"{name} output proxy failed: {type(exc).__name__}")

    @property
    def exceeded(self) -> bool:
        return self._exceeded.is_set()

    def finish(self, timeout_seconds: float = 5.0) -> None:
        self._finished.set()
        deadline = time.monotonic() + timeout_seconds
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def snapshot(self) -> tuple[bool, str]:
        return self.exceeded, "; ".join(self._errors)


class LinuxIsolateBackend(SandboxBackend):
    """Production sandbox adapter for an isolate-enabled Linux judge node."""

    _capabilities = IsolationCapabilities(
        process_group_termination=True,
        hard_wall_time_limit=True,
        hard_output_limit=True,
        hard_memory_limit=True,
        filesystem_isolation=True,
        network_disabled=True,
        low_privilege=True,
    )

    def __init__(self, *, toolchain: ToolchainConfig, work_root: Path | None, env: Mapping[str, str] | None = None):
        if os.name == "nt":
            raise SandboxConfigurationError("LinuxIsolateBackend is available only on POSIX systems.")
        self._env = os.environ if env is None else env
        self._toolchain = toolchain
        self._isolate_path = Path(self._env.get(SANDBOX_PATH_ENV, DEFAULT_ISOLATE_PATH)).expanduser()
        self._work_root = work_root
        self._meta_root = _resolve_directory(self._env, META_ROOT_ENV, DEFAULT_META_ROOT)
        self._rootfs = _resolve_directory(self._env, ROOTFS_ENV, DEFAULT_ROOTFS)
        self._cgroup_root = _resolve_directory(self._env, CGROUP_ROOT_ENV, DEFAULT_CGROUP_ROOT)
        self._first_uid = _env_int(self._env, FIRST_UID_ENV, DEFAULT_FIRST_UID)
        self._first_gid = _env_int(self._env, FIRST_GID_ENV, DEFAULT_FIRST_GID)
        self._user_ids = _env_int(self._env, USER_IDS_ENV, DEFAULT_USER_IDS)
        self._default_process_limit = _env_int(self._env, PROCS_ENV, DEFAULT_PROCESS_LIMIT)
        self._toolchain_root = _resolve_directory(self._env, TOOLCHAIN_ROOT_ENV, DEFAULT_TOOLCHAIN_ROOT)
        self._default_disk_blocks = _env_int(self._env, DISK_BLOCKS_ENV, DEFAULT_DISK_BLOCKS)
        self._default_disk_inodes = _env_int(self._env, DISK_INODES_ENV, DEFAULT_DISK_INODES)
        self._compile_process_limit = _env_int(
            self._env, COMPILE_PROCS_ENV, max(16, self._default_process_limit // 2)
        )
        self._compile_disk_blocks = _env_int(
            self._env, COMPILE_DISK_BLOCKS_ENV, max(51200, self._default_disk_blocks * 4)
        )
        self._compile_disk_inodes = _env_int(
            self._env, COMPILE_DISK_INODES_ENV, max(4096, self._default_disk_inodes * 4)
        )
        # Docker judge containers use a private, size-bounded /dev/shm for the
        # isolate boxes. tmpfs does not implement quotactl; the container-wide
        # shm_size is the hard disk ceiling in that deployment. Keep quota by
        # default everywhere else and require an explicit opt-in to disable it.
        self._disable_disk_quota = self._env.get(DISABLE_DISK_QUOTA_ENV) == "1"
        self._states: dict[int, _SpawnState] = {}
        self._lock = threading.Lock()
        self._next_box_id = os.getpid() % 1000
        self._mounts = self._build_mounts()
        self._meta_root.mkdir(parents=True, exist_ok=True)
        self._validate_static_configuration()

    @property
    def capabilities(self) -> IsolationCapabilities:
        return self._capabilities

    def _validate_static_configuration(self) -> None:
        if not self._isolate_path.is_file():
            raise SandboxConfigurationError(f"isolate executable is not available: {self._isolate_path}")
        if not self._rootfs.is_dir():
            raise SandboxConfigurationError(f"Linux judge rootfs is not available: {self._rootfs}")
        if self._work_root is not None:
            self._validated_work_root()
        self._validate_cgroup_v2()
        for source, destination in self._mounts:
            if not source.is_dir():
                raise SandboxConfigurationError(f"Sandbox mount source is missing: {source}")
            if not destination.startswith("/"):
                raise SandboxConfigurationError(f"Sandbox mount destination must be absolute: {destination}")

    def _validated_work_root(self) -> Path:
        assert self._work_root is not None
        try:
            root = self._work_root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise SandboxConfigurationError(f"JUDGE_WORK_ROOT does not exist: {self._work_root}") from exc
        if not root.is_dir():
            raise SandboxConfigurationError(f"JUDGE_WORK_ROOT must be a directory: {root}")
        return root

    def _validate_cgroup_v2(self) -> None:
        unified = self._cgroup_root / "cgroup.controllers"
        subtree = self._cgroup_root / "cgroup.subtree_control"
        if not unified.is_file() or not subtree.is_file():
            raise SandboxConfigurationError(
                f"Linux judge backend requires cgroup v2 at {self._cgroup_root}; cgroup v1 is unsupported."
            )
        available = unified.read_text(encoding="utf-8").split()
        missing = [controller for controller in _REQUIRED_CGROUP_CONTROLLERS if controller not in available]
        if missing:
            raise SandboxConfigurationError(
                "Linux judge cgroup v2 hierarchy is missing required controllers: " + ", ".join(missing)
            )

    def _build_mounts(self) -> tuple[tuple[Path, str], ...]:
        self._validate_toolchains()
        # isolate 2.0 cannot bind at "/", so the rootfs is exposed through
        # per-directory rules in `_dir_rules()`; only the toolchain is mapped
        # 1:1 for argv rewriting.
        return ((self._toolchain_root, _TOOLCHAIN_PATH),)

    def _validate_toolchains(self) -> None:
        root = self._toolchain_root.resolve(strict=True)
        if root == Path("/"):
            raise SandboxConfigurationError("Refusing to mount the host root as the toolchain directory.")
        resolved_values = []
        for raw_path in self._toolchain.sensitive_paths():
            resolved = Path(raw_path).resolve(strict=True)
            if not resolved.is_file():
                raise SandboxConfigurationError(f"Configured toolchain is missing: {resolved}")
            resolved_values.append(resolved)
        for resolved in resolved_values:
            if resolved != root and root not in resolved.parents:
                raise SandboxConfigurationError(
                    f"Configured toolchain {resolved} is outside {TOOLCHAIN_ROOT_ENV}={root}"
                )

    def _map_path(self, value: str, box_dir: Path) -> str:
        # Choose the most specific matching mount. Toolchains and the current
        # task directory may be nested under a common work root; a generic
        # parent prefix must not hide the more specific /toolchains or /box
        # mapping.
        mappings = [(*mount, len(str(mount[0]))) for mount in self._mounts]
        mappings.append((box_dir, _BOX_PATH, len(str(box_dir))))
        best_length = -1
        mapped = value
        for source, destination, length in mappings:
            source_text = str(source)
            if value != source_text and not value.startswith(source_text + os.sep):
                continue
            if length > best_length:
                best_length = length
                mapped = destination + value[len(source_text) :]
        return mapped

    def _sandbox_argv(self, argv: Sequence[str], box_dir: Path) -> list[str]:
        if not argv:
            raise SandboxConfigurationError("Sandbox command cannot be empty.")
        return [self._map_path(str(part), box_dir) for part in argv]

    def _dir_rules(self, work_dir: Path) -> list[str]:
        """Explicit isolate 2.0 --dir rules replacing the default ruleset.

        Default rules bind the *host* /bin, /lib, /usr, ...; with
        ``--no-default-dirs`` the same layout is sourced from the pinned
        rootfs so host system directories are never visible in the box.
        Bind rules without the ``rw`` flag are read-only in isolate.
        """
        rules = [f"--dir={_BOX_PATH}={work_dir}:rw"]
        for name, flags in _ROOTFS_SYSTEM_DIRS:
            rules.append(f"--dir=/{name}={self._rootfs}/{name}{flags}")
        rules.append(f"--dir={_TOOLCHAIN_PATH}={self._toolchain_root}")
        # Runtime plumbing the default ruleset normally provides.
        rules.append("--dir=/dev=/dev:dev")
        rules.append("--dir=/proc=proc:fs")
        rules.append("--dir=tmp:tmp")
        return rules

    def _limits(self, argv: Sequence[str], limits: ProcessLimits | None) -> tuple[int, int, int, int | None]:
        if limits is None:
            raise SandboxConfigurationError("Linux judge backend requires explicit process limits.")
        is_compile = self._is_compile_command(argv)
        process_limit = self._compile_process_limit if is_compile else self._default_process_limit
        disk_blocks = self._compile_disk_blocks if is_compile else self._default_disk_blocks
        disk_inodes = self._compile_disk_inodes if is_compile else self._default_disk_inodes
        return process_limit, disk_blocks, disk_inodes, limits.memory_limit_kb

    def _is_compile_command(self, argv: Sequence[str]) -> bool:
        executable = Path(argv[0]).name.lower()
        if executable in {"javac", "gcc", "g++", "gcc.exe", "g++.exe", "javac.exe"}:
            return True
        return executable.startswith("python") and len(argv) > 2 and argv[1] == "-m" and argv[2] == "py_compile"

    def _ensure_work_dir(self, cwd: Path) -> Path:
        if self._work_root is None:
            raise SandboxConfigurationError("JUDGE_WORK_ROOT is required for Linux judge isolation.")
        work_root = self._validated_work_root()
        resolved = cwd.resolve(strict=True)
        if resolved != work_root and work_root not in resolved.parents:
            raise SandboxConfigurationError(f"Refusing to execute outside JUDGE_WORK_ROOT: {resolved}")
        return resolved

    def spawn(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        creationflags: int,
        start_new_session: bool,
        limits: ProcessLimits | None = None,
    ) -> subprocess.Popen[bytes]:
        if creationflags:
            raise SandboxConfigurationError(f"Unsupported creation flags for Linux sandbox: {creationflags}")
        work_dir = self._ensure_work_dir(cwd)
        effective_limits = limits or ProcessLimits(wall_timeout_ms=1000, output_limit_bytes=1)
        process_limit, disk_blocks, disk_inodes, memory_limit_kb = self._limits(argv, effective_limits)
        command = self._sandbox_argv(argv, work_dir)
        box_id = self._allocate_box_id()
        try:
            # tempfile creates task directories as 0700. The per-box UID must
            # own this one directory to traverse it and create stdout/stderr;
            # no parent or sibling task directory becomes accessible.
            os.chown(work_dir, self._first_uid + box_id, self._first_gid + box_id)  # type: ignore[attr-defined]
        except PermissionError as exc:
            raise SandboxConfigurationError(
                "Linux judge worker needs permission to chown the per-spawn task directory to the isolate box UID"
            ) from exc
        self._init_box(box_id, disk_blocks, disk_inodes)
        state = _SpawnState(
            box_id=box_id,
            meta_dir=Path(tempfile.mkdtemp(prefix=f"spawn-{box_id}-", dir=self._meta_root)),
            meta_file=Path(""),
            stdin_file=Path(""),
            stdout_file=Path(""),
            stderr_file=Path(""),
            proxy=None,
            isolate=None,
        )
        state.meta_file = state.meta_dir / "meta.txt"
        # stdin/stdout/stderr staging files live in the task directory because
        # isolate opens the --stdin/--stdout/--stderr paths *inside* the box
        # after chroot(setup_fds runs in box_inside); they are addressed as
        # /box/... on the command line and as host paths by the output proxy.
        state.stdin_file = work_dir / ".judge-sandbox-stdin"
        state.stdout_file = work_dir / ".judge-sandbox-stdout"
        state.stderr_file = work_dir / ".judge-sandbox-stderr"
        shutil.copyfileobj(stdin, state.stdin_file.open("wb"))
        # isolate drops to the per-box UID before opening /box/.../stdin.
        # The judge service umask may be 077, so explicitly make the staged
        # input readable without making it writable by the sandboxed program.
        state.stdin_file.chmod(0o644)
        command_line = [
            str(self._isolate_path),
            "--box-id",
            str(box_id),
            "--run",
            "--cg",
            # Never expose host /usr, /bin, /lib, ...: the explicit rule set in
            # _dir_rules() sources system directories from the pinned rootfs.
            "--no-default-dirs",
            *self._dir_rules(work_dir),
            "--env=HOME=/box",
            "--env=TMPDIR=/box",
            "--env=TMP=/box",
            "--env=TEMP=/box",
            "--env=PATH=/usr/bin:/bin",
            f"--meta={state.meta_file}",
            f"--stdin={_BOX_PATH}/{state.stdin_file.name}",
            f"--stdout={_BOX_PATH}/{state.stdout_file.name}",
            f"--stderr={_BOX_PATH}/{state.stderr_file.name}",
            f"--wall-time={max(1, (effective_limits.wall_timeout_ms + 999) // 1000)}",
            f"--processes={process_limit}",
            f"--fsize={max(1, (effective_limits.output_limit_bytes + 1023) // 1024)}",
        ]
        if memory_limit_kb is not None:
            command_line.append(f"--cg-mem={memory_limit_kb}")
        command_line.extend(["--", *command])
        try:
            state.isolate = subprocess.Popen(
                command_line,
                cwd=str(work_dir),
                env={key: value for key, value in env.items() if key in {"PATH", "LANG", "LC_ALL"}},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            state.proxy = _OutputProxy(
                stdout=stdout,
                stderr=stderr,
                limit_bytes=effective_limits.output_limit_bytes,
                stop_event=threading.Event(),
            )
            state.proxy.start({"stdout": state.stdout_file, "stderr": state.stderr_file})
            with self._lock:
                self._states[state.isolate.pid] = state
            return state.isolate
        except BaseException:
            self._rollback(state)
            raise

    def _init_box(self, box_id: int, disk_blocks: int, disk_inodes: int) -> None:
        argv = [
            str(self._isolate_path),
            "--box-id",
            str(box_id),
            "--init",
            "--cg",
        ]
        if not self._disable_disk_quota:
            argv.append(f"--quota={disk_blocks},{disk_inodes}")
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SandboxConfigurationError(f"isolate --init failed: {result.stderr.strip()}")

    def _allocate_box_id(self) -> int:
        with self._lock:
            value = self._next_box_id
            self._next_box_id = (self._next_box_id + 1) % 1000
        return value

    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        state = self._state_for(process)
        # Record that WE requested termination: execution_info uses this to
        # distinguish an expected kill (timeout/output/memory enforcement, no
        # meta written) from an external SIGKILL or supervisor crash.
        state.termination_requested = True
        if state.proxy is not None:
            state.proxy.finish()
        if state.isolate is not None and state.isolate.poll() is None:
            state.isolate.send_signal(getattr(signal, "SIGKILL", signal.SIGTERM))
        if state.isolate is not None:
            try:
                state.isolate.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._isolate_cleanup(state)

    def memory_usage_kb(self, process: subprocess.Popen[bytes]) -> int | None:
        info = classify_isolate_meta(self._read_meta(process) or {})
        return info.peak_memory_kb

    def execution_info(self, process: subprocess.Popen[bytes]) -> SandboxExecutionInfo:
        state = self._state_for(process)
        meta = self._read_meta(process)
        if meta is None:
            isolate = getattr(state, "isolate", None)
            returncode = isolate.returncode if isolate is not None else None
            if returncode is not None and returncode < 0 and getattr(state, "termination_requested", False):
                # The supervising runner itself requested this kill (timeout/
                # output/memory enforcement): no meta is expected and the
                # termination reason is already known upstream. Report neutral
                # accounting instead of masking the real verdict with a
                # sandbox error.
                meta = {}
            else:
                # isolate finished (or died) on its own without usable meta —
                # including external SIGKILLs, which must never fail open.
                meta = {"status": "XX", "message": "isolate meta file missing or empty after run"}
        proxy_exceeded = False
        proxy_error = ""
        if state.proxy is not None:
            # Drain and join the pumps BEFORE reading their state: output
            # detected only after the supervised process exited would
            # otherwise be lost (cleanup, which also finishes, runs later).
            state.proxy.finish()
            proxy_exceeded, proxy_error = state.proxy.snapshot()
        return classify_isolate_meta(meta, proxy_exceeded=proxy_exceeded, proxy_error=proxy_error)

    def cleanup(self, process: subprocess.Popen[bytes]) -> None:
        state = self._state_for(process)
        if state.proxy is not None:
            state.proxy.finish()
        if state.isolate is not None and state.isolate.poll() is None:
            self.terminate(process)
        self._isolate_cleanup(state)
        with self._lock:
            self._states.pop(process.pid, None)
        self._remove_quietly(state.meta_dir)
        self._remove_quietly(state.stdin_file)
        self._remove_quietly(state.stdout_file)
        self._remove_quietly(state.stderr_file)

    def output_stop_event(self, process: subprocess.Popen[bytes]) -> threading.Event | None:
        state = self._state_for(process)
        return state.proxy.stop_event if state.proxy is not None else None

    def _isolate_cleanup(self, state: _SpawnState) -> None:
        if state.cleanup_started:
            return
        state.cleanup_started = True
        # --cg is required: without it isolate's cg_remove() returns early and
        # the per-run cgroup is left behind (accumulates until
        # "Device or resource busy"). Failures are recorded and logged instead
        # of being silently swallowed.
        try:
            result = subprocess.run(
                [str(self._isolate_path), "--box-id", str(state.box_id), "--cleanup", "--cg"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            state.cleanup_error = f"isolate --cleanup failed: {type(exc).__name__}: {exc}"
            logger.error("%s", state.cleanup_error)
            return
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            state.cleanup_error = f"isolate --cleanup exited with {result.returncode}: {detail}"
            logger.error("%s", state.cleanup_error)

    def _state_for(self, process: subprocess.Popen[bytes]) -> _SpawnState:
        with self._lock:
            state = self._states.get(process.pid)
        if state is None:
            raise SandboxConfigurationError(f"Unknown Linux sandbox process: {process.pid}")
        return state

    def _read_meta(self, process: subprocess.Popen[bytes]) -> dict[str, object] | None:
        state = self._state_for(process)
        try:
            text = state.meta_file.read_text(encoding="utf-8")
        except OSError:
            return None
        meta = parse_isolate_meta(text)
        return meta or None

    def _rollback(self, state: _SpawnState) -> None:
        if state.proxy is not None:
            state.proxy.finish()
        if state.isolate is not None and state.isolate.poll() is None:
            try:
                state.isolate.kill()
                state.isolate.wait(timeout=5)
            except Exception:
                pass
        self._isolate_cleanup(state)
        self._remove_quietly(state.meta_dir)
        self._remove_quietly(state.stdout_file)
        self._remove_quietly(state.stderr_file)

    @staticmethod
    def _remove_quietly(path: Path) -> None:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
