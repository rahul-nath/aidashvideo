"""Service descriptors (``MLTService`` / ``MLTParameter``, contracts §2 and the
``aidashvideo.service-descriptor/1`` wire schema) and the descriptor catalog a revision's
operations are validated against.

M1 defines the closed shapes, the catalog digest and JSON round trip; M2a fills a catalog
from ``melt -query`` of the installed build (``descriptors.freeze``) and reconciles it with
the frozen inventory. Nothing here imports MLT.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from aidashvideo.ledger.canonical import (
    as_bool,
    as_int,
    as_list,
    as_object,
    as_str,
    canonical_bytes,
    canonical_sha256,
    field,
    parse_json,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, is_str, widen
from aidashvideo.ledger.ids import Sha256

DESCRIPTOR_SCHEMA_ID = "aidashvideo.service-descriptor/1"
CATALOG_SCHEMA_ID = "aidashvideo.descriptor-catalog/1"


class ServiceType(StrEnum):
    PRODUCER = "producer"
    FILTER = "filter"
    TRANSITION = "transition"
    LINK = "link"
    CONSUMER = "consumer"


class ValueType(StrEnum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    STRING = "string"
    COLOR = "color"
    RECT = "rect"
    ENUM = "enum"
    GEOMETRY = "geometry"


class TimeDomain(StrEnum):
    SEQUENCE_FRAME = "sequence_frame"
    SOURCE_TIME = "source_time"
    NORMALIZED = "normalized"


class InterpolationKind(StrEnum):
    DISCRETE = "discrete"
    LINEAR = "linear"
    SMOOTH = "smooth"


class MetadataSource(StrEnum):
    UPSTREAM_YAML = "upstream_yaml"
    VERSION_BOUND = "version_bound_descriptor"


class ResourceKind(StrEnum):
    MEDIA = "media"
    FONT = "font"
    PLUGIN = "plugin"
    LUT = "lut"


def _enum[E: StrEnum](kind: type[E], raw: object, what: str) -> E:
    try:
        return kind(as_str(raw, what))
    except ValueError as exc:
        raise ContractError(f"{what}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Unbounded:
    def to_json(self) -> dict[str, object]:
        return {"kind": "Unbounded"}


@dataclass(frozen=True, slots=True)
class Bounded:
    minimum: Fraction
    maximum: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.minimum), Fraction) or not isinstance(
            widen(self.maximum), Fraction
        ):
            raise ContractError("Bounded limits must be Fractions")
        if self.maximum < self.minimum:
            raise ContractError("Bounded: maximum below minimum")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Bounded",
            "minimum": rational_to_json(self.minimum),
            "maximum": rational_to_json(self.maximum),
        }


type Constraints = Unbounded | Bounded


def constraints_from_json(raw: object) -> Constraints:
    data = as_object(raw, "constraints")
    kind = as_str(field(data, "kind", "constraints"), "constraints.kind")
    if kind == "Unbounded":
        require_keys(data, "constraints", ("kind",))
        return Unbounded()
    if kind == "Bounded":
        require_keys(data, "constraints", ("kind", "minimum", "maximum"))
        return Bounded(
            rational_from_json(data["minimum"], "minimum"),
            rational_from_json(data["maximum"], "maximum"),
        )
    raise ContractError(f"constraints: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class Static:
    value_type: ValueType
    units: str
    constraints: Constraints

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Static",
            "value_type": self.value_type.value,
            "units": self.units,
            "constraints": self.constraints.to_json(),
        }


@dataclass(frozen=True, slots=True)
class Animatable:
    value_type: ValueType
    units: str
    constraints: Constraints
    time_domain: TimeDomain
    interpolations: tuple[InterpolationKind, ...]

    def __post_init__(self) -> None:
        if not self.interpolations:
            raise ContractError("Animatable parameters declare at least one interpolation")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Animatable",
            "value_type": self.value_type.value,
            "units": self.units,
            "constraints": self.constraints.to_json(),
            "time_domain": self.time_domain.value,
            "interpolations": [i.value for i in self.interpolations],
        }


type MLTParameter = Static | Animatable


def parameter_from_json(raw: object) -> MLTParameter:
    data = as_object(raw, "MLTParameter")
    kind = as_str(field(data, "kind", "MLTParameter"), "MLTParameter.kind")
    if kind == "Static":
        require_keys(data, "Static", ("kind", "value_type", "units", "constraints"))
        return Static(
            _enum(ValueType, data["value_type"], "value_type"),
            as_str(data["units"], "units"),
            constraints_from_json(data["constraints"]),
        )
    if kind == "Animatable":
        require_keys(
            data,
            "Animatable",
            ("kind", "value_type", "units", "constraints", "time_domain", "interpolations"),
        )
        return Animatable(
            _enum(ValueType, data["value_type"], "value_type"),
            as_str(data["units"], "units"),
            constraints_from_json(data["constraints"]),
            _enum(TimeDomain, data["time_domain"], "time_domain"),
            tuple(
                _enum(InterpolationKind, i, "interpolations[]")
                for i in as_list(data["interpolations"], "interpolations")
            ),
        )
    raise ContractError(f"MLTParameter: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class ParameterDescriptor:
    param_id: str
    parameter: MLTParameter
    values: tuple[str, ...]
    """Enum choices; non-empty exactly when ``value_type`` is ``enum``."""

    default: dict[str, object]
    """JSON form of a ``ParamValue`` (validated by the project domain)."""

    mutable: bool
    metadata_source: MetadataSource

    def __post_init__(self) -> None:
        if not is_str(self.param_id) or not self.param_id:
            raise ContractError("ParameterDescriptor.param_id must be non-empty")
        is_enum = self.parameter.value_type is ValueType.ENUM
        if is_enum != bool(self.values):
            raise ContractError(
                f"parameter {self.param_id}: enum values are required exactly for enum types"
            )
        canonical_bytes(self.default)

    @property
    def value_type(self) -> ValueType:
        return self.parameter.value_type

    def to_json(self) -> dict[str, object]:
        return {
            "param_id": self.param_id,
            "parameter": self.parameter.to_json(),
            "values": list(self.values),
            "default": self.default,
            "mutable": self.mutable,
            "metadata_source": self.metadata_source.value,
        }

    @classmethod
    def from_json(cls, raw: object) -> ParameterDescriptor:
        data = as_object(raw, "ParameterDescriptor")
        require_keys(
            data,
            "ParameterDescriptor",
            ("param_id", "parameter", "values", "default", "mutable", "metadata_source"),
        )
        return cls(
            as_str(data["param_id"], "param_id"),
            parameter_from_json(data["parameter"]),
            tuple(as_str(v, "values[]") for v in as_list(data["values"], "values")),
            as_object(data["default"], "default"),
            as_bool(data["mutable"], "mutable"),
            _enum(MetadataSource, data["metadata_source"], "metadata_source"),
        )


@dataclass(frozen=True, slots=True)
class ResourceRule:
    param_id: str
    kind: ResourceKind
    rule: str = "scoped_locator_only"

    def __post_init__(self) -> None:
        if self.rule != "scoped_locator_only":
            raise ContractError("ResourceRule.rule must be scoped_locator_only")

    def to_json(self) -> dict[str, object]:
        return {"param_id": self.param_id, "kind": self.kind.value, "rule": self.rule}


@dataclass(frozen=True, slots=True)
class Qualified:
    evidence: str

    def __post_init__(self) -> None:
        if not is_str(self.evidence) or not self.evidence:
            raise ContractError("Qualified needs evidence")

    def to_json(self) -> dict[str, object]:
        return {"state": "Qualified", "evidence": self.evidence}


@dataclass(frozen=True, slots=True)
class Unavailable:
    reason: str
    required_action: str

    def to_json(self) -> dict[str, object]:
        return {
            "state": "Unavailable",
            "reason": self.reason,
            "required_action": self.required_action,
        }


type Qualification = Qualified | Unavailable


def qualification_from_json(raw: object) -> Qualification:
    data = as_object(raw, "qualification")
    state = as_str(field(data, "state", "qualification"), "qualification.state")
    if state == "Qualified":
        require_keys(data, "qualification", ("state", "evidence"))
        return Qualified(as_str(data["evidence"], "evidence"))
    if state == "Unavailable":
        require_keys(data, "qualification", ("state", "reason", "required_action"))
        return Unavailable(
            as_str(data["reason"], "reason"), as_str(data["required_action"], "required_action")
        )
    raise ContractError(f"qualification: unknown state {state!r}")


@dataclass(frozen=True, slots=True)
class ServiceDescriptor:
    service_id: str
    service_type: ServiceType
    module: str
    title: str
    build_id: str
    parameters: tuple[ParameterDescriptor, ...]
    resources: tuple[ResourceRule, ...]
    pixel_constraints: str
    audio_constraints: str
    interactions: tuple[str, ...]
    dependencies: tuple[str, ...]
    qualification: Qualification

    def __post_init__(self) -> None:
        if not is_str(self.service_id) or not self.service_id:
            raise ContractError("ServiceDescriptor.service_id must be non-empty")
        ids = [p.param_id for p in self.parameters]
        if len(set(ids)) != len(ids):
            raise ContractError(f"service {self.service_id}: duplicate parameter ids")
        for rule in self.resources:
            if rule.param_id not in ids:
                raise ContractError(
                    f"service {self.service_id}: resource rule for unknown parameter"
                )

    def parameter(self, param_id: str) -> ParameterDescriptor | None:
        for p in self.parameters:
            if p.param_id == param_id:
                return p
        return None

    def to_json(self, catalog_digest: str) -> dict[str, object]:
        return {
            "$id": DESCRIPTOR_SCHEMA_ID,
            "service_id": self.service_id,
            "service_type": self.service_type.value,
            "module": self.module,
            "title": self.title,
            "build_id": self.build_id,
            "catalog_digest": catalog_digest,
            "parameters": [p.to_json() for p in self.parameters],
            "resources": [r.to_json() for r in self.resources],
            "pixel_constraints": self.pixel_constraints,
            "audio_constraints": self.audio_constraints,
            "interactions": list(self.interactions),
            "dependencies": list(self.dependencies),
            "qualification": self.qualification.to_json(),
        }

    def identity_json(self) -> dict[str, object]:
        body = self.to_json("")
        del body["catalog_digest"]
        return body

    @classmethod
    def from_json(cls, raw: object) -> ServiceDescriptor:
        data = as_object(raw, "ServiceDescriptor")
        require_keys(
            data,
            "ServiceDescriptor",
            (
                "$id",
                "service_id",
                "service_type",
                "module",
                "title",
                "build_id",
                "catalog_digest",
                "parameters",
                "resources",
                "pixel_constraints",
                "audio_constraints",
                "interactions",
                "dependencies",
                "qualification",
            ),
        )
        if data["$id"] != DESCRIPTOR_SCHEMA_ID:
            raise ContractError("ServiceDescriptor: unsupported $id")
        resources: list[ResourceRule] = []
        for raw_rule in as_list(data["resources"], "resources"):
            rule = as_object(raw_rule, "ResourceRule")
            require_keys(rule, "ResourceRule", ("param_id", "kind", "rule"))
            resources.append(
                ResourceRule(
                    as_str(rule["param_id"], "param_id"),
                    _enum(ResourceKind, rule["kind"], "kind"),
                    as_str(rule["rule"], "rule"),
                )
            )
        return cls(
            as_str(data["service_id"], "service_id"),
            _enum(ServiceType, data["service_type"], "service_type"),
            as_str(data["module"], "module"),
            as_str(data["title"], "title"),
            as_str(data["build_id"], "build_id"),
            tuple(
                ParameterDescriptor.from_json(p) for p in as_list(data["parameters"], "parameters")
            ),
            tuple(resources),
            as_str(data["pixel_constraints"], "pixel_constraints"),
            as_str(data["audio_constraints"], "audio_constraints"),
            tuple(
                as_str(i, "interactions[]") for i in as_list(data["interactions"], "interactions")
            ),
            tuple(
                as_str(d, "dependencies[]") for d in as_list(data["dependencies"], "dependencies")
            ),
            qualification_from_json(data["qualification"]),
        )


@dataclass(frozen=True, slots=True)
class Callable:
    build_id: str
    descriptor: ServiceDescriptor
    qualification: Qualified


@dataclass(frozen=True, slots=True)
class ServiceUnavailable:
    service_id: str
    reason: str
    required_action: str


type MLTService = Callable | ServiceUnavailable


@dataclass(frozen=True, slots=True)
class RetimeCapabilities:
    """Which ``TimeMap`` modes/interpolations and constant speed ratios the build supports."""

    modes: tuple[str, ...]
    interpolations: tuple[str, ...]
    min_speed: Fraction
    max_speed: Fraction

    def __post_init__(self) -> None:
        for mode in self.modes:
            if mode not in ("Reverse", "Hold", "Variable"):
                raise ContractError(f"RetimeCapabilities: unknown mode {mode!r}")
        for interp in self.interpolations:
            if interp not in ("Hold", "Linear"):
                raise ContractError(f"RetimeCapabilities: unknown interpolation {interp!r}")
        if self.min_speed <= 0 or self.max_speed < self.min_speed:
            raise ContractError("RetimeCapabilities: speed range must be positive and ordered")

    def to_json(self) -> dict[str, object]:
        return {
            "modes": list(self.modes),
            "interpolations": list(self.interpolations),
            "min_speed": rational_to_json(self.min_speed),
            "max_speed": rational_to_json(self.max_speed),
        }

    @classmethod
    def from_json(cls, raw: object) -> RetimeCapabilities:
        data = as_object(raw, "RetimeCapabilities")
        require_keys(
            data, "RetimeCapabilities", ("modes", "interpolations", "min_speed", "max_speed")
        )
        return cls(
            tuple(as_str(m, "modes[]") for m in as_list(data["modes"], "modes")),
            tuple(
                as_str(i, "interpolations[]")
                for i in as_list(data["interpolations"], "interpolations")
            ),
            rational_from_json(data["min_speed"], "min_speed"),
            rational_from_json(data["max_speed"], "max_speed"),
        )


@dataclass(frozen=True, slots=True)
class ProfileConstraints:
    """Output profiles the build can render (the initial SDR Rec.709 1080p30 profile plus
    whatever the frozen consumer descriptors allow)."""

    frame_rates: tuple[Fraction, ...]
    max_width: int
    max_height: int
    sample_rates: tuple[int, ...]
    layouts: tuple[str, ...]
    containers: tuple[str, ...]
    colors: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.frame_rates or any(f <= 0 for f in self.frame_rates):
            raise ContractError("ProfileConstraints.frame_rates must be positive")
        if not is_int(self.max_width) or not is_int(self.max_height) or self.max_width < 16:
            raise ContractError("ProfileConstraints dimensions are invalid")

    def to_json(self) -> dict[str, object]:
        return {
            "frame_rates": [rational_to_json(f) for f in self.frame_rates],
            "max_width": self.max_width,
            "max_height": self.max_height,
            "sample_rates": list(self.sample_rates),
            "layouts": list(self.layouts),
            "containers": list(self.containers),
            "colors": list(self.colors),
        }

    @classmethod
    def from_json(cls, raw: object) -> ProfileConstraints:
        data = as_object(raw, "ProfileConstraints")
        require_keys(
            data,
            "ProfileConstraints",
            (
                "frame_rates",
                "max_width",
                "max_height",
                "sample_rates",
                "layouts",
                "containers",
                "colors",
            ),
        )
        return cls(
            tuple(
                rational_from_json(f, "frame_rates[]")
                for f in as_list(data["frame_rates"], "frame_rates")
            ),
            as_int(data["max_width"], "max_width"),
            as_int(data["max_height"], "max_height"),
            tuple(
                as_int(s, "sample_rates[]") for s in as_list(data["sample_rates"], "sample_rates")
            ),
            tuple(as_str(s, "layouts[]") for s in as_list(data["layouts"], "layouts")),
            tuple(as_str(s, "containers[]") for s in as_list(data["containers"], "containers")),
            tuple(as_str(s, "colors[]") for s in as_list(data["colors"], "colors")),
        )


@dataclass(frozen=True, slots=True)
class DescriptorCatalog:
    """The frozen descriptor set of one build; ``digest`` is an observed fact (D11)."""

    build_id: str
    services: tuple[ServiceDescriptor, ...]
    retime: RetimeCapabilities
    profile: ProfileConstraints

    def __post_init__(self) -> None:
        ids = [s.service_id for s in self.services]
        if len(set(ids)) != len(ids):
            raise ContractError("DescriptorCatalog: duplicate service ids")
        for s in self.services:
            if s.build_id != self.build_id:
                raise ContractError(f"service {s.service_id} belongs to build {s.build_id}")

    @property
    def digest(self) -> Sha256:
        return canonical_sha256(self.identity_json())

    def identity_json(self) -> dict[str, object]:
        return {
            "$id": CATALOG_SCHEMA_ID,
            "build_id": self.build_id,
            "services": [s.identity_json() for s in self.services],
            "retime": self.retime.to_json(),
            "profile": self.profile.to_json(),
        }

    def to_json(self) -> dict[str, object]:
        digest = self.digest.hex
        return {
            "$id": CATALOG_SCHEMA_ID,
            "build_id": self.build_id,
            "catalog_digest": digest,
            "services": [s.to_json(digest) for s in self.services],
            "retime": self.retime.to_json(),
            "profile": self.profile.to_json(),
        }

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.to_json())

    @classmethod
    def from_json(cls, raw: object) -> DescriptorCatalog:
        data = as_object(raw, "DescriptorCatalog")
        require_keys(
            data,
            "DescriptorCatalog",
            ("$id", "build_id", "catalog_digest", "services", "retime", "profile"),
        )
        if data["$id"] != CATALOG_SCHEMA_ID:
            raise ContractError("DescriptorCatalog: unsupported $id")
        catalog = cls(
            as_str(data["build_id"], "build_id"),
            tuple(ServiceDescriptor.from_json(s) for s in as_list(data["services"], "services")),
            RetimeCapabilities.from_json(data["retime"]),
            ProfileConstraints.from_json(data["profile"]),
        )
        if catalog.digest.hex != as_str(data["catalog_digest"], "catalog_digest"):
            raise ContractError("DescriptorCatalog: recorded digest does not match the content")
        return catalog

    @classmethod
    def from_bytes(cls, data: bytes) -> DescriptorCatalog:
        return cls.from_json(parse_json(data))

    def find(self, service_id: str) -> ServiceDescriptor | None:
        for s in self.services:
            if s.service_id == service_id:
                return s
        return None

    def service(self, service_id: str) -> MLTService:
        found = self.find(service_id)
        if found is None:
            return ServiceUnavailable(
                service_id,
                "not in the frozen descriptor catalog of this build",
                "freeze the installed build (python -m aidashvideo.catalog.descriptors"
                " --freeze, M2)",
            )
        if isinstance(found.qualification, Unavailable):
            return ServiceUnavailable(
                service_id, found.qualification.reason, found.qualification.required_action
            )
        return Callable(found.build_id, found, found.qualification)
