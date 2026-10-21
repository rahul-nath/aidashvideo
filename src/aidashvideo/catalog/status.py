"""Typed readiness results shared by every probe (same three words as docs/plan)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Readiness(StrEnum):
    VERIFIED = "Verified"
    """The exact planned identity is present and passed a real functional check."""
    MISSING = "Missing"
    """Not found at all. Always carries the exact missing evidence or install step."""
    CONFLICTING = "Conflicting"
    """Present, but its identity/capabilities/digest contradict the plan, or it fails."""


@dataclass(frozen=True)
class ComponentStatus:
    component: str
    readiness: Readiness
    detail: str
    facts: dict[str, str] = field(default_factory=lambda: {})
    optional: bool = False

    @property
    def ok(self) -> bool:
        return self.readiness is Readiness.VERIFIED

    def to_json(self) -> dict[str, object]:
        return {
            "component": self.component,
            "readiness": self.readiness.value,
            "optional": self.optional,
            "detail": self.detail,
            "facts": dict(self.facts),
        }
