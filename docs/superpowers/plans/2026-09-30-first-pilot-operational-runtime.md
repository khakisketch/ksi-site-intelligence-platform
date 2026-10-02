# First pilot operational runtime implementation plan

> 2026-09-30 resume hold: the user requested product-direction/planning documentation only and
> explicitly excluded further development. Preserve completed local FPO evidence and unfinished
> host/customer gates below. Resume through [SDP-20260930](2026-09-30-spatial-data-platform-roadmap.md)
> and the checkpoint after a new user instruction; FPO-04 is not the current authorized next action.

> For agentic workers: use `superpowers:executing-plans` with the bounded task packet. No commit, host change, credential installation, deployment, or release follows from this plan.

**Plan ID:** FPO-20260930. **Goal:** Prepare an independently operated Analysis worker and a reviewable Tailnet/OIDC pilot deployment route; keep field and release acceptance separate.

**Architecture:** Core retains signed Analysis activation, admission, policy, and durable results. A dedicated local worker process uses a protected immutable configuration and its own token file to poll only Analysis jobs. The pilot HTTPS surface is Tailnet scoped; customer OIDC and host release evidence are supplied and verified at an explicit later gate.

**Tech stack:** Python 3.12, systemd, Docker Compose, FastAPI Core, Next.js dashboard, pytest.

**Spec:** `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`, `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`, `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`.

## Scope and constraints

- Requirement IDs: REQ-INT-101..104, REQ-SEC-101, REQ-OPS-101/102; INV-020/024/040/051/053/054/060/061.
- Owner module: Analysis worker in `services/processing-controller/`; Core owns authority; `deploy/` owns optional host assembly.
- Acceptance: local package starts fail closed with a protected config and separate token, never falls back to a general processing principal, and preserves retry/fence semantics. Pilot deployment remains unclaimed until exact host, image/SBOM, OIDC, backup/restore and customer tests pass.
- Contracts affected: none for the worker configuration; existing AnalysisActivationV1 and Analysis worker API remain authoritative.
- Reference assets: `external_analysis_runner.py`, `external_analysis_worker.py`, `external_analysis_core_client.py`, existing external runtime systemd isolation pattern. No runtime import from `references/`.
- Adoption: reuse the existing GIS algorithm and Core lease API; add only packaging/configuration needed for independent operation. No reconstruction service or dev OIDC issuer in the customer path.
- HIL/real-device: none for local code; real customer DSM and host operations are separate gates.
- License/data: customer controls Terra and original capture; local tests use synthetic DSM only. No customer files or secrets in Git.
- Rollback: remove additive worker config/host templates; historical Analysis and V1 data remain unchanged.

## Review focus

- Configuration file symlink, owner/mode, oversize, malformed JSON or unexpected key must fail before any Core request.
- Token bytes never appear in argv, config, logs or exception text; token owner/mode remains 0600.
- General processing identity cannot poll, lease or report an Analysis job; worker identity cannot use general processing routes.
- Restart during a leased job cannot turn a stale attempt into a successful report; Core fencing remains authoritative.
- Pilot exposure must not bind a public listener or accept a development issuer; missing customer OIDC inputs must fail closed.

## Tasks

### FPO-01 — Protected Analysis worker launch configuration

**Owner:** Processing worker. **Depends:** P2 and P3 local integration. **Files:** add `services/processing-controller/src/ksi_processing_controller/external_analysis_worker_config.py`; edit `external_analysis_runner.py` and its narrow contract tests/README.

**Interface:** `load_analysis_worker_config(path: str) -> AnalysisWorkerConfigV1` reads one absolute owner-protected regular JSON file with a bounded size, exact keys, static Core literal-IP origin, runtime identity, trusted object endpoints and finite resource/HTTP limits. Runner accepts `--config` and `--worker-token-file`; previous explicit-argument test route may be retained for local compatibility, but no production default or secret in config. The config loader has no network or file creation side effects.

- [ ] Write tests for valid config, symlink/mode/owner/oversize/unknown-key/invalid-limit rejection and no request on failure; observe RED.
- [ ] Implement loader and runner wiring; observe GREEN on targeted tests, Ruff and mypy.
- [ ] Verify existing lease/retry/recovery tests unchanged; freeze exact source and independently review security boundary before integration.

### FPO-02 — Independently started worker service candidate

**Owner:** Processing/operations. **Depends:** FPO-01. **Files:** additive `deploy/analysis-pilot/` service unit and operator guide, plus service contract test.

**Interface:** a systemd `Type=exec` unit starts the FPO-01 CLI as a distinct non-Docker-group UID, reads only protected config/token, has no listener, restricts filesystem/capabilities/namespace/syscalls, and uses fixed Core and object network endpoints. The guide states exact account, filesystem, runtime digest, activation, log, restart, backup and rollback checks; it performs no host mutation.

- [ ] Write a static service contract test for identity, token/config paths, sandbox and non-public behavior; observe RED.
- [ ] Add the unit and guide; observe GREEN and `systemd-analyze verify` where available.
- [ ] Freeze and independently review unit/config/identity boundary before integration.

### FPO-03 — Tailnet HTTPS and customer OIDC candidate

**Owner:** Operations/Core/Dashboard. **Depends:** FPO-02. **Files:** additive `deploy/analysis-pilot/` Tailnet profile and contract tests.

