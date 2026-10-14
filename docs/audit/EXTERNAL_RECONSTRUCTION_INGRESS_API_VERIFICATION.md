# External reconstruction ingress API verification

## Scope and authority

This audit records local software evidence for the bounded Slice 2 Core API described by
[ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md) and the
[external-reconstruction release plan](../superpowers/plans/2026-09-06-external-reconstruction-release.md).
It is evidence, not product or current-state authority. The historical helper record is archived at
[`docs/archive/ksi-legacy-2026/goals.json`](../archive/ksi-legacy-2026/goals.json); it does not make a
current decision. `docs/superpowers/product-state.md` and its named slice ledger own the current
product slice, Backlog, and product-level next-work selection only when no active bounded checkout
task exists. An active checkout task resumes through the revalidated checkpoint and named task
ledger; this audit supplies evidence only.

Evidence was collected in `/tmp/ksi-flight-planning-design.wdFlvL/worktree` from base HEAD
`542fe0a272adfc9c964d3fd871fda3676385aea5`. The worktree intentionally contains uncommitted
multi-task WIP. No commit, push, merge, deployment, credential change, customer data, vendor call,
or device action occurred for this evidence.

## EXT-API acceptance evidence

| ID | Source and test evidence | Local result / limit |
| --- | --- | --- |
| EXT-API-01 | Core [route/store](../../services/core/src/ksi_core/external_reconstruction.py); [ortho-only/DSM and opaque-reference API tests](../../tests/contract/test_external_reconstruction_api.py) | Registration and byte sealing do not create a raw bundle, `ProcessingJob`, or managed profile. Ortho-only/DSM and returned `submissionRef` behavior are local software evidence, not semantic validation. |
| EXT-API-02 | [Scoped resolver/routes](../../services/core/src/ksi_core/external_reconstruction.py); [cross-tenant, unknown-ref, and denied-principal tests](../../tests/contract/test_external_reconstruction_api.py) | Principal-derived organization/site/cycle/actor scope and non-disclosing unknown/cross-tenant opaque-ref behavior are tested locally. This is not production identity-provider acceptance. |
| EXT-API-03 | [Revision state machine and replay-derived ref index](../../services/core/src/ksi_core/external_reconstruction.py); [revision and special-ID API tests](../../tests/contract/test_external_reconstruction_api.py); [collision fail-closed replay tests](../../tests/replay/test_external_reconstruction_replay.py) | Revisions retain raw customer IDs in durable identity while clients use a stable server-returned ref. Accepted slash, percent, dot, suffix-like, and Korean IDs are exercised; a collision fails closed. No cross-journal global-linearizability claim is made. |
| EXT-API-04 | [Digest-bound grant/seal implementation](../../services/core/src/ksi_core/external_reconstruction.py); [loopback boto3 PUT/HEAD/restart E2E](../../tests/e2e/test_external_reconstruction_upload_flow.py); [storage-failure and observation-mismatch tests](../../tests/replay/test_external_reconstruction_replay.py) | The synthetic loopback includes returned-ref addressing and local direct PUT/HEAD behavior. It is not AWS/MinIO authorization interoperability, object-lock, or permanent byte immutability. Already-issued URLs are not revoked; seal is point-in-time observation. |
| EXT-API-05 | [Strict replay and opaque-ref recovery](../../services/core/src/ksi_core/external_reconstruction.py); [restart, old-event ref derivation, forged-event, append-failure, and manifest-tamper tests](../../tests/replay/test_external_reconstruction_replay.py) | Local durable-journal replay restores stable refs without journal migration and rejects tested malformed/forged transitions. Its digest is an integrity binding, not unkeyed tamper authentication. |
| EXT-API-06 | [OpenAPI five-route contract](../../contracts/api/openapi-core.yaml); [assembly wiring](../../services/core/src/ksi_core/app.py); [shared assembly (archived)](../../archive/acquisition-2026/services/core/src/ksi_core/app_assembly.py); [conformance and assembly tests (archived)](../../archive/acquisition-2026/tests/contract/test_api_contract_sync.py) | Registration/list/detail expose `submissionRef`; detail/grant/seal accept only it, with no raw-route fallback. Routes require supported shared storage assembly; this is local conformance evidence, not a deployed service. |
| EXT-API-07 | Historical machine-local paths unavailable in this checkout: `../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/task-1-report.md`, `../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/submission-ref-task-review.md`, and `../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/submission-ref-verification.md`; and this audit | The corrected Task 1 review was reported PASS in unavailable historical artifacts; it is not current acceptance proof. Final documentation/integration review and helper-goal decision remain Lead-owned separate gates; this audit does not announce either verdict. |

