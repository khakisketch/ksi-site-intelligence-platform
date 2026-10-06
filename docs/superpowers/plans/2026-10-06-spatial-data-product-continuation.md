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
