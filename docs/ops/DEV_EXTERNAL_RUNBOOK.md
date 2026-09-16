# DEV external product-loop runbook — ADR-KSI-036 ingress (Core · storage · Console wiring)

Status: verification-only runbook. No product code changed; no credentials included
(env names only, no values). Deviations from code are resolved in favor of code.
External-loop authority is ADR-KSI-036
(`docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`);
activation state is owned by
`docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`
(SOFTWARE_PREPARED / ACTIVATION_BLOCKED); the implementation sequence is owned by
`docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
(slices 1–2 + quantitative V1 follow-on
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`).

Required implementation plan (AGENTS.md):

```text
Requirement IDs: ADR-KSI-036 external product-loop runbook reconciliation
  (REQ-INT-101/102/103/104, REQ-SEC-101, REQ-OPS-102); no PRD requirement change
Owner module: docs/ops (runbook only; Core/dashboard are read-only evidence)
Acceptance criteria: runbook traces register -> inspect -> decision -> volume ->
  review -> successor WorkOrder with file-line pointers read from code, cites the
  staging acceptance + release plan, marks pre-ADR-036 managed-pipeline sections
  historical, and links no secret values
Contracts affected: none (no contract/schema change)
Reference assets: none imported (reference repos not used)
Adoption decisions: none (no reference code adopted)
Files to change: docs/ops/DEV_EXTERNAL_RUNBOOK.md (this file only)
Tests: none (docs-only); targeted verification is read-back + path-existence + no-secret check
HIL or real-device assumptions: none exercised; synthetic product loop is NOT_RUN and
  customer/HIL/field acceptance is NOT_VERIFIED per the staging acceptance
License/data implications: none (no code/dependency/data change)
Rollback: revert this file (no runtime effect)
```

Invariants touched: none directly (docs-only). Described enforcement points are
INV-051 (external imports never gain managed source authority), INV-053
(quantitative comparison only on the admitted rule; typed blockers otherwise),
and INV-060 (organization isolation; wrong-tenant resources indistinguishable
from absent); enforcement stays in the cited code.

Pointer convention: each pointer cites the `@router.*` decorator line; the
handler `def` follows below it. Core route prefixes are literal in code
(`external_reconstruction.py:936`, `external_use_evaluator.py:1082`,
`external_reobservation_proposals.py:997-999`).

## 1. External product loop — register → inspect → decision → volume → review → successor WorkOrder

First-release boundary (ADR-KSI-036 D1/D4): the customer runs reconstruction on
equipment the customer owns or controls; KSI registers submitted facts, verifies
evidence/provenance, and analyzes only eligible results. Original photos stay on
customer equipment. Registration ≠ verification ≠ quantitative eligibility.

| Stage | Actual route | Code pointer |
|---|---|---|
| register (context) | `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-context` | `services/core/src/ksi_core/external_reconstruction.py:941` |
| register (declare) | `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions` (revision 1; returns opaque `submissionRef`) | `services/core/src/ksi_core/external_reconstruction.py:973` (router prefix `/v1/observation-work-orders` at `:936`, base at `:939`) |
| register (list) | `GET` same base | `services/core/src/ksi_core/external_reconstruction.py:1034` |
| register (revision detail) | `GET .../external-reconstruction-submissions/{submission_ref}/revisions/{revision}` (consume the returned `submissionRef`; never construct from the raw customer `submissionId`) | `services/core/src/ksi_core/external_reconstruction.py:1049` |
| register (byte slots) | `POST .../revisions/{revision}/upload-grants` (browser/worker PUTs bytes to granted `uploadUrl` preserving `requiredHeaders`; the storage PUT is not a Core route) | `services/core/src/ksi_core/external_reconstruction.py:1079` |
| register (seal) | `POST .../revisions/{revision}/seal` (REGISTERED→SEALED; sealed revisions immutable, corrections are new revisions) | `services/core/src/ksi_core/external_reconstruction.py:1123` |
| inspect (public view) | `GET .../revisions/{revision}/inspection` (`INSPECTION_PENDING_SEAL` until sealed) | `services/core/src/ksi_core/external_artifact_inspections.py:2234` (public base at `:2201`) |
| inspect (evidence declare) | `POST .../revisions/{revision}/evidence` (`Idempotency-Key` required) | `services/core/src/ksi_core/external_evidence.py:1078` (base at `:1012`) |
| inspect (evidence list) | `GET .../revisions/{revision}/evidence` | `services/core/src/ksi_core/external_evidence.py:1120` |
| inspect (evidence bytes) | `POST .../evidence/{evidence_ref}/upload-grant`, then `POST .../evidence/{evidence_ref}/seal` | `services/core/src/ksi_core/external_evidence.py:1136`, `:1165` |
| decision (single use) | `POST .../revisions/{revision}/use-decisions/single` (`DISPLAY`/`HEIGHT`; human `OPERATOR` only) | `services/core/src/ksi_core/external_use_evaluator.py:1145` (base at `:1087`) |
| decision (pair use) | `POST .../revisions/{revision}/use-decisions/pair` (`VISUAL_COMPARISON`/`RELATIVE_VOLUME` with baseline refs) | `services/core/src/ksi_core/external_use_evaluator.py:1184` |
| volume (issue) | `POST /v1/observation-work-orders/{work_order_id}/relative-volume-requests` (`Idempotency-Key`; human `OPERATOR` only) | `services/core/src/ksi_core/external_relative_volumes.py:2424` |
| volume (site history) | `GET /v1/sites/{site_id}/external-relative-volume-reports` | `services/core/src/ksi_core/external_result_workflow_api.py:401` |
| volume (site view) | `GET /v1/sites/{site_id}/observations/{report_ref}` | `services/core/src/ksi_core/external_result_workflow_api.py:423` |
| volume (report) | `GET /v1/external-relative-volume-reports/{report_ref}` | `services/core/src/ksi_core/external_result_workflow_api.py:441` |
| review (record) | `POST /v1/external-relative-volume-reports/{report_ref}/reviews` (human `OPERATOR` only) | `services/core/src/ksi_core/external_result_workflow_api.py:473` |
| review (read) | `GET /v1/external-result-reviews/{review_ref}` | `services/core/src/ksi_core/external_result_workflow_api.py:533` |
| successor (propose) | `POST /v1/external-reobservation-proposals` (`Idempotency-Key`) | `services/core/src/ksi_core/external_reobservation_proposals.py:1001` (router prefix at `:997`) |
| successor (approve → next order) | `POST /v1/external-reobservation-proposals/approve`; approval emits `external-reobservation-approved-and-next-order-created` and a planning-only successor binding (`acquisitionRunAllowed=false`, `missionIssuanceAllowed=false`) | `services/core/src/ksi_core/external_reobservation_proposals.py:1034`; `services/core/src/ksi_core/observation_work_orders.py:1750` |
| successor (read) | `GET /v1/external-reobservation-proposals/{proposal_ref}` | `services/core/src/ksi_core/external_result_workflow_api.py:542` |

