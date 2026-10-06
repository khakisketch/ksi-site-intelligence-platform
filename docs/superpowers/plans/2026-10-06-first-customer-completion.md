# First Customer Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans for inline development. Checkboxes record evidence, not product acceptance.

**Goal:** Finish the existing scoped customer analysis/data workflow and obtain the evidence required for a first repeatable customer pilot.
**Architecture:** Reuse Core identities, existing V1/V2 results, inspection/measurement workers, public HTTP and current Dashboard. Fix actual missing resource checks before enabling audited customer reads. Keep operations, real samples and human acceptance separate from local software.
**Tech Stack:** Existing Python/FastAPI/httpx/pytest, Next Dashboard and Local Codex; no installation or dependency changes.
**Spec:** PRD §1.1.1/1.1.2, ADR-KSI-036/037/038, SDP-20260930, FPC-20260928 and existing Dashboard experience ledger.

## Authorization and workspace
- 2026-10-06 follow-up: Human explicitly requested long-term autonomous development goal and chose
  `개발 goal로 교체 (Recommended)` after the existing paused operations-goal conflict was surfaced.
  Native replacement archived/cancelled the old operations goal (not completed or resumed) and
  activated development goal `42cd7bf4-6563-4bbc-877b-d0971383ee67` for this ledger's approved scope.
  Safety rails7days/1000auto-turns/no token cap; no-progress nativepause remains authoritative.
  Complete only with no required agent-owned work plus independent tests/static/build, actual
  scoped browser/reload, design-owned rendered defect closure and Git/ledger evidence. Unmet only
  for concrete required-input/contract/tool/authorization blockers with no safe independent work.
  Report finalstatus→usablelevel/evidence→stopreason→unverifiedscope/owner→nextaction; actual
  customer/data/field/operations acceptance remains distinct. No push/deploy/signing/liveauthority.
- Human: “다음 모두 개발 개선 해줘 제품을 완성하기 위해 필요한 것들이잖아” authorizes pursuing the stated completion work, not merely cosmetic/client polish.
- Existing current checkout `main`, base/integration target `6b27225ed58be569c8deea1c860185199950e3cc`; clean at start. One writer, no new worktree needed.
- Routine local code/tests/review/commits are authorized. No main push/PR/deploy, live grant/account/policy/signature change, equipment/customer contact or implicit operations-goal resume.
- No native goal was created at initial task intake; the explicit follow-up above now authorizes
  goal mode. Historical operations candidate/evidence remain separate and unapproved for execution.
- Completion must distinguish implemented, independently verified, operationally exercised and customer-accepted; EXT-VAL/P-AC stay open until their actual acceptance gates.

## Execution tracks (sequential within each shared-file owner)
- [x] C1 Customer observation-history resource-scope contract, security review and HTTP implementation (local technical scope; full-product/customer acceptance remains open).
- [x] C2 Related report/detail navigation scope and actual scoped browser workflow; independently verified local technical work only, no ADMIN fallback or customer/operations acceptance claim.
- [x] C3 bounded Dashboard technical work: actual UI/loading fixes, distinct rendered review and repeated-use auth repair independently verified, including final compiled-artifact OIDC/API/navigation/reload. Customer/field/operational acceptance stays open under C5/C6; do not mechanically redo 13 checked items.
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
- [x] Verify actual scoped Dashboard history flow with real HTTP/OIDC; detailed C2/C3 verification and product acceptance remain separate below.
- [x] Preserve C1 task-owned local commit a672ea3; customer/operational acceptance remains open.

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

## C2/C3 execution checkpoint
- C1 preserved local commit `a672ea3` (7files, task-owned only; no checkpoint/runtimeinputs).
- C2 RED9fail on expected403 before code; scoped exact3GET + Principal + shared predicate now
  implemented. Providers outside guard, derived-Site/allsource checks plus request/review equality,
  decision/zone/source/review and target-grant filtering before rawinline joins. Original privileged
  detail503/unavailable preserved; generic restricted404. No other GET/POST gate expansion.
- C2+C1+workflow affected GREEN62pass5.41s, ruffchecked3files0. Existing C1 sibling403 assertions
  intentionally updated only for the3 newly customer-approved exact reads; unrelated intents still403.
  These are provisional Primary checks, not independent final verification or customer acceptance.
- Follow-up real sealed proposal journal/cold graph experiment CORRECTS a prior reviewer hypothesis:
  tampered self-consistent target snapshot is rejected before mount by
  `verify_external_reobservation_organization_graph` with invalid historical lineage. The standalone
  store replay does not alone prove a reachable graph leak. Tests cover valid full inline review+
  proposal and this startup rejection; no bypass of graph validation to manufacture a leaking route.
- C3 source-only execution commissioned via explicit source patch-edit/build-test scenario and
  frontend-dev recipe, actual apps/dashboard directory. First call422 validation (missingrequired
  repoPath/targetStack) did not start a run; supplied confirmed existingstack/path using same action
  key after inspecting actual pluginmanifest. No framework migration/newtoken/dependency allowed.
  UI ownership2pages+focusedtests only, no Git/backendwrites; sourceoutput awaits renderedreview.
- No resident product-context.md found; existing approved brand/audit/ledger is standingbrief.
  Updated design-review input rule includes keyboard/focus, axe and motion/interactions, plus
  success/empty/error/loading at390/768/1440. Actual temporary product link must be labeled local
  or tailnet-only as appropriate; never imply prior stopped loopback preview remains reachable.
- C2 finalreview `ses_ef05e9898ffeDKyVVjDi3AWfGR`: no demonstrated blocking leak; provideroutside
  guard/allsource/derivedSite/inlinefilters/3routebudget hold. Remaining negative inline/mismatch
  status fixtures are deferred coverage, not evidence permitting forged graph lineage. Supplement
  `test_oidc_external_detail_scope_coverage.py` proves valid-reference direct403 and history/raw
  visible-count parity (Primary1pass); independent supplementary check pending. Final verifier
  `ses_ef05e71b8ffebuTt30GTfqebAJ` freezes backend/tests and uses BARE configuredpytest afterscoped/static.
- C3 generator completed ONLY2UIpages+2focusedtests, hashes recorded in its implementation report;
  actual installed Next16.3.3 docs and all3images read. Container Vitest could NOT start (prepared
  nativebinding absent; npmregistry refused); no dependencyinstall or fakeRED/GREEN. Host independent
  runner `ses_ef05bde5effelnHxfCMHZflHIJ` uses preparednode_modules: sameNEWtests against originalUI
  in taskowned detached `.worktrees/c3-history-red-20261006` basea672ea3, then currentUI/fullchecks.
  This is baseline-reproduction + outputverification, NOT a claim innerexecuted test-firstRED.
  Workspace needed specifically to avoid temporarily changing actual productUI; no otherworktrees
  commandeered. Copied2testfiles and dependencylink owned by this task; preserve evidence then cleanup.
- C3 independent runner completed: originalUI/newtests RED11failed6passed (no infrastructureerror,
  worktreealias verified), proposedUI3failed14passed17; fullUI10failed971passed981. Lint/tsc0,
  nextbuild0 with7existing CSSoptimizationwarnings. Exact2pages/2tests hashes unchanged throughout.
  Blockers:2permissioncopy mismatches + duplicatedhistorylink assertion;7existing unchangedkinds
  tests fail (baseline12/12pass): duplicate compact/tabletext + followuptrace heading lost when
  rawdetailunverified. This is actual qualityunmet, NOT merely waiting for useracceptance.
- Real productdev startupfailed500 CSSparser; ownedstack timedout/stopped and browserclosed.
  Actual overlay screenshot supplied todesign. Primary diagnosis using installed OxideScanner
  per-file extraction located corrupted arbitrary shadow candidates in historical Turbopack `.sst`
  caches under multiple .next-* directories, NOT changed eventsource/realvalidutility. No cache
  deletion/move or visualfallback. Context7 officialTailwindv4 docs confirm source(none)+explicit
  @source path for actualcomponenttree avoids unrelatedartifactscan. Next generatedtsconfig includes
  restored after ownedserverexit; no permanentbuildpathconfig accepted.
- Concrete refinement run `2ee02454-d5d1-43f3-a88b-231a2815f1e9` action
  `ee1614b7-691c-4308-a1ad-3df396d55269` started, frontend-dev/source-editprofile. Ownership extended
  only to related kinds test and globals.css source-detection directives (no token/style rewrite),
  with exact failedtestlogs/actualCSSerror render + rootcause input. Preserve unverified-flow guidance
  while withholding rawfacts; adapt duplicate DOM assertions to realresponsiveviews, no blanket
  weakening. Need independent repeatedfulltests + actualdev states then distinct designreview.
- C2 reviewer dispositions: no demonstrated blockers. Added validrefclosures/countparity test;
  negative inline/request-review mismatch in mounted verifiedgraph is deferred fixturecoverage,
  not fabricated through bypassing startuphistorical checks. Full verifier originally returned
  interim while its original barepytest backgroundprocess runs; continued samechildsession to
  finish on commandnotification with actualresult, no repeatedsuite or progresspoll.
- C2 independent supplement completed1pass0.58s/pytest0/ruff0; Primary re-read log
  `/tmp/opencode/customer-detail-independent-supplement-20261006.log`. Added test SHA256
  `d3c5b3757bfbd6d504078431806f5484c825f4b1507ef72617b8981e5a1d8094`, production projector
  `76f3af895ce96b572159361e2e41a109df0d7d48bb5c57733228e9d96745c89a`, auth
  `b315d6388da567e25224e949f22dd0959ece90bcc823cf253f34919c20812966` unchanged before/after.
  Original bare fullrun still executing; no exit/count claim, no repeated run. C3 refinementrunning.

## C3 refinement verification continuation
- First refinement terminal, authoritative inner report confirms source edits (canonical entry untouched),
  not generated artifact quality approval. Input screenshot correction: captured connection-refused,
  while CSS diagnostic was separately observed in actual development output/cache tracing.
