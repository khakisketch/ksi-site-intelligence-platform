# External GeoTIFF profile v1

> **Status:** Lead-adopted technical profile (2026-09-08), following
> independent review and the Human authorization to continue product work on
> 2026-09-08. Parser/runtime implementation: **NOT_IMPLEMENTED**. Producer
> compatibility, accuracy, host enforcement, deployment and release acceptance:
> **NOT_VERIFIED**.
>
> **Scope:** This supplements the external-artifact-validation design and the
> Docker-sandbox amendment.  It freezes the positive GeoTIFF grammar that their
> Task 3/4 implementation needs.  It does not alter an API, JSON Schema, report
> wire shape, product invariant, or customer-data route.

## Authority and boundary

The first-release direction is [ADR-KSI-036](../../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md): customer-produced ortho/DSM files remain derived external evidence.  The inspection design defines the use gates and report-first rule; see [external artifact validation](2026-09-07-external-artifact-validation-design.md).  The [sandbox amendment](2026-09-07-external-inspector-docker-sandbox-amendment.md) still owns sealed-byte staging, the launcher-only UDS boundary, a dedicated rootless daemon, cleanup, and real host enforcement.

Requirements are REQ-INT-101 through REQ-INT-104, REQ-SEC-101, and REQ-OPS-102.  This profile enforces INV-024 by producing no accuracy assertion or RMSE, INV-051 by retaining the result as derived observed evidence, INV-053 by making structural measurement distinct from eligibility, and INV-060 by accepting only the server-derived sealed artifact capability and returning records under Core's organization scope.

`services/processing-controller/` owns byte measurement and deterministic display derivation.  Core owns identity, policy, tenancy, journals, fence/lease and all DISPLAY/HEIGHT/RELATIVE_VOLUME decisions.  `packages/event-contracts/` remains the existing immutable boundary; its current `RasterMeasurementsV1` fields are sufficient.  No new client-selected profile, URL, filesystem path, Docker option, environment variable, grid, limit, or coordinate input is introduced.

## Immutable identity

The implementation must materialize this profile as one canonical, closed
`external-geotiff-profile.v1` JSON body.  Its SHA-256 must equal **both** the
policy `grammarDigest` and the signed execution-manifest `backendProfileDigest`.
A body with an omitted, additional, changed, or positionally reordered array
rule is a different grammar and must fail launcher admission.  `parserBuildDigest`/`inspectorBuildDigest`
remain the exact signed manifest body digest already defined by
`InspectorExecutionManifestV1`; they bind the image, source, SBOM, parser
protocol, backend profile, security profile and hard ceilings.  A worker runs
only when all three bindings agree with the current Core policy and the sealed
request.

The grammar body is serialized only with repository
`ksi_domain.canonical_json_bytes`: UTF-8, sorted object keys, minimal
separators, `ensure_ascii=False`, and finite JSON (`allow_nan=False`).  Key
reordering therefore has the same digest; array order is positional and any
array reordering changes the digest.  No other serializer, string normalization,
implicit default, unknown key, null, non-finite number, or float spelling is
accepted.  `parserBuildDigest` contains this binding through the signed manifest;
it is not required to equal the grammar/profile digest.

The closed root object has exactly these members (shown in logical order; the
serializer sorts keys):

```json
{
  "contractVersion": "external-geotiff-profile.v1",
  "canonicalization": "ksi-domain-canonical-json-bytes.v1",
  "artifactKinds": ["ORTHO", "DSM"],
  "tiff": {"containers": ["CLASSIC_TIFF", "BIGTIFF"], "byteOrders": ["II", "MM"], "fullResolutionImages": 1, "externalSidecars": false},
  "raster": {"imageCompression": ["NONE", "LZW", "DEFLATE", "ZSTD", "JPEG"], "integerPredictors": [1, 2], "floatPredictors": [1, 3], "interleave": "PIXEL"},
  "ortho": {"models": ["UINT8_RGB3", "UINT8_RGBA4_BINARY_ALPHA"], "nodata": "FORBIDDEN", "internalMask": "OPTIONAL_1BIT"},
  "dsm": {"models": ["FLOAT32_1", "FLOAT64_1"], "scale": 1, "offset": 0, "nodata": ["NONE", "FINITE", "NAN", "MASK"]},
  "scan": {"base": "REQUIRED", "mask": "WHEN_PRESENT", "overviews": "ALL", "unmaskedSamples": "FINITE"},
  "georeference": {"horizontal": ["EPSG_2D_GEOGRAPHIC", "EPSG_2D_PROJECTED"], "dsmHorizontal": "EPSG_2D_PROJECTED_METRE", "vertical": "OPTIONAL_COMPOUND_EPSG_1D_METRE"},
  "cog": {"layout": "IFDS_BEFORE_DATA", "blockLeader": "SIZE_AS_UINT4", "blockTrailer": "LAST_4_BYTES_REPEATED", "maskedBlockOrder": "MASK_INTERLEAVED_WITH_IMAGERY"},
  "sanitizer": {"fullResolutionResampling": "NONE", "outputBands": "RGB3", "outputMask": "BINARY_INTERNAL_MASK"}
}
```

