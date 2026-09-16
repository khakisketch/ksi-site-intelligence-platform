# External product loop — A2 Console browser pass (2026-09-17)

## Scope and authority

This audit faithfully transcribes the A2 Console browser-pass evidence whose source
of truth is `.dev-data/a2/EVIDENCE.md` (223 lines, read 2026-09-17). Recipe:
`.dev-data/a2/RECIPE.md`. Checklist authority:
`docs/ops/BROWSER_E2E_CHECKLIST.md:109-128` (§4A, full-pass `NOT_RUN`).
HEAD `4cec7a61fefcbd2e92212be82472b2541ed20db9` (verified `git rev-parse HEAD`
at run time). It records evidence for the `external-customer-ingress` workstream
owned by
[ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md)
and gated by `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`.
It is evidence, not product or current-state authority, and it sets no gate verdict.

Rank: below the frozen authorities (`PRODUCT_CONSTITUTION`, `FINAL_DECISION_LEDGER`,
`MASTER_PRD`, `DOMAIN_INVARIANTS`), below ADR-KSI-036 and
`docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`, and below the release
plan `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md` and the
quantitative specification
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
(implementation history); this evidence decides nothing.

**Scope statement — this is a local-only browser pass of BROWSER_E2E_CHECKLIST
section 4A against the decomposed stack.** It is NOT staging/deployment evidence,
NOT vendor export-compatibility evidence, NOT HIL/field acceptance, and NOT a
happy-path proof: the 4A.5–4A.7 positive paths were not executable with synthetic
fixtures (E6 chain below), and every reachable BFF state was asserted without
inventing facts to force the happy path.

Run root: `.dev-data/a2/` (data, worker-work, logs, identity, operator,
signing-keys, screenshots, artifacts). No A1 journal reuse: A1 facts are scoped to
`org-a` while every OIDC browser session is `org-local-pilot`; `<a2>/data` is fresh
and re-driven via the browser session (RECIPE §5 rule 2). Operator/authority
material was generated fresh by `.dev-data/a2/gen_a2_material.py` (adapted from
`.dev-data/external-loop/gen_material.py` with the §5-rule-4 semantic change: all
principals + authority records scoped to `org-local-pilot`).
Material generation reported `{"ok": true, "authorityDigest":
"sha256:3f3592…88ca5"}`. Principals: `worker-1` (PROCESSING_WORKER,
`org-local-pilot`) + `admin-1` (OPERATOR/ADMIN, `org-local-pilot`); no human
OPERATOR tokens (OIDC covers humans). Catalog
`executionTemplates[].authorizedActorIds = ["local-admin",
"local-field-operator", "worker-1"]`.

## Outcome per step (exact)

