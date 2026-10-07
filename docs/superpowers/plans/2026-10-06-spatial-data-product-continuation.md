# Spatial data product continuation — 2026-10-06

Status: ACTIVE checkout task; CONS-01 verified/committed, approved data-MCP spec → written plan.
Goal: native session goal ef9e2d2c (active); entire platform objective remains open.
Base / integration target: main `579cdfa95c330dc97222537b4dcc53757ba034e8`, same checkout,
one writer; existing worktrees/evidence retained. No push, deployment or host changes.

## Human intent and authorization

The Human accepted continuing DSM/orthophoto regional-data detailed-contract work, then asked
“그래 모두 개발 개선 장기적으로 멈추지 말고 진행을 해서 제품을 완성할 때까지 해줘”.
Continue local product development, verification and task-owned commits; do not repeatedly request
permission for routine reversible engineering. Material new interfaces/data/rights/operations
decisions retain their gates. Full product acceptance cannot be inferred from local software.

The preceding suggestion incorrectly implied that no regional-data contract existed. Inspection
found approved SDP-DATA-01 and its implemented V1. Reuse it instead of rewriting the contract.
Key rotation is a separately tracked security action, not a blanket software-development gate.
No actual keys, credential files, customer private data or root-protected diagnostics read here.

## Authority and reusable baseline

- Read current 00_READ_FIRST → Constitution → Decision Ledger → PRD §1.1.1/1.1.2,
  ADR036/037/038, first-request design, repository/document routing and domain invariants.
- ADR038's follow-up explicitly supersedes the earlier documentation-only development hold.
  User instruction supplies current development scope, not missing detailed contract decisions.
- Standing product slice remains EXT-VAL, acceptance OPEN; product-state is not reprioritized.
- Activated for this task: `../specs/2026-09-30-spatial-data-delivery-v1-design.md`
  (Human-approved V1) and `2026-09-30-spatial-data-delivery-v1.md` latest 2026-10-02 execution
  append, plus `../../ops/SPATIAL_DATA_LOCAL_VERIFICATION.md` latest availability/host updates.
- V1: native-grid rectangular DSM/RGB/RGBA only; exact catalog identity/MEASURED source,
  independent grants/purposes, durable jobs/leases/fences, derivative receipt, authenticated
  whole-file download with fresh chunk currentness. No Range/resampling/polygon-mask/accuracy.
- Existing artifacts inspected: Core delivery router/README, Processing README, strict schemas,
  HTTP-only `examples/spatial-data/native_window_client.py`, consumer tests, Analysis MCP
  README/manifest and Dashboard spatial-assets metadata client. No runtime reference imports.
- Existing local V1 implementation and generated HTTP/parser/child/download/replay evidence
  are retained, NOT reclassified as deployed/customer/remote-client acceptance. Old plan's
  planning-time unchecked tasks are superseded by its dated execution append.
- Public Floreat originals were acquired in the later 2026-10-03 record. Do not repeat the
  older missing-original conclusion. Their positive inspection/host/consumer acceptance remains
  open; do not decode them outside approved containment or assume a three-epoch customer sample.
- Analysis MCP is a separate local stdio analysis adapter, not a data-MCP implementation.
  Dashboard's inspected catalog client exposes VIEW_METADATA only. No data-client authority
  to that catalog is inferred; native asset search/MCP integration needs a selected contract.

## Work sequence / process checklist

- [x] Revalidate Git/status/worktree inventory and goal; preserve closed goal and prior artifacts.
- [x] Reflect intent; classify architectural successor work separately from existing-pattern fixes.
- [x] Reconcile existing contracts/implementation before proposing a new one.
- [x] Find concrete bounded consumer gap and reproduce without private data.
- [x] CONS-01: corrected RED tests → minimal terminal-reason repair → GREEN/static/integration.
- [x] Independent reviewer and test-runner freeze/related regression/full command evidence.
- [x] CONS-01 task-owned local commit/index/hash audit; checkpoint transition follows.
- [x] Present successor choices; Human selected dedicated local data-MCP direction.
- [x] Write detailed spec; Human approved exact204c90a/SHA7ef7a677 and requested planning.
- [x] Human plan review passed atd0aac56/SHAc9efd74e; subagent-driven method selected.
- [ ] Execute approved six-stage plan, per-task review and independent final verification.
- [ ] Continue remaining authorized independent work; distinguish real-data/host/client gates
  from software/design progress, with no automatic publication or fabricated support.

## CONS-01 required implementation declaration

Requirement IDs: SDP-REQ-05/07/08; SDP-DATA-01 §6/7/8.4 safe consumer/error behavior.
Owner module: HTTP-only external example `examples/spatial-data/` (not Core authority).
Acceptance criteria: hostile reasons in FAILED/CANCELED/EXPIRED successful status responses
must never reach exception/CLI output; return PREPARATION_FAILED. Valid bounded uppercase
machine-readable reasons retain meaning. Existing HTTP-denial fallback remains REQUEST_DENIED.
Contracts affected: none; no API/model/schema/principal/state/coordinates/resource-policy change.
Reference assets: existing `_json` reason filter and `test_spatial_data_consumer.py` ADOPT.
Adoption decisions: reuse the established safe-code rule; no new service, SDK or dependency.
Files to change: example consumer, its existing contract test, this ledger; checkpoint ignored.
Tests: targeted terminal-negative/control cases, existing consumer + mounted HTTP/replay
regression, Ruff/format, independent relevant/full Python verification after source freeze.
HIL or real-device assumptions: none; generated HTTP transport only, not real export acceptance.
License/data implications: no new download, training, external AI transmission or private data.
Rollback: a later task-owned revert may restore this small consumer patch; never reset user work.
Invariant enforcement: INV-040 no success fallback/fixture in production; INV-060 safe external
error output with no raw response values; INV-020/024/050/051/053/054/055/061 preserved unchanged
because this patch touches no geometry, grants, authority, worker, policy or analysis.

## Root cause / observed evidence

Read the complete consumer and its owner tests before edits. `_json` validates error `reason`
as a bounded uppercase code on HTTP denial; `wait` forwards `body.get("reason")` unchecked
on HTTP200 terminal states. CLI serializes the exception's `.reason`, so the bypass can print
arbitrary supplied text/objects despite the documented non-reflecting error boundary.

Reproduction at base579cdfa: a real NativeWindowClient with generated HTTP status bodies and
the same synthetic hostile marker returned `untrustedReasonReflected:false` for HTTP403,
but `true` for all three HTTP200 terminal states. No actual credentials/keys were used or
printed; probe output contained state/status/boolean evidence only. Root cause is the separate
terminal-error branch bypassing the established filter, not an authority or Core calculation bug.

Test break to catch: restoring direct forwarding in wait must fail terminal safety tests.
Mock only external HTTP status bytes; exercise real client parsing/wait and CLI output. Hand
derived expected reasons, no implementation helper as oracle. Core-generated positive states
remain covered by the existing mounted fixtures rather than a fake successful TIFF inspection.

## Successor options to develop, not silently selected contracts

1. Recommended: close the bounded consumer safety gap, then specify authenticated external
   discovery/create/poll/receipt references over the current data API for one selected client.
   Avoid large TIFF payloads in MCP messages; file access must stay under current data authority.
2. Console data-job status/prepare/download UI: requires design-owned UI work and a verified
   product-linked local assembly; it cannot create grant rights or expose storage credentials.
3. Polygon/reprojection/Range/generalized raster export: separate material coordinate/rights/
   resource contracts and sample evidence; not the next implicit extension of V1.

Selecting the first option's detailed MCP client/transport/catalog permissions/output-reference
contract is still a material design decision. Ordinary fixes of the approved V1 consumer do
not authorize that decision or need a repeated scope approval. Draft choices can be prepared
while local bounded verification runs; new contract implementation must wait for its gate.

## Open evidence / approval boundaries

- Real customer t0/t1/t2/use rights/CRS/vertical/provenance/auth/cost and independent customer use.
- Actual host/runtime/signing/backup/recovery; cancelled operations goal not resumed.
- Data-MCP/client topology, feed/resync/external-layer contracts; not guessed from old analysis.
- Key exposure: owner-authorized scope/access/replacement remains outstanding; no secret values.
- No new whole-suite or completion claims yet. Prior C1/C2/C3 proofs belong to their frozen sources.

## CONS-01 implementation / frozen verification in progress

- Test-first terminal negatives cover three states ×10 hostile/missing reasons, safe-code
  controls for three states, plus actual CLI return-code/stdout/no-file behavior. Transport
  alone is simulated; real parsing/status/wait/CLI and protected generated token-file reads run.
- First RED showed25fail/9pass, but its CLI fixture passed duplicate transport arguments;
  that initial CLI assertion was a setup failure, not defect evidence. Corrected the transport
  injection, removed ONLY the task-owned three-line fix, and observed corrected RED25fail/9pass
  (terminal24 plus actual CLI arbitrary-field output). No old user work or shared config restored.
- Corrected RED command: `.venv/bin/python -m pytest tests/contract/test_spatial_data_consumer.py
  -q -k terminal` (exit1, 0.55s). All failures are expectation mismatches, no import/environment
  errors. Corrected full output retained in harness shell output sh_1109406d6001RyXnT42D7YE25U.
- Minimal production delta: wait validates reason with the established `[A-Z_]{1,80}` rule;
  invalid values become PREPARATION_FAILED. Safe codes and HTTP denial behavior unchanged.
- Primary GREEN: `.venv/bin/python -m pytest tests/contract/test_spatial_data_consumer.py -q`
  →47passed/8.33s/exit0. Ruff check and format --check of both files and git diff-check exit0.
- Frozen example SHA `b5b3a18b04958af631c7b31766986735cc3f2bb2387ba8d1e1874a1015111497`;
  test SHA `717e3e97f7b9ab7aae7f16f8865095d90f4d3a87083879b18530ec76dc1516eb`.
- Independent reviewer ses_eef6b1cacffeYPjKUHlTWQ3ayF owns read-only bounded patch review.
  Independent test-runner ses_eef6ad35affe2HOrkU5EmdwRQh owns consumer/mounted/replay, static,
  syntax and actual bare full Python suite with subprocess-local022 umask. Neither writes
  source/checkpoint/Git or performs real-data/host/account operations. Results still pending.
  Primary now investigates successor client contracts; do not modify those frozen two files.

## CONS-01 review dispositions

Reviewer ses_eef6b1cacffeYPjKUHlTWQ3ayF read full example/tests/V1 spec/ledger, verified both
frozen hashes and scoped diff: no Critical/Important findings. It did not rerun verification.
Primary dispositions for every deferred observation:

- 80-character valid-code and lowercase edge tests: nonblocking additional coverage candidate;
  current negatives cover81chars and controls preserve known code. No new valid-code syntax.
- Duplicate two-line rule: retain minimal established-rule fix; helper extraction is unnecessary
  and would expand frozen change without improving current acceptance.
- Missing reason vs explicit null: same `.get()` branch, covered behavior; not a separate defect.
- CLI FAILED only: all three terminal states share the parametrized wait branch; no missing
  separate CLI branch justifies three duplicate CLI fixtures.
- HTTP denial remains REQUEST_DENIED; preparation terminal fallback PREPARATION_FAILED is
  intentional. COMPLETED/deadline/input/token errors unchanged, not hidden fixes.
- §8.4 citation means §8 local acceptance item4 (download/consumer safety), not a numbered
  subsection. Contract references identify §§6–8; no unapproved spec numbering or content edit.
- Accepted syntax is an existing bounded uppercase code rule, not proof of a known-reason enum
  or a universal secret classifier. This patch makes both error paths consistent and refuses
  the reproduced raw strings/objects; no claim it detects every encoded/uppercase secret.

## SDP-CLIENT-01 design investigation — actual missing seams

This is read-only architectural investigation, not a new approved wire contract or spec.

| Observed source | Fact | Consequence for proposed data-MCP |
| --- | --- | --- |
| Core `identity/auth.py:690–704,843–846` | SPATIAL_DATA_CLIENT gets only READ/REQUEST, six exact data route-methods | Catalog access cannot be gained by adding SITES_READ or by using Analysis credentials implicitly |
| Core delivery `source.py:124–148` | History scope permits OPERATOR or SPATIAL_DATA_CLIENT with current Site/area visibility | A new dedicated AI identity requires explicitly designed handling, not only an MCP wrapper |
| Core delivery `grants.py:238–270` | Preparation/read require exact current grant/purpose; EXTERNAL_AI checks current Site consent | Adapter forcing purpose alone is insufficient for every AI-bound metadata response |
| Core delivery `jobs.py:282–290,374–405,537–539` | History remains visible to owner after data rights lapse; receipt remains historical while availability is denied | This is approved V1 behavior, NOT a generic-data bug. AI transport needs a separate current metadata-egress gate |
| Analysis API `external_analysis_api.py:1921–1936` | Authenticated Analysis MCP identity triggers Core consent check and acknowledgment header | Use as reference only; do not borrow Analysis principal/header as data permission |
| `services/analysis-mcp/{README.md,server.py}` | Existing fixed analysis-only local stdio surface | No current data tools or verified remote MCP/client support |

### Approaches and recommended direction (not approval)

1. **Recommended, dedicated data-AI adapter with explicit Core boundary.** Keep generic V1
   client behavior intact. Specify a dedicated scoped AI identity, Core-enforced current AI
   metadata and byte-use consent, grant-aware source discovery, and small create/poll/list/
   receipt tools over the existing native preparation jobs. Local stdio first, same installed
   SDK family where verified; no remote listener, no arbitrary fetch/SQL/raw-key/tool code.
   Larger TIFFs stay out of MCP messages; an exact guarded HTTP reference is not a public URL
   or automatic transfer to an AI provider. File-capability/resolver auth and client usability
   must be specified before advertising a downloadable MCP resource.
2. **External HTTP consumer first, Console data-job successor.** Existing preparation HTTP
   remains the common engine; add minimal product-linked operator status/prepare/download
   UX only after design-owned audit/implementation/review. This helps human operation but
   does not meet selected external MCP client acceptance by itself.
3. **Unified/remote generalized integration now.** Broader deployment/auth/transport and
   sharing contracts, larger attack surface and real host prerequisites. Not recommended
   as the first successor; never widen Analysis permissions or introduce arbitrary GIS execution.

The first approach is a material identity/data-egress/discovery/output-reference contract,
not routine local configuration. Required written design decisions include whether discovery
uses an additive grant-filtered data projection, which declared/observed fields may leave to
AI, how revoked-consent historical status is represented without metadata disclosure, exact
client/transport and no-byte MCP output semantics. New routes/tool names/TTL/production
limits/signing/provider support remain undecided; do not commit guessed runtime schemas.
Generated consumer tests and current V1 repair continue independently of those decisions.

## Independent verification recovery — no tests were run in first assignment

- First runner ses_eef6ad35affe2HOrkU5EmdwRQh terminated at its step limit: it searched an
  invented `example/test_spatial_data_consumer.py` path and executed NONE of the assigned
  scoped/static/syntax/full tests. Its summary is a verifier execution failure, not evidence
  of a missing repository file or failing product test. Earlier “verification running” was
  assignment status only and does not establish an actual pytest process or result.
- Primary immediately revalidated actual Gitmain579cdfa/status and the TWO real frozen paths:
  `examples/spatial-data/native_window_client.py` b5b3a18b and
  `tests/contract/test_spatial_data_consumer.py`717e3e97. Both present and unchanged.
  User does not need to supply/confirm already discoverable source paths.
