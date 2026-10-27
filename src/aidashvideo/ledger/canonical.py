"""Canonical JSON (sorted keys, UTF-8, no NaN; contracts §7) and typed JSON accessors.

``canonical_bytes`` is the only serialization used for hashing anywhere in the
repository. The accessors turn untyped ``object`` trees from ``json.loads`` into
checked values, raising :class:`ContractError` instead of ``KeyError``/``TypeError``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import cast

from .errors import ContractError
from .ids import Sha256

_RATIONAL = re.compile(r"^(-?\d{1,40})/(\d{1,40})$")

type Json = bool | int | float | str | list["Json"] | dict[str, "Json"] | None


def _check_tree(node: object, path: str) -> None:
    if node is None or isinstance(node, bool | str):
        return
    if isinstance(node, int):
        return
    if isinstance(node, float):
        if math.isnan(node) or math.isinf(node):
            raise ContractError(f"canonical JSON: non-finite number at {path}")
        return
    if isinstance(node, Mapping):
        for key, value in cast(Mapping[object, object], node).items():
            if not isinstance(key, str):
                raise ContractError(f"canonical JSON: non-string key at {path}")
            _check_tree(value, f"{path}/{key}")
        return
    if isinstance(node, Sequence):
        for index, value in enumerate(cast(Sequence[object], node)):
            _check_tree(value, f"{path}[{index}]")
        return
    raise ContractError(f"canonical JSON: unsupported value {type(node).__name__} at {path}")


def canonical_bytes(value: object) -> bytes:
    """Sorted keys, compact separators, UTF-8, finite numbers only."""
    _check_tree(value, "$")
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_of(data: bytes) -> Sha256:
    return Sha256(hashlib.sha256(data).hexdigest())


def canonical_sha256(value: object) -> Sha256:
    return sha256_of(canonical_bytes(value))


def parse_json(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"JSON: not UTF-8: {exc}") from exc

    def _reject_constant(name: str) -> object:
        raise ContractError(f"JSON: non-finite constant {name} is not allowed")

    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ContractError(f"JSON: {exc.msg} at {exc.pos}") from exc


# ----------------------------------------------------------------------------- accessors


def as_object(raw: object, what: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ContractError(f"{what}: expected an object, got {type(raw).__name__}")
    out: dict[str, object] = {}
    for key, value in cast(dict[object, object], raw).items():
        if not isinstance(key, str):
            raise ContractError(f"{what}: non-string key")
        out[key] = value
    return out


def as_list(raw: object, what: str) -> list[object]:
    if not isinstance(raw, list):
        raise ContractError(f"{what}: expected a list, got {type(raw).__name__}")
    return list(cast(list[object], raw))


def as_str(raw: object, what: str) -> str:
    if not isinstance(raw, str):
        raise ContractError(f"{what}: expected a string, got {type(raw).__name__}")
    return raw


def as_int(raw: object, what: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ContractError(f"{what}: expected an integer, got {type(raw).__name__}")
    return raw


def as_bool(raw: object, what: str) -> bool:
    if not isinstance(raw, bool):
        raise ContractError(f"{what}: expected a boolean, got {type(raw).__name__}")
    return raw


def as_finite_float(raw: object, what: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ContractError(f"{what}: expected a number, got {type(raw).__name__}")
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        raise ContractError(f"{what}: non-finite number")
    return value


def require_keys(obj: dict[str, object], what: str, required: tuple[str, ...]) -> None:
    """Exact key set: missing or unknown keys are refused (no arbitrary dictionaries)."""
    missing = [k for k in required if k not in obj]
    unknown = sorted(set(obj) - set(required))
    if missing or unknown:
        raise ContractError(f"{what}: missing keys {missing}, unknown keys {unknown}")


def field(obj: dict[str, object], key: str, what: str) -> object:
    if key not in obj:
        raise ContractError(f"{what}: missing field {key!r}")
    return obj[key]


# ----------------------------------------------------------------------------- rationals


def rational_to_json(value: Fraction) -> str:
    """Exact ``"numerator/denominator"`` (always reduced, denominator positive)."""
    return f"{value.numerator}/{value.denominator}"


def rational_from_json(raw: object, what: str) -> Fraction:
    """Parse ``"n/d"`` or an integer; floats, NaN, empty and zero denominators are refused."""
    if isinstance(raw, bool):
        raise ContractError(f"{what}: boolean is not a rational")
    if isinstance(raw, int):
        return Fraction(raw)
    if not isinstance(raw, str):
        raise ContractError(f"{what}: expected 'n/d' string, got {type(raw).__name__}")
    match = _RATIONAL.match(raw)
    if match is None:
        raise ContractError(f"{what}: malformed rational {raw!r}")
    numerator, denominator = int(match.group(1)), int(match.group(2))
    if denominator == 0:
        raise ContractError(f"{what}: zero denominator in {raw!r}")
    return Fraction(numerator, denominator)
