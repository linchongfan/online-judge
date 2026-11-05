from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from judge.protocol import CaseResult, JudgeRequest, JudgeResult, JudgeStatus, TestCase


def test_all_required_statuses_are_stable_wire_values() -> None:
    assert {status.name: status.value for status in JudgeStatus} == {
        name: name
        for name in (
            "PENDING",
            "JUDGING",
            "AC",
            "WA",
            "TLE",
            "MLE",
            "RE",
            "CE",
            "SE",
        )
    }


def test_protocol_is_pure_immutable_data_and_serializes_camel_case_metrics() -> None:
    case = TestCase("1", "input", "output")
    result = JudgeResult(
        request_id="submission-1",
        status=JudgeStatus.AC,
        case_results=[CaseResult("1", JudgeStatus.AC, runtime_ms=7, memory_kb=64)],
        runtime_ms=7,
        memory_kb=64,
    )

    assert result.runtimeMs == 7
    assert result.memoryKb == 64
    assert result.to_dict() == {
        "requestId": "submission-1",
        "status": "AC",
        "caseResults": [
            {
                "caseId": "1",
                "status": "AC",
                "runtimeMs": 7,
                "memoryKb": 64,
                "diagnostic": "",
            }
        ],
        "runtimeMs": 7,
        "memoryKb": 64,
        "diagnostic": "",
    }
    with pytest.raises(FrozenInstanceError):
        result.status = JudgeStatus.WA

    request = JudgeRequest("r", "python", "print('ok')", [case])
    assert request.cases == (case,)
    assert isinstance(request.cases, tuple)
