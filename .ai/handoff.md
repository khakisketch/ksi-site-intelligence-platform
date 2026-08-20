# Current Handoff (2026-08-20, closed-loop MVP)

KSI의 제품 축을 `DJI waypoint 자체 구현`에서 `반복 관측 데이터를
변화·공정·상대 물량으로 바꾸고, 근거형 Copilot으로 설명하며, 사람이
재관측을 승인하는 폐루프`로 고정했다. ADR-KSI-022와 PRD/ledger/
invariant/traceability를 이 결정에 맞춰다.

소프트웨어로는 조직 범위 Observation Work Order 원장, 반복 일정,
사람 승인 재관측 초안, provider-neutral DJI Gateway, 서명 Capture Policy
범위의 native 품질 행동 허용기, typed-tool/citation Copilot, 5단계 `오늘
작업` Dashboard를 추가했다. OpenAPI 1.24는 실구현 경로·요청·응답과
다시 맞춄다.

## 엄격한 완료 경계

- Software foundation: implemented and locally tested.
- Concrete DJI Cloud/PSDK/MSDK provider: not implemented; capability remains `NOT_VERIFIED`.
- Automatic wayline/media round trip: not HIL/field proven; normal UX target is not yet operational.
- Production Copilot: orchestration exists, but no production model or deterministic query backend is configured.
- Tenant safety: new WorkOrder/Copilot surface is organization-scoped. Legacy Site/Mission/Artifact stores
  still need a migration before multi-tenant release, so INV-060 is only partially implemented.
- WorkOrder-to-Mission automatic coordinator and live Capture Policy-to-PSDK execution are not wired.
- FIELD-0a residual, FIELD-0b/1/2, device keys, DPK, media transfer and flight remain separate blockers.

## Verification

- Python: `3686 passed, 23 skipped, 3 xfailed` (`ulimit -n 8192`).
- Ruff and full Mypy: pass (`355 source files`).
- Dashboard: `41 files / 431 tests`, ESLint, TypeScript, Next production build pass.
- Native SQLite/WAL and capture policy: CTest `7/7` pass in the pinned arm64 container.
- OpenAPI sync, hostile-input route coverage, `uv lock --check`, repository hygiene,
  reference/third-party pins, KMZ SHA-256, staged secret-pattern scan and diff check: pass.
- Independent acceptance: `Approved`, remaining must-fix `0`. The first review found and the
  implementation closed Viewer-to-Copilot-draft write authorization and unknown-site list
  200/404 contract drift before this handoff.

## 배포 순서

1. 기존 단일 tenant 원장에 organization migration·rollback·backfill 검증을 먼저 한다.
2. 실장비에서 Cloud 5항목을 검증하고, 불가능하면 PSDK media를 검증한다.
3. 증거를 통과한 adapter 하나만 켜고 WorkOrder→Mission→Gateway→Media를 조립한다.
4. 서버 Intelligence query backend과 site egress policy 후 Copilot model provider를 켠다.
5. HIL·FIELD KPI가 세워진 뒤에만 Manifold active capture를 순차적으로 켠다.

수동 Pilot 2 KMZ·folder ingest는 복구 경로로 보존했다. 사용자가 다음 세션
연속성을 위한 로컬 `main` 체크포인트 커밋을 승인했다. 푸시·태그·릴리스·
프로덕션/장비 write는 수행하지 않았다.

## Next session start

다음 세션은 `main`의 이 핸드오프와 ADR-KSI-022를 읽고 **MVP Integration
Milestone 1**만 진행한다. 목표는 구체 provider를 추측해 만드는 것이 아니라,
실장비 Cloud 5항목과 PSDK media 경로의 capability evidence를 수집해 하나의
adapter 경로를 채택하는 것이다. 장비 접근·자격증명·비밀키·빌링·폄웨어
변경은 사용자의 명시적 현장 지시 없이 실행하지 않는다.

복사해 쓸 시작 요청:

