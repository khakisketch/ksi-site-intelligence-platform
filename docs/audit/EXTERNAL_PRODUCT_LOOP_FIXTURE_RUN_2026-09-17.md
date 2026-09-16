# External product loop — local real-fixture rehearsal (2026-09-17)

## Scope and authority

This audit faithfully transcribes the local real-fixture rehearsal evidence whose
source of truth is `.dev-data/a2-fix/EVIDENCE.md` (126 lines, read 2026-09-17),
except for the rehearsal observations listed in
`### Rehearsal observations (not in EVIDENCE.md)` below.
Recipe: `.dev-data/a2-fix/RECIPE.md` (note: file is truncated at §4, line 300 —
call-sequence tail + blocker list incl. B5 are missing in-file; lane
placement/sequence were re-derived from A2 evidence + Core sources and recorded
in the evidence file). Prior state: `.dev-data/a2/EVIDENCE.md` (synthetic bytes
honestly REJECTED; 4A.5–4A.7 positive paths not executable — E6 fixture
boundary). Generator: `.dev-data/a2-fix/gen_fixtures.py` (RECIPE §3.1 verbatim,
output dir adapted to `fixtures/`).

Rank: below the frozen authorities (`PRODUCT_CONSTITUTION`,
`FINAL_DECISION_LEDGER`, `MASTER_PRD`, `DOMAIN_INVARIANTS`), below ADR-KSI-036
and `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`, and below
the release plan
`docs/superpowers/plans/2026-09-06-external-reconstruction-release.md` and the
quantitative specification
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
(implementation history); this evidence decides nothing.

**Scope statement — this is a LOCAL-ONLY rehearsal against the decomposed
stack with locally generated real GeoTIFF fixtures.** It is NOT
staging/deployment evidence, NOT vendor export-compatibility evidence, NOT
HIL/field acceptance, and NOT a happy-path pass: the RELATIVE_VOLUME pair gate
returned typed BLOCKED and the 4A.5–4A.7 positives were not executable. Every
reachable lane outcome was asserted without inventing facts to force the happy
path.

Run root: protected `~/.local/state/ksi-a2-console/` (prior A2 journals
retained: WO-01/sub-01, WO-02/sub-02, old policies). A2 launch scripts reused
unchanged. Machine-local raw artifacts (data, worker-work, logs, identity,
operator, screenshots, run-state, drivers) remain under `.dev-data/a2-fix/`;
this audit is the durable record, not the raw bytes.

## Honesty labels (from EVIDENCE §0, authoritative for this pass)

- DSM/ortho rasters are locally generated constant planes (baseline 10.0 m,
  current 10.5 m, ortho flat 17 DN), valid GeoTIFF structure + real CRS
  metadata. They are NOT field data; no accuracy claim is made about them.
- Checkpoint elevations = baseline plane (10.0) + hand-set offsets
  (+0.05/+0.02/−0.02), filed with `independenceBasis` text marking them
  synthetic and `independent_attestation=None` (no independence claim).
- Lane outcomes filed are TRUE computations over the sealed bytes (same
  production decoder functions the container runs, executed locally — recorded
  per stage), verifiable by re-running the pre-flight.
- No accuracy, independence, or field-survey claim is implied anywhere.

## Fixtures + pre-flight (EVIDENCE §0)

Locally generated real GeoTIFFs: 16×16 float32 DSM planes (baseline 10.0 m,
current 10.5 m), 16×16 uint8 RGB ortho (flat 17 DN), EPSG:5186 horizontal +
EPSG:5709 vertical (DSMs; ortho EPSG:5186, no vertical). Pre-flight MEASURED by
the production decoder before any lane was driven.

| File | Bytes | Pre-flight |
|------|-------|------------|
| `fixtures/baseline-dsm.tif` | 408 | MEASURED (EPSG:5186 + vertical EPSG:5709 NAP height) |
| `fixtures/current-dsm.tif` | 408 | MEASURED (EPSG:5186 + vertical EPSG:5709 NAP height) |
| `fixtures/ortho.tif` | 425 | MEASURED (EPSG:5186, no vertical) |
| `fixtures/checkpoints.csv` | 127 | 3 points parse (`p1/p2/p3`) |
| `fixtures/inspector-preflight.json` | — | full TRUE measurement dumps for report construction |

