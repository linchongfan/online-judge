"""Cross-platform unit tests for the isolate v2.0 meta parser and classifier.

These exercise the pure functions in ``judge.linux_isolate`` without
constructing the POSIX-only backend, so they run on any development host.
The authoritative four-language VM acceptance still lives in
``tests/test_linux_judge_vm.py``.
"""

from __future__ import annotations

from judge.linux_isolate import classify_isolate_meta, parse_isolate_meta
from judge.sandbox import SandboxTerminationReason


def test_parse_empty_and_garbage_lines_are_ignored() -> None:
    assert parse_isolate_meta("") == {}
    assert parse_isolate_meta("\n   \nnot-a-meta-line\n:key-only\n") == {}


def test_parse_numeric_and_string_values() -> None:
    meta = parse_isolate_meta(
        "time:1.234\n"
        "cg-mem:8192\n"
        "exitcode:0\n"
        "status:RE\n"
        "cg-oom-killed:1\n"
        "message:boom: with colons\n"
    )
    assert meta["time"] == 1.234
    assert meta["cg-mem"] == 8192
    assert meta["exitcode"] == 0
    assert meta["status"] == "RE"
    assert meta["cg-oom-killed"] == 1
    assert meta["message"] == "boom: with colons"


def test_parse_duplicate_key_keeps_last_value() -> None:
    meta = parse_isolate_meta("time:1.000\ntime:2.500\n")
    assert meta["time"] == 2.5


def test_classify_timeout() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:TO\ntime-wall:0.250\ncg-mem:4096\n"))
    assert info.termination_reason is SandboxTerminationReason.WALL_TIME_LIMIT
    assert info.wall_time_exceeded is True
    assert info.runtime_ms == 250
    assert info.peak_memory_kb == 4096


def test_classify_success_without_status_line() -> None:
    info = classify_isolate_meta(parse_isolate_meta("time:0.042\ntime-wall:0.100\nexitcode:0\ncg-mem:2048\n"))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.exit_code == 0
    assert info.runtime_ms == 42
    assert info.peak_memory_kb == 2048


def test_classify_re_uses_program_exit_code() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:RE\nexitcode:3\ntime:0.010\n"))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.exit_code == 3


def test_classify_signal_maps_to_negative_exit_code() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:SG\nexitsig:11\n"))
    assert info.termination_reason is SandboxTerminationReason.NORMAL
    assert info.exit_code == -11


def test_classify_signal_without_exitsig_forces_nonzero_exit() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:SG\n"))
    assert info.exit_code == -1


def test_classify_oom_kill_is_memory_limit() -> None:
    info = classify_isolate_meta(parse_isolate_meta("cg-mem:1048576\ncg-oom-killed:1\n"))
    assert info.memory_exceeded is True
    assert info.termination_reason is SandboxTerminationReason.MEMORY_LIMIT


def test_classify_memory_status_is_memory_limit() -> None:
    # Forward compatibility: some isolate builds emit an explicit ML status.
    info = classify_isolate_meta(parse_isolate_meta("status:ML\n"))
    assert info.memory_exceeded is True
    assert info.termination_reason is SandboxTerminationReason.MEMORY_LIMIT


def test_classify_output_status_is_output_limit() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:OL\n"))
    assert info.output_exceeded is True
    assert info.termination_reason is SandboxTerminationReason.OUTPUT_LIMIT


def test_classify_internal_error_is_sandbox_error_with_message() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:XX\nmessage:box init failed\n"))
    assert info.termination_reason is SandboxTerminationReason.SANDBOX_ERROR
    assert "box init failed" in info.infrastructure_error


def test_classify_unknown_status_fails_closed() -> None:
    info = classify_isolate_meta(parse_isolate_meta("status:ZZ\n"))
    assert info.termination_reason is SandboxTerminationReason.SANDBOX_ERROR
    assert "isolate status=ZZ" in info.infrastructure_error


def test_classify_merges_proxy_output_exceeded() -> None:
    info = classify_isolate_meta(parse_isolate_meta("exitcode:0\n"), proxy_exceeded=True, proxy_error="stdout overflow")
    assert info.output_exceeded is True
    assert "stdout overflow" in info.infrastructure_error


def test_classify_memory_preference_cg_mem_then_max_rss() -> None:
    info = classify_isolate_meta(parse_isolate_meta("max-rss:999\ncg-mem:1234\n"))
    assert info.peak_memory_kb == 1234
    info = classify_isolate_meta(parse_isolate_meta("max-rss:999\n"))
    assert info.peak_memory_kb == 999
