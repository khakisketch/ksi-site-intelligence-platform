# External Observation Product UX Implementation Plan

**Goal:** Let a customer start an external observation, upload its artifacts, find its results in the Site, understand the comparison, and continue the next human task.

**Architecture:** Dashboard owns intent, navigation and presentation. Core owns creation, durable execution restrictions, epoch identity, retained reports and all authorization. Existing managed acquisition and external successor authority remain distinct.

**Spec:** User-approved findings in `/home/ksi/.codex/work-state/ksi-external-product-loop/ux-product-audit-20260909/product-flow-review.md`; ADR-KSI-036 and REQ-UX-101 remain authoritative. Use the same worktree and do not commit/push/deploy.

Requirement IDs: REQ-UX-101, REQ-INT-101..104, REQ-WRK-101, REQ-SEC-101.
Owner module: apps/dashboard; narrowly additive Core WorkOrder creation/context contracts when required.
Acceptance criteria: an external observation can start without Mission issuance; existing Site/WorkArea context is reused; exact external results are discoverable from Site data/report navigation; upload states are understandable; result/review/next actions retain exact report/proposal identity; unavailable/partial/forbidden states stay distinct.
Contracts affected: initial external WorkOrder creation and context only after architecture packet resolves its exact shape; existing external submission capture interval and external result projection consumed without promoting them to managed state.
Reference assets: existing SiteRegistrationOnlyWizard, shared Field/buttons/ResponsiveActionBoundary, external panels, result projector and tests. No reference-repository edits/imports.
Adoption decisions: retain design-system/ksi-operations-console/MASTER.md and globals.css as canonical visual/behavioral context; reuse Korean formatting and shared controls. No new palette, font, home redesign or duplicate design contract.
Files to change: Dashboard field/page.tsx, field/work-orders/[workOrderId]/page.tsx, field/ExternalReconstructionPanel.tsx, field/ExternalEvidencePanel.tsx, field/ExternalResultWorkflowPanel.tsx; Site page/header/report; reusable external result summary and exact result page; new observation create page/form and BFF/client; external submission builder; associated tests. Narrow Core creation/context/schema/tests are gated by the recorded architecture decision before those edits.
Tests: failing behavioral tests before features; creation permissions/idempotency/replay/no-device guards; exact cross-site report links, unavailable metrics and stale request isolation; upload cancel/resume/capture declaration; tsc, targeted lint, full Dashboard tests/build and affected Python contract/replay tests; independent combined review and local browser flow.
HIL or real-device assumptions: none; local synthetic data only, no Mission/device action or readiness claim.
License/data implications: no new dependencies, datasets, external upload/sharing or credentials.
Rollback: restore only the owned diff against packet baseline; retain unrelated dirty WIP and historical journals; no destructive reset.

## Invariants and enforcement

- INV-017/024/053: show only Core-retained metrics and limitations; no client-generated eligibility or accuracy.
- INV-018/020/051: preserve sealed capture time, epoch, CRS/vertical and source bindings. Missing values stay unknown.
- INV-040/060: no production mocks; authentic scoped reads and permission-gated mutations; source failure is not zero results.
- INV-061/002: user review/approval remains explicit; external creation never supplies device authority.

## Task A: Customer observation entry

- [ ] Resolve initial external creation vs successor binding in the read-only architect packet before editing this contract.
- [ ] Add a <=5-step user flow accessible from Site and work queue. Reuse saved WorkAreas; empty WorkAreas link to registration. Separate upload intent from existing flight planning. Core-issued identity, declared capture interval, disabled duplicate submit and retained retry identity are required.
- [ ] Test and implement server restrictions and replay if a new initial external intent is needed; never manufacture a successor approval record.
- [ ] Connect successful creation to the owning work detail/upload state, with scoped name/date labels and no managed execution controls.

## Task B: Site external results and reusable report presentation

- [ ] Write tests proving Site data/report sections expose available externalResult and preserve NO_RESULT/NOT_CONFIGURED/HISTORICAL_SOURCE_UNAVAILABLE distinctions.
- [ ] Implement a shared external summary plus exact scoped result route/deep link. Keep managed data separate; source failure cannot suppress an independently available external result.
- [ ] Present dates/WorkArea, cut/fill/net, coverage and defined uncertainty above expert identifiers. Use only observed geometry/artifacts for maps; do not fabricate a heatmap from aggregate metrics.
- [ ] Provide human-readable report/return-to-Site/next-task navigation with the same report binding. Do not claim arbitrary site history when only the latest projection exists.

## Task C: Upload, review and detailed interaction improvements

- [ ] Preserve upload state machine, frozen attempt identity, cancel/resume and byte binding while showing file check/upload/recorded/inspection states in user language.
- [ ] Accept explicit capture interval through the existing declaration contract; never substitute upload time or a whole-day interval for actual capture evidence.
- [ ] Improve comparison selection, result labels, Korean dates/units, primary vs secondary actions, and current request vs historical deadline wording.
- [ ] Preserve exact proposal/receipt binding while giving clear review completion and report/next-observation choices. Show honest bounded unavailable recovery rather than technical instructions.
- [ ] Simplify existing Site registration identifiers/expert fields only where the existing contract allows; preserve coordinate/height confirmation and data-egress consent.

## Task D: Integration and handoff

- [ ] Freeze a manifest, run targeted validation and full Dashboard checks, receive independent reviewer PASS, fix findings with the same writer.
- [ ] Lead verifies final owned hashes, impacted integrated checks and browser navigation; preserve pre-existing files and stop owned fixtures.
- [ ] Record implemented flows and explicit residual capabilities. Automatic schedules, external sharing permissions, new terrain/planner semantics and backend capabilities absent from current contracts are not silently created by UI labels.