| Step | Action | HTTP status / assertion | Screenshot | Result |
|------|--------|-------------------------|------------|--------|
| SETUP | OIDC login + create site `a2-console-site` (201), work-area `wa-a2-console-site-0001` (201), EXTERNAL_RECONSTRUCTION work-order `obs-work-00000001` (201, org-local-pilot, cycle 1); `expectedEpochId=obs-epoch-e7ebe0fc2db2bb452a5bcda5` derived client-side from the deterministic Core rule (`analysis_readiness.py:30-36`) | 201/201/201 + local derivation | `screenshots/setup.png` | PASS |
| 4A.1 | register submission → opaque `submissionRef=ers-v1-d6100…399af` | 201 | — | PASS |
| 4A.1 | request upload grants (ortho + dsm presigned PUTs, `requiredHeaders` preserved) | 200 | — | PASS |
| 4A.1 | PUT ortho bytes → 200; PUT dsm bytes → 200 (synthetic deterministic payloads, sha256/size declared) | 200/200 | — | PASS |
| 4A.1 | seal revision → `state=SEALED` | 200 | — | PASS |
| 4A.2 | operator: snapshot seq 2 (policy `a2-geotiff-v1` v1 + authority, subject-01) + reload | 200 `PROVIDER_CONFIGURED seq=2` | — | PASS |
| 4A.2 | operator inspection lane: LIST 1 pending (`eai-v1-711f…`), LEASE `LEASED`, INPUT `INSPECTION/INSPECT`, REPORT all-artifact `REJECTED/UNSUPPORTED_RASTER` (truthful: synthetic bytes are not parseable GeoTIFF; no fabricated MEASURED facts) | 200/200/200/200 `REPORTED` | — | PASS |
| 4A.2 | BFF poll inspection → `SEALED/SEALED`, `INSPECTION_REPORTED/COMPLETE`, outcomes 2×`REJECTED/UNSUPPORTED_RASTER`, display `PENDING_INSPECTION` (terminal-by-completion: no display queued without measured ortho) | 200 | `screenshots/stage4.png` | PASS (terminal) |
| 4A.3 | declare evidence → `eev-v1-1a95…` (201); grant → 200; PUT → 200; seal → `SEALED_BYTE_OBSERVED` (200); list → 200 | 201/200/200/200/200 | — | PASS (browser lane) |
| 4A.3 | operator evidence-validation lane: LIST → 200 empty (no validation issued — issuance requires an admitted evidence context carrying an independence attestation; authoring one for synthetic bytes would write false facts to a durable journal, so the lane was NOT driven) | 200 `NO_PENDING` | — | PASS with boundary (see §4A.3 note) |
| 4A.4 | single DISPLAY → 201 `BLOCKED / POLICY_UNAVAILABLE / AUTHORIZE_POLICY` (`…b2510bf4`); single HEIGHT → 201 `BLOCKED / HEIGHT_PRODUCT_DEFINITION_UNRESOLVED / DEFINE_HEIGHT_PRODUCT` (`…ceca831c`) | 201/201 | `screenshots/stage4.png` | PASS (verdict+reasons+remediations asserted) |
| 4A.4 | pair same-submission baseline → 422 `EXTERNAL_USE_SELECTION_INVALID` ×2 (`PAIR_SUBJECTS_NOT_DISTINCT` — pairs require distinct epochs) | 422/422 | — | PASS (structural rejection asserted) |
| 4A.4 | operator: WO-02 `obs-work-00000002` (201) + submission `a2-sub-02` sealed (`ers-v1-715a…`, 201/200/PUTs 200/seal 200); snapshot seq 3 (policy v2 + authority permitting exact pair `(sub-02, sub-01)`) + reload | 200 `PROVIDER_CONFIGURED seq=3` | `screenshots/stage5.png` | PASS |
| 4A.4 | pair VISUAL_COMPARISON (distinct baseline) → 201 `BLOCKED / POLICY_UNAVAILABLE` (`…837906e2`); pair RELATIVE_VOLUME (`zoneId=wa-a2-console-site-0001`) → 201 `BLOCKED / INSPECTION_REPORT_BINDING_INVALID / COMPLETE_CURRENT_INSPECTION` (`…a2529bc2`) | 201/201 | `screenshots/stage6.png` | PASS (verdict+reasons+remediations asserted) |
| 4A.5 | issue relative volume with RELATIVE_VOLUME `decisionRef` + fresh `Idempotency-Key` → 422 `AUTHORITY_UNAVAILABLE` (decision BLOCKED → no issuance); history → 200 empty | 422/200 | — | ATTEMPTED, refused by design (not executable without a real measurement fixture chain) |
| 4A.6 | positive (record + idempotent read-back) — BLOCKED: no `reportRef` exists (no volume report was ever issued; refs are Core-generated, not inventable) | — | — | NOT EXECUTABLE |
| 4A.6 | negative: role-test login as `local-viewer` → 200 `/`; viewer review POST (format-valid ref) → 403 (BFF: `이 작업을 수행할 권한이 없습니다.`); Core-direct viewer → 403 `권한이 부족하다`; Core-direct worker → 403; admin control (same fake ref) → 409 `EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE` (proves viewer 403 is the role gate, not missing-report) | 200/403/403/403/409 | `screenshots/viewer.png`, `screenshots/authorize-probe.png` | PASS (negative proven; exact-string drift noted in Blockers) |
| 4A.7 | create + approve proposal — BLOCKED: requires a real `reportRef` (none exists; format-validated, Core-generated) | — | — | NOT EXECUTABLE |
| 4A.8 | pure projection helper `presentExternalInspectionStatus` — no screen mounts it | — | — | MANUAL-ONLY by design |

Login result (SETUP prerequisite): SUCCESS via headless Chromium (`apps/dashboard`
Playwright lib, `.dev-data/a2/a2_login.mjs`). `GET /` → login page; clicked
`개발 Operations Console 시작|조직 계정으로 로그인`
(`operations-console.spec.ts:22-25` verbatim). Account picker NOT shown
(`hasAccountPicker=false`) — auto-authorized via `login_hint=local-admin` as the
recipe predicts. Landed `/`, `<main>` visible; sidebar `local-admin / 관리자`;
site list empty (`아직 등록된 현장이 없습니다`) — fresh `org-local-pilot` scope,
no A1 journal leakage. Screenshot: `.dev-data/a2/screenshots/login.png`.

