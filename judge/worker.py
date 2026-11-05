"""Independent judge orchestration; no Web, database, Redis, or secret imports."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .comparator import compare_output
from .config import JudgeConfig, build_clean_environment
from .diagnostics import sanitize_diagnostic
from .languages import LanguageAdapter, get_language_adapter
from .process import ProcessLimits, ProcessResult, ProcessRunner
from .protocol import CaseResult, JudgeRequest, JudgeResult, JudgeStatus, TestCase
from .sandbox import LocalSubprocessBackend, SandboxBackend, SandboxConfigurationError


class JudgeWorker:
    def __init__(
        self,
        config: JudgeConfig,
        *,
        sandbox_backend: SandboxBackend | None = None,
    ) -> None:
        self.config = config
        # Prefer the backend selected by JudgeConfig (e.g. WindowsSandboxBackend
        # in production); only fall back to the local development backend when no
        # explicit choice was made and none was configured.
        if sandbox_backend is None and config.sandbox_backend is not None:
            sandbox_backend = config.sandbox_backend
        self.sandbox_backend = LocalSubprocessBackend() if sandbox_backend is None else sandbox_backend
        self.runner = ProcessRunner(config.sandbox, self.sandbox_backend)

    def judge(self, request: JudgeRequest) -> JudgeResult:
        try:
            with tempfile.TemporaryDirectory(
                prefix="judge-",
                dir=self.config.work_root,
            ) as temporary_directory:
                return self._judge_in_directory(request, Path(temporary_directory))
        except SandboxConfigurationError as exc:
            return self._system_error(request.request_id, str(exc))
        except Exception as exc:
            return self._system_error(
                request.request_id,
                f"Judge infrastructure failure ({type(exc).__name__}): {exc}",
            )

    def _judge_in_directory(self, request: JudgeRequest, work_dir: Path) -> JudgeResult:
        self._validate_request(request)
        adapter = get_language_adapter(request.language, self.config.toolchain)
        adapter.validate_tools()
        source_path = adapter.materialize_source(work_dir, request.source_code)
        sensitive_values = (
            str(work_dir),
            str(source_path),
            *self.config.toolchain.sensitive_paths(),
        )
        environment = build_clean_environment(None, work_dir)

        compile_command = adapter.compile_command(work_dir)
        if compile_command is not None:
            compilation = self.runner.run(
                compile_command,
                cwd=work_dir,
                env=environment,
                stdin_data=b"",
                limits=ProcessLimits(
                    wall_timeout_ms=request.compile_time_limit_ms,
                    output_limit_bytes=request.compile_output_limit_bytes,
                    memory_limit_kb=request.memory_limit_kb,
                ),
            )
            compile_failure = self._compile_failure(compilation, sensitive_values)
            if compile_failure is not None:
                return JudgeResult(
                    request_id=request.request_id,
                    status=compile_failure[0],
                    runtime_ms=compilation.runtime_ms,
                    memory_kb=compilation.memory_kb,
                    diagnostic=compile_failure[1],
                )

        case_results: list[CaseResult] = []
        for case in request.cases:
            result = self._run_case(
                request,
                adapter,
                work_dir,
                environment,
                case,
                sensitive_values,
            )
            case_results.append(result)
            if result.status is JudgeStatus.SE:
                break
        return self._combine_case_results(request.request_id, tuple(case_results))

    @staticmethod
    def _validate_request(request: JudgeRequest) -> None:
        for name in ("time_limit_ms", "memory_limit_kb", "compile_time_limit_ms"):
            if getattr(request, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("output_limit_bytes", "compile_output_limit_bytes"):
            if getattr(request, name) < 0:
                raise ValueError(f"{name} cannot be negative")

    def _run_case(
        self,
        request: JudgeRequest,
        adapter: LanguageAdapter,
        work_dir: Path,
        environment: dict[str, str],
        case: TestCase,
        sensitive_values: tuple[str, ...],
    ) -> CaseResult:
        execution = self.runner.run(
            adapter.run_command(work_dir),
            cwd=work_dir,
            env=environment,
            stdin_data=case.input_data.encode("utf-8"),
            limits=ProcessLimits(
                wall_timeout_ms=request.time_limit_ms,
                output_limit_bytes=request.output_limit_bytes,
                memory_limit_kb=request.memory_limit_kb,
            ),
        )
        # Runtime stderr may echo anything the program read, including hidden
        # test input. Only public samples may return the sanitized diagnostic.
        allow_runtime_diagnostic = case.is_sample
        diagnostic = (
            sanitize_diagnostic(execution.stderr, sensitive_values=sensitive_values)
            if allow_runtime_diagnostic
            else ""
        )

        if execution.infrastructure_error:
            status = JudgeStatus.SE
            # Infrastructure messages come from our runner, not the user
            # program, so they cannot echo hidden input after sanitization.
            diagnostic = sanitize_diagnostic(
                execution.infrastructure_error,
                sensitive_values=sensitive_values,
            )
        elif execution.memory_exceeded:
            status = JudgeStatus.MLE
            diagnostic = "Memory limit exceeded."
        elif execution.timed_out:
            status = JudgeStatus.TLE
            diagnostic = "Wall time limit exceeded."
        elif execution.output_exceeded:
            status = JudgeStatus.RE
            diagnostic = "Output byte limit exceeded."
        elif execution.exit_code != 0:
            status = JudgeStatus.RE
            if not diagnostic:
                diagnostic = f"Process exited with status {execution.exit_code}."
        elif not compare_output(execution.stdout, case.expected_output.encode("utf-8")):
            status = JudgeStatus.WA
            diagnostic = ""
        else:
            status = JudgeStatus.AC
            diagnostic = ""

        return CaseResult(
            case_id=case.case_id,
            status=status,
            runtime_ms=execution.runtime_ms,
            memory_kb=execution.memory_kb,
            diagnostic=diagnostic,
        )

    @staticmethod
    def _compile_failure(
        compilation: ProcessResult,
        sensitive_values: tuple[str, ...],
    ) -> tuple[JudgeStatus, str] | None:
        diagnostic = sanitize_diagnostic(
            compilation.stderr or compilation.stdout,
            sensitive_values=sensitive_values,
        )
        if compilation.infrastructure_error:
            return JudgeStatus.SE, sanitize_diagnostic(
                compilation.infrastructure_error,
                sensitive_values=sensitive_values,
            )
        if compilation.timed_out:
            return JudgeStatus.CE, "Compilation wall time limit exceeded."
        if compilation.output_exceeded:
            return JudgeStatus.CE, "Compiler output byte limit exceeded."
        if compilation.memory_exceeded:
            return JudgeStatus.CE, "Compilation memory limit exceeded."
        if compilation.exit_code != 0:
            return JudgeStatus.CE, diagnostic or "Compiler exited unsuccessfully."
        return None

    @staticmethod
    def _combine_case_results(
        request_id: str,
        case_results: tuple[CaseResult, ...],
    ) -> JudgeResult:
        first_failure = next(
            (case for case in case_results if case.status is not JudgeStatus.AC),
            None,
        )
        runtimes = [case.runtime_ms for case in case_results if case.runtime_ms is not None]
        memories = [case.memory_kb for case in case_results if case.memory_kb is not None]
        return JudgeResult(
            request_id=request_id,
            status=first_failure.status if first_failure else JudgeStatus.AC,
            case_results=case_results,
            runtime_ms=max(runtimes, default=None),
            memory_kb=max(memories, default=None),
            diagnostic=first_failure.diagnostic if first_failure else "",
        )

    def _system_error(self, request_id: str, diagnostic: str) -> JudgeResult:
        sensitive_values = self.config.toolchain.sensitive_paths()
        if self.config.work_root is not None:
            sensitive_values = (*sensitive_values, str(self.config.work_root))
        return JudgeResult(
            request_id=request_id,
            status=JudgeStatus.SE,
            diagnostic=sanitize_diagnostic(
                diagnostic,
                sensitive_values=sensitive_values,
            ),
        )


def judge(
    request: JudgeRequest,
    config: JudgeConfig,
    *,
    sandbox_backend: SandboxBackend | None = None,
) -> JudgeResult:
    return JudgeWorker(config, sandbox_backend=sandbox_backend).judge(request)
