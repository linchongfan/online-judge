from __future__ import annotations

import sys
from pathlib import Path

from judge.config import JudgeConfig, ToolchainConfig
from judge.protocol import JudgeRequest, JudgeStatus, TestCase
from judge.sandbox import SandboxPolicy
from judge.worker import JudgeWorker


def _config(tmp_path: Path, policy: SandboxPolicy | None = None) -> JudgeConfig:
    return JudgeConfig(
        toolchain=ToolchainConfig(user_python_path=Path(sys.executable)),
        sandbox=policy or SandboxPolicy.development(allow_unsafe_tests=True),
        work_root=tmp_path,
    )


def test_harmless_complete_python_program_end_to_end_and_temp_cleanup(tmp_path: Path) -> None:
    request = JudgeRequest(
        request_id="safe-python",
        language="python",
        source_code=("import sys\ndata = sys.stdin.read()\nsys.stdout.write(data.upper() + '  \\n\\n')\n"),
        cases=(
            TestCase("1", "hello", "HELLO"),
            TestCase("2", "world", "WORLD\n"),
        ),
        time_limit_ms=2_000,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)

    assert result.status is JudgeStatus.AC
    assert [case.status for case in result.case_results] == [JudgeStatus.AC, JudgeStatus.AC]
    assert all(case.runtime_ms is not None for case in result.case_results)
    assert list(tmp_path.iterdir()) == []


def test_wrong_answer_does_not_leak_expected_or_actual_output(tmp_path: Path) -> None:
    request = JudgeRequest(
        request_id="wa",
        language="python",
        source_code="print('actual-secret-output')",
        cases=(TestCase("1", "", "expected-secret-output"),),
        time_limit_ms=2_000,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.WA
    assert result.diagnostic == ""
    assert "secret" not in repr(result.to_dict())


def test_hidden_case_runtime_error_does_not_echo_stderr(tmp_path: Path) -> None:
    # A malicious program can copy hidden stdin to stderr and exit non-zero;
    # hidden cases must never return the user program's runtime stderr.
    request = JudgeRequest(
        request_id="hidden-re",
        language="python",
        source_code=(
            "import sys\n"
            "data = sys.stdin.read()\n"
            "sys.stderr.write(data)\n"
            "sys.exit(3)\n"
        ),
        cases=(TestCase("1", "hidden-input-secret", "", is_sample=False),),
        time_limit_ms=2_000,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.RE
    assert "hidden-input-secret" not in repr(result.to_dict())
    assert "hidden-input-secret" not in result.diagnostic


def test_sample_run_keeps_sanitized_stderr(tmp_path: Path) -> None:
    request = JudgeRequest(
        request_id="sample-re",
        language="python",
        source_code="import sys\nsys.stderr.write('division by zero')\nsys.exit(1)\n",
        cases=(TestCase("1", "", "", is_sample=True),),
        time_limit_ms=2_000,
        is_sample_run=True,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.RE
    assert "division by zero" in result.diagnostic
    assert str(tmp_path) not in result.diagnostic


def test_official_submission_sample_case_does_not_echo_stderr(tmp_path: Path) -> None:
    # Sample cases ride along in official submissions. Without the request-level
    # is_sample_run boundary, a sample case that follows a hidden case could
    # echo hidden input (read from a stash) through its returned stderr.
    request = JudgeRequest(
        request_id="official-sample-re",
        language="python",
        source_code="import sys\nsys.stderr.write('sample-stderr-text')\nsys.exit(1)\n",
        cases=(TestCase("1", "", "", is_sample=True),),
        time_limit_ms=2_000,
        is_sample_run=False,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.RE
    assert "sample-stderr-text" not in result.diagnostic
    assert "sample-stderr-text" not in repr(result.to_dict())


def test_official_submission_cannot_smuggle_hidden_input_to_later_sample(tmp_path: Path) -> None:
    # Adversarial: the hidden case stashes its stdin in the temp dir; the later
    # public sample case reads the stash and echoes it to stderr. Both the
    # per-case scratch directory (stash must not survive) and the request-level
    # stderr boundary (never returned for official runs) must hold.
    exploit = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "data = sys.stdin.read()\n"
        "stash = Path(os.environ['TMP']) / 'stash'\n"
        "if stash.exists():\n"
        "    sys.stderr.write(stash.read_text())\n"
        "    sys.exit(3)\n"
        "stash.write_text(data)\n"
        "sys.stdout.write(data)\n"
    )
    request = JudgeRequest(
        request_id="official-smuggle",
        language="python",
        source_code=exploit,
        cases=(
            TestCase("1", "hidden-input-secret", "hidden-input-secret", is_sample=False),
            TestCase("2", "hello", "hello", is_sample=True),
        ),
        time_limit_ms=2_000,
        is_sample_run=False,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.AC
    assert [case.status for case in result.case_results] == [JudgeStatus.AC, JudgeStatus.AC]
    assert "hidden-input-secret" not in repr(result.to_dict())


def test_each_case_runs_in_fresh_scratch_directory(tmp_path: Path) -> None:
    # If cases shared a working directory, the marker written by case 1 would
    # be visible to case 2 and produce CONTAMINATED output.
    program = (
        "import sys\n"
        "from pathlib import Path\n"
        "marker = Path('marker.txt')\n"
        "if marker.exists():\n"
        "    sys.stdout.write('CONTAMINATED')\n"
        "else:\n"
        "    marker.write_text('x')\n"
        "    sys.stdout.write(sys.stdin.read())\n"
    )
    request = JudgeRequest(
        request_id="fresh-scratch",
        language="python",
        source_code=program,
        cases=(TestCase("1", "first", "first"), TestCase("2", "second", "second")),
        time_limit_ms=2_000,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.AC
    assert [case.status for case in result.case_results] == [JudgeStatus.AC, JudgeStatus.AC]


def test_cases_execute_in_deterministic_case_id_order(tmp_path: Path) -> None:
    # Result order must be deterministic regardless of caller/DB ordering.
    request = JudgeRequest(
        request_id="deterministic-order",
        language="python",
        source_code="import sys\nsys.stdout.write(sys.stdin.read())\n",
        cases=(TestCase("2", "b", "b"), TestCase("1", "a", "a"), TestCase("10", "c", "c")),
        time_limit_ms=2_000,
    )
    result = JudgeWorker(_config(tmp_path)).judge(request)
    assert result.status is JudgeStatus.AC
    assert [case.case_id for case in result.case_results] == ["1", "2", "10"]


def test_production_without_isolation_returns_se_and_executes_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    request = JudgeRequest(
        request_id="unsafe-production",
        language="python",
        source_code=f"from pathlib import Path; Path({str(marker)!r}).touch()",
        cases=(TestCase("1", "", ""),),
    )
    result = JudgeWorker(
        _config(tmp_path, SandboxPolicy.production()),
    ).judge(request)
    assert result.status is JudgeStatus.SE
    assert "Production execution refused" in result.diagnostic
    assert not marker.exists()
    assert list(tmp_path.iterdir()) == []
