"""Unit tests for the pure calculator functions."""

import pytest

from app.calculator import add, divide


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(1, 2, 3), (-1, 1, 0), (2.5, 2.5, 5.0)],
)
def test_add(a: float, b: float, expected: float) -> None:
    assert add(a, b) == expected


def test_divide() -> None:
    assert divide(10, 4) == 2.5


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
