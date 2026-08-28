# Civil Processing v1 — Acceptance

- Status: PARTIAL — the implementation, full software regression, live single-epoch persistence and
  separate foreign-CRS two-acquisition engine benchmark pass; sealed product E2E in a supported Korean
  project CRS and civil field acceptance remain gated.
- Authority: ADR-KSI-030; PRODUCT_CONSTITUTION; FINAL_DECISION_LEDGER v1.0;
  MASTER_PRD v3.0; DOMAIN_INVARIANTS.
- Requirements: REQ-WRK-101, REQ-INT-101/102/103/104, REQ-SEC-101, REQ-UX-101.
- Invariants: INV-017/018/020/023/024/040/050/051/053/060.

## Scope and non-scope

The v1 product flow is design-surface cut/fill remaining volume, temporal earthwork/stockpile
change, zone progress and reports. It uses the immutable `ksi-odm-civil-v1` profile:
NodeODM 2.2.4 / ODM 3.5.6, image
`opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2`,
`dsm=true`, `dtm=true`, `pc-quality=medium`, and dynamic-object masking `OFF`.

This acceptance does not authorize flight, motor, waypoint execution, camera/gimbal control,
DPK, Pilot 2/Manifold automatic media egress, DJI capability promotion, remote deployment or
release. FIELD-0a and DJI field capability status remain separately `BLOCKED` / `NOT_VERIFIED`.

## Software acceptance matrix

| ID | Acceptance | Required evidence | Status |
|---|---|---|---|
| CP-01 | Core expands only a registered profile ID to its canonical immutable snapshot and deterministic digest. | Profile canonicalization/registry contract and replay tests; user-supplied engine/image/parameter bypass rejection. | PASS |
| CP-02 | Historical ProcessingJob records replay as `LEGACY_UNMANAGED` without inferred profile values and cannot seed a new quantified comparison. | Legacy journal fixture/replay and preflight rejection tests. | PASS |
| CP-03 | NodeODM runtime is the exact pinned OCI image and reports the expected NodeODM/ODM identity. | Compose inspection plus `/info` identity integration test. | PASS |
| CP-04 | v1 standard processing runs with dynamic masking off; a future masking change requires a different profile with model/preprocessing lineage. | Worker fail-closed tests and profile snapshot inspection. | PASS |
| LX-01 | GeoTIFF direct registration, existing IFC→GeoTIFF conversion and LandXML 1.0–1.2 meter TIN ingress preserve source/derived distinction. | Single/multi-surface fixtures, selector contract tests, source SHA-256 → selector → parser/normalization → GeoTIFF digest lineage. | PASS |
| LX-02 | LandXML parser rejects unsafe or ambiguous inputs before normalization. | DTD/XXE, malformed namespace, depth/size, duplicate/unknown ID, NaN/Inf, degenerate triangle, non-meter and grid-limit negative tests. | PASS |
| LX-03 | IFC and LandXML use the same deterministic 0.5m TIN rasterizer and canonical GeoTIFF rule. | Hand-checkable TIN cell/height/digest golden tests. | PASS |
| CC-01 | A shared server preflight blocks every incomplete comparison with the exact typed reason. | Contract/replay tests for `ANALYSIS_NOT_READY`, `PROCESSING_PROFILE_UNKNOWN`, `PROCESSING_PROFILE_MISMATCH`, `SOURCE_LINEAGE_GAP`, `CRS_MISMATCH`, `VERTICAL_REFERENCE_MISMATCH`, `DESIGN_SURFACE_NOT_VERIFIED`, `DESIGN_NORMALIZATION_MISMATCH`. | PASS |
| CC-02 | Temporal comparison requires equal processing profile digest; design progress also requires identical design-surface revision and normalization digest. | Same/different profile, CRS, vertical datum, source lineage and design revision fixtures. | PASS |
| CC-03 | Cut, fill, net, zone progress, nodata and uncertainty reporting are deterministic and honest. | Hand-calculated fixtures; repeated runs; no independent checkpoint yields `null` uncertainty plus reason, never survey/settlement/RMSE wording. | PASS |
| SEC-01 | The code-owned profile recipe is globally readable and immutable; every profile-bound job, source byte, design surface and report remains organization-isolated. | Cross-organization 404-equivalence tests for each tenant-owned route/store. | PASS |
| UX-01 | Existing Home/Sites/Work/Items/site-detail information architecture remains intact while the existing upload, design and comparison panels gain v1 state. | Full Vitest, ESLint, TypeScript, production build, and browser evidence at 390/768/1024/1440 for overflow, keyboard/focus and console errors. | PASS |
| FI-01 | A private Korean civil field package is accepted for later evaluation only when rights, two original-image epochs, per-epoch ground control, LandXML design lineage, CRS/vertical basis and an independent reference are exact-digest bound. | Strict manifest schema, owner-only/no-symlink auditor, typed negative tests and [`CIVIL_FIELD_DATA_INTAKE.md`](CIVIL_FIELD_DATA_INTAKE.md). The successful result is `INPUT_READY`, never field acceptance. | PASS |
| E2E-B01 | The exact profile reconstructs two lawful public acquisitions of the same real area, emits DSM/DTM/point cloud for both and finds finite overlapping DSM cells without weakening the Korean CRS gate. | Opt-in live test plus [`CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`](CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json), source/archive/artifact digests and private retained bytes. | PASS — foreign-CRS technical benchmark only; product comparison remains non-executable. |
| E2E-01 | A public small photogrammetry fixture completes sealed ingest → pinned NodeODM → DSM/DTM/point cloud → two-epoch comparison. | Reproducible job log, artifact digests, identity check and comparison result. | PARTIAL — live sealed single-epoch reconstruction and object-store digest round-trip pass; no valid public same-site second epoch in a supported Korean project CRS was available. |
| HY-01 | No raw customer imagery, LandXML, GeoTIFF, credentials or large generated artifacts are committed. | `uv lock --check`, `git diff --check`, secret/large-file/reference-import hygiene checks. | PASS |

