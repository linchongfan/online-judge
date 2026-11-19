"""Cross-platform regression tests for the isolate output proxy.

The proxy itself has no POSIX dependencies, so the file-creation timing and
EOF-continuation behaviour are exercised on every development host.
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

from judge.linux_isolate import _OutputProxy


def _proxy(tmp_path: Path, limit: int = 1024) -> tuple[_OutputProxy, Path, Path, io.BytesIO, io.BytesIO]:
    stdout_path = tmp_path / "stdout"
    stderr_path = tmp_path / "stderr"
    stdout_sink = io.BytesIO()
    stderr_sink = io.BytesIO()
    proxy = _OutputProxy(
        stdout=stdout_sink,
        stderr=stderr_sink,
        limit_bytes=limit,
        stop_event=threading.Event(),
    )
    return proxy, stdout_path, stderr_path, stdout_sink, stderr_sink


def test_proxy_waits_for_output_files_created_after_start(tmp_path: Path) -> None:
    proxy, stdout_path, stderr_path, stdout_sink, stderr_sink = _proxy(tmp_path)
    proxy.start({"stdout": stdout_path, "stderr": stderr_path})

    # isolate only creates the files after entering the box; writing them
    # after proxy start must not be treated as an error.
    time.sleep(0.05)
    with stdout_path.open("ab") as stream:
        stream.write(b"hello ")
    with stderr_path.open("ab") as stream:
        stream.write(b"err ")
    with stdout_path.open("ab") as stream:
        stream.write(b"world")
    proxy.finish()

    assert stdout_sink.getvalue() == b"hello world"
    assert stderr_sink.getvalue() == b"err "
    assert proxy.snapshot()[1] == ""


def test_proxy_continues_polling_after_temporary_eof(tmp_path: Path) -> None:
    proxy, stdout_path, _, stdout_sink, _ = _proxy(tmp_path)
    stdout_path.write_bytes(b"part1")
    stderr_path = tmp_path / "stderr"
    stderr_path.write_bytes(b"")
    proxy.start({"stdout": stdout_path, "stderr": stderr_path})
    time.sleep(0.05)
    # The pump has likely hit EOF on part1 by now; later output must follow.
    with stdout_path.open("ab") as stream:
        stream.write(b"-part2")
    proxy.finish()

    assert stdout_sink.getvalue() == b"part1-part2"
    assert proxy.snapshot()[1] == ""


def test_proxy_hard_limit_sets_exceeded_and_stop_event(tmp_path: Path) -> None:
    proxy, stdout_path, stderr_path, stdout_sink, _ = _proxy(tmp_path, limit=16)
    proxy.start({"stdout": stdout_path, "stderr": stderr_path})
    time.sleep(0.02)
    stdout_path.write_bytes(b"x" * 64)
    proxy.finish()

    exceeded, _ = proxy.snapshot()
    assert exceeded is True
    assert proxy.stop_event.is_set()
    # Only bytes up to the cap are forwarded.
    assert len(stdout_sink.getvalue()) <= 16
