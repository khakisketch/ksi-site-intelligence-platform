# External product loop — local synthetic run (2026-09-16)

## Scope and authority

This audit transcribes the local synthetic external product-loop run whose source of
truth is `EVIDENCE.md` at run root `/home/ksi/.local/state/ksi-external-loop/`
(130 lines, read 2026-09-16). It records evidence for the `external-customer-ingress`
workstream owned by
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

**Scope statement — this is local software evidence only.** It is NOT
staging/deployment evidence, NOT customer export-compatibility evidence, and NOT
HIL/field acceptance. Unverified boundaries from the run itself: NodeODM was never
started (no stage needed it); review/proposal semantics beyond the recorded receipts;
revocation paths (untested by design here).

## Status: LOCAL PASS 8/8

Stage chain: register -> upload/seal -> inspection -> evidence -> use decision ->
relative volume -> review -> successor WorkOrder. Zero failed stages, zero non-2xx
steps in `artifacts/transcript.jsonl` (61 lines: 38× HTTP 200, 14× HTTP 201,
9× stage `pass` markers).

| # | Stage | Key operations | Result |
|---|-------|----------------|--------|
| 1 | register | Site + work-area + 2 observation WorkOrders + 2 reconstruction contexts + 2 external-reconstruction submissions | PASS — `obs-work-00000001/02`, refs `ers-v1-6640…`/`c229…` |
| 2 | upload/seal | 2 upload grants, 4 MinIO presigned-URL PUTs, 2 seals | PASS — manifests `sha256:3aff…`/`7938…` |
| 3 | inspection | Snapshot seq2 (`ADMIT_POLICY`) + reload; 2× pending/lease/input/report over the worker lane | PASS — reports `sha256:42c1…`/`4823…` |
| 4 | evidence | 2× declare/grant/PUT/seal; snapshot seq3 (contexts) + reload | PASS — refs `eev-v1-…`; validations NOT auto-issued (see lesson 6) |
| 4b | restart + measure | Core restart (startup reconcile issues validations); 2× pending/lease/input/measurement | PASS — records `sha256:f03f…`/`ab3f…` |
| 5 | use decision | Pair use-decision (`RELATIVE_VOLUME`, zone area) | PASS — `external-use-decision-e36b…`, verdict `ELIGIBLE` |
| 6a | mapping admit | Snapshot seq4 (`ADMIT_MAPPING`) + reload, digest matched | PASS — mapping `sha256:241b…`-class |
| 6b | relative volume | Request + lease (volume-worker bearer) + input + report | PASS — `external-relative-volume-report-8262…` |
| 7 | review | Review of the relative-volume report | PASS — `err-v1-4315…` |
| 8 | successor | Re-observation proposal + operator-a approval + successor WorkOrder fetch | PASS — `erop-v1-8993…`, successor `obs-work-external-c290…` (`EXTERNAL_RECONSTRUCTION`) |

## Readiness (raw)

```text
GET /ready -> {"ready":true} (HTTP 200)
GET /ready/external-authority -> {"status":"PROVIDER_CONFIGURED"} (HTTP 200)
```

Services: MinIO (`external-loop-minio2`, local dummy credentials only — no real or
reusable secrets) + Core production factory
(`ksi_core.production:build_production_app --factory`, port 8000) + processing
worker. No NodeODM was required: inspection/evidence/volume lane steps were driven
explicitly over the worker HTTP surface by the driver.

## Journals (`data/`, append-only; `.lock` files omitted)

Line counts verified by `wc -l` on 2026-09-16:

```text
external-artifact-inspections.jsonl            6
external-authority-provider-receipts.jsonl     4  (seq1->seq4 chained)
external-evidence-validations.jsonl            6
external-evidence.jsonl                        6
external-reconstruction.jsonl                  4
external-relative-volumes.jsonl                3  (issued + leased + reported)
external-reobservation-proposals.jsonl         1  (external-reobservation-proposed)
external-result-reviews.jsonl                  1  (external-result-reviewed)
external-use-decisions.jsonl                   2  (requested + recorded)
external-validation-policy.jsonl               1
observation-work-orders.jsonl                  3  (2 created + approved-and-next-order-created, incl. successor)
quantitative-authority.jsonl                   2  (mapping-activated + execution-activated)
sites.jsonl                                    1
work-areas.jsonl                               1
```

