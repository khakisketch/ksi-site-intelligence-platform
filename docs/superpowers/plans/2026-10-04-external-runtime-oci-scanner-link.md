# External Runtime OCI-to-Scanner Link v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the Human's preserved inline execution method. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the actual host OCI index→ARM64 manifest→config relation before consuming an unchanged native Grype runtime report.
**Architecture:** Add a bounded read-only stdlib archive verifier and a separate host-binding v2 schema. The existing lifecycle retains its independent host/source/RepoDigest checks and passes only the archive-derived config ID to the strict scanner consumer; v1 remains unchanged.
**Tech Stack:** existing Python3.12 stdlib, Bash/jq, pytest and prepared jsonschema/Ruff/mypy; no new dependencies.
**Spec:** [approved written v2 design](../specs/2026-10-04-external-runtime-oci-scanner-link-design.md).
**State:** approved technical unit complete and locally integrated; task/actual-main full regressions, independent review and genuine historical links verified. Release, activation and human product acceptance remain open.

**Human execution-review follow-up complete:** shared-DAG throughput/depth/cache and fixed future
release baseline inspected. Existing memoization was linear but a cached deep path could evade
depth8. Targeted2RED/3existing passes→related274GREEN19.44s after subtree-height and explicit
270337descriptor budget repair at5d0bb80. Two genuinehistoricalpairs reverified, originalsunchanged.
Taskfull8325passed/121skipped/98warnings776.15s; actualmainsource-equivalent407c9adrelated274pass18.56s
and full8325passed/121skipped/98warnings778.61s. Laterbundleplanning/status files aredocs-only.
The prior8320 results belong to the pre-repair source and remain retained, not relabeled.

## Execution summary

- [x] Task1 source deliverable:3fb5094; OCI72RED→GREEN, combinedscanner110pass0.42s, Ruff/mypy clean.
- [x] Task2 source deliverable:b444389; v2/platform9RED→GREEN (2v1stillpass), related269pass18.88s, Ruff/mypy2/bash clean.
- [x] Task3 closure:2actualhistoricalpairs verified, allwrongbindings/laterHEAD reject, originalsunchanged;
  taskfullb4443898320pass/121skip/98warnings/zero failures774.20s; independentread-only whole review
  noCritical/Important. Cleanlocalmainfast-forwardedtoedbdd78; actualmain269pass18.99s/Ruff6/mypy2/bash
  clean, full8320pass/121skip/98warnings/zero failures784.04s. Completionrecorddocs-only; no freshfullclaim.
  Review disposition in existingtaskledger. Alloriginalevidence/worktrees retained, no push/activation.

Detailed step checkboxes below are the original execution recipe; the summary and existing
task ledger record verified deliverables and remaining closure work, not inferred acceptance.

## Global Constraints

- Keep canonical `release-evidence.v1` unchanged. Add separate `contracts/schemas/external-runtime-host-binding.v2.json`; do not silently extend v1.
- `dockerImageId` remains the genuinely observed Docker ID (OCI index on this store). It is **not** replaced by a scan config ID.
- Each v2 runtime has exactly one `ociArchive`: absolute non-traversing path, lowercase `sha256:<64hex>`, positive integer bytes at most1GiB, `type: oci-archive`; both runtime roles required.
- Supported profile: Linux ARM64, variant absent or `v8`; native Grype0.120.0/DBv6.1.10, original bytes/findings/ignores preserved. No inferred platform or unsupported profile fallback.
- Outer archive: uncompressed TAR, ≤4096members, raw checked512byte headers, regular files/directories only; reject PAX/GNU/sparse/link/special flags before reading extension bodies.
- JSON index/layout/manifest/config ≤1MiB; graph depth≤8, descriptors per index/manifest≤64. Hash full archive and every archived/referenced blob; never extract/decompress/execute layers.
- Exact source40lowercasehex and actual role-specific user/fixed Cmd; archive provenance is not tool authenticity, a waiver, signing/Core/tenant authority, registry publication or containment safety.
- No build/load/export, host installation, service activation, TIFF decoding, new scanner run/DB, credential/key issuance, remote push, deployment or reference edit. Preserve all original images/reports/archives/workspaces.
- Use the existing task worktree `integration/readiness-20261002`; base and local-main target are `7f56def5a704cb0ba7884817375a9c298c15b615` at planning. Revalidate target/status at execution/integration.
- Use existing task ledger `.opencode/artifacts/contained-runtime-preparation-20261003/progress.md` and its private evidence directory; no competing product-slice/goal or disposable evidence cleanup.

