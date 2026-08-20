# Current implementation plan (2026-08-20, closed-loop MVP)

Requirement IDs:
- REQ-WRK-101, REQ-ACQ-101/102, REQ-INT-101, REQ-COP-101/102,
  REQ-SEC-101, REQ-UX-101; INV-001/002/010/020/040/041/050~052/060/061.

Owner module:
- Product/architecture contracts, Core, DJI Gateway, Manifold Runtime, Processing Controller,
  Dashboard.

Acceptance criteria:
- Observation Work Order가 반복 관측과 사람 승인, 수집·처리·결과,
  근거가 연결된 재관측 초안을 내구적으로 표현한다.
- DJI adapter는 feature flag와 실기 `VERIFIED` capability 근거가 둘 다 있을 때만
  wayline/media 작업을 수행하고 멱등 재시도한다.
- Edge는 검증된 Mission/Capture Policy 범위에서만 제한된 재촬영·짐벌·
  사전 승인 관측점을 허용하며 PSDK를 직접 호출하지 않는다.
- Copilot은 조직·현장 범위 typed tools가 반환한 근거만 인용하고,
  외부 AI 반출은 명시적 허용이 없으면 거부한다.
- Dashboard는 정상 흐름을 5단계·화면당 기본 행동 하나로 표시하고
  USB/SD/KMZ를 접힌 복구 도구로만 남긴다.

Contracts affected:
- Observation Work Order v1, Capture Policy/Quality v1, Copilot Answer v1, Core OpenAPI 1.24.

Reference assets:
- DJI 기본 비행/Pilot 2는 채택하되 실행 런타임은 참조 저장소에서
  import하지 않는다. Cloud/PSDK/MSDK 세부 지원은 실기 증거까지
  `NOT_VERIFIED`다.

Adoption decisions:
- Cloud/Pilot-to-Cloud → PSDK/Manifold → 얇은 MSDK 순으로 검증한다.
- LLM은 수치 계산기·비행 권위가 아니다. 재관측은 초안과 사람 승인을
  분리한다.
- 수동 KMZ·folder ingest는 제거하지 않고 rollback/장애 복구로 남긴다.

Files to change:
- `docs/product`, `docs/architecture`, `contracts`, `packages/event-contracts`,
  `services/core`, `services/dji-gateway`, `edge/manifold-runtime`, `apps/dashboard`, tests,
  `.ai/`.

Tests:
- WorkOrder replay/scope/version/approval, Gateway capability/idempotency/torn journal,
  Capture Policy negative decisions, Copilot allowlist/citation/egress/human approval,
  OpenAPI sync, Dashboard UX mapping, full Python/static/native/Dashboard gates.

HIL or real-device assumptions:
- Provider adapter·자동 media·PSDK 촬영 행동은 실기 증거 없이 활성화하지
  않는다. 현재 변경은 비행·장비 write를 수행하지 않는다.

License/data implications:
- 외부 LLM은 site egress policy 명시 허용 전에 호출하지 않는다.
  DJI SDK/Cloud, static OpenSSL의 약관·license·SBOM은 배포 전 게이트다.

Rollback:
- 각 adapter/feature flag를 독립적으로 끄고 기존 Pilot 2 수동 KMZ·folder ingest로
  되돌린다. 기록된 v1.3 high-water·attested evidence는 강등하지 않는다.

Execution:
1. Product decision/ADR/requirements/invariants — implemented.
2. Organization-scoped WorkOrder/schedule/reobservation ledger — implemented for the new surface.
3. Fail-closed provider-neutral DJI Gateway — implemented; concrete providers blocked on HIL.
4. Signed-policy capture-quality authorizer — implemented as pure native decision boundary;
   live PSDK wiring blocked on HIL.
5. Grounded Copilot orchestration and human-approved draft boundary — implemented;
   production model/query provider not configured.
6. Five-stage field Dashboard and recovery-only manual file path — implemented.
7. Full verification and current-state handoff — complete. Release remains blocked on the
   documented production migration/provider/HIL gates.

---

# Previous implementation plan (2026-08-20)

Requirement IDs:
- REQ-EVT-101, REQ-MSN-101, AOL-1 G1/G4.
- INV-011, INV-020, INV-021, INV-030, INV-040, INV-042, INV-051, INV-052.

Owner module:
- `services/core`, `packages/mission-contracts`, `edge/manifold-runtime`, `edge/psdk-app`,
  `services/processing-controller`, `apps/dashboard`.

