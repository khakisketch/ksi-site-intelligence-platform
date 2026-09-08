# TerrainPlanningSourceAdoptionRecord — 2026-09-08

**Status:** `PARTIAL` / `NOT_READY_FOR_ACCEPTANCE`

**Decision requested:** None. This is WP-R evidence preparation for a future
Human source decision, not a source adoption, procurement, account request,
license acceptance, or runtime input contract.

## Scope and authority

| Field | Record |
|---|---|
| Requirement IDs | ADR-KSI-035 D2/D5; TAP-02, TAP-03, TAP-04; INV-020, INV-024, INV-060 |
| Owner | Product Authority decides; this record is documentation-only evidence preparation |
| Candidate context | Korean construction sites are a candidate context; no customer AOI is assumed |
| Contracts changed | None. `PlanningInputSnapshot` remains future work after WP-R acceptance |
| Runtime/HIL assumption | None. ADR-035 is an approved design baseline, not Pilot/device/HIL evidence |
| Data/license action | No data acquired, account created, terms accepted, or supplier selected |
| Rollback | Do not accept or consume this record; no source, schema, or customer evidence changes |

The planning design requires source identity, terms decision, version/freshness,
coverage, CRS, vertical reference, uncertainty, and failure behavior before a
terrain input can support a candidate plan. Missing facts must remain a typed
gap rather than an inferred elevation or safety result. This record preserves
that boundary and does not create a numerical threshold, camera default, or
commercial conclusion.

## Candidate evidence ledger

| Candidate | Primary source evidence | What is established | What remains unresolved |
|---|---|---|---|
| Copernicus DEM collection | [Copernicus collection](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) (accessed 2026-09-08) | The collection describes a DSM; the visible collection history includes `release2024_1` (July 2024). GLO30/GLO90 are documented public collection candidates. | Exact tile/version, AOI coverage, delivered metadata, access entitlement, lawful sample, and KSI suitability. A collection page is not a tile receipt. |
| Copernicus DEM Process API | [DEM API documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM.html) (accessed 2026-09-08) | `COPERNICUS_30` access and its fallback behavior are documented separately from raw collection access; an unspecified instance can default to 90 m. API interpolation/output pixel size does not establish source resolution. The documented data mask is an output-pixel fact. | Actual endpoint authorization, request/response behavior, selected instance, fallback occurrence, sample provenance, and no-data behavior. |
| Copernicus product metadata / candidate terms | [Product Handbook, issue 5.0](https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf) (published 2022-11-29) and [GLO30 license artifact](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf) (accessed 2026-09-08) | The handbook describes DGED metadata as geographic WGS 84 with EGM2008 vertical metadata and records `RasterPixelIsPoint`; the license artifact has an acceptance condition and attribution-related terms. | Tile-specific product/quality metadata, GLO30 no-data behavior, lawful use decision, attribution implementation, and any legal conclusion. Handbook publication date must not be inferred from its URL folder. |
| NGII public DEM catalogue | [Data.go.kr file catalogue](https://www.data.go.kr/catalog/15059920/fileData.json) and [catalogue detail](https://www.data.go.kr/tcs/dss/selectFileDataDetailView.do?publicDataPk=15059920) (created 2024-09-24; modified 2025-06-17; accessed 2026-09-08) | The public listing identifies an IMG product and indicates portal login plus large-file transfer software. | Exact layer/tile edition, CRS, vertical datum, resolution, coverage, current delivery terms, access entitlement, and lawful sample. A historical 5 m reference is not evidence that this catalogue supplies a 5 m usable layer. |
| VWorld WebGL 3D | [VWorld WebGL 3D catalogue](https://www.data.go.kr/data/3073144/openapi.do) (modified 2025-07-09; accessed 2026-09-08) | The catalogue describes a nationwide JavaScript/WebGL/Cesium visualization/API surface and an API-key requirement. | Raw geometry/height export, layer identity/version, caching or redistribution terms, obstacle completeness/freshness, key eligibility, and a usable terrain input. Visualization is not raw geometry proof. |

The candidate sources are alternatives under investigation. None has the
`ADOPTED`, `REJECTED`, or `APPROVED_FOR_RUNTIME` status.

## Spatial, vertical, and no-data reconciliation

| Question | Current evidence | Status / required next evidence |
|---|---|---|
| Source CRS and pixel interpretation | The Copernicus handbook reports geographic DGED metadata and `RasterPixelIsPoint`. | `NOT_RUN`: obtain a lawful representative tile and inspect its actual metadata. Pixel interpretation is not a rejection rule in the current external-artifact profile. |
| Vertical reference | The handbook describes EGM2008 metadata; API documentation distinguishes orthometric/ellipsoidal output behavior. | `NOT_RUN`: record source tile and returned-output vertical metadata, any conversion path, and uncertainty. No conversion is selected. |
| No-data | The handbook's cited no-data table has a stated product scope; API documentation notes source-absent output can be zero. | `NOT_RUN`: decode a representative sample and distinguish source absence, no-data, mask, and valid zero. No blanket GLO30 no-data value is assumed. |
| Current inspector compatibility | The local external GeoTIFF profile requires projected metre horizontal axes for DSM. | `PARTIAL`: a geographic terrain candidate cannot be treated as accepted by that DSM profile. This is a future terrain-adapter contract question, not permission to widen the inspector. |
| Freshness, coverage, uncertainty | Catalogue and collection pages provide only candidate context. | `NOT_RUN`: AOI-specific coverage, tile/version/acquisition lineage, uncertainty, and applicable constraints need recorded sample evidence. |

## Required closure evidence

The following items must be recorded before this can become an approval-ready
source decision:

1. Human-selected candidate and an authorized access path, including the
   explicit terms/attribution decision by the responsible owner.
2. A lawful representative sample with immutable retrieval record, digest,
   tile/layer version, access date, and reproducible decoder command.
3. Decoded CRS, vertical reference, pixel interpretation, no-data/mask rules,
   resolution, coverage, freshness, uncertainty, and AOI/transit applicability.
4. Explicit rejection or limitation records for each non-selected candidate.
5. A new versioned planning-input source identity if a later supplier/layer
   switch occurs.

Until then the authoritative state is `SAMPLE_NOT_RUN`,
`TERMS_NOT_ACCEPTED`, `OWNER_DECISION_REQUIRED`, and
`NOT_READY_FOR_ACCEPTANCE`.

## Decision questions for the Product Authority

1. Which candidate, if any, may proceed to a lawful sample and terms review?
2. Who may accept terms and record attribution/retention obligations?
3. What representative AOI and non-customer test context may be used once
   access is authorized?
4. Which source limitations make a terrain input a typed planning gap rather
   than a usable candidate?

No answer is inferred by this record.