## Required implementation packet

Requirement IDs: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 preparation only.
Owner module: cross-domain host contract, tools artifact verifier and deploy lifecycle consumer.
Acceptance criteria: unchanged genuine archive/report pairs link to independently verified host index; hostile/substituted/ambiguous inputs block; v1/legacy and all other gates remain intact.
Contracts affected: additive external-runtime-host-binding.v2 only; v1/canonical release/source/authority wire unchanged.
Reference assets: existing KSI safe-file/strict-JSON/scanner/schema/shell-test patterns and retained16084bf archive receipts.
Adoption decisions: reuse reviewed format/role/source boundaries; implement bounded stdlib read-only validation, not a producer or reference-repository import.
Files to change: exact map below; no runtime images, lockfile, package manifests or service application code.
Tests: labeled synthetic archive/schema/consumer negatives; retained actual historical archives/reports; source regressions and actual-main reruns.
HIL or real-device assumptions: none; Docker observations reused only where genuine and explicitly dated, never HIL or activation proof.
License/data implications: existing stdlib/test tooling and local build evidence; no customer data, external upload or new license grant.
Rollback: consumer returns to v1-only path; preserve v2 records/evidence, never reinterpret as v1 or delete originals.
Invariants: INV-054 exact byte/source/host/config link enforced in verifier+consumer; INV-051/053/055/060 remain unchanged (no lineage, quantitative, policy or tenant grant).

## File map and interfaces

| Path | Responsibility |
| --- | --- |
| `tools/verify_external_oci_archive.py` (new) | Single-descriptor bounded archive/TAR/JSON/blob graph verification; returns only derived config ID |
| `tests/support/external_oci_archive_fixture.py` (new) | Small deterministic synthetic OCI graph factory shared by verifier and shell tests, explicitly not release evidence |
| `tests/contract/test_external_oci_archive.py` (new) | Safe reader, graph/provenance/resource/CLI positive and mutation negatives |
| `contracts/schemas/external-runtime-host-binding.v2.json` (new) | Strict additive v2 shape, no trusted declared config ID |
| `tools/verify_external_scanner_evidence.py` | Opt-in v2 Linux/ARM64 scanner-target check; prior default behavior unchanged |
| `deploy/bin/external-runtime-stage.sh` | Explicit version selection, archive derivation after host check, scanner handoff, fail-closed diagnostics |
| Existing scanner/deployment contract tests | Version/schema/platform/full shell gate regression coverage |
| Runtime README, RELEASE_EVIDENCE, SPATIAL_DATA_LOCAL_VERIFICATION, spec/plan/ledger | Supported profile, actual verification/limitations and exact source distinctions |

## Review Focus

1. Resource bypass before TAR parsing: an advertised huge PAX/GNU/sparse body must reject before allocation/read, even inside a correctly hashed ≤1GiB archive (Task1 guarded-reader tests).
   Human continuation also requires digest-result reuse, cached subtree height and an explicit
   aggregate descriptor budget; shared fanout must not cause exponential reads or hide depth9.
2. Valid selected runtime hides bad extra evidence: verify unselected attestation/extra blobs too; shared valid content is allowed, conflicting descriptors and missing blobs are not (Task1 graph tests).
3. A rehashed historical or wrong-role archive is still not current release evidence: derive source/role/platform from verified config, reject mismatch; never relabel16084bf as later HEAD (Tasks1/3).
4. Failed CLI output or a prior role's derived ID is not authority: nonzero exit with plausible stdout, role swaps, wrong host ID/RepoDigest and config/platform mismatch must still block (Task2 shell tests).
5. Version/legacy fallback cannot bypass v2: mixed/unknown records reject, v1 remains strict equality, legacy annotations stay compatible without claiming native in-report binding (Task2 compatibility tests).

