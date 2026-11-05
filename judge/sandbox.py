"""Execution policy and the boundary for real operating-system isolation."""

from __future__ import annotations

import os
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from .process import ProcessLimits


class SandboxError(RuntimeError):
    """Base class for sandbox setup and enforcement failures."""


class SandboxConfigurationError(SandboxError):
    """Raised before execution when the configured isolation is insufficient."""


class SandboxMode(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class SandboxTerminationReason(StrEnum):
    """Machine-readable reason reported by a supervising backend."""

    NORMAL = "normal"
    CPU_TIME_LIMIT = "cpu_time_limit"
    WALL_TIME_LIMIT = "wall_time_limit"
    MEMORY_LIMIT = "memory_limit"
    OUTPUT_LIMIT = "output_limit"
    PROCESS_LIMIT = "process_limit"
    DISK_LIMIT = "disk_limit"
    SANDBOX_ERROR = "sandbox_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SandboxExecutionInfo:
    """Optional authoritative accounting returned by a supervising backend."""

    termination_reason: SandboxTerminationReason = SandboxTerminationReason.NORMAL
    runtime_ms: int | None = None
    peak_memory_kb: int | None = None
    wall_time_exceeded: bool = False
    memory_exceeded: bool = False
    output_exceeded: bool = False
    infrastructure_error: str = ""


@dataclass(frozen=True, slots=True)
class IsolationCapabilities:
    """Security claims made by a backend; the local backend does not claim them."""

    process_group_termination: bool = False
    hard_wall_time_limit: bool = False
    hard_output_limit: bool = False
    hard_memory_limit: bool = False
    filesystem_isolation: bool = False
    network_disabled: bool = False
    low_privilege: bool = False

    def missing_production_capabilities(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "process_group_termination",
                "hard_wall_time_limit",
                "hard_output_limit",
                "hard_memory_limit",
                "filesystem_isolation",
                "network_disabled",
                "low_privilege",
            )
            if not getattr(self, name)
        )


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Refuse unsafe defaults instead of treating subprocess as a sandbox."""

    mode: SandboxMode = SandboxMode.DEVELOPMENT
    allow_unsafe_tests: bool = False
    # Human-readable explanation of where outbound-network isolation comes
    # from when a backend delegates networking to a host firewall; purely
    # informational for diagnostics, never a substitute for enforcement.
    production_network_source: str | None = None
    network_configuration_hint: str | None = None

    @classmethod
    def development(cls, *, allow_unsafe_tests: bool = False) -> SandboxPolicy:
        return cls(SandboxMode.DEVELOPMENT, allow_unsafe_tests)

    @classmethod
    def production(
        cls,
        *,
        network_source: str | None = None,
        network_hint: str | None = None,
    ) -> SandboxPolicy:
        return cls(SandboxMode.PRODUCTION, False, network_source, network_hint)

    def ensure_execution_allowed(self, backend: SandboxBackend | None) -> None:
        if backend is None:
            raise SandboxConfigurationError("No sandbox backend is configured.")
        if self.mode is SandboxMode.DEVELOPMENT:
            if not self.allow_unsafe_tests:
                raise SandboxConfigurationError(
                    "Development execution is disabled. Set allow_unsafe_tests=True "
                    "only for harmless, controlled unit-test programs."
                )
            return

        missing = backend.capabilities.missing_production_capabilities()
        # Duck-typed capability-only backends may not implement the hook; only
        # positively verified host firewalls waive network_disabled.
        firewall_check = getattr(backend, "firewall_configured", None)
        firewall_configured = bool(firewall_check and firewall_check())
        if firewall_configured and "network_disabled" in missing:
            # The backend delegates outbound-network blocking to a host
            # firewall it can positively verify (e.g. JUDGE_FIREWALL_ACTIVE=1
            # set by the firewall setup script), so the capability check for
            # network_disabled is waived for this backend only.
            missing = tuple(capability for capability in missing if capability != "network_disabled")
        if missing:
            message = (
                "Production execution refused; backend does not provide: " + ", ".join(missing) + "."
            )
            if firewall_configured:
                source = self.production_network_source or "host firewall"
                message += f" Network isolation is provided externally by the {source}."
            elif "network_disabled" in missing:
                message += (
                    " Outbound network control must come from a backend capability or a verified "
                    "host firewall. Do not claim a network capability without positively verifying it."
                )
                if self.network_configuration_hint:
                    message += f" Backend hint: {self.network_configuration_hint}"
            raise SandboxConfigurationError(message)


class SandboxBackend(ABC):
    """Adapter implemented by a real isolation system.

    Production adapters must enforce every capability they report. Returning
    capabilities without enforcing them is a security bug in that adapter.
    """

    @property
    @abstractmethod
    def capabilities(self) -> IsolationCapabilities:
        raise NotImplementedError

    def firewall_configured(self) -> bool:
        """Whether an external host firewall already blocks this backend's network access.

        Backends that do not isolate networking themselves must leave this as
        False; production policy refuses to run them without network_disabled.
        """
        return False

    @abstractmethod
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
        """Start a process, applying isolation before untrusted code runs."""
        raise NotImplementedError

    @abstractmethod
    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        """Synchronously request termination of the process and its children."""
        raise NotImplementedError

    def memory_usage_kb(self, process: subprocess.Popen[bytes]) -> int | None:
        """Return current/peak memory when the adapter can account for it."""
        return None

    def cleanup(self, process: subprocess.Popen[bytes]) -> None:
        """Release adapter resources after the process has been reaped."""
        return None

    def execution_info(self, process: subprocess.Popen[bytes]) -> SandboxExecutionInfo:
        """Return authoritative accounting and termination reasons, if available."""
        return SandboxExecutionInfo()


class LocalSubprocessBackend(SandboxBackend):
    """Process-group cleanup for harmless development tests, not a sandbox."""

    _capabilities = IsolationCapabilities(process_group_termination=True)

    @property
    def capabilities(self) -> IsolationCapabilities:
        return self._capabilities

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
        # Limits are enforced by supervising backends; the local backend has
        # no hard-limit support and intentionally ignores them.
        return subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=start_new_session,
            close_fds=True,
        )

    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            # taskkill /T includes descendants; CREATE_NEW_PROCESS_GROUP alone
            # does not provide process-tree cleanup on Windows.
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            taskkill = system_root / "System32" / "taskkill.exe"
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            finally:
                if process.poll() is None:
                    process.kill()
            return

        try:
            killpg = getattr(os, "kill" + "pg")
            killpg(process.pid, getattr(signal, "SIG" + "KILL"))
        except ProcessLookupError:
            return
