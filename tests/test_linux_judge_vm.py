"""Destructive Linux judge VM integration tests.

Run only on an authorized disposable Ubuntu 24.04 judge VM after
``deploy/judge-linux/bootstrap.sh`` and ``build-rootfs.sh`` have completed:

    JUDGE_VM=1 pytest -m linux_judge_vm

The tests use harmless controlled programs and verify isolation semantics; they
must not run on the developer workstation, production business host, or a VM
that contains anything worth preserving.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from judge.config import JudgeConfig
from judge.protocol import JudgeRequest, JudgeStatus, TestCase
from judge.worker import JudgeWorker

pytestmark = [
    pytest.mark.skipif(os.environ.get("JUDGE_VM") != "1", reason="set JUDGE_VM=1 on the disposable judge VM"),
    pytest.mark.skipif(os.name == "nt", reason="Linux judge VM only"),
    pytest.mark.linux_judge_vm,
]


@pytest.fixture
def worker(tmp_path: Path) -> JudgeWorker:
    work_root = tmp_path / "judge-work"
    work_root.mkdir(parents=True, exist_ok=True)
    config = JudgeConfig.from_env({"JUDGE_WORK_ROOT": str(work_root)})
    assert config.sandbox_backend is not None
    return JudgeWorker(config, sandbox_backend=config.sandbox_backend)


def _request(source: str, *, time_limit_ms: int = 2000, memory_limit_kb: int = 262144) -> JudgeRequest:
    return JudgeRequest(
        request_id=f"vm-{time.monotonic_ns()}",
        language="python",
        source_code=source,
        cases=(TestCase("1", "hello", "hello", is_sample=True),),
        time_limit_ms=time_limit_ms,
        memory_limit_kb=memory_limit_kb,
    )


def _judge(worker: JudgeWorker, source: str, *, time_limit_ms: int = 2000, memory_limit_kb: int = 262144):
    return worker.judge(_request(source, time_limit_ms=time_limit_ms, memory_limit_kb=memory_limit_kb))


def test_python_round_trip_ac_and_cleanup(worker: JudgeWorker, tmp_path: Path) -> None:
    result = _judge(worker, "import sys\nsys.stdout.write(sys.stdin.read())\n")
    assert result.status is JudgeStatus.AC
    assert list((tmp_path / "judge-work").iterdir()) == []


def test_wall_time_limit_is_reported_as_tle(worker: JudgeWorker) -> None:
    result = _judge(worker, "while True:\n    pass\n", time_limit_ms=100)
    assert result.status is JudgeStatus.TLE


def test_memory_limit_is_reported_as_mle(worker: JudgeWorker) -> None:
    result = _judge(
        worker,
        "data = bytearray()\nwhile True:\n    data.extend(b'x' * 1048576)\n",
        memory_limit_kb=16384,
    )
    assert result.status is JudgeStatus.MLE


def test_hard_combined_output_limit_stops_before_disk_fills(worker: JudgeWorker) -> None:
    result = _judge(
        worker,
        "import sys\nwhile True:\n    sys.stdout.write('x' * 4096)\n    sys.stdout.flush()\n",
        time_limit_ms=5000,
    )
    assert result.status is JudgeStatus.RE
    assert result.case_results[0].diagnostic == "Output byte limit exceeded."


def test_user_program_cannot_access_host_private_file(worker: JudgeWorker, tmp_path: Path) -> None:
    secret = Path("/var/lib/xinbaoyan-judge/judge_worker_host_secret")
    secret.write_text("vm-secret", encoding="utf-8")
    try:
        result = _judge(
            worker,
            "from pathlib import Path\n"
            f"p = Path({str(secret)!r})\n"
            "print(p.read_text() if p.exists() else 'missing')\n",
        )
        assert result.status is JudgeStatus.RE
        assert "vm-secret" not in repr(result.to_dict())
    finally:
        secret.unlink(missing_ok=True)


def test_user_program_has_no_outbound_network_device(worker: JudgeWorker) -> None:
    result = _judge(
        worker,
        "import socket\n"
        "s = socket.socket()\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "except OSError:\n"
        "    raise SystemExit(3)\n"
        "print('connected')\n",
    )
    assert result.status is JudgeStatus.RE


def test_multi_case_program_runs_each_case_in_fresh_sandbox(worker: JudgeWorker) -> None:
    request = JudgeRequest(
        request_id=f"vm-multi-{time.monotonic_ns()}",
        language="python",
        source_code="import sys\nsys.stdout.write(sys.stdin.read().upper())\n",
        cases=(
            TestCase("1", "hello", "HELLO", is_sample=True),
            TestCase("2", "world", "WORLD", is_sample=True),
        ),
        time_limit_ms=2000,
    )
    result = worker.judge(request)
    assert result.status is JudgeStatus.AC
    assert [case.status for case in result.case_results] == [JudgeStatus.AC, JudgeStatus.AC]