---

## Task 1: Independently testable read-only OCI link verifier

**Files:** create `tools/verify_external_oci_archive.py`, `tests/support/external_oci_archive_fixture.py`, `tests/contract/test_external_oci_archive.py`.
**Consumes:** protected archive path/hash/bytes and independently observed host index, source commit and runtime role from spec; no scanner input.
**Produces:**
- `verify_oci_archive(path: Path, *, expected_sha256: str, expected_bytes: int, expected_index_id: str, expected_source_commit: str, role: str) -> str` returns lowercase config digest only after all checks.
- `OciArchiveEvidenceError(ValueError)` exposes `.code` and safe `OCI_ARCHIVE_BLOCKED: <CODE>` only.
- CLI `--path --sha256 --bytes --index-id --source-commit --role`; success stdout is exactly `<derived sha256>\n`, exit0; evidence failure stdout empty, stderr safe code, exit1; argparse misuse may exit2.
- Test-only `OciFixture` frozen dataclass with `payload: bytes`, `index_id: str`, `config_id: str`, `source_commit: str`, `role: str`; `make_oci_fixture(role: str, source_commit: str) -> OciFixture` creates one runtime plus one unknown/unknown in-toto attestation and ≥1 tiny raw layer. Hash actual generated bytes, do not use invented successful digest constants.

The first positive test's essential assertion is:

```python
fixture = make_oci_fixture("inspector", "a" * 40)
path.write_bytes(fixture.payload)
assert fixture.index_id != fixture.config_id
assert tool.verify_oci_archive(
    path, expected_sha256="sha256:" + hashlib.sha256(fixture.payload).hexdigest(),
    expected_bytes=len(fixture.payload), expected_index_id=fixture.index_id,
    expected_source_commit="a" * 40, role="inspector",
) == fixture.config_id
assert path.read_bytes() == fixture.payload
```

