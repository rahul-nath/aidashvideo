"""Fixture catalog, synthetic GP-01 assets and builders for the project-domain tests.

The catalog is a small frozen descriptor set in the shape M2 will freeze from the installed
build; it declares what the tests need (a blur, an animatable transform, a transition, a
colour producer, a link, an unavailable service) and nothing is claimed qualified beyond
"test fixture".
"""

from __future__ import annotations

from fractions import Fraction

from aidashvideo.catalog.descriptors import (
    Animatable,
    Bounded,
    DescriptorCatalog,
    InterpolationKind,
    MetadataSource,
    ParameterDescriptor,
    ProfileConstraints,
    Qualified,
    RetimeCapabilities,
    ServiceDescriptor,
    ServiceType,
    Static,
    TimeDomain,
    Unavailable,
    Unbounded,
    ValueType,
)
from aidashvideo.ledger import ScopedLocator, Sha256, sha256_of
from aidashvideo.project.document import (
    AnalysisKind,
    AnalysisRef,
    AssetRef,
    ClipOccurrence,
    ClipTransform,
    EffectBinding,
    EvidenceArtifact,
    MaskRef,
    NoArtifact,
    NoMask,
    OccurrenceTarget,
    OutputProfile,
    Produced,
    ProjectDocument,
    ServiceRef,
    Unqualified,
)
from aidashvideo.project.params import Int, ParamAssignment, StaticValue
from aidashvideo.project.timing import (
    Normal,
    SequenceSpan,
    SourceSpan,
    Timing,
    duration_frames,
)
from aidashvideo.store import (
    Present,
    ProbeReceipt,
    SourceBinding,
    SourceIdentity,
    ToolIdentity,
    receipt_from_ffprobe,
)

F = Fraction
TOOL = ToolIdentity("ffprobe", "fixture-9.0.2", Sha256("cd" * 32))
FPS = F(30)
BUILD = "mlt-7.42.0-fixture"


def _param(
    param_id: str,
    value_type: ValueType,
    *,
    units: str = "",
    bounded: tuple[int, int] | None = None,
    animatable: bool = False,
    interpolations: tuple[InterpolationKind, ...] = (InterpolationKind.LINEAR,),
    values: tuple[str, ...] = (),
    default: dict[str, object] | None = None,
    mutable: bool = True,
) -> ParameterDescriptor:
    constraints = Bounded(F(bounded[0]), F(bounded[1])) if bounded else Unbounded()
    parameter: Static | Animatable
    if animatable:
        parameter = Animatable(
            value_type, units, constraints, TimeDomain.SEQUENCE_FRAME, interpolations
        )
    else:
        parameter = Static(value_type, units, constraints)
    return ParameterDescriptor(
        param_id,
        parameter,
        values,
        default or {"kind": "Int", "v": 0},
        mutable,
        MetadataSource.UPSTREAM_YAML,
    )


def _service(
    service_id: str,
    service_type: ServiceType,
    params: tuple[ParameterDescriptor, ...],
    qualification: Qualified | Unavailable | None = None,
) -> ServiceDescriptor:
    return ServiceDescriptor(
        service_id,
        service_type,
        "fixture",
        service_id,
        BUILD,
        params,
        (),
        "yuv420p",
        "s16 48000 stereo",
        (),
        (),
        qualification or Qualified("tests/project_support.py fixture"),
    )


def fixture_catalog(*, build: str = BUILD, without: tuple[str, ...] = ()) -> DescriptorCatalog:
    services = (
        _service(
            "avfilter.boxblur",
            ServiceType.FILTER,
            (_param("luma_radius", ValueType.INTEGER, units="px", bounded=(0, 100)),),
        ),
        _service(
            "affine",
            ServiceType.FILTER,
            (
                _param(
                    "transition.rect",
                    ValueType.GEOMETRY,
                    units="px",
                    animatable=True,
                    interpolations=(
                        InterpolationKind.DISCRETE,
                        InterpolationKind.LINEAR,
                        InterpolationKind.SMOOTH,
                    ),
                ),
            ),
        ),
        _service(
            "brightness",
            ServiceType.FILTER,
            (
                _param(
                    "level",
                    ValueType.FLOAT,
                    bounded=(0, 1),
                    animatable=True,
                    interpolations=(InterpolationKind.LINEAR,),
                ),
            ),
        ),
        _service(
            "volume",
            ServiceType.FILTER,
            (
                _param("gain", ValueType.FLOAT, units="dB", bounded=(-70, 24)),
                _param("fixed", ValueType.INTEGER, mutable=False),
            ),
        ),
        _service(
            "luma",
            ServiceType.TRANSITION,
            (
                _param("softness", ValueType.FLOAT, bounded=(0, 1)),
                _param("invert", ValueType.BOOLEAN),
            ),
        ),
        _service(
            "mix",
            ServiceType.TRANSITION,
            (_param("mode", ValueType.ENUM, values=("crossfade", "sum")),),
        ),
        _service("color", ServiceType.PRODUCER, (_param("resource", ValueType.COLOR),)),
        _service(
            "timeremap", ServiceType.LINK, (_param("speed", ValueType.FLOAT, bounded=(-10, 10)),)
        ),
        _service(
            "frei0r.baltan",
            ServiceType.FILTER,
            (),
            Unavailable("frei0r plugin directory not found", "install frei0r 3.6.0 and refreeze"),
        ),
    )
    kept = tuple(s for s in services if s.service_id not in without)
    if build != BUILD:
        from dataclasses import replace

        kept = tuple(replace(s, build_id=build) for s in kept)
    return DescriptorCatalog(
        build,
        kept,
        RetimeCapabilities(("Reverse", "Hold", "Variable"), ("Hold", "Linear"), F(1, 10), F(10)),
        ProfileConstraints(
            (F(24), F(25), F(30), F(30000, 1001), F(50), F(60)),
            3840,
            2160,
            (48000,),
            ("Stereo",),
            ("Mp4H264Aac",),
            ("Sdr709",),
        ),
    )


