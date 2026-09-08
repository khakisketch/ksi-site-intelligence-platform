# Proposed external inspector Docker-sandbox amendment

Date: 2026-09-07
Status: **APPROVED for the semantic amendment and local code implementation**
by the Human on 2026-09-07 (reply: “승인합니다” to the reviewed amendment and local
implementation plan). It replaces only the sandbox-runner requirement of the
[Task 4 plan](../plans/2026-09-07-external-artifact-validation.md#task-4-bounded-geotiffcog-inspection-worker).
Dedicated identities/daemon provisioning, container execution, host-backed
synthetic tests, production policy, customer data and release are NOT approved.

## Scope and authority

This responds to the lack of a validated bwrap backend in the [synthetic-only diagnostic](../../../.superpowers/sdd/2026-09-07-external-artifact-validation/sandbox-diagnostic-results.json).
The worker-image PATH lookup did not find bwrap and an earlier host namespace
failure remains unresolved; neither is a filesystem-wide absence claim. That
diagnostic observed basic controls in existing images; it did not establish
hostile-input safety, Docker trust, mounts, rootless delegation, escape
resistance, deployment, or parser acceptance.

Requirements remain REQ-INT-101–104, REQ-SEC-101, and REQ-OPS-102. This proposal
preserves INV-024 (no unsupported absolute accuracy), INV-051 (derived remains
non-source), INV-053 (no quantitative use absent compatible authority/evidence),
and INV-060 (server-derived tenant scope/non-disclosure). The active
[external-validation design](2026-09-07-external-artifact-validation-design.md)
and [ADR-KSI-036](../../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md)
remain authoritative.

## Alternatives and recommendation

| Option | Disposition |
|---|---|
| Retain bwrap in a validated environment | Valid alternative; no unsandboxed fallback. |
| Worker/Core/parser accesses Docker daemon | Rejected: broad container-control privilege. [Docker documents daemon trust and host-mount power](https://docs.docker.com/engine/security/). |
| Local launcher + dedicated rootless daemon | **Candidate only:** narrowest available Docker boundary. |

## Proposed boundary

```text
worker -- capped local UDS --> launcher (distinct OS UID)
                            --> dedicated rootless Docker daemon
                            --> pinned inspector container
Core, worker, parser: no Docker socket/credential/image/path/URL/env/flags
```

The launcher is a separately operated daemon adjunct of processing-controller,
not a generic product service. Its owned UDS uses `SO_PEERCRED` to allow only
the worker identity. One UDS connection carries one bounded request and one
operation; disconnect cancels it, timeout is typed incomplete, and the attempt
is terminal only after cleanup.

The launcher trusts the authenticated processing-controller worker through the
existing Core fenced input/heartbeat adapter; it does not independently
authorize current Core policy/fence and adds no Core principal, route, or port.
After a capped header, `InspectorLaunchRequestV1` contains exactly
`protocolVersion: "inspector-launch.v1"`, `operation: INSPECT|SANITIZE`,
original immutable `request`, Core `fence`, sealed `subject`, `sealedByteBinding`,
pinned `policy`, `attemptNonce`, and `canonicalInputDigest = SHA-256(canonical
body excluding exactly canonicalInputDigest)`. Its local `sealedByteBinding` is
exactly `{artifactId, observedSha256, observedSizeBytes}`, using the strict
types and wire aliases of existing Core input; it carries no object key or
download URL. Other nested values use existing immutable types. No URL, path,
image, environment, flag, or client limit is representable. It is followed by
exactly `sealedByteBinding.observedSizeBytes` raw bytes, capped and SHA-256
matched to `sealedByteBinding.observedSha256` before decoding; short, extra, or
trailing bytes reject. The worker rechecks Core before launch/on heartbeat and
cancels on loss; Core alone rejects stale result.

The fixed response frames are `ACCEPTED(nonce)` acknowledgement only, then
either `COMPLETED(nonce, canonicalInputDigest, inspectorBuildDigest, outcome,
outputSizeBytes, outputSha256)` followed by exactly bounded output bytes, or
`FAILED(nonce, typedReason)`. For INSPECT, `outcome` is existing
`ArtifactInspectionOutcomeV1`, `outputSizeBytes` is zero, and `outputSha256` is
absent. For SANITIZE, `outcome` is the fixed literal `SANITIZED` (not eligibility), output size/hash are
non-null bounded derivative bindings, and no file path exists. Parent validates
only bounded metadata schema plus length/hash; it never parses raster output.

The launcher resolves only an independently signed manifest from an
operator-provisioned read-only local catalog. Provisioned trust root, catalog
identity, signature verification, and revocation state are startup requirements:
missing, untrusted, revoked, or unreadable catalog fails closed. It verifies
canonical policy/envelope binding, clamps to hard ceilings, and includes upload
bytes in aggregate request/concurrency/spool quotas. No numeric value is chosen.

## Execution manifest and enforcement

Propose additive `InspectorExecutionManifestV1`, external to the OCI image and
represented by `contracts/schemas/inspector-execution-manifest.v1.json`. Its
canonical body binds exact image content; source/build/SBOM/protocol/backend/
security-profile digests; fixed environment/grid policy and UID; and finite
byte, CPU, memory, PID, wall-time, log, and output ceilings. It contains no
parser/inspector self-digest fields: `parserBuildDigest = inspectorBuildDigest =
SHA-256(canonical manifest body excluding signature/self digest)`. A detached
signature covers that body, preventing a hash cycle. The image contains parser
and protocol, not the manifest binding its image digest. The exact semantic
addition is `ExternalValidationPolicyV1.parserBuildDigest ==
InspectorExecutionManifestV1.canonical_body_digest ==
ExternalArtifactInspectionReportV1.inspectorBuildDigest`; no policy-schema field
is needed. Schema parity tests reject equality, signature, image/profile, or
report/policy mismatch. Reports do not decide eligibility.

Admission requires proof of effective rootless cgroup-v2/systemd delegation for
CPU, memory, and PIDs. [Docker's rootless resource guidance](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources)
warns unavailable controllers may make flags ineffective; it is not proof here.
No memory-limit claim or fallback is made without observed enforcement.

Host/worker work is count, SHA-256, and bounded magic hints only; TIFF structure
and GDAL/PROJ parsing run inside the container. Launcher creates one private
exclusive regular file, checks count/hash, and makes the only
launcher-configured host bind read-only at fixed `/input/artifact.tif`. This
controlled bind exceeds the diagnostic without caller-supplied binds and needs
independent acceptance. No workspace, customer directory, socket, archive/tar
input, sidecar, or other bind is permitted; Docker-generated mounts were not
enumerated by that diagnostic.

Reject symlink, hardlink, inode substitution/TOCTOU, and caller filenames.
User-namespace mapping must prove the fixed container UID reads that file without
broadening permissions; else unavailable. Container output is bounded framed
stdout into launcher-owned bounded tmpfs; launcher validates length/hash only.
Pinned GeoTIFF parsing has no network, credentials, writable root, capabilities,
plugins/PAM, remote VSI, unapproved grids, or unbounded logs. Timeout cleanup
uses durable exact container-ID/owner records; reconciliation never broad-deletes
by label. Cleanup failure closes new admission and retains recovery evidence.

Before create, the launcher durably records intent, nonce, deterministic owned
container name, owner, manifest/profile digests, and pending state. It binds a
returned ID only after exact owner/name/profile verification. Startup queries
only that known name: exact verification permits bind/cleanup, absence permits
retry, and uncertain/mismatched state stops admission without broad deletion.
Tests cover crash before create, after create-before-ID, and after-ID-before-
cleanup. This replaces **only** Task 4's bwrap-runner paragraph; full scan/
nodata, per-artifact/incomplete report, report-first/display takeover,
display-grant, and sanitizer semantics stay inherited unchanged.

## Approval, rollback, and evidence

Separate Human approval is required for this semantic amendment, contract
addition, distinct identity/daemon/UDS provisioning, signed image evidence, and
synthetic hostile-input scope. Provisioning is an external operational action.
Customer data, policy activation, deployment, compatibility, accuracy, HIL,
field acceptance, and release are separate gates. A compromised already-trusted
worker can threaten measurement integrity within its existing credentials: this
limits daemon privilege/resource blast radius, not measurement truth. Manifest
signatures do not attest bytes/computation; Core checks do not recompute raster
reports.

Rollback is admission-off: retain immutable reports/attempts, remove only exact
registered containers and launcher-private files after evidence capture, and
return typed sandbox-unavailable. Never widen Docker access or parse unsandboxed.
Without approval, revalidate bwrap.

Post-approval evidence must cover digest/signature/UDS authorization; synthetic
hostile bytes, timeout, cleanup, no-network/no-credential/mount/TOCTOU cases;
actual controller and UID enforcement; and independent security/operational
review. It proves only the tested local profile.