- [ ] Write `test_actual_index_to_config_link_is_derived_not_declared` for both roles: fixture uses source`a`×40, exact `ksi-<role>-image` and `/app/.venv/bin/ksi-external-<role>-entrypoint`; supplied index≠derived config, returned config matches exact bytes; original archive unchanged. Load tool with existing importlib patterns so missing verifier is the expected RED.
- [ ] Run RED: `UV_NO_SYNC=1 UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q tests/contract/test_external_oci_archive.py`; expect failure because verifier does not exist, not a fixture/import-path error.
- [ ] Implement the exact function/CLI. Validate expected types/digests/source/role before reading; `type(expected_bytes) is int` excludes bool. Descriptor-relative `O_NOFOLLOW` parent/leaf with `O_NONBLOCK`, regular-file check and stable fd/entry identity; hash/seek/parse the same fd. Stream in ≤1MiB chunks, never retain full archive/layer in memory. Rehash/stability-check before successful return. All fd cleanup on every error; NUL/path/read/JSON/TAR errors become safe codes.
- [ ] Implement checked raw TAR offsets/headers/checksums (stdlib `TarInfo.frombuf` on one512byte header is permitted, not `TarFile` extension expansion). Allow regular-file/directory flags only, directory size0, normalized names unique, no absolute/`..`, checked payload and padding within archive. Require two zero end blocks, zero trailing padding. Allowed names: index/layout, optional bounded compatibility `manifest.json` (never an identity source), `blobs/sha256/<64hex>` and directory markers. Bound metadata≤1MiB, members≤4096 before storing offset entries.
- [ ] Implement strict UTF-8/duplicate/nonfinite JSON, exact integer descriptor sizes and supported media. Verify root1.0.0 layout/schema2 index with one supplied-index root; full content-addressed graph, depth≤8 and ≤64descriptors per node. Exactly one runtime Linux/ARM64 manifest (variant absent/v8); attestations never selected. Permit shared same-size/media blobs; reject conflicting descriptors/foreign URLs/unsupported media. Hash every archived blob including unselected/extra ones and resolve all graph references; layers stay opaque. Media types exactly as spec, including in-toto attestation blobs.
- [ ] Check selected verified config source/user/Cmd, Linux/ARM64 and rootfs`type=layers`, lowercase diff IDs with count==runtime layers. Nonempty `Entrypoint` would change the fixed command and must block; absent/null/empty is permitted. Attestation bytes are hash-checked, not signature-verified. No metadata/result fallback or external reads.
- [ ] Add `test_bound_reader_rejects_unsafe_file_or_change`: wrong hash/size/expected types, leaf/parent symlink, FIFO/device/directory, grow/truncate/replacement and close-on-error. Add `test_tar_headers_reject_before_extension_payload_read` with guarded reads for PAX/GNU/sparse/oversize, member4097, bad checksum/name/type/offset, duplicate name, missing end blocks and trailing garbage. Full raw hashing is permitted in bounded chunks; guards forbid parser reads/allocations based on advertised extension-body size, not the required raw hash stream. Assert `pytest.raises(tool.OciArchiveEvidenceError)` and no read request larger than1MiB. Observe each new negative RED before its minimal implementation.
- [ ] Add `test_graph_proves_all_blobs_and_exact_runtime`: wrong root/index/manifest/config/layer digest or size, missing/unselected/extra corrupted blob, duplicated ARM64 candidates, bad variant/source/role/Cmd/Entrypoint/rootfs/platform, shared valid blobs, conflicting descriptors, foreign URL, unknown media, graphdepth9/descriptor65, malformed/duplicate/deep/nonfinite JSON. Recompute outer archive binding in graph mutation cases so errors exercise internal proof, not merely INPUT_HASH. Add `test_cli_output_is_only_config_digest_or_safe_blocker`; contents/paths never appear in errors. Observe RED→GREEN.
- [ ] Run whole verifier GREEN plus prepared `.venv/bin/ruff check` on the3files and `.venv/bin/mypy tools/verify_external_oci_archive.py`; expect zero failures/lint/type errors. Commit only Task1 files: `feat: verify bounded OCI runtime index-to-config evidence`.

## Task 2: Versioned host schema and strict lifecycle consumer

**Files:** create v2 schema; modify scanner verifier, stage and their existing2contract test files. V1 schema and canonical release files unchanged.
**Consumes:** Task1 CLI and function result; already host-verified image ID, canonical source commit and protected archive metadata.
**Produces:**
- Explicit v1/v2 `validate_host_binding` selection, strict per-version runtime keys; v2 required bounded archive metadata and existing role/reference/host constraints.
- `verify_scanner_evidence(..., expected_image_id: str | None, require_linux_arm64: bool = False) -> str`; CLI adds `--require-linux-arm64`. Only native profile target gains this check; existing legacy semantics/default remain unchanged.
- `verify_artifact_binding(path,sha,bytes,type,strict=0,image_id="",require_linux_arm64=0)` adds seventh shell argument only. After validated v2 host/role/source proof, caller passes derived config and7tharg1; v1 passes original host ID anddefault0.

Platform opt-in preserves the existing default while rejecting a wrong native target:

```python
# `path` contains a valid existing native fixture except target.architecture="amd64".
binding = dict(expected_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
               expected_bytes=path.stat().st_size, expected_image_id=image_id)
assert tool.verify_scanner_evidence(path, **binding) == "grype-0.120.0"
with pytest.raises(tool.ScannerEvidenceError):
    tool.verify_scanner_evidence(path, **binding, require_linux_arm64=True)
```