## Current execution evidence and historical supersession

The prior 324-test worker/verifier and 389-test Lead runs predate the submission-ref correction and
are historical only; they are not current acceptance evidence. The current worker ran the prescribed
nine-file suite with the corrected opaque-reference code and retained JUnit evidence:

```bash
env PYTHONPATH=services/core/src:packages/event-contracts/src:packages/domain/src \
  /tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m pytest \
  tests/contract/test_external_reconstruction_contracts.py \
  tests/contract/test_external_reconstruction_api.py \
  tests/replay/test_external_reconstruction_replay.py \
  tests/e2e/test_external_reconstruction_upload_flow.py \
  tests/contract/test_api_contract_sync.py \
  tests/contract/test_hostile_input_route_coverage.py \
  tests/contract/test_validation_error_rendering.py \
  tests/contract/test_dev_assembly.py \
  tests/contract/test_production_assembly.py -q \
  --junitxml=.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/integration-fix2-pytest.xml
```

Worker-reported result: `339 passed, 1 known warning in 40.67s`. Its retained JUnit records 339
tests, zero failures, zero errors, zero skips, and 40.620 seconds. The warning count is reported
separately because JUnit does not encode it. This is worker evidence, not an independent full rerun.

The independent Task 1 reviewer first inspected the corrected source with 16 focused checks, then
executed the latest three opaque-reference tests (`7 passed, 1 known warning in 0.64s`), Ruff on
the changed API test, and `git diff --check`; its reported PASS review at historical machine-local
path `../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/submission-ref-task-review.md`
(unavailable in this checkout) explicitly covered special customer IDs, all-three raw-ID route refusal, unknown valid-shaped refs,
and fail-closed collision handling. It did not independently rerun the full nine-file suite.

The independent verifier's current refresh ran API, replay, and real loopback HTTP flow tests
(`60 passed, 1 known warning in 5.33s`), Ruff/mypy on 11 files, and current-import checks; its
reported verification at historical machine-local path
`../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/submission-ref-verification.md`
(unavailable in this checkout) labels the prior 324-test verifier run historical. This is distinct from the worker's 339-test run
and is not a verifier full-suite rerun.

The Lead independently reported running the current 11-file suite below and retained the historical
machine-local artifact `../../.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/lead-ref-final-pytest.xml`
(unavailable in this checkout):

```bash
env PYTHONPATH=services/core/src:packages/event-contracts/src:packages/domain/src \
  /tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m pytest \
  tests/contract/test_external_reconstruction_contracts.py \
  tests/contract/test_external_reconstruction_api.py \
  tests/replay/test_external_reconstruction_replay.py \
  tests/e2e/test_external_reconstruction_upload_flow.py \
  tests/contract/test_api_contract_sync.py \
  tests/contract/test_hostile_input_route_coverage.py \
  tests/contract/test_validation_error_rendering.py \
  tests/contract/test_dev_assembly.py \
  tests/contract/test_production_assembly.py \
  tests/contract/test_processing_contracts.py \
  tests/contract/test_repository_normalization.py -q \
  --junitxml=.superpowers/sdd/2026-09-06-external-reconstruction-ingress-api/lead-ref-final-pytest.xml
```

Lead-reported result: `404 passed, 1 known warning in 41.25s`. The retained JUnit records 404 tests,
zero failures, zero errors, zero skips, and 41.246 seconds. This is current local test evidence only.

## Remaining boundaries

Registration and sealing are not semantic raster validity, accuracy, raw-source authority, managed
ProcessingJob/profile identity, analysis eligibility, or flight acceptance. External-comparison
compatibility, Console, customer export compatibility, retention/resource deployment, remote CI,
deployment, vendor/field acceptance, and detailed validation/compatibility policy remain release
work. No original upload, vendor integration, or license promise is introduced. The complete
release sequence remains [in progress](../superpowers/plans/2026-09-06-external-reconstruction-release.md).
