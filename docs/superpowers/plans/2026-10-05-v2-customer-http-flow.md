# V2 customer HTTP flow — bounded implementation and verification

## Authorization and design
Human instruction 2026-10-05 authorizes product code/tests/external example and isolated servers/files,
not quantitative-policy changes, operational changes, deployment, commit/push or equipment operation.
Reuse existing V2 Analysis, immutable input/evaluation/calculation records and human review patterns.
Separate operational reproduction from software flow; this task does not close EXT-VAL or platform acceptance.
Human follow-up 2026-10-06 (“그렇게 해줘 그럼”) approves preserving this verified task in a local
commit and safe remote backup on integration/readiness-20261002. This supersedes only the prior
commit/push restriction. Main merge, PR/publication, deployment, operational changes, policy/data
changes and equipment operation remain outside this action.

## Required task record
- Requirement IDs: EXT-VAL-02/03/04/05/06/08; SDP-REQ-01/02/04/05/06/07/08; ADR-037 D3/D4/D5.
- Owner module: services/core external ingress/quantity/workflow and identity; event-contracts; tests; examples.
- Acceptance: scoped customer OIDC registration, inspection, evidence remediation, V2 result/evidence,
  exact calculation/evaluation-revision review and next observation over public HTTP; negative scope,
  revoked grant, duplicate, restart and changed-input cases. Synthetic evidence never proves real export/accuracy.
- Contracts affected: additive V2 analysis review only; preserve strict V1, AP/NX V2 and prior review contracts.
- Reference assets: existing Core assembly, OIDC registry/verifier, ingress/evidence, AP/NX, durable reviews,
  local Analysis HTTP fixture/real-byte workers. No references/ runtime import or changes.
- Adoption decisions: reuse same common graph/currentness; no new Site context DB, alternate policy or engine.
- Files to change: identity/auth.py; scoped ingress/evidence guards if demonstrated missing; additive
  external/quantity analysis review module + event contract; composition wiring/routes; tests; HTTP example.
- Tests: RED/GREEN scoped HTTP checks, exact review binding/replay/corruption, loopback HTTP flow, regressions.
- HIL/real-device assumptions: none; no claims of vendor export, field accuracy or operational containment.
- License/data implications: generated tiny DSM/CSV only; no customer/private data or live credentials.
- Invariants: INV-060 organization + Site/WorkArea resource checks/404; INV-053 typed no-number blockers;
  INV-051 external lineage retained; INV-054/055 runtime/policy gates unchanged; INV-061 no AI/flight authority.
- Rollback: uncommitted task-owned diff against e82f73c; do not revert user work or modify operational files.
- Workspace: reuse task-owned linked integration-readiness-20261002, branch integration/readiness-20261002,
  base e82f73c485ecaef5e5e574bf50ae5e7a0cf62704; local main unchanged; no integration/commit requested.

## Execution checklist
- [x] C1 Reproduce scoped inspection/evidence access gaps; minimal route and resource-scope repair with tests.
- [x] C2 Add exact V2 calculation + evaluation-revision review, immutable durable history and public scoped routes.
- [x] C3 External HTTP-only example + isolated software E2E; separate privileged setup and worker actions.
- [x] C4 Negative, duplicate, restart, new-input/next-epoch checks; independent final test-runner and review.
- [x] C5 Record actual evidence, remaining operational blockers and platform follow-up criteria.

## Operational evidence lane (blocked, not a product prerequisite)
- Need matching provider.json, authority-snapshot.json, authority-key-registry.json and publicKeyFile PEMs
  from /tmp/opencode-ksi-deployment-20261004/step4/prov-test/ (root:root 0600 unreadable), plus unchanged
  full policy journal and relevant authority receipt/history. Owner supplies a narrowly readable diagnostic
  bundle preserving original signed bytes; no private keys/tokens or permission widening requested.
- Readable policy-journal and policy-journal-replay sha256 e6bb73de4df962f9ae48210069b61578cf17c4131f851ef1c84049de81c8b735:
  eight events vs journal-v7 one event. snap-check seq8 is not proven identical to deployed seq10.
