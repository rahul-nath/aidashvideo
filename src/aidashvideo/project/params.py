"""Typed parameter values and assignments (contracts §2 ``ParamValue``, ``ParamAssignment``).

No ``dict[str, object]`` carries a parameter: every value is one of the closed variants and
is validated against the service's ``MLTParameter`` descriptor before admission (typo,
wrong type, NaN, out-of-range value and unsupported animation are ``Rejected`` here, long
before any native construction; V23).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from fractions import Fraction

from aidashvideo.catalog.descriptors import (
    Animatable,
    Bounded,
    InterpolationKind,
    ParameterDescriptor,
    ServiceDescriptor,
    Static,
    TimeDomain,
    ValueType,
)
from aidashvideo.ledger.canonical import (
    as_finite_float,
    as_int,
    as_list,
    as_object,
    as_str,
    field,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, is_str, widen
from aidashvideo.ledger.results import RejectCode, Rejected

from .text import LiteralText
from .timing import SourceTime


@dataclass(frozen=True, slots=True)
class Int:
    v: int

    def __post_init__(self) -> None:
        if not is_int(self.v):
            raise ContractError("Int needs an integer")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Int", "v": self.v}


@dataclass(frozen=True, slots=True)
class Float:
    v: float

    def __post_init__(self) -> None:
        if isinstance(widen(self.v), bool) or not isinstance(widen(self.v), int | float):
            raise ContractError("Float needs a number")
        if math.isnan(self.v) or math.isinf(self.v):
            raise ContractError("Float must be finite")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Float", "v": float(self.v)}


@dataclass(frozen=True, slots=True)
class Bool:
    v: bool

    def __post_init__(self) -> None:
        if not isinstance(widen(self.v), bool):
            raise ContractError("Bool needs a boolean")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Bool", "v": self.v}


@dataclass(frozen=True, slots=True)
class Enum:
    v: str

    def __post_init__(self) -> None:
        if not is_str(self.v) or not self.v:
            raise ContractError("Enum needs a non-empty choice")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Enum", "v": self.v}


@dataclass(frozen=True, slots=True)
class Color:
    r: int
    g: int
    b: int
    a: int

    def __post_init__(self) -> None:
        for name in ("r", "g", "b", "a"):
            value = getattr(self, name)
            if not is_int(value) or not 0 <= value <= 255:
                raise ContractError(f"Color.{name} must be an integer in 0..255")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Color", "rgba": [self.r, self.g, self.b, self.a]}


@dataclass(frozen=True, slots=True)
class Rect:
    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction
    opacity: Fraction

    def __post_init__(self) -> None:
        for name in ("x", "y", "w", "h", "opacity"):
            if not isinstance(widen(getattr(self, name)), Fraction):
                raise ContractError(f"Rect.{name} must be a Fraction")
        if self.w <= 0 or self.h <= 0:
            raise ContractError("Rect needs positive width and height")
        if not 0 <= self.opacity <= 1:
            raise ContractError("Rect.opacity must be within [0, 1]")

    @classmethod
    def make(
        cls,
        x: Fraction | int,
        y: Fraction | int,
        w: Fraction | int,
        h: Fraction | int,
        opacity: Fraction | int = 1,
    ) -> Rect:
        return cls(Fraction(x), Fraction(y), Fraction(w), Fraction(h), Fraction(opacity))

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Rect",
            "x": rational_to_json(self.x),
            "y": rational_to_json(self.y),
            "w": rational_to_json(self.w),
            "h": rational_to_json(self.h),
            "opacity": rational_to_json(self.opacity),
        }


@dataclass(frozen=True, slots=True)
class Text:
    v: LiteralText

    def to_json(self) -> dict[str, object]:
        return {"kind": "Text", "v": self.v.to_json()}


type ParamValue = Int | Float | Bool | Enum | Color | Rect | Text


def value_from_json(raw: object) -> ParamValue:
    data = as_object(raw, "ParamValue")
    kind = as_str(field(data, "kind", "ParamValue"), "ParamValue.kind")
    match kind:
        case "Int":
            require_keys(data, "Int", ("kind", "v"))
            return Int(as_int(data["v"], "Int.v"))
        case "Float":
            require_keys(data, "Float", ("kind", "v"))
            return Float(as_finite_float(data["v"], "Float.v"))
        case "Bool":
            require_keys(data, "Bool", ("kind", "v"))
            value = data["v"]
            if not isinstance(value, bool):
                raise ContractError("Bool.v must be a boolean")
            return Bool(value)
        case "Enum":
            require_keys(data, "Enum", ("kind", "v"))
            return Enum(as_str(data["v"], "Enum.v"))
        case "Color":
            require_keys(data, "Color", ("kind", "rgba"))
            rgba = as_list(data["rgba"], "Color.rgba")
            if len(rgba) != 4:
                raise ContractError("Color.rgba needs four components")
            return Color(*(as_int(c, "Color.rgba[]") for c in rgba))
        case "Rect":
            require_keys(data, "Rect", ("kind", "x", "y", "w", "h", "opacity"))
            return Rect(
                *(rational_from_json(data[k], f"Rect.{k}") for k in ("x", "y", "w", "h", "opacity"))
            )
        case "Text":
            require_keys(data, "Text", ("kind", "v"))
            return Text(LiteralText.from_json(data["v"]))
        case _:
            raise ContractError(f"ParamValue: unknown kind {kind!r}")


# ----------------------------------------------------------------------------- keyframes


@dataclass(frozen=True, slots=True)
class FrameOffset:
    """Keyframe time in sequence frames relative to the target's start (moves keep it)."""

    frame: int

    def __post_init__(self) -> None:
        if not is_int(self.frame) or self.frame < 0:
            raise ContractError("FrameOffset must be a non-negative integer")

    def to_json(self) -> dict[str, object]:
        return {"kind": "FrameOffset", "frame": self.frame}

    def sort_key(self) -> Fraction:
        return Fraction(self.frame)


