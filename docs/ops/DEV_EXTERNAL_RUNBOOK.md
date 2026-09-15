# DEV external execution runbook — Core · storage · worker wiring

Status: verification-only runbook. No product code changed; no credentials included
(env names only, no values). Deviations from code are resolved in favor of code:
Core wiring is `services/core/src/ksi_core/production.py`, worker wiring is
`services/processing-controller/src/ksi_processing_controller/runner.py`.

Required implementation plan (AGENTS.md):

```text
Requirement IDs: dev external execution wiring verification (no PRD requirement change)
Owner module: docs/ops (runbook only; Core/worker/dashboard are read-only evidence)
Acceptance criteria: runbook names Core submission-inspection-measurement-review
  routes with file-line pointers, S3 presigned storage wiring with env names only,
  worker pull loop claim-execute-report with file-line pointers, dev
  startup-stop-rerun steps using compose.yaml without secrets, plus explicit gap
  list for storage-worker-browser linkage
Contracts affected: none (no contract/schema change)
Reference assets: none imported (reference repos not used)
Adoption decisions: none (no reference code adopted)
Files to change: docs/ops/DEV_EXTERNAL_RUNBOOK.md (single new file only)
Tests: none (docs-only); targeted verification is read-back + path-existence + no-secret check
HIL or real-device assumptions: none exercised; NodeODM runs as an unmodified
  upstream container image behind REST (deploy/compose.yaml header, ADR-KSI-012 D2)
License/data implications: none (no code/dependency/data change)
Rollback: delete this file (no runtime effect)
```

Invariants touched: none directly (docs-only). Described enforcement points are
INV-051 (SUCCEEDED requires verified input + registered artifacts — worker.py
steps 4–7) and INV-024 (RTK Fix is not absolute-accuracy proof; absolute RMSE
only with independent checkpoints — `docs/product/DOMAIN_INVARIANTS.md:110`);
enforcement stays in the cited code.

## 1. Core routes — submission → inspection → measurement → review

Term mapping (interpretive — Core modules do not use these four nouns as route
names; each mapping below names the actual route and file-line pointer).
Pointer convention: each pointer cites the `@router.*` decorator line; the
handler `def` follows 1–5 lines below it.

| Stage | Actual route | Code pointer |
|---|---|---|
| submission (source bytes declared) | `POST /v1/missions/{mission_id}/source-media` (register batch) | `services/core/src/ksi_core/source_media.py:1725` (router prefix `/v1/missions` at `source_media.py:1690`) |
| submission (ground control) | `POST /v1/missions/{mission_id}/source-media/ground-control` | `services/core/src/ksi_core/source_media.py:1764` |
| submission (seal bundle) | `POST /v1/missions/{mission_id}/source-media/seal` | `services/core/src/ksi_core/source_media.py:1825` |
| submission (issue work) | `POST /v1/missions/{mission_id}/processing-jobs` | `services/core/src/ksi_core/processing_jobs.py:3127` |
| inspection (worker-only input pull) | `GET /v1/processing-jobs/{job_id}/input` (spec + presigned download URLs; `PROCESSING_WORK` only, no `MISSIONS_READ`) | `services/core/src/ksi_core/processing_jobs.py:3388` |
| inspection (human read views) | `GET /v1/missions/{mission_id}/processing-jobs`, `GET /v1/sites/{site_id}/processing-jobs`, `GET /v1/processing-jobs/{job_id}` | `services/core/src/ksi_core/processing_jobs.py:3221`, `:3241`, `:3266` |
| inspection (worker pending list) | `GET /v1/processing-jobs` (QUEUED + lease-expired RUNNING, FIFO; worker-only) | `services/core/src/ksi_core/processing_jobs.py:3196` |
| measurement (worker reports measured values) | `POST /v1/processing-jobs/{job_id}/verify-input` (fenced; `VERIFIED`/`ALREADY_VERIFIED` only) | `services/core/src/ksi_core/processing_jobs.py:3471` |
| measurement (artifact byte slot) | `POST /v1/processing-jobs/{job_id}/artifacts/upload-url` (digest-bound presigned PUT) | `services/core/src/ksi_core/processing_jobs.py:3525` |
| measurement (artifact lineage record) | `POST /v1/processing-jobs/{job_id}/artifacts` | `services/core/src/ksi_core/processing_jobs.py:3691` |
| review (state transitions) | `POST /v1/processing-jobs/{job_id}/transitions` (per-target permission; lease fence required except human CANCELLED) | `services/core/src/ksi_core/processing_jobs.py:3277` |
| review (read registered bytes) | `GET /v1/processing-jobs/{job_id}/artifacts/{artifact_id}/download` (registered artifacts only, `MISSIONS_READ`) | `services/core/src/ksi_core/processing_jobs.py:3601` |
| review (lease gate) | `POST /v1/processing-jobs/{job_id}/lease` (CLAIM/RENEW; all gated mutations require the fence) | `services/core/src/ksi_core/processing_jobs.py:3343` |

