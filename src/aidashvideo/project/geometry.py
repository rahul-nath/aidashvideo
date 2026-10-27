"""Sole owner of pixel geometry: source/sequence pixels, orientation, mask grids (contracts §4).

* ``SourcePixel``: the decoded, unrotated buffer with its ``sar``.
* ``OrientedGrid``: the rotation-applied grid with square pixels; masks live here so they
  never depend on the sequence profile.
* ``SequencePixel``: the output profile's frame.

``display_affine(stream, profile)`` = ``fit(Contain) ∘ rotation ∘ sar_normalize`` (applied
right to left) as one exact :class:`Affine2D`. Selections arriving in sequence pixels (UI)
or oriented pixels (tool) are validated against the frame bounds; anything outside is
``RejectedSelection``.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from aidashvideo.ledger.canonical import (
    as_int,
    as_object,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, widen
from aidashvideo.store.identity import Rotation, VideoStream


def _fraction(value: object, what: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, Fraction | int):
        raise ContractError(f"{what} must be an exact rational")
    return Fraction(value)


@dataclass(frozen=True, slots=True)
class Affine2D:
    """``x' = a*x + b*y + c``; ``y' = d*x + e*y + f`` with exact coefficients."""

    a: Fraction
    b: Fraction
    c: Fraction
    d: Fraction
    e: Fraction
    f: Fraction

    def __post_init__(self) -> None:
        for name in ("a", "b", "c", "d", "e", "f"):
            if not isinstance(widen(getattr(self, name)), Fraction):
                raise ContractError(f"Affine2D.{name} must be a Fraction")
        if self.determinant == 0:
            raise ContractError("Affine2D must be invertible")

    @classmethod
    def make(
        cls,
        a: Fraction | int,
        b: Fraction | int,
        c: Fraction | int,
        d: Fraction | int,
        e: Fraction | int,
        f: Fraction | int,
    ) -> Affine2D:
        return cls(*(Fraction(v) for v in (a, b, c, d, e, f)))

    @classmethod
    def identity(cls) -> Affine2D:
        return cls.make(1, 0, 0, 0, 1, 0)

    @classmethod
    def scale(cls, sx: Fraction | int, sy: Fraction | int) -> Affine2D:
        return cls.make(sx, 0, 0, 0, sy, 0)

    @classmethod
    def translate(cls, tx: Fraction | int, ty: Fraction | int) -> Affine2D:
        return cls.make(1, 0, tx, 0, 1, ty)

    @property
    def determinant(self) -> Fraction:
        return self.a * self.e - self.b * self.d

    def apply(self, x: Fraction, y: Fraction) -> tuple[Fraction, Fraction]:
        return (self.a * x + self.b * y + self.c, self.d * x + self.e * y + self.f)

    def then(self, other: Affine2D) -> Affine2D:
        """``other ∘ self``: apply ``self`` first, then ``other``."""
        return Affine2D(
            other.a * self.a + other.b * self.d,
            other.a * self.b + other.b * self.e,
            other.a * self.c + other.b * self.f + other.c,
            other.d * self.a + other.e * self.d,
            other.d * self.b + other.e * self.e,
            other.d * self.c + other.e * self.f + other.f,
        )

    def inverse(self) -> Affine2D:
        det = self.determinant
        ia, ib, id_, ie = self.e / det, -self.b / det, -self.d / det, self.a / det
        return Affine2D(
            ia, ib, -(ia * self.c + ib * self.f), id_, ie, -(id_ * self.c + ie * self.f)
        )

    def to_json(self) -> dict[str, object]:
        return {k: rational_to_json(getattr(self, k)) for k in ("a", "b", "c", "d", "e", "f")}


@dataclass(frozen=True, slots=True)
class OrientedGrid:
    """Square-pixel grid after rotation (the mask coordinate contract)."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if not is_int(self.width) or not is_int(self.height) or self.width < 1 or self.height < 1:
            raise ContractError("OrientedGrid dimensions must be positive integers")

    def to_json(self) -> dict[str, object]:
        return {"width": self.width, "height": self.height}

    @classmethod
    def from_json(cls, raw: object) -> OrientedGrid:
        data = as_object(raw, "OrientedGrid")
        require_keys(data, "OrientedGrid", ("width", "height"))
        return cls(as_int(data["width"], "width"), as_int(data["height"], "height"))