Each nested object is closed.  The compact JSON values are semantic identifiers
for the fixed v1 prose ruleset below; they are not a second extensible rule
channel.  Any semantic change to that prose ruleset requires a new profile
version and new body identity, rather than a mutable expansion of this body.
Finite resource values are supplied separately by the policy-bound
`ResourceEnvelopeV1` and the manifest hard ceilings.  Runtime package, GDAL and
PROJ identities belong to the signed execution-manifest build body, not this
grammar body.  This document intentionally supplies no production numeric
capacity, accuracy, producer, or vendor-compatibility claim.

## Accepted bytes and layout

The input is one sealed regular-file byte stream.  Header/magic inspection is a
launcher hint only; TIFF structure and raster decoding execute only in the
pinned parser container.  The parser accepts classic TIFF and BigTIFF with
either byte order, using GDAL only after its own bounded structural validation.

One artifact contains exactly one full-resolution logical image.  It may contain
reduced-resolution internal overview IFDs and one internal per-dataset mask.
The parser rejects extra pages, subdatasets, multiple independent full-resolution
images, external `.ovr`, `.msk`, `.aux.xml` or any sidecar, VRT/VSI source,
GCP/RPC/geolocation-array model, sparse blocks with zero offsets, malformed
offset/count pairs, overlapping allocated blocks, and all metadata-directed file
or network access.  It never follows an artifact name, archive, symlink,
hardlink, URL, embedded executable reference, plugin, PAM file, or PROJ network
grid.

The base image and every overview must use the same sample model allowed for its
artifact kind.  This closed codec/predictor matrix applies to every image level:

| Sample model | Compression | Predictor |
|---|---|---|
| RGB/RGBA uint8 | NONE | 1 only |
| RGB/RGBA uint8 | LZW, DEFLATE, ZSTD | 1 or 2 only |
| RGB uint8 only | JPEG | 1 only |
| DSM Float32/Float64 | NONE | 1 only |
| DSM Float32/Float64 | LZW, DEFLATE, ZSTD | 1 or 3 only |

JPEG includes only an on-disk YCbCr representation that the pinned backend
exposes as three-band RGB; JPEG RGBA and DSM are rejected.  The internal mask is
exactly one-bit, uses NONE/LZW/DEFLATE/ZSTD with predictor 1 only, and has the
same base/overview chain as its image.  Multi-band image data is pixel
interleaved.  Any TIFF feature or codec/predictor combination not listed here is
rejected rather than delegated to a permissive GDAL default.

### ORTHO v1

An ORTHO is either uint8 RGB (three bands) or uint8 RGBA (four bands).  Palette,
CMYK, grayscale, complex, alpha-less fourth-band, and nodata-tag models are
rejected.  An exposed YCbCr model is accepted only for the JPEG RGB case above;
all other YCbCr forms are rejected.  RGBA alpha and an internal dataset mask are
mutually exclusive.  RGBA alpha must be lossless binary 0 or 255.  Valid color
pixels are those whose alpha is 255 or whose mask is valid, as applicable; the
profile records the corresponding existing `MASK` or `NONE` nodata
representation.  Alpha/mask bytes are scanned as input and are not treated as a
client claim about coverage.

### DSM v1

A DSM is one Float32 or Float64 band with scale 1 and offset 0.  It has no alpha.
Exactly one of these models applies: no nodata; a finite nodata value; NaN
nodata; or one internal per-dataset mask.  A file that combines nodata and mask
is rejected because the present report contract cannot express both meanings
without ambiguity.  Masked samples may be non-finite.  Every required,
unmasked, non-nodata sample must be finite; otherwise the artifact is rejected
with `UNMASKED_NONFINITE_SAMPLE`.  A structurally measured DSM with no resolved
vertical reference remains a `MEASURED` artifact fact but Core must block HEIGHT
and RELATIVE_VOLUME with the existing vertical/eligibility reason path.

### Full scan and resource accounting

