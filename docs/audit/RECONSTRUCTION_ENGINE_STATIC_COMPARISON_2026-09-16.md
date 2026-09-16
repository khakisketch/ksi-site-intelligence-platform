# Reconstruction-engine static comparison (2026-09-16)

## Scope and authority

This audit records **static desk research only**, accessed 2026-09-16, with no
installation, trial, or execution of any engine. It feeds the undecided items of
[ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md)
D5 (explicit mapping below). It makes no procurement, licensing, deployment, or
compatibility decision, and it is not HIL/field acceptance. Claims below are
transcribed faithfully from the cited vendor/community docs; nothing is added or
softened.

Rank: below the frozen authorities (`PRODUCT_CONSTITUTION`, `FINAL_DECISION_LEDGER`,
`MASTER_PRD`, `DOMAIN_INVARIANTS`), below ADR-KSI-036 and
`docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`, and below the release
plan `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md` and the
quantitative specification
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
(implementation history); this evidence decides nothing.

## Evidence tables (protocol §3 template)

One row per fact class, per `docs/product/ENGINE_COMPARISON_PROTOCOL.md` §3: fact +
source (title + publisher) + doc version + UTC access date + research status
(`CONFIRMED` / `NOT_DOCUMENTED` / `AWAITING-LICENSE`). Vendor pages carry no
published version, so doc version is `UNDATED_PAGE` per the protocol rules. Trial and
commercial facts are kept in separate rows per protocol §6. No trial was installed or
executed; the trial rows are documentation labels only.

### DJI Terra (research label T-local; vendor-cloud loci not researched)