Acceptance criteria:
- CRITICAL machine evidence is accepted only with a valid Ed25519 artifact signature and matching
  active-dispatch mission/device/risk-policy/calibration plus existing RiskField lineage.
- Mission Contract v1.3 is dual-read with v1.2, assigns a durable positive site sequence before
  signing, and rejects lower/equal-different replay and v1.2 downgrade after a v1.3 high-water.
- Every measured image has explicit capture-time source/status; bundle and ProcessingJob snapshots
  preserve a complete/incomplete/conflict window; freshness uses only `capturedTo`.
- `GET /v1/sites/{id}` returns a non-null nested spatial-model summary while list and legacy
  `/spatial-model` responses remain compatible.
- Full software gates pass without claiming production, HIL, flight, or field completion.

Contracts affected:
- Evidence `attestation={keyId,algorithm:"Ed25519",signature}` and response
  `deviceAttested`/`attestationKeyId`.
- Mission Contract v1.3 `issuance={issuerId,siteSequence,issuedAt}` plus dispatch schema dual-read.
- Per-file `captureTime`, bundle/ProcessingJob `captureWindow`, `SpatialModelView` capture fields,
  and `SiteDetailView`; OpenAPI/AsyncAPI/Dashboard mirrors are updated.

Reference assets:
- `docs/00_READ_FIRST.md`, Product Constitution, Final Decision Ledger, Master PRD,
  `DOMAIN_INVARIANTS.md`, ADR-KSI-019/020, relevant contract schemas, and pinned DJI samples.
- `references/` remains read-only and contributes no runtime imports.

Adoption decisions:
- Keep the Core writer default at v1.2 until dual-reader/high-water rollout and HIL are proven;
  v1.3 issuer identity is server configuration only.
- Keep `deviceBound` as channel identity and `deviceAttested` as artifact-signature truth. A device
  signature does not prove the sensor inference itself, so geometry/time/entity/uncertainty checks stay.
- Device public keys are operator-provisioned with no registration API. Edge private keys are read
  only from external owner-only 0600 files and never placed in DPK, env output, logs, fixtures, or repo.
- Link Ed25519 through target-static OpenSSL and reject dynamic `libcrypto` in the target ABI gate.
- Missing/conflicting capture time fails closed; never substitute `registeredAt`.

Files to change:
- Core evidence/dispatch/event/mission/site/source-media/processing/spatial-model/production assembly.
- Mission-contract models/signing/consumer/dispatch and v1.3 schema.
- Manifold attestation signer, Core REST sync, PSDK app assembly, CMake/Docker/ABI gates.
- Processing-controller capture extractor/client/worker; Dashboard site/detail types and labels.
- OpenAPI/AsyncAPI/contracts, contract/E2E/native tests, and `.ai` state/handoff records.

Tests:
- Attestation forged/context/digest/cross-device/unknown/revoked/expired/missing/dispatch mismatch.
- v1.3 gap/duplicate/tampered/new-mission rollback/downgrade/cross-site/issuer/v1.2 replay.
- GPS UTC/offset EXIF/explicit XMP/naive/1-second boundary/conflict/partial/legacy/late-upload/site detail.
- Full Python with FD limit, Ruff, full Mypy, Dashboard test/lint/build, native SQLite/WAL and static
  OpenSSL CTest, PSDK logic/ABI negative gate, API/contract/hygiene/reference guard, KMZ checksums.

HIL or real-device assumptions:
- A-file import/map rendering and original M4D WideCamera JPEG metadata are evidenced. Pilot-exported
  KMZ comparison remains formally incomplete, but the operator accepted it as a residual risk that does
  not block FIELD-0b preparation. Real key provisioning, signed device upload, DPK/USB/frame-telemetry
  and rollback HIL are NOT_VERIFIED. No route execution, flight, firmware update, or device mutation is
  part of this build.

License/data implications:
- Static OpenSSL requires license/SBOM/third-party notice clearance before release.
- No private key, credential, customer data, raw field image, GPS record, or DPK is added to source.
  Existing untracked `download/` and `Testing/` are preserved and excluded from delivery.

Rollback:
- Source and writer activation are independent rollback units. Deploy dual-reader and durable
  high-water first, pass HIL, then enable the v1.3 writer. Never lower a recorded high-water or
  verified evidence to v1.2/unsigned state. No production mutation is performed in this task.

Execution:

1. Device attestation, CRITICAL lineage hardening, static signer, and live sync wiring — implemented.
2. Mission Contract v1.3 dual-reader/durable high-water with writer default retained at v1.2 — implemented.
3. Capture-time lineage, immutable job snapshot, freshness, nested site detail, Dashboard — implemented.
4. Full software verification and independent acceptance follow-up — complete (`Approved`).
5. FIELD-0a Pilot-export comparison remains an accepted residual risk; it does not close the goal.
6. FIELD-0b HIL readiness — current next milestone; FIELD-1/2 and FIELD-3 terrain work remain later.

## FIELD-0b next execution plan

Requirement IDs:
- REQ-EVT-101, REQ-MSN-101; INV-011, INV-021, INV-030, INV-040, INV-042, INV-052.

Owner module:
- `edge/psdk-app`, `edge/manifold-runtime`, `packages/mission-contracts`, `services/core`, and
  `tools/hil`/`scripts/manifold`.

Acceptance criteria:
- With no route execution or flight command, capture a reproducible HIL session manifest and prove the
  Manifold network identity, DJI app-framework state, USB bulk mapping, and capture-only DPK
  install/restart state.
- Only after that, prove 30 seconds of telemetry and 10 seconds of RGB reception. `recv` timing is
  diagnostic only; sensor-time p95 <= 50 ms remains blocked until a verified RGB sensor timestamp exists.
- Separately prove real-Manifold rejection for unsigned, expired, and rollback Mission Contracts before
  enabling the v1.3 Core writer.
- Separately prove a signed evidence registration/upload with an external 0600 Ed25519 key and matching
  Core public-key registry. This does not claim that the signature proves sensor truth.

Contracts affected:
- No new public contract is planned. Existing Evidence attestation, Mission Contract v1.3 dual reader,
  native activation handoff, and Core edge-sync contracts are exercised unchanged.

Reference assets:
- `docs/hil/HARDWARE_SESSION_PLAYBOOK.md` (step 8 before steps 3/4/7),
  `docs/hil/RAW_LOG_CONVENTIONS.md`, `edge/psdk-app/README.md`, and
  `scripts/manifold/probe_usb_bulk.sh`.

Adoption decisions:
- Preserve `field-0a-kmz-acceptance` as `in_progress`; the accepted Pilot-export residual is not a
  substitute for formal field acceptance.
- Start with a capture-only DPK. Native activation, perception, Core sync, and any writer activation
  stay disabled until their own prerequisites and evidence pass.
- Keys, credential headers, bearer tokens, CA bundles, and SPKI pins remain external files; no secret is
  copied into the repository, DPK, CMake cache, command line, or HIL log.

Files to change:
- `.ai/` state and handoff evidence only, unless the HIL session exposes a reproducible implementation
  defect. Device-side raw evidence is placed outside delivery scope under `hil_raw_logs/<session>/`.

Tests:
- Before device work: existing static OpenSSL/ABI/flight-boundary, SQLite/WAL, PSDK logic, and contract
  gates remain the software baseline.
- In HIL: read-only USB probe; official `dji_app_ctl` DPK install/restart/status evidence; raw telemetry,
  RGB, contract rejection, and signed-upload evidence. Each failed stage remains BLOCKED, not inferred.

HIL or real-device assumptions:
- At 2026-08-20T09:38:12Z, the host wired link was healthy at 1 Gbit/s but `172.30.1.33` was ARP
  `INCOMPLETE` and SSH returned `No route to host`; no device action can start until this path is restored.
- The first DPK build/install requires an operator-supplied DJI-issued App credential header and
  `user_app_id`. The signed Core-sync phase additionally requires an operator-provisioned external 0600
  Ed25519 key, registered public key, token file, CA bundle, and pins. The operator enters/provisions
  secret values directly; this plan never requests their contents.
- No `DjiWaypoint*Action`, route upload/start, gimbal command, firmware update, or flight is in scope.

License/data implications:
- A sync-enabled DPK remains release-blocked until static OpenSSL/libcurl third-party notices and SBOM
  evidence are produced. Raw image, telemetry, serial, location, and credential data remain untracked.

Rollback:
- A DPK installation is a distinct device change and is only attempted after reachability and credential
  prerequisites are recorded. Stop/uninstall is the device rollback path; it does not alter Core high-water
  or downgrade signed evidence. The v1.3 writer stays v1.2 by default throughout FIELD-0b.

---

# Historical plan

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