Before a positive `MEASURED` report, the parser counts all IFDs, entries,
allocated blocks, decompressed bytes and sample bytes against the injected
envelope.  It reads every base-image block, every mask block, and every overview
block.  It checks each decoded sample required by the applicable model, computes
valid-pixel count only from those bytes, and verifies dimensions/bands/types at
each IFD.  Overviews are internal only, must be strictly smaller in both
dimensions than the preceding level, and must keep the base image/mask model and
codec matrix.  A cap, truncation, decode, checksum or metadata fault makes the
affected artifact `REJECTED`, never a partial positive result.  Cancellation or
lease/fence loss is a request-level incomplete terminal condition: the worker
submits no partial inspection report and does not invent an `INCOMPLETE`
per-artifact outcome outside the existing contract.

## Georeference and CRS

The artifact must carry one internal, finite, non-singular affine transform.  A
default identity transform is rejected.  Conflicting affine/georeference sources
are rejected.  The parser resolves offline only an exact two-dimensional
geographic or projected EPSG horizontal CRS; local engineering, custom, unknown,
geocentric, three-dimensional, and ambiguous definitions are rejected.  An
ORTHO may use either accepted form.  A DSM **must** have projected metre axes; a
geographic DSM is rejected.

Rasterio and Pyproj each resolve the sealed bytes with network disabled.  They
must agree on one horizontal EPSG `code` by identity and equivalence.  Rasterio's
resolved horizontal CRS must yield that code, and Pyproj must resolve
`pyproj.CRS.from_epsg(code)` as equivalent.  The observed identifier is exactly
`EPSG:{code}`.  The observed horizontal WKT is exactly
`pyproj.CRS.from_epsg(code).to_wkt(version="WKT2_2019", pretty=False,
output_axis_rule=True)`.  Its digest is `sha256:` plus SHA-256 of that UTF-8 WKT
with no trailing newline.  The signed execution-manifest build body, not this
grammar body, binds the Rasterio/Pyproj package versions and each reported
GDAL/PROJ version.  Disagreement, unavailable data, or a version/profile mismatch
is rejected.  These values populate the existing observed CRS identifier, WKT,
and digest fields in `RasterMeasurementsV1`; no wire field is added.

For affine `Affine(a,b,c,d,e,f)`, each pixel-edge point is exactly
`x = a * col + b * row + c` and `y = d * col + e * row + f`.  The five corners
are exactly `(0,0)`, `(width,0)`, `(width,height)`, `(0,height)`, `(0,0)` in that
order.  Every coordinate must be finite binary64, formatted with `.17g`, with
any signed zero rendered as `0`.  The footprint WKT is exactly
the output of:

```python
def fmt(value: float) -> str:
    return "0" if value == 0.0 else format(value, ".17g")

"POLYGON ((" + ", ".join(f"{fmt(x)} {fmt(y)}" for x, y in corners) + "))"
```

There is no orientation normalization or ring rotation.  Its digest is
`sha256:` plus SHA-256 of that UTF-8 text with no trailing newline.  Any
non-finite point, different text, or digest mismatch rejects the artifact.

The parser reports a vertical reference only when the bytes contain exactly one
resolvable compound-CRS EPSG one-dimensional vertical component with metre axes.
It does not download grids, transform coordinates, infer a datum, reconcile a
customer declaration, or turn this observation into accuracy evidence.  No
vertical component is recorded as `observedVerticalReference: null` on an
otherwise measured DSM; it is not a parser rejection reason.  Core blocks the
dependent HEIGHT and RELATIVE_VOLUME decisions from that observed absence.  This
embedded vertical observation is retained separately from the normalized
horizontal EPSG/WKT/digest calculation.

## COG classification

COG is an optional stricter classification, never a reason to accept bytes that
fail the base GeoTIFF profile.  A valid base profile becomes
`COG_PROFILE_V1` only when it also has square tiles divisible by 16 and no
larger than 1024 pixels.  The logical chain begins at the base image; each
overview has `width = ceil(previous_width / f)` and
`height = ceil(previous_height / f)` for one same integer `f` from 2 through 10,
and is strictly smaller in both dimensions.  The final overview is no larger
than one tile on either axis.  The logical chain remains strictly decreasing in logical
overview dimensions.
Physical directory/IFD order is base image (and its mask if present), then overview
levels from largest to smallest, and each overview carries the corresponding mask if
present.  All IFD/index data must precede imagery.  The IMAGE PAYLOAD BLOCK order is
smallest overview to larger overview to base image, with offsets ascending row-major
within each level; each mask block follows its corresponding image block and precedes
the next image block.  It requires `LAYOUT=IFDS_BEFORE_DATA`,
`BLOCK_LEADER=SIZE_AS_UINT4`, `BLOCK_TRAILER=LAST_4_BYTES_REPEATED`,
`BLOCK_ORDER=ROW_MAJOR`, `KNOWN_INCOMPATIBLE_EDITION=NO`, and, when masked,
`MASK_INTERLEAVED_WITH_IMAGERY=YES`.