Pre-flight used the processing-controller venv (`rasterio 1.5.1 / numpy 2.5.1 /
pyproj 3.7.2`) with `inspect_synthetic_sealed_geotiff` + `parse_checkpoint_csv`
(RECIPE §3.2, run from `tests/contract` for the `_envelope` helper import).

## Stack (EVIDENCE §1)

| # | Component | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Issuer 9120 | UP | `GET /healthz` → 200 (reused A2 identity dir) |
| 2 | MinIO 9002/9003 | UP | container `a2-minio` restarted; bucket `ksi-a2-console-evidence` retained (NOT fresh — holds A2 objects under distinct keys) |
| 3 | Core 8020 | UP | `GET /ready` → 200 `{"ready":true}`; `/ready/external-authority` → 200 `PROVIDER_CONFIGURED`. Boot repairs: snapshot re-issued seq 4 (validity + receipts chain; stale ADMIT_POLICY actions dropped — boot validates action payloads against live time), catalog + catalog authority refreshed (fresh ±windows, identical body) via seq 4/5 (`reissue_snapshot.py`, `refresh_catalog.py`; catalog digest `sha256:0aaabd…`) |
| 4 | Worker | UP | polling Core lanes HTTP 200 |
| 5 | Dashboard 3320 | UP | `GET /login` → 200 |

## Achieved (EVIDENCE §2)

- Sealed submissions: WO-03 `obs-work-00000003` + `a2f-sub-03`
  (`ers-v1-90b3…`, 201/200/PUTs 200/seal 200); WO-04 `obs-work-00000004` +
  `a2f-sub-04` (`ers-v1-3354…`, same); recovery `a2f-sub-05`
  (`ers-v1-1222…`, manifest `46dfba…`) after sub-04's inspection request was
  terminally exhausted (see incident note); plus sub-07 (08:50–09:50Z, disjoint
  from sub-03 07:34–08:34Z) for the mapping pair.
- Inspection MEASURED ×4 with true computed values: sub-03 REPORTED (TRUE
  2×MEASURED, BFF `INSPECTION_REPORTED/COMPLETE`); sub-05 REPORTED (TRUE
  2×MEASURED). Reports filed with production-decoder values over sha-verified
  downloads.
- Evidence VALIDATED with attestation None (no independence claim):
  `eev-v1-02e3…` (sub-03) + `eev-v1-dd6f…` (sub-05; content-idempotent re-declare
  under sub-05 path) sealed; contexts (attestation None) seq 7 reload 200
  `68335a…`; issuance needed a SECOND reload (historical-retention ordering —
  EVIDENCE B7); measurements filed with TRUE sampled aggregates (n=3,
  mean −0.0167, mae 0.03, rmse 0.0332, max 0.05) → both VALIDATED
  (`record-9660853f…` sub-03, `record-ccb233fb…` sub-05).
- Policy: v3 (pair sub-03/sub-04) seq 5 reload 200; v4 (pair sub-03/sub-05)
  seq 6 reload 200 `9a0f61…`; v6 admitted for the (sub-03, sub-07) pair.
- Mapping admitted: seq 10 content-field verified (exact expected content:
  subjects sub-03/sub-07, zone `wa-…-0002`/EPSG:5186, v6 policy `40d04cb7`, v6
  MEASURED reports `69cbef30`/`593adb97`, v6 VALIDATED evidence
  `a255ad4f`/`a610a199`, catalog `0aaabd64`); seq 11 duplicate (same content
  `f7871d74` vs seq 10 `fa5efa79`); seq 12 revoke experiment (duplicate revoked,
  leaving exactly one). Re-admission (seq 11) + revoke (seq 12) + pair retry did
  not change the pair outcome.

## Blocked gate (EVIDENCE §2–§3 B8)

RELATIVE_VOLUME pair decisions return 201 `BLOCKED /
VOLUME_AUTHORITY_UNAVAILABLE` (`…2c3ad67c`, re-request `…01eb74ce` same;
VISUAL_COMPARISON likewise 201 `BLOCKED / POLICY_UNAVAILABLE` `…c3262186`)
although every externally verifiable leg passes: mapping content-exact, policy
v6 ACTIVE (replayed registry selects v6 ACTIVE for the pair), evidence
resolvable (replayed `record_for_current_use` resolves both v6 evidence
records), validity windows cover (v6 authority/context/catalog/zone/snapshot
windows all cover pair time). The live `resolve_for_use` returns None, so the
failing sub-check inside `resolve_for_use` / `_current_participants` /
`locally_current` is NOT identifiable from outside Core — needs Core-side debug
logging (Build approval).

