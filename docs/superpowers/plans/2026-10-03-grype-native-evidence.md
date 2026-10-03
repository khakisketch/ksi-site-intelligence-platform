# Native Grype runtime scanner evidence implementation plan

> For agentic workers: use `executing-plans` for local implementation. Steps use checkbox tracking.

**Goal:** Consume genuine Grype0.120.0 reports in the strict runtime gate without rewriting originals.
**Architecture:** A stdlib verifier reads and validates one exact payload; the existing stage passes
artifact metadata and verified runtime config ID. Legacy scanner compatibility is retained.
**Tech stack:** existing Python3, Bash/jq, pytest; no new dependencies.
**Spec:** [approved native-consumer design](../specs/2026-10-03-grype-native-evidence-design.md).
**State:** written spec approved by Human; this written implementation plan awaits review.

## Global constraints and implementation packet
- Requirements: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 preparation only.
- Owner: deployment lifecycle scanner consumption and focused offline tool/tests.
- Acceptance: genuine native reports accepted only with their exact byte/config-image binding;
  malformed/substituted/unknown native documents fail; legacy strict reports remain compatible.
- Contracts affected: extend scanner content consumption only; canonical/host v1 wire fields unchanged.
- Invariants: INV-054 through existing source/registry binding plus raw report/config binding;
  preserve INV-051/053/055/060, no policy/credential/customer data or quantitative decisions.
- Reference assets/adoption: existing KSI safe release readers, shell consumer and captured Grype0.120.0 shape.
- Files: tool/tests/stage and the existing runtime/release/local-verification docs named below.
- HIL/device: none; tests use labeled fixtures and preserved reports, never activate a daemon.
- License/data: no private/customer uploads; full raw findings retained, no native report modification.
- Rollback: prior scanner consumer/source remains recoverable; preserve all original evidence.
- Only native supported profile: Grype0.120.0, DBv6.1.10; DB schema is not report schema.
- Maximum scanner JSON16MiB; no duplicate keys/nonfinite values/symlinks/path substitution.
- No scanner execution, new envelope, inferred DB hash, tool authenticity or release/security verdict.

## Review focus
- Native rejection falls through to legacy: G1 pins disjoint families, unsupported native always fails.
- OCI/synthetic manifest confused with config: G2 passes actual host-verified Docker ID, not index digest.
- Same path swaps between hash and parse: G1 reads/hashes/parses one protected descriptor payload.
- Honest zero findings rejected or ignores silently dropped: G1 validates full arrays without policy decisions.
- Parser success skips another gate: G2/G3 retain all source/registry/host/authority prerequisites.

### G1 — One-payload native/legacy verifier
**Create:** `tools/verify_external_scanner_evidence.py`,
`tests/contract/test_external_scanner_evidence.py`.
**Interfaces:**
- `ScannerEvidenceError(ValueError)` exposes safe reason code.
- `verify_scanner_evidence(path: Path, *, expected_sha256: str, expected_bytes: int,
  expected_image_id: str | None) -> str` returns `legacy` or `grype-0.120.0` on validation only.
- `main(argv: Sequence[str] | None = None) -> int`: CLI requires `--path`, `--sha256`,
  `--bytes`, accepts `--image-id`; exit0 on valid, nonzero with safe error otherwise.
  Missing image identity is permitted only for existing legacy compatibility, never native.
- [ ] Write `test_legacy_and_native_reports_are_disjoint_and_byte_bound`: valid legacy passes;
  labeled native0.120.0 fixture with exact config ID/hash/bytes passes; wrong ID/hash rejects;
  original file bytes remain equal. Import from tools using existing owner-test pattern.
- [ ] Run RED: `UV_NO_SYNC=1 UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q tests/contract/test_external_scanner_evidence.py`.
  Require failure because verifier is missing, not broken unrelated imports.
- [ ] Implement normalized absolute descriptor-relative O_NOFOLLOW directory/file read; reject
  nonregular/empty/>16MiB files; fstat before/after, exact supplied size/hash; parse same bytes with
  duplicate/nonfinite/UTF8/root rejection. Do not dereference embedded report paths or URLs.
- [ ] Implement exact native/legacy predicates from the spec, including full matches/ignored arrays,
  supported version/DB objects/source type/config identity. No fallback for mixed/malformed native.
- [ ] Add parametrized tests for every native field rejection, zero matches, preserved ignored
  matches, duplicate/NaN/UTF8 errors, oversized/nonregular/symlink parent/leaf and changed-read
  identity. Add CLI tests for positive validation and non-secret diagnostics/exit failures.
- [ ] Run GREEN and prepared `.venv/bin/ruff check` for the two files; require zero failures/errors.
  Inspect scoped diff/index and commit the verifier/tests.

### G2 — Strict runtime stage integration
**Modify:** `deploy/bin/external-runtime-stage.sh`,
`tests/contract/test_external_runtime_deployment_contract.py`.
**Interfaces:** extend `verify_artifact_binding(path, sha256, bytes, type, strict=0,
expected_image_id="")`; strict scanner delegates to G1 with the actual runtime image ID.
`require_release_evidence` passes its already image/RepoDigest-verified runtime `image_id`.
Generic Core/Dashboard and other artifact behavior stays unchanged.
- [ ] Write `test_runtime_scanner_accepts_native_grype_only_with_exact_image_binding`: source
  existing stage functions, valid raw native fixture with sixth image argument succeeds;
  missing/wrong ID/unknown native/mixed representation reject, old strict fixture stays valid.
- [ ] Run RED for that test against the old stage (native report rejected).
- [ ] Update only strict scanner branch and its two-role caller; delegate before any path-based
  preliminary hash reread, so G1 hashes and validates the same descriptor payload. Reuse existing
  python3 prerequisite, fail closed if verifier unavailable; never execute report instructions.
- [ ] Extend existing release/host shell fixture test to native runtime reports; changed report,
  config ID and RepoDigests remain rejected. No Docker/Compose/host action beyond its test stubs.
- [ ] Run focused tests GREEN plus `bash -n deploy/bin/external-runtime-stage.sh` and existing
  deployment/release/runtime pin tests; inspect scoped diff/index and commit.

### G3 — Genuine retained reports, docs and local integration
**Modify:** `deploy/external-runtime/README.md`, `docs/ops/RELEASE_EVIDENCE.md`,
`docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md`, existing contained-runtime task record.
**Interfaces:** consumes G1/G2 plus retained original reports/OCI identity receipts; no producer envelope.
- [ ] Run verifier and sourced strict-stage function on both unchanged real repaired Grype files
  with actual raw hash/size/config IDs from retained receipts; each valid input passes and each
  swapped role/config/hash fails. Retain logs privately; do not fabricate a host release record.
- [ ] Document native profile/legacy compatibility, DB/report and config/manifest distinctions,
  separate tool/DB/security review, and no change to release/source/registry/socket/authority gates.
- [ ] Run complete new verifier and existing deployment/release tests, Ruff, shell syntax and
  suitable existing mypy check; read-only review of the task diff/evidence and scoped fixes.
- [ ] Commit docs; recheck authorized clean main target, integrate verified task commits and rerun
  affected checks there. Report parser compatibility only; no activation, registry push or raw rewrite.

Self-review: G1 covers native/legacy/safe-file requirements, G2 exact existing consumer integration,
G3 actual preserved byte evidence/docs and remaining gates. Interface names/arguments agree in
all tasks. Bundle packaging is a separate later unit, not an implied supplier/authority substitute.