> `main`의 `docs/architecture/ADR-KSI-022-closed-loop-product-and-zero-touch-field-ux.md`,
> `.ai/goal.md`, `.ai/plan.md`, `.ai/task-state.md`, `.ai/handoff.md`를 읽어라.
> 이번 세션은 MVP Integration Milestone 1로 한정한다. 먼저 실장비에서
> DJI Cloud/Pilot-to-Cloud 5항목과 PSDK camera-media 경로를 재탐지하고,
> 증명된 경로 하나만 채택한다. 추측으로 capability를 VERIFIED로 올리지
> 말고, WorkOrder→Mission→Gateway→Media 조립 계획과 HIL 증거를 같이 남겨라.
> 기존 수동 Pilot 2/KMZ/folder ingest는 복구 경로로 보존하고 비행·장비
> write, 자격증명, commit/push/release는 해당 세션의 명시 승인 경계를 따라라.

---

# Previous Handoff (2026-08-20)

세 소프트웨어 안전 범위를 구현했다. 첫째, CRITICAL RiskField evidence는 채널의
`deviceBound`와 별개로 artifact Ed25519 서명을 검증하고, 활성 dispatch의 mission/device/
risk-policy/calibration과 기존 geometry/time/entity/uncertainty lineage가 모두 맞아야 한다.
공개키 registry는 운영자 파일 프로비저닝 전용이며 등록 API가 없다. Manifold 개인키는
외부 owner-only 0600 파일에서만 읽고 target-static OpenSSL을 사용한다. PSDK 앱은 journal
replay와 상시 Core sync 경로를 실제 실행 조립에 연결한다.

둘째, Mission Contract v1.3은 server-issued `issuance={issuerId,siteSequence,issuedAt}`와
durable per-site/issuer high-water를 가진다. v1.2/v1.3 dual-reader는 gap을 허용하되 낮은
sequence, equal-sequence 변조, v1.3 이후 v1.2 downgrade를 거부한다. 운영 writer 기본값은
안전한 staged rollout을 위해 계속 v1.2다.

셋째, 워커는 사진마다 고정 우선순위로 capture time을 측정하고 Core는 파일 상태와 번들
window를 원장에 기록한다. 성공 ProcessingJob은 그 window를 불변 스냅샷으로 보유한다.
공간모델 freshness는 오직 `capturedTo`를 쓰며 incomplete/conflict에서 `registeredAt`으로
대체하지 않는다. 단일 site 응답은 비-null spatial summary를 포함하고 Dashboard는 그
응답을 직접 쓴다. 기존 `/spatial-model`은 유지된다.

## Verification status

- 최종 full Python: `3635 passed, 23 skipped, 3 xfailed` (FD limit 8192).
- Ruff, full Mypy `345 source files`, `uv lock --check`, API/contract/hygiene/reference guards,
  KMZ 12 tests 및 A/B/C SHA-256 모두 통과.
- Dashboard: `39 files / 419 tests`, ESLint, TypeScript/Next production build 통과.
- Native: SQLite/WAL CTest `6/6`; static OpenSSL attestation CTest `6/6`와 target binary의
  dynamic `libcrypto` 부재 확인; PSDK logic CTest `2/2` 통과.
- 첫 full run에서 나온 12개 assembly/fixture/contract-mirror 회귀는 수정 후 최종 full
  run에서 모두 해소됐다.
- Independent acceptance follow-up: `Approved`, no must-fix items, software handoff scope only.
  `mission-contract-no-issuance-ordering-field` was resolved through the official goal-ledger helper;
  HIL/device-signature and sensor-truth residual risks were intentionally not closed.

## Rollout and rollback

1. v1.3 dual-reader와 durable high-water를 먼저 배포하고 writer는 v1.2로 둔다.
2. 실제 장비 키를 외부 보안 경로에 프로비저닝한 뒤 FIELD-0b에서 signed upload,
   DPK/USB/network/frame-telemetry 및 v1.3 rollback 거부를 검증한다.
3. HIL 통과 후에만 Core v1.3 writer를 활성화한다. 기록된 high-water와 attested evidence는
   v1.2/unsigned 상태로 강등하지 않는다.

## Field and release blockers