Per-step dumps retained in `artifacts/`: `seal-*.json`, `inspection-input-*.json`,
`evval-*.json`, `volume-input.json`, `proposal-approve.json`, `loop-state.json`;
full logs in `logs/core.log`, `logs/worker.log`.

## Protected-root requirement

Ancestors verified before start (re-checked 2026-09-16 via `stat`): `/` 0755,
`/home` 0755, `/home/ksi` 0750, `/home/ksi/.local` 0700,
`/home/ksi/.local/state` 0700 — none group/other-writable, i.e.
group/other-writable ancestors are rejected. Run root itself 0700; run-root
config files 0600.

## Operational lessons (all blockers were driver bugs, verified against Core code/tests)

1. URLs must use the registered `submissionRef` (`ers-v1-…`), not `submission_id`
   (404 `EXTERNAL_RECONSTRUCTION_NOT_FOUND` otherwise).
2. `SealedExternalSubjectV1` has no `.sealed()` (already sealed by construction).
3. Lease fence IDs must be canonical UUIDv4.
4. Manifest `kind` is lowercase on the wire (`ortho`/`dsm`); raster-measurement
   compatibility rejects mismatched MEASURED facts (`REPORT_BINDING_REJECTED`).
5. Pending-list order is arbitrary — match each leased request to its label via
   input `request.subject.workOrderId`.
6. Evidence validations do NOT auto-issue at seal until policy+context exist;
   designed recovery is restart → startup reconcile. Manifest digests are
   journal-only, so the driver reads them from `data/external-evidence.jsonl`.
7. Order matters: mapping must be admitted BEFORE the use decision (a pre-mapping
   decision is immutably BLOCKED; pair decisions dedupe).
8. Frozen clock across restarts: snapshot action rule `effective_at >= issued_at`
   means phase B must reuse phase-A `NOW` for all snapshot/action/validity times
   (persisted in `loop-state.json`); otherwise the provider goes BLOCKED.
9. Volume worker lane bearer: lease/input/report must use the `volume-worker`
   `PROCESSING_WORKER` bearer, not the generic `worker-1` token
   (`principal_id ∈ authorized_actor_ids`).
10. Volume requests expire (`deadline_after_issue` 60 s) and dedupe by decision —
    lease→report must complete within the deadline in one run.
11. Volume report `zone_snapshot_digest` must be the zone snapshot's
    `canonical_digest()`, not the wire `definitionDigest` (verified unequal locally).
12. Never combine `pkill` with a launch in one command — combined commands hang;
    stop each process in its own command with a bracket-trick pattern.

## Restart commands (local-only summary; journals replay, snapshot file persists)

> Fencing: the snippet below is local-only reproduction aid. The image is unpinned
> (`minio/minio:latest`) and credentials are placeholders — never promote this
> snippet to staging assets. Staging images must be exact version + OCI digest
> pinned per INV-054, and staging credentials must never be literals in the repo.

```sh
pkill -f "[s]tart_core[.]py"
pkill -f "[s]tart_worker[.]py"
docker stop -t 10 external-loop-minio2 && docker rm external-loop-minio2
```

```sh
docker run -d --name external-loop-minio2 -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
  -e MINIO_ROOT_USER=<local-dummy-user> -e MINIO_ROOT_PASSWORD=<local-dummy-password> \
  -v external-loop-minio2:/data minio/minio:latest server /data --console-address ":9001"
uv run --project services/core python /home/ksi/.local/state/ksi-external-loop/start_core.py  # (workdir: repo)
uv run --project services/processing-controller python /home/ksi/.local/state/ksi-external-loop/start_worker.py
curl http://127.0.0.1:8000/ready  # -> {"ready":true}
```