Consequence: 4A.5 volume NOT EXECUTABLE (issue requires an issuable
RELATIVE_VOLUME decision; 422 `AUTHORITY_UNAVAILABLE` on BLOCKED; history 200
empty); 4A.6 review positive NOT EXECUTABLE (no reportRef; refs are
Core-generated; negative already proven in A2 with viewer 403); 4A.7 proposal
NOT EXECUTABLE (no reportRef). No inputs were fabricated at any point; nothing
further can be driven without ELIGIBLE.

## Latent hazard (rehearsal observation, not triggered)

`ExternalEvidenceValidationStore` replay re-validates old-policy issued events
after policy rotation + restart — potential boot failure on accumulated
rotations (not triggered in this pass) (rehearsal observation; not reproduced — provenance: A2-fix session summary, not EVIDENCE.md). Requires a focused investigation
separate from the pair-gate root cause.

## Operational lessons (EVIDENCE §§1/3/4)

- Never abandon a leased lane item: the 60 s expiry is terminal by design
  (see incident note).
- Snapshot receipts chaining: a reload candidate must extend the Core-retained
  receipt history (`sequence == prior+1`, `previousSnapshotDigest == prior
  digest`); never hand-sequence snapshots — chain from the receipts journal
  (`reissue_snapshot.py`, `refresh_catalog.py` pattern).
- Frozen clock across restarts: boot validates action payloads against live
  time — stale ADMIT_POLICY actions / expired authority/catalog windows fail
  boot (EVIDENCE B1–B4); re-issue snapshots and refresh catalog/authority with
  fresh windows (identical body) before reload.
- OIDC operator token TTL ~5 min: mint a fresh `local-admin` OIDC access token
  before each OPERATOR-gated call; sessions/operator token expire (re-login +
  re-mint).
- Protected-root requirement: production factory external-authority loader
  rejects group-writable ancestors; protected run root
  `~/.local/state/ksi-a2-console/` (0700/0600) is required while worktree
  ancestors at 0775 are permanently rejected — copy material and rewrite
  embedded absolute-path pairs instead of chmodding shared dirs.
- Historical-retention ordering: evidence issuance needs a second same-snapshot
  reload on first-seen contexts (EVIDENCE B7).
- Recipe gap: `.dev-data/a2-fix/RECIPE.md` truncated at §4 line 300; lane
  placement/sequence re-derived from A2 evidence + Core sources.

### Rehearsal observations (not in EVIDENCE.md)

- BFF `INSPECTION_REPORTED/COMPLETE` states (no BFF-state counterpart in EVIDENCE).
- OIDC operator token TTL ~5 min (EVIDENCE notes expiry/re-mint only, no duration).
- Protected-root 0700/0600 requirement and worktree-ancestor 0775 rejection (EVIDENCE notes protected run root only, no mode bits).

## Honest incident note

One abandoned inspection lease (sub-04, via an operator subject-match parse
issue) exhausted `DEADLINE_EXCEEDED` and was terminal by design; it was
recovered with a fresh submission carrying the same bytes (sub-05, then sub-07
for disjoint captures). No measurements were fabricated at any point.

## Evidence location + final state

Raw artifacts are machine-local under `.dev-data/a2-fix/` (fixtures,
run-state.json, drivers `gen_fixtures.py`, `stage1_setup.mjs`,
`stage2_sub05.mjs`, `stage3_evidence.mjs`, `stage4_evidence05.mjs`,
`stage5_zone.mjs`, `stage6_sub07.mjs`, `stage7_pairs.mjs`,
`admit_policy_v3/v4.py`, `admit_policy_v5_seq8.py`, `admit_v6_seq9.py`,
`admit_mapping_seq8.py`, `admit_contexts_seq7.py`, `drive_inspections_real.py`,
`drive_evidence_real.py`, `reissue_snapshot.py`, `refresh_catalog.py`,
`revoke_mapping.py`, logs `logs-{core,worker,issuer,dashboard}.log`,
screenshots `shots-*.png`). This audit is the durable record.