CATALOG = fixture_catalog()
NO_ARTIFACT = NoArtifact()


def ref(service_id: str, catalog: DescriptorCatalog = CATALOG) -> ServiceRef:
    return ServiceRef(service_id, catalog.digest)


# ----------------------------------------------------------------------------- assets


def _video(
    index: int, fps: str = "30/1", width: int = 1920, height: int = 1080
) -> dict[str, object]:
    return {
        "index": index,
        "codec_type": "video",
        "codec_name": "h264",
        "width": width,
        "height": height,
        "sample_aspect_ratio": "1:1",
        "r_frame_rate": fps,
        "avg_frame_rate": fps,
        "time_base": "1/15360",
        "start_pts": 0,
        "start_time": "0.000000",
        "has_b_frames": 0,
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }


def _audio(index: int) -> dict[str, object]:
    return {
        "index": index,
        "codec_type": "audio",
        "codec_name": "aac",
        "sample_rate": "48000",
        "channels": 2,
        "channel_layout": "stereo",
        "time_base": "1/48000",
        "start_pts": 0,
        "start_time": "0.000000",
    }


def receipt(duration: str, streams: list[dict[str, object]]) -> ProbeReceipt:
    return receipt_from_ffprobe({"streams": streams, "format": {"duration": duration}}, {}, TOOL)


INTERVIEW = receipt("12.000000", [_video(0), _audio(1)])
BROLL = receipt("4.000000", [_video(0)])
MUSIC = receipt("20.000000", [{**_audio(0), "codec_name": "pcm_s16le"}])


def identity(name: str, receipt_: ProbeReceipt) -> SourceIdentity:
    return SourceIdentity(sha256_of(name.encode()), 1000 + len(name), receipt_.receipt_id)


def asset(name: str, receipt_: ProbeReceipt, grant_id: str) -> AssetRef:
    ident = identity(name, receipt_)
    return AssetRef(
        name,
        ident,
        Present(ident.sha256, ScopedLocator(grant_id, f"media/{name}"), ident.probe_receipt_id),
    )


def gp01_document(grant_id: str = "pg-fixture") -> ProjectDocument:
    doc = ProjectDocument.new(OutputProfile.default())
    from dataclasses import replace

    return replace(
        doc,
        assets=(
            asset("interview", INTERVIEW, grant_id),
            asset("broll", BROLL, grant_id),
            asset("music", MUSIC, grant_id),
        ),
        probes=(INTERVIEW, BROLL, MUSIC),
    )


def binding_of(doc: ProjectDocument, asset_id: str, stream_index: int) -> SourceBinding:
    found = doc.asset(asset_id)
    assert found is not None
    return SourceBinding(found.identity.sha256, stream_index, found.identity.probe_receipt_id)


# ----------------------------------------------------------------------------- builders


def occurrence(
    occurrence_id: str,
    asset_id: str,
    in_: F | int,
    out: F | int,
    start: int,
    *,
    stream_index: int = 0,
    timing: Timing | None = None,
    fps: F = FPS,
) -> ClipOccurrence:
    t: Timing = timing if timing is not None else Normal()
    source = SourceSpan.make(in_, out)
    frames = duration_frames(source, t, fps)
    return ClipOccurrence(
        occurrence_id,
        asset_id,
        stream_index,
        source,
        SequenceSpan.make(start, start + frames),
        t,
        ClipTransform.identity(),
    )


def blur(effect_id: str, occurrence_id: str, track: str, radius: int = 20) -> EffectBinding:
    return EffectBinding(
        effect_id,
        OccurrenceTarget(occurrence_id),
        ref("avfilter.boxblur"),
        (ParamAssignment("luma_radius", StaticValue(Int(radius))),),
        MaskRef(track),
    )


def plain_effect(
    effect_id: str, occurrence_id: str, service_id: str, params: tuple[ParamAssignment, ...] = ()
) -> EffectBinding:
    return EffectBinding(
        effect_id, OccurrenceTarget(occurrence_id), ref(service_id), params, NoMask()
    )


def transcript_ref(
    doc: ProjectDocument,
    ref_id: str,
    asset_id: str,
    stream_index: int,
    coverage: tuple[SourceSpan, ...],
    artifact: NoArtifact | EvidenceArtifact = NO_ARTIFACT,
) -> AnalysisRef:
    return AnalysisRef(
        AnalysisKind.TRANSCRIPT,
        ref_id,
        binding_of(doc, asset_id, stream_index),
        coverage,
        Produced(Unqualified("segment timing from the fixture; not word-qualified (D4)")),
        artifact,
    )


def mask_ref(
    doc: ProjectDocument, ref_id: str, asset_id: str, coverage: tuple[SourceSpan, ...]
) -> AnalysisRef:
    return AnalysisRef(
        AnalysisKind.MASK_TRACK,
        ref_id,
        binding_of(doc, asset_id, 0),
        coverage,
        Produced(Unqualified("explicit unqualified fixture coverage; no provider ran")),
        NO_ARTIFACT,
    )
