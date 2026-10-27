"""Project domain: documents, operations, inverses, undo, timing, geometry, identity and
the portable snapshot schema (docs/plan, M1c/M1d; owner of "project domain").

Never touches SQLite, never spawns processes, never imports providers. It plugs into the
ledger through :class:`aidashvideo.project.domain.ProjectDomain`.
"""
