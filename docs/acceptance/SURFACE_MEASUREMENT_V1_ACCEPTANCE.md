# Surface measurement v1 — Acceptance target

- Status: TARGET / SOFTWARE_PRIMITIVE_ONLY / CUSTOMER_NOT_EVALUATED — the pure line-profile
  computation, `measurement-feature.v1` / `surface-profile.v1` schemas and a local worker adapter exist
  (see Evidence). No Core route, use verdict, Console tool, API, CLI or MCP operation exists yet. Nothing here changes EXT-VAL-01..08 or P-AC-01..06.
- Authority: PRODUCT_CONSTITUTION; MASTER_PRD v3.0 (external technology adoption boundary);
  DOMAIN_INVARIANTS; `docs/superpowers/product-state.md`.
- Invariants: INV-017/018/020/023/024/040/050/051/053/060.
- Owner of the first slice: a saved **line** read on one or two registered surfaces (DSM/DTM GeoTIFF),
  then the same line on the next observation.

## Why this exists

Customers who compare observations over one site expect basic measurement tools — pick a place on the
map, read the heights along it, compare two dates, export the numbers. Agent integration does not
replace those tools; it uses the same ones. This target defines the first of them so that Console, API,
CLI and MCP return the same result with the same limits.

## Scope

- Point and line **surface profile** on one registered DSM/DTM: horizontal distance along the line
  (m, planar in the raster's projected CRS) and surface elevation (m).
- **Two-surface profile comparison**: the same line and sample positions read from two exact registered
  surfaces; difference = current − baseline.
- A saved **measurement feature** (line, later point/polygon) bound to a work area, with immutable
  geometry revisions. A new revision never rewrites an earlier result.
- Result export (CSV) and Console graph linked to a map position.

## Non-scope (separate input, acceptance and decision required)

- Volume from a line. A line has no area; cut/fill is a polygon/zone calculation (existing masked and
  single-volume paths), and cross-section area or corridor/multi-section earthwork tables need their own
  geometry and calculation contract.
- Design-surface profile or progress-to-design, grade/surface length, contours, DXF output, point cloud,
  mesh/3D, ground (DTM) extraction from a DSM.
- Any survey, settlement, progress or field-accuracy claim. A profile is the height of this grid along
  this line; it is not a measured accuracy.

## What each number means

| Value | Meaning | Never |
|---|---|---|
| distance (m) | planar distance along the polyline after projection to the raster CRS | surface length, geodesic length |
| elevation (m) | bilinear value at pixel centres of the exact registered grid | a surveyed height, an interpolated guess across NoData |
| difference (m) | current − baseline at identical sample positions, only where both are known | zero when either side is unknown |
| unknown | outside surface, within half a cell of the edge (no extrapolation), or NoData/non-finite neighbour | `0`, a neighbour value, a straight line across the gap |

## Acceptance criteria (target, not yet satisfied end to end)

| ID | Criterion | Evidence needed | Current status |
|---|---|---|---|
| SM-AC-01 | Heights and distances match analytical ground truth on synthetic surfaces; reprojection from WGS84 agrees with the projected line | local synthetic contract tests; later an independent reference (GDAL/QGIS) on the same samples | primitive: local synthetic pass |
| SM-AC-02 | Unknown stays unknown: outside, edge band, NoData sentinel, NaN, and one-sided unknown in a comparison never become a number or `0` | contract tests | primitive: local synthetic pass |
| SM-AC-03 | Reads are bounded by policy: single read window, source storage-block size, vertices, samples, line length; over-limit input is refused, never coarsened silently | contract tests; worker-level time, memory, cancellation and concurrency limits | primitive: window/block/vertex/sample/length limits pass; worker limits not implemented |
| SM-AC-04 | A request is bound to exact asset ID, submission, revision and digest; comparison runs only after the existing Core preflight (INV-053: processing profile, CRS, vertical reference, lineage) and returns typed blockers otherwise | Core route and replay tests | not implemented |
| SM-AC-05 | Saved line geometry is revisioned; editing creates a new revision, old results stay bound to the old one; the same line is reusable for the next observation with a new request and result | contract and persistence tests including restart and duplicate request | not implemented |
| SM-AC-06 | Rights and egress: no read, CSV or agent response widens the caller's current site/work-area permission or AI-egress consent; exports carry no credentials or signed URLs | permission, revocation and egress tests | not implemented |
| SM-AC-07 | Console, API, CLI and MCP return the same input revision, result ID, values and unknown reasons | cross-surface contract test | not implemented |
| SM-AC-08 | A field user completes draw → read graph → change date → export in the real browser at 390/768/1280/1440px and 200% zoom, with keyboard and touch, stale values withdrawn on input change, and no write request from selection alone | real-browser test; later unaided task test with field staff | not implemented |
| SM-AC-09 | Real customer data: the P-AC customer sample (same work area, t0/t1/t2 DSM, intended lines, CRS/vertical/quality evidence, usage rights) read with an independent reference comparison | customer-approved data and independent review | not evaluated |

## Decision: two-epoch difference gate (2026-11-17, user)

The difference between two dates' profiles is opened under the **same standard as RELATIVE_VOLUME**:
a new pair use (`PROFILE_DIFFERENCE`, no zone) that needs per-epoch independently attested evidence
for the measured DSM and a Core compatibility authority (INV-053). It is not derived from inspection
reports alone. Consequence to state plainly: the production compatibility authority port is
default-closed today, so the difference stays BLOCKED (per-date height profiles still shown) until a
mapping source and independent evidence are approved, exactly as for relative volume.

Found while scoping (no change made yet): the single-subject `HEIGHT` use is hard-wired to
`HEIGHT_PRODUCT_DEFINITION_UNRESOLVED` in `external_use_evaluator._single_reason`, so a single-surface
profile also needs that verdict opened before any Core route can serve it.

## Boundaries

A passing local synthetic test, a green software matrix or an exported CSV is not customer, field,
accuracy, settlement or deployment acceptance. Reading a surface is separate from file inspection,
suitability for a use, quantitative analysis, accuracy evaluation and human review.

## Evidence log

| Date | Evidence | Scope |
|---|---|---|
| 2026-11-16 | `packages/geo-spatial/src/ksi_geo_spatial/surface_profile.py`; `tests/contract/test_geo_spatial_surface_profile.py` (39 tests; ten injected defects — NoData as valid, edge extrapolation, out-of-surface read, nearest-neighbour sampling, inverted difference, no window limit, no block limit, missing vertices, mixed plans, ignored scale — were each detected) | pure primitive only; synthetic grids; no contract, Core, worker, UI, API, CLI or MCP |
| 2026-11-17 | `contracts/schemas/measurement-feature.v1.json`, `surface-profile.v1.json` (generated by `tools/generate_surface_profile_schemas.py --check`); `tests/contract/test_surface_profile_contracts.py` (41 tests, ten injected defects detected); `services/processing-controller/.../surface_profile_worker.py` + `tests/contract/test_surface_profile_worker.py` (8 tests; nine injected defects, including a reversed line, detected) | request/result shapes and a local adapter over an already-authorised raster path; synthetic grids only; no Core route, grant, egress or storage wiring |
| 2026-11-17 | 경계값 보정: 극소 표본 간격·극소 선·계약 상한 초과·복소수 래스터·복합 CRS(m 수직 성분만)·표본 null/사유 wire 스키마 (`test_geo_spatial_surface_profile.py` 46, `test_surface_profile_worker.py` 12, `test_surface_profile_contracts.py` 49개; 주입 결함 7개 중 6개 검출, 복합 CRS 성분 개수 방어 분기는 시험으로 도달시키지 못함) | 순수 계산·계약·로컬 어댑터만. 수직 성분은 선언 사실로 보존할 뿐 호환성 판정이 아님 |
