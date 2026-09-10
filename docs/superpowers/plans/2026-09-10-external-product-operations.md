# External Product Operations Implementation Plan

**Goal:** Complete the human workflow from external observation registration through ownership, deadlines, administrative closure, retained result history, and authenticated sharing.

**Architecture:** Core journals operational metadata independently from the sealed observation version. Dashboard requests authenticated human intent and presents retained source data. Existing acquisition and measurement authority remain unchanged.

**Tech stack:** Existing FastAPI/Pydantic/Core journal and Next.js/React Dashboard, with current locked dependencies and design system.

**Spec:** User approval on 2026-09-10 to implement the remaining product improvements; ADR-KSI-036 and the product authority documents remain canonical. Architecture decisions are retained in the product-operations-20260910 work-state packet.

Requirement IDs: REQ-UX-101, REQ-WRK-101, REQ-INT-101..104, REQ-SEC-101.
Owner module: services/core for durable operational state and scoped history; apps/dashboard for operator flows and presentation; packages/event-contracts and contracts/api for additive contracts.
Acceptance criteria: an authorized operator can claim/release a task, set/clear a deadline, close/reopen it with durable conflict-safe retries; closed work moves to completed history without altering measurement acceptance. Queue and Site views show consistent operational state and actionable in-app due notices. Operators can browse retained site reports, see honest comparable measurements, copy an authenticated exact-report link, and explicitly prepare another observation using existing work areas.
Contracts affected: separate work-order operations projection, operations mutation API, scoped retained report history and exact historical report resolver. No change to sealed WorkOrder.version, cycle, acquisition, Mission, or measurement evidence.
Reference assets: existing journal patterns, external result historical resolver, Site workspace, Field work queue, shared controls and design-system/ksi-operations-console/MASTER.md. No reference repository modification or runtime import.
Adoption decisions: self-assignment uses the authenticated principal because no authoritative team directory exists. Notifications are derived within the product; link sharing preserves authentication and grants no permissions. Repeat observation is an explicit human action using current active areas, not autonomous acquisition scheduling. Spatial visualizations require actual spatial data; aggregate volumes are plotted only as measured aggregates.
Files to change: Core observation_work_orders.py and focused operations module/schema/router/tests; external_result_workflow_api.py and retained history tests; site_workspace.py where operational joins are needed; openapi-core.yaml; Dashboard core client/types, BFF routes, Field work detail/queue and next-action resolver, Site result/history/report components, exact link resolver and tests. SiteRegistrationOnlyWizard may simplify generated identifiers while preserving coordinate and consent declarations.
Tests: targeted failing behavior tests before implementation; restart/idempotency/concurrency/tenant/human-permission checks; no sealed-version or device-journal mutation; close/reopen queue projection; history exact identity and unavailable authority; client conflict recovery and stable retry intent; time-zone deadlines and accessible actions; relevant Python contract/replay suites, Dashboard tests, TypeScript/lint/build; independent frozen-diff review and actual local synthetic browser flow.
HIL or real-device assumptions: none. Local synthetic fixtures do not prove production, field, or measurement-worker acceptance.
License/data implications: no new dependencies or customer datasets; no external messages, anonymous reports, credentials, or public data publication.
Rollback: restore only this packet's preimage-verified owned changes; no resets, journal deletion, or alteration of previous WIP.

## Invariants

- INV-017/024/053: closure is administrative, not measurement or accuracy approval; only authority-resolved compatible metrics are compared.
- INV-018/020/051: preserve observation version, epoch, capture time, CRS/vertical datum and all sealed provenance.
- INV-040/060: no production mocks; all reads/writes are organization-scoped and permission-checked; unavailable operations/history must not silently become open/empty/zero.
- INV-061/002: explicit human intent only; no new executable Mission or acquisition authority.
- INV-050: Site onboarding retains explicit data-egress declarations and coordinate/height confirmation.

## Task 1: Durable work operations

- [ ] Before each existing-file edit, save bytes under packet preimages and verify SHA256 against baseline.json.
- [ ] Add a separate operations projection with revision 0 UNSPECIFIED legacy default, OPEN/CLOSED explicit status, authenticated assignee, dueAt, closure note and audit timestamps. Persist full snapshots and hashed idempotency bindings in the existing ordered journal without updating the observation model.
- [ ] Add explicit authenticated assignment, deadline, close and reopen routes. Require expected operations revision and stable idempotency key; same request replays the retained response, differing input conflicts, stale revision cannot overwrite.
- [ ] Add efficient scoped bulk reads for queue/site projections. Managed operations remain unchanged; source failure is visible.
- [ ] Enforce closure against new external registration/measurement intent at the existing coordinated boundary while allowing retained in-flight receipt/sealing completion. Closure never cancels or accepts measurement work.
- [ ] Demonstrate journal restart, concurrent edits, scoped 404, operator permission, execution guard preservation and unchanged sealed version.

## Task 2: Operator workflow and notices

- [ ] Implement an accessible work operations panel with claim/release, local-time deadline, close note, close/reopen feedback and conflict refresh that preserves operator input.
- [ ] Join operations into work queue, Site and next-action views. Closed tasks count as completed administrative work and disappear from active actions; labels state 업무 종료.
- [ ] Show derived overdue/due-soon/my-work notices with direct task links, clock-consistent filtering and no notification transport.
- [ ] Test closed/open transitions, lost-response retries, stale edits, permission-disabled actions, unavailable source, and time-zone round trips.

## Task 3: Retained history, comparison and sharing

- [ ] Expose bounded site-scoped report history using the existing historical authority resolver; retain unavailable entries instead of falling back or inventing values.
- [ ] Add a Site history page with exact dates, area names, measurement state, coverage/uncertainty and exact report navigation. Link from Site data and reports.
- [ ] Show measured cut/fill/net trends only within identical comparison compatibility groups; display limits and a readable table alongside visualization. No fabricated spatial maps.
- [ ] Resolve shared historical links by site/order/report identity and digest rather than latest-only projection. Copy the exact authenticated link with explicit success/failure feedback; existing login return and print behavior remain intact.
- [ ] Add an explicit next-observation entry that reuses valid active areas and sends a fresh, human-confirmed idempotent external create request. Preserve approved proposal-successor semantics separately.
- [ ] Test cross-site/order mismatches, stale or unavailable retained authorities, historical login return, clipboard failure and compatible/incompatible measurement presentation.

## Task 4: Registration and integration

- [ ] Generate a stable optional Site identifier once per saved draft, retaining user overrides and existing drafts. Preserve retry identity, CRS, height and egress consent.
- [ ] Run affected tests and full Dashboard checks; freeze actual changed-file manifest and baseline-relative diff.
- [ ] Obtain independent review of the frozen source and correct confirmed findings with the same writer.
- [ ] Lead checks final hashes and runs the local synthetic create/claim/deadline/close/reopen/history/share journey, then stops only owned fixtures and restores generated configuration changes.
- [ ] Record shipped local capabilities and remaining external/team-directory/field limitations without claiming product-wide production completion.

No commit, push, PR, merge, deployment or device action is part of this plan.
