# First Customer Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans for inline development. Checkboxes record evidence, not product acceptance.

**Goal:** Finish the existing scoped customer analysis/data workflow and obtain the evidence required for a first repeatable customer pilot.
**Architecture:** Reuse Core identities, existing V1/V2 results, inspection/measurement workers, public HTTP and current Dashboard. Fix actual missing resource checks before enabling audited customer reads. Keep operations, real samples and human acceptance separate from local software.
**Tech Stack:** Existing Python/FastAPI/httpx/pytest, Next Dashboard and Local Codex; no installation or dependency changes.
**Spec:** PRD §1.1.1/1.1.2, ADR-KSI-036/037/038, SDP-20260930, FPC-20260928 and existing Dashboard experience ledger.

## Authorization and workspace
- Human: “다음 모두 개발 개선 해줘 제품을 완성하기 위해 필요한 것들이잖아” authorizes pursuing the stated completion work, not merely cosmetic/client polish.
- Existing current checkout `main`, base/integration target `6b27225ed58be569c8deea1c860185199950e3cc`; clean at start. One writer, no new worktree needed.
- Routine local code/tests/review/commits are authorized. No main push/PR/deploy, live grant/account/policy/signature change, equipment/customer contact or implicit operations-goal resume.
- No native goal was created: ordinary completion request is not goal-mode authorization.
- Completion must distinguish implemented, independently verified, operationally exercised and customer-accepted; EXT-VAL/P-AC stay open until their actual acceptance gates.

## Execution tracks (sequential within each shared-file owner)
- [x] C1 Customer observation-history resource-scope contract, security review and HTTP implementation (local technical scope; full-product/customer acceptance remains open).
- [ ] C2 Related report/detail navigation scope and actual scoped browser workflow; no ADMIN fallback.
- [ ] C3 Remaining Dashboard items: reconcile actual defects, Local Codex source implementation and distinct rendered review, then product-browser verification. Do not mechanically redo 13 checked items.
- [ ] C4 Reconcile exact release/runtime evidence and finish safe local verifier/recovery/tooling gaps. Host/account/deployment/signing changes require separately scoped authorization.
- [ ] C5 Real-data compatibility and repeated-use evidence: actual permitted t0/t1/t2, coordinates/vertical/producer/rights, selected customer OIDC/MCP, resource/cost measurements. Missing inputs block acceptance, not independent engineering.
- [ ] C6 Backup/restore and operational failure drills, independent customer use and named acceptance. Simulated drills do not establish deployed recovery.
- [ ] C7 Platform successors: specify feed/resync, data MCP and external-result provenance when selected requirements exist; no guessed wire/model/authority contract.

## C1 required implementation declaration / conservative read contract
- Requirement IDs: SDP-REQ-05/06/07/08, REQ-SEC-101, REQ-UX-101/A2, EXT-VAL-05/08.
- Owner module: Core external workflow read projection and identity route gate.
- Acceptance: scoped Site/WorkArea OIDC user sees only bound readable report history; same-org ungranted/foreign/missing Site is indistinguishable404; invisible rows/cursors/counts never leak; ordinary mutations and worker routes stay closed.
- Contracts affected: additive explicit Principal scope on internal history projection, existing GET response shape unchanged. Only the mixed Site history GET is the first allowlist candidate; report detail aliases/mutations need their own resource audit before opening.
- Reference assets/adoption: REUSE existing report-family stores, projector, scoped WorkOrder/WorkInbox predicates, OIDC verifier and generated fixtures. No reference imports or new identity store.
- Files to change: `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py`, `services/core/src/ksi_core/identity/auth.py`, new `tests/contract/test_oidc_external_history_scope.py`, nearest README/API documentation as required; this ledger/checkpoint. Existing numerical stores/results untouched.
- Tests: real mounted router and signed test OIDC JWT; positive history, empty grants, unknown/foreign Site, hidden cursor, filtered-before-pagination, missing/multi-area source orders, stale source binding, unchanged unscoped behavior and POST/internal denial. Independent review before customer GET activation; independent final tests and actual browser later.
- HIL/device: none. Fixture measurement/provider identities are generated software evidence only.
- License/data: no live keys/customer exports; test credentials and journals only.
- Invariants: INV-060 organization/Site/all-WorkArea provenance scope; INV-040 unknown source fail-closed; preserve INV-051/053/054/055/061 and V1/V2 numerical meaning.
- Rollback: task-owned commit revert only if requested; never mutate existing journals or grants.
- Read rule: restricted users require a proven exact report/result/zone and Core source WorkOrder binding. Relative reports require current and baseline source bindings; single-volume reports require current binding. Each order must match authenticated organization, requested Site, nonempty assigned areas and all those areas inside the user's explicit grants; zone must be granted. Unprovable rows are hidden, not exposed as unavailable placeholders. Unrestricted historical behavior remains unchanged.
- Filter authorized references before `after` lookup, slicing and `nextCursor`; hidden/foreign/absent cursor returns the existing generic404. No hidden totals or latest-result fallback.
- Do not infer authority from report IDs or body fields. History metadata is not approval, accuracy certification, data-download permission or flight authority.

