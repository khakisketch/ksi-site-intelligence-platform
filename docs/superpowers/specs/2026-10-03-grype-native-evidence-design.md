# Native Grype runtime scanner evidence design

Status: design direction approved in chat; written-spec review pending.
Date: 2026-10-03

## Intent and selected approach

The Human selected **Grype original JSON direct support**, not a producer/envelope adapter,
and approved the detailed consumption boundary. A genuine raw report must be usable in the
existing runtime release gate without adding fabricated `scanner` fields. Original bytes stay
unchanged. Accepting a report format is not accepting vulnerabilities or activating a service.

Requirements: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 evidence preparation.
Owner: `deploy/bin/external-runtime-stage.sh` and a focused stdlib verifier in `tools/`.
Authority: ADR-KSI-032, [Release Evidence](../../ops/RELEASE_EVIDENCE.md),
[runtime assembly](../../../deploy/external-runtime/README.md), current Task3 ledger.
INV-054 is enforced by exact raw byte/image binding. INV-051/053/055/060 remain unchanged;
no policy, tenant credential, customer rights or quantitative authority is issued.
Reference adoption: existing KSI release readers/host-binding consumers only; no submodule edits.

## Observed native report and identity distinctions

Retained repaired reports produced by Grype0.120.0 have `matches`, `source`, `distro`, `descriptor`.
Tool identity is `descriptor.name="grype"`, `descriptor.version="0.120.0"`.
`descriptor.db.status.schemaVersion="v6.1.10"` is the **database** schema, not the report schema.
There is no native top-level `scanner.schemaVersion`; do not add or invent one.

`source.type="image"` and `source.target.imageID` identify the scanned Docker config ID.
For the retained Docker archives, `source.target.manifestDigest` is Syft's synthetic Docker
manifest, not the OCI index/platform digest. `source.target.repoDigests` is empty. Therefore
bind `imageID` to the already host-verified `dockerImageId`; do not require synthetic digest
equality with a registry ref or infer publication. Existing registry/RepoDigest checks still run.

## Consumer contract

Canonical release evidence and `external-runtime-host-binding.v1` wire shapes and artifact type
`scanner-json` stay unchanged. They already carry path/byte length/SHA256 and the expected
runtime Docker image ID. Core/Dashboard generic scanner behavior remains unchanged in this unit.

For inspector/measurement strict scanner verification, accept exactly two disjoint families:

1. Existing scanner envelope with nonempty string `scanner.name` and `scanner.schemaVersion`,
   retaining its current compatibility behavior.
2. Native Grype0.120.0 JSON with the supported descriptor/source/matches shape described below.

A document containing both families is ambiguous and rejected. A malformed/unsupported native
document never falls back to the legacy scanner check. Unknown Grype versions need explicit
schema/fixture review; this profile is limited to the actual tested version, not all future Grype.

Native validation requires:
- `descriptor.name` exactly `grype`, version exactly `0.120.0`, nonempty timestamp.
- `descriptor.db.status` object with `valid` exactly true, nonempty `built`, and supported
  database schema `v6.1.10`. `configuration` and `db.providers` must be objects.
- `source.type` exactly `image`, `source.target` object, and `imageID` a lowercase SHA256
  identity exactly equal to the expected runtime Docker image ID supplied by the consumer.
- `matches` array; each match is an object containing object-valued `vulnerability` and
  `artifact`, nonempty vulnerability ID/severity and artifact name/version. Other native
  fields remain unmodified. Zero matches is structurally valid, not a security decision.
- If `ignoredMatches` exists, it is an array and its contents are preserved for review.
  Parser acceptance does not approve ignores or claim a complete unsuppressed scan.

Do not dereference paths or URLs embedded in the report. The report's DB location/`valid` flag
does not prove DB byte identity, authenticity or approved freshness. Original tool checksum/
Sigstore material, offline DB hash/provider snapshots and image/archive/SBOM provenance remain
separate release-review evidence. A parser validates representation and binding, not truth of
an untrusted producer, tool authenticity, exploitability, waiver or customer-data release.

## Safe file and integration boundary

Add one stdlib-only, non-networked verifier `tools/verify_external_scanner_evidence.py`.
It reads one normalized absolute scanner path through descriptor-relative directory traversal
and `O_NOFOLLOW`, requires a nonempty regular file of at most16MiB, verifies its supplied
byte count/SHA256 and stable fstat identity, then parses that **same** payload. Reject UTF-8/JSON
errors, duplicate keys, non-finite numbers and non-object roots. No generated report, default
image identity, environment-based authority, directory creation or tool/DB/image execution.
Use Python3 already required by the lifecycle; no new package/system tool dependency.

The strict scanner branch in `verify_artifact_binding` delegates to this verifier and passes
the actual runtime `dockerImageId` from `require_release_evidence` after image/RepoDigest checks.
It must not hash one file and validate bytes read from a substituted file. Other artifact paths
and existing release/host source checks remain unchanged. Failure remains
`BLOCKED_RELEASE_EVIDENCE`; no successful scanner check skips socket/authority/security gates.
CLI diagnostics expose reason codes, not report contents/embedded configuration or credentials.

## Acceptance and negative cases

Dedicated stdlib verifier tests and stage shell integration tests must cover:
- Legacy valid scanner compatibility and unknown/untyped empty JSON rejection.
- Native real-shape reports with both nonempty and empty matches; raw bytes never rewritten.
- Wrong image role/ID, missing expected identity, unknown tool/version, invalid DB/schema,
  malformed match/ignoredMatches, missing descriptor and mixed families are rejected.
- Wrong artifact hash/size, oversized file, duplicate keys, NaN, invalid UTF-8, symlinked parent/
  leaf, nonregular file and observed replacement/change during read are rejected.
- Native report accepted only with unchanged canonical/host source/image/artifact evidence;
  substituted RepoDigests/image binding still fails. No Docker/Compose/service activation in tests.

Tests may use small labeled fixtures matching the observed profile; they are not release evidence.
In local verification, also exercise both preserved real Grype reports with their actual raw
hashes/lengths/config IDs, and prove mismatched IDs/hashes reject them. This proves consumer
compatibility, not complete release acceptance, signatures or live containment.

## Files, rollback and follow-up

Expected owned files: verifier, focused verifier tests, existing stage/deployment contract tests,
runtime README and release/local-verification documentation. Existing host-binding wire fields
remain unchanged; do not introduce a producer envelope or Grype findings rewrite.
Rollback restores the prior strict scanner consumer, preserving all raw reports/host evidence.
No automatic host installation, bootstrap, registry push, signing/credential provisioning or
public TIFF processing. Bundle packaging and actual authorization suppliers stay separate work.
