"""Exceptions of the persistence boundary.

``ContractError`` is raised by validated constructors when a value cannot be represented.
``InvariantViolation`` is raised when the store is in a state the contracts declare
impossible (it is never logged-and-ignored: contracts §5, design brief M1).
``InjectedFault`` is raised only by test fault hooks (V12 crash injection).
"""

from __future__ import annotations


class ContractError(ValueError):
    """A closed variant could not be constructed from the given values."""


class InvariantViolation(RuntimeError):
    """The durable store contradicts an invariant; the operation fails visibly."""


class InjectedFault(RuntimeError):
    """Raised by a fault hook at a named persistence point (tests only)."""

    def __init__(self, point: str) -> None:
        super().__init__(f"injected fault at {point}")
        self.point = point


def require(condition: bool, message: str) -> None:
    """Constructor guard: raise ``ContractError`` when a closed variant would be invalid."""
    if not condition:
        raise ContractError(message)


def is_int(value: object) -> bool:
    """``True`` for an ``int`` that is not a ``bool`` (JSON and dataclass guards)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_str(value: object) -> bool:
    return isinstance(value, str)


def widen(value: object) -> object:
    """Identity function typed as ``object`` so constructor guards can ``isinstance`` a field."""
    return value