@dataclass(frozen=True, slots=True)
class Point:
    x: Fraction
    y: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.x), Fraction) or not isinstance(widen(self.y), Fraction):
            raise ContractError("Point coordinates must be Fractions")

    @classmethod
    def make(cls, x: Fraction | int, y: Fraction | int) -> Point:
        return cls(_fraction(x, "Point.x"), _fraction(y, "Point.y"))

    def to_json(self) -> dict[str, object]:
        return {"x": rational_to_json(self.x), "y": rational_to_json(self.y)}

    @classmethod
    def from_json(cls, raw: object) -> Point:
        data = as_object(raw, "Point")
        require_keys(data, "Point", ("x", "y"))
        return cls(rational_from_json(data["x"], "x"), rational_from_json(data["y"], "y"))


@dataclass(frozen=True, slots=True)
class Box:
    """Half-open axis-aligned box ``[x0, x1) x [y0, y1)``."""

    x0: Fraction
    y0: Fraction
    x1: Fraction
    y1: Fraction

    def __post_init__(self) -> None:
        for name in ("x0", "y0", "x1", "y1"):
            if not isinstance(widen(getattr(self, name)), Fraction):
                raise ContractError(f"Box.{name} must be a Fraction")
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ContractError("Box must have positive width and height")

    @classmethod
    def make(
        cls, x0: Fraction | int, y0: Fraction | int, x1: Fraction | int, y1: Fraction | int
    ) -> Box:
        return cls(*(Fraction(v) for v in (x0, y0, x1, y1)))

    @property
    def width(self) -> Fraction:
        return self.x1 - self.x0

    @property
    def height(self) -> Fraction:
        return self.y1 - self.y0

    def to_json(self) -> dict[str, object]:
        return {k: rational_to_json(getattr(self, k)) for k in ("x0", "y0", "x1", "y1")}

    @classmethod
    def from_json(cls, raw: object) -> Box:
        data = as_object(raw, "Box")
        require_keys(data, "Box", ("x0", "y0", "x1", "y1"))
        return cls(*(rational_from_json(data[k], k) for k in ("x0", "y0", "x1", "y1")))


# ----------------------------------------------------------------------------- orientation


def sar_normalized_size(stream: VideoStream) -> tuple[Fraction, Fraction]:
    """Width scaled by the sample aspect ratio; height unchanged (square pixels)."""
    return (Fraction(stream.width) * stream.sar, Fraction(stream.height))


def sar_normalize(stream: VideoStream) -> Affine2D:
    return Affine2D.scale(stream.sar, 1)


def rotation_affine(rotation: Rotation, width: Fraction, height: Fraction) -> Affine2D:
    """Rotate a ``width x height`` square-pixel buffer clockwise for display.

    ``R90``: ``(x, y) -> (height - y, x)``; the oriented grid is ``height x width``.
    """
    match rotation:
        case Rotation.R0:
            return Affine2D.identity()
        case Rotation.R90:
            return Affine2D.make(0, -1, height, 1, 0, 0)
        case Rotation.R180:
            return Affine2D.make(-1, 0, width, 0, -1, height)
        case Rotation.R270:
            return Affine2D.make(0, 1, 0, -1, 0, width)


def oriented_size(stream: VideoStream) -> tuple[Fraction, Fraction]:
    w, h = sar_normalized_size(stream)
    if stream.rotation in (Rotation.R90, Rotation.R270):
        return (h, w)
    return (w, h)


def oriented_grid(stream: VideoStream) -> OrientedGrid:
    """Integer grid of the oriented source; a non-integer SAR-normalized width rounds to
    the nearest pixel (the only rounding in geometry, recorded here)."""
    w, h = oriented_size(stream)
    return OrientedGrid(max(1, round(w)), max(1, round(h)))


def source_to_oriented(stream: VideoStream) -> Affine2D:
    """``rotation ∘ sar_normalize``: source pixels into the oriented grid (exact)."""
    w, h = sar_normalized_size(stream)
    return sar_normalize(stream).then(rotation_affine(stream.rotation, w, h))