The installed GDAL COG validator is an auxiliary implementation check only; the
parser's explicit rules and reopen/full-scan establish this profile's local
classification.  It does not claim OGC COG certification or producer
compatibility.  A valid non-COG GeoTIFF is classified `GEOTIFF_STRIPED_V1` or
`GEOTIFF_TILED_V1` according to its base layout.

## Deterministic sanitized display artifact

Only a measured ORTHO may have a sanitizer attempt.  The sanitizer creates an
RGB3 COG derivative with a one-bit binary internal mask even where every input
pixel is valid.  It removes RGBA alpha after turning binary alpha into that mask,
zeroes RGB at invalid pixels, and preserves every valid RGB sample exactly.  It
preserves CRS, affine transform, footprint and validity semantics.  It performs
no full-resolution reprojection, crop, stretch, color conversion, resampling,
coordinate transformation, or data repair.  It rebuilds overviews only: average
for color and nearest for the mask.  It keeps only required GeoKeys and validity
information and strips producer metadata.

The fixed derivation is pixel-interleaved, 512-pixel tiled, DEFLATE compressed,
standard predictor, single-threaded, `SPARSE_OK=FALSE`, `BIGTIFF=IF_SAFER`,
`GEOTIFF_VERSION=1.1`, `STATISTICS=NO`, and fresh internal overviews
(`OVERVIEWS=IGNORE_EXISTING`, average for color and nearest for the exact binary
mask).  The result is reopened in the same parser profile and fully scanned.  It
must compare source and result for CRS identifier/WKT/digest, affine transform,
five-point footprint WKT/digest, base dimensions, RGB3 values at valid pixels,
binary validity mask, overview chain, fixed COG facts and output SHA-256 before a
receipt is emitted.  Failure emits no display artifact or receipt.  Core still
decides whether a valid receipt is eligible for DISPLAY.

## Security and failure semantics

The launcher creates and verifies one exclusive private regular staging file,
rechecks byte count/digest, binds it read-only at the fixed container path, and
accepts bounded framed output only.  The parser has no Docker socket, customer
directory, workspace, credential, writable root, network, capabilities, plugin
path, PAM state, remote VSI or unapproved grid.  Exact attempts and containers
are durably tracked; timeout or recovery cleans only the recorded exact ID after
owner/name/profile verification.  Any uncertain ownership, clean-up, runtime
controller, UID mapping, signature, envelope or parser state closes admission.

Typed rejection must distinguish at least unsupported grammar, structural
corruption, resource exhaustion, unsafe external reference, ambiguous
georeference/CRS, unmasked non-finite sample, sandbox unavailability, and
sanitizer verification failure.  Request-level cancellation is incomplete and
distinct from per-artifact rejection; vertical-reference absence remains a
measured nullable observation.  Report text, logs, events and UI contain typed
codes and bounded safe facts, never untrusted metadata or byte content.

## Acceptance boundaries and rollback

The implementation may use the [GDAL GeoTIFF driver](https://gdal.org/en/stable/drivers/raster/gtiff.html),
[GDAL COG driver](https://gdal.org/en/stable/drivers/raster/cog.html),
[OGC COG standard](https://docs.ogc.org/is/21-026/21-026.html), and
[OGC GeoTIFF standard](https://docs.ogc.org/is/19-008r4/19-008r4.html) as
implementation references.  The currently observed GDAL 3.12.4 cannot supply
the later 3.13 `gdal driver cog validate` feature; it must not be used as an
acceptance substitute.

Synthetic byte tests can show only local parser behavior.  They do not prove
customer-export compatibility, license rights, accuracy, external readiness,
HEIGHT/RELATIVE_VOLUME eligibility, signed supply-chain trust, daemon isolation,
resource enforcement, deployment, HIL, field acceptance or release.  Host-backed
checks remain required under the sandbox amendment.  Rollback is admission-off:
retain immutable sealed submissions, reports, decisions and receipts; stop new
inspection/sanitizer starts; perform only exact registered cleanup; never parse
unsandboxed or widen a runtime privilege.
