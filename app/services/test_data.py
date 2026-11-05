"""Secure, framework-independent parsing and storage for test-data ZIP files."""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import stat
import struct
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

from app.schemas.test_data import (
    TestDataCase,
    TestDataCategory,
    TestDataError,
    TestDataFile,
    TestDataFileKind,
    TestDataLimits,
    TestDataResult,
)

type ZipSource = bytes | bytearray | memoryview | str | os.PathLike[str] | BinaryIO

_ARCHIVE_PATH = "<archive>"
_GROUPS = ("sample", "hidden")
_CATEGORY_ORDER: dict[TestDataCategory, int] = {"default": 0, "sample": 1, "hidden": 2}
_FILE_NAME_RE = re.compile(r"^([1-9][0-9]*)\.(in|out)$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_READ_CHUNK_SIZE = 64 * 1024


class TestDataValidationError(ValueError):
    """Raised when an archive fails validation, with structured errors."""

    def __init__(self, errors: Iterable[TestDataError]) -> None:
        self.errors = tuple(errors)
        if not self.errors:
            raise ValueError("At least one test-data validation error is required")
        details = "; ".join(f"{error.path}: {error.message}" for error in self.errors)
        super().__init__(details)


@dataclass(frozen=True, slots=True)
class _Member:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    member: _Member
    category: TestDataCategory
    number: int
    kind: TestDataFileKind
    stored_path: str


@dataclass(frozen=True, slots=True)
class _Pair:
    category: TestDataCategory
    number: int
    input: _Candidate
    output: _Candidate


@dataclass(frozen=True, slots=True)
class _ParsedArchive:
    result: TestDataResult
    # Keys are generated output paths, never paths supplied by the archive.
    contents: dict[str, bytes]


class TestDataService:
    """Validate ZIP test data and publish it to an immutable version directory."""

    def __init__(self, limits: TestDataLimits | None = None) -> None:
        self.limits = limits or TestDataLimits()

    def validate(self, source: ZipSource) -> TestDataResult:
        """Validate an archive without writing any of its contents."""

        return self._parse(source).result

    def store(self, source: ZipSource, version_dir: str | os.PathLike[str]) -> TestDataResult:
        """Validate and atomically store an archive in a new version directory.

        Existing destinations are never replaced, including symbolic links and
        empty directories. Files are named solely from their category and number.
        """

        parsed = self._parse(source)
        self._store_parsed(parsed, version_dir)
        return parsed.result

    def _parse(self, source: ZipSource) -> _ParsedArchive:
        archive_bytes = self._read_source(source)
        self._reject_raw_path_bypasses(archive_bytes)
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                return self._parse_open_archive(archive)
        except TestDataValidationError:
            raise
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError, ValueError) as exc:
            self._fail("invalid_zip", _ARCHIVE_PATH, f"Not a readable ZIP archive: {exc}")

    def _parse_open_archive(self, archive: zipfile.ZipFile) -> _ParsedArchive:
        errors: list[TestDataError] = []
        files: list[_Member] = []
        directories: list[_Member] = []
        seen_file_names: set[str] = set()
        declared_total = 0

        infos = archive.infolist()
        file_count = sum(not info.is_dir() for info in infos)
        if file_count > self.limits.max_test_cases * 2:
            self._fail(
                "too_many_test_cases",
                _ARCHIVE_PATH,
                f"Archive contains {file_count} files; at most {self.limits.max_test_cases * 2} are allowed",
            )

        for info in infos:
            path = info.filename or _ARCHIVE_PATH
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                errors.append(self._error("symlink", path, "Symbolic links are not allowed"))
                continue
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                errors.append(self._error("special_file", path, "Special filesystem entries are not allowed"))
                continue

            parts = self._safe_parts(info, errors)
            if parts is None:
                continue
            member = _Member(info=info, parts=parts)
            if info.is_dir():
                directories.append(member)
                continue

            if info.flag_bits & 0x1:
                errors.append(self._error("encrypted_file", path, "Encrypted files are not supported"))
                continue
            if info.filename in seen_file_names:
                errors.append(self._error("duplicate_file", path, "Duplicate archive member"))
                continue
            seen_file_names.add(info.filename)

            if info.file_size == 0:
                errors.append(self._error("empty_file", path, "Test-data files must not be empty"))
                continue
            if info.file_size > self.limits.max_file_bytes:
                errors.append(
                    self._error(
                        "file_too_large",
                        path,
                        f"Uncompressed size exceeds {self.limits.max_file_bytes} bytes",
                    )
                )
                continue
            if info.compress_size == 0 or info.file_size / info.compress_size > self.limits.max_compression_ratio:
                errors.append(
                    self._error(
                        "suspicious_compression_ratio",
                        path,
                        f"Compression ratio exceeds {self.limits.max_compression_ratio}",
                    )
                )
                continue

            declared_total += info.file_size
            files.append(member)

        if declared_total > self.limits.max_total_bytes:
            errors.append(
                self._error(
                    "total_too_large",
                    _ARCHIVE_PATH,
                    f"Total uncompressed size exceeds {self.limits.max_total_bytes} bytes",
                )
            )
        self._raise_if_errors(errors)

        pairs = self._classify_and_pair(files, directories)
        contents: dict[str, bytes] = {}
        metadata: dict[tuple[TestDataCategory, int, TestDataFileKind], TestDataFile] = {}
        actual_total = 0

        for pair in pairs:
            for candidate in (pair.input, pair.output):
                info = candidate.member.info
                path = info.filename
                content = self._read_member(archive, candidate.member, errors)
                if content is None:
                    continue
                actual_total += len(content)
                if actual_total > self.limits.max_total_bytes:
                    errors.append(
                        self._error(
                            "total_too_large",
                            _ARCHIVE_PATH,
                            f"Actual uncompressed size exceeds {self.limits.max_total_bytes} bytes",
                        )
                    )
                    self._raise_if_errors(errors)

                if not content:
                    errors.append(self._error("empty_file", path, "Test-data files must not be empty"))
                    continue
                try:
                    content.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    errors.append(self._error("invalid_utf8", path, f"File is not valid UTF-8 at byte {exc.start}"))

                contents[candidate.stored_path] = content
                metadata[(pair.category, pair.number, candidate.kind)] = TestDataFile(
                    path=path,
                    stored_path=candidate.stored_path,
                    category=pair.category,
                    number=pair.number,
                    kind=candidate.kind,
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )

        self._raise_if_errors(errors)
        cases = tuple(
            TestDataCase(
                category=pair.category,
                number=pair.number,
                input=metadata[(pair.category, pair.number, "input")],
                output=metadata[(pair.category, pair.number, "output")],
            )
            for pair in pairs
        )
        result = TestDataResult(
            test_count=len(cases),
            sample_count=sum(case.category == "sample" for case in cases),
            hidden_count=sum(case.category == "hidden" for case in cases),
            cases=cases,
        )
        return _ParsedArchive(result=result, contents=contents)

    def _classify_and_pair(self, files: list[_Member], directories: list[_Member]) -> list[_Pair]:
        errors: list[TestDataError] = []
        candidates: list[_Candidate] = []
        layout: tuple[str | None, bool] | None = None
        seen_logical_paths: set[str] = set()

        for member in files:
            parts = member.parts
            path = member.info.filename
            top: str | None
            grouped: bool
            category: TestDataCategory
            file_name: str

            if len(parts) == 1:
                top, grouped, category, file_name = None, False, "default", parts[0]
            elif len(parts) == 2 and parts[0] in _GROUPS:
                top, grouped, category, file_name = None, True, parts[0], parts[1]  # type: ignore[assignment]
            elif len(parts) == 2:
                top, grouped, category, file_name = parts[0], False, "default", parts[1]
            elif len(parts) == 3 and parts[1] in _GROUPS:
                top, grouped, category, file_name = parts[0], True, parts[1], parts[2]  # type: ignore[assignment]
            else:
                errors.append(
                    self._error(
                        "unexpected_file",
                        path,
                        "Expected N.in/N.out at the root, in one top-level directory, or in sample/hidden",
                    )
                )
                continue

            match = _FILE_NAME_RE.fullmatch(file_name)
            if match is None:
                errors.append(self._error("invalid_filename", path, "Expected a canonical N.in or N.out file name"))
                continue

            current_layout = (top, grouped)
            if layout is None:
                layout = current_layout
            elif layout != current_layout:
                errors.append(self._error("mixed_layout", path, "All files must use one consistent archive layout"))
                continue

            number = int(match.group(1))
            kind: TestDataFileKind = "input" if match.group(2) == "in" else "output"
            stored_path = f"{number}.{match.group(2)}"
            if grouped:
                stored_path = f"{category}/{stored_path}"
            if stored_path in seen_logical_paths:
                errors.append(self._error("duplicate_file", path, "Duplicate test-data file"))
                continue
            seen_logical_paths.add(stored_path)
            candidates.append(
                _Candidate(
                    member=member,
                    category=category,
                    number=number,
                    kind=kind,
                    stored_path=stored_path,
                )
            )

        self._validate_directories(directories, layout, errors)
        self._raise_if_errors(errors)

        grouped_candidates: dict[TestDataCategory, dict[int, dict[TestDataFileKind, _Candidate]]] = {}
        for candidate in candidates:
            grouped_candidates.setdefault(candidate.category, {}).setdefault(candidate.number, {})[candidate.kind] = (
                candidate
            )

        if not grouped_candidates:
            self._fail("no_test_cases", _ARCHIVE_PATH, "Archive contains no test-data files")

        total_cases = sum(len(numbers) for numbers in grouped_candidates.values())
        if total_cases > self.limits.max_test_cases:
            self._fail(
                "too_many_test_cases",
                _ARCHIVE_PATH,
                f"Archive contains {total_cases} test cases; limit is {self.limits.max_test_cases}",
            )

        pairs: list[_Pair] = []
        for category in sorted(grouped_candidates, key=_CATEGORY_ORDER.__getitem__):
            numbers = grouped_candidates[category]
            for number in sorted(numbers):
                pair = numbers[number]
                for kind, extension in (("input", "in"), ("output", "out")):
                    if kind not in pair:
                        logical_path = f"{number}.{extension}"
                        if category != "default":
                            logical_path = f"{category}/{logical_path}"
                        errors.append(
                            self._error("missing_pair", logical_path, f"Missing {kind} file for test case {number}")
                        )

            expected = set(range(1, max(numbers) + 1))
            if set(numbers) != expected:
                errors.append(
                    self._error(
                        "non_contiguous",
                        category,
                        f"Test cases must be numbered continuously from 1; found {sorted(numbers)}",
                    )
                )

            for number in sorted(numbers):
                pair = numbers[number]
                if "input" in pair and "output" in pair:
                    pairs.append(_Pair(category=category, number=number, input=pair["input"], output=pair["output"]))

        self._raise_if_errors(errors)
        return pairs

    def _validate_directories(
        self,
        directories: list[_Member],
        layout: tuple[str | None, bool] | None,
        errors: list[TestDataError],
    ) -> None:
        if not directories:
            return
        allowed: set[tuple[str, ...]] = set()
        if layout is not None:
            top, grouped = layout
            if top is not None:
                allowed.add((top,))
            if grouped:
                prefix = (top,) if top is not None else ()
                allowed.update(prefix + (group,) for group in _GROUPS)

        for directory in directories:
            if directory.parts not in allowed:
                errors.append(
                    self._error(
                        "unexpected_directory",
                        directory.info.filename,
                        "Directory is outside the selected archive layout",
                    )
                )

    def _read_member(
        self,
        archive: zipfile.ZipFile,
        member: _Member,
        errors: list[TestDataError],
    ) -> bytes | None:
        path = member.info.filename
        chunks: list[bytes] = []
        size = 0
        try:
            with archive.open(member.info, "r") as stream:
                while True:
                    chunk = stream.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.limits.max_file_bytes:
                        errors.append(
                            self._error(
                                "file_too_large",
                                path,
                                f"Actual uncompressed size exceeds {self.limits.max_file_bytes} bytes",
                            )
                        )
                        return None
                    chunks.append(chunk)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError) as exc:
            errors.append(self._error("unreadable_file", path, f"Unable to decompress file: {exc}"))
            return None
        return b"".join(chunks)

    def _read_source(self, source: ZipSource) -> bytes:
        if isinstance(source, (bytes, bytearray, memoryview)):
            data = bytes(source)
            if len(data) > self.limits.max_archive_bytes:
                self._fail_archive_too_large(len(data))
            return data

        try:
            if isinstance(source, (str, os.PathLike)):
                with Path(source).open("rb") as stream:
                    return self._read_stream(stream)
            return self._read_stream(source)
        except TestDataValidationError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            self._fail("archive_read_failed", _ARCHIVE_PATH, f"Unable to read archive: {exc}")

    def _read_stream(self, stream: BinaryIO) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = stream.read(min(_READ_CHUNK_SIZE, self.limits.max_archive_bytes + 1 - size))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                self._fail("archive_read_failed", _ARCHIVE_PATH, "Archive stream must be opened in binary mode")
            chunks.append(chunk)
            size += len(chunk)
            if size > self.limits.max_archive_bytes:
                self._fail_archive_too_large(size)
        return b"".join(chunks)

    def _store_parsed(self, parsed: _ParsedArchive, version_dir: str | os.PathLike[str]) -> None:
        destination = Path(version_dir)
        if os.path.lexists(destination):
            raise FileExistsError(f"Immutable test-data destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))

        try:
            for case in parsed.result.cases:
                for file in (case.input, case.output):
                    output_path = temporary.joinpath(*file.stored_path.split("/"))
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb") as stream:
                        stream.write(parsed.contents[file.stored_path])
                        stream.flush()
                        os.fsync(stream.fileno())
            if os.path.lexists(destination):
                raise FileExistsError(f"Immutable test-data destination already exists: {destination}")
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _reject_raw_path_bypasses(self, data: bytes) -> None:
        """Inspect raw central-directory names before zipfile normalizes them.

        On Windows, ZipInfo converts backslashes to slashes while reading a ZIP.
        Checking the original central-directory bytes is therefore necessary to
        distinguish a safe nested path from a backslash-based traversal bypass.
        Malformed structures are left for ZipFile to reject as invalid ZIPs.
        """

        eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65_557))
        if eocd < 0 or eocd + 22 > len(data):
            return
        try:
            _, _, _, _, directory_size, directory_offset, _ = struct.unpack_from("<4H2LH", data, eocd + 4)
            central_start = eocd - directory_size
            if directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
                locator = eocd - 20
                if locator < 0 or data[locator : locator + 4] != b"PK\x06\x07":
                    return
                eocd64_offset = struct.unpack_from("<Q", data, locator + 8)[0]
                if data[eocd64_offset : eocd64_offset + 4] != b"PK\x06\x06":
                    return
                directory_size, directory_offset = struct.unpack_from("<2Q", data, eocd64_offset + 40)
                central_start = eocd64_offset - directory_size
            if central_start < 0 or central_start + directory_size > len(data):
                return

            position = central_start
            central_end = central_start + directory_size
            while position < central_end:
                if position + 46 > central_end or data[position : position + 4] != b"PK\x01\x02":
                    return
                flags = struct.unpack_from("<H", data, position + 8)[0]
                name_length, extra_length, comment_length = struct.unpack_from("<3H", data, position + 28)
                name_start = position + 46
                name_end = name_start + name_length
                next_position = name_end + extra_length + comment_length
                if next_position > central_end:
                    return
                raw_name = data[name_start:name_end]
                if b"\\" in raw_name or b"\x00" in raw_name:
                    encoding = "utf-8" if flags & 0x800 else "cp437"
                    path = raw_name.decode(encoding, errors="replace")
                    self._fail("unsafe_path", path, "Unsafe raw archive member name")
                position = next_position
        except (struct.error, IndexError):
            return

    def _safe_parts(self, info: zipfile.ZipInfo, errors: list[TestDataError]) -> tuple[str, ...] | None:
        name = info.filename
        if not name or "\x00" in name or "\\" in name or name.startswith("/"):
            errors.append(self._error("unsafe_path", name or _ARCHIVE_PATH, "Unsafe archive path"))
            return None

        directory_name = name[:-1] if info.is_dir() and name.endswith("/") else name
        raw_parts = directory_name.split("/")
        if any(not part or part in (".", "..") or _DRIVE_RE.match(part) for part in raw_parts):
            errors.append(self._error("unsafe_path", name, "Unsafe or non-canonical archive path"))
            return None
        return tuple(raw_parts)

    def _fail_archive_too_large(self, actual_size: int) -> NoReturn:
        self._fail(
            "archive_too_large",
            _ARCHIVE_PATH,
            f"Archive size {actual_size} exceeds {self.limits.max_archive_bytes} bytes",
        )

    @staticmethod
    def _error(code: str, path: str, message: str) -> TestDataError:
        return TestDataError(code=code, path=path, message=message)

    @staticmethod
    def _raise_if_errors(errors: list[TestDataError]) -> None:
        if errors:
            raise TestDataValidationError(errors)

    @staticmethod
    def _fail(code: str, path: str, message: str) -> NoReturn:
        raise TestDataValidationError([TestDataError(code=code, path=path, message=message)])


def validate_test_data(source: ZipSource, *, limits: TestDataLimits | None = None) -> TestDataResult:
    """Convenience wrapper around :meth:`TestDataService.validate`."""

    return TestDataService(limits).validate(source)


def store_test_data(
    source: ZipSource,
    version_dir: str | os.PathLike[str],
    *,
    limits: TestDataLimits | None = None,
) -> TestDataResult:
    """Convenience wrapper around :meth:`TestDataService.store`."""

    return TestDataService(limits).store(source, version_dir)


__all__ = [
    "TestDataService",
    "TestDataValidationError",
    "ZipSource",
    "store_test_data",
    "validate_test_data",
]