@dataclass(frozen=True, slots=True)
class ProfileFrame:
    width: int
    height: int

    def __post_init__(self) -> None:
        if not is_int(self.width) or not is_int(self.height) or self.width < 1 or self.height < 1:
            raise ContractError("ProfileFrame dimensions must be positive integers")


def fit_contain(
    oriented_width: Fraction, oriented_height: Fraction, frame: ProfileFrame
) -> Affine2D:
    """Uniform scale to fit inside the frame, centred (letterbox/pillarbox, never crop)."""
    scale = min(Fraction(frame.width) / oriented_width, Fraction(frame.height) / oriented_height)
    tx = (Fraction(frame.width) - oriented_width * scale) / 2
    ty = (Fraction(frame.height) - oriented_height * scale) / 2
    return Affine2D.scale(scale, scale).then(Affine2D.translate(tx, ty))


def display_affine(stream: VideoStream, frame: ProfileFrame) -> Affine2D:
    """Source pixel -> sequence pixel: ``fit(Contain) ∘ rotation ∘ sar_normalize``."""
    w, h = oriented_size(stream)
    return source_to_oriented(stream).then(fit_contain(w, h, frame))


def oriented_to_sequence(stream: VideoStream, frame: ProfileFrame) -> Affine2D:
    w, h = oriented_size(stream)
    return fit_contain(w, h, frame)


def transform_box(affine: Affine2D, box: Box) -> Box:
    """Hull of the transformed corners (exact for rotations by multiples of 90 degrees
    and axis-aligned scaling; half-open semantics are preserved by taking the hull)."""
    corners = [affine.apply(x, y) for x in (box.x0, box.x1) for y in (box.y0, box.y1)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return Box(min(xs), min(ys), max(xs), max(ys))


def transform_point(affine: Affine2D, point: Point) -> Point:
    x, y = affine.apply(point.x, point.y)
    return Point(x, y)


# ----------------------------------------------------------------------------- selections


@dataclass(frozen=True, slots=True)
class ValidatedPoint:
    grid: OrientedGrid
    point: Point


@dataclass(frozen=True, slots=True)
class ValidatedBox:
    grid: OrientedGrid
    box: Box


@dataclass(frozen=True, slots=True)
class RejectedSelection:
    detail: str


def validate_point(grid: OrientedGrid, point: Point) -> ValidatedPoint | RejectedSelection:
    if not (0 <= point.x < grid.width and 0 <= point.y < grid.height):
        return RejectedSelection(
            f"point ({point.x}, {point.y}) is outside the {grid.width}x{grid.height} frame"
        )
    return ValidatedPoint(grid, point)


def validate_box(grid: OrientedGrid, box: Box) -> ValidatedBox | RejectedSelection:
    if box.x0 < 0 or box.y0 < 0 or box.x1 > grid.width or box.y1 > grid.height:
        return RejectedSelection(
            f"box [{box.x0},{box.x1})x[{box.y0},{box.y1}) exceeds the"
            f" {grid.width}x{grid.height} frame"
        )
    return ValidatedBox(grid, box)


def sequence_point_to_oriented(
    stream: VideoStream, frame: ProfileFrame, point: Point
) -> ValidatedPoint | RejectedSelection:
    """A UI click in sequence pixels mapped onto the source's oriented grid and validated
    (clicks on letterbox bars are outside the frame and rejected)."""
    mapped = transform_point(oriented_to_sequence(stream, frame).inverse(), point)
    return validate_point(oriented_grid(stream), mapped)


def sequence_box_to_oriented(
    stream: VideoStream, frame: ProfileFrame, box: Box
) -> ValidatedBox | RejectedSelection:
    mapped = transform_box(oriented_to_sequence(stream, frame).inverse(), box)
    return validate_box(oriented_grid(stream), mapped)


def source_box_to_oriented(stream: VideoStream, box: Box) -> ValidatedBox | RejectedSelection:
    """Ground-truth boxes given in unrotated source pixels (fixtures) onto the oriented grid."""
    return validate_box(oriented_grid(stream), transform_box(source_to_oriented(stream), box))