- [ ] Write `test_v2_host_schema_and_stage_are_strict_without_extending_v1`: v2 both roles with exact archive4fields accepted by schema and sourced host parser; missing/extra/mixed/unknown version, one missing archive, declared config ID, path traversal, bool/float/zero/1GiB+1bytes, wrongtype/digest, duplicate role and source/hash mismatch rejected. V1 fixture still passes; adding archive under v1 fails. Use existing prepared Draft202012Validator test pattern. Run RED on missingv2schema/oldstage, not unrelated clean-source failure.
- [ ] Add v2 schema based on v1's strict defs, changing only id/title/version and required `ociArchive` definition (`maximum:1073741824`). Keep v1 bytes untouched. In stage branch v2 rules explicitly; correct v2 path predicate grouping (absolute and no`..`segments) and actual repository-digest uniqueness. Do not silently loosen or refactor pre-existing v1/generic behavior.
- [ ] Write `test_native_scanner_platform_is_required_only_when_requested`: native Linux/ARM64 passes with flag; missing/wrongos/wrongarchitecture fails; same original report/default v1 remains compatible; legacy metadata still accepted without fabricated platform proof; unsupported/mixednative still fails. Run old scanner RED, add optional exact-bool argument/flag and native check, run GREEN.
- [ ] Write `test_stage_v2_derives_each_runtime_config_after_host_verification`: extend existing sourced `require_release_evidence` fixture for both version choices and scanner families. V2 fixtures contain actual tinyOCIgraphs source`a`×40 with distinct hostindex/config IDs and matching native os/architecture. Keep full Core/Dashboard/dependency fixture checks, no real release record fabricated. Assert unchanged raw archives/reports and correct v1direct/v2derived routing. Run old stage RED with validv2 fixtures.
- [ ] Integrate only the runtime loop: hostimage/RepoDigest→SBOM→v2 OCI CLI→strictscanner. Extract validated `schemaVersion` once, reset derived ID/platform flag every role. For v2 pass current canonical source/role/host ID to CLI; capture output only on exit0 and require exactly one lowercase digest. Nonzero/malformed output raises role-specific `BLOCKED_RELEASE_EVIDENCE`; never fallback to host ID, scanner ID, previous role, synthetic manifest or v1. No publication/load/export/activation commands added.
- [ ] Add `test_v2_archive_failure_cannot_become_scanner_authority`: fake trusted CLI test stub emits plausible config then exit1 or malformed output; stage blocks before scanner. Mutation/rebound fixtures reject wrong archive/source/role, scanner config/platform/hash, second-rolefailure, altered host ID/RepoDigest, canonical source/hash, missing dependencies and dirty source. Caller still requires existing ownership0600/signed/currentness/live gates; source stub remains explicitly synthetic. Observe each regression RED→GREEN.
- [ ] Run GREEN with command-localumask022/offline/no-sync: `.venv/bin/python -m pytest -q tests/contract/test_external_oci_archive.py tests/contract/test_external_scanner_evidence.py tests/contract/test_external_runtime_deployment_contract.py tests/contract/test_release_evidence.py tests/contract/test_runtime_image_pins.py tests/contract/test_external_runtime_image_packaging.py tests/contract/test_external_runtime_image_security_pins.py`; then changed-file Ruff, mypy bothverifiers, `bash -n deploy/bin/external-runtime-stage.sh`, `git diff --check`. Expect no failures/errors and no diff in v1/canonical schema, Dockerfiles, locks or manifests. Commit: `feat: bind native runtime scans through verified OCI archives`.

## Task 3: Genuine historical evidence, final review and authorized local integration

**Files:** deployment README and RELEASE_EVIDENCE/local-verification docs; this plan/spec status and existing private ledger/checkpoint. No authority supplier/producer or bundle installation.
**Consumes:** Task1/2 committed verifier+consumer; both preserved16084bf archives and rawreports, actual prior observed index IDs and same archive-source16084bf.
**Produces:** honest retained evidence, reviewed/regression-tested source and authorized clean local-main integration; not a current-source full release/activation.

