# FPC-03C — V2 DSM 실바이트 검사와 Analysis 연결

- Plan ID: `FPC-03C-20260929`; status: local software evidence complete, product/host gates open. Parent: `2026-09-28-first-product-completion-roadmap.md` FPC-03/04/05. Current product slice remains EXT-VAL.
- Requirement IDs: REQ-INT-101..104, REQ-SEC-101, REQ-OPS-102; EXT-VAL-01..05; INV-020/024/040/051/053/060.
- Owner modules: Core external reconstruction/inspection/Analysis and processing-controller inspection/measurement; implementation ownership for this task is limited to contract-test fixtures and an end-to-end local integration test.
- Acceptance: two sealed V2 DSM-only epochs' actual GeoTIFF bytes are independently parsed through the test-owned inspector UDS; Core records measured facts, distinguishes declarations, and admits the same exact bytes to the Analysis/GIS worker, whose stored result/evidence match a hand calculation. An invalid DSM fails closed without a normal number. Test evidence is local software evidence only.
- Contracts affected: none planned. Preserve V1 and V2 wire schemas, policy authority, and immutable result identity. A runtime contract defect requires a separate scoped correction before implementation.
- Reference assets/adoption: reuse the existing V2 local Analysis fixture, Core inspection lane and real-byte inspector/measurement entrypoint tests (`ADOPT` as test seams). Reference repositories: none; no runtime import.
- Files to change: `tests/contract/analysis_api_local_fixture.py`, `tests/contract/test_external_analysis_http_integration.py`, and one dedicated integration test or the existing real-byte integration test. Do not touch production code in this task.
- Tests: focused new integration and existing V2 Analysis/real-byte tests; Ruff on owned paths and diff whitespace check. Report exact commands/results. A pass must include actual measured source bytes, not a synthetic report helper.
- HIL/real-device assumptions: none. This does not satisfy independent deployed host, DJI Terra export compatibility, RTK accuracy, customer acceptance, or settlement accuracy.
- License/data: generated test GeoTIFF only; no customer data or vendor export.
- Rollback: remove the new integration test and any narrow test-fixture adaptation; no production behavior or journal migration.

## Tasks and dependencies

| ID | Owner | Deliverable | Depends on | Validation |
| --- | --- | --- | --- | --- |
| FPC-03C-T1 | bounded worker in existing task worktree | Exact two-epoch V2 DSM byte inspection through Core worker protocol and measured report assertion | Existing FPC-03B V2 ingress | Focused test with real parser entrypoint; malformed source rejected |
| FPC-03C-T2 | same worker | Link measured inspections to Analysis HTTP/GIS result and retained evidence | T1 | Hand-derived cut/fill/net and exact input/report digests |
| FPC-03C-T3 | Lead | Inspect exact diff, risk review if policy/auth contract changed, integrate hash-matched owned paths, run focused checks on main | T1/T2 | Main checkout focused pytest, Ruff, diff check; record result here |

Stop if completion requires changing production authorization/measurement semantics, operating a host, credentials, or customer data. Record the exact blocker and form a new bounded task; do not label synthetic or local checks as field acceptance.

## 2026-09-29 evidence and boundary

The bounded worker changed only the three named test paths. Exact reviewed source SHA-256 values are `42a7bf7de62c590e2c707d46e940650befdf84e4da7a3c690c76c179c50fb2c0` (fixture), `4a321f81fc32b7690030a49543dc74796d2dc4291a54fd86f36a382a29142a5e` (HTTP test), and `8a9b9f93dc7316585ddd67de8c39779c1ec3f4785c10f3393e9bca606a328e56` (new integration). An independent reviewer returned PASS on that frozen state with no findings. Lead integrated only those paths by hash check; no production code changed.

On main, `uv run --package ksi-core pytest -q tests/contract/test_external_analysis_http_integration.py tests/contract/test_external_analysis_real_inspection_integration.py tests/contract/test_external_validation_real_bytes_integration.py --tb=short --disable-warnings` passed **13** tests. The existing real UDS runner case passed **3** tests. Ruff on the three owned files and `git diff --check` passed. Pytest reported 12 existing temp-cleanup warnings, suppressed in command output.

The positive local case reads the exact sealed two-epoch DSM bytes with the real GeoTIFF parser through a test-owned UDS, records measured inspection reports in the assembled Core store, then uses actual Core HTTP and GIS-worker HTTP to store/replay hand-checkable `cut=0.01`, `fill=0.01`, `net=0.00` m³ with matching report/byte evidence. Malformed current DSM is `BLOCKED / NOT_STARTED` with no result. The test manually drives the in-process Core inspection request/lease/report and uses a test `authority_is_current` callback; it does **not** prove the independent long-running inspection lane, deployed rootless host, real object-store capabilities, Terra export, or field accuracy. Those remain FPC-03/FPC-12/FPC-10 gates.

## FPC-03D — Close the local inspection-lane seam

Plan ID `FPC-03D-20260929`; status: local software evidence complete, product/host gates open. This is a follow-up within FPC-03, not product-slice closure. Requirements, invariants, first-request scope, and excluded external gates above remain unchanged.

| ID | Owner | Deliverable | Depends on | Validation |
| --- | --- | --- | --- | --- |
| FPC-03D-T1 | bounded worker in existing task worktree | Drive V2 DSM-only sealed bytes through actual `InspectionValidationLane`, authenticated Core inspection client/capability, object stream, and real-parser test UDS; retain measured Core report | FPC-03C fixture, existing V1 lane contract | Focused integration with exact byte/digest/lease/report assertions and no synthetic report helper |
| FPC-03D-T2 | same worker | Link two measured reports to the existing Analysis HTTP/GIS result; malformed DSM remains blocked without number | T1 | Hand-derived metrics, evidence IDs, typed blocker, regression |
| FPC-03D-T3 | Lead | Freeze/inspect exact diff, independent review for cross-contract evidence, integrate reviewed paths and rerun narrow checks | T1/T2 | Main focused pytest, Ruff, diff check; evidence here |

Owner paths: a new dedicated contract integration test plus only the existing local Analysis fixture and real-inspection helper if necessary; no production code or wire contract changes. Test-owned HTTP/UDS is not deployed-host evidence. Stop and report a reproducible defect if actual lane, authorization, object capability, or policy semantics need production modification.

### FPC-03D verification and limit

The bounded worker added only `tests/contract/test_external_analysis_real_inspection_lane_integration.py`, SHA-256 `2683148fe04413385ce86750b3e11e3ad7739df12b71a08849956d1cb78ecd07`. Independent review of that frozen file returned PASS with no findings. Lead integrated it by exact hash. On main, the four-file Analysis/real-byte suite passed **15** tests, the existing inspection-lane UDS case passed **3** tests, Ruff lint and `git diff --check` passed, and the new file passed `ruff format --check`. The broader format check named four test files and failed because the three older files contain formatting differences, including lines outside this change; no unrelated formatting sweep was made. Pytest reported 12 existing temporary-directory cleanup warnings.

Core `issue_after_seal` creates each request in the assembled store; the actual `InspectionValidationLane` then uses authenticated Core HTTP for poll/claim/current input, Core-issued object download capability over test-owned loopback HTTP, real parser UDS, heartbeat, report and release. Measured reports retain exact lease fences and feed Analysis HTTP/GIS hand-derived cut/fill/net and evidence. Malformed current DSM remains blocked without a number. This is stronger local software evidence than FPC-03C, but loopback storage, test-owned UDS, in-process assembled Core graph and generated 2×2 rasters still do not prove separate accounts/rootless runtime, real S3, Terra exports, customer repeat operation, or field accuracy.
