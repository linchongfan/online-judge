"""Windows production sandbox backend built on Win32 restricted tokens and job objects.

Isolation enforced here, before untrusted code runs:

* A restricted token derived from the current process token with
  ``CreateRestrictedToken`` (all privileges disabled, enabled high-risk
  groups removed), used to start the child via ``CreateProcessWithTokenW``.
* A job object (``CreateJobObject`` / ``SetInformationJobObject``) with
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` so closing the handle reaps the
  whole tree, plus a hard per-process memory cap
  (``JOB_OBJECT_LIMIT_PROCESS_MEMORY``) and a hard per-process CPU time cap
  (``JOB_OBJECT_LIMIT_PROCESS_TIME``) taken from ``ProcessLimits``.
* The working directory must live under ``JUDGE_WORK_ROOT`` and its DACL is
  tightened with ``SetNamedSecurityInfo`` so only the current user, SYSTEM,
  and Administrators retain access.

Outbound network blocking is deliberately *not* claimed as a capability;
production deployments delegate it to a host firewall and must set
``JUDGE_FIREWALL_ACTIVE=1`` (see ``firewall_configured``), which
``SandboxPolicy.ensure_execution_allowed`` verifies before waiving the
``network_disabled`` requirement.

This module is Windows-only; every Win32 call goes through the module-level
``_advapi32()`` / ``_kernel32()`` loaders so unit tests can inject fakes
without administrator rights or real tokens/jobs.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from .sandbox import IsolationCapabilities, SandboxBackend, SandboxConfigurationError

if TYPE_CHECKING:
    from .process import ProcessLimits

_logger = logging.getLogger(__name__)

FIREWALL_ACTIVE_ENV = "JUDGE_FIREWALL_ACTIVE"

# --- Token constants ---------------------------------------------------------
_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_DUPLICATE = 0x0002
_TOKEN_QUERY = 0x0008

_TOKEN_INFO_CLASS_USER = 1
_TOKEN_INFO_CLASS_GROUPS = 2

_SE_GROUP_MANDATORY = 0x00000001
_SE_GROUP_ENABLED = 0x00000004
# SE_GROUP_LOGON_ID (0xC0000000) doubles as SE_GROUP_USE_FOR_DENY_ONLY; the
# logon identifier group must survive restriction or the token is unusable.
_SE_GROUP_LOGON_ID = 0xC0000000

_DISABLE_MAX_PRIVILEGE = 0x00000001

# --- Job object constants ----------------------------------------------------
_JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

# --- Process creation constants ----------------------------------------------
_STARTF_USESTDHANDLES = 0x00000100
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_HANDLE_FLAG_INHERIT = 0x00000001

# --- ACL constants -----------------------------------------------------------
_GENERIC_ALL = 0x10000000
_GRANT_ACCESS = 0x00000001
_SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x00000003
_TRUSTEE_IS_SID = 0x00000000
_SE_FILE_OBJECT = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x00000010

_SECURITY_BUILTIN_DOMAIN_RID = 0x00000020
_DOMAIN_ALIAS_RID_ADMINS = 0x00000220
_SECURITY_LOCAL_SYSTEM_RID = 0x00000012
_SECURITY_NT_AUTHORITY = (0, 0, 0, 0, 0, 5)


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.POINTER(ctypes.c_byte)),
        ("Attributes", wintypes.DWORD),
    ]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_GROUPS(ctypes.Structure):
    _fields_ = [
        ("GroupCount", wintypes.DWORD),
        ("Groups", _SID_AND_ATTRIBUTES * 1),
    ]


class _TRUSTEE_W(ctypes.Structure):
    # TRUSTEE_W ends in an unnamed union of LPWSTR ptstrName and PSID pSid;
    # both are pointer-sized, so a single LPWSTR field covers both layouts.
    _fields_ = [
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", wintypes.LPWSTR),
    ]


class _EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TRUSTEE_W),
    ]


_ADVAPI32: Any | None = None
_KERNEL32: Any | None = None


def _advapi32() -> Any:
    """Return advapi32 with prototypes configured; cached and mockable."""
    global _ADVAPI32
    if _ADVAPI32 is None:
        lib = ctypes.WinDLL("advapi32", use_last_error=True)
        lib.OpenProcessToken.restype = wintypes.BOOL
        lib.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        lib.GetTokenInformation.restype = wintypes.BOOL
        lib.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        lib.CreateRestrictedToken.restype = wintypes.BOOL
        lib.CreateRestrictedToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        lib.AllocateAndInitializeSid.restype = wintypes.BOOL
        lib.AllocateAndInitializeSid.argtypes = [
            ctypes.POINTER(wintypes.BYTE),
            wintypes.BYTE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(wintypes.BYTE)),
        ]
        lib.FreeSid.restype = ctypes.c_void_p
        lib.FreeSid.argtypes = [ctypes.c_void_p]
        lib.SetEntriesInAclW.restype = wintypes.DWORD
        lib.SetEntriesInAclW.argtypes = [
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.LPVOID,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        lib.SetNamedSecurityInfoW.restype = wintypes.DWORD
        lib.SetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.LPVOID,
        ]
        lib.CreateProcessWithTokenW.restype = wintypes.BOOL
        lib.CreateProcessWithTokenW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _ADVAPI32 = lib
    return _ADVAPI32


def _kernel32() -> Any:
    """Return kernel32 with prototypes configured; cached and mockable."""
    global _KERNEL32
    if _KERNEL32 is None:
        lib = ctypes.WinDLL("kernel32", use_last_error=True)
        lib.GetCurrentProcess.restype = wintypes.HANDLE
        lib.GetCurrentProcess.argtypes = []
        lib.CloseHandle.restype = wintypes.BOOL
        lib.CloseHandle.argtypes = [wintypes.HANDLE]
        lib.TerminateProcess.restype = wintypes.BOOL
        lib.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        lib.CreateJobObjectW.restype = wintypes.HANDLE
        lib.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        lib.SetInformationJobObject.restype = wintypes.BOOL
        lib.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        lib.QueryInformationJobObject.restype = wintypes.BOOL
        lib.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        lib.AssignProcessToJobObject.restype = wintypes.BOOL
        lib.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        lib.TerminateJobObject.restype = wintypes.BOOL
        lib.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        lib.SetHandleInformation.restype = wintypes.BOOL
        lib.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        lib.LocalFree.restype = wintypes.HANDLE
        lib.LocalFree.argtypes = [wintypes.HANDLE]
        _KERNEL32 = lib
    return _KERNEL32


def _last_error(api_name: str) -> str:
    return f"{api_name} failed with Win32 error {ctypes.get_last_error()}."


def _set_out_pointer(out: Any, value: int) -> None:
    """Write ``value`` through a byref() output pointer passed to a mocked API."""
    ctypes.cast(out, ctypes.POINTER(wintypes.HANDLE)).contents.value = value


class WindowsSandboxBackend(SandboxBackend):
    """Production isolation on Windows: restricted token + job object + ACL'd work dir."""

    _capabilities = IsolationCapabilities(
        process_group_termination=True,
        hard_wall_time_limit=True,
        # Enforced by ProcessRunner's bounded temporary-file reads, which work
        # unchanged because this backend still wires real file handles.
        hard_output_limit=True,
        hard_memory_limit=True,
        filesystem_isolation=True,
        # Outbound blocking is delegated to the host firewall; never claimed.
        network_disabled=False,
        low_privilege=True,
    )

    def __init__(self, *, work_root: Path | None = None) -> None:
        if os.name != "nt":
            raise SandboxConfigurationError("WindowsSandboxBackend is only available on Windows.")
        self._work_root = work_root
        self._jobs: dict[int, int] = {}
        self._managed_dirs: dict[int, Path] = {}

    @property
    def capabilities(self) -> IsolationCapabilities:
        return self._capabilities

    def firewall_configured(self) -> bool:
        """True when the firewall setup script has set JUDGE_FIREWALL_ACTIVE=1."""
        return os.environ.get(FIREWALL_ACTIVE_ENV, "") == "1"

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
        del creationflags, start_new_session  # Job objects supersede both on Windows.
        if not argv:
            raise SandboxConfigurationError("Cannot spawn an empty argv under the windows sandbox.")
        work_dir = self._prepare_work_dir(cwd)
        restricted_token = self._create_restricted_token()
        try:
            job = self._create_job(limits)
            try:
                process_info = self._start_process(
                    restricted_token,
                    argv,
                    work_dir,
                    env,
                    stdin,
                    stdout,
                    stderr,
                )
            except Exception:
                _kernel32().CloseHandle(job)
                raise
        finally:
            _kernel32().CloseHandle(restricted_token)

        process_handle = int(process_info.hProcess or 0)
        try:
            if not _kernel32().AssignProcessToJobObject(job, process_info.hProcess):
                raise SandboxConfigurationError(_last_error("AssignProcessToJobObject"))
        except Exception:
            _kernel32().TerminateProcess(process_info.hProcess, 1)
            _kernel32().CloseHandle(process_info.hProcess)
            _kernel32().CloseHandle(process_info.hThread)
            _kernel32().CloseHandle(job)
            raise
        _kernel32().CloseHandle(process_info.hThread)

        popen = self._wrap_popen(process_handle, int(process_info.dwProcessId), argv)
        self._jobs[popen.pid] = int(job)
        managed = self._managed_dirs.pop(-1, None)
        if managed is not None:
            self._managed_dirs[popen.pid] = managed
        return popen

    # ------------------------------------------------------------------ cwd --

    def _prepare_work_dir(self, cwd: Path) -> Path:
        """Confine the working directory to JUDGE_WORK_ROOT and tighten its DACL."""
        resolved = cwd.resolve()
        if self._work_root is not None:
            root = self._work_root.resolve()
            if resolved == root:
                # The work root itself is shared between tasks; give this task
                # its own dedicated subdirectory before running anything.
                dedicated = Path(tempfile.mkdtemp(prefix="judge-task-", dir=root)).resolve()
                self._managed_dirs[-1] = dedicated
                resolved = dedicated
            elif root not in resolved.parents:
                raise SandboxConfigurationError(
                    f"Refusing to execute outside JUDGE_WORK_ROOT: {resolved} is not under {root}."
                )
        self._tighten_directory_acl(resolved)
        return resolved

    def _tighten_directory_acl(self, directory: Path) -> None:
        advapi32 = _advapi32()
        keepalive: list[Any] = []
        try:
            entries = self._acl_entries(advapi32, keepalive)
            array_type = _EXPLICIT_ACCESS_W * len(entries)
            new_acl = wintypes.LPVOID()
            result = advapi32.SetEntriesInAclW(len(entries), array_type(*entries), None, ctypes.byref(new_acl))
            if result != 0:
                raise SandboxConfigurationError(f"SetEntriesInAclW failed with error {result}.")
            try:
                result = advapi32.SetNamedSecurityInfoW(
                    str(directory),
                    _SE_FILE_OBJECT,
                    _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    new_acl,
                    None,
                )
                if result != 0:
                    raise SandboxConfigurationError(f"SetNamedSecurityInfoW failed with error {result}.")
            finally:
                _kernel32().LocalFree(new_acl)
        except SandboxConfigurationError:
            _logger.error("Filesystem isolation failed for %s.", directory)
            raise
        except Exception as exc:
            _logger.error("Filesystem isolation failed for %s: %s", directory, exc)
            raise SandboxConfigurationError(
                f"Filesystem isolation failed for {directory}: {type(exc).__name__}: {exc}"
            ) from exc

    def _acl_entries(self, advapi32: Any, keepalive: list[Any]) -> list[_EXPLICIT_ACCESS_W]:
        sids = [
            self._current_user_sid(advapi32, keepalive),
            self._well_known_sid(advapi32, _SECURITY_LOCAL_SYSTEM_RID, 1, keepalive),
            self._well_known_sid(
                advapi32,
                _SECURITY_BUILTIN_DOMAIN_RID,
                2,
                keepalive,
                extra_sub_authority=_DOMAIN_ALIAS_RID_ADMINS,
            ),
        ]
        entries = []
        for sid in sids:
            entry = _EXPLICIT_ACCESS_W()
            entry.grfAccessPermissions = _GENERIC_ALL
            entry.grfAccessMode = _GRANT_ACCESS
            entry.grfInheritance = _SUB_CONTAINERS_AND_OBJECTS_INHERIT
            entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
            entry.Trustee.ptstrName = wintypes.LPWSTR(sid)
            entries.append(entry)
        return entries

    def _current_user_sid(self, advapi32: Any, keepalive: list[Any]) -> int:
        token = self._open_process_token(advapi32)
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, _TOKEN_INFO_CLASS_USER, None, 0, ctypes.byref(size))
            if size.value == 0:
                raise SandboxConfigurationError(_last_error("GetTokenInformation(TOKEN_USER) sizing"))
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, _TOKEN_INFO_CLASS_USER, buffer, size.value, ctypes.byref(size)):
                raise SandboxConfigurationError(_last_error("GetTokenInformation(TOKEN_USER)"))
            keepalive.append(buffer)
            user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents  # type: ignore[arg-type]
            return int(ctypes.cast(user.User.Sid, ctypes.c_void_p).value or 0)
        finally:
            _kernel32().CloseHandle(token)

    def _well_known_sid(
        self,
        advapi32: Any,
        first_sub_authority: int,
        sub_authority_count: int,
        keepalive: list[Any],
        *,
        extra_sub_authority: int = 0,
    ) -> int:
        authority = (wintypes.BYTE * 6)(*_SECURITY_NT_AUTHORITY)
        sid = ctypes.POINTER(ctypes.c_byte)()
        ok = advapi32.AllocateAndInitializeSid(
            authority,
            sub_authority_count,
            first_sub_authority,
            extra_sub_authority,
            0,
            0,
            0,
            0,
            0,
            0,
            ctypes.byref(sid),
        )
        if not ok:
            raise SandboxConfigurationError(_last_error("AllocateAndInitializeSid"))
        keepalive.append(sid)
        return int(ctypes.cast(sid, ctypes.c_void_p).value or 0)

    # --------------------------------------------------------------- token --

    def _open_process_token(self, advapi32: Any) -> int:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            _kernel32().GetCurrentProcess(),
            _TOKEN_QUERY | _TOKEN_DUPLICATE | _TOKEN_ASSIGN_PRIMARY,
            ctypes.byref(token),
        ):
            raise SandboxConfigurationError(_last_error("OpenProcessToken"))
        return int(token.value or 0)

    def _create_restricted_token(self) -> int:
        advapi32 = _advapi32()
        token = self._open_process_token(advapi32)
        try:
            groups, keepalive = self._token_groups(token)
            removable = [
                sid
                for sid, attributes in groups
                if (attributes & _SE_GROUP_ENABLED) and not (attributes & (_SE_GROUP_MANDATORY | _SE_GROUP_LOGON_ID))
            ]
            deleted: Any = None
            deleted_count = 0
            if removable:
                array_type = _SID_AND_ATTRIBUTES * len(removable)
                deleted = array_type()
                for index, sid in enumerate(removable):
                    deleted[index].Sid = ctypes.cast(sid, ctypes.POINTER(ctypes.c_byte))
                    deleted[index].Attributes = 0
                deleted_count = len(removable)
            restricted = wintypes.HANDLE()
            if not advapi32.CreateRestrictedToken(
                token,
                _DISABLE_MAX_PRIVILEGE,
                deleted_count,
                deleted,
                0,
                None,
                0,
                None,
                ctypes.byref(restricted),
            ):
                raise SandboxConfigurationError(_last_error("CreateRestrictedToken"))
            # The restricted token owns copies of the group SIDs, so the
            # source group buffer is no longer needed once the call returns.
            return int(restricted.value or 0)
        finally:
            _kernel32().CloseHandle(token)

    def _token_groups(self, token: int) -> tuple[list[tuple[int, int]], Any]:
        advapi32 = _advapi32()
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, _TOKEN_INFO_CLASS_GROUPS, None, 0, ctypes.byref(size))
        if size.value == 0:
            raise SandboxConfigurationError(_last_error("GetTokenInformation(TOKEN_GROUPS) sizing"))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, _TOKEN_INFO_CLASS_GROUPS, buffer, size.value, ctypes.byref(size)):
            raise SandboxConfigurationError(_last_error("GetTokenInformation(TOKEN_GROUPS)"))
        groups = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_GROUPS)).contents  # type: ignore[arg-type]
        result = [
            (
                int(ctypes.cast(groups.Groups[index].Sid, ctypes.c_void_p).value or 0),
                int(groups.Groups[index].Attributes),
            )
            for index in range(groups.GroupCount)
        ]
        return result, buffer

    # ----------------------------------------------------------------- job --

    def _create_job(self, limits: ProcessLimits | None) -> int:
        kernel32 = _kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise SandboxConfigurationError(_last_error("CreateJobObjectW"))
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if limits is not None:
            # PerProcessUserTimeLimit is a 100-nanosecond interval; wall clock
            # milliseconds are the documented input so a process burning CPU
            # across cores is still bounded by the same budget.
            info.BasicLimitInformation.PerProcessUserTimeLimit = int(limits.wall_timeout_ms) * 10_000
            limit_flags |= _JOB_OBJECT_LIMIT_PROCESS_TIME
            if limits.memory_limit_kb is not None:
                info.ProcessMemoryLimit = int(limits.memory_limit_kb) * 1024
                limit_flags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.BasicLimitInformation.LimitFlags = limit_flags
        if not kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = _last_error("SetInformationJobObject")
            kernel32.CloseHandle(job)
            raise SandboxConfigurationError(error)
        return int(job)

    # ------------------------------------------------------------- process --

    def _start_process(
        self,
        token: int,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
    ) -> _PROCESS_INFORMATION:
        advapi32 = _advapi32()
        startup_info = _STARTUPINFOW()
        startup_info.cb = ctypes.sizeof(startup_info)
        startup_info.dwFlags = _STARTF_USESTDHANDLES
        startup_info.hStdInput = self._inheritable_handle(stdin)
        startup_info.hStdOutput = self._inheritable_handle(stdout)
        startup_info.hStdError = self._inheritable_handle(stderr)

        command_line = subprocess.list2cmdline([str(argument) for argument in argv])
        command_buffer = ctypes.create_unicode_buffer(command_line)
        environment_block = self._environment_block(env)
        process_info = _PROCESS_INFORMATION()
        if not advapi32.CreateProcessWithTokenW(
            token,
            0,
            None,
            command_buffer,
            _CREATE_UNICODE_ENVIRONMENT,
            environment_block,
            str(cwd),
            ctypes.byref(startup_info),
            ctypes.byref(process_info),
        ):
            raise SandboxConfigurationError(_last_error("CreateProcessWithTokenW"))
        return process_info

    @staticmethod
    def _environment_block(env: Mapping[str, str]) -> Any | None:
        if not env:
            return None
        block = "".join(f"{key}={value}\x00" for key, value in env.items()) + "\x00"
        return ctypes.create_unicode_buffer(block)

    @staticmethod
    def _inheritable_handle(stream: BinaryIO) -> int:
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        if not _kernel32().SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT):
            raise SandboxConfigurationError(_last_error("SetHandleInformation"))
        return int(handle)

    @staticmethod
    def _wrap_popen(process_handle: int, pid: int, argv: Sequence[str]) -> subprocess.Popen[bytes]:
        """Re-wrap a raw process handle as a Popen the runner can supervise.

        The handle is real (created by CreateProcessWithTokenW), so Popen's
        own wait/poll/terminate machinery keeps working untouched.
        """
        popen = cast("subprocess.Popen[bytes]", subprocess.Popen.__new__(subprocess.Popen))
        popen.args = list(argv)
        popen.stdin = None
        popen.stdout = None
        popen.stderr = None
        popen.pid = pid
        popen.returncode = None
        popen._handle = process_handle  # type: ignore[attr-defined]
        popen._child_created = True  # type: ignore[attr-defined]
        popen._sigint_wait_secs = 0.25  # type: ignore[attr-defined]
        return popen

    # ------------------------------------------------------------- control --

    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        job = self._jobs.get(process.pid)
        if job is None:
            process.terminate()
            return
        if not _kernel32().TerminateJobObject(job, 1):
            raise SandboxConfigurationError(_last_error("TerminateJobObject"))

    def memory_usage_kb(self, process: subprocess.Popen[bytes]) -> int | None:
        job = self._jobs.get(process.pid)
        if job is None:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not _kernel32().QueryInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return None
        return int(info.PeakProcessMemoryUsed) // 1024

    def cleanup(self, process: subprocess.Popen[bytes]) -> None:
        job = self._jobs.pop(process.pid, None)
        if job is not None:
            # KILL_ON_JOB_CLOSE reaps any descendant still in the job.
            _kernel32().CloseHandle(job)
        managed = self._managed_dirs.pop(process.pid, None)
        if managed is not None:
            shutil.rmtree(managed, ignore_errors=True)
