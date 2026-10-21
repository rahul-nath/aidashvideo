"""Capability catalog: host/toolchain profile, supplier readiness and model assets.

Owner of the "capability catalog" responsibility (docs/plan/implementation-plan.md).
Nothing here downloads or installs anything; probes observe the host and report a
typed :class:`~aidashvideo.catalog.status.ComponentStatus` whose readiness is one of
``Verified | Missing | Conflicting``. Every module imports its tools lazily so that
``import aidashvideo`` stays stdlib-free and provider-free (I10).
"""
