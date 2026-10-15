# SINGLE_VOLUME SV-4 execution record — integrated flow, rehearsal and close-out

Status: complete — owner acceptance 2026-09-18 (SV-4 done per spec §10).
Spec: `docs/superpowers/specs/2026-09-17-single-volume-design.md` §9 (testing and acceptance) and §10 (SV-4 = "Integrated flow + replay + rehearsal + docs").
Base: `main` 600e7d6. Branch: `feat/single-volume-sv4` (merged fast-forward with owner approval, 2026-09-18).

## Scope executed

- **Integrated flow + replay** — already covered by the production-flow test; verified, no new product code:
  `tests/contract/test_external_quantitative_production_flow.py:2001` (`test_signed_provider_drives_complete_external_relative_volume_lifecycle`) drives the single path at `:2165-2340` (admit single mapping → decision ELIGIBLE → issue → claim → worker input → report) and the review/proposal/approval/successor path via `_review_propose_and_approve_single_over_http` (`:781`); restart replay at `:2358-2405` calls `_assert_single_lifecycle_replayed` (`:833`) which runs `verify_external_reobservation_graph`.
- **SV-V3** — the shared review status line rendered the raw ISO `reviewedAt`; now `formatKoreanDateTime(review.reviewedAt, { dateStyle: "short", timeStyle: "short" })` (`apps/dashboard/src/components/external-results/ExternalResultReviewActions.tsx:7,254`), both families.
- **SV-V4 (owner-approved copy)** — list approved as-is 2026-09-18; the only inconsistency `미기록` → `기록 없음` at the single RMSE line (`ExternalResultWorkflowPanel.tsx:276`).
- **a11y** — single result card heading `h3` → `h4` with the className unchanged (`ExternalResultWorkflowPanel.tsx:296`), fixing the `h3`(측정) → `h4`(목록) → `h3`(결과) outline backtrack inside the measurement card.
- **Rehearsal** — local in-process end-to-end run with real sealed GeoTIFF bytes and the production measurement path (spec §9 bullet "Rehearsal"), run twice.
- **Gates, independent verification, review, docs** (this record + product-state).

## Commits

- `90c7ec5` fix(dashboard): format shared review timestamp in Korean (SV-4)
- `89d7533` fix(dashboard): unify single-volume copy and heading level (SV-4)
- `77a3840` test(dashboard): guard single-volume heading and review timestamp (SV-4)
- this record + product-state close (docs commit)

Commits carry no `Co-Authored-By` trailer (OpenCode session, owner decision).

## Evidence

### Gates (test-runner, exact exit codes, real runs)

- @89d7533 (full slice-close gates): `ruff check .` 0; `mypy packages services tests tools` Success (819 files); `tests/contract` in 10 chunks — 6029 passed / 112 skipped / 0 failed; `packages services` 193 passed / 0 failed; `tests/e2e tests/hil tests/replay tests/support tests/tools` 398 passed / 4 skipped / 0 failed; dashboard `tsc --noEmit` 0, `npm run lint` 0, `npm test` 118 files / 896 passed, `npm run build` 0.
- @77a3840 (test-only commit after the full gates): dashboard `tsc` 0, `lint` 0, 896/896, build 0; the 12 contract files that read `apps/dashboard` (found via `grep -rl`) — 139 passed / 0 failed. `git status` clean before/after; HEAD unchanged.

### Rehearsal (local, in-process, real bytes)

- Command: `SV4_RESULT_TAG=runA uv run --locked python .dev-data/sv4-rehearsal/rehearse.py` → exit 0; runB → exit 0; measured values identical.
- Fixtures (`.dev-data/a2-fix/fixtures/`, labelled synthetic constant planes): `current-dsm.tif` sha256 `7b70c280…e36f8eb` / 408 B; `checkpoints-current.csv` `6d98404a…12d7f91` / 128 B; `ortho.tif` `10b3bdb1…aecab166e` / 425 B.
- Observed: fill 0.0 m³; uncertainty ±1.1939849245279506 m³; base roughness ≈0 (2.63e-15 m); common valid 1.0; boundary valid 1.0; 36/36 cells / 36.0 m²; checkpoint TRUE stats n=3, mean −0.016667, rmse 0.033166, max 0.05 → VALIDATED; verdicts REPORTED / ELIGIBLE / ISSUED / LEASED (fence gen 1) / INPUT_READY; report digest `sha256:30100b97…3909a`; review `err-v1-75a1b4d9…` → proposal → approval → successor `obs-work-external-01aa5588…`; briefing sentence `… 적치물 체적 0.0 m³ (±1.2 m³, 기저면 거칠기 0.00 m).`; restart replay of decision/report/reads/lifecycle passes and `verify_external_reobservation_graph` passes; journal chain covers every stage (3 site briefings).
- Evidence: `.dev-data/sv4-rehearsal/EVIDENCE.md`, `result-runA.json`, `result-runB.json` (machine-local, git-ignored).
- Reviewer note (M-3, documentation completeness): the runA/runB "differ by design" list should also name the inspection report digest, which differs between runs while measurement/evidence/briefing values are identical.