## Deviations (recorded as found, in substance)

- D1: MinIO image `minio/minio:latest` (+ `minio/mc:latest`) from the local daemon
  instead of the pinned
  `minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea…` (no network pulls;
  exact pin not present locally). Recorded in evidence, not silently substituted.
- D2: protected run root `~/.local/state/ksi-a2-console/` (mode 0700, 0600 files;
  chain `~/.local`, `~/.local/state` 0700, `/home/ksi` 0750 — verified clean per
  `_protected_bytes` rule) holds `operator/`, `signing-keys/`, `data/`,
  `worker-work/`. Cause: the production factory's external-authority loader
  rejects any config whose ancestor chain is group-writable
  (`external_authority_provider.py:121-140` walks EVERY parent from `/`); the repo
  chain (repo root, `KSI-Projects`, `.dev-data` all 0775) can never satisfy it, and
  those shared dirs are outside this pass's write ownership so they were NOT
  chmodded. First boot failed verbatim `ValueError: authority provider
  configuration has an unprotected parent` (`.dev-data/a2/logs/core.log`
  pre-fix); after copying material + rewriting the two embedded absolute-path
  pairs (`workflow.json`: `authorityJournalPath`, `catalogPath`;
  `external-authority-provider.json`: `keyRegistryPath`, `snapshotPath`) to the
  new root, Core booted. Scripts (`start_core.py`, `start_worker.py`), identity
  secrets, logs, screenshots, and the evidence file stay under `.dev-data/a2/`
  (allowed path; no protected-parent check applies there).
- D3: snapshot seq 3 re-issued validity (`issuedAt`/`validUntil` = now∓1h/±1h)
  with the local dummy authority key (same test-helper pattern as the generation
  script); prior `validUntil` (05:36:47Z) would otherwise have expired mid-pass.
- E1: Dashboard `node_modules/@noble/hashes` was absent although
  `apps/dashboard/package.json:17` + lock pin `2.4.0` (route
  `lib/external-reconstruction-submission.ts:1-2` imports it) → register BFF threw
  500 `Module not found`. Repaired with
  `npm install --no-save --no-audit --no-fund @noble/hashes@2.4.0` (node_modules
  only; `package.json`/lock untouched, verified via `git status`). Environment
  drift, not a product bug.
- E2: Dashboard dev auto-rewrote tracked `apps/dashboard/tsconfig.json`
  (`.next-a2` includes); restored via `git checkout --` after the pass step. Tree
  is clean except untracked `.opencode/` + gitignored `.dev-data/`.
- E3: BFF sessions are short-lived here (OIDC access TTL 300s; refresh does not
  survive across dispatches). A stale `storageState` yields 400
  `INVALID_EXTERNAL_RECONSTRUCTION_REQUEST` (GET) or 500 `MissingSessionError`
  (POST). Fix: fresh browser login per stage (`storage-fresh.json`,
  `storage-stage4/5/6.json`, `storage-admin7.json`, `storage-viewer.json`).
- E4: In `KSI_CORE_HUMAN_AUTH_MODE=OIDC`, opaque OPERATOR tokens are rejected
  (`auth.py:_resolve_principal` returns non-OPERATOR opaque principals only;
  `admin-1` Bearer → 401). Core-direct OPERATOR calls (authority reload) used a
  real `local-admin` OIDC access token minted via the documented auto-authorized
  code flow (`a2_mint_operator_token.mjs`: PKCE + local dummy client secret, 302
  Location captured with manual-redirect fetch so Auth.js never consumes the
  single-use code). Same principal/org/role as the browser session — no privilege
  escalation. Token TTL 300s: re-mint before each OPERATOR-gated call. Token
  values are never stored (dummy placeholders only in this audit).
- E5: A reload candidate must extend the Core-retained receipt history
  (`sequence == prior+1`, `previousSnapshotDigest == prior digest`), else `BLOCKED`
  (`_validate_history`). First seq-3 attempt reused file sequence (3 vs retained
  1) → `200 BLOCKED, sequence/digest null`; fixed by chaining from the receipts
  journal (receipts: seq 1 `a2b62…` → seq 2 `3223fd…` → seq 3 `8f0f84…`). Never
  hand-sequence snapshots.