FINAL per EVIDENCE §4: stack STOPPED (all ports verified down). Authority
generation seq 12 (`5756cbcb…`); snapshot `validUntil` ≈ +2 h from seq-12 time
— re-issue via `reissue_snapshot.py` pattern before any new reload;
catalog/policy/context windows ≈ +3 h. Sessions + OIDC operator token expired
(re-login + re-mint). Relaunch order per `.dev-data/a2/EVIDENCE.md` §6
(issuer → MinIO `docker start a2-minio` → Core `start_core.py` → worker
`start_worker.py` → Dashboard dev 3320). Never copy
`.dev-data/a2/operator/*.json` over protected copies.

## Root cause resolved — Core-side reproduction (2026-09-17 follow-up)

Method: the protected run root was copied to an isolated replay root with its
embedded absolute paths rewritten; the production Core factory was assembled
in-process from the retained journals with the clock frozen at the retry time
(`2026-09-16T10:13:24Z`, inside the seq-12 snapshot, catalog, policy v6 and
mapping `f7871d74…` windows). `ExternalUseEvaluator.request_pair` for the
recorded intent (sub-03 → sub-07, zone `wa-…-0002`, `RELATIVE_VOLUME`)
reproduced `BLOCKED / VOLUME_AUTHORITY_UNAVAILABLE` against the isolated copy;
the retained journals and the protected root were not modified.

Finding: `resolve_for_use` was NOT the failing leg. Every mapping participant
check passed and the catalog returned a valid `ExternalRelativeVolumeAuthority`.
The pair request then discarded that authority because
`_pair_evidence_remains_current` was false: the evaluator's
`_validated_evidence_for` accepts a VALIDATED checkpoint record only when its
measurement context carries an `independent_attestation`, and this rehearsal
filed both contexts with `independent_attestation=None` (the honest choice for
locally generated fixtures, EVIDENCE §0). The blocked verdict was therefore
correct under the relative-volume V1 rule ("independently measured,
Core-validated checkpoint evidence per epoch",
`docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`), but
two product defects hid it:

1. `request_pair` nulled the resolved volume authority whenever evidence was
   not current, so `_pair_reason` reported `VOLUME_AUTHORITY_UNAVAILABLE` /
   `AUTHORIZE_VOLUME_ZONE_AND_MAPPING` instead of the evidence blocker
   (EXT-VAL-04 explicit remediation was violated).
2. Mapping admission (`ExternalQuantitativeAuthorityParticipants._evidence_matches_binding`)
   accepted unattested evidence, so seq 10/11 admission succeeded while the
   same evidence could never satisfy a pair decision.

Correction (same day, Core only, no contract schema change; reasons and
remediations are free strings in `external-pair-use-decision.v1.json`):

- `ExternalUseEvaluator` retains the exact evidence blocker resolved through
  the evidence port before the guard and names it ahead of the mapping:
  `EVIDENCE_RECORD_BINDING_INVALID` (no currently validated record binds the
  measured DSM) or the new `EVIDENCE_INDEPENDENCE_UNATTESTED` (a validated
  record exists but its context has no independence attestation), remediation
  `ATTEST_INDEPENDENT_EVIDENCE`. The volume authority is now discarded only
  when it is absent or no longer current.
- Mapping admission requires `independent_attestation` on both evidence
  contexts, so an unattested mapping fails closed at admission.
- Contract tests: `tests/contract/test_external_use_evaluator.py`
  (unattested → `EVIDENCE_INDEPENDENCE_UNATTESTED`; no evidence →
  `EVIDENCE_RECORD_BINDING_INVALID`; attested → `ELIGIBLE` with both evidence
  digests, zone and mapping) and
  `tests/contract/test_external_quantitative_authority.py` (binding requires
  attestation; existing witness fixture carries one).

Re-running the frozen-clock replay against the same retained journals after
the correction records `BLOCKED / EVIDENCE_INDEPENDENCE_UNATTESTED /
ATTEST_INDEPENDENT_EVIDENCE`, which is the truthful outcome for this
rehearsal's evidence.