### Visual fidelity (SV-V3/V4 UI)

- design-task final verdict **VISUAL PASS** on regenerated captures (`design-previews/sv3b-single-volume/captures/{states,single,relative,share}-{desktop,mobile}.png`, 12:47; git-ignored harness): Korean datetime in the review status line (single `2026. 9. 15. 12:00`, relative `2026. 9. 2. 12:00`, no raw ISO); single result card heading h4 (visual unchanged); null-RMSE line pixel-legible `대상 독립 검사점 RMSE: 기록 없음`; no regressions at 1280x800 / 390x844.
- One fix round: the first review returned FAIL on evidence legibility only (details collapsed); the harness expanded the null-RMSE details and was re-captured; re-review verdict PASS. DOM checks 9/9, no console errors.
- This is Build visual verification plus a delegated design-task fidelity review — not Design or Human approval.

### Independent review

- reviewer on `600e7d6..89d7533`: Critical 0; Important I-1 (no heading-level guard), Minor M-1 (substring assertion), M-2 (no panel-level datetime assertion). Fixed at `77a3840`; scoped re-review verdicts: I-1 ADDRESSED, M-1 ADDRESSED, M-2 ADDRESSED, no new breakage, diff isolation verified (4 files, all in scope; full diff artifact `.opencode/artifacts/sv4-branch.diff`).
- Residual minor: the heading className is verified by diff, not asserted in a test. Coverage: the reviewer had no shell, so diff isolation was supplied as an artifact and gate/visual claims were executed by the test-runner, not the reviewer.

## Decisions

- Copy approved by the owner 2026-09-18: the SV-V4 list as-is, `미기록` → `기록 없음` unification, and the single result card heading h3 → h4 (className unchanged, zero visual delta) to correct the outline backtrack.
- Rehearsal ruling: in-process per the spec's wording ("local in-process playbook") with real sealed bytes and the production measurement path; a live-stack operator session remains an unverified boundary, not an SV-4 done condition.
- SV-3b follow-ups were not all closed here; they are recorded in the product-state backlog at this slice close.

## Boundaries (not verified)

- No live local-stack operator session; no container worker/manifest round trip for this rehearsal; no S3/MinIO; no HIL, field, vendor-compatibility or release evidence. Fixtures are labelled synthetic planes; no accuracy or independence claim is made anywhere.
- Pre-existing raw ISO remains in the selected-request status line (`보고 완료 · 2026-09-15T01:00:00Z`, both families) — routed to the backlog (overlaps the dashboard date-format SSOT work).
- Rehearsal harness observations (not product defects): `latest()` race on a superseded REVIEWED briefing was worked around by reading the journal; filed metrics carried a raw `cutM3: -0.0` (the briefing renders 0.0).

## Follow-ups (backlog candidates recorded in product-state)

- Selected-request status line raw ISO (both families) — overlaps `2026-09-17-dashboard-experience-improvements.md` B1.
- SV-3b render-lag follow-up: `selectedRefRef` / `selectionGenerationRef` mirror updates one render late; a reload invoked in the same tick is dropped (fail-closed, retry needed).
- [x] M-3: add the inspection report digest to the rehearsal evidence's differ-by-design list. Done 2026-10-15: `.dev-data/sv4-rehearsal/EVIDENCE.md` (machine-local, git-ignored) now names the inspection report digest and why it differs (binds the Core-issued report moment; measurement/evidence/briefing values stay identical).