## C1 steps / review focus
- [x] Write failing mounted-OIDC tests for positive200 vs current403; scope negatives, cursor/pagination and preserved unscoped paths.
- [x] Observe RED with expected route/resource behavior, not import failures.
- [x] Implement scope predicate/projection filtering while route remains closed; review actual retained-source and proposal metadata paths independently.
- [x] After no security blockers, add the one audited GET template; observe GREEN and denial regressions.
- [x] Run affected workflow/auth/history tests, tests-directory Python suite and static checks independently; record exact revision/hashes/logs. Bare repository pytest includes additional configured paths and remains a final combined-bundle check.
- [ ] Verify actual scoped Dashboard history flow with real HTTP/OIDC before closing A2/C2; any visual work remains Local Codex-owned.
- [ ] Preserve task-owned local commit; record what is technically complete versus customer/operational acceptance.

## C1 security review — contract decision gate
- Independent read-only reviewer `ses_ef09090afffeFp3vLpuUrYIMkb` examined actual projector,
  report stores/resolve, auth, WorkOrder/WorkInbox and current scope patterns. No tests run and
  no implementation/allowlist changes yet. This is design evidence, not reviewer approval authority.
- Confirmed existing route remains403-closed for scoped OIDC; organization-only historical
  enumeration and unavailable row placeholders would disclose other areas' report references.
- Initial review raised `_review_join` proposal/approval counts without target-area scope.
  Follow-up actual service + durable producer tracing CORRECTS this hypothesis: both
  `_target_matches_review` and `proposals.create` require the exact sealed report-zone target;
  another area is rejected409 (`EXTERNAL_REOBSERVATION_TARGET_NOT_REPORT_ZONE`). There is no
  valid independent target-area disclosure under this contract. Verify replay/final review too.
- Confirmed cursor must resolve exclusively within the authorized sequence; hidden refs cannot
  be admitted as cursors or used to calculate nextCursor.
- Confirmed empty assigned-area sets must fail restricted reads (not vacuous subset success),
  baseline and current WorkOrders must both be verified for relative reports, and unknown bindings hidden.
- Review's whole-operation coordinator recommendation requires further implementation tracing:
  `resolve_historical_report_ref` explicitly resolves independent historical authority outside
  coordinator/store locks. Do NOT blindly put an external/provider call inside guarded_read;
  preflight frozen witnesses outside locks and revalidate connected local state inside the guard.
- Proposed user decision batch (recommended conservative customer read semantics):
  1. Only exact organization/Site/zone plus nonempty all-area grants for current and baseline source
     WorkOrders; unprovable/cross-scope reports hidden before cursor/paging, no unavailable placeholder.
  2. For a readable report, expose only downstream proposals whose complete target-area set is
     granted; history counters explicitly mean the current user's visible proposal/approval counts.
     Unrestricted callers and immutable numerical/historical records retain their existing meaning.
  3. Archived areas do not erase readable retained history while explicit grants remain; archive
     grants no new execution/approval authority. Changed/missing source bindings are hidden.