@dataclass(frozen=True, slots=True)
class SourceInstant:
    at: SourceTime

    def to_json(self) -> dict[str, object]:
        return {"kind": "SourceInstant", "at": self.at.to_json()}

    def sort_key(self) -> Fraction:
        return self.at.seconds


@dataclass(frozen=True, slots=True)
class Normalized:
    position: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.position), Fraction) or not 0 <= self.position <= 1:
            raise ContractError("Normalized position must be a Fraction within [0, 1]")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Normalized", "position": rational_to_json(self.position)}

    def sort_key(self) -> Fraction:
        return self.position


type KeyframeTime = FrameOffset | SourceInstant | Normalized


def keyframe_time_from_json(raw: object) -> KeyframeTime:
    data = as_object(raw, "KeyframeTime")
    kind = as_str(field(data, "kind", "KeyframeTime"), "KeyframeTime.kind")
    if kind == "FrameOffset":
        require_keys(data, "FrameOffset", ("kind", "frame"))
        return FrameOffset(as_int(data["frame"], "frame"))
    if kind == "SourceInstant":
        require_keys(data, "SourceInstant", ("kind", "at"))
        return SourceInstant(SourceTime.from_json(data["at"]))
    if kind == "Normalized":
        require_keys(data, "Normalized", ("kind", "position"))
        return Normalized(rational_from_json(data["position"], "position"))
    raise ContractError(f"KeyframeTime: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class Keyframe:
    at: KeyframeTime
    value: ParamValue

    def to_json(self) -> dict[str, object]:
        return {"at": self.at.to_json(), "value": self.value.to_json()}


@dataclass(frozen=True, slots=True)
class StaticValue:
    value: ParamValue

    def to_json(self) -> dict[str, object]:
        return {"kind": "Static", "value": self.value.to_json()}


@dataclass(frozen=True, slots=True)
class Animated:
    keyframes: tuple[Keyframe, ...]
    interpolation: InterpolationKind

    def __post_init__(self) -> None:
        if len(self.keyframes) < 2:
            raise ContractError("Animated needs at least two keyframes")
        kinds = {type(k.at) for k in self.keyframes}
        if len(kinds) != 1:
            raise ContractError("Animated keyframes must share one time domain")
        keys = [k.at.sort_key() for k in self.keyframes]
        if any(b <= a for a, b in itertools.pairwise(keys)):
            raise ContractError("Animated keyframes must be strictly increasing in time")
        value_kinds = {type(k.value) for k in self.keyframes}
        if len(value_kinds) != 1:
            raise ContractError("Animated keyframes must share one value kind")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Animated",
            "keyframes": [k.to_json() for k in self.keyframes],
            "interpolation": self.interpolation.value,
        }


type Assignment = StaticValue | Animated


@dataclass(frozen=True, slots=True)
class ParamAssignment:
    param_id: str
    value: Assignment

    def __post_init__(self) -> None:
        if not is_str(self.param_id) or not self.param_id:
            raise ContractError("ParamAssignment.param_id must be non-empty")

    def to_json(self) -> dict[str, object]:
        return {"param_id": self.param_id, "value": self.value.to_json()}

    @classmethod
    def from_json(cls, raw: object) -> ParamAssignment:
        data = as_object(raw, "ParamAssignment")
        require_keys(data, "ParamAssignment", ("param_id", "value"))
        value = as_object(data["value"], "ParamAssignment.value")
        kind = as_str(field(value, "kind", "Assignment"), "Assignment.kind")
        if kind == "Static":
            require_keys(value, "Static", ("kind", "value"))
            assignment: Assignment = StaticValue(value_from_json(value["value"]))
        elif kind == "Animated":
            require_keys(value, "Animated", ("kind", "keyframes", "interpolation"))
            keyframes: list[Keyframe] = []
            for raw_kf in as_list(value["keyframes"], "keyframes"):
                kf = as_object(raw_kf, "Keyframe")
                require_keys(kf, "Keyframe", ("at", "value"))
                keyframes.append(
                    Keyframe(keyframe_time_from_json(kf["at"]), value_from_json(kf["value"]))
                )
            try:
                interpolation = InterpolationKind(as_str(value["interpolation"], "interpolation"))
            except ValueError as exc:
                raise ContractError(f"Animated.interpolation: {exc}") from exc
            assignment = Animated(tuple(keyframes), interpolation)
        else:
            raise ContractError(f"Assignment: unknown kind {kind!r}")
        return cls(as_str(data["param_id"], "param_id"), assignment)