**Interface:** local services bind loopback only and HTTPS is exposed only through the host Tailnet identity. Core and Dashboard use customer OIDC issuer/audience/JWKS and protected `iss+sub` mapping; absent or mismatched values fail closed. No development OIDC issuer is in the pilot profile.

- [ ] Test rejected public bind, absent OIDC values and dev issuer; observe RED.
- [ ] Add a reviewable profile and customer IT input checklist; observe GREEN in static and local synthetic tests.
- [ ] Keep actual Tailnet, OIDC app registration and credentials for separately authorized host work.

### FPO-04 — Release and recovery evidence gate

**Owner:** Lead/operations. **Depends:** FPO-01..03 and authorized clean source state. **Files:** `deploy/analysis-pilot/` runbook and external evidence inventory.

- [ ] Record exact commit/image/SBOM/scanner/host binding, separate principal/token, signed activation, logging, backup and restore evidence; never substitute local test results.
- [ ] Rehearse restart, stale lease fencing, activation expiry and durable-history retrieval against the approved host candidate.
- [ ] Request separate human authorization before any commit, credential installation, host change or deployment; field acceptance still requires P5/P6 customer inputs.

## Current state

P3 local code and test gate passed; remote CI, clean release source, actual customer OIDC/Terra and host evidence are absent. FPO-01 protected configuration was implemented in the isolated candidate, independently reviewed PASS after oversized-integer correction, and integrated byte-exact. Review freeze: `.opencode/artifacts/first-product-completion-20260929/fpo01-analysis-worker-config-review-freeze-v2.json`. Main targeted config/worker-loop/recovery command: `uv run --package ksi-processing-controller pytest -q tests/contract/test_external_analysis_worker_config.py tests/contract/test_external_analysis_worker_loop.py tests/contract/test_external_analysis_worker_recovery_integration.py` — 40 passed. FPO-02 independent service candidate and token ancestry correction were reviewed PASS and integrated byte-exact; freeze `.opencode/artifacts/first-product-completion-20260929/fpo02-analysis-worker-service-review-freeze-v2.json`. Main service/config/loop/recovery tests: 49 passed. `systemd-analyze verify` cannot fully pass until the operator installs the immutable worker at `/opt/ksi-analysis/venv/bin/ksi-external-analysis-worker`; no unit/account was installed. FPO-03 separate loopback Compose, customer OIDC/Tailnet preflight, and bucket-only initializer were reviewed PASS after secret-length, checked-file and IAM corrections; freeze `.opencode/artifacts/first-product-completion-20260929/fpo03-tailnet-oidc-review-freeze-v3.json`. Main deployment/service candidate tests: 30 passed; candidate Compose was parsed with synthetic values, not started. FPO-04 release/host and field gates remain unverified.

## FPO-04 evidence inventory (not an approval)

| Gate | Current evidence | Next required evidence |
| --- | --- | --- |
| Exact release source | Dirty main/candidate WIP at `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; FPO-01..03 frozen file hashes above | Separately approved commit, clean Git tree and CI on that exact source |
| Core/Dashboard/worker runtime | Reviewed local source and synthetic Compose; no installed worker executable | Built exact images and immutable worker bundle, SBOM/scanner, runtime/lock digest and host binding reviewed against signed activation |
| Host isolation and HTTPS | Unit/loopback Compose candidate only | Distinct UID/GID and no Docker group, effective systemd/cgroup egress, actual `*.ts.net` Serve routes, absence of public listeners, TLS and firewall observations |
| Customer login | Protected `iss+sub` and scope code; no customer issuer or test subject | Customer IT issuer/audience/JWKS, app registration and secret through approved channel, subject registry, signed token and rejected cross-scope login probes |
| Object and durable data | Bucket-only initializer and explicit IAM host gate; no live MinIO | Exact Core user secret, direct bucket-only policy and empty group memberships at start/restart, Core journal/object/signing-key backup and isolated restore |
| Worker recovery and authority | Synthetic lease/recovery tests; activation code reviewed | Live restart/stale-fence drill, activation expiry blocking new work with old result retrievable, logs and support procedure |
| Terra and two-cycle acceptance | Customer request packet only | Approved `t0,t1,t2` DSM/report/boundary/CRS/height/rights/checkpoint evidence; two actual analyses, UI/API/Codex parity and named customer acceptance |

The `docs/ops/RELEASE_EVIDENCE.md` generator requires a clean commit plus real image/SBOM/scanner artifacts. No such envelope, remote CI, host binding, backup/restore result, field result, or customer sign-off was generated here. Commit, deployment, host configuration and credential installation each need action-specific authorization after the candidate and evidence are reviewable.

## Local integrated validation at the current candidate source

Snapshot: `.opencode/artifacts/first-product-completion-20260929/fpo-local-full-validation-source.json` records HEAD, full Git status hash and 11 relevant file hashes. On main, `uv run pytest -q` completed with **7,131 passed, 121 skipped, 45 warnings** (exit 0). Dashboard `npm test -- --reporter=dot` completed with **946 passed across 124 files**; `npm run build` passed; weekly three-epoch Playwright completed **1 passed**. FPO-03 deployment/service candidate tests passed **30**; changed Python passed Ruff and three FPO source files passed mypy. These checks use synthetic fixtures and local environment. No remote CI or host/field verification was run.