- Inspector: parser identity is manifest.parser_build_digest, not worker executable identity. Preserved
  issued profile mismatches two preserved manifests; catalog lookup alone is not launch/signature proof.
- scratch stage-r2 HEAD d4375ba: stage script sha256 disk 58f6ccd083c8dda7cbad0b237a596a26a30d0d80ff4281457c287706edd8c44e
  vs HEAD 45cbfcbf0bc254059bc1ae9e0ccace7ae7602caaa74d524db37ae3513703bc54; compose disk
  e682c65d5d763f7e5c1110c5521346ddf8f0dddb1c6b212995275f0a91bbca1d vs HEAD
  4730c04d702e6b2d3f825aa02240bd36ff0867e63c201809c1b2434830c6e4d3. Both assume-unchanged.
  DUAL and external tool mount are observed differences, not adopted configurations.

## Baseline / evidence
- Current e82f73c worktree clean before task. Independent read-only baseline session
  ses_ef3ba03c4ffe4cvgJaGXuBfJWE: 61 passed / 0 skipped, 2.49s; contract-only, not customer E2E.
- Whole-provider replay attempt ses_ef3b63d6cffeLwC1UUrOOwbSdt blocked on protected fixture reads.

## Preserved successor acceptance (not implemented by this task)
Change feed and cursor-expiry resynchronization; provenance-bound limited external result ingress;
API/MCP equivalence; independent non-volume consumer of time/coverage/missing-data/change facts;
second-site repeated-cost/support measurements. Technical slice success is not platform or customer acceptance.

## Implementation evidence (uncommitted against e82f73c)
- C1 developer ses_ef39e29c9ffeNDKrszEBqD35S1: new scoped customer tests RED 403/missing helper ->
  GREEN 7; affected auth/ingress regression 163 passed, plus earlier adjacent 111.
  Exact six human route entries plus organization/Site/all-WorkArea checks; worker gates unchanged.
- C2 Primary: review-target GET and human reviews POST/GET under scoped V2 analysis routes, separate
  journal and additive contract. Target binds report/result revision, calculation, admission and two
  exact evaluation revisions; replay re-resolves independent AP/NX/intent sources. Bounded paging.
  RED missing review-target 404 -> GREEN first 6; pagination RED 3 vs requested2 -> GREEN.
  Rehashed forged-source replay rejected; wrong digests/evaluation revision conflict; MCP review denied.
- Current combined command (process umask077): pytest -q tests/contract/test_external_analysis_reviews.py
  tests/contract/test_oidc_external_evidence_scope.py tests/contract/test_external_analysis_api.py
  tests/contract/test_external_analysis_http_integration.py -> 58 passed, 42.15s.
- Baseline test_external_ai_identity_is_site_scoped_and_acknowledged_before_analysis_access initially
  failed under shell umask002: mkdir child becomes group-writable, protected authority journal loader
  correctly denies CONFIG_FILE. Unmodified test passes with process umask077; no operational chmod or
  production gate relaxation. Final checks will use private test umask and report this environment condition.
- Ruling: retain the existing task ledger rather than generate another PRD/spec/reapproval cycle; latest
  user supplied design, execution and no-commit restrictions. Review is use acknowledgement/follow-up,
  not official issuance, policy change or accuracy validation.

## Follow-up hardening (2026-10-05, Human: 다음 개발 개선을 진행)
- Resume unfinished C3/C4, not a new product milestone. Primary corrects bounded C1/C2 review findings
  in `.worktrees/v2-review-hardening-20261005`, branch `task/v2-review-hardening-20261005`, base e82f73c.
  C3 developer ses_ef3892eabffeRJaJGqRBPJ1gHm exclusively owns examples + dedicated HTTP harness/tests
  and its optional parser-test admit callback in the original integration worktree. Disjoint ownership.
- Frozen C1/C2 task sources copied as exact local bootstrap snapshots (no credentials/config copied).
  Existing original source remains untouched until verified task-owned patch integration; no commit/merge/push.