Consequence for 4A.5–4A.7: the positive path requires evidence contexts that
carry an independence attestation. Any local rehearsal attestation over
generated fixtures must be labelled as a local software rehearsal with no
field-survey claim in its `attestation_id` / `reconstruction_exclusion_basis`
text, and the resulting volume report is software-path evidence only.

## Positive-path rehearsal run2 — 4A.4 to 4A.7 (2026-09-17)

Same protected run root, same sealed fixtures (sub-03 baseline, sub-07
current), Core restarted from `main` with both corrections, the Dashboard dev
server on 3320 with local OIDC, and a script-driven worker lane (no
long-running worker). Drivers: `.dev-data/a2-fix/run2/`.

Honesty label: the two v7 evidence contexts carry an explicit
**local-software-rehearsal** independence attestation
(`attestationId LOCAL-SOFTWARE-REHEARSAL-2026-09-17-*-NO-FIELD-SURVEY`,
exclusion basis states hand-set checkpoints over a generated constant-plane
DSM, no field survey, no accuracy or independence claim). This proves the
attested software path only. It is not survey evidence.

| Stage | Result |
|---|---|
| Authority | snapshot seq 13 re-issue plus catalog refresh `71f9bba1…`; seq 14 policy v7 `37704e5b…` plus attested contexts; reload 200 |
| 4A.2 inspection (v7) | sub-03 and sub-07 REPORTED, 2×MEASURED each, production decoder over sha-verified bytes (reports `a2c6d517…`, `779e39b8…`) |
| 4A.3 evidence (v7) | both VALIDATED with true aggregates n=3, mean −0.0167, MAE 0.03, RMSE 0.0332, max 0.05 (records `215c9e3e…`, `7d31bb9c…`) |
| Mapping | seq 15 ADMIT_MAPPING `68683970…` activated |
| 4A.4 pair (BFF) | RELATIVE_VOLUME 201 **ELIGIBLE / USE_ELIGIBLE**; VISUAL_COMPARISON 201 BLOCKED / POLICY_UNAVAILABLE (v7 does not permit that use, correct) |
| 4A.5 volume (BFF plus lane) | issue 201 ISSUED; lane lease 201, input INPUT_READY, both DSMs sha-verified; production `align_masked_dsm_difference` plus `measure_external_volume_zone`: zone 256 cells, all valid, area 256 m², cut 0, **fill 128 m³, net 128 m³** (256 m² × 0.5 m), uncertainty 12.0075 m³ (256 × hypot(0.0332, 0.0332)); report 201 REPORTED, request SUCCEEDED, report `…19d270b9…` |
| 4A.5 read-backs (BFF) | site history 200 AVAILABLE; report 200; site observation view 200 |
| 4A.6 review (BFF) | 201 `err-v1-1804dbd3…`; read-back 200; idempotent re-record returns the same review |
| 4A.7 proposal (BFF) | propose 201 `erop-v1-853ccbab…`; approve 200; successor `obs-work-external-7d7090fac0db8c72b83ae856` is `EXTERNAL_REOBSERVATION_PLANNING` with acquisitionRunAllowed=false and missionIssuanceAllowed=false (Core read) |
| Negative | unauthenticated review POST 401 |

Third defect found and fixed during run2: production mapping execution
activation hard-coded `baseline_rmse_m=None` / `current_rmse_m=None`, while
Core sends the two VALIDATED evidence records to the worker and the
production measurement container then must report the independent-epoch RSS
uncertainty. Core therefore rejected every real worker report with
`INVALID_REPORT / uncertainty must be unknown without two trusted RMSE
values` (first run2 request expired on this). The execution authority now
binds both epochs' Core-validated RMSE from the resolved participant snapshot
(never client input). The production-flow contract tests now file the
worker-consistent uncertainty and failed before the fix.

Observed UX gap (backlog): the source work-order page still shows
"외부 산출물 등록 준비" (prepare registration) as the next action after its
result was reviewed and a successor was approved.

Final state: stack stopped (8020/3320/9120/9002 down); `apps/dashboard/tsconfig.json`
edit made by `next dev` reverted.

Boundary: LOCAL software rehearsal only. Not staging, vendor export
compatibility, HIL, field acceptance, or survey accuracy.
