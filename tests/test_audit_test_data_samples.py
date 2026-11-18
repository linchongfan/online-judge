from sqlalchemy import select

from app.models import TestCase as JudgeTestCase
from app.models import TestDataStatus as VersionStatus
from app.models import TestDataVersion as JudgeDataVersion
from scripts.audit_test_data_samples import audit_versions, expected_is_sample, repair_versions


def _version(db_session, problem_id, version_no, is_current=True, sample_count=0):
    version = JudgeDataVersion(
        problem_id=problem_id,
        version=version_no,
        status=VersionStatus.VALID,
        is_current=is_current,
        storage_path=f"/tmp/p{problem_id}/v{version_no}",
        original_filename="data.zip",
        compressed_size=1,
        sample_count=sample_count,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _case(version, number, input_key, is_sample):
    case = JudgeTestCase(
        version_id=version.id,
        case_number=number,
        input_key=input_key,
        output_key=input_key.replace(".in", ".out"),
        is_sample=is_sample,
        input_size=1,
        output_size=1,
    )
    version.cases.append(case)
    return case


def test_expected_is_sample_comes_from_stored_path_prefix():
    assert expected_is_sample("sample/1.in") is True
    assert expected_is_sample("1.in") is False
    assert expected_is_sample("hidden/1.in") is False
    assert expected_is_sample("problem/1.in") is False


def test_audit_flags_buggy_default_cases_and_wrong_count(db_session):
    version = _version(db_session, problem_id=1, version_no=1, sample_count=2)
    # Historical buggy upload: a default (root) case was marked as sample.
    _case(version, 1, "1.in", is_sample=True)
    _case(version, 2, "sample/1.in", is_sample=True)
    db_session.commit()

    mismatches = audit_versions(db_session)

    assert len(mismatches) == 1
    report = mismatches[0]
    assert report.is_current is True
    assert [(number, current, expected) for _id, number, current, expected in report.cases] == [(1, True, False)]
    assert report.sample_count_mismatch is True  # stored 2, truth is 1
    assert report.conflicts == []


def test_audit_ignores_correct_and_non_valid_versions(db_session):
    valid = _version(db_session, problem_id=1, version_no=1, sample_count=1)
    _case(valid, 1, "sample/1.in", is_sample=True)
    _case(valid, 2, "hidden/1.in", is_sample=False)
    invalid = _version(db_session, problem_id=1, version_no=2)
    invalid.status = VersionStatus.INVALID
    _case(invalid, 1, "1.in", is_sample=True)  # wrong but not VALID: excluded
    db_session.commit()

    assert audit_versions(db_session) == []


def test_repair_updates_flags_and_sample_count(db_session):
    version = _version(db_session, problem_id=7, version_no=3, sample_count=2)
    buggy = _case(version, 1, "1.in", is_sample=True)
    _case(version, 2, "sample/1.in", is_sample=True)
    _case(version, 3, "hidden/1.in", is_sample=False)
    db_session.commit()

    mismatches = audit_versions(db_session)
    stats = repair_versions(db_session, mismatches)

    assert stats == {"repaired_cases": 1, "skipped_versions": 0}
    stored = db_session.scalars(select(JudgeTestCase).where(JudgeTestCase.version_id == version.id)).all()
    assert {case.input_key: case.is_sample for case in stored} == {
        "1.in": False,
        "sample/1.in": True,
        "hidden/1.in": False,
    }
    assert db_session.get(JudgeDataVersion, version.id).sample_count == 1
    # Second audit must be clean.
    assert audit_versions(db_session) == []
    assert buggy.is_sample is False


def test_repair_skips_versions_with_unique_constraint_conflict(db_session):
    # A version that (through bad history) holds both a wrongly-flagged
    # default case and a hidden case with the same number: flipping the
    # default case to False would collide on (version_id, number, is_sample).
    version = _version(db_session, problem_id=9, version_no=1, sample_count=1)
    _case(version, 1, "1.in", is_sample=True)
    _case(version, 1, "hidden/1.in", is_sample=False)
    db_session.commit()

    mismatches = audit_versions(db_session)
    assert len(mismatches) == 1
    assert mismatches[0].conflicts == [(1, False)]

    stats = repair_versions(db_session, mismatches)

    assert stats == {"repaired_cases": 0, "skipped_versions": 1}
    stored = db_session.scalars(select(JudgeTestCase).where(JudgeTestCase.version_id == version.id)).all()
    assert {case.input_key: case.is_sample for case in stored} == {"1.in": True, "hidden/1.in": False}
