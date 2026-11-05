from __future__ import annotations

import os
from pathlib import Path

import pytest

from judge.config import (
    GCC_ENV,
    GXX_ENV,
    JAVA_ENV,
    JAVAC_ENV,
    USER_PYTHON_ENV,
    JudgeConfig,
    ToolchainConfig,
    ToolchainConfigurationError,
    build_clean_environment,
)
from judge.diagnostics import sanitize_diagnostic
from judge.languages import get_language_adapter
from judge.sandbox import (
    IsolationCapabilities,
    LocalSubprocessBackend,
    SandboxConfigurationError,
    SandboxMode,
    SandboxPolicy,
)


def test_toolchain_paths_are_loaded_from_explicit_environment_variables() -> None:
    env = {
        GCC_ENV: r"C:\TDM-GCC\bin\gcc.exe",
        GXX_ENV: r"C:\TDM-GCC\bin\g++.exe",
        JAVAC_ENV: r"C:\jdk1.8\bin\javac.exe",
        JAVA_ENV: r"C:\jdk1.8\bin\java.exe",
        USER_PYTHON_ENV: r"C:\Python38\python.exe",
    }
    toolchain = ToolchainConfig.from_env(env)
    assert toolchain.gcc_path == Path(env[GCC_ENV])
    assert toolchain.gxx_path == Path(env[GXX_ENV])
    assert toolchain.javac_path == Path(env[JAVAC_ENV])
    assert toolchain.java_path == Path(env[JAVA_ENV])
    assert toolchain.user_python_path == Path(env[USER_PYTHON_ENV])
    assert ToolchainConfig.from_env({}).user_python_path is None


def test_missing_or_relative_tool_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolchainConfigurationError, match="JUDGE_USER_PYTHON_PATH"):
        ToolchainConfig().user_python()
    with pytest.raises(ToolchainConfigurationError, match="absolute"):
        ToolchainConfig(user_python_path=Path("python.exe")).user_python()


def test_language_commands_pin_required_standards_and_java_entry(tmp_path: Path) -> None:
    def executable(name: str) -> Path:
        path = tmp_path / name
        path.touch()
        return path

    toolchain = ToolchainConfig(
        gcc_path=executable("gcc"),
        gxx_path=executable("g++"),
        javac_path=executable("javac"),
        java_path=executable("java"),
        user_python_path=executable("python38"),
    )
    c = get_language_adapter("c", toolchain)
    cpp = get_language_adapter("cpp", toolchain)
    java = get_language_adapter("java", toolchain)
    python = get_language_adapter("python", toolchain)

    assert "-std=c99" in c.compile_command(tmp_path)
    assert "-std=c++11" in cpp.compile_command(tmp_path)
    assert c.source_name == "Main.c"
    assert cpp.source_name == "Main.cpp"
    assert java.source_name == "Main.java"
    assert "--release" in java.compile_command(tmp_path)
    assert "8" in java.compile_command(tmp_path)
    assert java.run_command(tmp_path)[-2:] == [".", "Main"]
    py_compile_cmd = python.compile_command(tmp_path)
    assert py_compile_cmd is not None
    assert py_compile_cmd[-3:] == ["-m", "py_compile", "Main.py"]
    assert python.run_command(tmp_path) == [
        str(toolchain.user_python_path),
        "-I",
        "-B",
        "Main.py",
    ]


def test_policy_defaults_closed_and_production_requires_real_capabilities() -> None:
    local = LocalSubprocessBackend()
    with pytest.raises(SandboxConfigurationError, match="Development execution is disabled"):
        SandboxPolicy.development().ensure_execution_allowed(local)
    SandboxPolicy.development(allow_unsafe_tests=True).ensure_execution_allowed(local)

    with pytest.raises(SandboxConfigurationError, match="Production execution refused") as error:
        SandboxPolicy.production().ensure_execution_allowed(local)
    message = str(error.value)
    assert "hard_memory_limit" in message
    assert "network_disabled" in message
    assert "low_privilege" in message


def test_environment_policy_and_clean_environment_do_not_inherit_secrets(tmp_path: Path) -> None:
    config = JudgeConfig.from_env(
        {
            "JUDGE_ENV": "production",
            "JUDGE_ALLOW_UNSAFE_TESTS": "1",
            "JUDGE_WORK_ROOT": str(tmp_path),
        }
    )
    assert config.sandbox.mode is SandboxMode.PRODUCTION
    assert not config.sandbox.allow_unsafe_tests

    clean = build_clean_environment(
        {"PATH": r"C:\tools", "DATABASE_URL": "secret", "SECRET_KEY": "secret"},
        tmp_path,
    )
    expected = {
        "PATH": r"C:\tools",
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "HOME": str(tmp_path),
    }
    if os.name != "nt":
        expected["PATH"] = "/usr/bin:/bin"
    assert clean == expected


def test_full_capability_declaration_is_an_explicit_adapter_contract() -> None:
    class FullyConfiguredBackend:
        capabilities = IsolationCapabilities(
            process_group_termination=True,
            hard_wall_time_limit=True,
            hard_output_limit=True,
            hard_memory_limit=True,
            filesystem_isolation=True,
            network_disabled=True,
            low_privilege=True,
        )

    SandboxPolicy.production().ensure_execution_allowed(FullyConfiguredBackend())


def test_diagnostic_redacts_paths_secrets_control_codes_and_length(tmp_path: Path) -> None:
    sensitive = str(tmp_path / "judge-private")
    diagnostic = sanitize_diagnostic(
        f"token=secret\x00 {sensitive}\\Main.py " + "x" * 30,
        sensitive_values=(sensitive, "secret"),
        max_chars=50,
    )
    assert "secret" not in diagnostic
    assert sensitive not in diagnostic
    assert "<redacted>" in diagnostic
    assert "\x00" not in diagnostic
    assert len(diagnostic) <= len("x" * 50) + len("\n...[truncated]")