- Tests use the existing prepared virtualenv, with explicit PYTHONPATH for the isolated Core/contracts
  source and assertion of effective import paths. No dependency installation.
- Requirement IDs/owner/invariants/rollback remain the task record above; additional files:
  reconstruction/Analysis empty-WorkArea guard, review wire schema/OpenAPI, focused review tests.
- [x] H1 Uniform fail-closed area-restricted anchors (original public model already forbids empty arrays).
- [x] H2 Review stale/currentness, grant/revocation, body-authority and failure-response checks.
- [x] H3 Add canonical additive wire schema/OpenAPI and verify runtime-model parity.
- [x] H4 Integrate task-owned fixes after C3 ownership release; independent final checks and truthful report.
- Review triage: public malformed empty-anchor exploit is not established (wire model min_length=1);
  align helper defenses anyway. Malformed/unsealed source maps to typed unavailable, never numeric approval.
  Per-analysis review quotas/rotation are deferred operational follow-up, not a new limit chosen here.

## Integrated software evidence — 2026-10-06
- C3 developer ses_ef3892eabffeRJaJGqRBPJ1gHm delivered stdlib/httpx-only external consumer, public
  FIELD_OPERATOR OIDC register/grant/PUT/seal/evidence/analysis/review flow. Customer declarations and
  selectors use public WorkOrder/context and returned submissionRef; operator-only contexts/policies
  are separate test preconditions. No customer store calls, ADMIN token, or manual DB updates.
- Real generated GeoTIFF and checkpoint CSV run through parser + measurement entrypoints over UDS,
  with generated Ed25519-signed manifests and actual signature/binding admission checks. Object PUT
  forwards exact requiredHeaders/checksum but never Core credentials; wrong checksum rejected.
  First/next pair software cut/fill 0.01/0.02 m3; historical reviews are not inherited or rebound.
- Isolation limits: entrypoints are in-process, runtime identity digests simulate local builds; no Docker
  containment/deployed-executable/production-provider proof. Checkpoint declarations are synthetic,
  not an actual independent survey, despite exercising normal typed acceptance gates.
- H1/H2 RED: empty restricted scope passed vacuously; malformed target raised untyped validation error.
  GREEN isolated verification22 passed; canonical schema/OpenAPI missing-path RED -> GREEN42 passed.
  Added real evidence-mutation-before-append, fresh grants/VIEWER/revocation, body authority denial,
  immutable calculation journal, stale-target/history/idempotency checks. No quantitative policy changed.
- Hardening integrated only after original task source SHA256/bootstrap and unchanged target paths were
  checked. All9 shadow checkout changes preserved in integration target; task-owned shadow source/index
  normalized and worktree/branch removed non-forced. Unrelated worktrees/main untouched; no commits.
- Independent verifier ses_ef363340affeid8aDX95B1sLkn: affected27-file pytest301 passed/0 failed/0 skipped
  211.12s; mypy9 production files clean; ruff17 task Python files clean; git diff --check clean.
  Source19-file aggregate d9da735191d81ac6937154d19930b9626d5ab6c4d5c3d42e823f8385d55e3e10.
  This snapshot predates the post-review coverage/measurement-negative/policy-expiry test additions below.
- Final read-only reviewer ses_ef35ee667ffeJbQMPZHLSkhV4b found no critical defect; requested missing
  measurement admission negative, customer coverage/options, policy-expiry/history tests. Fix pass:
  actual captured measurement request + bit-flipped manifest rejected by production admission;
  added explicit bounded HTTP coverage-range consumer and observation-options checks (missing method RED);
  simulated clock expiry rejects new target/review409 but preserves original receipt/list/idempotent replay.
  Post-review independent final verification is recorded below; no release/product acceptance inferred.
