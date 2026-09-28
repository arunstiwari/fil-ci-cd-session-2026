"""Pure business logic, kept separate from the web layer so it is easy to test."""


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def divide(a: float, b: float) -> float:
    """Return a divided by b.

    Raises:
        ZeroDivisionError: if b is zero.

    """
    if b == 0:
        raise ZeroDivisionError("division by zero is not allowed")
    return a / b
