# External reconstruction contract v1 — local verification record

Date: 2026-09-06. Scope: first contract slice of
[the release plan](../superpowers/plans/2026-09-06-external-reconstruction-release.md), implementing
the customer-owned-original direction in
[ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md).

## Scope and evidence boundaries

- Additive submission and observed-byte manifest models, two schemas and focused tests.
- Ortho-only submission permitted; DSM and other kinds optional. Original photos stay external.
- Producer declarations, observed bytes, semantic validation and quantitative eligibility remain
  separate. This slice grants neither managed ProcessingJob identity nor source authority.
- No Core upload endpoint, durable import journal, storage operation, semantic raster inspection,
  external analysis eligibility, Console workflow or device execution has been implemented here.
- Release goal `pilot-default-external-reconstruction-release` remains in progress. The contract
  child `external-reconstruction-contract-v1` is independently gated, not a product release.

## Review findings and corrections

Independent task review required and then verified corrections for sealed/nested model mutation,
nullable producer metadata, vertical-basis/schema bounds, strict numeric inputs and canonical
object keys. Follow-up covered numeric timestamp coercion and unchecked nested models with
matching forged digests. Independent integration review found valid timestamp spellings could
produce a digest rejected by the model; digest production now uses the same validated canonical
payload as verification. Test-only type annotations are also included in the static-check gate.

These findings were reproduced before correction. A green suite before the adversarial probes
was not treated as sufficient acceptance.

## Reproduction

Run from the isolated feature worktree. The existing interpreter's editable imports point to
an older worktree, so the explicit current source paths below are required; do not mutate that
other environment or claim its default imports verify the new files.

```bash
env PYTHONPATH="$PWD/packages/event-contracts/src:$PWD/packages/domain/src" \
  /tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m pytest -q \
  tests/contract/test_external_reconstruction_contracts.py \
  tests/contract/test_processing_contracts.py \
  tests/contract/test_repository_normalization.py

env PYTHONPATH="$PWD/packages/event-contracts/src:$PWD/packages/domain/src" \
  MYPYPATH="$PWD/packages/event-contracts/src:$PWD/packages/domain/src" \
  /tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m mypy \
  packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py \
  tests/contract/test_external_reconstruction_contracts.py

/tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m ruff check \
  packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py \
  tests/contract/test_external_reconstruction_contracts.py
git diff --check
```

Final gate: LOCAL PASS — contract slice only.

- Independent task reviewer `external_contracts_review`: PASS; final static check clean.
- Independent integration reviewer `external_release_integration_review`: PASS; previously
  failing schema-valid timestamp/digest probes now pass. No remaining findings.
- Lead current-source import assertions: PASS for event-contracts and domain.
- Lead focused + managed + repository-normalization suite: **110 passed** (45 + 48 + 17).
- Targeted mypy: **no issues in 2 source files**; targeted Ruff and `git diff --check`: PASS.
- Code remains uncommitted in `docs/terrain-aware-pilot-mvp`, base HEAD
  `542fe0a272adfc9c964d3fd871fda3676385aea5`. No dependency or old managed-contract changes.

The native conversation goal could not be replaced because its previous unfinished goal is
still `blocked` and the tool exposes no resume transition. No false completion was used to
bypass this restriction. The helper-managed repository release goal is the active local plan;
native automatic goal continuation has not been established by this work.

## Non-local acceptance

No commit, push, PR, merge, remote CI, deployment, real customer data, device/HIL or field acceptance
was performed. Original main WIP remains unchanged; all new work is isolated and uncommitted.
Next dependent implementation is authenticated Core registration and digest-bound derived-byte
upload/sealing with frozen work-order-cycle provenance, as described in the release plan.