- FIELD-0a는 A KMZ import/map rendering과 원본 M4D WideCamera JPEG metadata를 증명했다.
  5280×3956·12.29mm·24mm equivalent·explicit DJI XMP UTC를 확인해 Dashboard shared focal
  length를 12.0mm→12.29mm로 교정했다(focused Dashboard 7 tests/lint/build pass). 원본은
  사용자 untracked `download/drone pictures/`에만 있고 이동·커밋하지 않았다. Pilot-exported
  mapping KMZ와 그 회수 증거가 없어 전체는 여전히 `in_progress`다. 운영자는 이 Pilot-export
  비교를 `kmz-real-device-acceptance-still-unverified` 수용 리스크로 기록해 FIELD-0b 준비를
  진행하기로 했지만, 이것은 formal FIELD-0a 완료나 비행 수용을 뜻하지 않는다.
- FIELD-0b/1/2, 실제 Manifold 서명 키, DPK/USB/frame-telemetry, 실사진 NodeODM 종단,
  2회차 re-observation lineage는 NOT_VERIFIED다.
- 현재 FIELD-0b LAN preflight(2026-08-20T09:38:12Z): PC 유선 `enP7s7`은 1 Gbit/s link-up이나
  `172.30.1.33`은 ARP `INCOMPLETE`, SSH `No route to host`였다. 이는 Manifold/기체 능력 실패
  판정이 아니며, USB probe·DPK install/start·키 provision은 수행하지 않았다.
- 정적 OpenSSL은 배포 전 license/SBOM/third-party notice evidence가 필요하다.
- Core DTM→WPML은 FIELD-2와 ceiling-reference 결정을 통과한 FIELD-3 전에는 시작하지 않는다.
- `download/`와 `Testing/`은 사용자 원본일 수 있어 이동/삭제하지 않았고 전달·커밋 대상이
  아니다. Git commit/push/tag/release, 프로덕션 배포, device write는 수행하지 않았다.

---

# Historical Handoff

## Outcome

The software safety gates are implemented and locally verified. Field readiness is **not** claimed.
IFC mm georeference is fixed and its high-risk ledger item is resolved. Mission Contract activation
and CRITICAL RiskField consumption are fail-closed in software, while their hardware/generation risks
remain open under their original resolve conditions. The consumer also rejects untrusted state
directories (symlink, wrong owner, or any group/other permission) before writing or loading active
contracts.

The IFC meter contract now covers three distinct georeference cases: an explicit map unit, the IFC4.3
project-unit fallback when a present target CRS omits `MapUnit`, and scale-free `IfcRigidOperation`.
A coordinate operation whose `TargetCRS` itself is missing remains a compatibility-only half-set; its
unit cannot be proven from the CRS and must not be advertised as verified georeferencing.

## Remaining blockers

1. Restore network/device access to `ksi-manifold`. The latest read-only retry at
   `2026-08-20T09:38:12Z` returned `No route to host` with neighbor `INCOMPLETE`, although the PC's
   wired carrier was up. Once reachable, run `scripts/manifold/probe_usb_bulk.sh` and collect the
   app-framework state, firmware/SDK inventory, and USB bulk channel before any DPK change.
2. Run `psdk_tap` through the installed DJI application framework, collect at least 100 valid
   frame/telemetry pairs and evaluate official p95 against 50 ms.
3. Import the generated KMZ on RC Plus 2 and record `wpmz/`, `droneEnumValue`, payload values and route
   display. Do not promote camera/flight/battery/RTH capability without that evidence.
4. Deploy `ksi-mission-contract-consumer` at the Manifold-facing execution boundary and HIL-test
   malformed/tampered/expired/revoked rejection before resolving `mission-contract-verification-unwired`.
5. Decide RISK-003 geometry synthesis ownership/shape and wire the producer before resolving
   `riskfield-production-generator-unwired`; the Core consumer now validates real bytes but
   intentionally does not invent tactical geometry.
6. Define a durable Edge device heartbeat/presence contract before implementing Fleet·Edge connection
   state. Event or equipment observations must not be relabeled as an online connection.

## Re-run commands

```bash
ulimit -n 8192 && uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
cd apps/dashboard && npm test && npm run lint && npm run build
```

The raised soft FD limit is currently required for the monolithic Python suite on this host; the
default 1024 limit exhausts descriptors across the large number of journal-backed tests.