def assignments_from_json(raw: object, what: str) -> tuple[ParamAssignment, ...]:
    out = tuple(ParamAssignment.from_json(a) for a in as_list(raw, what))
    ids = [a.param_id for a in out]
    if len(set(ids)) != len(ids):
        raise ContractError(f"{what}: duplicate parameter ids")
    return out


# ----------------------------------------------------------------------------- validation


def _value_matches(descriptor: ParameterDescriptor, value: ParamValue) -> str | None:
    """``None`` when the value fits the declared type, enum choices and range."""
    vt = descriptor.value_type
    match value:
        case Int(v):
            if vt not in (ValueType.INTEGER, ValueType.FLOAT):
                return f"expects {vt.value}, got an integer"
            return _in_range(descriptor, Fraction(v))
        case Float(v):
            if vt is not ValueType.FLOAT:
                return f"expects {vt.value}, got a float"
            return _in_range(descriptor, Fraction(v))
        case Bool():
            return None if vt is ValueType.BOOLEAN else f"expects {vt.value}, got a boolean"
        case Enum(v):
            if vt is not ValueType.ENUM:
                return f"expects {vt.value}, got an enum choice"
            if v not in descriptor.values:
                return f"{v!r} is not one of {list(descriptor.values)}"
            return None
        case Color():
            return None if vt is ValueType.COLOR else f"expects {vt.value}, got a color"
        case Rect():
            if vt not in (ValueType.RECT, ValueType.GEOMETRY):
                return f"expects {vt.value}, got a rect"
            return None
        case Text():
            return None if vt is ValueType.STRING else f"expects {vt.value}, got text"


def _in_range(descriptor: ParameterDescriptor, value: Fraction) -> str | None:
    constraints = descriptor.parameter.constraints
    if isinstance(constraints, Bounded) and not (
        constraints.minimum <= value <= constraints.maximum
    ):
        return f"{float(value)} outside [{constraints.minimum}, {constraints.maximum}]"
    return None


def validate_assignment(
    service: ServiceDescriptor, assignment: ParamAssignment, context: str
) -> Rejected | None:
    """Descriptor-bound validation; ``None`` means admissible."""
    descriptor = service.parameter(assignment.param_id)
    if descriptor is None:
        return Rejected.make(
            RejectCode.UNKNOWN_PARAMETER,
            f"{context}: service {service.service_id} has no parameter {assignment.param_id!r}",
            (context,),
        )
    if not descriptor.mutable:
        return Rejected.make(
            RejectCode.PARAMETER_TYPE,
            f"{context}: parameter {assignment.param_id!r} is not mutable",
            (context,),
        )
    match assignment.value:
        case StaticValue(value):
            problem = _value_matches(descriptor, value)
            if problem is not None:
                code = (
                    RejectCode.PARAMETER_RANGE
                    if "outside" in problem
                    else RejectCode.PARAMETER_TYPE
                )
                return Rejected.make(
                    code, f"{context}: {assignment.param_id}: {problem}", (context,)
                )
            return None
        case Animated(keyframes, interpolation):
            parameter = descriptor.parameter
            if isinstance(parameter, Static):
                return Rejected.make(
                    RejectCode.UNSUPPORTED_ANIMATION,
                    f"{context}: parameter {assignment.param_id!r} is static and cannot be"
                    " animated",
                    (context,),
                )
            assert isinstance(parameter, Animatable)
            if interpolation not in parameter.interpolations:
                return Rejected.make(
                    RejectCode.UNSUPPORTED_ANIMATION,
                    f"{context}: {assignment.param_id}: interpolation {interpolation.value} is not"
                    f" declared ({[i.value for i in parameter.interpolations]})",
                    (context,),
                )
            expected_domain: dict[TimeDomain, type[object]] = {
                TimeDomain.SEQUENCE_FRAME: FrameOffset,
                TimeDomain.SOURCE_TIME: SourceInstant,
                TimeDomain.NORMALIZED: Normalized,
            }
            for keyframe in keyframes:
                if type(keyframe.at) is not expected_domain[parameter.time_domain]:
                    return Rejected.make(
                        RejectCode.UNSUPPORTED_ANIMATION,
                        f"{context}: {assignment.param_id}: keyframe time domain must be"
                        f" {parameter.time_domain.value}",
                        (context,),
                    )
                problem = _value_matches(descriptor, keyframe.value)
                if problem is not None:
                    code = (
                        RejectCode.PARAMETER_RANGE
                        if "outside" in problem
                        else RejectCode.PARAMETER_TYPE
                    )
                    return Rejected.make(
                        code, f"{context}: {assignment.param_id}: {problem}", (context,)
                    )
            return None