- Independent final runner `ses_ef05bde5effelnHxfCMHZflHIJ`: scoped27pass2fail29, full979pass2fail981;
  lint/types/build EXIT0 and build has no prior Tailwind warnings. Six file hashes unchanged; complete
  logs `/tmp/opencode/customer-ui-independent-final-{scoped,full,static,build}-20261006.log`.
- Remaining RED is exact404/503 copy in `ObservationDetailReadFailure`: shared default subject adds
  `이 ` to every status, whereas original tests expect that prefix only403. Ruling: restore exact
  nonpermission copy, not weaken tests; preserve contextual Site escape/status/retry and custom
  Site-information subject. Cost if wrong: misleading status copy; no permission/data contract change.
- Focused Local Codex repair `48216aa3-ab2d-4d74-9d7d-1e0df4836bf6`, action
  `425cc292-82d6-4fe2-a771-eeb2258ce097`, frontend-dev + source-edit scenario; sole detail-page
  writer, implementation handoff only otherwise. New RED log text input read-access verified.
- Owned generated Core/issuer/Next browser stack restarted separately for actual development/render
  verification; no shared server/config/grant changes. C2 original barepytest remains independent;
  no duplicated Python suite. UI remains provisional pending repaired tests and distinct renderedreview.
- Copy repair terminal: only detailpage and local implementation handoff changed. Page SHA
  `bbe317fb559798572405dde09fd9c1f8d74fdd3e2db8bac671cda0bbc80b3494`.
  Independent runner `ses_ef05bde5effelnHxfCMHZflHIJ`: scoped29/29 and full981/981 across129files,
  lint/types/build EXIT0, no warnings/errors in build, six checked source/test hashes stable.
  Primary read actual logs `/tmp/opencode/customer-ui-independent-copy-green-{scoped,full,static,build}-20261006.log`.
- Actual generated FIELD_OPERATOR/PKCE browser: history→detail→history by links, detail reload
  and history reload retain cut1/fill5/net+4m³, common valid100%10/10m² and uncertainty±5m³.
  Scoped Site projection and exact raw relative detail GET200. Missing retained display derivatives
  explicitly unavailable, never fabricated; supporting404s in this assembly are not real data evidence.
- Settled history/success detail/empty/history403/history503/detail403/detail404 captured390/768/1440;
  all21 settled axe4.12.1 checks0violations/0incomplete. No horizontal document overflow; compact
  uncertainty accessible with vertical scroll (history height1082 at390×844), no horizontal panning.
  2px focus-visible outline on detail link and keyboard Enter navigation observed; reduced-motion
  preference activated. No screen-reader listening/real-device/touch target claim: device preset
  attempt still returned pointer:coarse=false and38px buttons; capture renamed accordingly.
- Loading captured only after visible actual aria-busy DOM during injected10s delay; resolvesempty.
  C3-A11Y-01 OPEN: axe serious aria-prohibited-attr in two SkeletonList generic divs with aria-label
  and no role, atall3viewports. Actual source `src/components/ui/Skeleton.tsx:3`; SkeletonBlock
  sibling has role=status. Needs design-owned scoped repair plus regression/render verification,
  not a Primary UI edit or an unrelated global accessibility rewrite.
- Distinct web-design-guidelines review brief prepared at
  `apps/dashboard/design-review-inputs/c1-20261006/rendered-review-brief.md`; all screenshots,
  snapshots/axe JSON and final-render-source-sha256.json locally excluded. Brief read through design
  API successfully, but file-metadata call caused MCP process EPIPE/disconnect before commissioning.
  Native OpenCode exact-project/name connect request restored statusconnected without config edits,
  installation, credential reads or service restart; THIS session's tool catalog still lacks design
  tools. Review NOT STARTED, no rendered quality approval; required C1-V defects remain pending
  review closure. Do not substitute direct UI edits, standalone engine or another design source.
- Task-owned smoke owner PID was identity-verified before SIGTERM; completion observed and browser
  closed. Only inspected smoke-induced tsconfig formatting/distincludes restored; tsconfig diffempty.
  Independent post-smoke runner same session: tsc EXIT0, sixsource/test hashes unchanged and config
  SHA `6b1807cfc5a7d27e4d7d3a9a731bd4bd5d93a10988ef7169412b817ca2f23aea` equals baseline.
  Log `/tmp/opencode/customer-ui-independent-post-smoke-static-20261006.log`; initial wrong-cwd
  Git path emitted a benign warning, authoritative root check appended. No full981test rerun needed.
  C2 original bare configuredpytest still has no final report; no duplicate/progresspoll performed.