- Cause-specific recovery: fixed-command driver
  `/tmp/opencode/cons01-independent-verification-20261006-v2.py` uses absolute paths plus
  full hashes, refuses a mismatch without discovery, runs named scoped/static/syntax/diff
  checks and actual bare fullpytest with process-local022 umask, and records exact argv,
  returncodes, log SHA256 and pre/post source/Git state. It performs no product writes,
  host/credential/provisioning/install/browser operations or new dependent tests.
- Fresh independent runner ses_eef635cfaffeTfzgntP29Vq0ds is assigned that one foreground
  driver invocation with timeout0. No search/retry/polling loop and no second test job.
  `/tmp/opencode/cons01-independent-20261006-v2/receipt.json` will carry results only after
  actual commands finish; no outcome/commit claimed yet. Prior failure evidence retained.

## CONS-01 independent closure evidence — actual commands complete

Independent runner ses_eef635cfaffeTfzgntP29Vq0ds executed the fixed driver once to completion,
exit0. Primary opened its actual receipt and rechecked current source hashes, GitHEAD/status:
two frozen files still b5b3a18b/717e3e97; HEAD579cdfa, no unexpected changes, normal checkout.

| Actual command | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/contract/test_spatial_data_consumer.py tests/contract/test_spatial_data_http_integration.py tests/replay/test_spatial_data_delivery_replay.py -q` | 58passed, exit0, 19.36s pytest /19.662s driver |
| `.venv/bin/ruff check examples/spatial-data/native_window_client.py tests/contract/test_spatial_data_consumer.py` | All checks passed, exit0 |
| `.venv/bin/ruff format --check` on the same two paths | 2files formatted, exit0 |
| `py_compile.compile(...,doraise=True)` both exact paths, explicit private cfile outputs | exit0; no source-tree bytecode write |
| `git diff --check` | exit0 |
| `.venv/bin/python -m pytest -q` (bare configured full suite, process-local022 umask) | 8719passed/122skipped/101warnings, exit0, 914.83s pytest /917.227s driver |

- Receipt `/tmp/opencode/cons01-independent-20261006-v2/receipt.json` SHA256
  `1a119e730e078113386c02c42744404f7abe26ccc35fc1229d13fb5d9bec9abb`.
- Full log adjacent `full.log` SHA256
  `182ed241e107a0301f24f3ed4c4ed66f6f2af005437e497729845c57697a5e43`;
  scoped log `d6be222708694c853595d9e4679002cd6e9d648186e96d5a13b0dca1cc2fbbe0`.
  Other exact argv/returncodes/log hashes in the receipt, all source/HEAD stable.
- No failed tests/errors. 122environment/conditional skips are recorded, not proof of those
  acceptance cases. 101nonfailing warnings include pre-existing multithreaded fork warnings
  in storage_supervisor; no unrelated repair silently bundled. No new package install/build,
  Dashboardbuild/browser, public/customer TIFF decoding or deployed-host operation performed.
- CONS-01 changes a Python HTTP example only; actual CLI hostile-output tests plus mounted
  consumer/parser/worker/download/replay and full-suite cover its changed flow. Browser is not
  a substitute/required driver for this CLI-only change. No visual-source delta or design claim.
- Local commit contains ONLY example/test/this taskledger, reviewed exact source hashes;
  checkpoint/tmp receipts/retained worktrees excluded. No push/PR/deploy. Full goal and EXT-VAL
  customer/operational acceptance remain open; completion of CONS-01 is not whole-platform completion.

## Human direction selection — SDP-CLIENT-01

The rendered question offered dedicated local data MCP (recommended), Console data UX first,
or remote MCP design first. The Human selected **“전용 로컬 데이터 MCP (추천)”** on2026-10-06.
Confirmed direction: independent local stdio data adapter, explicit Core AI identity/consent
boundary, small status/evidence/result references, authenticated existing HTTP file delivery;
unchanged existing V1/Analysis semantics and no remote service/install/deploy.

This approves the design direction and preparation of its written detailed specification,
NOT yet the particular new route/tool/schema names or uncreated implementation plan.
Next architectural work is a written contract for review, with explicit acceptance/negative
tests, discovery/metadata egress and exact result-reference semantics; no runtime privilege
change before its approval. Safe independent local engineering continues under the full goal.

## CONS-01 committed / client specification prepared

- CONS-01 local commit `ee12062b6d780c5c4f5b9b92eaa3c8056beb1e83` includes exactly example,
  existing consumer test and this ledger; index/source hashes bound to the independent receipt.
  Postcommit tree was clean; no push or retained-worktree cleanup. Scoped fixture imports the
  actual main example via Path(__file__).resolve().parents[2], not a managed/candidate copy.
- Selected direction's written proposal:
  `../specs/2026-10-06-spatial-data-mcp-v1-design.md`, SDP-CLIENT-01-AI,
  SHA256 `7ef7a677b20b04e5407796bd1a1266b8e31dac2d762fcddbd0e65b560e7c9c93`.
  Proposed299line contract: dedicated AI principal, grant-filtered discovery, Core-enforced
  current metadata egress, six fixed stdio tools and no-byte authenticated HTTP reference.
  Existing data/Analysis/grant-worker/history semantics preserved. No new runtime code yet.
- Current official SDKv2 stdio/schema/structured-output/error behavior consulted through
  Context7 (`/websites/py_sdk_modelcontextprotocol_io_v2`, official whats-new/migration docs).
  API reference is advisory, not installed2.2.0/client/host verification; no dependency upgrade.
- Inline spec self-review corrected ambiguous-grant rectangle union, Core-vs-adapter reference
  ownership and explicit typed get-wrapper; added exact frozen job-grant and response-scope
  substitution rules. No placeholders; each material proposed decision and acceptance/negative
  gate is explicit. Complete source/prose linkage verified; no product source diff afteree12062.
- HUMAN DIRECTION selection is not HUMAN WRITTEN-SPEC approval. Ask to review this exact
  proposal; only after approval invoke writing-plans and prepare its implementation plan.
  No uncreated plan approval, data-MCP activation/client install/live grant/egress inferred.

## Human written-spec approval and implementation planning — 2026-10-06

The Human selected **“명세 승인, 구현 계획 작성”** in the rendered question naming full
`../specs/2026-10-06-spatial-data-mcp-v1-design.md` at204c90a. Approval binds the original
SHA2567ef7a677 proposal, not an unseen successor. Spec status/review-gate annotations now
reflect approval; its original §1–9 contractual body is unchanged.

Implementation plan: `2026-10-06-spatial-data-mcp-v1.md`. Six sequential deliverables:
strict shared DTO/isolated identity; current AI metadata/job/byte ack boundary; grant-filtered
native discovery; dedicated finite stdio adapter; genuine generated SDK/HTTP/worker/consumer
parity + next-observation/restart; independent review/test-runner/owned-Git closeout.
This is one dependency-linked contract, not unrelated subsystems needing competing specifications.
Recommended execution is Native one-writer with independent final reviewer/test-runner; method
and written plan review remain pending. No runtime schema/source/test/activation changed here.

Evidence after compaction: Gitmain204c90a clean before these doc edits, actual worktree inventory
unchanged; product-state still openEXT-VAL. Authority/PRD§1.1.1/1.1.2/invariants/ADR036/037/038/
first-request/roadmap/repository/document routing, Core README/manifests and actual source/grant/
job/ASGI-download/credential/composition/catalog paths reread. Relevant tests/fixtures inspected,
not run again merely for a documentation stage. No delivery README or test_analysis_mcp_adapter.py
exists; use actual Core README/test_analysis_mcp_stdio.py, no invented command handed to runner.

Installed public package metadata: mcp2.2.0/httpx0.28.1/pydantic2.13.4/mypy2.3.0. Existing SDK
constructor/schema fields match low-level v2 reference. First read-only inventory stopped at
missing Hatchling metadata; safe follow-up confirmed builder absent, no dependency installation.
This blocks claiming wheel/sdist readiness, not safe source/SDK/HTTP development. Plan records
required artifact smoke/build gate and separate environment preparation if no existing backend.
Current uv lock/check/offline preference docs consulted through Context7; no lock/source/install
command executed in this planning phase.

Self-review covered spec§1–9/acceptance1–10, five review-focus failures, type/file map and proportion.
Corrected missing optional candidate accumulation budget seam, avoided repeated all-catalog source
resolution, added explicit MCP success/error schema compatibility, private metadata audit sequence/
capacity, and bootstrap config representation bounds. These are plan-level enforcement details,
not changed crop/job/Analysis/permission semantics or actual verified runtime output.

### Planning verification and review handoff

- Independent test-runner `ses_eef08feb5ffeBGw90AFNDcNdc3` ran one exact foreground
  `.venv/bin/python - <<'PY'` document-verification script (hash/HEAD/spec-body/task/source-path
  assertions + `git diff --check`), exit0. Exact stdin/original output retained in that session.
- Verified plan226lines SHA256 `c9efd74ea599632b59d90a2995cd2369d2a90d78b56e2a30b004ac4fc2195f30`;
  current approved-status spec303lines SHA256
  `09416699e5b6aa8a30cead8659e3881b3c051f3685ac874d08868262339f6c31`;
  original spec§1–9 body unchanged against approved204c90a/SHA7ef7a677.
  Full current spec is NOT byte-identical to the original (status/gate annotations changed).
- All15 named existing source/contract/test references present, tasks1–6 unchecked, five review
  focus classes, no placeholders, clean whitespace/index and no product source diff. Ledger
  verification snapshot was SHA b84952fb before adding this result paragraph.
- This is structural/source-reference evidence plus Primary plan/spec self-review only.
  No new runtime tests/SDK handshake/build/customer checks; earlier8719 suite is ee12062-consumer
  evidence, not implementation of this plan. All runtime tasks remain unfinished.
- Preserve original long-term authorization. Next gate: Human plan review + execution method;
  recommend Native sequential with independent end review/test-runner because authority files
  are shared. No automatic implementation or repeated approval-question loop while gate pending.

## Approved execution start — stage-by-stage agents

Human chose **“계획 승인·단계별 에이전트”** for complete plan atd0aac56/SHA
c9efd74ea599632b59d90a2995cd2369d2a90d78b56e2a30b004ac4fc2195f30.
No remaining design/plan gate for these six tasks. Proceed sequentially without per-task approval;
material external/security/installation effects remain excluded. Execution base d0aac56 on main.

Ruling: use current checkout/main as approved in the plan and ambient workspace policy; only one
source writer at a time — no concurrent implementation or new worktree needed. No dependency
setup/baseline rerun solely from skill defaults: actual source freeze is unchanged since independent
8719suite; fresh task tests will establish changed behavior. Cost if wrong: a scoped local task
revert is available; preserve unknown user changes and all existing worktrees.
Ruling: Primary performs Git/checkpoint/ledger, helpers source/test/report only; no helper commits
or recursive delegation — preserves integration ownership. Harness disallows model overrides
absent an explicit user model request; use native role defaults, not skill-generated model choices.
Ruling: missing Hatchling remains artifact-build gate, not a reason to install or stop Task1–5.

### Preflight cross-task conflict scan (spec binding, before Task1 dispatch)

| Tasks | Shared file/interface | Check / ruling |
| --- | --- | --- |
| 1↔2 | new identity/AI DTO/error contracts; auth→source/grant/jobs | New kind must be recognized only in exact data branches; generic permissions/history unchanged |
| 1↔3 | AssetView/Page and AI error | Strict projection/list bounds plus typed cursor conflict; no old V1 enum change |
| 1↔4 | wrapper/error schemas and six typed tool results | New error DTO must be in advertised success-or-error schema, not arbitrary JSON |
| 1↔5 | IDs/digests/ref validation | Generated TIFF/real HTTP/SDK must exercise contracts, not synthesize compliant result bodies |
| 1↔6 | immutable schema/identity diff | Freeze all Task1 paths for final independent validation; not just latest commit |
| 2↔3 | sources/grants/jobs/egress/composition | Metadata selection independent of crop geometry; discovery extends typed response gate, no geometry-based metadata shortcut |
| 2↔4 | ack and current metadata response | Every adapter success requires distinct Core acknowledgment; error never carries protected payload |
| 2↔5 | consent/credential/audit race | Barrier tests before headers; byte chunk currentness stays existing route, no downloaded-copy recall claim |
| 2↔6 | audit/source/job/currentness source | Final read-only security review plus independent tests; no unconstrained loop or live grant provisioning |
| 3↔4 | two source routes/filtered cursors | Exact path and closed projection + response scope; preserve generic cursor/metadata catalog |
| 3↔5 | discovery pages/real HTTP query | Existing fixture MockTransport drops query; actual loopback fixture must preserve query for page evidence |
| 3↔6 | bounded source candidate seam | Optional catalog budgets preserve old callers; dependency caps produce503, not empty success |
| 4↔5 | package entry/config/SDK/consumer | Source-path stdio until permitted build backend; owner config/key separate; no current shared-venv sync |
| 4↔6 | uv.lock/package/static/frame limit | Metadata-only offline lock update; no third-party drift; builder absence stays explicit |
| 5↔6 | real parity/restart evidence and docs | Generated software checks do not establish customer/client-host/export/containment acceptance |
| 1 self | strict models vs tests/auth | Real model/registry/schema assertions; no live token, source authority or widened original allowlist |
| 2 self | preflight vs final send/audit | Guard checks source/current READ independently of byte availability; refreshed credential outside coordinator locks |
| 3 self | list/detail/limits/ambiguity | Empty scoped page vs safe404/ambiguity; filtering before page, no rectangle union; finite pre-accumulation seam |
| 4 self | config/bootstrap/transport/output | Required positive finite owner limits and fixed representation caps; output schema covers errors; no endpoint retries with new keys |
| 5 self | source fixture vs genuine TIFF | Use actual generated parser/worker plus SDK/HTTP; synthetic-report-only fixtures cannot stand in for parity |
| 6 self | verification vs readiness | No UI delta; independent source/API/stdio checks + separately required build, no product-state completion |

Plan-scoped ignored scratch: `.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/`, marker matches
this plan; existing two other scratch plans/.gitignore preserved. Its progress.md is a cache of
this durable task record, not competing product/task authority. Task1 brief generated by installed
skill script; global constraints supplied alongside it. Task1 owns only new DTO/schema/two tests
and canonical auth.py. No other source writer until developer returns.

### Task1 first implementation / review and bounded repair ruling

Developer `ses_eef02487cffep60RkdP6xj1Vyq` produced exactly Task1's five owned files, no commit.
Original reports/logs in plan scratch. RED missing-new-module collection error is genuine greenfield
RED, not test fixture failure; GREEN71 and new+named old regressions292/4.94s; scoped Ruff/format/diff0.
Primary checked actual logs/owned hashes; original source unchanged outside allowed auth/newfiles.
Reviewer `ses_eeefca156ffej0cr7C7oZ9oLQt` judged spec compliant/quality accepted with four minor notes
and five cross-task cannot-verify items. Review source package captured all new files, not only gitdiff.

Primary technical dispositions before closure:
- M1 verified: new `_ai_native_profile`/`_ai_capture_interval` duplicate V1's identical validators.
  Ruling: eliminate copied rules by reusing those existing sibling-package validators directly
  from spatial_data.py, with tests pinning original behavior; no V1 file/API change needed.
  The review's blanket “do NOT import private names” is not a product boundary inside this same
  contract family which already imports private _spatial_data types. Cost if wrong: localized
  import refactor, not additional public geometry engine or silently divergent profile.
- M3 verified: canonical-path equality alone allows a malicious Site segment containing slash/
  query if it supplies a correspondingly constructed path. This contradicts spec§5's strict
  no-arbitrary-path descriptor. Ruling: add path-safe segment constraint to NEW file-reference
  Site/area fields and negative tests with matching crafted path; keep old V1 DTO fields unchanged.
  Producer/transport checks remain necessary, but are not substitute for new descriptor validity.
- M2 optional reversed capture/flight-route coverage deferred; reviewer found no present defect.
  M4 original missing-module RED accepted; subsequent existing-module fixes use behavioral RED.
- Cross-task items: code union T4, schema/HTTP composition T2–4, egress/rights T2–3,
  discovery/cursor T3, full SDK/API/replay/frozen independent T5–6 are required remaining work,
  not evidence Task1 supplied runtime consent or completed data-MCP.

Fix round1 resumes original developer only, owned newDTO/newtest/schema (if constraints change).
Regenerate schema mechanically; scoped re-review follows. Task1 not complete/committed yet.

### Task1 verification closure — contracts and isolated identity only

Fix round1 developer retained all owned-source scope; genuine behavioral RED10fail/2pass for
matching hostile descriptor path→GREEN304. `_native_profile`/`_capture_interval` reuse leaves
V1 immutable, generated schema adds only new descriptor scope patterns. Scoped reviewer
`ses_eeefca156ffej0cr7C7oZ9oLQt` marked M1/M3 ADDRESSED with no new defects; M2 optional
reversed-capture/flight-negative test breadth deferred for final triage, not silently closed.

Independent test-runner `ses_eeef37cfdffebqpwGftl0IyoK5`: exact `.venv/bin/python -m pytest
tests/contract/test_spatial_data_ai_contracts.py tests/contract/test_spatial_data_mcp_identity.py
tests/contract/test_spatial_data_permissions.py tests/contract/test_analysis_mcp_identity.py
tests/contract/test_spatial_data_contracts.py -q` →304passed/0skip/4.93s. Ruff check/format on
newDTO/auth/two tests and gitdiffcheck all exit0. Five owned hashes and d0aac56 HEAD unchanged
before/after. Primary read receipt argv/results and checks retained original log hashes.
Receipt `.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-1-independent/receipt.json`;
the directory is ignored task scratch, durable exact frozen hashes:

| Task1 source | SHA256 |
| --- | --- |
| packages/event-contracts/src/ksi_event_contracts/spatial_data_ai.py | 802251dd58de60aba340b2a2da6afcda6c7deabc31c4297ccaa0489a149c89b6 |
| contracts/schemas/spatial-data-ai.v1.json | bc81d67d272a8cf9b698e1d88c1217785dc794067403d2226baba195eeb7dc2c |
| tests/contract/test_spatial_data_ai_contracts.py | d921ef8508d9cc2b4f41f4b3f05cb7ee30cb5262a6b2095a5d299b6ea1d1f8e8 |
| tests/contract/test_spatial_data_mcp_identity.py | 2a44201d3366281ea2c675ef2b79c2b25675d024215f97412151df826f2578ae |
| services/core/src/ksi_core/identity/auth.py | a322a2e13c3e2bc463b2bedfb319806787be138817bfb27b49590c0eb10ebeea |

Task1: complete at scoped source level after Primary owned-index local commit. No running new
adapter, discovery/egress implementation or provisioning/readiness implied. Required cross-task
checks remain specifically assigned T2–6. Product EXT-VAL and long-term goal remain open.
Resume revalidation: main/d0aac56/no extra productdiff; actual checkpoint/parent ledger/plan read,
latest approval reused. Authority unchanged since approved plan, relevant product text reread;
checkpoint's stale 'no source writes/Task1 dispatch next' corrected at this closure boundary.

### Task2 recovery and first security review — not accepted

Task1 committed374849a86a063380602ca25f92440d6e067f7ee3. Task2 developer
`ses_eeeef962effeS7teCU01Jo77xy` stopped after11owned source/test edits with provider error:
only auto tool_choice supported. Same-session resume reproduced it, no report. No unverified
commit/reset/installation/provider-config change. Fresh bounded recovery
`ses_eeed879dfffeYkRttN7Rx4WmN9` inspected existingdiff (not greenfield rewrite), produced report;
new13/old6files211pass/newsource3mypy/Ruff0. Original RED unknown; historical374849a overlay
failed13missing-module, explicitly not originalTDD or changed-behavior proof. Source preserved.

Reviewer `ses_eeed506a2ffe1uMG2tybaQZPq5` rejected Task2: C1 cancel mutates before path binding;
I1 file-route AI handling evidence; I2 metadata selector dead/untested; I3 READ+PREPARE issuance/
retry check; I4 hard-failure list test. Current11hash freeze and full reviewpackage in ownedSDD
scratch. All claims remain provisional pending repair/review/independent scoped verification.

Primary source checks/rulings (spec and existing V1 are binding, not report):
- C1 confirmed: cancel API calls jobs.cancel before comparing requested path. Fix pre-mutation
  exact job/path scope, add different permitted scope test with no journal mutation.
- I1: approved plan says byte errors remain V1; no obligation to rewrite byte error envelope.
  Ruling: preserve V1 byte error handling; explicitly enforce AI scope/missing-egress failclosed
  at file route and add GET/HEAD revoked consent, missing wiring, scope + noack tests. Current
  indirect jobs.get gate protects rights, but route-level evidence is required.
- I2/M3 confirmed: select_metadata_current unused; job metadata instead re-plans native pixels.
  Wire unique READ selector into actual metadata, keep exact frozen grant equality/revocation
  semantics, test subpixel rights/duplicate/CRS/location/dependency limits without crop planning.
  Ruling: licenseProvenanceDigest is the authoritative sealed-grant fact; no matching field exists
  on SpatialDataSourceV1 and no license policy-service invented. Validate sealed current grant +
  exact frozen-grant equality (license included), test tamper/replacement; discovery uses this
  same recorded digest. This is not verification of actual license or export compatibility.
- I3 partly misstated: existing retry calls _current, so revoked-grant retry already denies.
  Real gap: it checks PREPARE only, no READ/unique metadata authorization. Add direct store tests
  and enforce both on new/retry before journal, no grant resurrection or generic-history change.
- I4 confirmed coverage gap: hard-failure list test currently only tests revocation filtering.
  Add genuine sealed/currentness/resource failure, not unasserted name-only proof.
- Primary P1 reproduced: metadataResponse prepares content=b'', Starlette advertises Content-Length0
  then sends322JSONbytes; successful local ASGI framing is invalid for real HTTP. Fixture import
  first lacked tests/support path and was corrected before genuine reproduction, no initial
  failure counted. Fix success framing, test exact serialized bytes/contentlength on HTTP.
- Primary P2: metadata max_json_bytes alone lacks finite auth/recheck/audit/send duration or
  disconnect/cancellation handling; final _recheck is awaited worker-thread handoff, rather than
  plan's synchronous local check immediately before start. Add bounded publication deadline from
  existing explicit policy, preserve no remote credential I/O under coordinator, final local
  immediate checks and cancellation/deadline/after-audit barriers. Disclose unavoidable transport
  handoff window; never claim sent-data recall or global atomic authorization.
- Reviewer M1: audit means authorized publication attempt at audit time, not client receipt;
  late denial can keep attempt event. Document no delivered-byte metadata claim. M2 reason/status
  mapping advisory; M4 cursor-denial audit union T3 decision, no old enum modification.
- Unchanged source.require_current is locally bounded genuine revision/report/WorkOrder recheck;
  credentials.resolve genuine bearer refresh outside coordinator; bytesprepared.authorize path
  uses current credentials + guarded job output. New route/token-expiry tests strengthen this
  evidence now, generated realSDK/HTTP receipt/bytes parity remains mandatoryT5.

Fix round1 recovery developer resumes, same11owned paths only; originalTask2 child cannot return.
Behavioral RED for actual shortcomings first; same scoped tests/static + targeted re-review.

### Task2 fix1 reviewed; Primary independently found remaining load-bearing gaps

Recovery developer fix1: 16behavioral failures/12controls→41newpass,211existing +783related,
11fileRuff/format/new3mypy0. Scoped reviewer ses_eeed506a2ffe marked C1/I1–I4/P1/P2 addressed.
Primary accepted C1/filegates/selectorwiring/framing repairs based on actualdelta but rejected
P2 closure and new-issue uniqueness closure after direct synthetic reproductions:

- P2 STILL OPEN: `_check_deadline` only checks injected wall-clock after each completed await;
  stalled auth/audit/send is not awaited with timeout. With0.01s configured deadline, blocked
  send still runs until outer0.1s testdriver cancels. No self-timeout or disconnect interrupt
  during await. Passing fake-clock-advance checks do not prove finite waiting. Ruling: real
  monotonic publication budget + remaining-time bounded await/send and disconnect racing;
  keep injectableUTC for authority timestamps, check local CPU budget immediately after final
  synchronous recheck; disclose no CPUhardpreemption. Validate finite deadline (infinity currently
  accepted constructor), cleanup/cancel watcher/tasks, bound refusal sends too. Tests must stall
  actual awaits with clockconstant, not merely advance fakeclock/threadpool-count assertions.
- P3 OPEN: newAI issuance selects PREPAREgrant then checks membershipREAD, but never uniqueREAD
  metadata selection before append. Primary provisioned sameasset PREPARE+READ plus READ-only
  subpixel grant: jobs.issue appended1job, require_ai_metadata immediately denied AMBIGUOUS_GRANT.
  Ruling: require current uniqueREAD selector equals exact PREPAREgrant before sweep/issuance,
  new conflictingREAD cannot create unreadableAIjobs; generic issuance unaffected. No rectangle
  union or scopes rewrite. This enforces already approved current metadata eligibility, not new
  product direction. Regression must assert nojournalappend on read-only overlapping grant.

Fixround2 resumes recoverydeveloper, same11paths. Reviewer green is advice, not acceptance;
future re-review must compare actual stalled behavior and direct create/store denial, not claims.

### Task2 fix2 independent validation — two publication defects still open

Fix2 new52/old211/related783+static0; reviewer again marked P2/P3 addressed. Independent runner
`ses_eee8899d7ffeX0iTUza6tSBlem` actually ran567scope tests +11fileRuff/format/new3mypy/diff:
exit0, 5RuntimeWarnings, no skips; all source/HEAD stable. Complete stdout unlike developer's
tail-only newtest log retained at task-2-independent-fix2/cmd01.log, receipt exactargv/hashes.
Original first driver green but receipt regex failed; same argv rerun produced finalreceipt;
neither run is finalTask2closure. No fullrepository/customer pass inferred.

- P4 OPEN: five new RuntimeWarnings `SpatialDataAiMetadataResponse._refuse was never awaited`
  at metadata_response.py315: coroutine constructed before _await_stage rejects exhaustedbudget.
  Ruling: lazily construct awaitables only after positivebudget/disconnect precheck or explicitly
  close unstarted coroutine, with real warnings-as-errors targeted test + fullscoped verification.
  Do not silence runtimewarnings or hide closedbudget cleanup.
- P5 OPEN: fix2 bounded send introduces ensure_future scheduling after local finalgate. Primary
  scheduled rightsrevoke via call_soon from2ndrecheck: rightswere revoked before firstsend, yet
  ASGI status200/ack/protectedjobIdJSON delivered. Initial one-off script had nonlocalsyntax
  error, corrected before genuine reproduction; do not count setupfailure as RED. This is
  application scheduling before transport, not uncontrollable networkbyte recall window.
  Ruling: bounded header-send coroutine owns final synchronous authorization/digest/bytebudget
  check immediately before its actual send call (not before scheduling that coroutine). Add
  deterministic late-revoke barrier proving no protectedsuccess; retain finite sends/cancellation
  and no remoteauth under coordinator. Unavoidable actual awaitsend handoff remains disclosed.
- P2 receive-failure deviation: watcher silently stops on exception. Ruling: brokenreceive is
  disconnect/failclosed stop, not excuse for unprotectedcontinuedsend; testfixture absence of
  inbounddata must block on Event, not throw interpretedashealth. Same finite error/success budget.

Fixround3 same recoverydeveloper, onlymetadata_response/newtests (egress signature if necessary)
within11ownedpaths. No unverifiedstagecommit, no provider/modelchanges, no fabricatedskips.

### Task2 fix3 residual byte-handoff defect — bounded fresh repair

Fix3 new60RuntimeWarning-aserror0warnings/old211/related783/static0; reviewer scoped P4/P5/
brokenreceive addressed. Primary verified actual code separates protected JSON body handoff
after guardedheader task. Direct sendcallback revokes rights immediately after authorized
http.response.start: subsequent bodyphase still emits jobIdJSON with rights already revoked.
This is not recalling sentbytes — NO metadata bytes had been handed to transport at revocation.

P6 OPEN: bodystage needs same synchronous rights/digest/size/deadline recheck inside its bounded
sendcoroutine immediately before actualprotectedbody handoff. On afterheader refusal, no newJSON
error, no successful EOF; raise/terminate according to existing response semantics. Header can
already have an ack valid when sent — must not claim it means laterbodydelivered/rightsremain.
Add authentic late grant/consent/lane-revocation bodybarriers and brokenreceive test (reviewminorT1).
Ruling: fresh bounded developer round4 from current source/snapshots, modelnative defaults per
higher harness rule (no arbitrary override), same11pathownership; no greenfield redo or extra
Task2publiccontract. Preserve all earliercorrections/TDD/evidence. NoTask2closureyet.

### Task2 fix4 bodyrights repaired; bearer refresh final gap

Fresh developer `ses_eee663f40ffear68c6B44LBF9I`: P6RED3fail61controls→new64pass0RuntimeWarnings/
old211/Task1net304/static0. Onlymetadata_response/ai_egresstest changed,9pathsunchanged.
Body now rechecks current localrights/digest/time just beforehandingbytes, no errorJSON/EOF on
afterheaderdenial. Developer disclosed body still uses late_principal capturedbeforeheaders.
Primary tested genuine AuthRegistry revocation in actualsendcallback afterauthorizedheaders:
registry emptied but protectedjobIdJSONstillhanded. Earlierheaderackcannotauthorize laterbytes.

P7 OPEN: genuine requestcredential refresh offlocalcoordinator before bodyfinal localgate;
late identity/scopes/expiry/revoke must be reflected. Ruling: bounded asyncbodycredentialrefresh
then synchronous localbodygate with newprincipal immediately before actualsend, same existing
time/byte limits, no production/authcontract expansion; add tokenrevocation/expiry/scopechange
barriers. Afterheaders refusal ends transport withoutJSONerror or successfulEOF. No tokenlogs.
Fresh boundedround5 developer, same2fileownership +11snapshot, no arbitrarymodeloverride,
no stagecommit before scopedreview/independentverification. No broadredo or repeats of783suite.

### Task2 scoped closure — Core AI metadata boundary verified

Fix5 freshdeveloper `ses_eee5f4892ffetwKrHc2438h7vs`: P7behavioralRED4fail66controls→new70pass,
211existing/Task1304/static0. Finalscoped reviewer `ses_eeed506a2ffe1uMG2tybaQZPq5` fixes4+5
P6/P7/brokenreceiveT1 ADDRESSED, no newImportantbreakage. Reviewed sequence includes permissions/
uniqueREAD/frozengrant, auditattempt, boundedlazyawaits, guardedheader+body, freshbodycredential.

Fresh finalrunner `ses_eee593e99ffe7fv5Up2GCJnO2M` looked onlyCodeModecatalog, claimed no native
shell, ranZEROchecks: no pass/evidence. Original successful independentrunner
`ses_eee8899d7ffeX0iTUza6tSBlem` resumed with exactnative-shell script, no search/credentials:
`.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-2-verify-final.py` once.
Driver actual argv: pytest ai_egress/jobs/api/current_grants/real_credential_audit/asgi_stream/
assembly/ai_contracts/mcp_identity/permissions/analysis_mcp_identity/contracts (12exactpaths)
`-q -W error::RuntimeWarning` →585passed/0skip/0warnings/37.99s. Runner summary called13files,
but actualreceipt/scriptnames12files; actualargv/results govern. Ruffcheck+format11sourcefiles,
mypynew3, gitdiffcheck all0. No source/HEADdrift beforeafter against fix5freeze.

Primary read receipt/original loghashes/currentSHA, not just childsuccess. Receipt:
`.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-2-independent-final/receipt.json`
SHA256d899b74b29c63a8e8d40c693a90584a2447cfb33d44e059d23118e722b1fa6ad;
fullpytestlogSHAe0ac94aa0691af608c6c06945ed27972d5d6143a4ce169c7c669d201343f7ca8.
No initial5RuntimeWarnings remain; failedchecks were repaired ratherthan suppressed/deferred.
OriginalTask2TDD gap remains disclosed, subsequentfivefixrounds carry actualbehavioralRED.

Task2: complete at scopedCore sourceboundary after Primary ownedcommit; no stdioadapter/discovery
or actualSDK/HTTPderivedbytesparityyet. GenericV1/Analysis regressions included; defaultclosed
sourcegraph unchangedunlessexplicitlocalgraphsupplied. Local source/core checks are not remote
hosting/customer/export/license/containment acceptance; fullrepository/fullMCP checks requiredT6.
Audit is authorizedpublicationattempt, not receipt; canceledthreadwork may finish its audit;
unavoidable remotecredential/CPU/actualtransport handoff window is not globalatomicity/recall.
Next Task3 will use tested uniqueREADmetadata selector + exact identity and current response
gate for filtered assetprojection/cursors, never cropgeometryasmetadataauthorization.

### Task3 start — committed boundary handoff

Task2 committedbed4d9ce5b38bfcebdb86954627246571583bb5b, source/plan/ledgeronly13files;
Gitclean, checkpoint keptignored. Task3base/integrationmainbed4d9c, soledeveloperwriter.
Ruling: add delivery/jobs.py to Task3 exactfileownership because approved Task3Step5 requires
AI-only strict snapshot pagination for jobs, while its Files paragraph omitted that existing
owner. No new route/policy/publicschema scope; preserve generic cursor semantics. Costifwrong
localizedAIcursorimplementation can be reverted, never missing approvedcurrentness test.
Ruling: reuse Task2 ai_egress typedresponse final credential/header/body gate + exactmetadata
selector, extend by typedasset/page methods ratherthan copyanother guard/byte engine.
Task3 uses authentic syntheticreports for catalog/sourceauthority contracts, not SDK/TIFF
parity/hostacceptance; genuine generatedinspection/worker/consumer requiredTask5 stillpending.
Originalprovider/securityfixloops are complete history, not permission to repeatTasks1/2.

### Task3 partial execution recovery — 2026-10-07

Revalidated main/bed4d9c/worktree inventory/checkpoint/taskcache/productstate and current approved
authority. Task3 child `ses_eee51a5b0ffeYWV0ZJTDEQ3919` wrote source.py/newasset_discovery/newtest
then returned provider tool_choice protocol failure. Same-child recovery once reproduced that
environment error; no report/pass/commit. task-3-red.log remains, source writes preserved.
Ruling: fresh bounded recovery developer completes actual unfinished Task3 from current diff,
not greenfield rewrite or completed-stage redispatch — provider failure blocks original child,
not product requirements — cost if wrong is a scoped reversible repair; no provider/model/config
changes, installation or unsafe state reset authorized. Primary retains Git/checkpoint/ledger.

### Task3 first report/review and repair ruling

Recovery developer `ses_eee39259effeVnIJuQEuI1kxBH` found preserved original implementation
complete (10sourcepaths, parentledger is Primary's change); no own source edits. New10/sixfiles93/
egress+Task1subset153 passed, scopedstatic0. OriginalRED10missingmodule/wiring retained, not
misrepresented as complete negative coverage. Current task3freeze hashes all10sourcepaths.
Reviewer `ses_eee35557fffeUm44fQZ4OzE607` required stale API sync-count repair and one consistent
`now` per list. Source locations in report use package line numbers, not actual file lines.
Ruling: add test_api_contract_sync.py to bounded Task3 ownership; verify actual failingcount
then assert complete13opt-in operations + newroute/schema concordance ratherthan merely hide
failure — approved two GETs require this existing conformance change, reversible test-only.
Ruling: pass list(now) into _resolve_for_list grant check; egress supplies fresh now per stage,
one projection evaluates one authority-time, not differenttimes per candidate.

Primary targeted current code checks found three additional load-bearing gaps:
- P1: _list_ai lacks require_ai_scope independently of entries. Genuine empty jobpage prepared,
  consent withdrawn before finalsend still gave200/ALLOWED. Fix common fresh AI scope/consent
  before enumeration even empty/all-filtered pages, directstore+egress barrier tests; generic
  history unchanged. This is already explicit Task3 empty-page snapshot/currentness acceptance.
- P2: catalog.items invokes _project_revision returning complete tuple before max_items/max_bytes
  checks; append then checksbytes. Required accumulation bounds must apply within per-revision
  projection before result growth, singleton bytescount included; omit optional limits preserves
  existing callers. New projection-specific failure cannot masquerade as denied/emptysuccess.
- P3: final newasset recheck lambdas call discovery.get/list, then resolve_candidate→
  public_snapshot_bounded→policyregistry._select→authority_port.resolve. This is externalport
  resolution inside synchronous lastheader/body checks, not boundedlocal currentness. Ruling:
  separate bounded detached remote preflight from typed final local source/grant/lifecycle/page
  re-projection; finalgate uses genuine local owner/report currentness, no externalport. No fake
  Principal/authority or stalebodyacceptance; callbackauth outside coordinator/async boundedstage,
  no unsafe generic publication callback. Test externalport resolver forbidden at final local
  gate + revocation/report/lifecycle change still refuses protectedbytes. Existing current source
  localreport method explicitly owns final recheck, no new publicwire/policy authority allowed.

Reviewer CannotVerify dispositions: select_metadata_current sealeduniquegrant/indexbudget and
source.require_ai_scope internals read at Task2, unchanged; final guardedresponse/header/body
auth/audit boundedness verified Task2 sourcefreeze, require same inputs for new typed assetpath.
Exact new schema/model/OpenAPI and actual logs must pass independentTask3conformance, not inferred
from refs. Customer load/performance and actualSDK/TIFF parity deferred explicitT5/customergates.
Fixround1 same recoverydeveloper, genuine behavioralRED then scopedtests/static and re-review.

### Task3 fix1 review and final snapshot/conformance check

Fix1 recovery resumed after provider interruption without reset: RED6/4controls→327scopedpass,
Ruff/format/diff0 +7filemypy0, fullstdout retained. Reviewer marked I1/I2/P1/P2/P3 addressed.
Primary confirmed count/time/emptyconsent/generator/localremote split in actual source; initial
10hashsnapshot validated, current12freeze includes metadataresponse/synctest. ReviewminorM1
port tests only upper-bound total resolvercalls; strengthen phase-attributed zero finalcalls
including historical resolution in this stage, not claim wholehost containment.

P4 conformance: asset_api responses use old SpatialDataErrorV1 while newroute runtime ai_error_response
and OpenAPI refs use SpatialDataAiErrorV1 (stale reason absent oldenum). Ruling: same newroutes'
declared error model must match actualtypedfamily; test mounted router error-schema aliases/reasons
against committed newAI schema, not only2xx/count. Genericerror/runtimecontracts unchanged.
P5 snapshot verification: fix1 skips unresolvable preflightcandidates without noticing local
report/seal readiness changes. Reviewer accepted disclosed under-admission, but approved current
permitted-snapshot contract needs evidence when a granted candidate changes readiness before
handoff. Ruling: prove samecandidate locally arrives report/seal with relevant currentgrant after
preflight causes stale/refusal (not incompletecursor); if reproduction shows omission, bind bounded
local candidate/report state for that classification and recheck changes before headers/body.
Keep no externalport in finalgate and no deniedcounts in wire, no invented policyservice.
Purely ungranted unrelated source drift need not become data-sharing permission or payload.
Fixround2 targeted to actualrefusedcase/conformance; no broadredo/currentpublicwire changes.

### Task3 fix2 returned; bounded local inspection fingerprint still required

Fix2 developer RED2/4controls (fixture setup failures excluded)→331scopedpass/static8typing0;
newrouterAIerror family +phase-attributed zero externalport gates +grantedseal-readiness409.
Developer explicitly left pure report-arrival for already sealed unmeasured source undetected:
catalog readiness class has no report-state identity. This was requested P5, not an optional
feature, so no Task3completion accepted. No need for external port in final local gate.
Ruling: extend Task3 ownership by one canonical owner file ingress/external_artifact_inspections.py
for a bounded local exact-subject retained-state fingerprint (not authority/metadata API).
Source resolver re-establishes real scoped subject before using it; fingerprint merely detects
local mutation of inspection records/report/seal, never authorizes source/READ or replaces genuine
local currentness. Finite max_pending_records, dependency fail-closed, no new runtime/config or
publicwire. Cost if wrong localized read-only helper reversible; no provenance meaning change.
Fixround3 close actual pure-report readiness barrier with genuine owner mutation and zeroport
final gates; scopes/typed projection/shared authority unchanged. Schema/conformance gates must
stay strict. One sourcewriter, Primary Git/ledger, no packageinstall or broader code reshuffle.

### Task3 final review returned; cursor evidence before closure

Fix3 RED sealed-unmeasured/report-arrival200 omission→409,333scope/static9mypy0; finalscoped
review `ses_eee35557fffeUm44fQZ4OzE607` marked P4/P5/M1 addressed, no newfindings. Primary
inspected coverage: sharedstrictcursor rawJSON cases and AIjobsnapshot transitions lackdirect
Task3 tests; decode accepts arbitrary nonempty snapshot strings and emits409 ratherthan malformed
hashshape422. Ruling: complete Task3Step5 negative matrix now, exact SHA256hash shapes required;
lexical cursor validation and directAIjobfilter/currentprojection/revocation/mutation-free tests
within existingdiscovery testfile, no newjobwire/enum or genericV1behavior. This is explicitly
approved strictcursor/currentness scope, not a newpubliccontract. Minimal parserrepair only if
behavioralRED confirms gap; validate future Task4 inputlimits independently then.

### Task3 scoped closure — current granted discovery and pagination

Task3 developer recovery `ses_eee39259effeVnIJuQEuI1kxBH` completed fourboundedfixes; genuine
missingmodule/synccount/clock/emptyconsent/remoteport/errorfamily/grantedseal/reportreadiness/
malformedhash RED retained separately from fixture/setup errors and already passingcontrols.
Finalscoped reviewer `ses_eee35557fffeUm44fQZ4OzE607`: I1/I2/P1–5/M1 and strictcursor proof
addressed, no open task findings; genuineAI2job/genericfilter/cancel/revocation/replacement/
noresurrection/nojournalmutation evidence added. Generic V1 history/cursor remains unchanged.

Independent runner `ses_eee8899d7ffeX0iTUza6tSBlem` ran once:
`.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-3-verify-final.py`.
Actualpytestargv17files: asset_discovery/source/catalog_adoption/catalog_prerequisites/api/jobs/
assembly/current_grants/real_credential_audit/asgi_stream/ai_egress/ai_contracts/mcp_identity/
permissions/analysis_mcp_identity/contracts/api_contract_sync, all test_ prefix and .py under
tests/contract, `-q -W error::RuntimeWarning` →699passed/0skip/0warnings/101.39s. Ruffcheck+
format13changedPythonfiles, mypy9owner/gatefiles, gitdiffcheck all exit0.14sourceSHA256+HEAD
bed4d9c unchangedbeforeafter. Primary checked actualreceipt/fullstdout/allloghash/currentfiles.
Receipt `.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-3-independent-final/receipt.json`,
SHA2568d5450684e81a3d5604deeaebeb59de8b28244a5a75e60658169d0b847da3b33. Exactsourcefreeze
task-3-fix4-freeze.json in ownedignoredscratch; committedTask3source revision recordsdurably.

Observable Task3level: opt-in local Core graph exposes the two authenticatedAI discovery GETs,
exactnativeDSM/ORTHO permission-restrictedfacts/actions and strict currentasset/AIjobpage cursors;
newassets/page metadata use bounded remote preflight then local owner fingerprint/currentrights/
freshcredentials before guardedheaders/body. Emptyjobpage/lateconsent failclosed, no authority
resolution in finalgate, no deniedcounts, no pretending recordidentity provesrights/accuracy.
Coreoptionalcatalogaccumulation limits refuse beforegrowth; no measuredcustomer-load/SLAclaim.
OpenAPI errorfamilies/aliases/runtime paths agree in actual conformancechecks.

Task3 complete at scoped software sourcelevel after Primarytaskownedcommit. Task4stdio adapter,
Task5actual SDK/HTTP/worker/independentconsumer/restart/nextobservation parity, Task6wholechange
review/fullverification remainrequired. No nativehost/customer/realexport/operationalrelease
acceptance/AIclientconfig/provisioning/push/deploy performed. ProductEXT-VAL and goalremainopen.

### Task4 start — dedicated bounded stdio client

Task3 committedf8afb011244e79586ca035473ac4d16dc5ac0a2e,14sourcepaths+plan/parentledger,
cleanGit/main; taskbase/integrationf8afb01. Fresh sequentialdeveloper owns newadapter/tests/root
workspace metadata only, noCore/Analysiswriter. Task1–3 not redispatched.
FocusedContext7 currentSDKv2 constructor callbacks/explicitCallToolResult and uv offline lock/
preferences consulted2026-10-07; installedmcp2.2.0 Server/result/tool/RPC fields inspected.
Exactdocsummary in ownedtask4scratch, no training-only SDK syntax assumed.
Ruling: finite configured structuredresponse limit also bounds actualserialized outgoing RPC
frame including duplicatedtext/overhead; safe error that cannot fit closes safely, never
truncatedJSON. SDKhandshake/tools/error output schemas must prove this, no silentSDKexception
fallback. Input/environmentprivate credentials never scanned; generated fixturetokens only.
Ruling: use owner-protected generatedfixture paths under thisplan's ignoredprivate scratch when
systemtempancestors violate secureparentpolicy; never weaken productionparent checks merely
to accommodate tmp_path. Root-owned immutable ancestry is not a non-owner tokenfile exception.

### Task4 first implementation / review — required repairs, not accepted

Task4 developer `ses_eeddc496affejlATAKJ3AjW6NB` source preserved after providerprotocolerror,
same-child recovery returned19new/11oldAnalysisstdio/static9typing0; offlineuvlock additive22lines,
thirdparties reportedlyunchanged, sourceclosure only. Originalmissing-moduleRED19 retained,
fixture syntax/query setup fixes excluded. Current13ownedhashfreeze/reviewdiff generated;
first package script accidentally included oldidentitytest in glob, assertioncaught14not13,
correctedexplicit4newtest paths before actualreview; no oldsource modification.
Reviewer `ses_eedc8192fffeBlc0BEhPg7iLar` required actualframe-byte accounting, budgetedlistTools,
cannot-fit SDKerror path safeclosure. Overall compliance tick conflicts with these required
findings; Task4 remains NOTcomplete/accepted. Report cites package positions notactualsource.

Primary concrete source/reproductions and rulings:
- I1/I2/I3 confirmed server frame estimator2*JSON+1024 ignores escapedtext and actualRPCids,
  listTools/controlframes budgets absent, errorcannotfit raisedinto SDKgeneric fallback rather
  than boundedclose. Synthetic backslash payload actualSDKJSONRPC frame60163B vsestimate41074B
  (first setup lacked requiredjsonrpc field, correctedbeforeactualrepro). Measure actual bytes
  at final SDKframe handoff includingnewline/id/textescaping for everyframe, boundedstderrclose
  if safeerror itself cannotfit. No truncation/oversizedframework fallback or schema weakening.
- P1 confirmed protectedread accepts group-writable0o770 ancestor; afteros.read syntheticfile
  mtime changed butread accepted (no postreadfstat). Strengthen group/worldwrite checks, safe
  ancestor descriptor walk/no symlink-swap race, pre/open/post/path stats and localfilebounds.
  Fixed token representation4096B(+CRLF) applies regardlessownerquota; no control bytes/header
  material accepted, safe stat/read failure. No actualcredentials read/replaced.
- P2 HTTPS DNS origin core.example.com refused by literalIP-only implementation despite approved
  exactHTTPSorigin allowance. Accept validated exactDNSHTTPS (nouserinfo/path/query/fragment/
  controls, verifiedTLS/noambientproxy); only HTTP mustliteral-loopback. NoDNSnetworktestneeded.
- P3 _file_reference refuses COMPLETED+UNAVAILABLE with retainedreceipt asINVALID_CORE_RESPONSE;
  genuinehistory validmetadata mustreturnfileReference=null, never imply bytesavailable.
  Queued/no-receipt/get and allvalid unavailable states require direct regression, no newjobwire.
- P4 overall call deadline currently startsafter synchronous tokenfile/headerbudget work; move
  budget toinvoke entry and bound asyncawait stages; expose no reservation/file/clientleaks.
  SynchronousboundedCPU work cannot be hard-preempted; budgetcheck after parse/model/frame stages
  required, no standingpermission from previously loaded credential. Use complete timeout/cancel
  test proof, not fixture success counts alone.
- P5 configuredidentifierbytes must apply idempotencykey and returnedcursor/count/scope fields;
  digest lexicalformat shouldmatchactualsha256wire instead of loosehexdigtext. Genericbearer
  substringban on identifiers advisory: headers/purpose/token fields closed already; don't
  reject legitimate safely-routed identifier justbecause it contains a word.
- P6 config RecursionError/startup/client invalidheader or nonlatin values mustsafeclosed, no
  raw exception/traceback/input echo. Handwritten remediation map loses validatedCore meaning;
  carry bounded recognized reason+remediation fromclosedmodel ratherthan reflection/default
  guess. Genericunknownfailure codes stayclosed.

Repairround1 scoped sameadapter/tests only, actualbehavioralRED before code forload-bearing
defects plus all required negativeconfig/race/framing/cancel/cleanup cases. StageTask5realCore/
TIFF/worker parity remainsseparate; adversarialTask4transport checks cannot be deferred to it.

### Task4 fix1 review — actual I/O cleanup and safe refusals still required

Fix1 actual17RED→39new/11oldAnalysis/83Task1/static9typing0;13originalSHAvalidated.
Reviewer `ses_eedc8192fffeBlc0BEhPg7iLar` marked I1–3/P1–6 addressed, but found newImportant
shortos.write ignored and only-newline outputbudget checks; close emits tail markedMinor.
Ruling: tail emission is load-bearing no-partialJSON requirement, not optional cosmetic.
Implement pre-growth bound and reliable shortwrite handling, discard incomplete tail onclose;
transport interruption of already sent bytes cannot be recalled and must never claim success.

Primary additional source verification:
- SDK stdio.stdin_reader iterates unboundedlines then validate_json; current _bounded_stdio
  passes only stdoutwrapper. Incomingframe bound absent beforeparse, CannotVerify nowconfirmed
  gap. Reuse configuredmaxRequestBytes for the incomingprotocol frame representation (notnew
  quota), bound reads/ids/deep malformedframes beforeSDK, safecodeclose/no rawfield reflection.
- SDK taskgroup can surface ExceptionGroup; main only catches FrameBudgetExceeded singleton,
  current malformed/runtime diagnostics sanitization incomplete. Add exactsafe stderr closure
  for actual nestederror/backpressure/invalidinput, preserve cancellation, no traceback.
- P1 postread stats compare inode/size/mtime only, don't revalidate mode/uid/nlink or ctime:
  chmod/hardlink change while read mustnot authorize staleunsafe credential. Require full
  observed metadata continuity and revalidate protectedmode/owner/nlink afterread/pathstat.
- P6 table equality is not proof that any closed receivedremediation is retained; carry validated
  reason/remediation asbounded facts from Coreerror, not rawmessage/default guess or newauthority.
- Config opaque tokenprefix stringbearerX is not header scheme; keep no whitespace/control bytes
  and don't reject a legitimate opaque credential solely prefixword. Noauthpermission change.
- Fixture moved to ~/.cache duegroupwritable worktreeancestors; no securitypolicyweakened.
  Ruling: permit ONLY new unique0700 temporarygenerated-test namespace under existingsecure
  ownercache; no scanning realcache/credentials/hostconfig or chmodexistingfixednamed directories.
  Preserve any previously created taskfixtures as identified; future writes isolated/per-run
  with ownedcleanup, never overwrite unfamiliar/shared namespace. Harmlessfixturelocation is
  not installation/securityweakening/provisioning. Existingcache path provenance is task4fixtures.

Fixround2 sameadapter/tests only, genuine syscall/splitframe/SDKstderr/deadline/receivedremediation
RED plus exactnegativecoverage. Nativebackpressure finite configuredcall budget; do not silently
turn responsewriter into unbounded blocking thread or drop bytes on success.

### Task4 fix2 recovery / scoped review and remaining budget repairs

Fix2 child returned provider protocolerror after saving complete report/logs; actual54new/11old/
83Task1/static9typing0 retained. No blind redispatch needed: current13snapshot vs priorfreeze
proved, fullfixreport exists. Reviewer closed shortwrite/tail/stdin/stat/remediation/cachefindings,
but called reset-on-EAGAIN timeout Minor. Ruling: total finite frame deadline is load-bearing
agreedtransport contract; slowtrickle mustnot reset it indefinitely, fix within sameowner scope.
Use configuredcall deadline as total plus existingpool timeout perwait (minremaining), no new
operatorquota. Idle stdio session remains allowed; incomingpartialframe once bytesarrive is
boundedrepresentation, not a new unattendedsessionidle policy.

Reviewer pre-growth closure contradicted actual extend-before-check source. Primary generated
instrumented pendingbytearray: 32B ownerlimit, existing1B +1024Bchunk reached1025B before refusal.
Ruling: split into complete/current-line slices, check remaining bound BEFOREeveryextend on both
outputwriter andinputpump, never allocate full overlimitline first. Oversize refusal before any
framebytes emitted; complete legal multi-frame chunks still supported. One unsuccessful
loopbackrepro setup assumed contextmanager; corrected start/close, malformedRPCmethod42 +synthetic
marker showed noecho/noTraceback/exit0; not a securityfailure or behavioralRED. Record separately.

Fixround3 samewriter: genuine preallocation and deterministic trickle-deadline RED then repair,
existing54negative/regressions+SDKcontrols/static. Documentation mustmatch effective per-frame
input/output configrequirements and pinned-history nullreference, not imply installation;
sourceimports/transitive anyio requirement verified against unchangedSDKmanifest/lock.
Mixedgroup extra safe stderr code is harmless diagnosedfailure, not rawreflection; retain scoped
minor unless exactcontract fails. Fullpackagebuild/Hatchling gap still explicit, no installation.

### Task4 scoped closure — bounded local data stdio adapter

Three repairrounds closed I1–3/P1–6, syscall/partialtail/groupederror/stat/receivedremediation/
uniquefixture namespace, then genuinepregrowth andtotaltrickle deadline RED. Finalreview
`ses_eedc8192fffeBlc0BEhPg7iLar` fixed priorpregrowthverdict againstactualsource and marked all
requiredfindings addressed; no newCritical/Important, harmless extra safe stderr code for mixed
exceptiongroup remains deferredMinor forT6review. Testdelta restored3accidentallydroppedtests
verbatim beforefinalfreeze; actual59new tests includes them. No criterion weakened to getGREEN.

Independent runner `ses_eee8899d7ffeX0iTUza6tSBlem` executed once exactdriver:
`.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-4-verify-final.py`.
8files config/client/stdio +oldAnalysisstdio +AIcontracts/identity/egress/api_contract_sync,
`-q -W error::RuntimeWarning`:263passed/0failed/0skip/0warnings/137.50s.9changedPythonfiles
Ruff/format/mypy all0, offlineuvlockcheck162packages, gitdiffcheck0.13sourceSHA+HEADf8afb01
stablebeforeafter; all144thirdpartyTOML packageversions/origins/hashes EXACTequalGitbase; new
workspace leaf metadata/console script verified. No packagewheel/sdist/installation checked.
Receipt `.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-4-independent-final/receipt.json`
SHA256f0e7cf6a7d3216a48c04fe0706cf88ab03b82105ed2b73a1b9ac92bdfe8e9777. Primary checked
actualreceipt/fullstdout/loghashes/currentfiles; reportedumask022 was stale reportcopy: actual
driverumask077 andreceipt+all6logs0600 verified.9files count (not earlierreport's10) authoritative.

Usable sourcelevel: six fixed MCP tools with officialSDK2.2.0 realstdio handshake andclosed
arguments/results/error schemas; safe explicitconfig/private token reread, exactHTTPSorigin or
literal-loopbackHTTP, finiteHTTP/header/body/response/deadline/concurrency/currentack checks.
Actualserializedprotocol output+input frames bounded, late protection changesrefused, opaque
credentialreplacement supported, completedunavailable jobmetadata hasnullfileReference; no
adapter rasterdownload/storageauthority/automaticcreate/reconstruction/calc/listener/AIhostsetup.
No SDK/core privateclient permission was weakened; old Analysis stdio remainsunchanged.

Task4 complete at scoped software sourcelevel after Primarytaskownedcommit. Task5genuineCore/
worker/GeoTIFF/authenticatedHTTP/independentconsumer/replay/nextobservation parity and Task6
wholechange review/full/static/build acceptance remain. Fixedownerpolicy cannotuse insecure
groupwritable sourcefolder for credentials; tests use unique0700temporary generatednamespace
undersecurecaller cache with taskownedcleanup. This is testfixture setup, not liveprovisioning.
Packagebackend absent and actualcustomer/field/operations acceptance remain open; goalactive.

### Task5 start — actual generated end-to-end software evidence

Task4committedbcca3c324f54ce7efd76d2be4519aa3d5787ff65, cleanmain,15ownedfiles+parent/plan.
Task5base/integrationbcca3c3; freshsequentialdeveloper owns newSDKHTTPintegration/replay/example
andboundedfixture/docs only. NoCore/adapterruntime change silently authorized; if actualfailure
demands ownerrepair, preserveRED andreport specificscope before Primaryruling. ExistingTask4
fixturefile nowexists: compose/extend it minimally (no overwritingconfig/client/stdiofixtures),
leave oldsource/objectworker/publicbyteengine helpers unchangedunlessexplicitinput needed.
Ownedgeneratedloopbacklistener+objectserver+worker/MCPsubprocess permissible; closeonlyowned
ports/processes, noinstall/production/customerstartup/hostconfig/securityoverride. ActualSDK
uses explicitnewsource PYTHONPATH sinceadapteruninstalled; claimsremain generatedsoftwareonly.

### Task5 partial recovery — genuine RGBA worker defect, no scope weakening

Task5child `ses_eed68c9f9ffesu2jIbj6bfEIYR` providerprotocolerror afterfixture/integrationwrites;
samechildretry failedagain butearlyreport preserved. Actualfixture+integrationpartialsource/
report not discarded. Report labels invalidsingleDSMsubmission/alpha128/undefinedcolorinterp
as genuineRED; these are setup/profilefaults, not missingproductbehavior/TDD evidence. Genuine
reportedfailingbehavior: inspectedcanonicalRGBA withbinaryalpha isMEASURED, butnativewindowworker
refuses SOURCE_MEASUREMENTS_MISMATCH because `MaskFlags.per_dataset` is mistaken for separate
internalmask even alongside `MaskFlags.alpha`. Primary traced exactsourcebranch589–596 vsowner
inspector `_has_internal_mask` structural maskIFD rule. No previousruntimewrite occurred.

Ruling: required DSM/RGB/RGBA full byteparity cannot be reduced to RGBAmetadata-only. Newbounded
recovery developer preserves actualpartialwork and completes remainingTask5; no blindtaskredo.
Authorize minimal ownerrepair in packages/geo-spatial/src/ksi_geo_spatial/external_native_window.py
+ tests/contract/test_external_native_window.py ONLY after genuinealpha-only vsinternalmask/
NoData/invalidalpha diagnostic confirms rule. GDAL per_dataset+alpha is an alpha mask, not proof
of separateinternalmask; genuine internalmask must stillrefuse unsupported RGBAcomposition.
Prefer correct existingmaskflag semantics without newparser/workerAPI/contract/inspectionimport
fromservices; if structural boundedparser trulyneeded report exactpath/scopebeforeimplementation.
Nativeprofile/sha/finitebounds/currentrights/fullinspection unchanged, no newband/profile support.
Cost if wrong localized primitive rollback with negativecontrols; approvedprofile alreadyRGBA.
Task5oracle must independently handderive row/col/affine fromknown fixture grid beforeworker,
not compute expectedpixelwindow with same productiongeometryhelper under test. Genuinereplay/
lostresponse/nextobservation/negativeMatrix/examples/docs remainrequired. Distinct worker process
and any in-process securetransport limitation must be reported, not described asallHTTPendtoend.

### Task5 recovery progress — preserve tests, finish report/static then review

Recoverychild `ses_eed4bdcc4ffeMP7pIMtc1DF7T5` providerfault after ownactualRGBA primitiveRED/
GREEN/6parity then after remainingmatrix/replay/example/docs work. Actual8integration/3replay/
2example logs retained; fullTask5regression/static/independentreview stillunrun asobserved.
Minimalnativewindowownerrepair +negativeinternalmask/nodata/nonbinaryalpha retained, no skippedRGBA.
Ruling: test_spatial_data_mcp_workflow_example.py is boundedTask5ownership addition necessary to
prove alreadyapproved externalexample behavior; no newproductfeature ordeletionofoldtests.
Ruling: freshbounded recovery finishes actualunfinished coveringchecks/report only, not another
greenfield implementation or blindlyretryerroredproviderchild. Diagnoseactualcheck failures
within existingownership; consequentialownerneedsreportedbeforewriting. Fullstdout/hashes freeze
and review remainrequired, never count implementationreport as independentverification.

### Task5 first scoped review — required evidence / external example repairs

Recoverychecker `ses_eeb9e60a3ffeFK8uCIHMZA1DxX` ran124coveringtests/staticRuff7/diff0, but
mypy support.* importerrors unresolved. It called missingRGBAhelperbody/IndentationError a
genuineRED: correction this is fixture/setup repair, genuineRGBAbehaviorRED logs remain separate.
Reviewer `ses_eeb978974ffeoUcopl6F0EHOMT` requires actualHTTP/SDKcursor traversal+stale409,
guarded examplecredentialreads, WorkOrder source-binding negatives, typegate resolution.
Ruling: mypy's support fixtures require tests in MYPYPATH, correct invocation noteditunrelated
source or waive gate. WorkOrder absence fromroutepath doesnot remove genuine sourceworkorder/
allsourceareas authorization; add actual owner-record mismatch negatives no publicwire change.

Primary confirmed additional missingchecks: 6SDK calls sweep GRANTrevocation only, not current
consent; no headerdowngrade ormissingack negative inTask5file. Report claim allStep4passed is
incorrect. Ruling: testcurrentconsent for each6tools withprotectedbyteabsence/nomutation,
realCore-origin response ack stripping fixture (not forgedsuccess) and purpose/header attempts;
keep originalgrantnegative control. Allrequiredcases tracked separately passed/open.

Externalexample has finitepoll loop but unboundedinitialize/create/callawait; floatinf passes
parsercomparisons, rawValueError reflected via_fail(str(exc)); config.read_bytes unbounded and
token.read_text unguarded onoptionaldownload. Ruling: reuse existing AdapterConfig protectedread/
read_token validatedfiniteownerlimits foroptionalconsumer, overallasync deadline aroundSDK
initialize/create/poll cleanup +finitepositiveCLI budget/interval, safeclosederror allowlist.
No secretargs, hostconfig/installation, freshcreate retry or newwire; same-keycaller recovery
preserved. Boundactualreceived typedjob/reference/source scopes beforepersist/download andatomic
no-overwrite receipt publishing withownedcleanup, no partialreceipt oninterruption. Tests genuine
unsafeconfig/token/callstall/nonfinite/rawexception/startup/latefile protection; sourceonly same
example/fixture/test ownership. Reviewminorcomment actualruntime line56-60 notRGBAbranch, no
requirement toaddhandoraclecomment onproductionreceipt dataclass; currentaccuracy nonclaims stand.
Repairfix1 recoverychecker ownsremaining scopedfixes; no fulltaskredo, noCore/adapterchanges.

### Task5 fix1 bounded handoff (step limit, not product blocker)

Checker `ses_eeb9e60a3ffeFK8uCIHMZA1DxX` reached childstep limit after read-only genuine probes;
current11sourcehashes reportedlyunchanged, 11/11originalsnapshot exists. CorrectMYPYPATH resolved
7ownedfilesclean (tests:tests/contract:adapter source) without unrelatededits. Probeconsent6tools/
pagination/ackstrip/workorder-byteconfusion are scratchcontrols, not committedtests; conversion
andexample security/deadline repairs remainunfinished. Reviewer returnedconcretefindings but
didnotpersist promised task-5-review.md; actualreceivedverdict recordedinpreviousledger section,
no claim of an existent reviewfile. Requiredre-review mustwriteits actualreport beforecompletion.
Ruling: splitremainingfix1 into two sequentialboundedwriters: integrationmatrix+fixture helper,
then example+coveringtests/doc/update. Not concurrent/sharedfilewrites, no greenfieldtaskredo or
modelchange. Keep existingRED/probes/fullstdout andapprovedsame11file scope. Finishfullcovering
regression/static afterboth, thenfrozen-diff review andindependentrunner. No productscopechange.

### Task5 fix1 A/B re-review and file-byte ceiling disposition

Sequential A ses_eeb8d388bffeCVecRrieHU1LQf added6genuineintegrationtests/currentconsentSDK6/
pagination/crossWorkOrder/downgrade/realackstripping;14integration+23stdio/static0. Sequential B
ses_eeb729acbffeYSKpyCSuUtcJJR exampleprotectedconfig/token/typedviews/deadline/closederrors/
atomicreceipt genuine6RED/1control→9exampletests/static0, old2realSDKcases retained. Correct
MYPYPATH7typingcleanwithoutsourcewaivers. Bothscopedchecks only, finalfullregressionpending.
Re-review `ses_eeb978974ffeoUcopl6F0EHOMT` nowpersisted task-5-fix1-review.md: originalI1–4/P1/P2
addressed, newImportant optionalfiledownload ceiling conflates structuredmetadata quota with
rasterbytes. Ruling: add optional positive finite caller --max-download-bytes for HTTP-only
consumer; absent defaults conservatively to currentownerresponse ceiling, document thisexactly.
This is externalexample's existingdownload budget, not newCore/MCP config/authority/wire/profile.
Large authorizedraster neednot force oversized MCP JSON budget. CLI invalid/nonfinite rejected
no rawreflection, suppliedsize honor beforebytepublish; preserve existingCLI compatibility.
Minimal Bfollowup example/test+README/opsevidence, thenscopedre-review+independentrunner.
MinorSDKcleanup relies onofficialSDK closing/real2e2e+mockedstall, not universalhostcompatibility;
receiptparentcaller-ownedpath requirement documented, failureatomic temp/link publication
verified; publicstdout caller receiptpath notcredential. Retain disclosednonclaims forT6.

### Task5 fix2 externalexample capacity and flaky-flow diagnosis gate

Bfollowup positivecallerdownloadbudget/unchangedJSONquota3RED→12examplepass/static0,4source/
docchanges only. It also observed3examplee2e ADAPTER_UNAVAILABLE failures before2greenreruns and
called it pre-existing timingrace without rootcause. Ruling: failuresnotwaived by repeatedgreen
or assumingearlieruntouchedtest means earlierbug; preserveactualfailedlogs anddiagnose current
SDK/Core/worker overlap beforefinalverification. No automaticnewrequest/key, callerpollbudget
mustremainfinite; any sourceowner defect beyondcurrentexample/test/fixture scope requires exact
RED+permission ruling. Test guards shouldn'tsleep/increasebudget justhidefailure. Concrete
typedtransient status handling onlyafterverifiedcause, no genericexcept-and-retrygreen fallback.
Record generated managementrun_once transport in-process +sandbox rasterlauncherchild accurately;
do not call exampleprocess namedworker a distinctproductiondata-worker networkdeployment.

### Task5 flake investigation — instrumentation permitted in generated-test wrapper only

Diagnostician ses_eeb663b40ffegUIcAhxiwYPMnV couldnot reproducewithin3boundedruns (2targetedgreen,
12full-examplegreen), no Bfailedlogs retained so exactcause undetermined, no runtimefixmade.
No acceptancefrom repeatedgreen; original3failures remain recordedunexplained, not silently
calledpreexisting/nonblocking. Ruling: test-only Pythonwrapper around example subprocess may
capture exceptionCLASS +repo/library sourcefile:line into0600taskowneddiagnostic artifact,
never rawexceptionmessages/locals/arguments/headers/config/token/outputJSON and never public
stderr diagnostic escape. Normalexampleclosederror contract unchanged; wrapper scopedexact
generatedtest command and no realcustomerinvocation. Record finalfailures classlines if they
occur, not retry-until-green. No need for usersecurityapproval for safe generated-test tracing,
no productionhook/hostconfig/newdependency. Finalindependentcoveringsuite stillrequired; any
failuregenuinecausebeforefix, unresolved historicalflake disclosedandkeptopen untilrealproof.

### Task5 independent functional failure — not closed

Independentrunner ses_eee8899d7ffeX0iTUza6tSBlem executed task-5-verify-final.py ONCE:139passed/
1failed/0skip/1NodataShadowWarning/127.99s; scriptstoppedbeforestaticchecks. Failureactualexample
ADAPTER_UNAVAILABLE reoccurred, diagnosticbounded8eventring retained mostlybenignStopIteration
thenExceptionGroup beforeexample mapsunknownfailure atline326. Actual11SHA+HEAD stable, failed
receipt+fullstdout retained task-5-independent-final. No Task5acceptance/commit/goalclosure.
Ruling: refine test-onlydiagnostic toskipbenignStopIteration and recursivelyrecord exceptiongroup
leaves +suppressed __context__ class/fileline; exactlyrecognizedclosed ValueError code may be
recorded (allowlist not reflection). Real SDKCallToolResult error may be recorded ONLYafter
strict SpatialDataMcpErrorV1 validation ascode/remediation facts, never payload/messages/header/
args/token/locals. No productiondiagnostic orcatchall retry exemption. Boundrecords/artifacts.
Tracecurrentknownfailure oncewithrealworker/status overlap, identifycausalCore/SDK/model phase;
fixonlyprovenreason withinauthorizedowner orreport exactadditionalownerneed beforewrite.

### Task5 deterministic exception-group mapping defect

Diagnostician ses_eeb663b40ffegUIcAhxiwYPMnV proved trueREQUEST_DENIED ValueError iswrapped by
SDK/anyio session teardown ExceptionGroup; exampleexceptValueError missesgroup and mapsit to
ADAPTER_UNAVAILABLE. Genuine strengthened denied-test RED retained, no productionwriteyet.
Oneexact9filebatch140green isdiagnosticcontrol, notindependentclosure ofhistorical139/1failure:
samegroupsignature but originalinnerflake leaf stillundetermined. Refinedtrace nowrecords16
meaningfulevents/skipsStopIteration/closedCallToolResult codes, privacyguard intact.
Ruling: authorize minimal example/test groupederror normalization withinalreadyapprovedscope;
preserve exactknownclosed leafcode when unambiguous, unknown/mixed errorsfailclosed, cancellation/
timeout remainactualabort and finitebudget. Do not normalize into success or automaticcreate,
and no GETretry until exacttransientCorecode/phase actuallyproven. This repairs deterministic
misclassification and improves realfault visibility; not a claim of historicalSDKflake rootcause.
ScopedRED→GREEN, thenreviewdelta+independentfunctionalrerunonce. Missing actualmatrix/behavior
or true transientfailure remainsunfinished, not dismissed as onlyhumanacceptance.

### Task5 controlled publication-race evidence (Primary functional probe)

Reviewerdiagnostic ses_eeb470bb8ffesRgFiO6FVNOKJ7 reached step limit beforeexperiment, no cause
report written; codeplausibility notcountedproof. Primarybuilt private generatedprobe
task5-publication-race/probe.py: actualSDKstdio/create, genuineCoreHTTP/audit, realnativewindow
sandboxlauncher/worker, barrier afteractualCREATE_JOBaudit append (no coordinatorheld), only1
issuance/samecallerkey eachcase. Twoinitialsetupfaults (tests/support importpath, insecure/tmp
spoolancestor) corrected, no securitypolicy weakened; uniqueowned0700cache root used.
No-workermutation control returns is_errorfalse/QUEUED. Advance realworker whilecreatepublication
paused returns is_errortrue REPORT_CONFLICT/CONTACT_OPERATOR, QUEUED→COMPLETED,1durablejob,
unchangedgrant/consent/source/currentrights. This proves legitimateworkerprogress conflicts
with single-job whole-view equality in Coremetadata_response/ai_egress, NOTidempotencyconflict.
Originalhistoricalpostheader tracephase stillnotdirectcaptured; causalrace nowdeterministic.

Interpretation for boundedrepair review: approvedspec§3 currentness is actualidentity/consent/
exactfrozengrant/source rights, §5 adopts existingV1worker/jobs; genericV1 acknowledgement is
an authoritativepoint-in-time jobrecord. No permission tostopworker/callerautomaticnewcreate or
freezehistoricalquantity. Investigate private OWNER-produced single-job publicationsnapshot
boundtoimmutableissued-job/source/frozengrant identity, protectedpayload fromownerselectedview,
then freshauthorization atheader/body evenifexecutionState advances. List/discovery cursors
still strictcurrentprojection/stale409; file bytes stillfullcurrentavailability/chunkguards.
This is a candidate technicalrepair, not yet sourcewriteapproval: independentfocused review
must confirm it preserves intendedcurrentness/no forgedpayload/cross-source/expiredrights and
identify any material product ambiguity beforeimplementation. No newpublicwire orauthidentity.

### Task5 single-job publication repair ruling after focused contract review

Focusedreview ses_eeb3fb430ffeFBtyxFAevgXukB: permissible-with-conditions; wholeviewdigest equality
is implementation, notspec§3/5requirement. Freshidentity/consent/exactfrozengrant/source+allscopes
remainmandatory, list/discovery snapshot409 andfilecurrentavailability/chunks unchanged.
Ruling: capture genuineowner-selected authoritativeV1jobview/canonicalbytes atprepare; allow
normalexecution/availability/receipt/reason progressaftercapture, never staleauthorization.
Audit digest equals ACTUALselectedcanonicalbytesattemptedforemission, notlatestviewneveremitted.
No claim latestatomicstate, filedescriptor remainsan authenticatedreference notbytecapability.
Handler-suppliedtypedview MUST NOT be accepted asproof ofbody: ownerreselects exactjob/current
authorizedpayload; privateperresponse witness tiedto immutableissuedjob/source/frozengrant/
scope/requester/purpose andowner, bodytampering/wrongstore/forgedwitness refused, finiteJSONlimits.
Ephemeral integrity/provenance object only, no newpublictoken/authidentity/policy/service/cache.

Authorize boundedownerrepair services/core/src/ksi_core/domains/external/delivery/jobs.py and
ai_egress.py +new tests/contract/test_spatial_data_ai_job_snapshot.py, extendexistingTask5barrier
tests/fixture onlyasneeded. Prefer reuseunchangedmetadata_response guard: typedfrozenbody recheck
returns selectedbytes onlyaftergenuinefreshcurrentrights+immutablebinding witness verification,
so header/body equality/audit/deadline machinery remains. If extraowner trulyneeded reportfirst.
Requirement SDP-CLIENT-01-AI§3/5/6; ownerCorejobs/egress; acceptance deterministicCREATE/GET/CANCEL
worker-progress barriers no falseconflict, revocation/expiry/source/forgery stillfailbeforebytes,
AIlist statuschange still409/genericV1unchanged; existing source/native/identity invariants
enforced viaoriginalownerrequireAI gates. No publicschema/descriptor/layout changes, generated
fixturesonly/noHIL/noaccuracyclaim. Rollback localizedCorehunks/newregressions; runtimechange
invalidates earlierTask2/3frozen evidence andrequires allcurrentmetadata+nativeflowchecks/T6.

### Task5 provisional owner repair review — provenance and boundedness defects

Developer ses_eeb3cca6cffey9hpV7QsW6mcTH hit step limit afternew16+370/146test evidence,
nofinalstatic/report. It editedT2test hook2→3 outsideexplicitownership beforePrimaryruling:
preserveactualdiff, recordprocessdeviation, notdiscardtests; freshresolve movedhookstage but
thatnewinline resolve is itself a defect. Review ses_eeb2de625ffeDY18zcyR4vu4lB foundCritical
self-consistent forgedsnapshot passesverify; computedbindingdiscarded/noowner/storeseal.
Important synchronousmay-OIDC credentialresolve beforeboundedresponse, splitguard TOCTOU.
No Task5sourceacceptance; passingnewtests lacked self-consistentforgery/identicalwrong-store cases.

Ruling: private per-store EPHEMERAL integrity authenticator over exact bodydigest+allimmutable
job/source/grant/scope/requester/purpose fields, store-specific torejectsamebinding fromanother
store; genuineowner-producedselectedbodyonly, no newpublictoken/capability/credentialprovisioning/
operationalsigning/loggedsecret/unboundedregistry. Integrity doesNOT replacefresh authorization.
Capture+verify eachwrapgenuinecurrentrequireAI+record binding in one sharedreentrantcoordinator
guard, no gap. AvoidinlineOIDC entirely: expectedrequestidentity is onlya routinghint obtainable
from credentialcontext; genuine job currentness port already provides trusted LOCAL requester
lookup. Privateowner bodycapture useslocalcurrentowner actor, notcallerfrozenPrincipal or new
identityauthority. Existingboundedmetadata_response first/header/body OIDC refresh stays sole
actualrequestcredential authorization; no protectedbytes untilallfreshgates. If localactor
unavailable/mismatch failclosed; explicitExpectedId mustmatch actualsealedjob/requester and later
freshOIDC identity checks. No change frozen-source or permission/caller-scope meaning.
Authorize credential_currentness.py read-only expectedidentity accessor (notprincipal/token,
notauthority) ifneeded; noapi.py/metadata_response orpublicwire change. RestoreT2hookindices
whenremovinginlinefreshresolve, preserveallcurrentprivacy assertions; explicitT2testfile now
ownedforstage-alignedexistingtest adjustment only. Newself-consistent body+view+digest forgery/
same-frozen-job otherstore/seal tamper +slowOIDC no prepareblock/deadline/source/grantchange
barriers requiredRED→GREEN. Any alternative needingnewnetwork/authidentity mustreportbeforewrite.

### Task5 owner snapshot FIX1 disposition

Developer ses_eeb259298ffelfb48i2R9MfMry: 21 snapshot +70 egress tests passed; five new
controls recorded before repair. Per-store ephemeral HMAC now binds body digest and immutable
owner facts; capture/verify share the local coordinator; prepare does not invoke OIDC.
Review ses_eeb2de625ffeDY18zcyR4vu4lB closed provenance, store identity, split observation,
and unbounded synchronous credential-refresh findings. Source remains provisional until final
independent integrated checks. Original new test file still has 17 mypy errors: its earlier
untracked version is not an unrelated baseline and does not excuse the new deliverable.
Ruling: repair typing in that owned new test without import/error suppression; include job_id
explicitly in private seal binding rather than rely only on job_digest; correct stale snapshot
docstring. No public schema, permission, credential, or policy change. Re-review only this delta,
then independent integrated egress/discovery/native/SDK checks. Existing Task1–4 evidence belongs
to its revisions; current Core runtime changes require current covering verification.

### Task5 integrated verification — runtime green, imported test typing remains open

Independent ses_eee8899d7ffeX0iTUza6tSBlem ran task-5-verify-integrated.py once:
872 passed/0 failed/0 skipped, one intentional NodataShadowWarning; Ruff/format12 passed.
Mypy11 targets traversed the new snapshot test's imported T2 test helpers and found 52 errors
in test_spatial_data_ai_egress.py, so full verification failed and diff check was not reached.
16 required-file hashes and main bcca3c3 stayed stable; actual receipt/logs retained.
Ruling: repair annotations/types in that existing owned T2 test (and snapshot test only if
needed) without changing runtime assertions, fixtures, rights, hook stages or expected results.
This is the necessary dependency of the new typed test, not authority to waive errors or use
follow_imports/error suppression. No Core runtime changes. Focused 92-test author check and
review of annotation-only diff, then independent integrated checks on the resulting snapshot.

### Task5 scoped software closure — current evidence, not product acceptance

Imported-helper typing repair ses_eeb1353f8ffe9WG2DeOznACo4S and scoped review
ses_eeb2de625ffeDY18zcyR4vu4lB preserved privacy assertions and response hook timing.
Independent runner ses_eee8899d7ffeX0iTUza6tSBlem executed
`.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-5-verify-integrated.py`:
**872 passed, 0 failed, 0 skipped**, one intentional NodataShadowWarning; Ruff/format12,
mypy11 (including imported helpers), diff check all exit0. Main bcca3c3 and 16 required hashes
were stable before/after. Receipt SHA256
`bc41edfe2025b6ca898c3a59481b515fa8ec6a093e04987e248b01cef8dabd6e`;
full original logs: scratch `task-5-independent-integrated-typed/cmd-00.log` through `cmd-04.log`.
Earlier 139/1 runtime failure and 872-pass/52-type-error receipts retained; neither counts as pass.

Primary updated only ops evidence disclosure after that run: actual worker management is
in-process with HTTPS-mounted transport, raster preparation is an isolated genuine child;
SDK/client/file consumption uses real loopback HTTP. It is not deployed-worker network evidence.
Independent final docs check verified all 15 non-doc hashes unchanged, all 16 final hashes,
five original log hashes, six runnable test paths, scope disclosures and diff check. Its first
phrase-based checker falsely required invented wording; corrected harness checks actual wording
and exit status, retaining the failed harness receipt. No source weakening to satisfy that check.

| Task5 acceptance | Current evidence |
| --- | --- |
| DSM/RGB/RGBA exact native bytes/affine/mask/CRS/hash/size | 3 genuine SDK/Core/worker/HTTP parity cases, independent hand-derived grid oracle |
| Durable restart/lost response/next observation | queued/completed/canceled journal replay, actual socket lost response, one issued job, exact new asset/source/result |
| Consent/rights/mismatch matrix | 8 HTTP pairs, 6 SDK tools, grant expiry/revoke/replacement/ambiguity/READ-only, org/Site/area/WorkOrder, purpose/header/no-ack, source bytes and midstream revoke |
| Finite safe external workflow | actual SDK subprocess, explicit protected config/token, closed typed scopes/errors, finite caller budget, atomic no-overwrite receipt and guarded raster download |
| Publication race/owner integrity | controlled real worker progress, owner-selected point-in-time payload, per-store private seal, fresh header/body authorization, tamper/cross-store/source/grant refusals |
| Software scope/documentation | exact source entrypoint/config and generated commands; no install, customer/host/export/accuracy/cost/containment claims |

Ruling: Task5 can close at this demonstrated local software scope and commit its owned files.
Spec acceptance10, Task6 full-change/full-repository/package closeout remain OPEN. Current run
closes the deterministic worker-publication race and exact grouped-error classification defect;
does not claim universal absence of transport failures or reconstruct the lost original trace.
No generic V1 history, quantitative values, Analysis MCP authority, visual UI or product slice
changed. No external delivery. Next: Task6 whole-change review and independent full/static/
offline-lock/package-closure checks; unavailable build backend stays an explicit readiness gate.

### Task6 whole review and first full-suite failure

Task5 committed fc14059205ac30812814d09f654c260678d35767, clean main. Whole-change reviewer
ses_eeb00f05affe0sENsboc2LMPXZ audited d0aac56..fc14059. It initially cited the superseded
52-error log; corrected report uses current typed872 receipt, no waiver. Quota fallback clarity
was already addressed; no open Critical/Important. Deferred minors: safe extra mixed-group
stderr code and optional negative-test cases. Spec acceptance10 remained explicitly unverified.

Independent runner ses_eee8899d7ffeX0iTUza6tSBlem executed task-6-verify-final.py once:
**scoped 1349 passed, 54 warnings**; then exact bare `.venv/bin/python -m pytest -q`
with child umask022: **6 failed, 9022 passed, 122 skipped, 102 warnings** in1039.34s.
Full original stdout/argv/hashes preserved in task-6-independent-final receipt/logs; source50
hashes and HEAD stable. Statics/lock/source-import/backend probes not reached. Runner's first
summary mislabeled the full-suite counts as scoped; actual command logs establish both above.

Root cause: tools/check_core_module_boundaries.py:273–286 requires an inventory record for every
Core source. The five new delivery modules ai_egress/asset_api/asset_discovery/metadata_audit/
metadata_response were omitted from docs/audit/CORE_R1_MODULE_MIGRATION.json. Six existing
migration negative controls fail because this incomplete baseline masks their intended checks.
Ruling: add exactly those five canonical delivery T3_NEW_MODULE records, following existing
jobs/credential/api entries, with no checker/test weakening, exclusions, module moves, runtime
or product authority change. Existing full-suite failures are genuine RED; scoped migration
checks must pass after the metadata repair. Run remaining final statics before another long
full run to surface fast faults early; preserve original failed receipt, no retry-until-green.

### Task6 current local-software verification and unresolved distribution gate

Developer ses_eeae49c82ffe157oxYHPhuOlKZ added exactly five inventory records;
all 174 existing records/metadata retained. Checker179 records and 38 migration tests passed.
Scoped final review ses_eeb00f05affe0sENsboc2LMPXZ closed that omission without checker/test
exclusions or runtime changes. Final source snapshot: fc14059 plus inventory correction,
51 required files, original 50-path runtime unchanged apart from durable documentation.

Independent runner ses_eee8899d7ffeX0iTUza6tSBlem, exact commands:
1. `.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-6-verify-final.py --checks-only`
   — exit0; Ruff/format39, scoped mypy35 production/test targets, diff0,
   `uv lock --check --offline`162 workspace packages, exact144 third-party entries unchanged,
   manifest/AST console closure and uninstalled source-console import passed.
2. `.venv/bin/python .superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task-6-verify-final.py --full-only`
   — exit0; actual bare `.venv/bin/python -m pytest -q`, child umask022:
   **9028 passed, 122 skipped, 102 warnings, 0 failures**,1046.70s.
   Reused scoped1349-pass/54-warning receipt only after its log digest and unchanged non-doc
   source were verified; no redundant scoped run for an inventory-only correction.
Both checked the same51 frozen hashes and fc14059 before/after; parent receipts/logs0600.
Static receipt SHA256 `bf3211433f5d028a60574d5ef01c2a0df3feb099420ffea0bfa47ba5ff012c61`;
full receipt SHA256 `c21c5681995c73d9aa142aa1e71d82be9b70f1287bff25689399161c54326468`.
Original full failure, scoped result and fast/final full stdout remain in owned scratch.
All skipped tests remain unverified; passing software tests are not field/customer/host proof.

Backend probes verified Hatchling unavailable in BOTH project and system Python. Manifest
and source import passed, but wheel/sdist build and SDK smoke from exact installed artifact
are UNRUN. Task6 package obligation/spec acceptance10 distribution portion stays OPEN; do not
mark the entire six-stage plan complete. No installation/sync/private account lookup attempted.
Recommendation for the material environment gate: approve a task-owned isolated build/test
environment under /tmp/opencode, only build-backend preparation and local artifact install/smoke,
without touching shared .venv, production grants/config, external publication or deployment.
Approval is pending; this does not authorize the preparation itself.

Current usable scope: source-tree dedicated local stdio MCP and finite external HTTP workflow
with generated DSM/RGB/RGBA parity, real current rights, replay and next-observation semantics.
No package distribution, installed AI host, customer export/license/accuracy/cost/containment,
operational recovery, real customer/field acceptance, product EXT-VAL close or full goal completion.
Keep deferred safe-stderr/optional negative cases as backlog, not silently-open acceptance defects.
Next: commit the verified inventory/docs locally, then return the bounded build-environment
approval gate while retaining the active long-term goal and all remaining customer/operations gates.

### Explicit isolated build-environment approval — Task6 distribution check resumes

On continuation, Git main d68b0fb revalidated clean. Generic auto-continuation was NOT taken as
installation permission. Native question explicitly requested only a task-owned isolated build/
test environment under /tmp/opencode, build dependencies, local wheel/sdist and installed SDK
verification; shared .venv, production configuration and deployment unchanged. Human selected
the affirmative recommended option (“允许隔离构建 (Recommended)”). This is the scoped permission
for environment preparation, not publication, deployment, live credentials or customer acceptance.

Ruling: use existing Python/uv; no interpreter download or shared environment sync. Build the
dedicated MCP package and its local ksi-event-contracts/ksi-domain closure from exact recorded
source. Download only required build/runtime dependencies into owned isolated environments,
pin runtime dependencies from current uv.lock, capture exact versions/artifact hashes; no
ambient auth/keyring/proxy profiles or credential copying. Verify wheels and sdist source closure
and actual installed entrypoint/modules from the built artifacts, not source-PYTHONPATH success.
Actual Core/SDK/native-byte smoke may reuse generated Task5 fixtures with the server command
redirected only to the installed wheel console entrypoint; real auth/jobs/worker/HTTP unchanged.
Keep protected generated config/token in existing approved unique0700 fixture cache namespaces,
not world-writable /tmp ancestry; build/test environments/artifacts alone live under /tmp/opencode.
Independent reviewer/test-runner required for resulting package evidence; any packaging defect
needs exact RED and owner-scoped source repair, never silently change product/dependency contracts.

### Task6 isolated package progress and harness-failure diagnosis (not closeout)

Main d68b0fb revalidated; only this Primary-owned ledger is modified. No product source,
root lock, shared environment, host configuration, live authority, publication or deployment
changed. StageA Developer ses_eeaa12f94ffevuW0X3aTwDeyrr built wheel/sdist for domain,
event-contracts and spatial-data-mcp into owned `/tmp/opencode/ksi-spatial-mcp-build-20261007-a1`.
The MCP source-wheel and sdist-rebuilt wheel both hash
`c16a656d80f90cdb0978d763c3e02cc08532ed4ba2cdc221aa65b7577287e288`; 68 source modules match.
Fresh isolated runtime imports, installed RECORD and 34-distribution pip-check passed.
These are packaging evidence, not an installed external AI-host claim.

StageB Developer ses_eea9b1521ffeDsfkDt6Q3S8hxM ran 14 unchanged genuine HTTP/SDK tests via
the installed console: 14 passed/0 skipped/0 warnings. Its additional fresh installed SDK-client
leg failed. The developer's initial transport/timing hypothesis was unsupported and withdrawn:
the frozen private client calls tools after exiting its stdio/ClientSession context, introduced
by its diagnostic indentation edit. A tracking-double regression proves that harness lifecycle
defect, not a transport/product fault. A separate private-harness mistake expected a top-level
receipt instead of the real SDK `fileReference`. The earlier lost-error recover failure's
association with this shape mistake is an inference; the missing original trace stays unknown.
No runtime repair or retry policy change was justified by those harness defects.

Ruling: preserve all original attempts, fix only a copied private harness, and compare the
issuance invariant rather than all journals (legitimate metadata publication audit grows).
Recovery full DSM/RGB/RGBA run passed with 6 installed-client children; controlled DSM passed
separately. Author evidence is provisional pending independent review and test-runner execution.
Scratch: `.superpowers/sdd/2026-10-06-spatial-data-mcp-v1/task6-package-{build,smoke,smoke-recovery}/`.

Reviewer ses_eea8f356bffepJiLRG346mN9WN confirmed archive/source closure but found missing raw
command provenance. StageA addendum recovers exact commands from the same Developer session's
executed-call context; it honestly labels missing full install logs/historical fingerprint files.
Original receipt/logs preserved. Independent offline rebuild into new output plus current
environment/lock/source inspection will provide directly observed command/evidence closure;
do not turn a recovered command list into an originally captured transcript.

Next: close actual package-smoke coverage findings, independent offline build/artifact-origin/
genuine SDK/native-byte verification, then reconcile Task6 evidence and local documentation.
The full product goal, real input/export/rights/accuracy, external-host, customer and operations
acceptance gates remain open; no new UI work or product slice closure.

### Package-smoke review rulings and independent execution handoff

Reviewer ses_eea8f356bffepJiLRG346mN9WN found two material harness-coverage gaps: SDK-returned
digest/size were never compared to the actual HTTP receipt, and target-job-only issuance counts
could miss an extra job under another ID. Primary verified both in the actual private driver.
Ruling: add those exact assertions with failing sensitivity controls, not alter product code,
worker control, grant policy, native byte oracle, deadlines or existing tests. The same Developer
repaired only `task6-package-smoke-recovery/fix1/`; SHA/size mismatch and extra other-ID issuance
controls now reject, and the full three genuine flows passed once. Reviewer re-review marked
G1/G2 addressed. An empty stdout file alone proves no command exit: independent execution must
record exact argv/cwd/exit, full pytest output and the generated result JSON, rather than use
author wall-time/exit claims as final proof. Minor note-only audit control is not a unit assert;
actual audit growth and total/target issuance remain observable in the genuine journals.

Independent runner ses_eea7d86e8ffeHmJ00clvsU9KPH now owns new verification scratch only:
offline three-package wheel/sdist + MCP-from-sdist rebuild, archive/source/installed RECORD/
origin/lock checks, lifecycle and assertion controls, full installed-SDK DSM/RGB/RGBA flow and
unchanged installed-console T14. Original author artifacts/receipts are retained. Parent Core
fixtures use the existing secure `/home/ksi/.cache` namespace via explicit parent HOME; temporary
build HOME is not appropriate for those fixture processes. This environment clarification is a
test-command boundary, not permission to weaken secure-file checks or inspect credential profiles.
No fresh bare full-suite claim is required for unchanged product runtime: previous full/static
evidence may be reused only after matching the original source freeze and log hashes.

### Full-goal acceptance audit — remaining gates after package verification

This table audits the requested product outcome, not a new implementation mandate. Requirements
come from PRD §1.1.1/1.1.2, ADR036/037/038 and the approved MCP spec; old roadmap WIP rows do not
override later verified implementation. Independent read-only reviewer
ses_eea7b9c48ffeCPLrRKezIvRrai inspected the current checkpoint/task ledger, C4–C7 reconciliation,
roadmap SDP/P-AC/GAP rows, product-state and the actual customer sample guide. It found no additional
concrete mandatory engineering task executable without external inputs or a new material contract;
package reconciliation/docs/local commit is still agent-owned work. This is conditional on the
pending independent package result, not a premature whole-goal completion or blocked declaration.

| Requested outcome | Concrete implementation/evidence | Remaining required evidence / owner |
| --- | --- | --- |
| Customer-owned registration, inspection, source/revision evidence | Existing ingress/inspection + C1/C2 history/detail local verified through 579cdfa; no KSI reconstruction engine/raw-upload substitution | Permitted actual exports and provenance/rights, customer owner; registration alone is not compatibility/accuracy acceptance |
| V2 analysis, revision-bound review, next-observation reuse | Existing V2 customer HTTP/browser/reload and C1–C3 closure in first-customer ledger; unchanged strict V1/V2/history semantics | Real same-Site/WorkArea t0→t1 and t1→t2 use and customer acceptance, customer/field owner |
| DSM/ortho region delivery with coordinates/native pixels/NoData/limits | Approved Spatial Data V1 + T5 generated DSM/RGB/RGBA Core/worker/HTTP/SDK hand-oracle parity, replay/rights/next-source tests | Actual supported customer files and independent consumer use, customer/integration owner; no format/accuracy guarantee |
| Dedicated local data MCP/common API/external workflow | T1–T5 commits 374849a/bed4d9c/f8afb01/bcca3c3/fc14059; six tools, consent/rights/ack, finite protected example; package runner pending | Installed external AI/client environment and actual owner use still separate; no universal host support |
| Required independent scoped/full/static/build/API checks and local Git | Prior scoped1349/full9028/122skip/102warnings, Ruff39/format39/mypy35, offline lock and 51-file freeze; Task6 package execution pending | Current package closure and final docs reconciliation, agent-owned; skipped tests remain unverified |
| Design-owned rendered review and actual UI auth/reload/persistence | C3 design review and production compiled-artifact OIDC/navigation/reload closure through579cdfa; no UI delta in MCP work | Human customer acceptance, not another redundant visual rewrite; any new visual delta requires design ownership |
| Actual host, runtime identity, rights/OIDC, cost/containment and recovery | Existing application bundle/OCI binding/degraded-boot are implemented local evidence, not deployed-host proof | Selected host/candidate/configuration/identity/backup custodian and scoped operations authorization, operations owner |
| Full product P-AC01..06 and EXT-VAL acceptance | Product-state current EXT-VAL slice retained; generated simulations and SDK conformance are explicitly local software only | Independent external developer/customer repeated use, permitted real sample, rights/cost/retention and owner acceptance |
| Feed/resync/PC/Mesh/external producer and result layer successors | Unselected future contracts under ADR038/SDP09, excluded from this accepted MCP spec | Material consumer/format/authority decision and approved spec/plan before implementation, product owner |
| Key incident/external effects/other workspaces | No secret reproduction, credential change, push/deploy/publication/signing/live grants/device/customer contact; unrelated/dirty worktrees retained | Affected-key rotation by account owner separately; it does not block safe independent development |

Recommended next product action is real-input first-platform validation, not duplicate C1–C3,
bundle/OCI/degraded-boot or another synthetic success run. Minimum supplied input is the sample
guide's same-Site t0/t1/t2 DSM, one ortho, requested boundary, CRS/vertical/unit/time/provenance and
processing/transfer/AI rights, in an explicitly permitted accessible location. No raw photos or
secret values need to be pasted into chat. Actual-host/client/cost/recovery verification requires
its own selected target and authorization; new expansion contracts remain optional decisions,
not guessed requirements or substitutes for this first-platform acceptance.

### Task6 independent built-package closure — 2026-10-07

Independent runner ses_eea7d86e8ffeHmJ00clvsU9KPH directly executed and captured command
argv/cwd/exit/stdout/stderr/timestamps in `/tmp/opencode/task6-package-final-verify/logs/`.
Its first execution reached the helper step limit after A/B; original work was retained and
the same runner finished only C/after/receipt, without repeating successful build/three-lane work.
This was a bounded helper execution limit, not a product failure or missing installation permission.

All four offline builds exited0, using existing authorized isolated Hatchling1.32.4:

```sh
B=/tmp/opencode/ksi-spatial-mcp-build-20261007-a1/buildvenv/bin/python
O=/tmp/opencode/task6-package-final-verify/out-a
uv build packages/domain --python "$B" --no-python-downloads --no-build-isolation --no-sources --no-config --offline --out-dir "$O/domain" --sdist --wheel
uv build packages/event-contracts --python "$B" --no-python-downloads --no-build-isolation --no-sources --no-config --offline --out-dir "$O/event-contracts" --sdist --wheel
uv build services/spatial-data-mcp --python "$B" --no-python-downloads --no-build-isolation --no-sources --no-config --offline --out-dir "$O/mcp" --sdist --wheel
uv build "$O/mcp/ksi_spatial_data_mcp-0.0.1.tar.gz" --python "$B" --no-python-downloads --no-build-isolation --no-sources --no-config --offline --out-dir "$O/mcp-from-sdist" --wheel
```

Actual build env was allowlisted/config-free, no interpreter download, install or external network;
only pre-existing task build/runtime environments were used. All seven artifacts matched StageA
hashes, and 68 modules matched source/wheels/installed bytes. MCP source/sdist wheel hash c16a656d
above is exact, not a broad cross-platform reproducibility guarantee. Archive traversal/path safety,
entrypoint/metadata, sdist required files, non-editable fresh runtime imports and installed lock
closure were checked. Fresh `uv export --package ksi-spatial-data-mcp --frozen --offline
--no-emit-workspace --no-emit-project --no-config -o <owned-closure>` matched prior requirements
apart from command-header comments. `uv pip check --python <runtimevenv/bin/python> --no-config
--offline` exited0,34 distributions;31 marker-applicable third-party requirements match the lock.

Copied frozen private harness `b-ns/fix1/` under the runner namespace proves
the missing SHA/size and extra-other-job issuance assertions via controlled RED exit3 / GREEN
exit0, not product correctness. Actual genuine `.venv/bin/python <runner b-ns/fix1/recovery_flows_fix1.py>`
then exited0: DSM/RGB/RGBA all completed, six child exits0, SDK and console from isolated installed
artifacts (`python -I`, no source PYTHONPATH), same-key second stdio process uses the same job,
total/target issued counts1→1 and upload1 per lane, no workspace leftovers, SDK hash/size equals
HTTP receipt and byte/native pixel/mask/affine/bounds/CRS oracle. Worker control remains genuine
in-process HTTPS-mounted Core + raster child, not deployed network-worker evidence.

The original author's `fix1/receipt.json` contains wrong/short manually transcribed RGB/RGBA
hash strings; its raw `fix1/fix1_flows.json` matches the independently observed full hashes for
all three kinds. Original receipt SHA513fe54298d75f3dd0ade21dfe69cbbff67519f96cc0d86c4db3a0ea5cc21b12
is retained as inaccurate historical evidence, NOT the canonical byte receipt. Runner raw-result
comparison is programmatic; there is no demonstrated nondeterministic writer or transport fault.

Final C command from repository cwd, only parent plugin PYTHONPATH, HOME=/home/ksi:

```sh
.venv/bin/python -m pytest tests/contract/test_spatial_data_mcp_http_integration.py -p task6_smoke_plugin -q -rf
```

Exit0: **14 passed,0skipped,0warnings**,29.04s;13 console spawns plus a separate origin proof,
all absolute installed console, own empty cwd, child PYTHONPATH/VIRTUAL_ENV absent. Existing
Core/worker/grant/rights/oracle assertions were not mocked or changed. AFTER source68/HEAD/root
lock/shared `.venv` cfg and distribution metadata unchanged; `git diff --check`0. The continuation
ledger was the only product-checkout delta. No fresh bare-full/static claim: earlier final
full9028/122skip/102warn/static evidence remains at its recorded unchanged runtime snapshot.

Canonical package receipt SHA256
`db1258a1577dd7246fb273768f56f81c3211d24bad17da5b04e7ae763565e7ef`;
report SHA256 `231bebd51e3ed48f84a40a096d481deceaa578a9d7f2a80c0abb1f318fcdc446`.
Both0600 and nonempty. Exact witness hashes and raw results are retained in that owned namespace.
Task6 distribution verification obligation is now achieved for local built-package execution,
not public distribution, AI-host/customer installation, deployed worker/Core or product acceptance.

Final closeout delta is documentation only: this ledger, the MCP plan checkbox, software-evidence
document and service README. README updates the stale source-only description; its changed sdist
documentation needs an offline packaging/unchanged-module validation before the closeout commit.
The installed runtime test bytes remain the exact d68b0fb package snapshot. No UI changes.

### Final documentation/package snapshot and local closeout

Scoped docs reviewer ses_eea8f356bffepJiLRG346mN9WN verified the four-path diff against the
canonical independent receipts and required the current README sdist rebuild before commit.
Independent runner ses_eea7d86e8ffeHmJ00clvsU9KPH completed that exact docs-only check:
47/47 non-document entries of the prior 51-file final freeze match; all 68 package modules,
root lock and shared environment fingerprints unchanged. Earlier full/scoped/static receipt
snapshots differ only at the four intended documents; no runtime/test/contract delta or fresh
bare-full-suite claim. `git diff --check` exited 0.

Two fresh offline MCP build commands (current source wheel/sdist, then its sdist wheel) exited 0.
The current README is in the fresh sdist; pyproject/module bytes/entrypoint/metadata are unchanged.
Current MCP wheel and from-sdist wheel remain the exact tested c16a656d hash. Current MCP sdist:
`d96076bc24196851b7f394a31dc27d9b60aa7922126d2b59bc855918da2fa664`.
Final docs/package receipt `/tmp/opencode/task6-package-final-verify/docs-final/receipt.json` SHA256:
`6fa66bb42be7cef6c4e6d884cad56071c7b67b39eedb5c0ca5825c75eb14fc38`;
report SHA256 `21db6c60367b2cff3d04ceb80e5ecc836902fe65bdccd6b51050080fc62958aa`.
Raw artifacts and original failed attempts remain retained; no unrelated worktree was cleaned.

Task6 and SDP-CLIENT-01-AI are now complete **only as local software/built-package verification**.
Primary will commit exactly the four task-owned documents on the existing authorized local main;
no branch merge, push, PR, publication, deployment, AI-host setup or customer acceptance is implied.
The independent remaining-goal audit above found no further executable mandatory engineering
repair outside the now-closed package obligation. Next product progress requires the actual
permitted customer inputs/rights or a selected and explicitly authorized host/operations stage;
new feed/resync/external-result contracts remain material decisions, not assumed implementation.

### Committed evidence and actual external-input impasse

Four documentation changes were committed locally as `e7020f6d3cb8bc3d4e3321fe5ca8bd588b57f46d`.
Independent runner ses_eea7d86e8ffeHmJ00clvsU9KPH confirmed clean main, exact four-document commit,
51/51 working-file/committed-blob equality, 47/47 unchanged non-document freeze entries and all
68 package modules. Current README equals the new sdist; installed/source/sdist wheel bytes match.
Its first postcommit proof mistakenly reported no prior log-hash keys. Primary inspected actual
`commands[]` entries (`log`, `sha256`) and the same runner corrected that lookup: nine prior full/
static command logs plus the reused scoped log all rehash exactly, recorded exits0. Actual log
tails confirm full9028/122skip/102warnings, scoped1349/54warnings and the recorded static results.
Original interpretation remains preserved, superseded by
`/tmp/opencode/task6-package-final-verify/docs-final/commit-proof-correction.json`, SHA256
`c4537121e9e62a707a321069a17d329eecb9ce85caabacbb3972171ba1bf95a6`;
prior-log integrity receipt SHA256 `02c8d95f2c03ca111f86b922d511a65040192137ffa9868a7274d7f395da8ccb`.

At the next required-input gate the Human explicitly answered **“자료와 환경이 아직 없음”**.
The independently audited remaining requirements therefore cannot advance: permitted actual
same-Site t0/t1/t2 DSM/ortho/boundary/provenance/coordinate/vertical/rights input and selected actual
host/OIDC/MCP/operations/cost/containment/recovery evidence are absent. Safe mandatory approved
agent-owned engineering work is exhausted; no new expansion contract or external execution is
authorized by that answer. Repeated generated tests or invented features cannot meet those criteria.
Native full-objective goal ef9e2d2c-989e-411a-99ee-1da204f8dd6f was recorded **unmet, stopReason blocked**,
not complete, paused, cancelled, narrowed or replaced. Objective/history are preserved; no automatic
continuation or revival of closed/cancelled goals. Product-state EXT-VAL/P-AC and customer/field/
operations acceptance remain unchanged and open. Account-owner key rotation remains separate.

Next prerequisite owners: customer/field owner provides accessible permitted export/rights evidence
as described in `docs/acceptance/SPATIAL_PLATFORM_CUSTOMER_SAMPLE.md`; operations owner selects the
actual target and authorizes its scoped verification. Then resume product work under a new explicit
task/eligible goal contract, not by treating this closed unmet goal as active. No secret values,
full raw-photo transfer, new hardware, publication or deployment are implied by this handoff.