- Additional scoped consumer defect: wait_for_analysis ignored NOT_STARTED/BLOCKED and timed out
  instead of returning known blockers. Actual customer HTTP reversed-capture request reproduced
  BLOCKED -> TimeoutError RED; minimal client fix returns the existing blocked/remediation/reassessment
  view without deciding admission or recomputing. Independent final frozen-source recheck below covers
  this method; no earlier report is substituted for its actual final run.
- Initial broad regression ses_ef3884a2bffeGD80tcH8t2TDlF: 271 failed/8299 passed/121 skipped597.62s.
  Original full log: /tmp/opencode/v2-customer-regression-20261005.log. First inspected cause is protected
  CONFIG_FILE rejection of shared nonsticky /tmp/opencode mode0775 despite owned child0700; don't
  characterize every failure from this cause without checking. No permissions widened. Final whole-suite
  rerun uses default protected pytest temp root + process umask077 (ses_ef3549fceffegyuLXMJ4FcRSbj).

## Deferred findings / acceptance boundary
- Final whole-suite verifier ses_ef3549fceffegyuLXMJ4FcRSbj: 10 failed/8573 passed/121 skipped,
  852.82s, rc1, log /tmp/opencode/v2-customer-final-all-20261006.log. CONFIG_FILE ancestor failures0.
  Six boundary tests share task-owned missing inventory entry; exact checker reproduced rc1 naming only
  external_analysis_reviews.py. Added its domains/external/quantity T3_NEW_MODULE entry to
  docs/audit/CORE_R1_MODULE_MIGRATION.json; no module move or boundary exception.
- Other failures: test_genuine_deployment_inputs_absent_stays_not_run depends on installed root runtime
  but current .venv Python3.12.13 (expects3.12.15); leave unrelated host/test unchanged. Three authority
  spawn failures used stdin main (unimportable <stdin>); verifier's file-based python -m pytest rerun5
  passed. Final rerun must use shell umask077 + python -m pytest rather than stdin launcher.
- Interim full-run snapshot19-file aggregate03aa4b8e55da3d5b5ff6361cea465e771655cef88bd712378ad65d1d38fcfc94
  excludes the later inventory entry. Final verifier confirmed consumer/test hashes already matched
  that prior snapshot; supersede earlier timing assumption, use final frozen-source evidence below.
- Review journal quota/rotation; stricter upload-header allowlist; redacted PUT-error artifact ID;
  polling backoff are deferred operational/client hardening, not silently added policy or release gates.
- Historical human reviews are immutable use acknowledgements. Expired policy, new/failed/conflicting
  evidence or changed inputs cannot authorize a new ordinary review or remove numeric-result restrictions;
  retrying an already recorded exact review only returns its historical receipt.
- No actual customer export, field/volume accuracy, HIL, deployed runtime/provider replay, UI/API/MCP
  parity, second-site labor baseline or platform acceptance is established. EXT-VAL remains open.

## Final bounded-task outcome — 2026-10-06
- Technical software deliverable verified, human/customer acceptance pending, deployed delivery not done.
  Authorized Git-only branch backup is recorded in the later section below, not deployment/release acceptance.
  Product-state remains EXT-VAL open, current product slice unchanged. This bounded task is not a slice
  closure, V2 launch decision or quantitative-policy amendment. Existing PRD/constitution/ADR untouched.
- Final independent verifier: ses_ef3549fceffegyuLXMJ4FcRSbj; final reviewer:
  ses_ef35ee667ffeJbQMPZHLSkhV4b. The reviewer important coverage findings received one scoped fix/test
  pass; no recursive reviewer/audit cycle. Residual upload-header/polling/error-detail minors are above.
- Frozen source: integration/readiness-20261002 at e82f73c485ecaef5e5e574bf50ae5e7a0cf62704 plus
  uncommitted task diff. SHA256 aggregate20-files
  10fdbfd25ce422b6d3c2639b1032e63059c642422a5abac749aee52d06013ffd.
  Algorithm: SHA256 of sorted `sha256sum` per-file lines; source list/hash evidence
  /tmp/opencode/task_20_sha256_final.txt. Primary rechecked all20 actual file hashes match this snapshot.