Quantitative eligibility (ADR-KSI-036 D5) is the narrow external relative-volume
V1 rule only: same immutable `external-geotiff-profile.v1` grammar digest and
parser/inspector build, same observed CRS/vertical digests, ordered
non-overlapping capture, independently measured Core-validated checkpoint
evidence per epoch, exact WorkArea match, digest-bound policies — full rule in
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`.
Anything else is a typed blocker, never a default-eligible comparison.

## 2. Console upload flow — BFF routes and Core clients (browser never calls Core directly)

- Upload BFF: `apps/dashboard/src/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/route.ts`
  (register; builds the `external-reconstruction-submission.v1` candidate via
  `apps/dashboard/src/lib/external-reconstruction-submission.ts`).
- Revision BFF routes (seal, inspection, upload-grants, evidence + evidence
  seal/upload-grant, use-decisions single/pair/[decisionId], sanitized display
  download): `apps/dashboard/src/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/`
  (`inspection/route.ts`, `seal/route.ts`, `upload-grants/route.ts`,
  `evidence/route.ts`, `evidence/[evidenceRef]/seal/route.ts`,
  `evidence/[evidenceRef]/upload-grant/route.ts`,
  `use-decisions/single/route.ts`, `use-decisions/pair/route.ts`,
  `use-decisions/[decisionId]/route.ts`,
  `display-artifacts/[sanitizedDisplayRef]/download/route.ts`).
- Server-only Core clients: `apps/dashboard/src/lib/core-api/external-reconstruction.ts:68-114`
  (base + register/grants/seal/inspection/display download),
  `:212-238` (evidence declare/grant/seal + single/pair use-decision intents),
  `:240-242` (reconstruction context); work-order execution-context resolution at
  `:156-191` (`EXTERNAL_INGRESS` vs `EXTERNAL_REOBSERVATION_PLANNING` vs `UNVERIFIED`).
- Report/review/proposal clients: `apps/dashboard/src/lib/core-api/external-result-workflow.ts:240-265`
  (volume issue/list/get), `:267-283` (report/review get + review record),
  `:285-312` (proposal create/get/approve), `:325-333` (site report history).
- Field status projection: `apps/dashboard/src/app/field/external-reconstruction-status.ts`
  (inspection-view types from `lib/core-api/external-reconstruction.ts`).
- Report/proposal BFF routes: `apps/dashboard/src/app/api/external-relative-volume-reports/[reportRef]/route.ts`,
  `.../[reportRef]/reviews/route.ts`,
  `apps/dashboard/src/app/api/external-reobservation-proposals/route.ts`,
  `apps/dashboard/src/app/api/sites/[siteId]/external-relative-volume-reports/route.ts`,
  `apps/dashboard/src/app/api/sites/[siteId]/observations/[reportRef]/route.ts`,
  `apps/dashboard/src/app/api/observation-work-orders/[workOrderId]/relative-volume-requests/[requestRef]/route.ts`.
- Browser check for the upload flow: register → granted PUT(s) → seal → poll
  `.../inspection` until a terminal inspection/display state → evidence
  declare/grant/seal → use-decision → volume issue → report → review →
  proposal/approve → successor WorkOrder binding. The full browser pass is
  NOT_RUN (synthetic product loop `NOT_RUN` per the staging acceptance); record
  per-stage terminal states by hand (see the checklist run record).

## 3. Storage and dev startup (still current; external loop rides the same wiring)

- Sole real implementation of the `EvidenceStorage` port is
  `S3EvidenceStorage` — `services/core/src/ksi_core/evidence_s3.py:34`.
- Core assembles it only from env names (values live in `deploy/.env`, never
  committed): `KSI_CORE_S3_ENDPOINT`, `KSI_CORE_S3_PUBLIC_ENDPOINT` (browser/field
  public endpoint; falls back to the internal endpoint),
  `KSI_CORE_S3_BUCKET` — required in
  `services/core/src/ksi_core/production.py:612-614`; object credentials ride
  the boto3 default chain (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or a
  cloud IAM role) — `production.py:675-683`, `deploy/.env.example:67-70`.
- Without `KSI_CORE_S3_ENDPOINT`/`KSI_CORE_S3_BUCKET`, production Core refuses
  to start (fail-closed) — missing values raise in `_require_env` at
  `production.py:612-614`.
- Byte-flow rule (ADR-KSI-010 §1): Core never relays bytes — it mints
  presigned PUT/GET URLs (here: `upload-grants`, evidence `upload-grant`,
  display download) and the browser/worker talks to storage directly.
- Local compose default: MinIO service (`minio/minio`, pins digest) with
  `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` from `.env`
  (`deploy/compose.yaml:113-132`, `deploy/.env.example:28-35`).
- Dev startup/stop/rerun (compose.yaml, no secrets): full procedure stays in
  `docs/ops/DEPLOYMENT.md` §§2–3; sequence:

```bash
cd deploy
cp .env.example .env                # then fill per DEPLOYMENT.md §§2-4 (never commit .env)
cp device-attestation-keys.example.json device-attestation-keys.json
docker compose up -d --build        # init-volumes fixes uid 10001/10002 ownership first
curl -fsS http://127.0.0.1:8000/ready && echo   # /ready, NOT /health
```

```bash
cd deploy
docker compose ps                   # confirm core/worker/minio/nodeodm state
docker compose logs core worker     # targeted logs (cite, don't dump)
docker compose down                 # stop; named volumes persist
docker compose up -d                # rerun (no --build unless images changed)
docker compose up -d --build        # rerun after code change
```

- `docker compose down -v` is DESTRUCTIVE (deletes journal/object volumes).
- Dashboard is NOT in `deploy/compose.yaml` (separate Next.js deployment);
  browser linkage in dev requires `apps/dashboard` `npm run dev` alongside
  compose (DEPLOYMENT.md header note).
- Activation blockers (staging acceptance): UDS ACL activation
  (`BLOCKED_ACL_ACTIVATION`), runtime provenance / release evidence
  (`BLOCKED_RELEASE_EVIDENCE`), quantitative authority source
  (`BLOCKED_AUTHORITY_SOURCE`); host identities `NOT_APPLIED`. Do not present a
  local dev run as activation evidence.

## Appendix H. Pre-ADR-036 managed pipeline (HISTORICAL — not the first-release route)

The KSI-managed reconstruction pipeline below (`source-media` /
`processing-jobs` / NodeODM worker) remains implemented for test/demonstration
scope only (ADR-KSI-036 D1; `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md` §2).
It must not be relabeled as customer-operated results and it is not the
first-release route. Pointers are retained so operators can still run the
managed test path; deviations from code are resolved in favor of code.

- Managed submission: `POST /v1/missions/{mission_id}/source-media`,
  `.../source-media/ground-control`, `.../source-media/seal`,
  `POST /v1/missions/{mission_id}/processing-jobs`
  (`services/core/src/ksi_core/source_media.py`, `processing_jobs.py`).
- Managed worker pull loop: `services/processing-controller/src/ksi_processing_controller/runner.py`
  (`run_pending_batch`, `run_forever`); claim-execute-report via
  `core_client.py` → `worker.py:334-580`; failures attempt a `FAILED`
  transition (`worker.py:581-596`).
- Deprecated/unfenced surface (must NOT be used):
  `POST /v1/missions/{mission_id}/source-media/verify` always returns 409
  `LEASE_FENCE_REQUIRED` (`source_media.py:1852`).
- Line-number detail for the managed routes no longer tracked here — the
  pre-reconciliation revision of this runbook carried them and the code files
  above are authoritative.