- [ ] Rehash retained archives to `image-build-16084bf/reports/python-repair-verification.json` identities. For each role use `/tmp/opencode/ksi-runtime-verification-20261004-16084bf/images/<role>.tar`, its actual recorded index ID and source`16084bfa6c8bdde6123511ea11660852707e6760`; invoke actual CLI and strictscanner with unchanged report/hash/bytes and Linux/ARM64 flag. Require derivedconfig==independent retainedconfigreceipt and report target. Before/after bytes/hashes identical; wrongindex/role/hash/source/config rejects. Do not decode/extract/execute images or TIFFs.
- [ ] Retain commands/results/hashes privately, with `fullReleaseGateExecuted:false` and historical-image-source vs verifier/current HEAD explicit. Existing builds cannot pass a laterHEADsource assertion; prove that negative instead of relabeling. Complete actual release remains blocked by genuine current-source builds, Core/Dashboard/registry/security/authority/live inputs. No fake host release record or new scan/build for this task.
- [ ] Run entire prepared task Python suite with command-localumask022/offline/no-sync/no-download. Create logs privately before lowering mask for tests. Expect zero failures; preserve original failures if any, use systematic-debugging rather than disable directory/SDK gates or skip tests. Record exact revision, count/skips/warnings/time; changed code gets rerun after repairs.
- [ ] Update supported-profile/v1fallback/legacy limits and actual results docs; old-v1 blocker remains true, replace overalltarget-block wording only with verified narrowv2 evidence. Bundle packaging, tool-signature/DBauthenticity, High59 disposition, true release/current-host/containment/customer/accuracy gates remain open. Check local links/anchors and `git diff --check`; commit only task-owned source/docs/evidence-safe files, never checkpoints/rawarchives/tokens.
- [ ] Obtain ONE independent read-only whole-task branch review against execution BASE, spec/plan and Review Focus verbatim, with actual receipts and rulings. Preserve inline method, no per-task agents/model override. Grade findings by effect; one scoped Important/Critical RED→GREEN fix pass plus affected/full regressions; deferredminors/rulings recorded. Do not accept reviewer labels as authority to activate or waive gates.
- [ ] Recheck localmain HEAD/status/index and ownedtaskdiff. Already authorized non-destructive fast-forward into exact recorded target where safe; preserve unfamiliar changes/worktrees and all evidence, no push/publication/cleanup. Rerun relevant contracts/lint/shell on actualmain and fullsuite on affected code; docs-only changes after fullsuite are disclosed, not called newfullruns. Update existingcheckpoint (<80lines) and ledger with exacttechnicalpartial outcome.
- [ ] Report actual v2 archive/scanner binding separately from current release, security, host and human product acceptance. Continue separately authorized protected application bundle design only after this unit; no editablevenv copy or unverifiedhostPython assumption.

## Pre-flight and self-review

- Task1→Task2: stdout exact configdigest/exit0 vs shell single-digest check; expected hostindex/source/role flags identical. Scanner optional flag is introduced by Task2, not assumed in Task1.
- Task2→Task3: standalone16084bf historicalsource is allowed only in retainedarchive checks; full stage still reads cleanHEAD and rejects historicalimages at laterHEAD.
- Coverage: every spec boundary maps to Task1safeTAR/file/JSON/graph, Task2v1/v2/schema/target/gates or Task3actualbytes/source/verification/delivery. Both roles and attestation profile match actual archives; no producer/installation scope.
- Resource constants, field names and function/CLI/shell interfaces agree; fixture hashes come from bytes. Negative graph tests rebind outerhash, so they do not merely test hashing. Each Review Focus line has named negative checks above.
- Raw hashing vs header interpretation is explicit: bounded full-file reads are required, but no parser read/allocation may trust an extension's advertised body length. These are distinct phases, not an exception allowing PAX/GNU expansion.
- Planning evidence: actual retained scans have `os=linux`, `architecture=arm64`; archives have oneimage root, oneARM64 plus oneunknownattestation,15runtime diffIDs/layers and26regular/dirmembers without PAX/GNU extensions. This is profile inspection, not v2 implementation evidence.
- Human approved this presented plan with “그렇다면 이제 개발 모두 진행해줘”; preserved inline method. Execution BASE68c4e4b, local integration target main7f56def; no publication or runtime activation permission.