- Full verification command (file-based main, no authority temp paths beneath shared /tmp/opencode):
  `umask 077; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
  -> rc1, 8582 passed / 1 failed / 121 skipped / 101 warnings, 890.29s.
  Log: /tmp/opencode/v2-customer-final-file-main-20261006.log.
  Sole failure: tests/contract/test_external_application_bundle_runtime.py::
  test_genuine_deployment_inputs_absent_stays_not_run. Test checks host protected-runtime directory
  presence but gets version from suite sys.executable (3.12.13, expected3.12.15). Unchanged test/host;
  no task code involved. Environment-sensitive test follow-up needs separate scope; whole suite NOT green.
  All6 inventory and all3 stdin-spawn failures resolved without product authority relaxation.
- Focused final verification command, same umask/file-based interpreter:
  `.venv/bin/python -m pytest -q tests/contract/test_core_module_migration.py
   tests/contract/test_v2_customer_http_flow.py tests/contract/test_external_analysis_reviews.py
   tests/contract/test_external_analysis_review_contract.py tests/contract/test_oidc_external_evidence_scope.py`
  -> rc0, 66 passed / 0 failed / 0 skipped, 80.71s.
  Log: /tmp/opencode/v2-customer-final-focused-20261006.log.
- Static final gates: ruff check17 task Python files rc0; mypy9 production files rc0;
  git diff --check rc0; tools/check_core_module_boundaries.py rc0 (174 inventory records).
  Optional format observation: three touched files had baseline formatting drift and the new harness
  has format-only drift; no configured formatting gate or functional change requested. Deferred, not hidden.
- Skips121: optional model/corpus extras, unconfigured live NodeODM/S3, excluded ZoneLayer, socket ACL
  privilege and benchmark fixtures. No dependencies installed, credentials requested, live services tested
  or HIL/field gates passed. In-process entrypoint validation is not deployed containment proof.
- HTTP completed: mapped customer registration/granted PUT/seal; pending/reported inspection; actual CSV
  evidence validation/remediation; V2 result/conditions/evidence/coverage/options reads; exact revision-bound
  use review + history; next observation with no review inheritance. Negative signature/checksum/scope/
  revocation/VIEWER/body-authority/stale result/policy expiry/duplicate/restart/reversed epoch paths verified.
- Before the later Git-preservation authorization: no commits/push. Main merge, deployment, policy reissue,
  operational restart/data/permission changes and equipment operations remain unperformed. Original
  integration worktree retained; task-created shadow worktree already removed.

### Product binding (bounded API software test, not a deployment target)
- Repository/workspace: .worktrees/integration-readiness-20261002; recorded branch/base above.
- Owner/start: services/core assembly + tests/support/v2_customer_http_harness.py; generated loopback Core
  and object server are started/stopped by test_v2_customer_http_flow.py. Verify commands above.
- Product URL: no persistent server/preview retained; isolated ephemeral loopback URLs are not live links.
- Design project/storage/entry and brand: not applicable (no UI/layout/visual-system change).

### Changed file manifest
- Customer example: examples/analysis/customer_v2.py; examples/analysis/README.md.
- Review: packages/event-contracts/src/ksi_event_contracts/external_analysis_review.py;
  services/core/src/ksi_core/domains/external/quantity/external_analysis_reviews.py;
  services/core/src/ksi_core/composition/external_graph.py; services/core/src/ksi_core/composition/routes/external.py.
- Scope: services/core/src/ksi_core/identity/auth.py;
  services/core/src/ksi_core/domains/external/ingress/{external_artifact_inspections,external_evidence,external_reconstruction}.py;
  services/core/src/ksi_core/domains/external/quantity/external_analysis_api.py.
- Wire/inventory: contracts/api/openapi-core.yaml; contracts/schemas/external-analysis-review.v2.json;
  docs/audit/CORE_R1_MODULE_MIGRATION.json.
- Tests: tests/contract/{test_external_analysis_reviews,test_external_analysis_review_contract,
  test_oidc_external_evidence_scope,test_v2_customer_http_flow,test_external_analysis_api_contract,
  test_external_analysis_real_inspection_integration}.py; tests/support/v2_customer_http_harness.py.
- Record: this ledger; .opencode/working-state.md (uncommitted resumability cache, not product authority).

### Next candidates (not started / no new authorization)
1. Customer producer/export sample + capture/vertical/lineage facts + independent checkpoints:
   test actual compatibility and numeric suitability that synthetic software cannot establish.
2. Narrow owner-provided diagnostic bundle for the preserved provider/authority inputs, unchanged signed
   bytes and public keys only: recover operational replay/Inspector evidence without widening authority.
3. Later change-feed/resync + API/MCP-equivalence successor: implement preserved platform consumption
   acceptance once its bounded contract is selected; this task does not silently start it.

## Authorized commit / remote backup — 2026-10-06
- Target: current integration/readiness-20261002 -> origin/refs/heads/integration/readiness-20261002
  at existing khakisketch/ksi-site-intelligence-platform repository. No main merge/push or PR.
- Before push: exact remote main9edc4a18e873e356f5cfea7d69437f1fb5e11acd, same-name remote branch absent.
  Observed repository workflows: ci push only main / PR; civil-live-contracts manual dispatch only.
  Hosted repository hooks API reports no active push hooks; no executable local commit/push hooks.
  No automatic deployment trigger found on the selected branch. No workflow dispatched.
- Fresh independent commit-candidate verifier ses_ef3296a1bffejYsLV4CzV7Xuph: focused66 passed80.20s,
  rc0; mypy9 and ruff17 rc0; diff-check clean; all20 SHA256 files exactly match final source snapshot.
  Full suite was not redundantly rerun on identical bytes; 8582passed/1failed/121skipped890.29s
  remains the actual full-run result (known unchanged host/version-dependent test, not all-green).
- Commit includes only the20 tested source/contract/inventory files plus example README and this ledger.
  Checkpoint, caches, runtime diagnostics/keys/data/config and unrelated work stay out of the index.
  Do not infer deployability from backup success.
- Actual source commit: 8082b4c54ca62853a2725087bafc6c2527d16dbf
  (`feat(core): complete scoped V2 customer HTTP analysis flow`),22 task files,4572 insertions/21 deletions.
  Commit index matched actual22 file bytes; source20-file hash matches verified snapshot; limited
  private-key/GitHub-token/AWS-key/JWT pattern scan found no matches, not a comprehensive security audit.
- Actual push: `git push --set-upstream origin HEAD:refs/heads/integration/readiness-20261002` succeeded
  (new branch). `git ls-remote --heads origin integration/readiness-20261002` independently returned
  8082b4c54ca62853a2725087bafc6c2527d16dbf, exactly matching source HEAD. Local status clean.
- This documentation-only closeout follows the source commit on the same branch; preserve source commit
  evidence above. Remote backup is not PR acceptance, release, production configuration or operational proof.
- Next development remains unstarted. Worktree/branch retained for continued work; main and other worktrees
  untouched. No paused execution goal resumed and no deployment service started or restarted.

## Local main selective integration — 2026-10-06
- Latest Human approves only the proposed local-main selection of8082b4c anddec3c67 plus integrated
  verification. Main push, PR, deployment and operations remain unapproved; earlier9 tool/deployment
  commits are deliberately excluded. Prior "main untouched" statements describe the earlier backup action.
- Actual target: /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform, branchmain;
  clean base037d6366a4e7c496b7d6d2f045c88ce31ac2e6f2 and empty index checked before writes.
  Native session now bound to this main checkout. No additional worktree or concurrent writer created.
- `git cherry-pick -x 8082b4c54ca62853a2725087bafc6c2527d16dbf
  dec3c6706742ca890ce3026ec3a2dbee1b6e1ee9` completed without conflicts:
  source8082b4c -> mainb0e4c9f; sourcedec3c67 -> mainb291276. No branch history rewritten.
- Requirements, owner, invariants, contracts and acceptance remain the Required task record above.
  Scope is integration only, no new runtime/product behavior. Rollback boundary: original main037d636;
  use task-scoped revert if necessary, never reset/discard user work. Verification must use actual main
  source/imports and prepared main .venv; don't substitute integration branch tests for this checkout.
- [x] M1 Select exactly the two approved commits and bind actual main checkout.
- [x] M2 Independent actual-main customer/adjacent/static and full-suite integration verification.
- [x] M3 Record main result, excluded history, residual known failures and local-only delivery boundary.
- Main checkpoint read before reuse: stale idle spatial-delivery closure9edc4a18 disagreed with actual
  Git037d636; historical evidence remains in2026-09-30-spatial-data-delivery-v1 ledger. Latest Human task
  now governs main integration; product-state EXT-VAL still open. No native goal started/resumed/closed.
- Actual-main verifier ses_ef31828a0ffedlV1ZjxEx1ABdn at
  b2912769208b06a7d595491c340b238629069946 (implementationb0e4c9f29f46fb4adb5c078bef1db91e6b563153):
  main .venv Python3.12.13; Core/event-contract imports resolve under actual main root. Same20 relevant
  source/contract SHA256 values verified before/after; aggregate10fdbfd25ce422b6d3c2639b1032e63059c642422a5abac749aee52d06013ffd.
- Focused actual-main command: `umask 077; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
  tests/contract/test_external_analysis*.py tests/contract/test_v2_customer_http_flow.py
  tests/contract/test_oidc_external_evidence_scope.py tests/contract/test_oidc_route_scope.py
  tests/contract/test_oidc_auth.py tests/contract/test_external_reconstruction_api.py
  tests/contract/test_external_evidence_api.py tests/contract/test_external_artifact_inspections_api.py
  tests/contract/test_external_evidence_validations.py
  tests/contract/test_external_relative_volume_analysis_contract.py tests/contract/test_core_module_migration.py`
  (28 files) -> rc0,340 passed/0 failed/0 skipped,218.94s.
  Log: /tmp/opencode/v2-customer-main-scoped-20261006.log.
- Whole actual-main command: `umask 077; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
  -> rc1,8522 passed/1 failed/121 skipped/101 warnings,872.40s.
  Log: /tmp/opencode/v2-customer-main-full-20261006.log. Failure remains
  tests/contract/test_external_application_bundle_runtime.py::test_genuine_deployment_inputs_absent_stays_not_run:
  protected-runtime directory present but suite sys.executable3.12.13 != asserted3.12.15. Not a new
  integration regression or claimed all-green run; no host, test, privilege or installation workaround.
  Excluded tooling commits mean counts differ from the source branch; don't reuse its8582 tally here.
