# Plan

Requirement IDs:
- REQ-MSN-101, REQ-EVT-101, REQ-GEO-101
- SPATIAL-002, RISK-003, RISK-004, EDGE-001
- INV-010, INV-011, INV-020, INV-021, INV-040, INV-041, INV-050, INV-052

Owner module:
- `packages/mission-contracts` executable activation consumer (Manifold deployment is the remaining HIL gate)
- `services/core` event/evidence gate
- `services/bim-integration`
- `apps/dashboard` only for existing change integration and truthful readiness display

Acceptance criteria:
- A concrete Edge-facing consumer refuses malformed, unsigned, wrong-digest, wrong-schema,
  unknown/revoked/expired-key and out-of-TTL contracts, and persists an active digest only after
  successful `load_verified_contract` validation.
- CRITICAL confirmation refuses a RiskField reference unless a registered non-tombstoned artifact
  exists, its bytes can be read, JSON/model validation passes, geometry is non-empty, the RiskField
  covers the event time and references the event entities; the verified content digest is frozen in
  the transition evidence snapshot.
- mm-unit georeferenced IFC geometry returns meter-correct local offsets without applying the unit
  scale twice; the transformed output is then normalized from the declared `MapUnit`, or from the
  project length unit when `IfcProjectedCRS.MapUnit` is omitted. The same meter contract applies to
  `IfcRigidOperation`, which has no scale field. IFC-to-GeoTIFF uses the corrected mesh.
- Root Python and Dashboard gates exit 0. No hardware result is promoted without HIL evidence.

Contracts affected:
- Mission Contract v1.2 semantics are unchanged; a new activation receipt/runtime boundary consumes it.
- Event transition behavior becomes stricter for CRITICAL confirmation. Evidence uploads add
  `application/json` for typed machine evidence; EventBundle v1.2 wire fields stay unchanged.
- RiskField v1.0 wire schema stays unchanged; server-side semantic validation is strengthened.
- IFC public extraction return contract remains meters, with corrected implementation.

Reference assets:
- ADR-KSI-002, ADR-KSI-007, ADR-KSI-009, ADR-KSI-010
- `contracts/schemas/mission-contract.v1.2.json`, `risk-field.v1.json`,
  `event-bundle.v1.2.json`
- `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`, existing `psdk_tap` and timing capture tools
- Reference repositories are `REFERENCE_ONLY`; no runtime import or modification.

Adoption decisions:
- Reuse `load_verified_contract` as the only structure+signature+TTL gate; do not duplicate crypto.
- Keep tactical RiskField generation on Manifold. Core validates persisted evidence content and
  relationships, but does not recompute tactical geometry.
- Use ifcopenshell geometry output's measured meter units once; map conversion adds map offsets once.
- Treat `auto_local2global` output as map-unit coordinates. Resolve that unit from
  `IfcCoordinateOperation.TargetCRS.MapUnit`; when a present target CRS omits `MapUnit`, apply the
  IFC4.3 project-unit fallback. Preserve the existing half-set behavior when `TargetCRS` itself is
  absent because its output unit is not described by a CRS entity.
- Existing UI changes are preserved unless a gate proves a conflict.

Files to change:
- `.ai/goal.md`, `.ai/plan.md`, `.ai/task-state.md`, optional `.ai/handoff.md`
- Mission activation consumer under `packages/mission-contracts` and tests under `tests/contract`
- `services/core/src/ksi_core/events.py`, evidence/RiskField verifier and tests/OpenAPI
- `services/bim-integration/src/ksi_bim_integration/ifc_reference_model.py` and IFC tests
- risk/phase ledgers and remaining-work docs only after evidence is available

Tests:
- Focused contract tests for activation, event triage/evidence, RiskField and IFC conversion
- Explicit mm regressions for `IfcProjectedCRS` without `MapUnit` and `IfcRigidOperation`
- Edge native control-plane build/ctest where touched
- `uv run --locked pytest -q`
- `uv run --locked ruff check .`
- `uv run --locked mypy packages services tests tools`
- Dashboard Vitest (expected baseline 214), ESLint and production build
- `git diff --check`, reference-import guard and relevant hygiene checks

HIL or real-device assumptions:
- Prior repo evidence says M4D, RC Plus 2, Manifold 3 and PSDK entitlement exist, but current reachability
  must be rechecked. `.dpk` install/start, USB bulk and RC import are device writes explicitly within
  this task; secrets/OTP are not handled. Failure or absence remains BLOCKED/SPIKE_REQUIRED.

License/data implications:
- No customer/production data or new external asset is introduced.
- Existing PSDK/ifcopenshell licenses remain unchanged; no reference-repository runtime code is adopted.

Rollback:
- Remove the activation consumer and stricter confirmation wiring, revert the IFC extraction change,
  and restore prior docs/ledger states. No schema migration or production mutation is involved.