| Axis (§2) | Fact (≤ 2 sentences) | Source (title + publisher) | Doc version | Access date (UTC) | Research status |
|---|---|---|---|---|---|
| 1 license model | Online vs offline license; CodeMeter/Wibu, hardware-locked; unbind limits 1-device 1×/yr and 3-device 2×/yr. | Activation-and-binding guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | AWAITING-LICENSE |
| 1 offline activation | Offline license exists as a license type; v4.0+ online license invalid after 3 days offline. | Activation-and-binding guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | AWAITING-LICENSE |
| 1 trial limits | Trial 1 month, ≤500 photos, ≤8 GB LiDAR, 1 computer. | Software-trial guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | AWAITING-LICENSE |
| 2 LAS/LAZ export | LAS/LAZ/PLY/PCD point-cloud export documented. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 GeoTIFF DSM/DTM export | GeoTIFF ortho + DSM/DEM export documented. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 ortho export | GeoTIFF orthophoto export documented (see DSM/DTM row). | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 mesh export | Mesh OBJ/PLY/OSGB/B3DM/S3MB/I3S documented. B3DM vs 3D Tiles terminology must not be equated without a `tileset.json` check. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 3D Tiles export | Gaussian 3D Tiles documented. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 CRS handling | CRS known/arbitrary/import PRJ; POS via XMP (RTK 0.03/0.06 m) or TXT/CSV with explicit POS CRS + offset; GCP control vs check. | GCP guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 vertical handling | Vertical CRS explicit; Default = ellipsoidal (misinterpretation risk for absolute claims). Geoid list unpublished. | GCP guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 4 parameter export | Templates documented, but no parameter-file schema, CLI, or digest documented. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |
| 5 execution loci | Local Windows + NVIDIA documented. | Cluster guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 5 data residency | No data-residency statement found in primary docs. | — (primary Terra docs surveyed) | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |
| 6 automation/CLI | GUI-only; no CLI documented, so no documented headless-batch path. | Output-view guide, DJI Terra docs (terra.dji.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 7 cost inputs | Public prices unverified. | — (pricing not published in surveyed docs) | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |

### Pix4D — Mapper / Matic / Engine SDK / cloud (research label P)

| Axis (§2) | Fact (≤ 2 sentences) | Source (title + publisher) | Doc version | Access date (UTC) | Research status |
|---|---|---|---|---|---|
| 1 license model | Mapper recurrent subscription floating license (1 device at a time); Matic offline requires a dedicated Sales license, hardware-locked `.lic` (OTC version-locked; subscription 3/5-yr with in-term upgrades). | Offline-license guide for Pix4Dmatic, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | AWAITING-LICENSE |
| 1 trial limits | Trial 15-day, 1/org + 1/user, single seat. Trial-export contradiction unresolved: trial guide blocks export vs Matic 2.9.0 release note includes full export. | Trial-license guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | AWAITING-LICENSE |
| 2 LAS/LAZ export | LAS/LAZ/PLY/XYZ + classified LAS/LAZ documented. | Mapper outputs guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 GeoTIFF DSM/DTM export | DSM/DTM GeoTIFF documented. | Mapper outputs guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 ortho export | Ortho GeoTIFF (+KML) documented. | Mapper outputs guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 mesh export | Mesh PLY/FBX/DXF/OBJ/PDF; LOD OSGB/SLPK documented. | Mapper outputs guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 3D Tiles export | Matic adds native Cesium 3D Tiles. | Matic outputs docs, Pix4D (pix4d.com / support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 CRS handling | Image/GCP/project CRS independent; default WGS84 + EGM96 unless camera DB/XMP says otherwise. | Mapper CRS guide, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 vertical handling | Geoid selection supported. | Mapper CRS/GCP guides, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 4 parameter export | Templates + `.p4d` parameter reuse documented. | Mapper outputs/CRS guides, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 5 execution loci | Local by default; cloud optional (org-level cluster default US; existing projects do not migrate). | Process-in-Pix4Dcloud and clusters/storage guides, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 5 data residency | Sub-processors include AWS us-east-1 etc.; DPA published. | Sub-processors PDF 2026-02-20; DPA, Pix4D (pix4d.com) | 2026-02-20 (PDF) | 2026-09-16 | CONFIRMED |
| 6 automation/CLI | Mapper legacy CLI obsolete and Enterprise-gated; automation path is Engine SDK (quote-based, Python modules, in-house or cloud); Matic has no CLI. | Engine SDK docs (pix4d.com); Mapper guides, Pix4D support (support.pix4d.com) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 7 cost inputs | Matic full tier matrix and Engine SDK pricing unverified. | Pricing pages, Pix4D (pix4d.com/pricing) | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |

### ODM / WebODM (open-source reference; no license gate on documentation)

| Axis (§2) | Fact (≤ 2 sentences) | Source (title + publisher) | Doc version | Access date (UTC) | Research status |
|---|---|---|---|---|---|
| 1 license model | ODM AGPL-3.0, CLI + Docker, no activation. | ODM repository (github.com/OpenDroneMap/ODM) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 1 trial limits | Not applicable (no trial-gated use). | — | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |
| 2 LAS/LAZ export | Cloud PLY/LAZ/CSV (+optional LAS/COPC/EPT) documented. | Outputs docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 GeoTIFF DSM/DTM export | `--dsm`/`--dtm` GeoTIFF documented. | Arguments/outputs docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 ortho export | Ortho GeoTIFF documented. | Outputs docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 mesh export | Mesh OBJ/GLB documented; OSGB/I3S not documented. | Outputs docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 2 3D Tiles export | Opt-in `--3d-tiles` documented. | Arguments docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 CRS handling | GCP file, `--geo`, `--use-exif` documented. | Arguments docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 3 vertical handling | `--gps-z-offset` documented; NO built-in geoid picker (weakest vertical-datum metadata). | Arguments docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 4 parameter export | CLI flags documented (arguments reference). No vendor digest/signature scheme found. | Arguments docs (docs.opendronemap.org) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 5 execution loci | Local Docker/CLI documented; Lightning cloud optional, paid. | ODM docs; Lightning pricing (webodm.net) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |
| 5 data residency | No vendor data-residency statement surveyed for local runs. | — | UNDATED_PAGE | 2026-09-16 | NOT_DOCUMENTED |
| 6 automation/CLI | Highest documented automation surface: CLI + NodeODM REST API v2.2.1 + ClusterODX. | NodeODM repository API v2.2.1 (github.com/OpenDroneMap/NodeODM) | v2.2.1 | 2026-09-16 | CONFIRMED |
| 7 cost inputs | Lightning is paid (see pricing); no further cost inputs surveyed. | Pricing (webodm.net) | UNDATED_PAGE | 2026-09-16 | CONFIRMED |

WebODM decoupling note (applies to all WebODM rows): WebODM 2026 processes with
ODX/MicMac/LGT, NOT ODM — any "WebODM result = ODM result" claim is invalid
(sources: https://www.webodm.org, https://docs.webodm.org,
https://github.com/OpenDroneMap/WebODM).

## Normalized view vs ADR-KSI-036 artifact classes

- All three plausibly produce ortho-only and DSM.
- Point cloud / DTM conditional for all (ODM weakest vertical-datum metadata;
  Terra default-ellipsoidal is a misinterpretation risk).
- Mesh optional (ODM lacks OSGB/I3S).

## Research observations (decision pending; requires a future spec per ADR-KSI-036 D5)

The following are non-normative observations only; they close nothing and every
item below requires the future detailed specification described in ADR-KSI-036 D5:

- Under an offline/air-gap mandate, Terra offline, Matic offline, or ODM local
  would be the candidates that qualify for further study (axes 1, 5).
- Under a headless batch mandate, ODM/NodeODM and Engine SDK would be the loci
  with documented paths (axis 6).
- Absolute DSM/DTM claims would point to GCP + checkpoint residuals + recorded
  CRS/vertical datum as necessary evidence (axes 3–4; INV-024).
- Under a cloud ban, a future procedure would need to address Pix4D cloud
  processing and Terra bug-report cloud rerun (axis 5).

## Mapping to ADR-KSI-036 D5 undecided items

Per protocol §5, these D5 items remain undecided; research informs but does not
close them:

- **Accepted file formats and actual producer export compatibility** ← axis 2
  (export formats) plus axis 3 (CRS/vertical metadata) rows above. Requires a
  future detailed specification with contracts, validation, compatibility policy,
  security review, tests, and acceptance evidence.
- **Semantic validation and provenance/trust verification evidence beyond byte
  identity** ← axes 3–4 (CRS/vertical handling, reproducibility/parameter export)
  rows above. Requires the same future specification track.
- **Engine/version/profile compatibility and quantitative-comparison policy** ←
  axes 4–5 (reproducibility, execution loci) rows above, constrained by INV-053.
  The only closed quantitative rule is the narrow external relative-volume V1 rule
  in `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`;
  this research adds no cross-engine mapping.

## Unknowns (unresolved)

- Pix4D trial export contradiction unresolved (trial guide blocks export vs Matic
  2.9.0 release note includes full export).
- Terra B3DM vs 3D Tiles terminology must not be equated without a `tileset.json`
  check.
- Terra public prices / Matic full tier matrix / Engine SDK pricing unverified.
- No vendor digest or signature scheme found.

## Source references (accessed 2026-09-16 UTC)

- DJI Terra docs (`terra.dji.com`): activation-and-binding, software-trial,
  output-view, GCP, and cluster pages (all UNDATED_PAGE; see per-row citations).
- `enterprise.dji.com/dji-terra/faq` (https://enterprise.dji.com/dji-terra/faq).
- Pix4D support (`support.pix4d.com`): offline-license-pix4dmatic,
  how-to-get-a-trial-license, Mapper outputs / GCP / CRS pages,
  process-in-pix4dcloud, clusters/storage pages, and sub-processors PDF (2026-02-20).
- Pix4D pricing (`pix4d.com` pricing pages, https://www.pix4d.com/pricing/).
- ODM docs (`docs.opendronemap.org`, https://docs.opendronemap.org): outputs and
  arguments pages.
- ODM source, AGPL-3.0 (https://github.com/OpenDroneMap/ODM).
- NodeODM API v2.2.1 (https://github.com/OpenDroneMap/NodeODM).
- WebODM: https://www.webodm.org, https://docs.webodm.org,
  https://github.com/OpenDroneMap/WebODM (decoupling note), https://webodm.net
  (Lightning pricing).