- Human selected “권장안 적용 (Recommended)” for the exact three-item batch on2026-10-06.
  Source/zone/all-area filtering, visible-only workflow counts and retained archived-history reads
  are approved. Implement now; no blanket GET/ADMIN fallback or live grant changes.
- Test-only fixture helper `_sealed_source` may add an optional baseline WorkOrder argument with
  its existing default preserved, to build a genuinely bound synthetic baseline/current pair.
- Query resource envelope needs existing budget/owner configuration evidence before a numeric
  scan cap is fixed. Do not invent an operational scan limit from the50-row response page size.
- C2 detail routes and already-allowlisted registration-context projections also need their own
  cross-source and downstream-metadata audit; C1 must not imply blanket result/workflow read authority.
- At initial audit, independent UI execution prerequisite was unverified exact-folder linkage;
  subsequently resolved below without cancelling unrelated runs. Backend work did not depend on it.

## Current execution state
- C1 read semantics approved. Initial projector RED6fail1pass after fixing fixture errors,
  GREEN scoped+workflow12pass; proposal/archived regressions plus workflow14pass on resume.
- Signed FIELD_OPERATOR/OIDC actual mounted router RED6fail13pass, all six fail on current403
  missing mixed-history permission. Log `/tmp/opencode/customer-history-http-red-20261006.log`.
- Scope filtering + exact-witness projection implemented; providers outside coordinator,
  local source/grants/projection joins inside. Independent resource audit completed below;
  exact one audited history allowlist entry added, others stay closed.
- Ruling: retain proposal counts because every durable proposal is bound to the readable report's
  exact zone — service rejects another target409, valid same-zone proposal201. This implements
  visible-only counts without inventing a new counter schema or unsupported hidden-target state.
  Cost if wrong: metadata disclosure; independent replay/source review is required before opening.
- Independent actual implementation audit `ses_ef0863522ffe4ec1x6wkvg17Q3` found three preconditions:
  avoid all-provider/full-coordinator pre-pagination scanning; open exactly one route; cover single
  family scope. Confirmed exact-zone proposal producer/review/approval constraints; no valid other
  target should be filtered arbitrarily. Crafted/legacy replay target equality remains a deferred
  read-hardening minor, not evidence of a reachable authenticated cross-zone producer.
- Ruling: take review alternative(b), cursor-aware incremental resolution, rather than invent a
  numeric operational scan cap. Validate cursor visibility itself, skip preceding refs, resolve until
  page+one visible lookahead, guard only one local scope/projection join at a time. RED2fail1pass→GREEN
  verifies skipped preceding authority and no oldest-report resolution on the first1-row page.
  Cost if wrong: slow/sparse histories; local retained-index O(N), hidden/unavailable-row traversal and
  per-row proposal enumeration still require real cardinality/latency measurement before scale/SLA claims.
- Single-family positive/hidden + mixed-family3report page order/cursor tests added; hidden middle
  source does not consume a page/create a cursor. Current and baseline all-assigned-area checks proven
  with real durable WorkOrders. Producer refuses empty assignments rather than creating fake invalid
  records. Unrestricted retained unavailable history and original numerical policies remain unchanged.
- Added exactly GET mixed-history allowlist and handler Principal propagation. Relevant checks now
 47pass (`customer-history-http-green-20261006.log`), before the final additional source cases.
  No detail/family-alias/pending/mutation/internal allowlist expansion; live grants are untouched.
- Local Codex unrelated run terminal; actual gateway capability GET200 and enabled confirmed via
  prepared service config (only origin/upstream/port/enabled fields read; no secrets). Standing exact
  `apps/dashboard` connection ready and folder imported in-place; project `KSI Operations Console`,
  source directory verified via get_project + get_file actual component/tokens/brand. No source copy.
  GET connections404 was wrong discovery endpoint, not outage. Hidden input folder unreadable to
  project raw API; permitted sanitized screenshots/brand copied to explicit locally excluded
  `apps/dashboard/design-review-inputs/c1-20261006/`, actual read access verified. No secrets copied.
- Current HEAD main6b27225; task-owned provisional source/test/ledger changes only. C1 technical
  final checks, public socket/browser and C2/C3..7 acceptance remain unfinished.