- E6 (honesty boundary): worker-lane outcomes filed truthfully for synthetic
  fixtures — inspection `REJECTED/UNSUPPORTED_RASTER` (bytes genuinely not
  parseable TIFF; a real inspector reports the same), no fabricated MEASURED
  raster facts, no evidence independence attestation, no invented metrics.
  Consequence chain: no MEASURED ortho → no display → pair RELATIVE_VOLUME
  `BLOCKED/INSPECTION_REPORT_BINDING_INVALID` → volume issue `422
  AUTHORITY_UNAVAILABLE` → no `reportRef` → 4A.6-positive/4A.7 not executable.
  Every reachable BFF state was asserted; nothing was invented to force the happy
  path. A measured happy path needs real raster/checkpoint fixtures — a future
  real-measurement fixture-authoring task, not more browser automation.

## Blockers (verbatim in substance)

- `RELOAD 200 {"status": "BLOCKED", "sequence": null, "snapshotDigest": null}`
  on the first seq-3 attempt — cause: candidate sequence/prev did not extend
  retained receipts (E5). Resolved the same dispatch by chaining from receipts.
- Pair same-baseline: `422 {"code":"EXTERNAL_USE_SELECTION_INVALID"}` — cause:
  `PAIR_SUBJECTS_NOT_DISTINCT` (pairs require distinct epochs). Resolved with
  WO-02/sub-02 baseline + policy v2.
- Volume issue: `422 {"message":"요청을 처리하지 못했습니다.
  (AUTHORITY_UNAVAILABLE)","code":"AUTHORITY_UNAVAILABLE"}` on an honest BLOCKED
  RELATIVE_VOLUME decision — by design (E6 chain), not a defect.
- Recipe drift (B8-class): 4A.6 negative expects `403 HUMAN_REVIEW_REQUIRED`
  (cited `external_result_workflow_api.py:485`), but over HTTP every unauthorized
  review attempt yields generic 403 (`권한이 부족하다` /
  `이 작업을 수행할 권한이 없습니다.`): the kind-check at :485 is shadowed by the
  `write_dependency` permission gate, which evaluates first. Viewer role gate
  proven by admin-vs-viewer control (409 vs 403 on the identical fake ref). Exact
  `HUMAN_REVIEW_REQUIRED` string not observable over HTTP in this assembly.
- No other blockers. No step required inputs beyond local fixtures.

## Manual-judgment steps

- 4A.8: manual-only by design — `presentExternalInspectionStatus`
  (`app/field/external-reconstruction-status.ts:56-186`) is a pure function; no
  screen mounts it, so live-browser projection rendering is unobservable.
- 4A.2 display rendering: no upload/inspection screen exists (RECIPE §4) —
  terminal enums asserted at BFF-JSON level (`INSPECTION_REPORTED/COMPLETE`,
  display `PENDING_INSPECTION`); headed judgment against a screen is impossible
  without new UI (requires Build approval per checklist §9).
- 4A.3 measurement summaries: not observable — the validation lane needs an
  admitted evidence context with a truthful independence attestation (E6); sealed
  lane (`SEALED_BYTE_OBSERVED`) asserted instead.
- 4A.4–4A.7 render assertions: no report-view / decision / proposal screens exist
  — all assertions are BFF-JSON level (verdicts, reasons, remediations, refs,
  flags would-be). Blocked-pair typed-blocker rendering likewise has no screen
  (RECIPE §4: assert JSON shape only — done: `BLOCKED` + reasons).
- 4A.5–4A.7 positive flows: not executable with synthetic fixtures (E6 chain).
  Reaching `ISSUED`/report/reviews/proposals requires measured inspection +
  validated evidence + compatibility mapping — i.e., real measurement fixtures,
  which is a fixture-authoring task, not a browser finding.

## Components and ports

