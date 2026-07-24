# KSI Site Intelligence Agent Instructions

## Authority

Read in this order:

1. `docs/00_READ_FIRST.md`
2. `docs/product/PRODUCT_CONSTITUTION.md`
3. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
4. `docs/product/MASTER_PRD_v3.0.md` and relevant section
5. Relevant contract/schema
6. Acceptance criteria
7. Reference adoption matrix
8. Reference code

## 도메인 불변식

정본은 `docs/product/DOMAIN_INVARIANTS.md` (INV-xxx)다. 여기 복제하지 않는다.
구현·리뷰·감사는 해당 문서의 불변식 ID로 대조한다.

## Reference repositories

- `references/repos/ksi-platform`
- `references/repos/ksi-terra`
- `references/repos/ksi-scout`

They are read-only reference implementations, not product authority.

Never import runtime code directly from `references/`.
Never modify a reference submodule unless the task explicitly says `UPDATE_REFERENCE_PIN`.

## Required implementation plan

Before code changes, state:

```text
Requirement IDs:
Owner module:
Acceptance criteria:
Contracts affected:
Reference assets:
Adoption decisions:
Files to change:
Tests:
HIL or real-device assumptions:
License/data implications:
Rollback:
```

## Control boundaries

- Manifold owns tactical perception, tracking, local world model, risk, active perception and local mission decisions.
- DJI Flight Controller owns stabilization, low-level flight, verified reactive avoidance and RTH.
- Core owns signed Mission Contract, policy, map/model versions and workflow.
- LLM must not emit executable flight coordinates or bypass safety policy.
- Server loss must not invalidate a locally valid Mission Contract.

## Quality

Do not claim completion from mocks, imports or unit tests alone.
Use contract tests, replay tests and real-device/HIL gates where applicable.
Unknown facts and unverified DJI behavior must remain explicit.

## Claude Code behavior

Use repository search before proposing new abstractions.
Keep a brief working plan in the task response.
Do not edit files under `references/repos/`.
