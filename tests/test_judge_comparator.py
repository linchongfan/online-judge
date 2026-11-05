from __future__ import annotations

import pytest

from judge.comparator import compare_output, normalize_output


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ("answer", "answer"),
        ("answer\n", "answer"),
        ("answer  \t\n\n", "answer\n"),
        ("first  \r\nsecond\t\r\n\r\n", "first\nsecond\n"),
        ("  leading\n", "  leading"),
        ("\n", ""),
        (b"answer  \n\n", b"answer"),
    ],
)
def test_standard_output_equivalence(actual, expected) -> None:
    assert compare_output(actual, expected)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (" answer", "answer"),
        ("answer ", "answ er"),
        ("a  b", "a b"),
        ("a\tb", "a b"),
        ("a\n\nb", "a\nb"),
        ("a\nb", "a\nB"),
        ("\na", "a"),
        ("a\nb\n", "a\nb\nc"),
    ],
)
def test_comparator_does_not_ignore_other_content(actual, expected) -> None:
    assert not compare_output(actual, expected)


def test_normalization_preserves_non_trailing_horizontal_space() -> None:
    assert normalize_output(" a \t b  \n") == " a \t b"


def test_comparator_rejects_mixed_types() -> None:
    with pytest.raises(TypeError):
        compare_output(b"bytes", "text")
