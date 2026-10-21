"""Child-process MLT probe (run via ``python -m``; see :func:`mlt.run_native_probe`).

Prints one JSON line: bindings version, the complete service catalog, a rendered
frame check and, when a target path is given, renders one second of 1080p30
video + 48 kHz stereo audio through the avformat consumer.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def main(argv: list[str]) -> int:
    import mlt7 as mlt  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

    m: Any = mlt
    repo: Any = m.Factory.init()
    if repo is None:
        raise SystemExit("mlt Factory.init() returned no repository")
    catalog: dict[str, list[str]] = {}
    for kind in ("producers", "filters", "transitions", "consumers", "links"):
        props: Any = getattr(repo, kind)()
        catalog[kind] = sorted(props.get_name(i) for i in range(props.count()))

    profile: Any = m.Profile("atsc_1080p_30")
    producer: Any = m.Producer(profile, "color:#336699")
    flt: Any = m.Filter(profile, "brightness")
    if not (producer.is_valid() and flt.is_valid()):
        raise SystemExit("core producer/filter unavailable")
    flt.set("level", 0.5)
    producer.attach(flt)
    frame: Any = producer.get_frame()
    image: Any = frame.get_image(m.mlt_image_rgba, profile.width(), profile.height())
    width, height = frame.get_int("width"), frame.get_int("height")
    if (width, height) != (1920, 1080) or len(image) != 1920 * 1080 * 4:
        raise SystemExit(f"unexpected frame {width}x{height} ({len(image)} bytes)")
    # #336699 at brightness 0.5 should be darker than the source colour.
    r, g, b = image[0], image[1], image[2]
    if not (r < 0x33 and g < 0x66 and b < 0x99):
        raise SystemExit(f"brightness filter had no visible effect: rgb=({r},{g},{b})")

    if len(argv) > 1:
        tractor: Any = m.Tractor(profile)
        video: Any = m.Producer(profile, "color:#336699")
        video.set("out", 29)
        tone: Any = m.Producer(profile, "tone:")
        tone.set("out", 29)
        tractor.set_track(video, 0)
        tractor.set_track(tone, 1)
        mix: Any = m.Transition(profile, "mix")
        tractor.plant_transition(mix, 0, 1)
        consumer: Any = m.Consumer(profile, "avformat", argv[1])
        for key, value in (
            ("vcodec", "libx264"),
            ("acodec", "aac"),
            ("frequency", "48000"),
            ("channels", "2"),
            ("real_time", "-1"),
            ("terminate_on_pause", "1"),
        ):
            consumer.set(key, value)
        consumer.connect(tractor)
        consumer.run()

    print(
        json.dumps(
            {
                "version": m.mlt_version_get_string(),
                "catalog": catalog,
                "frame": f"{width}x{height} rgba brightness-filtered rgb=({r},{g},{b})",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
