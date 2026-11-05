"""External toolchain and judge-worker configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import SandboxBackend, SandboxMode, SandboxPolicy

GCC_ENV = "JUDGE_GCC_PATH"
GXX_ENV = "JUDGE_GXX_PATH"
JAVAC_ENV = "JUDGE_JAVAC_PATH"
JAVA_ENV = "JUDGE_JAVA_PATH"
USER_PYTHON_ENV = "JUDGE_USER_PYTHON_PATH"
SANDBOX_BACKEND_ENV = "JUDGE_SANDBOX_BACKEND"

TDM_GCC_VERSION = "TDM-GCC 4.9.2 (Dev-C++ 5.11)"
LINUX_GCC_VERSION = "GCC 13 (Linux production baseline)"
WINDOWS_JDK_VERSION = "JDK 1.8"
LINUX_JDK_VERSION = "OpenJDK 17 (--release 8 target)"
WINDOWS_USER_PYTHON_VERSION = "Python 3.8.6"
LINUX_USER_PYTHON_VERSION = "Python 3.12 (Linux production baseline)"


class ToolchainConfigurationError(RuntimeError):
    """A required external tool was not configured as an absolute executable."""


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value and value.strip() else None


@dataclass(frozen=True, slots=True)
class ToolchainConfig:
    """Paths are deliberately external; the Worker never uses its own Python."""

    gcc_path: Path | None = None
    gxx_path: Path | None = None
    javac_path: Path | None = None
    java_path: Path | None = None
    user_python_path: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ToolchainConfig:
        source = os.environ if env is None else env
        return cls(
            gcc_path=_optional_path(source.get(GCC_ENV)),
            gxx_path=_optional_path(source.get(GXX_ENV)),
            javac_path=_optional_path(source.get(JAVAC_ENV)),
            java_path=_optional_path(source.get(JAVA_ENV)),
            user_python_path=_optional_path(source.get(USER_PYTHON_ENV)),
        )

    def require_executable(self, path: Path | None, variable: str) -> Path:
        if path is None:
            raise ToolchainConfigurationError(f"Required toolchain path is not set: {variable}.")
        if not path.is_absolute():
            raise ToolchainConfigurationError(f"Toolchain path from {variable} must be absolute.")
        if not path.is_file():
            raise ToolchainConfigurationError(f"Toolchain configured by {variable} is not an executable file.")
        return path

    def gcc(self) -> Path:
        return self.require_executable(self.gcc_path, GCC_ENV)

    def gxx(self) -> Path:
        return self.require_executable(self.gxx_path, GXX_ENV)

    def javac(self) -> Path:
        return self.require_executable(self.javac_path, JAVAC_ENV)

    def java(self) -> Path:
        return self.require_executable(self.java_path, JAVA_ENV)

    def user_python(self) -> Path:
        return self.require_executable(self.user_python_path, USER_PYTHON_ENV)

    def sensitive_paths(self) -> tuple[str, ...]:
        return tuple(
            str(path)
            for path in (
                self.gcc_path,
                self.gxx_path,
                self.javac_path,
                self.java_path,
                self.user_python_path,
            )
            if path is not None
        )


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    toolchain: ToolchainConfig
    sandbox: SandboxPolicy = field(default_factory=SandboxPolicy.development)
    work_root: Path | None = None
    # Selected via JUDGE_SANDBOX_BACKEND; None means the local subprocess
    # backend, which production policy refuses for its missing capabilities.
    sandbox_backend: SandboxBackend | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> JudgeConfig:
        source = os.environ if env is None else env
        try:
            mode = SandboxMode(source.get("JUDGE_ENV", "development").lower())
        except ValueError as exc:
            raise ToolchainConfigurationError("JUDGE_ENV must be 'development' or 'production'.") from exc
        allow_unsafe_tests = mode is SandboxMode.DEVELOPMENT and source.get("JUDGE_ALLOW_UNSAFE_TESTS") == "1"
        work_root = _optional_path(source.get("JUDGE_WORK_ROOT"))
        return cls(
            toolchain=ToolchainConfig.from_env(source),
            sandbox=SandboxPolicy(mode=mode, allow_unsafe_tests=allow_unsafe_tests),
            work_root=work_root,
            sandbox_backend=cls._select_sandbox_backend(source, work_root),
        )

    @staticmethod
    def _select_sandbox_backend(source: Mapping[str, str], work_root: Path | None) -> SandboxBackend | None:
        name = source.get(SANDBOX_BACKEND_ENV, "local").strip().lower()
        if name == "local":
            return None
        if name == "windows":
            from .windows_sandbox import WindowsSandboxBackend

            return WindowsSandboxBackend(work_root=work_root)
        if name == "isolate":
            from .linux_isolate import LinuxIsolateBackend

            return LinuxIsolateBackend(
                toolchain=ToolchainConfig.from_env(source),
                work_root=work_root,
                env=source,
            )
        raise ToolchainConfigurationError(
            f"{SANDBOX_BACKEND_ENV} must be 'local', 'windows' or 'isolate', got {name!r}."
        )


def build_clean_environment(
    source: Mapping[str, str] | None,
    temp_dir: Path,
) -> dict[str, str]:
    """Build a minimal environment without inheriting website/application secrets."""
    original = os.environ if source is None else source
    allowed = ("SystemRoot", "windir", "PATH", "PATHEXT", "ComSpec", "LANG", "LC_ALL")
    clean = {name: original[name] for name in allowed if name in original}
    clean["TMP"] = str(temp_dir)
    clean["TEMP"] = str(temp_dir)
    clean["TMPDIR"] = str(temp_dir)
    clean["HOME"] = str(temp_dir)
    if os.name != "nt":
        # Toolchains resolved to absolute paths do not need an inherited PATH.
        clean["PATH"] = "/usr/bin:/bin"
    return clean
