"""Standard output comparison with deliberately narrow normalisation."""

from __future__ import annotations

from typing import overload


@overload
def normalize_output(value: str) -> str: ...


@overload
def normalize_output(value: bytes) -> bytes: ...


def normalize_output(value: str | bytes) -> str | bytes:
    """Ignore CR in CRLF, trailing spaces/tabs, and trailing blank lines only."""
    if isinstance(value, str):
        lines = value.split("\n")
        normalised_text = [line.removesuffix("\r").rstrip(" \t") for line in lines]
        while normalised_text and normalised_text[-1] == "":
            normalised_text.pop()
        return "\n".join(normalised_text)
    if isinstance(value, bytes):
        byte_lines = value.split(b"\n")
        normalised_bytes = [line.removesuffix(b"\r").rstrip(b" \t") for line in byte_lines]
        while normalised_bytes and normalised_bytes[-1] == b"":
            normalised_bytes.pop()
        return b"\n".join(normalised_bytes)
    raise TypeError("output must be str or bytes")


def compare_output(actual: str | bytes, expected: str | bytes) -> bool:
    """Return whether outputs match under :func:`normalize_output` rules."""
    if isinstance(actual, str) != isinstance(expected, str):
        raise TypeError("actual and expected output must have the same type")
    if not isinstance(actual, (str, bytes)) or not isinstance(expected, (str, bytes)):
        raise TypeError("output must be str or bytes")
    return normalize_output(actual) == normalize_output(expected)


standard_output_equal = compare_output
