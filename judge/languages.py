"""Language-specific source layout and fixed toolchain invocations."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from .config import ToolchainConfig

SUPPORTED_LANGUAGES = ("c", "cpp", "java", "python")


class LanguageAdapter(ABC):
    language: str
    source_name: str

    def __init__(self, toolchain: ToolchainConfig) -> None:
        self.toolchain = toolchain

    def materialize_source(self, work_dir: Path, source_code: str) -> Path:
        source_path = work_dir / self.source_name
        source_path.write_text(source_code, encoding="utf-8", newline="")
        return source_path

    @abstractmethod
    def validate_tools(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def compile_command(self, work_dir: Path) -> list[str] | None:
        raise NotImplementedError

    @abstractmethod
    def run_command(self, work_dir: Path) -> list[str]:
        raise NotImplementedError


class NativeAdapter(LanguageAdapter):
    def __init__(self, toolchain: ToolchainConfig, *, language: str, standard: str) -> None:
        super().__init__(toolchain)
        self.language = language
        self.standard = standard
        self.source_name = "Main.c" if language == "c" else "Main.cpp"
        self.executable_name = "program.exe" if os.name == "nt" else "program"

    def validate_tools(self) -> None:
        if self.language == "c":
            self.toolchain.gcc()
        else:
            self.toolchain.gxx()

    def compile_command(self, work_dir: Path) -> list[str]:
        compiler = self.toolchain.gcc() if self.language == "c" else self.toolchain.gxx()
        return [
            str(compiler),
            f"-std={self.standard}",
            "-O2",
            self.source_name,
            "-o",
            self.executable_name,
        ]

    def run_command(self, work_dir: Path) -> list[str]:
        return [str(work_dir / self.executable_name)]


class JavaAdapter(LanguageAdapter):
    language = "java"
    source_name = "Main.java"

    def validate_tools(self) -> None:
        self.toolchain.javac()
        self.toolchain.java()

    def compile_command(self, work_dir: Path) -> list[str]:
        # The unified production baseline compiles with a modern JDK but keeps
        # the Java 8 language and API surface for cross-platform consistency.
        return [str(self.toolchain.javac()), "--release", "8", "-encoding", "UTF-8", self.source_name]

    def run_command(self, work_dir: Path) -> list[str]:
        return [str(self.toolchain.java()), "-cp", ".", "Main"]


class PythonAdapter(LanguageAdapter):
    language = "python"
    source_name = "Main.py"

    def validate_tools(self) -> None:
        self.toolchain.user_python()

    def compile_command(self, work_dir: Path) -> list[str] | None:
        # Syntax-check the source before running so that SyntaxError surfaces
        # as CE rather than a runtime RE.
        return [
            str(self.toolchain.user_python()),
            "-I",
            "-B",
            "-m",
            "py_compile",
            self.source_name,
        ]

    def run_command(self, work_dir: Path) -> list[str]:
        # This path is never inferred from sys.executable: it is the separately
        # configured user Python (the production target is Python 3.8.6).
        return [str(self.toolchain.user_python()), "-I", "-B", self.source_name]


def get_language_adapter(language: str, toolchain: ToolchainConfig) -> LanguageAdapter:
    normalised = language.lower()
    if normalised == "c":
        return NativeAdapter(toolchain, language="c", standard="c99")
    if normalised == "cpp":
        return NativeAdapter(toolchain, language="cpp", standard="c++11")
    if normalised == "java":
        return JavaAdapter(toolchain)
    if normalised == "python":
        return PythonAdapter(toolchain)
    raise ValueError(f"Unsupported language {language!r}; expected one of {', '.join(SUPPORTED_LANGUAGES)}.")