## C2 definitive verification recovery and local closeout
- During explicit goal activation, original verifier `ses_ef05e71b8ffebuTt30GTfqebAJ` recovered
  its original completed command record, not a repeated suite. Shell `sh_10fa44109001bqYliPCxCC3DZ8`
  completed: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` (pipefail/tee with exit
  persisted) →8684passed122skipped101warnings920.47s, `PYTEST_EXIT:0`. Primary read actual final log
  `/tmp/opencode/customer-detail-independent-full-20261006.log`, source hashes still identical.
  This supersedes interim pending statements above and is the bare configured tests/packages/services
  evidence, not merely tests-directory output. Existing warnings/skips remain disclosed.
- The detail supplement created15s after bare collection is NOT included in8684; independently
  1passed0.58s/ruff0 with stableSHA d3c5b3757bfbd6d504078431806f5484c825f4b1507ef72617b8981e5a1d8094.
  Original scoped95pass +ruff/mypy0 remain valid frozen-snapshot evidence.
- C2 acceptance audited against exact3GET permission budget, source/all-area/zone/request/review
  binding, scoped404 and unrestricted semantics, signedHTTPbothfamilies, valid workflow403/count
  parity, cold graph rejection, final security review and actual relative detail/reload/escape200.
  Local technical C2 complete; C3 loading accessibility/rendered review and actualcustomer/field/
  release acceptance remain open. Task-owned source/tests/README/ledger only staged for localcommit;
  six pending UI files/checkpoint/design inputs are excluded. No push/deploy or operationscandidate change.
- Actual local commit `7177620866cd45a2b93493b38ef4785598b16fb6` preserved8task-owned files;
  index/diff checked clean, six UI files remain pending, checkpoint/designinputs excluded. Git HEAD
  changed only commit metadata; verified backend/test bytes retain their frozen hashes.
- Required design access recovery: native actual-project MCP list connected after scoped reconnect,
  but both Primary and fresh read-only helper `ses_ef01d1057ffeRrUfU7lENbkCs2` discover0design tools.
  Prepared native API `location.reload` is GLOBAL/all-loaded-locations, cancels pending permissions
  and forms, running sessions continue at nextstep; does not restart productserver/containers/host or
  edit config. Human explicitly chose `공유 재로딩 승인 (Recommended)` after effects disclosed.
  Authorized exactly one reload then actualproject/source/renderinput revalidation, no blindgeneration.
- Approved reload executed through native `opencode api post /api/location/reload`, command EXIT0.
  Current request's Code Mode catalog stillempty; recovery is NOT yet verified. Next fresh native
  goal step must rediscover/read exactproject and requiredbrief/images before commissioning review.
  Do not repeat globalreload, silently changepermissions or use a standalone design fallback.

## C4–C7 current-evidence reconciliation (read-only, no operations resume)

- C4: source-frozen offline application bundle/Python binding and OCI/scanner v2 byte linking are
  already implemented with independent repair evidence in `2026-10-04-external-runtime-application-bundle.md`
  and `2026-10-04-external-runtime-oci-scanner-link.md`. Do not reimplement or relabel as current
  operational acceptance. Current backend regression includes their contract tests; actual preparation
   requires supplied protected runtime/wheelhouse/host records. Archived/cancelled operations goal retains candidate
  037d6366a4e7c496b7d6d2f045c88ce31ac2e6f2; newmaina672/C2 is NOT that candidate/release.
  No new image/signature/installation/release selected/produced by this continuation.
- C6/FPC-15: old roadmap row saying degraded boot unimplemented is stale historical state. Actual
  `2026-09-29-expired-authority-degraded-boot.md` records snapshot-expired and catalog-expired
  restart/recovery + unchanged history; later signed current-source review exists. Reuse implementation
  and tests, no duplicatefix. Real host key/catalog recovery remains separately authorized/unverified,
  as does representative customer backup/restore and retention.
- C5/C6 acceptance needs owner-supplied sameSite t0/t1/t2 exports + CRS/vertical/provenance/rights,
  selected customerOIDC/MCP and field/cost evidence, plus separately approved actualhost/runtime
  containment/recovery stages. Generated simulations do not close these actual-evidence gates.
- C7 has no selected detailed feed/resync/dataMCP or externalproducer/model/input/revision contract;
  material wire/authority decision required beforeimplementation. Existing data/analysiscontracts intact.

## Goal deliverable-to-evidence audit — 2026-10-06 continuation

The objective remains the full approved repeatable customer workflow, not just passing tests or
closing C2. Completion requires all mandatory agent-owned work, independent checks, actual scoped
browser/reload evidence, design-owned rendered defect closure, task-owned local commits and durable
evidence. Customer/field/operations acceptance remains separate; missing evidence is not achieved.

| Goal requirement / deliverable | Concrete evidence and remaining gate | Audit disposition |
| --- | --- | --- |
| Resume current checkout and approved requirements | Native goal42cd7bf4 active at audit; Git main7177620866cd45a2b93493b38ef4785598b16fb6; six C3 files + ledger pending. Reread checkpoint/product-state/task ledger, authority sequence, PRD1.1.1/1.1.2, ADR036/037/038 and routing. EXT-VAL slice not closed/reprioritized. | Revalidated; objective intact |
| C1 exact-source scoped history/cursor | Commita672ea3; signed HTTP scoped80+4pass; original tests-directory8476pass; incremental cursor/provider-outside-guard evidence and reviewer sessions above. | Local technical evidence retained, not customer/field acceptance |
| C2 exactly3 audited detail GETs and complete visible joins | Commit7177620; named Core projector/auth/README +4scope test files; frozen hashes/scoped95/bare8684+separate1pass/static0 above; actual FIELD_OPERATOR history/detail/reload/escape and projection/raw200. | Local technical evidence retained |
| Preserve organization/Site/every relevant source WorkArea, strict V1/V2 and historical numeric meaning | C1/C2 exact binding and denial tests/reviews; INV040/060 enforced in existing Core scope/read paths; INV051/053/054/055/061 unchanged. No journal, grants, numerical profile, reconstruction engine or review authority changed in this continuation. | Preserved source snapshot; no metrological or operational claim |
| C3 actual UI source, independent tests/static/build and auth/API browser persistence | Six pending files; final source hash JSON, copy-green scoped29/full981/static/build0 and post-smoke tsc0; actual generated Core/JWKS/PKCE browser and390/768/1440 state evidence in locally excluded review inputs. | Technically exercised generated assembly, provisional UI only |
| C3 distinct design-owned rendered review and required defect closure | Prepared rendered-review-brief.md and actual screenshots/axe/focus/loading evidence exist. C1-V-01/02/03 final rendered closure missing; C3-A11Y-01 loading aria-prohibited-attr remains open in SkeletonList. Review not commissioned. | NOT achieved; required design tools unavailable |
| C4 finish safe local verifier/recovery gaps without duplicate implementation | Actual bundle/Python binding/OCI source/schema/tests and dated plan status sections already implemented; expired-authority degraded-boot source/tests/plan already present. No concrete additional approved gap demonstrated. | Reconciled only; genuine candidate bundle/host preparation not newly verified |
| C5 actual repeated customer t0→t1→t2, rights/CRS/vertical/provenance/OIDC/MCP/cost | No selected owner-supplied actual export/rights/customer identity/client or cost evidence available to this task. Generated records cannot replace these inputs. | NOT achieved; owner-supplied inputs required |
| C6 actual containment, backup/restore/failure drills and named customer acceptance | Existing local simulations/code are not actual deployed recovery. Host/runtime/signer/configuration/backup custodian/destination/retention and customer gates remain unapproved/unverified. | NOT achieved; operations authority/evidence required |
| C7 selected feed/resync/data-MCP/external-result contract | ADR038 D4/D5 and roadmap GAP04..10 retain material scope/authority/transport/output decisions; no selected detailed successor wire contract. | NOT achieved; material requirements/decision required, no guessed implementation |
| Local Git, ownership and external-effect boundaries | Only C1/C2 source commits preserved; C3 remains provisional. No push/PR/deploy/registry/signing/live-authority/equipment/customer contact; operations goal cancelled/archived, not resumed. | External delivery not performed; C3 commit remains gated |
| Safe owned-workspace cleanup and retained evidence | c3-history-red-20261006 detacheda672ea3 has2dirty test files and node_modules symlink to main. Baseline detail test differs from current; preserve worktree unchanged. Extra patch /tmp/opencode/customer-c3-red-baseline-preserved-20261006.patch SHA25660eab4000d792a49bcc3e6e107dc0800caf8a600ea5f645d7eb2aa01a913b548. | Retained exception, not deleted or forced clean |

### Required-tool investigation and independent blocked audit
- After the approved single shared reload, fresh native step and Code Mode discovery still expose
  zero OpenDesign tools; the fresh helper also found none. Exact-project native MCP API reports
  connected, native service API is healthy (2.0.22), session location is the actual repository and
  native agent is Build. Read-only resource discovery returns no resources/templates.
- Sanitized configuration/agent inspection confirms no Build design deny and design enabled with
  default Code Mode. Installed proxy statically defines22tools including get_project/get_file/
  start_run/get_run and a tools-list handler. This narrows the failure to catalog exposure but does
  NOT prove an internal root cause or a successful recovery. Default CLI mcp list reported no
  servers in its default location; exact-project API is authoritative for this task's connection.
- No second global reload, service/container/host restart, permission change, standalone design
  fallback, dependency installation or UI edit was performed. Shared service restart, if selected,
  needs its own approval and may not fix the unproven catalog defect.
- Independent reviewer `ses_ef0063e0effergSiA5V03TYhXr` inspected all open C tracks and found no
  concrete independent authorized engineering task executable with current tools/inputs/contracts.
  It verified C3's actual source defect, existing C4 tool/schema/test paths and dated implementation
  evidence, C5/C6 input/operations gaps and C7 unresolved decisions; no test or visual rerun claimed.
  Reservation: the old ignored contained-runtime progress.md link is absent from this checkout and
  a bounded task-worktree lookup; do not infer genuine bytes/host evidence from that unavailable
  record. The tracked dated plan sections establish local source history only.
- Security incident in diagnostic output: a response-shape error caused API key values to be emitted
  in a local tool trace. No values are reproduced or persisted here; owner rotation of the affected
  Meta/NVIDIA/Context7 keys is required. No credential changes/sharing or cleanup of session history
  was attempted. Follow-up diagnostics print only allowlisted nonsecret state and permission fields.

### Independent final-snapshot verification (not a fresh full-suite/build run)
- Test-runner `ses_ef005f2c4ffeZM0poST5LBMkNM`, terminal audit log
  `/tmp/opencode/customer-goal-snapshot-audit-20261006.log`, independently compared actual working
  files and committed bytes with frozen hashes. All C2 production/tests and six C3 source/test files
  match the original full/static/build/browser snapshot; restored tsconfig SHA6b1807cf matches.
- Fresh `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` on history scope/coverage,
  detail scope/coverage and external_result_review_proposals test files →62passed5.63s EXIT0.
  Fresh `npm run test -- test/external-observation-history.test.tsx
  test/site-observation-detail-exact-display.test.tsx test/external-observation-history-kinds.test.tsx`
  from apps/dashboard →29passed/3files EXIT0. git diff and cached diff --check EXIT0.
- Actual frozen logs confirm bare8684pass122skip101warnings920.47s EXIT0 (separate supplement1pass),
  scoped95pass/ruff+mypy0, UI full981/129files/scoped29/static/build0 and post-smoke tsc0. No repeated
  full suites/build/browser claims. The build used Next-generated tsconfig c870274d, not the later
  restored6b1807cf; only source/test bytes were identical, restored config subsequently tsc-verified.
- Required brief filenames:80checked0missing. Independent JSON parsing confirms21settled axe files
  0violations0incomplete but all3loading axe files retain serious aria-prohibited-attr on2nodes.
  rendered-review.md absent. These checks do NOT establish design quality or C3 completion.
- Audit conclusion: NOT complete. C3 still requires unavailable design execution/review; all other
  open tracks require genuine supplied inputs, new operations authorization or selected detailed
  contracts. No safe independent approved engineering task demonstrated. Preserve unfinished UI,
  review inputs and dirty baseline worktree; report concrete blockers rather than an automatic wait
  or silently substitute Primary UI edits, synthetic acceptance or a narrower goal.
- Same independent test-runner then checked this final ledger against its actual audit log: text-only
  diff, accurate counts/limitations, unchanged production/UI hashes, no secret values, diff --check0.
  Final disposition is required-tool/input/authorization/contract blocked, not product completion.
  Preserve this evidence in a ledger-only local commit; checkpoint remains excluded. No external delivery.

## Human continuation and bounded recovery authorization
- Human follow-up2026-10-06: "그렇게 해줘 멈추지 말고 제품 개발 개선 계속 완성할 때까지 해줘".
  Native prior goal42cd7bf4 stays unmet; it was not revived or silently narrowed. New explicit goal
  `8fe5db9c-0f38-4f49-bfd2-1a1985b0ec0e` is active for the same full development objective plus
  required-tool recovery. Safety rails7days/1000auto-turns/no token cap; completion/blocker/stop
  evidence and no-progress rules unchanged. Existing C1/C2, numerical/resource/authority contracts,
  six provisional C3 files and baseline worktree remain preserved; no new product slice/direction.
- Key-management capability discovery found no available vendor key-management tool. A provider API
  credential is not an authenticated account-admin session. Meta/NVIDIA/Context7 key revocation and
  replacement require the account administrator; no values requested in chat or reproduced, no
  credential read/write or unsupported account-management request. This does not block independent
  safe design recovery/development; do not claim key rotation completed.
- Native service identity verified: opencode api info2.0.22/PID1228482/loopback49374 matches native
  opencode service status. Exact session/currentrepo and source HEAD1bc6fa4 unchanged; no server
  substitution. Design catalog still absent on this new user turn; no unverified UI source writes.
- Human chose `공유 서비스 재시작 승인 (Recommended)` after explicit disclosure: ONE OpenCode
  shared-service restart may temporarily disconnect other sessions and interrupt running requests;
  it does NOT restart the product server, OpenDesign container or host. Save all task/evidence state
  and finish owned diagnostics before performing it; no guaranteed catalog fix. This does not
  authorize further global reloads, installs, container security changes or a design fallback.
- Read-only explore helper failed before execution (upstream model unavailable); no evidence came
  from that failed dispatch. A bounded general helper now investigates supported catalog recovery
  without mutations, protected config/credential/raw-log reads or source writes. No model override.
  Service restart is approved but NOT yet performed; checkpoint records the exact once-only boundary.
- General helper `ses_eeff77d5fffe6I8y3pRLwve90Q` confirmed native service executable/identity,
  static proxy tools-list22definition mechanism, absent current Code Mode namespace and working
  notifier/history. No narrower supported recovery demonstrated; internal transport cause remains
  unproven. Save this ledger locally, then invoke approved `opencode service restart` exactly once.
  If its tool result disconnects, reconcile native service identity/catalog at next boundary;
  lack of a completion result is NOT authorization to replay the restart.
- Approved `opencode service restart` executed once, EXIT0; after restart native PID494960
  replaced1228482 at the same service URL. CodeMode catalog was briefly empty during startup,
  then exposed22OpenDesign tools; exactproject metadata and prepared review brief/source Skeleton
  reads succeeded. Metadata still resolves the actual Dashboard folder with explicit code-migration
  scenario. Catalog later fluctuated again; successful reads are evidence of restored access, not
  sustained health or a design review. Do not repeat the shared restart.

## C3-A11Y-01 regression declaration / design-owned repair boundary
- Requirement IDs: REQ-UX-101, C3-A11Y-01; owner Dashboard shared Skeleton loading presentation.
  Acceptance: actual list/block loading has named busy status semantics; actual loading axe's
  aria-prohibited-attr closes at390/768/1440; original rows/style/motion and numerical states intact.
- Contracts affected: no API/data/auth/schema/profile changes. Invariants: preserve INV040/060
  honest loading/scope; no numerical or authority mutation. Reuse actual components/test tools and
  existing status pattern, no reference import, dependency or newbrand. Read Dashboard AGENTS,
  README/package and installed Next16 loading.md before new test code.
- Files: Primary owns new test/skeleton-loading-accessibility.test.tsx and evidence records ONLY;
  OpenDesign owns any src/components/ui/Skeleton.tsx UI change after actual rendered review.
  Test named regression: removing meaningful loading role makes named status unavailable (the
  observed current list defect); real component rendering, not source-text/mock assertions.
- Tests: failing named busy-status regression, host full/static/build after repair and actual
  loading DOM/axe/render recapture; distinct web-design-guidelines review against prepared inputs.
  No HIL/customer/screen-reader listening claim, no private data/license change. Rollback task-owned
  source commit only if requested; preserve existing six-file UI snapshot and RED evidence.
- Primary observed intended RED: `npm run test -- test/skeleton-loading-accessibility.test.tsx`
  →1failed(list namedstatusmissing)/1passed(block),307ms EXIT1. Log
  `/tmp/opencode/customer-c3-loading-status-red-20261006.log`; no production UI changed.
  Skeleton SHA df67827a243e0aeb7b9f9dbfb87820aa2a3af51b7b9b51bb80eb4864fb60000d;
  newtest94b0483f9592d87a92100101c3fa0b3cdfb123175119278fb52726e72518ed5f;
  preparedbrief7eb20c7df8027f7cba94d5ac9714d46737f48c1e219666ede936c214e27ea285.
- Prepared distinct read-only review action requestId `8bd60420-5a50-446f-afe2-c3b1eaffd6a0`:
  web-design-guidelines, existing actual Dashboard project; write ONLY rendered-review.md. Primary
  has NOT called start_run for this action. Catalog still fluctuates after successful reads;
  a bounded coordinator helper may use supported native OpenDesign tools to verify exact inputs and
  commission this ONE action, never design or edit UI itself. Same requestId after any lost response;
  no new request, fallback CLI/HTTP runner, new project, permissions, service restart or recursive run.
- Coordinator helper `ses_eeff1530bffe30yeZDKAr8USAR` found no callable OpenDesign namespace;
  no review run was started. Parent also reconfirmed absent start_run after the successful actual
  project/brief/Skeleton reads. This is unstable tool exposure, not a completed design review.
- Human chose `프로젝트 한정 변경 승인 (Recommended)` for a reversible, project-only native
  tool-exposure experiment: `.opencode/opencode.jsonc` (absent before, task-owned, ignored) repeats
  the existing nonsecret OpenDesign server command/flags/timeouts, adding only codemode:false.
  No permissions/authentication/sandbox/engine/cloud/credential change; all other global servers
  and agent rules remain inherited. Native scoped debug.location.evict for this actual repository
  is authorized to load the config (same-project sessions can be affected, other projects untouched).
  Hypothesis: avoiding Code Mode exposure may restore stable native tools; internal cause unproven.
  If ineffective remove only this task-created file and refresh only this project, no global restart.
- Project-scoped eviction completed; sanitized config summary confirms codemode:false applied.
  Native direct get_project/get_run/get_file now succeeds with unchanged actual Dashboard root;
  old48216aa3 was terminal and NOT replayed. Direct source-hash manifest and review brief were read.
  Exposed tools recovered sufficiently to commission the previously prepared action, not a proven
  internal root-cause fix. Retain the approved local exposure setting while it is effective.
- Distinct read-only review started once: request8bd60420-5a50-446f-afe2-c3b1eaffd6a0,
  run47cfff0e-52c5-44e7-9e5e-9beb455fde7d, skillweb-design-guidelines;
  explicit existingcode-migration scenario retained, LOCAL configured engine. Await actual opened
  image inventory and report, not run success/canonical-entry alone. No UI source repair yet.
- After interruption native get_run confirms this SAME review running with folder-backed,
  user-local/in-place workspace and explicit strategy off; no successor/recursive action.
  An inadvertent different-payload start with the same requestId returned IDEMPOTENCY_CONFLICT409;
  no second run was created. Follow original47cfff0e only; never reinterpret conflict as restart.
  Host check: all5 final-render-source-sha256 manifest entries unchanged, Skeleton stilldf67827a,
  52PNG inputs present, report not yet written. No review finding/closure inferred from these counts.
- Prepared distinct AFTER-only loading closure harness at
  `/tmp/opencode/customer-c3-loading-closure-20261006.py` (syntaxchecked, not exercised yet);
  before PNG/axe files retained. Existing authorized generated Core/OIDC/Dashboard smoke script
  re-launched only on verified free3237/9037 for this loading-repair acceptance. Owner638648
  cmdlineverified, sessioncustomer-c3-closure-20261006. Real UI role-test selector chose FIELD_OPERATOR
  and existing history showed unchanged1/5/+4m³/100%10/10m²/±5m³. Initial default development admin
  lacked mapped subject in this fixture and was NOT granted/fallbacked; explicit operator selection
  used normal PKCE. No tokens/cookies echoed. Private smoke log withheld. Save only owned generated
  outputs; stop exact owner at task end and restore only its proven tsconfig-generated changes.
  BaselineconfigSHA6b1807cfc5a7d27e4d7d3a9a731bd4bd5d93a10988ef7169412b817ca2f23aea.
- Distinct design-owned review47cfff0e terminal; actual `rendered-review.md` exists and was read
  through native project API. SHA504ecd862e562e4c27edc6552b94cbc6500ec719433f7e4fe15180c038db1f37;
  51opened PNG inventory entries independently match on-disk hashes. C1-V-01/02/03 fixed in that
  actual rendered snapshot; C3-A11Y-01 remains OPEN/serious at390/768/1440. No new settled defect.
  Entry no_artifact is expected for report-only output and does not supersede the actual report.
- Next concrete refinement action request32ae87df-4173-4e27-8171-8eb7c8af21c4:
  generatorfrontend-dev, actual-source/in-place, source ownership ONLYsrc/components/ui/Skeleton.tsx;
  preserve layout/classes/rows/motion and SkeletonBlock semantics. Apply valid named busy status to
  list; no changed numerical/API/auth behavior. Existing RED test observed, actual source read
  verified unchanged. Follow by host independent GREEN/full/static/build + newloading browseraxe
  captures, then distinctweb-design-guidelines closure against AFTER evidence; no premature closure.
- Minimal repair startedrun48bea7ac-1475-470d-a484-846f86c22254 with original request32ae87df;
  workspace again verified folder-backed/user-local/in-place. Watch bound; no other source writer.
  A differing-payload replay was rejected409; original run alone remains active, no duplicate.
- Repair48bea7ac terminal, verified actualoneattribute diff ONLYSkeletonList role=status;
  SHA7e98133493066e3711ed6d08bdb7ad32f36bb84d9101f0949eafd728a0978b3f;
  repairnoteSHAd88ceef3bf4863d60788460ebbdcba471e0fd1ca04066061d784bd5e77b9c23d.
  Inner Vitest WASI blocker unchanged, no falseinnerGREEN/install. Host scoped4files31passed EXIT0
  (newlist/block2plusprior29), logcustomer-c3-loading-green-20261006.log.
- First AFTER capture attempt stopped before loading on expired login; actualsnapshot says expired,
  no CoreSite-loading call. Reauthenticated via normalFIELD_OPERATORUI/PKCE, then actualinflight3
  viewport after-loading PNG/snapshot/axe allgenerated; named visiblebusy statuses>=2, eachaxe4.12.1
  0violations/0incomplete and resolvesempty. Preserve final-loading BEFOREfiles. No sessionfix inferred.
  Read-only authrefresh investigation helpers were accidentally dispatched twice with overlapping
  read scope; no writers/models override. Track terminalreports without further duplicate dispatch.
- Closure action requestb052a524-3ae8-4e19-aef6-6f1ee17cd244 prepared against actual AFTERinputs:
  distinctweb-design-guidelines READONLY loading-closure-brief.md → loading-closure-review.md only.
- Distinct AFTERreview started07c8cc77-19a8-4ee9-9f8f-278ac3ba224d, requestb052a524;
  same actualsourceproject, report-only/no writer. Await exactopenedbefore/afterimages and closure.
- Authtrace helpersses_eefd866afffeGbBGlmv0aDLe5l andses_eefd85150ffemVye7kltdR6N11 bothterminal:
  code proves accessTTL300s, refresh/session8hours, one-use rotation, coalesced5s reuse and RSCfanout;
  proxy doesn't stripcookies. Possible late stalecookie replay/persistence/HMR NOTPROVEN; sanitized
  ownedlog shows healthy200s, not expiredflowmetadata. No authpolicy/source change from speculation.
  Eligible next safecheck: naturalpost-expiry navigation + sanitized issuerstatus/SetCookiepresence,
  no tokens/cookies/JWTclaims. This is a newly observed repeat-use investigation, not fieldreadiness.
- Independent verifier ses_eefd57d89ffeR1tcuIe37BQpfV confirms scoped31/4files and full983/130files,
  lint0/no diagnostics, tsc0/no diagnostics, eightfilehashes/HEAD16b8304 stable. Types used temporary
  generatedtsconfigSHA c870274d887189c8ea70858efdafe758ddab81e1626bb53320cb87fe9b77108c;
  baseline restoration/build+tsc still pending. Logs customer-c3-independent-{scoped,full,lint,types}
  under/tmp/opencode. Duplicate verifier ses_eefd5448bffeXl5ZnMRWssZqpn was interrupted via native
  ownedsession endpoint, cancelled; no use of partial/duplicate results. Code reviewer
  ses_eefd58e5dffeUQsOwQhKG3TyKZ stillpending, read-only and no visualapproval substitution.
- Natural-expiry probe started onceownedPID727291/shellsh_1102b54530016h6ZjuWGAWBfu6; waits365s,
  then single realhistorynavigation, prints only UIexpired/empty flags and allowlisted issuer/Core
  HTTPstatuscounts. No cookies/claims/body values. Accidentally duplicatedownedPID728064 stopped
  before navigation after exactcmdlinevalidation; originalprobe alone owns browseruntil completion.

## Human MCP diagnosis / observation-only steering
- Human2026-10-06: codex MCP crash loop identified and disabled; first observe whether tool-list
  flapping recurs, revisit Code Mode hypothesis ONLY if it recurs. This supersedes active pursuit of
  the earlier unproven Code Mode cause. No new config/service/reconnect/reload/restart action.
- Native exact-project status confirms codex=disabled, four remaining MCPs connected. Service
  PID494960 unchanged. Samples07:47:10/07:47:22/07:48:37UTC (plus07:49:09 sample) show same statuses.
  CodeMode catalogs repeated: context7=2, mobbin=3, opencode=5, playwright=30. DirectOpenDesign
  project/source/brief/report/run reads succeeded; no observed list disappearance/EPIPE in this
  bounded window. Not proof of long-term stability or isolated causality. Existing approved local
  codemode:false retained unchanged; do not treat the intentionally absent CodeModeOD namespace as
  flapping, and do not re-enable codex MCP or alter Code Mode without the requested recurrence gate.
  Sanitized observationmetadata `/tmp/opencode/customer-mcp-disabled-observation-20261006.jsonl`.
- Delayed notification for oldreview47cfff0e matches alreadyverified report, not a new generation
  request. NewAFTERreview07c8cc77 terminal with real `loading-closure-review.md` SHA12e38c58:
  semanticrepair evidenced but visualclosure OPEN: after390 PNG actually768×1024, after768 actually
  1440×1000. Exactviewport binding therefore invalid; previous three-width claim is provisional.
  This is a capture-evidence defect, NOT a demonstrated tool-list recurrence/UIregression. No UI
  source repair needed; after naturalprobe ends, use ONE browserdriver and assert DOM+PNGdimensions
  before accepting freshviewportcaptures, then design-owned closure against corrected evidence.
- Finalcode reviewer ses_eefd58e5dffeUQsOwQhKG3TyKZ terminal: no demonstrated runtimeCritical or
  Important; I-1 generatedtsconfig churn alreadyassigned for ownedrestorationbeforecommit. Deferred
  M-1 unknown-error tone mismatch, M-2 deadunavailablePair branch, M-3 missing single-detail error
  cases, M-4 Site403/404 testgaps, M-5 possible uncertaintydd ATreading; no newscope/polishchanges.

## Corrected capture and refresh-persistence investigation
- Original naturalexpiryprobe completed:375s idle, normalbrowserhistorynavigation, retainedempty,
  noexpired/login banner, issuer/token200x1/Core200x3. Cookiepersistence NOTinspected; not authfix.
- Next normalSite navigation >5s later reproduces expiredUI/token400 with no corresponding Core
  ingress. This is repeated-use failure, not contradicted by first-navigation success. Authsources
  unchanged; no TTL/grace/rotation/securitypolicy change. Original recapture stopped on expiredUI.
- NormalFIELD_OPERATOR selector/PKCE reauthentication, same ownedbrowser only; correctedcapture
  `/tmp/opencode/customer-c3-corrected-loading-20261006.py` completed all3widths. LiveDOM before/after
  and intrinsicPNG synchronously bound:390x844/768x1024/1440x1000, DPR1, nohorizontaloverflow,
  visiblebusy status nodes, axe4.12.1 zero violations/incomplete, resolvesempty. Original images kept.
  Source sevenhashmanifest stillmatches. CorrectedPNG SHA:f49252a2/5f670cfc/fc4e053f; state d6cdf7fa.
  New `corrected-loading-closure-brief.md`/state/source inputs verified through projecttools.
- Coordinator error: TWO report-only correctedreview runs started with different requestIds:
  aa2ac238-13cc-4b9b-9115-694b3d6fa942→dd59baba-4f61-4d9c-8b85-cbd187d3e0f7;
  21443850-9e7b-4e4d-a2e6-6e8604e1e710→6a1c222a-069c-45db-85ba-d0ba60fc022d.
  Both distinctweb-design-guidelines/explicitcode-migration, readonlysource, outputonly same
  corrected-loading-closure-review.md. Later identical21443850payload reused6a1c222a, no thirdrun.
  Additional runs stopped; no cancellationwithoutHumanrequest. Preserve terminalreports/hashes
  and compare consistency/provenance after BOTH finish; do not infer approval from mutablefile/run.
  No UI source writers or security/config/service mutations. Duplicate coordination failure disclosed.
- Existing authhelper ses_eefd866afffeGbBGlmv0aDLe5l codeproof: RSC bareauth() returns parsedJSON
  without SetCookie propagation; actualproxy checkscookieexistence only; installednext-auth RSC
  parseSessionResponse dropsresponseheaders unlike wrappedrequest handler. Issuer rotates singleuse.
  This fits first200/later400, but outgoingresponse runtime confirmation is stillrequired.
  A later samehelper continuation errored expiredreasoning, no newevidence; no blind redispatch.
- Existing browser network metadata has normalnavigation200 and noSetCookie header, but callback
  redirect records lackstatus/allresponseheaders, so positivecontrol notestablished. Missingincoming
  Cookie metadata likewise NOTproof of absentbrowsercookie. Save only safeheader-presence/status/
  path metadata under/tmp/opencode/customer-c3-session-response-metadata-20261006.json; no values.
  Next: exact ownedbrowser passiveCDP responseExtraInfo observer/booleanonly, then normalnavigation
  to distinguish response-cookie drop from browserpersistence/race; not secondbrowserdriver.

## C3 final evidence and owned smoke lifecycle
- Correctedreview6a1c222a terminal: actualreport SHA89ef5bef984db72f6735f010157e7d0b5fe0da92580370eb18f1da810327076f;
  six openedbefore/correctedafter images intrinsicdimensions/hashes recorded. C3-A11Y-01 FIXED,
  viewportevidence defect FIXED, no new boundedloadingdefect. C1-V-01/02/03 remainpriorreviewfixed,
  not freshly reauditsettledscreens. Source sevenhashmanifest unchanged. Snapshot preserved at
  `/tmp/opencode/customer-c3-corrected-review-6a1c222a-20261006.md` before any late overwrite.
- Duplicate dd59baba stillreportsrunning with engine activewritererror; no UI/sourcewriting, no
  new generation/cancellation/restart. Do not mistake activewritererror for MCPcatalogflapping.
  Reconcile terminal explanation/reporthash before using mutablefile as finaldelivery.
- Owned smoke638648/shellsh_1101d01bc001xJ2866zUTzNWeU completed normally at1800s timeout;
  lifecycleREADY+STOPPED, no traceback. ExactPIDabsent,3237/9037 closed; no impliedrestart.
  Browserowner639634/child639656 and41525 remainowned; passiveobserver script was prepared only,
  NOTexecuted before shutdown. No runtimeExtraInfo confirmation yet; preserve authcodeunchanged.
- Restored only proven smoke-generated tsconfig changes with patch; SHA6b1807cf exactlymatches
  presmoke/HEADbaseline, incidentalcustomdist paths/formatting excluded. Existingtest-runner57d8
  continues final npmrunbuild then baseline tsc only; already983/31/fullPython evidence notrepeated.
- MCPobservation through07:59:59UTC: samePID494960, codexdisabled/fourMCPconnected; catalogs2/3/5/30
  stable at07:59:48. No newconfig/reconnect/serviceaction. Separate providermodelstream1006 and
  expiredreasoning errors are NOT established MCP listflapping; don't reopenCodeMode withoutrecurrence.

## C3 independently verified local UI bundle milestone (not full-product acceptance)
- Original independenttest-runner ses_eefd57d89ffeR1tcuIe37BQpfV terminal: fresh `npm run build`
  in apps/dashboard EXIT0, Next16.3.3/Turbopack compiled/TypeScript/static27of27,115route-lines.
  BUILD_ID TBr1c2d0HAVQ2kL_OiSOd; original and frozen customer-c3-independent-build-20261006 logs,
  frozenSHA eacd168d2361c0ce6e8ba7d9e44c557ce289024b9c6f7e0be34645e7ef46447d.
- Fresh `npm exec -- tsc --noEmit` EXIT0/no diagnostics; localexistingTypeScript/noinstall,
  baseline-types frozenlogSHA adb3afd42f92ab51feb3c3ae88aa60d2384bbffeb6a5692b8b31391695987d29.
  tsconfig6b1807cf stable before/afterbothcommands, equalsHEAD; next-env.d.ts clean. ProductionCSS
  3vccfwkve82lf.css emits lg:hidden/lg:table/sm:grid-cols-2 exactlyonceeach. All8taskfilehashes/HEAD
  stable; originalfull983/31scoped/lint0 evidence retained, no fullPython/UI suite repeat needed.
- Verifier disclosed duplicated initial build invocation: Next guard rejected overlapping duplicate;
  one subsequent cleanbuild is authoritative and no duplicate nowrunning. This is coordination
  error, not evidence of productbuild failure/tool-list flapping. No source/config overwritten.
- Independently checked inventory (not aestheticapproval): correctedreview89ef5bef matches current
  bytes, all7source entries/6openedPNG dimensions+hashes/3snapshot+3axe+statehashes agree; before
  serious2nodes→corrected0violations0incomplete, exact3widths verified. Designreview owns fixed finding.
- Ownedbrowsercustomer-c3-closure-20261006 closed normally after smokeexit; no otherbrowser/server
  touched. No currently reachable productpreview at3237; preserved screenshots and current-daemon
  designStudio remain reviewevidence, not public/client delivery. Realcustomer/device/44px/listening
  and operationalacceptance remain unverified. DuplicateODdd59baba not replayed/cancelled implicitly.
- Ruling: commit ONLY8verifiedUI source/tests +thisledger to localmain as coherent technicalbundle;
  tsconfig/checkpoint/generatedprivateevidence excluded, no push/PR/deploy/worktreecleanup. Authissue
  remains independent approved recovery work, C3overall/repeat-use/product acceptance remains OPEN.
  Aftercommit, one generated-only authdiagnostic smoke with passive completeHTTPheader metadata is
  the nextcausalcheck; no authpolicy/source change until evidence distinguishes cookie-drop/race.

## C3 UI bundle committed / refresh-persistence causal probe
- Local main commit57ae74a4a1b9465189f30ba53cbc30fc97995488 contains exactly8verifiedUI source/tests
  and thisledger. Parent16b8304, sourcehashes unchanged, indexchecks clean, postcommitGit clean.
  No push/PR/deploy/product-sliceclose; overall C3/repeat-use acceptance stillOPEN due authfailure.
- Both correctedreview runs nowterminal:6a1c222a succeeded report89ef5bef; duplicate dd59baba failed
  inactivity_watchdog600s after activewriterguard, zero observed toolcalls/output. No blindretry,
  cancellation or sourcechange. Successful frozenreview/source+openedimage evidence governsUIclosure.
- Duplicate verifier's later stray"mobbin" reply grants no newdesignscope; no Mobbin search needed.
  Original independent build/types/inventory report remains authoritative; no more verificationjobs.
- One new authorizedgenerated-only causal smoke afterC3commit, protected by task-owned flock+start
  marker. Owner scriptcustomer-c3-auth-diagnostic-owner-20261006.py, shellsh_1103f906e001rCmyJa4MI2vecw;
  private logcustomer-c3-auth-diagnostic-smoke-private-20261006.log, exactownership JSON under/tmp.
  Same loopback3237/9037; no sharedservices/accounts/livegrants/config/security mutation/install.
- Sole browsercustomer-c3-auth-diagnostic-20261006 owner849900/child849923; nativeCDP43967 verified
  from that childonly. Observercustomer-c3-auth-http-metadata-20261006.py shellsh_11040f492001tr0Yg0L8FywAvn
  PASSIVE (no navigation/cookievalues), Network.responseReceivedExtraInfo queues bound across
  redirectrequestIDs. NormalFIELD_OPERATOR UI/PKCE initialcontrol: callback302 SetCookiePRESENT;
  actual initialhistory200 SetCookieabsent. Thus exactresponseheader presence can be observed,
  unlike earlier summary-only redirectmetadata. No values/claims/headersraw saved or printed.
- One idempotent sole-driver naturalprobe customer-c3-auth-causal-probe-20261006.py launched as
  shellsh_11042850e001L5UptCUfzaqVrS:305s idle, normalhistory then settledempty/expired (real10s loading),
  subsequentnormalSite nav beyond5s coalescing; snapshots flags + statussequence + observerboolean
  metadata only. Observer stops via task-owned sentinel when probe finishes; no duplicatebrowserdriver.

### Conditional nonvisual repair declaration — implementation remains gated on causal evidence
- Requirement IDs: REQ-SEC-101/REQ-UX-101, C3-AUTH-01 repeated-use refresh-persistence defect.
- Owner module: Dashboard authentication request/response boundary, NOT Core authority/visualUI.
- Acceptance: natural accessexpiry300s followed by normalnavigation refreshes once and persists
  encrypted HttpOnly session to browser; same response's upstream RSC uses refreshed session before
  callingCore; nextnavigation after5s reuse keeps existing identity and exactgrants, no stale replay.
  Invalid/revoked sessions remain failclosed; publiclogin/API401/HIL404/sessionendpoint404 preserved.
- Contracts affected: internal request/response cookie propagation only if proved; existingPKCE,
  secure/profile/sameSite, accessTTL300/session8h/rotation/coalesced5s and all Core resource scopes
  remain unchanged. No newidentitystore, tokenJS/body/traces, authfallback or broadGETpermissions.
- Reference assets/adoption: REUSE actual Auth.js5beta32/Next16 requestwrapper cookie persistence,
  existingauthConfig/authJsCookies/Core session consumer; source refs REFERENCE_ONLY, no imports.
- Potential files: src/proxy.ts, one small internalcookiepropagation helper onlyifneeded, behavioral
  test for real auth boundary; thisledger/checkpoint. NO visualcomponents/styles, TTL/coalescingfix.
- Tests: regression RED→GREEN against actual response/upstream behavior, same-request freshcookie
  and laternavigation afterreuse; chunked/auth-vs-othercookie preservation, invalidcookie/public/API
  failclosed regressions. Mock only generatedexternaltoken exchange/time where unavoidable, not
  authwrapper/cookie effect. Independent scoped+UI suite/static/build, actualOIDC browser+reload.
- Invariants touched: INV-040 no productionplaceholder/failopen; INV-060 serverPrincipal/allsource
  grants remain Core-enforced; no body/header grantingauthority or client-provided override.
- HIL/real-device assumptions: none; generatedlocalissuer software evidence only, no customerOIDC.
- License/data implications: existingdeps only; no customer/privateexports or credentials copied.
- Rollback: task-owned subsequentauthcommit onlyifrequested; never journals/keys/grants/policies.
- Ruling: noauthsource/behavior change during305s causalprobe; exact completeHTTPmetadata distinguishes
  browserpersistence from RSCcookie-drop before selecting the minimum compatible nonvisual repair.

### C3-AUTH-01 causal evidence / behavioral RED
- Original sole probe and passive observer completed without duplicate driving. Preserved generated-only
  `/tmp/opencode/customer-c3-auth-causal-probe-20261006.json`: first expiry navigation token200,
  Core200x3, empty history; complete HTTP ExtraInfo shows document200 WITHOUT Set-Cookie.
  Callback302 WITH Set-Cookie is the positive control. Subsequent normal Site navigation after10s
  gets token400 and expired-session UI, with no new Core ingress. No cookie values/claims inspected.
- Installed Auth.js bare RSC auth() parses session JSON without propagating response cookies;
  request wrapper propagates Set-Cookie. Current proxy only tests cookie existence. Thus rotation
  consumes the single-use refresh token but leaves the stale browser and same-request cookie.
- The conditional declaration above is now activated for this proven nonvisual boundary defect.
  Preserve public login, auth route ownership (especially callback/refresh/closed session), HIL404,
  API JSON errors, opaque legacy path, Core authority and all existing TTL/coalescing parameters.
- Regression `test/proxy-session-persistence.test.ts`: real NextRequest/NextResponse, encrypted JWT
  and decoder; only external issuer/runtime fixture is synthetic. Missing response persistence,
  same-request stale/chunk cookies and invalid-cookie cleanup are the named breaks.
  `npm test -- test/proxy-session-persistence.test.ts`: expected RED 4failed/5passed; original log
  `/tmp/opencode/customer-c3-auth-red-20261006.log`. No production source written before RED.
- Next implementation: use existing Auth.js request handling for KSI session-bearing protected
  requests, transport its cookie deltas upstream and downstream; do not expose token JSON or trust
  request-supplied authority headers. Then actual generated OIDC idle/navigation/reload verification
  plus independent suite/static/build. Existing visual artifacts need no regeneration for this repair.
- Boundary implementation keeps real Auth.js response cookies and forwards only KSI session deltas
  in upstream request cookie headers; unrelated cookies/route ownership preserved. Installed Next
  cookie parser drops falsy empty value/Max-Age=0, so empty session values are treated as deletion,
  not literal upstream `undefined`. Regression now9pass with actual Auth.js wrapper/encryption.
- Vitest initially could not resolve Auth.js's extensionless Next imports in native Node ESM;
  verified installed Vitest/current docs support `server.deps.inline: ["next-auth"]`. This test-only
  configuration runs real wrapper mechanics instead of mocking the persistence under test; no dep
  install/version or product configuration change. Expected malformed-JWE test logging is muted
  only inside that synthetic invalid-cookie case, not production logging.
- Independent test-runner `ses_eefb2deceffejEA35wrhvLa31y`: scoped27/3files, full992/131files and
  lint0, EXIT0 each, once each. Logs `/tmp/opencode/customer-c3-auth-independent-{scoped,full,lint}-20261006.log`.
  Before/after source/test/Vitest hashes stable: cd779d300476c32cfc168f0f4d187a4d6ad35e9073f0eab8a65ac445e9af8a25,
  0a11685a906079d855103e7deda781071596b128181844521d55718b78e22468,
  c443feadfb15936d969373af8124ff389988db81ca9d498e3b62446235b53603. Build/typecheck
  deliberately held until owned smoke stops and its generated tsconfig changes are restored.
- Actual AFTER run reuses same owned smoke/browser. Default generated-admin login returned Core401
  because generated TEST assembly maps FIELD_OPERATOR only; expected fixture boundary, not repair
  failure/authority fallback. Normal role-test UI then selects generated field account via PKCE,
  history empty succeeds. No mappings/grants/auth/TTL mutated. Snapshot confirms field-session UI.
- Distinct passive AFTER observer `sh_1104d4537001hFO5jLq6iJEylJ` records header-presence only;
  sole AFTER driver `sh_1104fb4220017Xk83h53vcdxzi` waits natural305s then history/Site/history reload/
  Site reload, asserts authenticated state+HTTP Set-Cookie+one token200/no replay400. No concurrent
  driver or background-completion polling. Original causal BEFORE files remain immutable.
- Read-only final bounded reviewer `ses_eefb00484ffemj2StRxLAU75Ai` examines these3 task files and
  installed Auth.js/cookie boundaries; findings pending. No aesthetic/UI source changes in this work.
- Installed Auth.js runtime accepts direct request/event calls but its public TypeScript auth API
  exposes the middleware-wrapper overload instead. Use `auth(() => NextResponse.next())` with a
  missing-response failclosed guard rather than an unsafe cast/unsupported typed direct call.
  This preserves the tested response behavior; proxy hash changed after the first independent run,
  so scoped/full/lint/build/type verification must bind to the final wrapper source before commit.

### C3-AUTH-01 review disposition and actual AFTER persistence
- Read-only review ses_eefb00484ffemj2StRxLAU75Ai found3 Important COVERAGE gaps, not demonstrated
  production defects. Test-only supplement now12pass: raw downstream deletion entries for both stale
  chunks, concurrent same-stale-refresh requests yield1issuer exchange and2fresh upstreams, actual
  `/api/auth/session` GET returns empty404. Added actual missing-session refreshPOST JSON401/noLocation
  to close the API-ownership coverage caveat. These protect already implemented behavior; no new
  production fix or claim of new RED made for this coverage supplement.
- Reviewer read earlier runtime-direct-call snapshot; final source72b5e7ca changes only supported
  typed wrapper and failclosed missing-response guard. TestSHA034620470fd44254893ed7a6f26682a81219803cc491255fa8623767ffb9d943;
  Vitest c443fead unchanged. Final independent rerun binds these final bytes before commit.
- Review minor(deferred): exact `/api/auth` (no trailing slash) is not excluded; nonexistent404 route
  can cause unnecessary rotation when carrying an expiring session. No authority leakage/current
  callback/session/refresh regression; no route or behavior expansion in this repair.
- Review Ruling: do not accept the unrelated-cookie-corruption claim — installed NextRequest parser
  and serializer preserve semantic values for synthetic plus/percent/unrelated cookies after
  reparse (actual Node probe true); raw encoding differs but no current raw-cookie consumer defect
  demonstrated. Cost if wrong: a future consumer requiring original raw encoding needs its own test.
- Review Ruling: preserve Auth.js raw Set-Cookie output rather than add speculative downstream filter.
  Current session response emits only KSI session-cookie changes; callback/transient handling is
  explicitly bypassed. Filtering future framework cookie deltas without a selected contract could
  break persistence. Cost if wrong: future session cookie-scope change requires targeted review.
- Review Ruling: do not catch unexpected Auth.js throws and pass the stale request through — a500
  is failclosed availability failure, not successful authentication. Silent pass-through could repeat
  the original single-use rotation loss. Normal invalid-session handling remains tested JSON401;
  unexpected-failure UX/typed error contract is not altered from a hypothetical. Cost if wrong:
  unexpected framework exception yields unavailable request instead of the normal expired response.
- Review note: harmless maxAge0 check retained alongside actual empty-value/expiry deletion logic;
  installed parser drops0, current deletion behavior is covered by raw response + upstream tests.
- Original sole AFTER driver completed EXIT0: after natural305sidle, history after real10s loading,
  subsequentSite beyond5s reuse, history reload and Site reload all authenticated/no expired escape.
  Exactly1issuer token200 and10relevant Core200 statuses; completeExtraInfo confirms document200
  Set-CookiePRESENT at first refresh and each subsequent navigation. Original BEFORE token200→400
  and missingSetCookie preserved. No cookie values/claims inspected; generated software-only.
  Evidence `/tmp/opencode/customer-c3-auth-after-probe-20261006.json` and distinct after-http metadata.
  Final proxy72b5e7ca was in place before first expiry navigation; no production-source changes after.
- Postprobe actual browser: closed session API404; bound history BFF GET200 JSON/no redirect.
  `/api/sites` GET405 is its existing POST-only route, not a200 claim. Normal logout returns/login,
  same bound history BFF GET then401application/json/no redirect. Browser JS error listing empty.
  Screenshot `/tmp/opencode/customer-c3-auth-after-site-20261006.png` retains actual authenticated state.
- Owned diagnostic terminated gracefully via exact owner/smokePID identity+pidfd; original owner
  sh_1103f906e001rCmyJa4MI2vecw completed EXIT0. Named browserclosed,3237/9037closed; no shared service
  stopped. Product loopback preview no longer reachable; preserved screenshots/metadata remain evidence.
- Restored only proven smoke-generated tsconfig formatting/customdist additions; SHA6b1807cf equals
  saved baseline/HEAD. No tsconfig pendingdiff. Original test-runner2deceff now runs final scoped/full/
  lint/build/baseline-types once per command with distinct closure logs; output pending.
- Final closure checker returned scoped30/full995/lint0 but build1/types2: Auth.js overload inferred
  zero-arg callback as AppRouteHandler (event needsparams), parsed cookie expiry is Date|number,
  synthetic refreshPOST response is void|Response. Vitest does not typecheck, so GREEN tests did
  not close production gate. Original failed closure logs preserved; no commit/BUILD_ID claimed.
- Minimal type-safe correction (no auth policy/flow redesign): callback explicitly typed public
  NextMiddleware before wrapping; Date|number normalized by new Date; test missing-response guard
  narrows void. Final proxy23ca4a3c51450daa8a2a2189a63b9b153e1749bd8a5ea2afc73e6a768334e4e6;
  testcbc212674b4887c68f4d1e35bf18df0034ccdb3cde93a8daab13313dfcb98a9b.
- Verifier discovered another idle development server3210 sharing default.next; failed build cleared
  its artifacts. No server/service stopped or restarted. Primary read public/login once and all15
  same-origin scriptassets:200 each, development artifacts regenerated normally. No auth/cookies/
  responsebodies saved. Do not perform another default.next build while this devserver exists.
- Recovery uses existing next.config KSI_DASHBOARD_DIST_DIR/KSI_DASHBOARD_TSCONFIG_PATH rather than
  new product configuration: ignored nested isolateddist `.next-e2e/auth-closure-20261006-23ca4a3c`
  and task-owned ignored compilercopy `.tsconfig-analysis-<proxySHA>.json`; baseline config and
  saved generated next-env are guarded. Original runner2deceff executes isolated scoped/full/lint/
  build/baseline-type once each; no global.next overwrite or dependency install.
- Final production-artifact browser smoke is prepared, NOT started before successful independent
  isolated build. It reuses the approved generated Core/issuer graph, pins final source/artifact,
  runs Next start on distinct3237/9037 with fresh owned markers/logs; no shared3210 service, real
  accounts/customer data or reconstruction/authority changes. Repeat natural expiry/persistence
  against final artifact is required because source snapshot changed after the earlier browser run.
- Final isolated runner2deceff succeeded: scoped30/3files, full995/131files, lint0, isolatedbuild0
  (27/27pages, Proxy Middleware), baseline-tsc0, no diagnostics/warnings. All3source and roottsconfig
  hashes before=after. Build log SHA8f0a0bb12e47dcad0b6218004d7fdd5e383f98b81e9697b9421f9a644dd3183f;
  logs `/tmp/opencode/customer-c3-auth-isolated-independent-{scoped,full,lint,build,types}-20261006.log`.
  BUILD_ID0f2yQyJ2NCPvzv9jQsVT_ exists only in task-owned nested isolateddist; no default.next build.
- Ignored generated compilercopy unchanged by build; generated next-env changed only customdist
  references and was restored exactly to prior1862ac4b before baseline-tsc. Baseline tsconfig6b1807cf
  untouched, shared3210 server not stopped/restarted. Generated tsbuildinfo is not committed.
- Existing config uses output standalone, so final software probe runs generated standalone/server.js
  rather than unsupported nextstart. Mechanically copied unchanged public5SVGs and build/static into
  that task-owned artifact; source files/brand/assets not adapted. Ownerpins proxySHA23ca4a3c plus
  actual BUILD_ID before starting. Fresh generated TEST Core/JWKS/issuer retains exact granted field
  identity; this is not Core production assembly/customer/host-release evidence.
- Final standalone smoke sh_1105dd541001OkYkfpkIwEEf1p and named browser
  customer-c3-auth-production-20261006 owner1058971/Chrome1058993 are the only new verification owners.
  Normal role-test UI selects generated FIELD_OPERATOR, realPKCE callback succeeds, emptyhistory loads.
  Passive final ExtraInfo observer sh_1105ef8fc001r1Lj7uiSZenGwv +sole natural305s production probe
  sh_1105fb9f50010fvgfPv0ai4sI9 nowpending; no duplicate navigation/checks/cookievalues or bodytokens.
- Design-reviewed8UI source/tests exactly equal committed57ae74a; auth.ts/coalesced-refresh.ts/
  auth-cookie.ts/Core session consumer also equalHEAD. Safe12file hash snapshot
  `/tmp/opencode/customer-c3-auth-final-invariants-snapshot-20261006.json` confirms no TTL/grants/policy/
  UI/numerical changes. C4 tools/detailed implementation plans and FPC15A/B source history reconciled
  again without duplicateimplementation; C5/C6/C7 actual input/operations/contract gates still missing.

## Full-objective audit refresh — final-source verification, no acceptance substitution

Deliverables remain the complete authorized registration→inspection→evidence→V2 analysis→query→
revision-bound review→next-observation workflow, incident/tool recovery and required software evidence.
The local auth repair is necessary progress, not a replacement for this full objective.

| Explicit goal requirement | Concrete artifact/evidence | Current disposition |
| --- | --- | --- |
| Current Git/requirements/checkpoint; preserve C1/C2/C3 | main57ae74a, C1a672ea3/C27177620 ancestors; active named ledger + authority/routing revalidated; design-reviewed8files byte-equal57ae74a | Preserved; final artifact browser/lifecycle verified below, receipt and local commit follow |
| Scoped history/detail, all relevant source grants; strict V1/V2 and historical numbers | C1/C2 mounted signed-OIDC scope/cursor/detail tests and independent bare8684/122skip evidence above; Core/numerical files have no pendingdiff | Software evidence retained, not real-data/field accuracy |
| Design-tools recovery without unsupported bypass/restarts | Approved single shared restart/config recovery, actual in-place Dashboard source/read/render runs and canonical-source manifests; current tools available, no recurrent flapping observed | Resolved local capability; no extra restart/Cloud/standalone-designer fallback |
| C3 required actual-source loading/UI fixes and distinct rendered review | local57ae74a; review47cfff0e plus corrected6a1c222a/frozen89ef5bef closes C1-V-01/02/03/C3-A11Y-01 and viewport mismatch with opened-image hashes | Design-owned closure verified; UI unchanged by auth repair |
| C3 repeated-use auth response/upstream persistence | proxy23ca4a3c; real boundary RED4fail→GREEN12; final source BUILD_ID0f2yQyJ2NCPvzv9jQsVT_ standalone natural305s/4nav+reloads/token200x1/Core200x16/SetCookiepresent | Final-source software runtime verified; no customer/field claim |
| Independent related/full/static/build, real auth/API/reload | runner2deceff scoped30/full995/lint/build/baseline-types0; failed first build and cause-specific isolated recovery preserved; final artifact numeric history/detail/reload and actual logout boundAPI401/session404 verified below | Tests cover cookie transport/rotation/chunks/invalid/closed session, not customer data or field gates |
| C4 safe local verifier/recovery gaps, no duplicate bundle/OCI/degraded boot | Existing tools/external_runtime_application_bundle.py + builder/verifier; application-bundle/OCI plans and FPC15A/B reviewed above, no concrete additional approved software gap found | Local reconciliation done; protected runtime/wheelhouse/actual-host preparation remains unavailable/unapproved |
| Exposed Meta/NVIDIA/Context7 key replacement | Incident record, no secret values in this ledger/tool inputs; available prepared tools provide no authenticated account-admin rotation capability or confirmed account scope | NOT achieved; account owner must revoke/replace through authorized account session, without posting keys |
| C5 actual same-Site/WorkArea t0/t1/t2, rights/CRS/vertical/provenance/selected customer OIDC/MCP/cost | No owner-supplied selected exports/rights/customer identity/client/cost baseline; generated Core/issuer/DSM records explicitly labeled software-only | NOT achieved; required external input, not a new engineering failure |
| C6 actual contained host, signing/recovery/representative backup+restore/retention, independent customer/named acceptance | Local source/drill history exists; no approved actual host/runtime/signer/customer acceptance or representative recovery inputs | NOT achieved; separately authorized operations/customer evidence required |
| C7 selected feed/resync/data-MCP/external producer/model/input/revision contracts | ADR038/roadmap GAP04..09 remain material detailed-contract/client/operations/customer decisions | NOT achieved; no fabricated wire contract/client support/vendor claim |
| No external delivery/security weakening; preserve evidence/workspaces | No push/PR/deploy/registry/signing/live grants/policies/config activation/install/equipment/customer contact; operations goal/candidate remain cancelled/archived; dirty task-owned RED worktree preserved | Boundary maintained; retained worktree exception, no forced cleanup |

Blocking audit is finalized only after original final-artifact runtime/owned lifecycle evidence
and verified local auth commit. Runtime/lifecycle are recorded below; receipt/local commit still
remain meaningful agent-owned work. Do not close the goal for a temporary wait or recovered failure.

## C3-AUTH-01 final compiled-artifact runtime closure
- Original final production probe sh_1105fb9f50010fvgfPv0ai4sI9 completed EXIT0 with actual pinned
  BUILD_ID0f2yQyJ2NCPvzv9jQsVT_/proxy23ca4a3c, natural305s idle, first history after real10s loading,
  subsequentSite beyond5s reuse, history reload and Site reload. All4states retain context/no expired
  escape; exactly1token200,16relevant Core200 statuses; completeExtraInfo callback302 positive control
  and all4normaldocument200 responses Set-CookiePRESENT. Distinct observer completed normally.
  `/tmp/opencode/customer-c3-auth-production-probe-20261006.json` + production-http metadata preserve
  actual records, not just a success toast. Generated software-only, not customer/field acceptance.
- Postprobe actual operator changed flow on same compiled artifact: history/site-a shows cut1m3,
  fill5m3, net+4m3, uncertainty±5m3; actual detail link then exact URL/document reload then history
  link retain those same values and limitation copy. No display-derivative bytes invented; unsupported
  display remains unavailable. Browser JS error list empty. Bound history BFF200 JSON/no redirect;
  closed `/api/auth/session` GET404 with no client-token body. No private token/cookie values read.
- Normal logout button returns/login; same bound history BFF then401application/json/no redirect,
  closed session API remains404. This exercises real UI/logout/cookie clearing and authenticated
  route enforcement, not a page API shortcut in place of interaction. No mutation/grant bypass.
- Actual settled detail/history PNGs retained at `/tmp/opencode/customer-c3-auth-production-{detail,history}-20261006.png`.
  Initial click screenshot preceded confirmed detail settlement and is explicitly preserved as
  `...-early-click-preserved-20261006.png`; only post-confirmed URL/title capture is detail evidence.
  These nonvisual-repair runtime captures do not replace the previous design-owned viewport review.
- Final owned standalone smoke owner1054950/smoke1054952 exited0 after exactidentity+pidfd graceful
  termination; named browserclosed;3237/9037closed. Shared3210 not stopped/restarted. Root config,
  next-env and3taskfiles retain independent snapshot hashes. Product loopback preview now stopped;
  frozen build/screenshots/metadata remain evidence, not external/public delivery.
- Original independent runner2deceff is binding receipt JSON fields/timestamps/artifact/source/PNG
  dimensions and owned lifecycle without duplicate full tests/build/browser driving. Separate remaining
  C4–C7/external-blocker audit by existing reviewer ses_ef0063e0effergSiA5V03TYhXr is pending; it must
  identify any concrete safe approved engineering work before this goal can be reported blocked.
- Local technical C3 closure does not close/reprioritize product EXT-VAL slice or full customer
  repeat-use/field/operational acceptance. Authcommit is task-owned3source/test/configfiles +thisledger,
  excludes ignored checkpoint/compiler/build/evidence and existing dirty RED worktree. No push/PR/deploy.
- Remaining-work audit ses_ef0063e0effergSiA5V03TYhXr inspected current3taskfile hashes (match final
  snapshot), actual C4 tools/dated plans, C5 data directory (only geoid), empty Core/policy diffs,
  missing C7 selected contracts and preserved dirty RED worktree. Found no concrete safe independently
  executable approved engineering candidate beyond Primary receipt/local commit. Keys/C5/C6/C7
  require external account/input/operations/material-contract evidence, not duplicate local tooling.
- Audit read the earlier938line ledger while Primary was recording completion. Its summary-vs-ledger
  discrepancy refers to that earlier snapshot's pending rows, not a failed/missing runtime result.
  Final section and refreshed table now record original probe artifact/exit0, source/build pins,
 4states/token/Core/header metadata, actual postprobe flow and exact owned shutdown. Do NOT replay
  the completed probe because of this read/write timing difference; independent receipt reads the
  preserved original actual files. Auditor correctly declined to attest execution it did not perform.
- Final receipt runner ses_eefb2deceffejEA35wrhvLa31y verified actual original JSON fields/timestamps,
  not summary booleans: build/source match,4states correct/noexpired/loginEscapeFALSE, token['200']
  exactly,16Core statuses all200; post-expiry document records2..5 all200/SetCookie/completeExtraInfo,
  record2 timestamp >=firstnavigation. Callback302 is separate pre-expiry positivecontrol, not the
  persistence witness. Shorthand `noexpired/login` in the request means neither expired nor login
  escape; no positive-login assertion was intended. ActualFalse is the required authenticated state.
- Receipt JSON `/tmp/opencode/customer-c3-auth-final-receipt-independent-20261006.json` SHA
  15075e5547d078f9efce9c137198c4a68b2181bea166b09b29a622333f76327a;
  original production probe SHA52786a24cbcc9614b3bd25cf36237d8ceab12f703b51d7b47131e83904b704ea,
  HTTP metadata SHAd27463dad9826ede1b29b84a71b84cb6e48563267edaa8966f6a20be48dd2793.
  Owned4PIDs inactive/3237+9037+CDP39285closed, git diff-check0, source/config hashes unchanged.
  New history/detail/early PNGs intrinsically1280x633; no claim they are390/768/1440 design captures.
  Independent runner DID NOT drive Primary's manual numerical/detail/logout follow-ups; those are
  actual Primary tooltrace evidence. No aesthetic/customer/field/operations attestation inferred.

## Agent-owned closeout and genuine remaining blockers
- Full authorized objective is unchanged. C1/C2 scoped reads and bounded C3 UI/loading/auth repairs
  are locally implemented/design-reviewed where visual, independently tested/static/built, and
  exercised through actual generated OIDC/Core/compiled Dashboard navigation/reload/logout.
  All required files are complete/untruncated, with actual-source hashes/artifact/runtime receipts.
  This local auth milestone is committed only after these checks as `fix(dashboard): persist rotated
  OIDC sessions across requests`; actual resulting revision is recorded in native goal report and
  ignored checkout checkpoint. No push/PR/deploy/registry/release/operationscandidate change.
- Independent remaining-work audit found no executable approved software task beyond that commit;
  its previously pending runtime/receipt/lifecycle gate is now concretely closed above. C4 existing
  verifier/OCI/degradedboot code needs no duplicatefix. Deferred minor `/api/auth` bare-path refresh
  is nonblocking follow-up; no new product contract/route needed for current acceptance.
- Genuine required external blockers, not temporary waits/recoverable errors/effort limits:
  1. Account owner: exposed Meta/NVIDIA/Context7 keys require authorized account-admin revocation/
     replacement and confirmed account scope. No prepared admin capability; never send key values.
  2. Customer/data owner: selected actual sameSite/WorkArea t0/t1/t2 derived exports plus usage rights,
     CRS/vertical/provenance and required compatibility evidence, selected customer OIDC/MCP and
     cost baseline. No permitted actual input supplied; synthetic bytes cannot replace this gate.
  3. Operations owner: separately scoped actual host/runtime/containment/signer/recovery/representative
     backup+restore/retention authorization and evidence. Cancelled operations goal is not resumed.
  4. Product/integration owner: selected detailed feed/resync/data-MCP and external producer/model/
     input/revision contract; unresolved material requirements cannot be safely guessed.
- Actual customer/field/device/operational/named acceptance remains open; optional physical coarse-
  pointer44px and real screen-reader listening were not established by software emulation. Local
  tests/build/design reviews are not numerical accuracy, formal issuance or flight approval.
- Stop-report contract after local commit: report goal blocked/unmet with exact local revision and
  evidence above; do not shrink objective, claim full-product completion or continue a meaningless
  poll/retry loop. Next executable work is binding authorized real inputs/account completion and
  selected contracts/operations scope; only then can the remaining workflow/evidence be advanced.
