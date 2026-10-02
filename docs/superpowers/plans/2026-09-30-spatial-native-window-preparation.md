# Native Grid Spatial Window Preparation Implementation Plan

> **For agentic workers:** Use red/green tests for each bounded task. Do not commit, deploy, install credentials, or claim Terra compatibility from synthetic fixtures.

**Plan ID:** SDP-WINDOW-20260930  
**Goal:** Prepare a byte-verified, bounded DSM or orthophoto window from an already inspected GeoTIFF while preserving its native grid and spatial meaning.  
**Architecture:** Add an import-only raster preparation function in `packages/geo-spatial/` that a future isolated Processing worker can call. It takes a locally staged exact source, observed inspection measurements and a bbox in that observed CRS; it creates a private GeoTIFF candidate plus a typed receipt. It publishes no URL, grants no data access, and is not mounted to Core until the rights, durable job, worker identity, and delivery contract are approved.  
**Tech Stack:** rasterio/GDAL in existing pinned Python workspace, Pydantic event contracts, pytest.  
**Spec:** ADR-KSI-038 D2/D4 and PRD SDP-REQ-03/06/07; existing `external-geotiff-profile.v1` inspector and `RasterMeasurementsV1`.

## Global Constraints

- No CRS transform, resampling, unit conversion, or height adjustment in this first preparation profile. Request and source CRS digest must match exactly. Unsupported affine layouts fail explicitly.
- For the supported north-up affine `(a,0,c,0,e,f)` with `a>0,e<0`, treat the finite request rectangle as continuous coordinates. Use `floor((xmin-c)/a)` and `ceil((xmax-c)/a)` for `[colStart,colStop)`, and `floor((ymax-f)/e)` and `ceil((ymin-f)/e)` for `[rowStart,rowStop)`. Exact cell edges do not add the next cell. Reject requests outside the source outer extent; report the expanded pixel-edge output extent, which may be larger than the request.
- Only an observed, measured DSM or ORTHO from the fixed GeoTIFF profile is an admissible source. A customer declaration alone is not an inspection fact.
- Work entirely in a private path; repeat the source byte hash/size and raster metadata checks before output. Do not expose source metadata tags, internal object keys, or partial output after failure.
- Reject nonfinite/inverted/outside bounds, unsupported bands/dtype/mask, excessive input/output pixels or bytes, and cancellation. No silent clipping of requested area or fabricated NoData.
- A caller supplies a finite output-pixel and output-byte envelope from a reviewed worker policy; the primitive does not accept an arbitrary unlimited request. A wholly invalid pixel window fails; a partially masked window preserves its invalid pixels and reports valid coverage.
- The output receipt states the exact requested and actual pixel-aligned bounds, transform, CRS and vertical reference (if known), bands/dtype/NoData, output SHA-256/size, source digest, preparation profile/version, and whether accuracy was assessed (always no).
- This task is a software primitive. Customer data rights, Core permission, AI consent, presigned URL revocation, job/idempotency/fencing, retention, and actual Terra export fit remain unresolved gates of SDP-DATA-01.

## Review Focus

- Bounding box crosses one cell edge: defined half-open pixel-window rule and actual expanded bounds are exact.
- Request outside the raster or wholly NoData: explicit typed refusal, no zero-filled plausible data.
- Rotated/skewed transform, wrong CRS digest, or vertical reference mismatch: no implicit repair.
- Byte substitution between inspection and preparation: hash mismatch, no output receipt.
- Large or hostile TIFF: fixed resource budget and offline GDAL environment, no network/VRT reference.

---

### Task SDP-WIN-01: Native-grid window geometry and private candidate

**Owner:** bounded `worker` after SDP-CAT-01 review/integration; isolated worktree mapping reused.  
**Dependencies:** fixed inspector outcome contract and existing synthetic GeoTIFF fixture helpers.  
**Files:** new focused `packages/geo-spatial/src/ksi_geo_spatial/external_native_window.py`; `packages/event-contracts/src/ksi_event_contracts/` only if a receipt model is needed across worker/Core; focused `tests/contract/test_external_native_window.py`; package README only if needed. No Core route or new service in this task.  
**Acceptance:** exact native-pixel DSM/ORTHO window output, typed failure, bounded resource use, source and output hash, crop transform/footprint and mask/NoData checks, cancellation cleanup. Positive/negative synthetic fixtures and one existing real ODM negative sample are separate evidence classes.  
**Validation:** failing edge/window/CRS/hash/resource/NoData tests first, then focused tests and related inspector/sanitizer regression. Independent review is required for untrusted raster processing before integration.

### Task SDP-WIN-02: Durable authorized preparation and delivery

**Owner:** separate Core/Processing task after WIN-01 and customer rights/profile contract.  
**Dependencies:** SDP-CAT-01, source profile from actual authorized DSM/ORTHO export, delivery-rights/AI consent, worker identity and finite job envelope.  
**Acceptance:** Core-issued durable request/lease/receipt, exact source and policy binding, retry/fencing/cancel/replay, permission checked at byte access, external API consumer and one MCP client, no completed claim without customer sample.  
**Stop:** do not implement a new data-egress route by borrowing display-only presigned URLs or Analysis worker credentials.

## Release boundary

`SDP-WIN-01` can prove deterministic local preparation only. It is not a customer data-access service and does not close SDP-04/05/08, EXT-VAL, or the first pilot's real two-cycle acceptance.

## Local software checkpoint — 2026-09-30

`SDP-WIN-01` is integrated as an import-only primitive in `packages/geo-spatial/`.
The two new files, baseline hashes, three review freezes, exact reviewed patch,
integration hashes, and validation record are in
`.opencode/artifacts/spatial-native-window-20260930/`. Independent review
returned **PASS** on the third freeze after exact fractional pixel-edge,
offline GDAL, and private cleanup corrections. The reviewer independently
checked 660 generated boundary cases.

On the integrated main worktree, the focused window and existing GeoTIFF
inspector/sanitizer suites passed **114 tests** (35 existing
`NotGeoreferencedWarning`s); Ruff check/format and scoped diff check passed.
The worker used synthetic GeoTIFFs. No customer Terra export, rights, Core
delivery authority, MCP consumer, deployed runtime, remote CI, or field
acceptance was verified. `SDP-WIN-02` remains dependent on the sample,
customer use rights, and an independently reviewed durable delivery contract.
