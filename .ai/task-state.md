# Task State

- Status: software_complete_hil_blocked
- Date: 2026-08-14
- Milestone: safety gate integration and H3/H4 evidence audit
- Baseline worktree: Dashboard audit follow-up changes plus DSM test-module rename are uncommitted and
  preserved. Initial `git diff --check` is clean.
- IFC: fixed the mm + `IfcMapConversion` double scale. Geometry-engine meter coordinates are restored
  to project units only for georeference transformation, then map scale is applied once. The
  `auto_local2global` output is normalized from explicit `TargetCRS.MapUnit`, or from project units
  when a present target CRS omits MapUnit; this closes the reverse 1000x expansion for mm
  `IfcRigidOperation` and MapUnit-omitted files. Focused IFC reference/conversion suite: 34 passed.
  Risk `bim-integration-ifc-mm-unit-double-scale` was audit-reopened for the follow-up regression and
  resolved again with those test refs in `.ksi/goals.json`.
- Mission Contract: added the installed `ksi-mission-contract-consumer` CLI and public-key-only registry.
  It calls `load_verified_contract`, rejects duplicate-key/oversized JSON, atomically persists exact
  bytes with mode 0600 only after VALID, keeps the previous active contract on candidate failure, and
  revalidates TTL/revocation on every active load. Its state directory must be a non-symlink directory
  owned by the process user with no group/other access (0700). This closes the package-level software
  caller gap but not the ledger risk: deployment through the Manifold PSDK application and HIL
  rejection evidence remain required, so `mission-contract-verification-unwired` stays open.
- CRITICAL RiskField: confirmation now requires all referenced artifacts to be registered and not
  tombstoned, reads the `application/json` RiskField bytes from storage, rejects malformed/oversized/
  empty geometry, checks validity covers `occurredAt`, entity coverage and positive finite horizon,
  and freezes exact content SHA-256 plus semantic metadata in `evidenceSnapshot`. Storage outage is
  503 and bundle/artifact races are 409. The old presence-only risk is resolved with these tests;
  residual RISK-003 production synthesis is separated as open `riskfield-production-generator-unwired`.
- Dashboard: integrated prior audit work. World now displays actual observation/Core receipt times,
  reporting-device count, uncertainty range and honest 2D/3D layer status without inferring online
  state. Fleet·Edge and Data·AI remain `준비 중` because heartbeat/device-lineage APIs do not exist.
- HIL: session `SESS-20260813T162327Z-PENDING-SN` was blocked before inventory. `ksi-manifold`
  (`172.30.1.33`) returned `No route to host` from both local addresses and neighbor state was
  `FAILED`; a 2026-08-13T17:04:01Z read-only retry had the same result. No DPK/device mutation or
  flight/gimbal command occurred. DPK startup, USB bulk channel, frame-telemetry p95 and RC Plus 2
  KMZ import remain NOT_VERIFIED. Evidence is staged under the ignored `hil_raw_logs/<session>/` path.
- Verification:
  - Full Python: `3031 passed, 22 skipped, 3 xfailed` (soft FD limit raised from 1024 to 8192; the
    unmodified limit caused infrastructure `Too many open files`, not test assertions).
  - Mission consumer trust-boundary tests: 11 passed; focused IFC/GeoTIFF suite: 34 passed; prior
    focused safety/API/IFC suite before the two follow-up regressions: 158 passed.
  - Ruff: pass. mypy CI scope: 296 source files pass. `git diff --check`: pass.
  - Dashboard: 23 files / 217 tests pass, ESLint pass, Next.js production build pass.
- Acceptance review: initial verdict was `Needs changes`; the stale IFC risk document and consumer
  state-directory trust checks identified by review have been corrected. The follow-up MapUnit and
  IfcRigidOperation regression fix also received `Approved` with no must-fix items. Hardware/Edge
  deployment findings remain explicit blockers rather than software completion claims.
- Git: no commit, push, tag or release was performed.