## Final C1 review and observed product browser evidence
- Final fresh reviewer `ses_ef07e8ef0ffeSEQwdmlAMczrxb`: no demonstrated scope leak; incremental
  alternative(b) and exact one GET hold. Four Important coverage gaps addressed in a separate
  test-only supplement: single target all-area/zone negatives, signed mixed HTTP pagewalk/hidden404,
  real registered sibling403, unrestricted unavailable preserved. Independent supplement runner
  `ses_ef072f62affeLl9zKxXk0poLog`; result pending. No further production changes after first runner
  `ses_ef07ec7aaffe40o9G3oHtP5oAe` froze four source/test hashes for scoped/static/full tests.
- Deferred minors: crafted/legacy replay divergent-target counter defense-in-depth; guessed hidden
  versus missing cursor timing; retained-index/sparse-history/proposal scale measurement. OIDC always
  produces explicit frozenset grants; None breadth only applies existing unrestricted/opaque roles.
- Disposable actual issuer/JWKS → Authorization Code/PKCE → FIELD_OPERATOR browser verified on
  real Core socket + actual Next product server, generated durable Core graph. Initial assembly
  attempt correctly refused absent issuance storage dependencies; corrected TEST assembly mounts
  the real existing read router only, without disabling production validation or manufacturing
  storage dependencies. Initial default-admin dev login correctly401 (test maps only FIELD_OPERATOR);
  selected actual role-test field account, no ADMIN fallback or persistent mappings changes.
- Actual history loaded200: Synthetic site/Measured zone, original cut1/fill5/net+4 m3 and RMSE
  limit displayed. Desktop1440x1000/mobile390x844 captures under `/tmp/opencode/customer-history-*`.
  Reload retains exact row/metrics. UngrantedSite gives contextual404 without identity/row disclosure,
  visible Site-list escape works. Browser JS errors empty. Core log records only method/path/status;
  auth state remains private. Detail click actual403 produces bare retry-only UI: C2/C3 OPEN, not
  accepted end-to-end navigation and not numerical/real-data/customer/field acceptance.
- Browser smoke owner stopped and browser closed; generated data not erased, no shared-server stop.
- Design stage: read-only `design-review` commissioned on same real workspace and all3 actual
  desktop/mobile/detail-error images. Must confirm actual image opens, criterion→concrete defects;
  output only `design-review-inputs/c1-20261006/design-audit.md`, no UI/Git/dependency writes. Installed
  Dashboard AGENTS.md/Next docs are mandatory before later source changes. Design audit running;
  no newly design-reviewed output claimed. Canonical image/source hashes:
  - history page `78c4d9b6091cd8bd94fd8f03dd13131a418d4f987e7edc22dbfdd40f7f65e44b`
  - history component `38ae4d319f92236bc8424be78691235a2297251856522ea3e76a945748c41738`
  - globals `e2ed9fad389b7ba80a7e5198196b22f10fe5c2dc121f268fbf4c7a9894ac8f2f`
  - brand `6269a2aa063a56baabcded7214cf9378642220ffde924cb5b042844435dcb467`
  - desktop `2f85597d615f1c92be7bb16d4b5c444c845b10b6350e3c3cdc31ffaac52f1601`
  - mobile `525fb34adaec534439d68067c7038e155cbd30e513d756bdb3b007316d0f344a`
  - denied-detail `dda0c5c0e1bc54b65f1f2b1f1d08ec9849570a4ca551f10a5c699daea0a28a43`
- C2 specific three-candidate route audit assigned read-only `ses_ef0737779ffevnikXVibt1F2T0`;
  do not open detail/family routes without its actual payload/source/downstream findings and tests.

