# CGD coverage map

This map records where the source design's requirements are carried into the standalone tasks.
Implementation evidence is not available yet; M0 must turn this map into the concrete module/fixture/evidence matrix.
Names refer to sections in the source CGD snapshot identified by `manifest.json`, not required external files.

| Source section | Standalone coverage |
| --- | --- |
| 1-2: Theory and rationale | Every brief's product context; M0 ownership and M5 conversation semantics |
| 3: Happy path and GP-01 | M0 corpus/plan; M5 integrated behavior; M6 exact embedded flow; M8 reproduction |
| 4: V1 scope/non-goals | M0 full scope; M2 complete MLT package; M4 the SAM 3.1 MLX profile; M5/M8 future boundaries |
| 5.1: Sole owners and suppliers | M0 owner/interface/readiness and real root/toolchain/command plan; M1 admission first; M2 supervisor/worker; M5 client boundary |
| 5.2: Payload and authority | M0 closed variants; M1 real storage/schema/admission; M2 derived execution; M5 lifecycle |
| 5.3: Time and coordinates | M1 algebra; M2 inclusive endpoint/lowering; M3 captions; M4 masks; M6 timing fixtures |
| 5.4: Patches and undo | M1 semantic operations and inverse/replay; M5 real chat; M6 concurrency/undo |
| 5.5: Speech | M3 complete timing/selection/correction/qualification; M5 UI; M6 exact installed-command/nonempty-test cases |
| 5.6: Subjects/extensions | M4 local Metal worker, text/visual tracking/correction, offline weights/tokenizer and durable masks; M5 UI; M6 real quality |
| 5.7: MLT/jobs/cache/resources | M0 freeze; M2 full execution contract; M4 analysis cache; M5 tools/UI; M6 native/failure cases |
| 6: I1-I12 | Embedded in M0 and M6; owners below |
| 7: Verification | All rows embedded verbatim in M6 with stable V IDs; thresholds/performance/evidence in M3/M4/M6 |
| 8: Milestones | Same nine milestones, with explicitly documented M0 bootstrap and sequential scheduling adaptation |
| 9: Operations | M0 manifests/limits; M2 containment/jobs; M3/M4 providers; M5 egress/lifecycle; M8 runbook |
| 10: Migration/rollback | M1 immutable lineage; M5 user flow; M6 cases; M8 recovery reproduction |
| 11-12: Risks/decisions | M0 plan; M2 metadata/native caveats; M3 precision; M4 no parity/speed presumption; M6 claim limits |
| 13: Future work | M0/M5/M8 explicitly defer QuickTime/external chat, high-level multicam/stabilization, templates/interchange |
| 14: Permissions | Every brief; M0 manifest grants; M2 effect authority; M7 human approval; M8 separate publication |
| Required artifacts | M0 implementation plan; M1-M5 source changes/reports; M6 verification bundle; M7 decision; M8 delivery record |

## Invariant ownership

| Invariant | Main implementation milestones | Final evidence |
| --- | --- | --- |
| I1: Immutable originals | M1, M2 | M6 source replacement/mutation/publication cases |
| I2: One durable transition boundary | M1, M2, M5 | M6 persistence/authority/crash cases |
| I3: Replay/concurrency | M1, M5 | M6 replay/concurrent/stale cases |
| I4: One time/coordinate mapping | M1, M2, M3, M4 | M6 timing/rotation/retiming cases |
| I5: Explicit uncertainty/coverage | M3, M4, M5 | M6 precision/subject/coverage cases |
| I6: Exact output/session binding | M2, M5 | M6 stale/concurrent preview/export cases |
| I7: Selective undo | M1, M5 | M6 cut/blur/title inverse case |
| I8: Grants | M1, M2, M3, M4, M5 | M6 acquisition/egress/overwrite cases |
| I9: Fenced cancellation/recovery | M2, M5 | M6 crash/cancel/effect reconciliation cases |
| I10: Optional isolation | M0, M2, M3, M4, M5 | M6 clean-boot/unavailable cases |
| I11: Complete MLT contract | M0, M2, M5 | M6 full inventory/parameter/output coverage |
| I12: Derived native state | M1, M2, M5 | M6 graph/transport/generation cases |

## Verification case ownership

The case text and required observations are embedded in M6, which verifies every row.
The implementation owners below retain earlier focused evidence as they build.

| ID | Source case | Implementation owners |
| --- | --- | --- |
| V01 | Full golden flow with several clips, titles, captions, music and blur | M1-M5 |
| V02 | Selective undo after blur plus half-second title shift | M1, M4, M5 |
| V03 | VFR, rotated portrait, mixed rates/resolutions, B-frame reordering and nonzero stream offsets | M1-M4 |
| V04 | Insufficient transition handles, negative title start, unsupported speed/HDR input | M1, M2 |
| V05 | Repeated phrase, segment-only timing, silence, recognition error and failed inference with zero FFmpeg exit | M3 |
| V06 | Word-alignment qualification | M3 |
| V07 | SAM occlusion, similar people, exit/re-entry, shot cut and correction | M4 |
| V08 | Qualified SAM 3.1 MLX mask quality | M4 |
| V09 | Deterministic edit replay, two concurrent clients and stale chat reply | M1, M5 |
| V10 | Corrupted cache, replaced/missing source, original modified during render and incompatible project version | M1, M2, M5 |
| V11 | Metacharacters in captions/paths, network URLs and symlink races | M2, M5 |
| V12 | Crash at payload seal, head commit, render, output publish and receipt admission | M1, M2 |
| V13 | Cancel during render, concurrent export, source-alias destination and disk/GPU exhaustion | M2 |
| V14 | Clean boot without optional packages; denied download/egress; unavailable SAM 3.1 MLX backend | M0, M2-M5 |
| V15 | Real preview/export correctness | M2-M5 |
| V16 | Audio delivery | M2 |
| V17 | Offline asset setup, missing tokenizer/model, corrupt files and failed Metal initialization | M4 |
| V18 | SAM 3.1 MLX profile identity, residency and durable per-object masks | M4 |
| V19 | SAM 3.1 MLX text/visual selection, interactive correction and fresh-frame tracking | M4, M5 |
| V20 | Edits during delayed analysis, rapid blur changes and preview cancellation | M2, M4, M5 |
| V21 | Deferred export, uncached masks and preview/export agreement | M2, M4, M5 |
| V22 | Complete MLT package coverage | M0, M2, M5 |
| V23 | Parameter typo, wrong type/units, NaN, out-of-range value, unsupported animation and malicious resource/plugin reference | M1, M2, M5 |
| V24 | Chat-driven parameter/keyframe/retiming edits | M1, M2, M5 |
| V25 | Local operation without GUI editors or network | M2, M5 |
| V26 | Frame preview, seek/pause/resume and two rapid revisions | M2, M5 |
| V27 | Concurrent playback graph replacement and export | M2, M5 |
| V28 | MLT crash, stale native session and stuck shutdown | M2, M5 |
| V29 | MLT build/plugin upgrade and missing service | M0-M2, M5 |
| V30 | Upgrade/rollback/portable reimport | M1, M5 |