Deprecated/unfenced surface (must NOT be used by the worker):
`POST /v1/missions/{mission_id}/source-media/verify` always returns 409
`LEASE_FENCE_REQUIRED` — `services/core/src/ksi_core/source_media.py:1852`.

## 2. S3 presigned storage wiring (env names only, no values)

- Sole real implementation of the `EvidenceStorage` port is
  `S3EvidenceStorage` — `services/core/src/ksi_core/evidence_s3.py:33`.
- Core assembles it only from env names (values live in `deploy/.env`, never
  committed): `KSI_CORE_S3_ENDPOINT`, `KSI_CORE_S3_PUBLIC_ENDPOINT` (browser/field
  public endpoint; falls back to the internal endpoint),
  `KSI_CORE_S3_BUCKET` — required in
  `services/core/src/ksi_core/production.py:585-587`; object credentials ride
  the boto3 default chain (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or a
  cloud IAM role) — `production.py:629-637`, `deploy/.env.example:61-64`.
- Without `KSI_CORE_S3_ENDPOINT`/`KSI_CORE_S3_BUCKET`, production Core refuses
  to start (fail-closed) — `production.py:32-38`.
- Without storage, dev Core still assembles but evidence/3D-pipeline surfaces
  are not mounted — storage-absent gate is
  `services/core/src/ksi_core/app_assembly.py:180,223`
  (`evidence_storage is not None`, else the stores stay unmounted).
- Byte-flow rule (ADR-KSI-010 §1): Core never relays bytes — it mints
  presigned PUT/GET URLs and the browser/worker talks to storage directly.
  Uploads sign `Content-Type` into the SigV4 signature (`evidence_s3.py:120`);
  worker artifact slots additionally bind `ChecksumSHA256`
  (`evidence_s3.py:129-162`); worker artifact PUT must set explicit
  `Content-Length` (no chunked encoding — `worker.py:250-271`).
- Local compose default: MinIO service (`minio/minio`, pins digest) with
  `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` from `.env`; cloud S3 = remove the
  minio service and point `KSI_CORE_S3_ENDPOINT` at it —
  `deploy/compose.yaml:113-132`, `deploy/.env.example:28-35`.

## 3. Worker pull loop — claim → execute → report

- There is NO Core-side pull surface pushed to the worker: the loop lives in
  `services/processing-controller/src/ksi_processing_controller/runner.py:1-63`
  (`run_pending_batch`, `run_forever`).
- Claim: `GET /v1/processing-jobs` → `POST .../lease` (CLAIM; RENEW =
  heartbeat) via `HttpCoreClient` —
  `services/processing-controller/src/ksi_processing_controller/core_client.py:901-964`.
- Execute: `run_job` order is fixed — lease → `GET .../input` → QUEUED→RUNNING
  → download+measure+`verify-input` → engine-identity check + NodeODM
  submit/poll (heartbeat renews the 15-min lease) → presign+PUT+register
  artifacts in order → SUCCEEDED —
  `services/processing-controller/src/ksi_processing_controller/worker.py:334-580`.
- Report: every failure path (steps 4–6, ANY `Exception`) attempts a `FAILED`
  transition and re-raises as `WorkerRunError` — `worker.py:581-596`.
- One process runs one job at a time; concurrency = more processes (lease
  arbitrates) — `worker.py:48-60`, `runner.py:25-29`.
- Poll priority per round (one item max): reconstruction → design-surface
  verification → checkpoint validation → two-epoch comparison → design
  conformance → region extraction — `runner.py:189-241`.
- Worker env names only: `KSI_WORKER_CORE_BASE_URL`, `KSI_WORKER_CORE_TOKEN`
  (raw token whose digest is registered as `PROCESSING_WORKER` in
  `KSI_CORE_PRINCIPAL_TOKENS_JSON`), `KSI_WORKER_NODEODM_BASE_URL`,
  `KSI_WORKER_WORK_DIR`, optional `KSI_WORKER_POLL_INTERVAL_SECONDS`,
  `KSI_WORKER_HEARTBEAT_INTERVAL_SECONDS`, `KSI_WORKER_LOG_LEVEL`,
  `KSI_WORKER_LOG_FORMAT`, optional `KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR`
  (default OFF; set-but-unloadable = worker refuses to start) —
  `runner.py:418-544`, `deploy/.env.example:153-187`.
- SIGTERM/SIGINT stops only at the next poll boundary (in-flight job is not
  cut); dead-worker jobs are reclaimed via lease expiry + `list_pending`
  returning expired `RUNNING` — `runner.py:40-62`.

