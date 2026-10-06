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