| # | Component | Port | Status | Evidence |
|---|-----------|------|--------|----------|
| 1 | Local Identity issuer | 9120 | UP (at pass time) | `GET /healthz` → 200; discovery `issuer=http://localhost:9120` (log `.dev-data/a2/logs/issuer.log`) |
| 2 | MinIO | 9002/9003 | UP (at pass time) | `GET /minio/health/live` → 200 (container `a2-minio`, `minio/minio:latest`); bucket `ksi-a2-console-evidence` fresh/empty via `mc ls` |
| 3 | Core (production factory) | 8020 | UP (at pass time) | `GET /ready` → 200 `{"ready":true}`; `GET /ready/external-authority` → 200 `{"status":"PROVIDER_CONFIGURED"}` (log `.dev-data/a2/logs/core.log`) |
| 4 | Processing worker | — | UP (at pass time) | Polling Core lanes, all `HTTP 200` (log `.dev-data/a2/logs/worker.log`) |
| 5 | Dashboard dev server | 3320 | UP (at pass time) | `GET /login` → 200 (`KSI_DASHBOARD_DIST_DIR=.next-a2`; log `.dev-data/a2/logs/dashboard.log`) |

## Screenshot inventory

9 files observed under `.dev-data/a2/screenshots/` at audit-write time (the
assignment brief described 10; 9 were present — listed exactly, nothing inferred):

```text
authorize-probe.png
final-console.png
login-page.png
login.png
setup.png
stage4.png
stage5.png
stage6.png
viewer.png
```

`final-console.png` and `login-page.png` are auxiliary captures not mapped to a
checklist step in `.dev-data/a2/EVIDENCE.md`.

## Final state

All components STOPPED after the pass (ports 9120/9002/8020/3320 verified down,
no residual processes). `git status` shows no tracked modifications (tree clean
except untracked `.opencode/` + gitignored `.dev-data/`). Protected run root
retained: `~/.local/state/ksi-a2-console/` (0700/0600, authority generation seq 3
`8f0f84…`; snapshot `validUntil` now expired — re-issue via `admit_policy_seq3.py`
pattern before any new reload).

## Resume / stop commands (local-only summary)

> Fencing: local-only reproduction aid. The MinIO image is unpinned
> (`minio/minio:latest`) and any credentials are local dummy placeholders — never
> promote this snippet to staging assets. Staging images must be exact version +
> OCI digest pinned per INV-054, and staging credentials must never be literals in
> the repo.

```sh
# Stop (each in its own command; never combine pkill with a launch):
pkill -f "[s]tart_core[.]py"
pkill -f "[s]tart_worker[.]py"
docker stop -t 10 a2-minio  # container name per evidence; do not remove blindly
```

```sh
# Re-run (in order; repo root = /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform):
# 1. Issuer (port 9120):
uv run python tools/run_local_oidc_issuer.py --host 127.0.0.1 --port 9120 \
  --issuer-origin http://localhost:9120 --dashboard-origin http://localhost:3320 \
  --client-id ksi-operations-console \
  --client-secret-file <repo>/.dev-data/a2/identity/secrets/dashboard-oidc-client.secret \
  --state-dir <repo>/.dev-data/a2/identity --core-audience ksi-core
# 2. MinIO: container `a2-minio` (`docker start a2-minio`),
#    bucket `ksi-a2-console-evidence` (contains the uploaded 4A.1/4A.3/stage-5 objects)
# 3. Core: `uv run --project services/core python .dev-data/a2/start_core.py`
#    (repo root; env inside script, protected root `~/.local/state/ksi-a2-console`)
# 4. Worker: `uv run --project services/processing-controller python .dev-data/a2/start_worker.py`
# 5. Dashboard: `next dev --hostname 127.0.0.1 --port 3320` from `apps/dashboard/`
#    with the §1c env (see log header); readiness `GET http://127.0.0.1:3320/login`
# All logs: `.dev-data/a2/logs/{issuer,core,worker,dashboard}.log`.
# Durable pass state: `.dev-data/a2/run-state.json` (WO-01 `obs-work-00000001` +
# sub-01 `ers-v1-d6100…` + WO-02/baseline sub-02 `ers-v1-715a…`).
# BFF sessions in `storage-*.json` are EXPIRED (re-login per stage; E3), OIDC
# operator token `operator-token.json` expired (re-mint; E4).
# Scripts: `a2_login.mjs`, `a2_stage1_setup.mjs`, `a2_stage2_4a1.mjs`,
# `a2_stage3_inspect_evidence.mjs`, `a2_stage4_volume.mjs`,
# `a2_stage5_baseline.mjs`, `a2_stage6_pairs.mjs`, `a2_stage7_viewer.mjs`,
# `a2_mint_operator_token.mjs`, `drive_inspection.py`, `drive_evidence.py`,
# `admit_policy.py`, `admit_policy_seq3.py`.
# Never copy `.dev-data/a2/operator/*.json` over the protected copies.
```