- Final actual-main static gates: ruff17 rc0, mypy9 rc0, diff-check clean, Core174-record boundary rc0.
  Default private pytest temp root used, no shared /tmp/opencode authority fixtures or stdin spawn main.
- Scope audit: main037d636..b291276 exactly2 selected commits and22 task paths; all9 earlier deployment/tool
  commit ancestry checks false. Main deploy/scripts/image-policy and excluded tools unchanged vs037d636.
  Git provenance kept with cherry-pick -x. Integration evidence changes only this ledger in a local docs
  closeout commit; production source stays byte-identical to the verified implementation.
- Delivery boundary: local-main source integration verified, user product acceptance/EXT-VAL/field/export
  and deployment remain open. Native session now uses main; tests did not launch any retained service.
  `git ls-remote` after verification still shows origin/main9edc4a18 and sourcebranchdec3c67; no mainpush.
- Preserve original integration worktree and remote branch: they retain9 unique unintegrated commits and
  an independent previous deployment workstream. Do not remove them as if fully merged. No other worktree
  or session modified; no external deployment/restart/credentials/policy/data/permission actions performed.
- Next candidates remain the existing actual-export/independent-checkpoint and narrowly readable authority
  diagnostics above. This integration does not authorize starting either or resuming the paused ops goal.
