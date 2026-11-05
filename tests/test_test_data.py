from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pytest

from app.schemas.test_data import TestDataLimits as Limits
from app.services.test_data import TestDataService as Service
from app.services.test_data import TestDataValidationError as ValidationError
from app.services.test_data import store_test_data, validate_test_data

ArchiveEntry = tuple[str, bytes] | zipfile.ZipInfo


def make_zip(entries: Iterable[ArchiveEntry]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                archive.writestr(entry, b"target")
            else:
                name, content = entry
                archive.writestr(name, content)
    return buffer.getvalue()


def error_codes(data: bytes, *, limits: Limits | None = None) -> set[str]:
    with pytest.raises(ValidationError) as caught:
        validate_test_data(data, limits=limits)
    return {error.code for error in caught.value.errors}


def test_flat_archive_returns_counts_sizes_and_hashes() -> None:
    data = make_zip(
        [
            ("1.in", b"1 2\n"),
            ("1.out", b"3\n"),
            ("2.in", b"4 5\n"),
            ("2.out", b"9\n"),
        ]
    )

    result = validate_test_data(data)

    assert result.test_count == 2
    assert result.sample_count == 0
    assert result.hidden_count == 0
    assert [case.number for case in result.cases] == [1, 2]
    assert result.cases[0].input.size == 4
    assert result.cases[0].input.sha256 == hashlib.sha256(b"1 2\n").hexdigest()
    assert result.cases[0].output.sha256 == hashlib.sha256(b"3\n").hexdigest()
    assert [file.stored_path for file in result.files] == ["1.in", "1.out", "2.in", "2.out"]


def test_single_top_level_directory_is_supported() -> None:
    data = make_zip([("problem/1.in", b"in\n"), ("problem/1.out", b"out\n")])

    result = validate_test_data(data)

    assert result.test_count == 1
    assert result.cases[0].input.path == "problem/1.in"
    assert result.cases[0].input.stored_path == "1.in"


@pytest.mark.parametrize("prefix", ["", "problem/"])
def test_sample_hidden_compatibility_layout(prefix: str) -> None:
    data = make_zip(
        [
            (f"{prefix}sample/1.in", b"s1 in"),
            (f"{prefix}sample/1.out", b"s1 out"),
            (f"{prefix}sample/2.in", b"s2 in"),
            (f"{prefix}sample/2.out", b"s2 out"),
            (f"{prefix}hidden/1.in", b"h1 in"),
            (f"{prefix}hidden/1.out", b"h1 out"),
        ]
    )

    result = validate_test_data(data)

    assert (result.test_count, result.sample_count, result.hidden_count) == (3, 2, 1)
    assert [case.category for case in result.cases] == ["sample", "sample", "hidden"]


def test_store_generates_names_and_atomically_publishes_new_directory(tmp_path: Path) -> None:
    data = make_zip(
        [
            ("untrusted/sample/1.in", b"input"),
            ("untrusted/sample/1.out", b"output"),
            ("untrusted/hidden/1.in", b"secret in"),
            ("untrusted/hidden/1.out", b"secret out"),
        ]
    )
    destination = tmp_path / "versions" / "v1"

    result = store_test_data(data, destination)

    assert result.test_count == 2
    assert (destination / "sample" / "1.in").read_bytes() == b"input"
    assert (destination / "sample" / "1.out").read_bytes() == b"output"
    assert (destination / "hidden" / "1.in").read_bytes() == b"secret in"
    assert not (destination / "untrusted").exists()
    assert not list(destination.parent.glob(f".{destination.name}.tmp-*"))


def test_missing_pair_has_a_locatable_error() -> None:
    codes = error_codes(make_zip([("1.in", b"in"), ("2.in", b"in"), ("2.out", b"out")]))

    assert codes == {"missing_pair"}
    with pytest.raises(ValidationError) as caught:
        validate_test_data(make_zip([("sample/1.in", b"in")]))
    assert caught.value.errors[0].path == "sample/1.out"
    assert caught.value.errors[0].code == "missing_pair"


def test_non_contiguous_numbers_are_rejected() -> None:
    data = make_zip([("1.in", b"a"), ("1.out", b"b"), ("3.in", b"c"), ("3.out", b"d")])

    assert "non_contiguous" in error_codes(data)


@pytest.mark.parametrize("name", ["../1.in", "/absolute/1.in", "C:/1.in", "top/./1.in"])
def test_unsafe_paths_are_rejected(name: str) -> None:
    assert "unsafe_path" in error_codes(make_zip([(name, b"input")]))


def test_backslash_path_is_rejected_without_zipfile_normalization() -> None:
    member = zipfile.ZipInfo("placeholder")
    member.filename = "top\\1.in"

    assert "unsafe_path" in error_codes(make_zip([member]))


def test_duplicate_archive_members_are_rejected() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        data = make_zip([("1.in", b"first"), ("1.in", b"second"), ("1.out", b"out")])

    assert "duplicate_file" in error_codes(data)


def test_empty_file_is_rejected() -> None:
    data = make_zip([("1.in", b""), ("1.out", b"out")])

    assert "empty_file" in error_codes(data)


def test_non_utf8_file_is_rejected() -> None:
    data = make_zip([("1.in", b"\xff\xfe"), ("1.out", b"out")])

    assert "invalid_utf8" in error_codes(data)


def test_non_zip_input_is_rejected() -> None:
    assert "invalid_zip" in error_codes(b"not a zip file")


def test_symbolic_link_is_rejected() -> None:
    link = zipfile.ZipInfo("1.in")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    data = make_zip([link, ("1.out", b"out")])

    assert "symlink" in error_codes(data)


def test_test_case_count_limit() -> None:
    data = make_zip([("1.in", b"a"), ("1.out", b"b"), ("2.in", b"c"), ("2.out", b"d")])
    limits = Limits(max_test_cases=1)

    assert "too_many_test_cases" in error_codes(data, limits=limits)


def test_single_file_size_limit() -> None:
    data = make_zip([("1.in", b"12345"), ("1.out", b"out")])
    limits = Limits(max_file_bytes=4)

    assert "file_too_large" in error_codes(data, limits=limits)


def test_total_uncompressed_size_limit() -> None:
    data = make_zip([("1.in", b"1234"), ("1.out", b"5678")])
    limits = Limits(max_total_bytes=7)

    assert "total_too_large" in error_codes(data, limits=limits)


def test_archive_size_limit() -> None:
    data = make_zip([("1.in", b"in"), ("1.out", b"out")])
    limits = Limits(max_archive_bytes=len(data) - 1)

    assert "archive_too_large" in error_codes(data, limits=limits)


def test_suspicious_compression_ratio_is_rejected_before_decompression() -> None:
    data = make_zip([("1.in", b"a" * 10_000), ("1.out", b"out")])
    limits = Limits(max_compression_ratio=2)

    assert "suspicious_compression_ratio" in error_codes(data, limits=limits)


def test_existing_version_directory_is_never_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "v1"
    destination.mkdir()
    marker = destination / "keep"
    marker.write_text("unchanged", encoding="utf-8")
    data = make_zip([("1.in", b"in"), ("1.out", b"out")])

    with pytest.raises(FileExistsError):
        Service().store(data, destination)

    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_failed_publication_cleans_temporary_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_zip([("1.in", b"in"), ("1.out", b"out")])

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        Service().store(data, tmp_path / "v1")

    assert list(tmp_path.iterdir()) == []