## Executed evidence — 2026-08-28

- Python full regression: `4051 passed, 24 skipped, 3 xfailed`. The new private field-input audit
  passed `18` typed positive/negative tests and its opt-in live benchmark remained the one new skip.
  Ruff passed, and Mypy reported no issues in `424` source files.
- Dashboard: Vitest passed `58` files / `541` tests; ESLint, TypeScript `--noEmit` and the Next.js
  production build passed.
- Browser regression: Playwright passed `62` tests with `14` intentional environment/device skips.
  The civil upload, LandXML selection and blocker states passed at 390, 768, 1024 and 1440 px with
  no test-observed console error or overflow failure.
- Runtime identity: the local image RepoDigest matched the ADR pin and `/info` reported NodeODM
  `2.2.4`, ODM `3.5.6`, engine `odm`.
- Live processing: the exact pinned image reconstructed 12 public Pacifica JPEGs to DSM, DTM and
  point-cloud artifacts (`1 passed` in 181.07 s). A second run exercised Core source registration and
  sealing, profile expansion, worker execution, artifact upload to a temporary real MinIO instance,
  download and digest verification (`1 passed` in 182.57 s). All temporary containers were removed.
- Two-acquisition benchmark (2026-08-29 KST): two official USGS Madeira Beach distributions passed
  exact byte-length and ZIP CRC checks. A deterministic common-area subset of 24 preservation JPEGs
  per date ran through the exact profile in `529.02 s`; both runs emitted seven mapped artifacts,
  including DSM/DTM/point cloud, and distinct DSMs overlapped on `4,290,788` finite cells. The complete
  non-sensitive digest record is `CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`; original distributions,
  selection manifest and output archives remain owner-private outside Git. The temporary benchmark
  container was removed after its task list returned zero.
- Harness correction: the first completed baseline exposed a roughly micrometre-scale X/Y pixel-size
  difference that an overly strict square-pixel assertion rejected. The live test now uses the same
  `resolve_gsd()` geometric-mean rule as the production worker; the clean two-epoch rerun passed.
- Dataset compatibility negative: the lawful HovoPhoto40 close-range rock-face candidate reached an
  `841,293`-point dense cloud but was rejected at the 2.5D DSM meshing stage. Its vertical scene is not
  a civil terrain-profile fixture; the exact failure output is retained privately by digest rather
  than hiding the result or changing the fixed profile.
- Repository gates: `uv lock --check`, `git diff --check`, repository hygiene, secret/large-file
  checks, no-reference-runtime-import checks and the repository-hygiene contract tests passed.

The Pacifica and Madeira fixtures are real foreign-CRS processing checks, not Korean civil quantity
fixtures. The Madeira mean absolute DSM delta (`1.99291 m`) is only a finite technical overlap signal:
its preservation JPEGs use approximate EXIF GNSS and lack a common independent control/vertical/design
contract, so it is not accuracy, change, cut/fill or progress evidence. Relabelling either UTM CRS as a
supported Korean project CRS would invalidate lineage and `INV-053`; `E2E-01` therefore remains
`PARTIAL`. Existing real-byte Korean-CRS fixtures still verify deterministic two-DSM cut/fill/report
calculation and the preflight contracts verify two-job compatibility.

## Deployment and license gate

NodeODM is consumed as an unmodified AGPL-3.0 container across a REST process boundary. Customer
on-prem image delivery is **not** accepted by this software matrix until an AGPL source-offer notice
and legal review are recorded for that delivery. This is a deployment gate, not evidence that KSI
proprietary services inherit the engine's license.

## Field acceptance is separate

Software green is not civil-survey acceptance. A field acceptance entry can be marked only after all
of the following are available under the approved data-governance path:

1. an anonymized Korean LandXML design surface;
2. two original-image epochs from the same site using the accepted processing profile;
3. an independent reference volume or checkpoints sufficient to compare the reported uncertainty;
4. recorded CRS, vertical reference, source lineage and result limitations.

The owner prepares that package with [`CIVIL_FIELD_DATA_INTAKE.md`](CIVIL_FIELD_DATA_INTAKE.md) and
the `civil-field-acceptance-manifest.v1.json` contract. The read-only audit reports only
`INPUT_READY` or typed `BLOCKED` and always leaves `fieldAcceptance=NOT_EVALUATED`; processing and
independent result review are later, separate gates.

Until then, every result is labelled operational relative quantity and must not be used as a contract
settlement, survey-grade or absolute-accuracy claim.

## Rollback

Disable profile issuance, LandXML conversion or civil comparison creation independently through their
feature flags. Preserve all originals, design surfaces, jobs, artifacts and reports. Never make the
comparison preflight permissive to restore availability; read-only existing results remain available.