## Observed prerequisites / blockers
- C1 independent verification: `ses_ef07ec7aaffe40o9G3oHtP5oAe`, main6b27225 + exact stable
  task-owned snapshot: scoped80pass7.86s, ruff4files/mypy2productionfiles/diff rc0; `pytest -q tests/`
  8476pass122skip101warnings909.83s EXIT0. New supplement postcollection independently4pass0.84s,
  ruff0, whitespace no diagnostics via no-indexcheck; verifier `ses_ef072f62affeLl9zKxXk0poLog`.
  Prior supplement ruff2xF811 fixed by correct parameter-line noqa, not production changes.
  Logs `/tmp/opencode/customer-history-independent-{scoped,static,full}-20261006.log` and
  `/tmp/opencode/customer-history-independent-supplement-final-20261006.log` verified by Primary.
  Four production/test hashes stable before/after and equal staged candidate:
  - projector `eef77f893d5b4df274f8ef7e4a906c4a54f6269169ccb2674ecd744481b8a8cf`
  - auth `0309632a12d36689d1db8f8b9aff669478ca62e393fb7056f4afa3b0130ba105`
  - scope test `b19def1bf58035d94f1f9b380d2364f9080cece58d7967dc8f7dd1c0504ba7f3`
  - fixture `aa04dbeea23eafb231851888a2db756462b80d1867717a5228a2747073c59498`
  - supplement `c6ddbc0ef7b4588eecaef6724a2cade7f55419f32872d17034d5024b34b940ed`
  README/ledger/new supplement were added during fullrun; checked production sources were frozen,
  supplement independently tested later. No claim of a frozen fulltree or 0warnings/skips acceptance.
- Local Codex source registered/access verified; UI source edits/design-reviewed output remain pending.
- Real customer t0/t1/t2 exports/rights/independent validation/cost baseline and customer login are not supplied. Existing root0600 provider diagnostic material remains unavailable; no chmod/credential sharing workaround.
- Prior full Python8641pass/122skip/101warnings and Dashboard973 tests belong to the previous recorded snapshot. Reuse as baseline, not evidence for future source changes.

## C2 approved payload contract and required declaration
- Human chose “검증된 상세 공개 (Recommended)” on2026-10-06 after actual3-route/payload audit
  `ses_ef0737779ffevnikXVibt1F2T0`: exact-source ALLarea grants before summary/rawdetail; for a
  readable report include original request/report/policy/review and visible proposal/approval bodies;
  site-less route derives Site only from the exact validated witness+Core orders. Inline proposals
  filter decision+zone digests and complete target grants, never expose hidden placeholders.
- Requirements: REQ-SEC-101, REQ-UX-101/A2, SDP-REQ-05/06/07/08, EXT-VAL-05/08. Invariants
  INV-060 source/org/Site/allareas, INV-040 unavailable failclosed; preserve numerical/accuracy/control
  and revision-bound V2 review boundaries. Owner Coreworkflow projector/router+identity.
- Acceptance: exactly3 detail GET templates return original bound summary/raw bodies for granted
  customers; hidden/foreign/unavailable/mismatch returns generic404; archived history remains;
  wrong-family404; unauditedaliases/pending/proposal/reviewdirect/V1mutations/internal remain403.
- Candidate templates: Site observations exact projection; relative report exact rawdetail; single
  report exact rawdetail. No POST permission or live OIDC/grant/policy/signature/production change.
- Contracts: preserve existing3 response schemas and unrestricted history/unavailable semantics.
  Local one-row guarded scope+joins after independent provider preflight, exact-witness rendering.
- Files: existing projector/router+auth; new bounded signed-OIDC detail tests; README/thisledger.
  Reuse C1 predicate/fixtures/canonicalstores, no reference runtime import or new identity/modelstore.
- Tests:3route×family positive/negative org/site/zone/allarea/currentbaseline/missing/unavailable,
  archived/changed sources, inlinedmetadata/receipt binding, no familyalias/mutation widening.
  Red→green; final independent scoped/static/bare repository pytest; actual product-browser flow.
- HIL/device/license/data: generated durable records only; no field/customer/RTK/license claim.
  Rollback task-owned localcommit only if requested; retain journals/rights and unchanged V1/V2.
- C3 audit Local Codex opened all3 supplied images; findings C1-V-01 hidden mobile uncertainty,
  C1-V-02 denial context/escape, C1-V-03 unclear numerical limitations. Implement within existing
  approved brand, generator frontend-dev then distinct web-design-guidelines rendered review.
