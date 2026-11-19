"""Audit (and optionally repair) historical test-data sample flags.

Background: an earlier upload path marked every non-hidden case as a public
sample (`is_sample = category != "hidden"`), so root/ordinary top-level
directory cases were exposed as samples. Uploads now only mark explicit
"sample/" files as samples.

The original archive category is still recoverable for existing rows because
`TestCase.input_key` keeps the stored path prefix ("sample/1.in" vs "1.in").
This script verifies each case against that prefix and reports (or, with
`--apply`, repairs) mismatches. Rows whose repair would violate the
(version_id, case_number, is_sample) unique constraint are reported for
manual review and never changed.

Usage:
    python scripts/audit_test_data_samples.py            # audit only, exit 1 on mismatch
    python scripts/audit_test_data_samples.py --apply    # repair safe mismatches
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import TestCase, TestDataStatus, TestDataVersion

SAMPLE_PREFIX = "sample/"


def expected_is_sample(input_key: str) -> bool:
    """The stored path prefix preserves the original archive category."""
    return input_key.startswith(SAMPLE_PREFIX)


@dataclass
class VersionMismatch:
    version_id: str
    problem_id: int
    version: int
    is_current: bool
    # (case_id, case_number, current, expected) rows that differ.
    cases: list[tuple[int, int, bool, bool]] = field(default_factory=list)
    # Expected flags blocked by the (version_id, case_number, is_sample)
    # unique constraint; these need a human to re-upload or merge manually.
    conflicts: list[tuple[int, int]] = field(default_factory=list)
    # sample_count stored on the version row differs from repaired truth.
    sample_count_mismatch: bool = False


def _expected_sample_count(cases: list[TestCase]) -> int:
    return sum(expected_is_sample(case.input_key) for case in cases)


def audit_versions(db: Session) -> list[VersionMismatch]:
    versions = db.scalars(
        select(TestDataVersion)
        .where(TestDataVersion.status == TestDataStatus.VALID)
        .order_by(TestDataVersion.problem_id, TestDataVersion.version)
    ).all()
    mismatches: list[VersionMismatch] = []
    for version in versions:
        cases = list(version.cases)
        case_mismatches = [
            (case.id, case.case_number, case.is_sample, expected_is_sample(case.input_key))
            for case in cases
            if case.is_sample != expected_is_sample(case.input_key)
        ]
        expected_count = _expected_sample_count(cases)
        count_mismatch = version.sample_count != expected_count
        if not case_mismatches and not count_mismatch:
            continue
        report = VersionMismatch(
            version_id=version.id,
            problem_id=version.problem_id,
            version=version.version,
            is_current=version.is_current,
            cases=case_mismatches,
            sample_count_mismatch=count_mismatch,
        )
        if case_mismatches:
            occupied = {
                (case.case_number, case.is_sample)
                for case in cases
                if (case.id, case.case_number, case.is_sample, expected_is_sample(case.input_key))
                not in case_mismatches
            }
            for _case_id, number, _current, expected in case_mismatches:
                if (number, expected) in occupied:
                    report.conflicts.append((number, expected))
        mismatches.append(report)
    return mismatches


def repair_versions(db: Session, mismatches: list[VersionMismatch]) -> dict[str, int]:
    repaired = skipped = 0
    for report in mismatches:
        if report.conflicts:
            # Never partially repair a version: a mixed flag set can break the
            # unique constraint and leave the version internally inconsistent.
            skipped += 1
            continue
        version = db.get(TestDataVersion, report.version_id)
        if version is None:
            continue
        for case_id, _number, _current, expected in report.cases:
            case = db.get(TestCase, case_id)
            if case is not None:
                case.is_sample = expected
                repaired += 1
        version.sample_count = _expected_sample_count(list(version.cases))
    db.commit()
    return {"repaired_cases": repaired, "skipped_versions": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply", action="store_true", help="repair mismatches in place (conflicting versions are skipped)"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mismatches = audit_versions(db)
        for report in mismatches:
            flag = "current" if report.is_current else "old"
            print(
                f"problem {report.problem_id} version {report.version} ({flag}, id={report.version_id}): "
                f"{len(report.cases)} case flag(s) wrong"
                + (", sample_count wrong" if report.sample_count_mismatch else "")
            )
            for case_id, number, current, expected in report.cases:
                print(f"  case #{number} (id={case_id}): is_sample {current} -> {expected}")
            for conflict_number, conflict_expected in report.conflicts:
                print(
                    f"  CONFLICT: case #{conflict_number} would become is_sample={conflict_expected} "
                    "but a conflicting row exists; re-upload required"
                )
        if not mismatches:
            print("No mismatches found.")
            return
        if not args.apply:
            print(f"\nAudit found {len(mismatches)} version(s) with mismatches.")
            print("Re-run with --apply to repair safe ones.")
            raise SystemExit(1)
        stats = repair_versions(db, mismatches)
        print(
            f"\nApplied: {stats['repaired_cases']} case flag(s) repaired; "
            f"{stats['skipped_versions']} version(s) skipped due to conflicts."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