## 4. Dev startup → stop → rerun (compose.yaml, no secrets)

Prerequisites (values in `deploy/.env`, created from `deploy/.env.example`;
signing keys in `deploy/signing-keys/`; full procedure in
`docs/ops/DEPLOYMENT.md` §§2–3 — this runbook only sequences the commands):

```bash
cd deploy
cp .env.example .env                # then fill per DEPLOYMENT.md §§2-4 (never commit .env)
cp device-attestation-keys.example.json device-attestation-keys.json
docker compose up -d --build        # init-volumes fixes uid 10001/10002 ownership first
curl -fsS http://127.0.0.1:8000/ready && echo   # /ready, NOT /health (§6)
```

Stop / rerun:

```bash
cd deploy
docker compose ps                   # confirm core/worker/minio/nodeodm state
docker compose logs core worker     # targeted logs (cite, don't dump)
docker compose down                 # stop; named volumes (ksi-data, ksi-objects,
                                    # ksi-worker-work, ksi-odm) persist
docker compose up -d                # rerun (no --build unless images changed)
docker compose up -d --build        # rerun after code change
```

Notes:

- Healthcheck and readiness use `/ready` (sealed journals report 503 there;
  `/health` only proves liveness) — `deploy/compose.yaml:82-91`.
- Core binds `127.0.0.1:8000` only, plain HTTP — never expose to the public
  internet as-is (TLS/reverse-proxy is environment-owned, not in this file) —
  `deploy/compose.yaml:14-18,75-76`.
- `docker compose down -v` is DESTRUCTIVE (deletes journal/object volumes) —
  do not run unless ledger loss is intended; backup targets are the `ksi-data`
  volume + host dir `deploy/signing-keys/` — `DEPLOYMENT.md §8`.
- Local alternative (not compose): `scripts/run_core_dev.py` boots a dev Core
  with fixed dev tokens for dashboard (`npm run dev`) development —
  `scripts/run_core_dev.py:1-12,41-53`. Production/compose never imports it
  (`production.py:3-8`).

## 5. Gap list — storage ↔ worker ↔ browser linkage

1. No new-code gap found in the claim-execute-report chain for reconstruction
   jobs (pending-list → lease → input → verify → upload-url → artifacts →
   transitions all wired and read back above). Gaps below are linkage/UX
   observations, not wiring breaks.
2. Non-reconstruction queues share the same single-process loop; a long ODM
   run head-of-line-blocks design-surface/comparison/conformance/region work
   for that worker (priority order only applies between rounds —
   `runner.py:207-236`). Mitigation is more worker processes, not code verified here.
3. Browser presigned URLs are minute-TTL (`DEFAULT_VIEW_TTL`, 5 min —
   defined at `services/core/src/ksi_core/evidence.py:33`; upload TTL at
   `:32`): viewers re-fetch on mount
   (`OrthophotoOverlay`, `DiffHeatmapOverlayInner`); screens must treat a
   missing/null `downloadUrl` as empty state, not retry-blindly (dashboard
   `phase34.ts:85` comment). No runbook step can extend TTL — it is code-set
   (`DEFAULT_VIEW_TTL`).
4. Retried jobs against an already-verified bundle return `ALREADY_VERIFIED`
   (success, not error — `core_client.py:1016-1045`); operators seeing
   `ALREADY_VERIFIED` after a failure-retry should NOT treat it as a failure.
5. Partial-success retry re-registers from scratch; already-registered
   artifacts can return `DUPLICATE_ARTIFACT` → `FAILED` on the retry
   (`runner.py:53-62`). Resuming (skipping registered artifacts) is explicitly
   out of scope there — human triage signal, not silent recovery.
6. `KSI_CORE_S3_PUBLIC_ENDPOINT` must be browser-reachable (localhost for dev
   compose, `objects.<domain>` behind Caddy on external VMs). If browsers
   receive the internal Docker-DNS name (`minio`), presigned URLs resolve
   nowhere — check this env name first (`deploy/.env.example:31-34`).
7. Dashboard is NOT in `deploy/compose.yaml` (separate Next.js deployment;
   external-VM profile is additive `compose.vm.yaml` + Caddy per
   `docs/ops/VM_DEPLOYMENT_READINESS.md`) — `compose.yaml:17-18`. Browser
   linkage in dev therefore requires `apps/dashboard` `npm run dev` alongside
   compose (DEPLOYMENT.md header note).
8. DJI Gateway is NOT in the default compose set (no PSDK/MOP device evidence;
   capabilities stay `NOT_VERIFIED`) — `compose.yaml:19-23`. Any device-linked
   step is out of scope for this runbook — escalate if required.
