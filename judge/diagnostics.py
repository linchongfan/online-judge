"""Small, deterministic diagnostic redaction helper."""

from __future__ import annotations

import re
from collections.abc import Iterable

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WINDOWS_PROFILE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
_POSIX_PROFILE = re.compile(r"(?m)(?<![\w])/(?:home|Users)/[^/\s]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_diagnostic(
    value: str | bytes,
    *,
    sensitive_values: Iterable[str] = (),
    max_chars: int = 4_000,
) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        raise TypeError("diagnostic must be str or bytes")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    replacements = {item for item in sensitive_values if item}
    for item in sorted(replacements, key=len, reverse=True):
        text = text.replace(item, "<redacted>")
        text = text.replace(item.replace("\\", "/"), "<redacted>")
        text = text.replace(item.replace("/", "\\"), "<redacted>")

    text = _ANSI_ESCAPE.sub("", text)
    text = _WINDOWS_PROFILE.sub("<user-profile>", text)
    text = _POSIX_PROFILE.sub("<user-profile>", text)
    text = _CONTROL.sub("", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text
