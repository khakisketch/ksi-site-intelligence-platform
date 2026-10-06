# Spatial data product continuation — 2026-10-06

Status: ACTIVE checkout task; existing V1 reconciliation and bounded consumer repair.
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
- [ ] Present successor choices grounded in actual missing functionality; selected material
  design → written spec review → implementation plan review/method → approved execution.
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
