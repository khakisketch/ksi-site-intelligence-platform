# External runtime Python security repair design

Status: design direction approved in chat; written-spec review pending.
Date: 2026-10-03

## Intent and authority

The Human requested all follow-up development improvements and approved the two-image Python
repair design. Remove the confirmed affected Python component from the two contained runtime
images while preserving existing OS fixes and runtime boundaries. Do not convert a corrected
image or reduced scan count into release, containment, data-use or quantitative authority.

Requirements: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 preparation only.
Owner: root external inspector/measurement Dockerfiles and their packaging/security tests.
Authority: ADR-KSI-032 D1, ADR-KSI-036, existing
[Task 3 record](../plans/2026-10-03-contained-runtime-preparation.md).
INV-054 remains enforced by exact multiarchitecture image pins and source/image/SBOM/scan binding.
INV-051/053/055/060 remain unchanged: no managed identity, comparison authority, Core policy or
tenant grant is created. No device/HIL assumption, new data license or reference adoption.

## Exact change boundary

Change builder and final `FROM` in both `Dockerfile.external-inspector` and
`Dockerfile.external-measurement` to:

```text
python:3.12.15-slim@sha256:29113dcae7aad06daa8e95260fa09f27d62be33b9687ea3774f771d601a02256
```

The official public registry returned this OCI index for both `3.12.15-slim` and
`3.12.15-slim-trixie`; its Linux ARM64/v8 manifest is
`sha256:18d23907c5d7ef2ca1b0ea8b4a73fe4a6ae47114c257a1afed8bc66c3886f8cb`.
Retain and hash raw index/platform/config bytes before implementation/build; a response digest
alone does not prove a built image or signature authenticity. Refetch by immutable identity, not
by silently changing the selected pin if the tag moves.

Preserve `uv:0.11.15` digest, `uv.lock`, all Python dependency versions, the exact allowed Docker
contexts, distinct image users10003/10004, fixed entrypoints and copies. Preserve the
`20261003T000000Z` Debian/security snapshots and all current exact package versions:
gzip1.13-1+deb13u1; libc-bin/libc6 2.41-12+deb13u4; libexpat1 2.8.3-1~deb13u1;
libpcre2-8-0 10.46-1~deb13u3; libsqlite3-0 3.46.1-7+deb13u2;
openssl/libssl3t64/openssl-provider-legacy 3.5.7-1~deb13u3; perl-base5.40.1-6+deb13u1.
Do not use unsigned APT, downgrade flags, floating images or a changed Python minor series.
If the selected base cannot build with these pins, investigate and report the conflict rather
than weakening signatures, changing locks or guessing new pins.

## Regression contracts

`tests/contract/test_external_runtime_image_packaging.py` must check the new Python exact pin
in **both** stages, current snapshot and existing copies/identities/commands/context allowlists.
`tests/contract/test_external_runtime_image_security_pins.py` must check the real approved snapshot
and OpenSSLdeb13u3 rather than obsolete20260911/deb13u2. Preserve cryptography50.0.1 checks and
strict package assertions; removing assertions or accepting arbitrary newer strings is not repair.

Before this task, those two files reproduced2failed/3passed on clean
`14b5d9891f1ea69b7cc105c5d9086385a6b7886a`; this is baseline evidence, not a new regression.
Require RED for the desired Python pin before repair, then GREEN for source/pin contracts.
Run existing runtime pin, release, deployment, inspector and measurement owner regressions.

## Real image verification and acceptance

Use only the existing dedicated rootless daemon, fresh task-private build contexts derived from
the exact clean Git tree, additive image tags and the retained tools/DB. Preserve prior image
IDs, source archives and raw reports. Do not install system tools or mutate staging/accounts/units.

Technical acceptance requires both actual ARM64 builds, archived index/platform/config/layer
hashes, source/context identity, SBOM Python3.12.15, preserved OS/Python dependency checks, and
same-tool/same-DB raw scans. Confirm `CVE-2026-82049` no longer matches the Python binary and
verify the actual archived `tarfile.py` is the upstream fixed version; do not assert removal from
imports, tests or a Dockerfile string alone. Report every residual finding, not `High == 0` as an
invented gate. Preserve the official PSF applicability evidence and unknown exploitability state.

No public TIFF, hostile raster, daemon startup or genuine tenant operation runs in this task.
New runtime identities need genuine newly signed execution profiles before later activation;
old manifests/trust records cannot be relabeled. Sigstore, release security, Core/worker authority,
actual containment and customer/field acceptance remain independently open.

## Rollback and handoff

Rollback uses preserved prior source/image identities, not a tag-only fallback, prune or reset.
Record exact repaired source/image/report hashes and residual gates in the existing task ledger
and local-verification doc. Locally integrate task-owned verified source only; no push/deployment.
Application bundle packaging is a separate implementation unit, not silently folded into this repair.
