# ADR-KSI-033 — Repository normalization and media-path boundaries

- Status: ACCEPTED (2026-09-04, product-owner R0-R2 normalization directive)
- Scope: `REPO-NORM-R0`, `REPO-NORM-R1`, `REPO-NORM-R2`
- Related: ADR-KSI-005, ADR-KSI-009, ADR-KSI-013, ADR-KSI-016,
  ADR-KSI-023, INV-011/012/018/040/041/042/051/052/060
- Structure authority: [`REPOSITORY_STRUCTURE.md`](../../REPOSITORY_STRUCTURE.md)
- Cleanup authority:
  [`REPOSITORY_CLEANUP_MANIFEST_R0_R2.json`](../audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json)

## Context

The repository contains a large pre-existing working set, several generations of product and UX
documents, three distinct acquisition data paths, and local non-runtime artifacts at the repository
root. A later implementation can otherwise mistake a target topology for the current product path,
an old handoff for current state, or a diagnostic Liveview path for a central video product.

R0-R2 is a repository-governance change. It does not delete runtime code, merge bounded contexts,
promote a capability, perform HIL, write to a device, or change production authority.

## Decisions

### D1 — Separate product authority, execution state, and historical evidence

- Product definition and durable decisions remain in Product Constitution, Final Decision Ledger,
  Master PRD, contracts, and ADRs in that order.
- Current execution state remains in `docs/goals/PHASE_REGISTRY.yaml` and `.ksi/goals.json` via the
  goal-ledger helper. `.ai/*`, dated handoffs, audits, and implementation plans are evidence or
  session continuity, not product authority.
- `docs/DOCUMENT_STATUS.md` records active, historical, and superseded document families and their
  replacements. An active authority document must not cite a superseded document as canonical.

### D2 — Keep Liveview, EDGE_UPLINK, and source media as different paths

`PSDK Liveview` is a local Manifold acquisition/perception input. It may support bounded capture
quality, perception, and adaptive observation. Continuous video reception by Core, Vercel, or the
Operations Console is not a core KSI Site Intelligence path. A separate explicitly approved
diagnostic or provider feature must not become a product prerequisite.

`EDGE_UPLINK` carries bounded EventBundle/EdgeBundle metadata and object references. It does not
carry Liveview frames, original photos, RTK/POS streams, orthomosaics, point clouds, or source-media
bytes. Route availability never substitutes for Mission Contract validity, organization scope, or
capability authority.

The source-media paths are:

| State | Path | Meaning |
|---|---|---|
| CURRENT | `SD/storage -> field PC -> KSI web upload` | Normal v1 original-photo ingress. |
| TARGET, gated | `MEDIA_PULL` then `MEDIA_UPLOAD` through an exact approved adapter | Optional automation after device/HIL evidence; ordinary DPK remains OFF. |
| NOT CORE | Continuous central Liveview/video reception | Not required for spatial/temporal site intelligence. |

The target adapter may replace only the ingress leg. It does not change SourceMedia sealing,
Observation Epoch temporal policy, Processing, comparison, or provenance contracts.

### D3 — Preserve the working set and normalize only non-runtime assets

The R0 fingerprint records the pre-existing `85 modified + 42 untracked porcelain entries` at HEAD
`41d9f55270581d9660664f6c23c65ab0d7af0a4a`. Those paths remain owned by the pre-existing user work,
except for explicitly listed additive normalization edits. Normalization must not clean, revert, or
silently absorb that work.

Every cleanup target is classified as `RETAIN`, `CONSOLIDATE`, `ARCHIVE`, or `REMOVE` with rationale,
references, replacement, and rollback in the cleanup manifest. Root UI captures are archived with
their hashes. Reference repositories, HIL raw evidence, customer data, credentials, model binaries,
and device artifacts are never moved or deleted by R0-R2.

### D4 — One canonical place per non-runtime asset class

- Repository structure and owners: root `REPOSITORY_STRUCTURE.md`.
- Cleanup decisions and rollback: `docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json`.
- Audit reports and durable audit assets: `docs/audit/`.
- Superseded, non-authoritative captures: `docs/archive/`.
- Executable design prototypes: `design/`; durable design constraints: `design-system/`.
- Generated prototype/build/test output: ignored under its owning module, never at repository root.
- Private field/HIL originals: existing ignored owner-private locations; no relocation in R0-R2.

### D5 — Defer runtime consolidation to R3

Similar names or overlapping concepts under `edge/`, `services/`, and `packages/` are not sufficient
evidence for deletion or merger. R0-R2 records dependency, build, test, and CI reachability only.
Any runtime removal or large module consolidation requires a separate R3 goal, adoption decision,
before/after import graph, build matrix, tests, and rollback plan.

## Invariant enforcement

- INV-011/012: transport and server status do not replace a signed local Mission Contract or cancel
  it merely because a server path is unavailable.
- INV-018/051: moving the ingress transport cannot weaken capture-window, source/derived lineage, or
  sealed-original authority.
- INV-040/041: target paths and software seams remain explicit `NOT_VERIFIED`/blocked where physical
  evidence is absent; no mock or configuration becomes product support.
- INV-042: route state, signed artifacts, activation, and model/map lineage stay separate.
- INV-052: repository cleanup does not change MissionType/SiteStatus gating.
- INV-060: media, route, and artifact scope remains organization-derived and fail-closed.

## Consequences and rollback

The repository gains a small governance validator and contract test. It validates the cleanup
manifest schema, canonical paths, root capture cleanup, related links, and superseded-authority
references. It does not inspect or mutate runtime data.

Rollback is file-scoped: reverse the documented moves, revert these documentation/validator changes,
and regenerate removed caches if desired. Do not roll back or reset the pre-existing working set.
