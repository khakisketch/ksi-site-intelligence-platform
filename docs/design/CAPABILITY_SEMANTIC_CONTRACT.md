# Capability Semantic and Persistence Corrective Contract

> 상태: 의미·persistence 계약 확정, CAP-1~CAP-5 local software 구현은 이 pre-R3 트리에 반영됨
>
> 근거 감사: `REQ-ACQ-102`, `REQ-ACQ-103`, `REQ-MSN-104`, `REQ-SEC-101`,
> `docs/product/PRODUCT_CONSTITUTION.md`, `docs/product/FINAL_DECISION_LEDGER_v1.0.md`,
> `docs/product/MASTER_PRD_v3.0.md`, `docs/product/DOMAIN_INVARIANTS.md`,
> `docs/DOCUMENT_STATUS.md`, `REPOSITORY_STRUCTURE.md`.
>
> 설계 기준 코드: `41d9f55270581d9660664f6c23c65ab0d7af0a4a`
>
> 2026-09-03 correction closure: legacy `VERIFIED`의 zero-authority mapping과
> prerequisite revocation 뒤 explicit new-authorization reactivation을 이 문서의 유일한
> normative compatibility/activation 규칙으로 확정했다.

이 문서는 현재 세 의미로 쓰이는 `VERIFIED`를 도메인 개념으로 분리하고, 그 의미를
잃지 않는 durable authority journal, replay, projection 계약을 고정한다. public enum은
즉시 rename하지 않지만 adapter 밖에서 ambiguous `VERIFIED`를 권위 상태로 저장하는 것은
금지한다. CAP-1~CAP-5는 local software에서 구현되어 있으며
`services/core/src/ksi_core/capability/authority_store.py`,
`services/core/src/ksi_core/capability/runtime_projection.py`,
`services/core/src/ksi_core/capability/runtime_api.py`,
`services/core/src/ksi_core/app.py`가 중심 경로다.
schema/API 자체의 공개 형태는 현재 유지되며, 실제 HIL/field/owner activation은 별도 gate다.

## 작업 계약

- Requirement IDs: `REQ-ACQ-102`, `REQ-ACQ-103`, `REQ-MSN-104`, `REQ-SEC-101`
- Owner module: Core Capability domain(approval/projection), Acquisition(heartbeat observation),
  DJI Gateway(route qualification/activation)
- Acceptance criteria: evidence claim, exact runtime route observation, exact-route qualification,
  product approval, runtime activation을 별도 상태로 판정하고 어떤 단일 `VERIFIED`도 혼자
  mission behavior를 authorize하지 않는다.
- Contracts affected: 이 문서는 내부 capability authority journal/프로젝션의 구현 계약이다.
  현재 public schema/API/deployment configuration은 변경하지 않는다.
- Reference assets: Core Capability Registry/SpikeEvidence, Acquisition Connectivity snapshot,
  DJI Gateway CapabilityEvidence/Router, VendorDocumentationStatus.
- Adoption decisions: 기존 외부 enum은 `ADOPT_AS_COMPATIBILITY`; 내부 `VERIFIED` 혼용은
  `REPLACE`; exact path/hardware/firmware scope, TTL, feature flag/config/binding gate는 `ADOPT`;
  증거와 activation을 합치는 모델은 `REJECT`.
- Files to change: 이 문서 하나.
- Tests: pinned mapping/gate registry, journal idempotency/replay, authority provenance,
  fail-closed projection, conflict/staleness/restart golden fixtures가 이미 고정됨.
- HIL or real-device assumptions: 실제 DJI/Manifold capability는 이 문서로 검증되지 않는다.
  existing `NOT_VERIFIED`와 feature flags OFF를 유지한다.
- License/data implications: evidence URI의 raw contents와 vendor document license는 별도
  policy 대상. 공개 `/capabilities`에는 firmware/SDK/raw evidence를 노출하지 않는다.
- Rollback: internal semantic adapter를 제거해도 legacy reader는 유지하되, operational
  activation은 OFF로 내린다. evidence를 삭제하거나 `VERIFIED`로 추정하지 않는다.
- Invariants touched: `INV-041`의 장비 기능 검증과 장비 지원단계 분리 및 미검증 UX 차단,
  `INV-040`의 fail-closed production, `INV-060`의 조직·Site 범위를 지킨다
  (`docs/product/DOMAIN_INVARIANTS.md`, `docs/product/MASTER_PRD_v3.0.md`).
  특히 vendor documentation과 exact hardware/path field verification은 독립 evidence로 고정한다.

## 1. 현재 의미 지도

### 1.1 semantic table

| Existing term/value | Producer | Evidence source | Persistence | Authority | Consumer | Actual meaning | Safety/authority effect | Lifecycle / downgrade | Mission behavior authorize? |
|---|---|---|---|---|---|---|---|---|---|
| Core `CapabilityVerificationState.VERIFIED` | Core registry transition을 호출하는 승인 흐름/테스트 | 11-field `SpikeEvidence` + string evidence | **없음**; process memory dict | legacy memory-only product/HIL claim이며 durable approval authority는 없음 | `/capabilities`, 운영 UI 후보 | Product/HIL approval을 의도했던 과거 상태이나 `ProductCapabilityApproval.APPROVED`는 아님 | 현행 `/capabilities`에는 노출되지만 신규 authority adapter는 §7대로 fail-closed | `VERIFIED→BLOCKED`; context/evidence를 지움 | **아니오** |
| Acquisition `CapabilityReceiptV1.status=VERIFIED` | 인증된 `GATEWAY_DEVICE` heartbeat | gateway가 보고한 capability receipt/evidenceRef | `acquisition-connectivity.jsonl` snapshot | gateway가 “현재 이렇게 보고했다”는 관측 권위만 있음 | acquisition readiness / optional mission issue gate | Device/gateway self-reported current availability | unexpired snapshot 안에서 readiness에 영향 | 새 snapshot/profile 변경/5분 TTL로 대체·폐기 | **아니오** |
| DJI Gateway `CapabilityEvidence.status=VERIFIED` | Gateway 조립에 주입된 evidence registry | field/HIL evidenceRef, exact path/hardware/firmware | **없음**; process memory dict | exact route qualification | `CapabilityRouter`와 legacy facade | 특정 integration route의 field-evidence qualification | flag/config/binding도 통과할 때 route 후보 | `NOT_VERIFIED/BLOCKED` record로 재조립; 현재 durable downgrade 없음 | **필요조건이나 단독 충분조건 아님** |
| `VendorDocumentationStatus.DOCUMENTED_*` | vendor-document ingestion/config | vendor document reference | Gateway evidence object 안에서만 memory | vendor 문서가 무엇을 말하는지 | audit/route evidence context | Declared/documented support | field route를 활성화하지 않음 | 새 문서·conflict로 갱신 | **아니오** |
| Gateway feature flag `true` | 배포 운영자/config | 운영 설정 | deployment config | activation intent | `CapabilityRouter.select()` | route 사용을 시도하도록 연 runtime switch | OFF면 무조건 차단 | 즉시 OFF 가능 | **아니오; 다른 조건과 함께만** |

Repository evidence:

- Core enum은 `VERIFIED/SPIKE_REQUIRED/BLOCKED`이고 운영 노출 gate로 쓰인다
  (`packages/domain/src/ksi_domain/capability.py:26-35`,
  `services/core/src/ksi_core/capability/registry.py:57-65`, `:181-193`).
- Core `VERIFIED`에는 구조화 `SpikeEvidence`가 필요하지만 registry 자체는 memory dict다
  (`capability/registry.py:115-179`; `packages/domain/src/ksi_domain/spike_evidence.py:35-78`).
- `/capabilities`는 이 Core registry의 VERIFIED만 공개하며 capability ID/title/state만
  반환한다(`services/core/src/ksi_core/app.py:586-607`). 기본 app은 in-memory registry를
  만들고 9개 spike를 seed한다(`app.py:438-441`, `:561-563`;
  `capability/registry.py:202-223`).
- Acquisition receipt는 gateway self-report이고 `VERIFIED`에는 evidenceRef만 요구한다
  (`services/core/src/ksi_core/acquisition/models.py:266-280`). 인증된 Gateway device만 heartbeat를
  쓸 수 있다(`acquisition/api.py:73-94`). Store는 snapshot을 journal에 append하고 replay한다
  (`acquisition/store.py:52-83`, `:123-155`).
- Acquisition readiness는 unexpired connected snapshot에서 VERIFIED receipt 집합을 읽는다
  (`acquisition/store.py:183-246`). Snapshot TTL은 최대 5분이다
  (`acquisition/models.py:283-323`).
- Gateway `CapabilityEvidence`는 field status와 vendor documentation status를 이미 별도
  필드로 가진다(`services/dji-gateway/src/ksi_dji_gateway/domain/capabilities.py:42-107`).
- Gateway registry key는 `(path, capability, hardware, firmware)`이고 exact VERIFIED만
  반환한다(`domain/capabilities.py:110-153`).
- route 선택은 feature flag, transport, runtime config, org/site/device binding, exact
  verified evidence를 모두 요구한다(`routing/capability_router.py:28-89`).
- Gateway journal은 capability evidence가 아니라 integration receipt만 append한다
  (`persistence/journal.py:17-100`).

### 1.2 왜 단일 rename 문제가 아닌가

세 값은 scope와 authority가 다르다.

- Core `VERIFIED`: 9개의 PRD spike ID에 대한 legacy memory-only product/HIL claim 형태이며,
  durable `ProductCapabilityApproval.APPROVED` authority는 아니다
  (`capability/registry.py:202-213`).
- Acquisition `VERIFIED`: 5개의 current capability receipt가 gateway heartbeat 안에 있다
  (`acquisition/models.py:75-86`, `:266-301`).
- Gateway `VERIFIED`: 5개 semantic capability와 legacy alias를 exact route matrix로 본다
  (`dji-gateway/domain/capabilities.py:29-40`, `:110-153`).

따라서 public enum 하나를 일괄 rename하면 오히려 서로 다른 wire의 reader를 깨고, 9→5
capability mapping이 없는 상태를 감춘다. 먼저 내부 의미를 분리하고 명시적 mapping으로
호환하는 것이 안전하다.

## 2. Canonical internal concepts

### 2.1 `DeclaredCapabilitySupport`

외부 vendor 문서 또는 device manifest가 “지원한다/부분 지원/미지원/미상”이라고 선언한
사실이다. canonical verdict 예시는 `DECLARED_SUPPORTED`, `DECLARED_PARTIAL`,
`DECLARED_UNSUPPORTED`, `UNKNOWN`, `CONFLICTING`이다.

- Evidence authority: vendor document의 출처와 digest를 보존하는 ingestion.
- Safety authority: 없음.
- Legacy mapping: `VendorDocumentationStatus`를 손실 없이 mapping.
- Mission effect: 없음. `REQ-ACQ-103`에 따라 field qualification을 대신하지 못한다.

### 2.2 `RuntimeRouteObservation`

`RuntimeRouteObservation`은 인증된 runtime component 또는 그 component를 검증하는 신뢰된
health collector가 한 시점에 **exact configured route port가 해당 typed capability operation을
받을 수 있는지**를 `REPORTED_AVAILABLE`, `REPORTED_UNAVAILABLE`, `UNKNOWN`으로 보고한
관측이다. 이는 generic “network online”이나 device의 “나는 X를 지원한다”는 선언이 아니다.

- Observation authority: producer identity는 exact subject가 그 시점에 무엇을 보고했는지에만
  권위가 있다. evidence qualification, product approval, activation을 만들 권위는 없다.
- Scope: organization/site, configured deployment binding, subject kind/device/port,
  integration path, canonical capability, equipment/runtime build와 observation lifetime.
- Lifecycle: explicit `expiresAt`, newer exact-subject observation, configured binding 변경으로
  stale한다. replay는 만료시간을 연장하지 않는다.
- Legacy adapter: 기존 authenticated `GATEWAY_DEVICE`의 Acquisition receipt는
  `GatewayCapabilityObservation`으로 보존하고, exact subject/path/capability/binding을 검증한
  경우에만 `RuntimeRouteObservation` 입력으로 적응한다. `VERIFIED→REPORTED_AVAILABLE`,
  `BLOCKED→REPORTED_UNAVAILABLE`, `NOT_VERIFIED→UNKNOWN`이다.
- Non-gateway subject: `PSDK_MANIFOLD`, `MANIFOLD_DIRECT`, 일부 `MSDK_FIELD` 경로는 gateway
  heartbeat가 아니라 Manifold Edge 또는 gateway-edge bridge의 exact route port를 관측한다.
  모든 경로를 gateway라는 이름으로 뭉뚱그리지 않는다.
- Mission effect: §8.5 표의 모든 현재 v1 transport route에서 **새 route 선택/호출**의 current
  runtime 필요조건이다. 이미 발급된 signed Mission Contract의 로컬 실행 권위를 소급
  취소하지 않는다(`REQ-EDGE-101`).

### 2.3 `RouteEvidenceQualification`

exact `(integration_path, canonical_capability_id, hardware_model, firmware_version,
test_build/policy_scope)`에 대해 KSI가 field/HIL evidence를 검토한 결과다. canonical verdict는
`QUALIFIED`, `NOT_QUALIFIED`, `BLOCKED`, `REVOKED`다.

- Evidence authority: immutable raw evidence, procedure, operator, build/firmware scope.
- Approval authority: evidence producer와 별도인 KSI capability approver.
- Legacy mapping: current in-process Gateway `VERIFIED`는 local route 후보로 계속 읽을 수 있지만,
  durable verifier provenance가 없으면 persistence adapter에서
  `LEGACY_ROUTE_EVIDENCE_UNATTESTED`다. 새 `CapabilityEvidenceRecordV1`과 verifier decision 없이
  `QUALIFIED` authority로 migration하지 않는다. `NOT_VERIFIED/BLOCKED`는 각각
  `NOT_QUALIFIED/BLOCKED_LEGACY` negative state로 보존한다.
- Mission effect: exact route 사용의 필수조건이나 activation 없이 충분하지 않다.

### 2.4 `ProductCapabilityApproval`

안정된 product capability ID가 특정 support matrix에서 Operations Console 또는 Mission
policy 후보로 노출될 수 있다는 KSI product/HIL 승인이다. canonical state는
`APPROVAL_REQUIRED`, `APPROVED`, `BLOCKED`, `REVOKED`다.

- Evidence authority: one or more qualified route evidence와 필요한 product/HIL evidence.
- Approval authority: 인증된 human/release approval role. Gateway/device가 스스로 승격할 수
  없다.
- Scope: product capability ID + supported route matrix + firmware/build/policy.
- Approval provenance: durable `approvalRecordId`, evidence producer와 별도인
  `approverPrincipalId`, evidence-set digest, mapping version, required route matrix,
  hardware/firmware/build/policy scope, validity policy와 decision timestamp가 모두 필요하다.
  `approverPrincipalId`는 `SpikeEvidence.operator`에서 추정하거나 복사해 채우지 않으며,
  approval permission을 가진 인증 principal의 별도 필드여야 한다.
- Legacy mapping의 유일한 규칙은 §7이다. 이 provenance가 없는 legacy Core `VERIFIED`는
  `APPROVED`가 아니다.
- Mission effect: public catalog eligibility의 필요조건이나 current site activation은 아니다.

### 2.5 `OperationalCapabilityActivation`

검증 사실이 아니라 **어느 organization/site/deployment에서 exact route를 지금 사용할지**에
대한 운영 상태다. canonical state는 `INACTIVE`, `ACTIVE`, `SUSPENDED`, `REVOKED`다.

- Authority: 운영 승인/config owner.
- Scope: organization/site/device binding/integration route/capability.
- Durable authorization identity: 각 explicit activation decision은 새로운
  `activationAuthorizationId`와 그때 승인한 prerequisite-set digest를 가진다.
- Existing primitives: feature flag default OFF, runtime config, transport, binding checks
  (`capability_router.py:36-89`).
- Activation은 evidence를 만들거나 approval을 승격하지 않는다. OFF는 언제든 fail-closed
  적용할 수 있다.

## 3. A-E 관계

| 질문의 개념 | Canonical concept | 관계 |
|---|---|---|
| A. device-declared support | `DeclaredCapabilitySupport` 또는 device manifest claim | 정보성 claim. field fact가 아님. |
| B. gateway/edge/bridge-observed runtime state | `RuntimeRouteObservation` (`GatewayCapabilityObservation`은 legacy input) | exact route subject의 짧은 TTL current observation. |
| C. field/route evidence verification | `RouteEvidenceQualification` | exact route가 시험 범위에서 통과했다는 승인된 evidence verdict. |
| D. product/HIL approval | `ProductCapabilityApproval` | product capability의 지원 matrix와 사용자 노출 승인. |
| E. operational capability activation | `OperationalCapabilityActivation` | 검증된 route를 특정 deployment에서 사용하도록 별도 enable. |

의존 방향은 다음과 같다.

```text
Declared support ───────────────┐
                               │ information only
Route evidence ──approved───────┼──> Product capability approval
                               │
Runtime route observation ─current──┼──> Operational runtime evaluation
Product approval ─current───────┤
Exact route qualification ──────┤
Feature flag/config/binding ─────┘
```

Device/gateway/edge observation이 `REPORTED_AVAILABLE`이라고 해서 route evidence, product
approval 또는 activation을 자동 promotion하지 않는다. 반대로 product approval과 activation이
있어도 §8.5가 요구하는 exact runtime subject observation이 missing/stale/unavailable이면 새
route operation은 불가하다.

## 4. `/capabilities` 의미와 operational usability

현재 `/capabilities`는 organization/site/device parameter가 없는 public endpoint이며 Core
registry의 product-level ID/title/state만 반환한다(`app.py:586-607`). 따라서 이 endpoint가
표현할 수 있는 정본 의미는 **catalog visibility / approval eligibility**이지 “이 Site의 이
기체가 지금 사용할 수 있음”이 아니다.

### 4.1 노출에 필요한 정확한 사실

신규 semantic projection에서 `/capabilities`가 legacy `state=VERIFIED`로 capability를
노출하려면 다음이 모두 참이어야 한다.

1. stable canonical product capability ID가 존재한다.
2. PRD spike ID와 gateway/acquisition semantic capability 사이의 explicit, versioned,
   many-to-many mapping이 존재한다. 9개 Core spike와 5개 route capability를 이름 유사성으로
   추정하지 않는다.
3. 현재 `ProductCapabilityApproval=APPROVED`가 durable하며 approval actor, evidence set
   digest, support matrix, build/firmware scope, validity policy를 가진다.
4. approval이 요구하는 모든 `RouteEvidenceQualification`이 exact scope에서 `QUALIFIED`이고
   revoked/expired/stale하지 않다.
5. 같은 또는 더 구체적인 scope에 unresolved `BLOCKED/REVOKED` evidence가 없다.
6. approval이 `validUntil` 또는 명시적 review policy를 가지며 현재 그 정책을 만족한다.
7. replay 또는 evidence resolution이 실패하면 capability는 노출되지 않는다.

이 endpoint는 **현재 durable `ProductCapabilityApproval.APPROVED` projection만** legacy wire
`state=VERIFIED`로 직렬화한다. 과거 입력에 `VERIFIED` 문자열이 있었다는 사실은 이 projection을
만들지 않는다. Gateway heartbeat의 `REPORTED_AVAILABLE`이나 특정 Site activation도 뜻하지 않는다.
현재처럼 firmware/SDK/raw evidence를 public 응답에서 빼는 경계도 유지한다
(`app.py:594-606`).

### 4.2 mission behavior가 실제로 사용하기 위한 추가 사실

특정 mission/runtime route가 capability를 사용하려면 `/capabilities` 노출과 별개로 다음이
모두 참이어야 한다.

1. current product approval.
2. 요청한 exact path/hardware/firmware의 current route qualification.
3. organization/site/device binding에 대한 `OperationalCapabilityActivation=ACTIVE`.
4. feature flag ON.
5. selected port의 runtime configuration ready.
6. allowed transport와 exact organization/site/gateway/edge binding 일치.
7. §8.5의 exact 12-row registry에서 요구하는 unexpired matching
   `RuntimeRouteObservation=REPORTED_AVAILABLE`. 현재 mapping의 12개 route는 모두 `YES`이며,
   표에 없는 tuple은 관측 불필요로 default하지 않고 `UNMAPPED_NOT_ACTIVATABLE`이다.
8. Mission Contract/policy가 그 behavior를 허용하고 별도 execution safety gate를 통과.
9. 어느 scope에도 우선하는 BLOCKED/REVOKED가 없음.

항목 4~6은 현재 Gateway Router가 이미 검사한다(`capability_router.py:43-87`). 항목 7의
Gateway-scoped 연결/TTL primitive는 Acquisition readiness에 이미 있으나
(`acquisition/store.py:195-246`), Edge/bridge subject까지 포괄하는 route-specific observation
ingress와 projector는 CAP-5 범위다.
`/capabilities` 응답 하나는 mission authority token이 아니며 어떤 실행 경로도 이 공개
endpoint만 보고 활성화해서는 안 된다.

## 5. Verification과 activation

**Verification/qualification과 activation은 반드시 별도 상태다.**

- Verification은 증거와 승인 범위에 대한 사실이며 append-only history를 가진다.
- Activation은 현재 deployment의 운영 선택이며 OFF가 안전 기본값이다.
- Verification이 새로 생겨도 activation은 자동 ON되지 않는다. 현재 Router도 flag 누락을
  OFF로 처리한다(`capability_router.py:36-44`).
- Activation OFF 또는 SUSPENDED는 evidence를 downgrade하지 않는다.
- **선택한 revocation mechanism은 A — durable `SUSPENDED` activation transition이다.** required
  route evidence, product/HIL approval 또는 exact hardware/firmware scope가 revoked/invalidated되면
  영향받는 모든 activation authorization은 같은 authoritative revocation decision에서
  `SUSPENDED`로 전이된다. config를 삭제하지는 않지만 historical `ACTIVE`는 current
  authorization이 아니다.
- 한 `activationAuthorizationId`에 append된 `SUSPENDED`는 그 ID에 대한 irreversible fence다.
  같은 ID를 `ACTIVE`로 되돌리는 transition, resume/unmask adapter, latest-value overwrite는
  금지한다. 복구 뒤 허용되는 유일한 경로는 모든 prerequisite를 다시 검증한 **새
  `activationAuthorizationId`**다.
- prerequisite가 나중에 복구돼도 `SUSPENDED`는 자동 `ACTIVE`가 되지 않는다. 모든 prerequisite를
  다시 검증한 별도 operations action이 새 `activationAuthorizationId`를 발급해야 한다.

**Effective-operation invariant:** operational projection은 latest historical flag가 아니라
현재 scope의 최신 activation authorization이 `ACTIVE`이고, 그 authorization이 결속한
prerequisite-set이 여전히 current이며, 그 뒤에 이를 fence한 revocation/suspension이 없을 때만
true다. historical `ACTIVE` record나 복구된 evidence만으로 true를 만들 수 없다.

**Normative revocation/reactivation invariant:** required route evidence, product/HIL approval,
또는 exact hardware/firmware scope 중 하나라도 revoke 또는 authoritative invalidation되면,
영향받은 current activation authorization은 같은 authoritative decision에서 durable
`SUSPENDED`로 전이되어야 한다. 그 prerequisite를 나중에 복구하는 것만으로는 이 activation을
다시 operational하게 만들 수 **없으며**, 모든 prerequisite를 다시 검증한 별도 operations
principal의 명시적 결정과 새로운 `activationAuthorizationId`가 반드시 필요하다.

## 6. authority, lifecycle, conflict contract

### 6.1 Evidence authority

- Vendor/device declaration: claim의 출처·digest·시점에만 권위.
- Gateway/Edge/bridge observation principal: exact configured subject의 snapshot을 보고했다는
  사실에만 권위. product/route approval 또는 activation 권한 없음
  (`acquisition/api.py:78-94`; §8.5.4).
- Field operator: raw evidence 생산과 attestation 권위. 스스로 production approval 불가.
- Capability approver: evidence scope와 procedure를 검토해 route qualification/product
  approval을 append할 권위.
- Operations owner: activation ON/OFF 권위. evidence를 수정하거나 승인할 권위와 별개.

인증은 이 역할을 증명하는 수단이고 evidence truth 또는 activation authority와 동일하지
않다.

### 6.2 Persistence 경계

§9~§11은 기존 `DurableJournal`을 재사용하는 단일 Core capability-authority journal을
선택한다. 다음 사실은 그 journal에 durable해야 한다.

- immutable evidence identity/digest/scope.
- route qualification verdict와 approver.
- product capability approval, mapping/version, support matrix, validity policy.
- downgrade/revocation과 그것이 supersede하는 prior decision.
- operational activation decision의 `activationAuthorizationId`, approver principal, scope,
  prerequisite-set digest와 state transition.
- prerequisite revocation과 영향받은 activation authorization의 durable `SUSPENDED` 전이를
  결속한 한 authoritative decision record.

기존 Gateway observation은 connectivity journal에서 durable replay되지만 TTL 뒤에는
runtime authority가 없다(`acquisition/store.py:52-83`, `:195-203`). Non-gateway
`RuntimeRouteObservation`도 audit/replay 가능하되 explicit `expiresAt` 뒤 current가 아니어야
한다. Current Core와 Gateway
capability registry는 memory-only이므로 restart 뒤 promotion을 재구성할 수 없다
(`core/capability/registry.py:57-65`, `dji-gateway/domain/capabilities.py:110-117`). 현재 authority journal의
replay 결과가 이 memory projection을 대체한 promotion 근거를 제공합니다. Gateway integration
receipt journal은 evidence store로 재해석하지 않는다
(`dji-gateway/persistence/journal.py:17-100`).

### 6.3 Promotion

1. Evidence ingest는 immutable candidate를 만든다.
2. Scope/digest/procedure 검증을 통과한 candidate만 approver에게 간다.
3. Approver가 exact route qualification을 결정한다.
4. Versioned capability mapping이 필요한 route qualification 집합을 product capability에
   결속한다.
5. 별도 approver가 ProductCapabilityApproval을 결정한다.
6. 별도 operations principal이 current prerequisite set을 다시 읽고 그 canonical digest를
   결속한 새로운 `activationAuthorizationId`로 Site activation을 `ACTIVE`로 만들 수 있다.

Device heartbeat나 vendor document는 3~5를 자동 실행할 수 없다.

### 6.4 Downgrade와 revocation

- 새 failure evidence, firmware regression, procedure flaw는 `BLOCKED` 또는 `REVOKED`를
  append한다. prior evidence를 삭제하지 않는다.
- 더 구체적인 hardware/firmware route revocation은 그 exact route의 current activation을
  durable `SUSPENDED`로 전이한다.
- product/HIL approval revocation은 mapping된 모든 current activation을 durable `SUSPENDED`로
  전이한다.
- authoritative revocation record는 affected `activationAuthorizationId` 목록과 원인을 값으로
  포함한다. prerequisite revocation과 이 suspension set은 한 append/fsync decision이어야 하며,
  일부 activation만 정지된 중간 상태를 authority로 노출하지 않는다.
- activation OFF는 즉시 적용되며 evidence state는 그대로다.
- evidence/approval 재승격은 blocker를 명시적으로 supersede하는 새 evidence와 approval을
  요구한다. 단순히 최신 timestamp라는 이유로 blocker를 덮지 않는다. 이것은 evidence 축만
  복구하며 activation은 계속 `SUSPENDED`다.
- 재활성화는 복구된 prerequisite 전부가 current임을 확인한 **새 operations decision**과 새
  `activationAuthorizationId`를 요구한다. 이전 `ACTIVE` record를 unmask하거나 재사용하지 않는다.

현재 Core가 VERIFIED→BLOCKED에서 stale context를 지우고 공개 목록에서 즉시 제외하는
fail-closed 관습은 유지한다(`capability/registry.py:151-177`; `tests/contract/test_core_app.py:116-132`).
Durable 설계에서는 evidence 자체를 지우지 않고 projection만 비노출로 바꾼다는 점이
현재 memory model보다 강화된다.

### 6.5 Expiry와 staleness

- Runtime route observation: existing Gateway adapter는 explicit `expiresAt`, 최대 5분이다.
  non-gateway subject는 §8.5.4의 Core-owned freshness policy와 explicit `expiresAt`을 요구하며
  unknown policy에는 default TTL을 부여하지 않는다.
- Route qualification: exact firmware/build scope가 바뀌면 자동 non-applicable이고, 그 old
  scope에 결속된 activation은 durable `SUSPENDED`가 된다. 새 scope에는 새 qualification,
  product approval applicability와 새 activation authorization이 필요하다. 동일 scope도
  `validUntil` 또는 review policy가 만료되면 stale.
- Product approval: approval validity/review policy가 만료되면 non-operational.
- Vendor document: stale여도 field qualification을 자동 취소하지 않지만 conflict review를
  생성할 수 있다.
- 시각 또는 validity policy가 미상인 legacy promotion은 public operational projection에서
  fail-closed 제외하고 audit-only로 보존한다.

### 6.6 Restart reconstruction

1. evidence→qualification→product approval→activation→revocation/suspension 순으로 append-only
   records를 replay.
2. canonical mapping/version과 digest를 재검증.
3. structurally valid event의 revocation/supersession graph가 모순이거나 cycle이면 **그
   canonical capability + scope chain만** `BLOCKED_CORRUPT`로 격리한다. JSON 자체가 깨져
   scope를 식별할 수 없으면 capability-authority subsystem 전체를 sealed로 두고 모든
   capability projection을 false로 만든다. 어느 경우에도 `APPROVED`로 fallback하지 않으며,
   capability 외 Core 기능을 seed state로 되돌리거나 승격하지 않는다.
4. §8.5 exact subject key에 일치하고 `observedAt <= now < expiresAt`인
   `RuntimeRouteObservation=REPORTED_AVAILABLE`만 current로 사용한다. 기존 Gateway snapshot을
   replay해도 expiry를 연장하지 않으며 non-gateway subject를 추정해 만들지 않는다.
5. 모든 feature flag는 deployment config가 없으면 OFF.
6. replay가 historical `ACTIVE` 뒤의 required suspension을 찾으면 current state는
   `SUSPENDED`다. prerequisite restoration record만으로 이를 `ACTIVE`로 바꾸지 않는다.
7. legacy activation에 durable `activationAuthorizationId`와 prerequisite-set digest가 없으면
   `INACTIVE_LEGACY_UNATTESTED`로 격리하며 operational projection에 쓰지 않는다.

### 6.7 Conflicting evidence

우선순위는 “최신이 무조건 승리”가 아니다.

1. same/more-specific scope의 unresolved `BLOCKED/REVOKED`가 `QUALIFIED/APPROVED`보다 우선.
2. device self-report는 field failure를 이길 수 없다.
3. vendor documented support는 field failure를 이길 수 없다.
4. 더 구체적 firmware qualification은 다른 firmware를 승인하지 않는다.
5. conflict 해소에는 approver가 양쪽 evidence를 참조한 explicit supersession decision이
   필요하다.
6. 해소 전 operational projection은 false다.

## 7. Public compatibility mapping

Public/contract enum rename은 지금 필요하지 않다. Product approval에 대한 **유일한 normative
compatibility rule**은 다음이다. §14의 표는 이 규칙의 비규범 요약이며 별도의 승격 규칙이
아니다.

> Legacy Core `VERIFIED` 입력에 matching durable approval provenance가 없으면 **MUST NOT**
> internally map to `ProductCapabilityApproval.APPROVED`; 반드시
> `LegacyCapabilityCompatibility.LEGACY_UNATTESTED`로 격리한다. 이는 audit-only이며
> `ProductCapabilityApproval.APPROVED`는 catalog visibility/approval eligibility뿐이다. durable
> `approvalRecordId`, 별도 `approverPrincipalId`, evidence-set digest, pinned mapping version과
> required route matrix, exact hardware/firmware/build/policy scope, validity policy가 모두
> 검증된 경우에만 그 **approval record 자체**가 `APPROVED`를 만든다.

| Legacy public value/source | Internal semantic mapping | Reader/serialization behavior |
|---|---|---|
| legacy Core `VERIFIED`, durable approval provenance 없음 | `LEGACY_UNATTESTED` | audit-only; `/capabilities` 비노출; mission/runtime authority 없음 |
| verified durable ProductCapabilityApproval record | `ProductCapabilityApproval.APPROVED` | current policy까지 통과할 때만 `/capabilities.state=VERIFIED`로 legacy serialization 가능 |
| Core `SPIKE_REQUIRED` | `APPROVAL_REQUIRED` | 기존 public endpoint에는 비노출 |
| Core `BLOCKED` | `ProductCapabilityApproval.BLOCKED/REVOKED` | 비노출 |
| Acquisition receipt `VERIFIED` | legacy `GatewayCapabilityObservation.REPORTED_AVAILABLE`, exact adapter 검증 뒤 `RuntimeRouteObservation` input | snapshot TTL 안에서만 current; approval/activation 없음 |
| Acquisition `NOT_VERIFIED/BLOCKED` | `UNKNOWN/REPORTED_UNAVAILABLE` | activation 불가 |
| Gateway evidence `VERIFIED`, durable verifier provenance 없음 | `LEGACY_ROUTE_EVIDENCE_UNATTESTED` | current legacy process의 local route 후보일 수 있으나 durable promotion·catalog authority 없음 |
| verified durable `CapabilityEvidenceRecordV1` | `RouteEvidenceQualification.QUALIFIED` | exact route/equipment/build/policy scope만 |
| Gateway `NOT_VERIFIED/BLOCKED` | `NOT_QUALIFIED/BLOCKED_LEGACY` | route 불가 |

내부 코드와 log/metric은 canonical semantic names를 사용하고, adapter boundary에서만 legacy
enum을 읽고 쓴다. legacy audit/export가 원문을 보존해야 하면 `sourceLegacyValue=VERIFIED`처럼
비권위 metadata로만 echo할 수 있고 `/capabilities.state`로 복사하지 않는다. 반대로 현재
`APPROVED`를 public 호환 때문에 `VERIFIED`로 serialize하는 것은 표현 변환일 뿐 approval을
생성하지 않는다. 권위는 항상 durable approval record에서 온다. 향후 public v2가 필요하면
`semanticKind`, `scope`, `operationallyUsable`을 명시할 수 있지만, 이 설계는 기존 public
contracts를 깨는 rename을 요구하지 않는다.

따라서 legacy API/export가 source audit metadata를 `VERIFIED`로 그대로 직렬화하더라도 그
필드는 authority input으로 재수입할 수 없고 `/capabilities.state` 또는 approval projection으로
복사할 수 없다. `/capabilities.state=VERIFIED` 호환 출력은 현재 유효한 durable approval
record를 projector가 읽은 결과일 때만 허용되며, 그 문자열 자체는 approval principal,
approval record identity 또는 activation authority를 부여하지 않는다.

## 8. Canonical identity와 pinned 9→5 mapping

### 8.1 canonical semantic types와 persistence 속성

| Canonical internal type | Producer | Authority | Evidence source | Durable? | Revocable? | Direct operational authority? | Legacy boundary |
|---|---|---|---|---|---|---|---|
| `DeclaredCapabilitySupport` | vendor-document ingester 또는 signed device manifest adapter | 출처가 그렇게 선언했다는 사실만 | document URI + digest 또는 signed manifest | 아니오(정보 축적 축) | supersede 가능 | 아니오 | `VendorDocumentationStatus` |
| `RuntimeRouteObservation` | authenticated gateway/edge/bridge principal 또는 trusted health collector | exact configured route subject가 그 snapshot에 보고된 상태라는 사실만 | existing `ConnectivitySnapshotV1` adapter + CAP-5 route observation input | 예; audit/replay 가능하되 TTL 뒤 current authority 없음 | 새 observation/binding change/`expiresAt`로 stale | 아니오; transient runtime 필요조건일 뿐 | Acquisition receipt `VERIFIED` 등 |
| `RouteEvidenceQualification` | evidence verifier | exact product/route/equipment scope의 시험 판정 | immutable evidence artifact + digest + procedure | 예; capability authority journal | 예 | 아니오; 필수 prerequisite일 뿐 | Gateway evidence `VERIFIED` 등 |
| `ProductCapabilityApproval` | authenticated human product approver | 제품 카탈로그와 policy 후보로 승인 | required qualification IDs/digests + approval record | 예 | 예 | 아니오; deployment activation이 별도 | Core `VERIFIED` serialization |
| `OperationalCapabilityActivation` | authenticated human operations authority | exact organization/site/device deployment 사용 승인 | current prerequisite witness digest | 예 | 예; `SUSPENDED/REVOKED` | 다른 runtime gate와 함께만 예 | feature flag/config는 입력일 뿐 authority record가 아님 |

authority-bearing record에는 generic `VERIFIED` 필드를 저장하지 않는다. 외부 adapter가 이를
읽으면 위 type과 source enum을 함께 기록하고 canonical state로 바꾼다. legacy Core
`VERIFIED`에 §7의 durable approval provenance가 없으면 오직 `LEGACY_UNATTESTED`다.

### 8.2 canonical IDs와 alias

canonical product/runtime capability ID는 현재 acquisition과 v1.3 Gateway가 공통으로 쓰는
다음 5개다.

```text
WAYLINE_DELIVERY
EDGE_DOWNLINK
EDGE_UPLINK
MEDIA_PULL
MEDIA_UPLOAD
```

Gateway legacy alias는 adapter에서만 `WAYLINE_PUSH→WAYLINE_DELIVERY`,
`TASK_STATUS→EDGE_UPLINK`, `CAMERA_MEDIA_PULL→MEDIA_PULL`로 정규화한다. alias 원문은 audit
metadata로 보존할 수 있으나 durable authority key에는 들어가지 않는다. unknown ID는
fail-closed다.

### 8.3 mapping version과 exact source matrix

첫 mapping identity는 **`ksi-dji-capability-map-v1`**이다. mapping의 단위는 단순
`source ID→canonical ID`가 아니라
`(canonicalCapabilityId, integrationPath)→requiredSourceCapabilityIds`다. 한 route의 listed
source는 전부 **AND**이고 각 source는 별도 qualification provenance를 유지한다. 같은 source가
여러 canonical capability에 쓰여도 capability별 별도 product approval이 필요하다. 한 route의
qualification이나 approval이 다른 route/capability를 암묵적으로 승인하는 OR 또는 fan-out은
금지한다.

| Canonical capability + integration path | Required PRD source approvals (all required) |
|---|---|
| `WAYLINE_DELIVERY / PSDK_MANIFOLD` | `SPIKE-DJI-04`, `SPIKE-DJI-06`, `SPIKE-DJI-07` |
| `WAYLINE_DELIVERY / DJI_DOCK` | `SPIKE-DJI-04`, `SPIKE-DJI-08` |
| `EDGE_DOWNLINK / MANIFOLD_DIRECT` | `SPIKE-DJI-07` |
| `EDGE_DOWNLINK / MSDK_FIELD` | `SPIKE-DJI-06`, `SPIKE-DJI-07` |
| `EDGE_UPLINK / DJI_CLOUD` | `SPIKE-DJI-06` |
| `EDGE_UPLINK / PSDK_MANIFOLD` | `SPIKE-DJI-07` |
| `EDGE_UPLINK / MANIFOLD_DIRECT` | `SPIKE-DJI-07` |
| `MEDIA_PULL / PSDK_MANIFOLD` | `SPIKE-DJI-02`, `SPIKE-DJI-07` |
| `MEDIA_PULL / MSDK_FIELD` | `SPIKE-DJI-02`, `SPIKE-DJI-06` |
| `MEDIA_PULL / DJI_DOCK` | `SPIKE-DJI-02`, `SPIKE-DJI-08` |
| `MEDIA_UPLOAD / MANIFOLD_DIRECT` | `SPIKE-DJI-07` |
| `MEDIA_UPLOAD / DJI_DOCK` | `SPIKE-DJI-08` |

이는 현재 candidate catalog와 일치하는 **승격 가능 subset**이다
(`services/dji-gateway/src/ksi_dji_gateway/adapters/catalog.py:18-30`). 표에 없는 canonical/path tuple은 v1에서
`UNMAPPED_NOT_APPROVABLE`이고 evidence가 있어도 승인·activation할 수 없다. 특히
`DJI_CLOUD/WAYLINE_DELIVERY`는 현재 candidate catalog에서도 제외되어 있으므로 mapping하지
않는다.

9개 source 관점의 cardinality는 다음과 같이 고정한다.

| Source capability | v1 target count | Canonical/path targets 또는 결과 |
|---|---:|---|
| `SPIKE-DJI-01` live frame access | 0 | `NO_V1_CANONICAL_EQUIVALENT`; stored media transfer로 오인 금지 |
| `SPIKE-DJI-02` lens/capture/focus | 3 | 세 `MEDIA_PULL` route의 source prerequisite |
| `SPIKE-DJI-03` yaw/gimbal | 0 | `NO_V1_CANONICAL_EQUIVALENT`; 실행 제어 capability는 현 5종에 없음 |
| `SPIKE-DJI-04` FlyTo/Hold/Rejoin/Route Update | 2 | 두 `WAYLINE_DELIVERY` route의 source prerequisite |
| `SPIKE-DJI-05` obstacle-avoidance coexistence | 0 | `NO_V1_CANONICAL_EQUIVALENT`; flight execution safety는 별도 gate |
| `SPIKE-DJI-06` Pilot/Cloud/PSDK control authority | 4 | PSDK wayline, MSDK downlink/pull, DJI Cloud uplink |
| `SPIKE-DJI-07` Manifold event path | 7 | PSDK wayline/uplink/pull, direct downlink/uplink/upload, MSDK downlink |
| `SPIKE-DJI-08` Dock physical operations | 3 | Dock wayline/pull/upload |
| `SPIKE-DJI-09` endurance/thermal/power | 0 | `NO_V1_CANONICAL_EQUIVALENT`; mission feasibility gate이지 transport capability가 아님 |

Zero-target source도 삭제하거나 5종 중 하나로 억지 mapping하지 않는다. 이 결정은 9개 PRD
spike와 5개 transport semantic이 동형이 아니라는 현재 코드 사실을 보존한다
(`capability/registry.py:202-213`, `acquisition/models.py:75-81`).

### 8.4 equipment scope per path

`EquipmentScopeV1`은 role로 정렬된 component 배열이다. 각 component는
`(role, productFamily, hardwareModel, hardwareRevision, firmwareOrImageVersion)`을 가지며
canonical JSON digest를 `equipmentScopeDigest`로 쓴다. product approval과 route evidence에
physical serial/device ID를 넣지 않는다. 그것은 시험 provenance 또는 deployment activation에
만 들어간다.

| Integration path | Required equipment roles |
|---|---|
| `DJI_CLOUD` | `AIRCRAFT`, `GATEWAY` |
| `PSDK_MANIFOLD` | `AIRCRAFT`, `GATEWAY`, `EDGE` |
| `MANIFOLD_DIRECT` | `AIRCRAFT`, `EDGE` |
| `MSDK_FIELD` | `AIRCRAFT`, `GATEWAY`, `EDGE` |
| `DJI_DOCK` | `AIRCRAFT`, `DOCK` |

빈 문자열, wildcard, `LEGACY_UNSCOPED`, 범위 추정은 신규 authority record에서 금지한다.
현재 device attestation은 evidence artifact identity만 서명하고 hardware/firmware를 서명하지
않으므로(`device_attestation.py:116-137`) self-report만으로 이 scope를 만들 수 없다. verifier가
raw evidence와 operator-managed inventory를 대조해 scope를 결정하고 product approver가 그
exact scope를 승인한다. runtime에서는 모든 route가 §8.5의
`configuredDeploymentMatches=true`여야 하며, 표에 적힌 exact subject의 current observation도
일치해야 한다. 여기서 configured identity와 transient observation은 별도 predicate다.

### 8.5 CAP-4/CAP-5 connectivity and runtime observation contract (normative)

#### 8.5.1 의미와 결정 범위

이 절의 `requiresCurrentRuntimeRouteObservation`은 다음 하나만 뜻한다.

> exact activation/configured-deployment scope에 결속된 exact route port가 `now`에 해당 typed
> capability operation을 받을 수 있다고, 권한이 제한된 subject/collector가 보고했고 그
> observation이 아직 만료되지 않았는가.

이는 static configured deployment identity, durable `RouteEvidenceQualification`, durable
`ProductCapabilityApproval`, generic 인터넷 reachability와 각각 별도다. 특히 observation은
어떤 approval/evidence/activation을 선택하거나 생성할 수 없다. observation lookup key는 먼저
durable activation과 trusted configured deployment에서 정하고, self-report payload가 그 key를
정하게 해서는 안 된다.

현재 12개 route는 모두 데이터/명령 전송 port다. static config와 product/HIL approval은 그
port process, socket, bridge 또는 remote endpoint가 지금 살아 있고 typed operation을 받을 수
있음을 증명하지 않으므로 **12개 모두 `YES`**다. 이는 모든 미래 capability가 connectivity를
요구한다는 default가 아니다. 이 표에 없는 tuple은 `NO`가 아니라
`UNMAPPED_NOT_ACTIVATABLE`로 fail-closed한다.

#### 8.5.2 exact 12-row registry

| Canonical capability | Integration path | Required source capabilities | Configured deployment match required? | Current live observation required? | Observation subject/component | Observation freshness required? | Reason | Missing/stale/unavailable behavior |
|---|---|---|---|---|---|---|---|---|
| `EDGE_UPLINK` | `DJI_CLOUD` | `SPIKE-DJI-06` | YES | YES | `GATEWAY_ROUTE_PORT(gatewayDeviceId, EDGE_UPLINK)` — RC Plus 2/Pilot 2 cloud uplink adapter | YES — explicit `expiresAt` | configured RC transport does not prove the Pilot/cloud bridge currently accepts uplink | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new uplink route selection |
| `MEDIA_PULL` | `DJI_DOCK` | `SPIKE-DJI-02`, `SPIKE-DJI-08` | YES | YES | `DOCK_ROUTE_PORT(gatewayDeviceId, MEDIA_PULL)` — configured Dock media service | YES — explicit `expiresAt` | configured Dock identity does not prove its media service or aircraft-media session is available | `TEMPORARY_RUNTIME_INEFFECTIVE`; no media pull |
| `MEDIA_UPLOAD` | `DJI_DOCK` | `SPIKE-DJI-08` | YES | YES | `DOCK_ROUTE_PORT(gatewayDeviceId, MEDIA_UPLOAD)` — configured Dock upload service | YES — explicit `expiresAt` | configured Dock/network does not prove the upload port currently accepts bytes | `TEMPORARY_RUNTIME_INEFFECTIVE`; no media upload |
| `WAYLINE_DELIVERY` | `DJI_DOCK` | `SPIKE-DJI-04`, `SPIKE-DJI-08` | YES | YES | `DOCK_ROUTE_PORT(gatewayDeviceId, WAYLINE_DELIVERY)` — configured Dock wayline service | YES — explicit `expiresAt` | configured Dock does not prove the exact no-start wayline delivery port is ready | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new wayline delivery |
| `EDGE_DOWNLINK` | `MANIFOLD_DIRECT` | `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, EDGE_DOWNLINK)` — Manifold direct ingress adapter | YES — explicit `expiresAt` | configured SIM/HTTPS endpoint does not prove the Edge ingress process is reachable | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new contract downlink |
| `EDGE_UPLINK` | `MANIFOLD_DIRECT` | `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, integrationPath=MANIFOLD_DIRECT, subjectPortId=<trusted MANIFOLD_DIRECT EDGE_UPLINK port>)` — Manifold direct egress adapter | YES — explicit `expiresAt` | configured direct transport does not prove the Edge uplink process is ready | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new uplink route selection |
| `MEDIA_UPLOAD` | `MANIFOLD_DIRECT` | `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, MEDIA_UPLOAD)` — Manifold direct media uploader | YES — explicit `expiresAt` | configured direct endpoint does not prove the media uploader/session is available | `TEMPORARY_RUNTIME_INEFFECTIVE`; no media upload |
| `EDGE_DOWNLINK` | `MSDK_FIELD` | `SPIKE-DJI-06`, `SPIKE-DJI-07` | YES | YES | `GATEWAY_EDGE_ROUTE_PORT(gatewayDeviceId, edgeDeviceId, EDGE_DOWNLINK)` — MSDK field bridge plus Edge ingress | YES — explicit `expiresAt` | MOP/config alone does not prove the MSDK bridge and Edge endpoint pair is alive | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new contract downlink |
| `MEDIA_PULL` | `MSDK_FIELD` | `SPIKE-DJI-02`, `SPIKE-DJI-06` | YES | YES | `GATEWAY_EDGE_ROUTE_PORT(gatewayDeviceId, edgeDeviceId, MEDIA_PULL)` — MSDK field media bridge | YES — explicit `expiresAt` | field app presence/config does not prove the exact media bridge is ready | `TEMPORARY_RUNTIME_INEFFECTIVE`; no media pull |
| `EDGE_UPLINK` | `PSDK_MANIFOLD` | `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, integrationPath=PSDK_MANIFOLD, subjectPortId=<trusted PSDK_MANIFOLD EDGE_UPLINK port>)` — Manifold PSDK/MOP uplink adapter | YES — explicit `expiresAt` | configured Unix/MOP bridge does not prove the companion process/socket is live | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new uplink route selection |
| `MEDIA_PULL` | `PSDK_MANIFOLD` | `SPIKE-DJI-02`, `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, MEDIA_PULL)` — Manifold PSDK media adapter | YES — explicit `expiresAt` | product approval/config does not prove the camera-media/MOP port is presently usable | `TEMPORARY_RUNTIME_INEFFECTIVE`; no media pull |
| `WAYLINE_DELIVERY` | `PSDK_MANIFOLD` | `SPIKE-DJI-04`, `SPIKE-DJI-06`, `SPIKE-DJI-07` | YES | YES | `EDGE_ROUTE_PORT(edgeDeviceId, WAYLINE_DELIVERY)` — Manifold PSDK wayline adapter | YES — explicit `expiresAt` | configured local socket does not prove the PSDK companion can accept the no-start wayline operation | `TEMPORARY_RUNTIME_INEFFECTIVE`; no new wayline delivery |

#### 8.5.3 configured deployment rule

`configuredDeploymentMatches`는 **모든 12개 activation/runtime evaluation에 필수**다.

1. activation key의 organization/site/gatewayDeviceId/edgeDeviceId가 current trusted
   `AcquisitionDeploymentProfileV1`과 exact-match해야 한다. profile이 요구하는 두 device
   identity는 서로 달라야 한다(`acquisition/models.py:220-262`).
2. route의 §8.4 required equipment roles와 exact equipment scope/build가 operator-managed
   inventory 및 activation snapshot과 일치해야 한다. self-report로 scope를 교체하지 않는다.
3. integration path, canonical capability, allowed transport, runtime build, policy scope,
   mappingVersion, gateVersion 및 selected port binding이 exact-match해야 한다. wildcard/alias/
   “latest” fallback은 없다.
4. activation은 이 configured deployment snapshot의 canonical digest를 pin한다. current
   configured snapshot이 달라지면 observation 유무와 무관하게 match는 false이고 authority
   scope change 절차가 affected activation을 durable `SUSPENDED`로 fence한다.
5. route에서 사용하지 않는 component도 activation key의 deployment context로는 일치해야
   하지만 live observation subject가 되지는 않는다. 예를 들어 `MANIFOLD_DIRECT`의 current
   subject는 Edge port이고 RC heartbeat가 아니다.

#### 8.5.4 minimum CAP-5 observation record

CAP-5가 구현한 canonical `RuntimeRouteObservationV1`은 최소한 다음을 가져야 한다.

```text
observationId
organizationId
siteId
configuredDeploymentDigest
subjectKind = GATEWAY_ROUTE_PORT | DOCK_ROUTE_PORT |
              EDGE_ROUTE_PORT | GATEWAY_EDGE_ROUTE_PORT
subjectDeviceIds                         # exact gateway/edge IDs required by subjectKind
subjectPortId                            # capability-specific adapter/port identity
integrationPath
canonicalCapabilityId
equipmentScopeDigest
runtimeBuildDigest
availability = REPORTED_AVAILABLE | REPORTED_UNAVAILABLE | UNKNOWN
observedAt
expiresAt
freshnessPolicyId
freshnessPolicyDigest
producerPrincipalId
producerPrincipalKind
sourceObservationRef                    # existing snapshot/event provenance when adapted
```

Observation은 audit/replay 가능한 append-only record로 보존할 수 있지만 runtime authority는
`observedAt <= now < expiresAt`에서만 존재한다. 기존 `ConnectivitySnapshotV1` adapter는 현재
계약의 최대 5분 TTL과 explicit `expiresAt`을 그대로 사용한다
(`acquisition/models.py:283-323`). non-gateway subject에는 새 수치를 발명하지 않는다. CAP-5는
Core-owned versioned freshness policy가 발급한 `freshnessPolicyId/digest`와 explicit
`expiresAt`을 요구한다. 이 identity는 해당 `OperationalCapabilityActivation`이 pin한
`freshnessPolicyId` **및** `freshnessPolicyDigest`와 각각 exact-match해야 한다. 단순히 known/
supported policy라는 것만으로는 부족하며, 어느 하나라도 다르면 `CurrentRuntimeReady=false`다.
policy가 없거나 unknown이어도 observation은 current가 아니다. Core
restart는 record를 replay할 수 있으나 `expiresAt`을 재기준화하거나 연장하지 않는다.

Core가 지원하는 non-gateway freshness policy는 ID/digest만 있는 이름표가 아니라 다음
정확한 `RuntimeRouteFreshnessPolicyV1` 내용으로 등록한다.

```text
schemaVersion = 1.0
freshnessPolicyId
observationTtlSeconds                 # 1..300, exact validity window
minimumRefreshMarginSeconds           # >0 and < observationTtlSeconds
freshnessPolicyDigest                 # 위 네 canonical field의 SHA-256
```

`freshnessPolicyDigest`는 digest 필드 자신을 제외한 위 canonical policy payload에서 계산한다.
Core ingress는 policy ID/digest exact match에 더해
`expiresAt - observedAt == observationTtlSeconds`를 검사한다. interval이 더 짧거나 길어도
다른 의미의 policy이므로 거부한다. ID가 unknown이거나 legacy ID/digest-only entry라서 window를
알 수 없으면 default TTL을 추정하지 않고 observation을 거부한다.

`minimumRefreshMarginSeconds`는 authority TTL과 별개인 명시적 운영 cadence 하한이다. Gateway
runner는 같은 policy에 pin된 `freshnessTtlSeconds`와 `minimumRefreshMarginSeconds`를 받아
`pollIntervalSeconds + minimumRefreshMarginSeconds <= freshnessTtlSeconds`일 때만 기동한다.
이는 임의 percentage가 아니며, transport timeout 자체를 authority TTL에 더하거나 성공을
보장하지 않는다. Core가 소유한 policy 내용과 Gateway 배포 값이 달라지면 digest/ingress에서
fail-closed한다.

같은 exact subject key의 새 observation은 causal append 순서와 nondecreasing `observedAt`을
따른다. out-of-order, duplicate/conflicting ID, identity/scope mismatch는 해당 prerequisite를
fail-closed한다. `REPORTED_UNAVAILABLE`과 `UNKNOWN`은 available로 fallback하지 않는다.

#### 8.5.5 outage, reconnect and authority classification

- observation 만료, unavailable, 미수신, self-reported identity mismatch는
  `TEMPORARY_RUNTIME_INEFFECTIVE`다. durable approval/activation을 mutate하거나 suspend하지
  않는다.
- reconnect 뒤 fresh exact matching observation이 생기면 **기존 activation이 여전히 current이고
  모든 durable authority prerequisite가 유효한 경우에만** runtime effectiveness가 회복된다.
- operator-managed configured deployment identity/equipment/build가 실제로 변경된 것은 transient
  self-report mismatch와 다르다. 이는 authority scope invalidation이며 affected activation을
  durable `SUSPENDED`로 fence한다.
- 서버 관측 소실은 새 Core/Gateway route 선택을 막지만, 이미 발급된 locally valid signed
  Mission Contract의 Edge 실행 권위를 소급 취소하지 않는다.

| Change | Classification | Recovery |
|---|---|---|
| A. required evidence revoked | `DURABLE_AUTHORITY_SUSPENSION` | 새 evidence/approval과 새 activation authorization |
| B. product approval revoked | `DURABLE_AUTHORITY_SUSPENSION` | 새 approval과 새 activation authorization |
| C. configured hardware/firmware authority scope invalidated | `DURABLE_AUTHORITY_SUSPENSION` | 새 exact scope approval과 새 activation authorization |
| D. pinned mapping/gate authority invalidated or interpreter unsupported | `DURABLE_AUTHORITY_SUSPENSION` | supported version으로 explicit requalification/approval/activation; 단순 새 version 발급은 old interpreter를 자동 무효화하지 않음 |
| E. current runtime observation missing/stale/unavailable | `TEMPORARY_RUNTIME_INEFFECTIVE` | fresh exact matching observation; 새 human activation 불필요 |

#### 8.5.6 path-specific attack check

- `MSDK_FIELD / EDGE_DOWNLINK`: configured MOP와 device IDs만으로 field bridge process와 Edge
  ingress가 살아 있다고 추정하면 stale bridge로 dispatch할 수 있으므로 pair observation이
  필요하다.
- `PSDK_MANIFOLD / WAYLINE_DELIVERY`: configured Unix socket/PSDK qualification은 companion
  process가 지금 no-start upload를 받는다는 뜻이 아니므로 Edge route-port observation이
  필요하다. 관측 소실은 이미 발급된 mission 실행을 취소하지 않는다.
- `DJI_DOCK / WAYLINE_DELIVERY`: Dock가 inventory에 존재하거나 generic online이어도 wayline
  service가 준비됐다는 뜻이 아니므로 capability-specific Dock port observation이 필요하다.
- `DJI_CLOUD / EDGE_UPLINK`: RC 인터넷/gateway heartbeat만으로 Pilot/cloud uplink adapter의
  typed-operation readiness를 추정하지 않는다.
- `MANIFOLD_DIRECT / MEDIA_UPLOAD`: SIM, certificate pin, endpoint config만으로 Edge media uploader
  process/session 가용성을 추정하지 않는다.
- `DJI_DOCK / MEDIA_PULL`: Dock generic heartbeat와 media service/aircraft-media session은 다른
  사실이므로 capability-specific observation이 필요하다.

따라서 모든 `YES` row에서 configuration alone은 부족하다. 현재 `NO` row는 없다. 미래에
offline/preloaded capability를 `NO`로 추가하려면 새 mapping/gate version과 그 route가 현재
endpoint 관측 없이도 안전하게 동작한다는 별도 product decision이 필요하다.

## 9. Exact persistent scopes와 record contract

### 9.1 authority applicability keys

record는 immutable ID로 식별되고, 권위 적용 범위는 다음 canonical tuple로 판정한다.

- **A. field/route evidence verification key**:
  `(canonicalCapabilityId, sourceCapabilityId, integrationPath,
  equipmentScopeDigest, testBuildDigest, policyScopeId, mappingVersion)`.
  이는 KSI product qualification 범위이며 organization/site 전역이 아니다. 시험에 쓴
  organization/site/physical device는 `testedDeploymentRef` provenance로만 남아 다른
  equipment scope를 승인하지 못한다.
- **B. product/HIL approval key**:
  `(canonicalCapabilityId, supportMatrixDigest, productBuildDigest,
  policyScopeId, mappingVersion, gateVersion)`. `supportMatrixDigest`는 승인된
  `(integrationPath, equipmentScopeDigest, required qualification IDs/digests)`의 정렬된
  canonical snapshot이다. approval은 KSI product-global이고 tenant-specific하지 않다.
- **C. operational activation key**:
  `(organizationId, siteId, gatewayDeviceId, edgeDeviceId, integrationPath,
  canonicalCapabilityId, equipmentScopeDigest, runtimeBuildDigest,
  policyScopeId, mappingVersion, gateVersion)`. physical deployment authority는 이 tuple을
  벗어나지 않는다.
- **D. suspension/revocation key**: generic scope 추정이 아니라
  `(targetKind, targetRecordId, targetScopeDigest)`다. evidence revocation은
  `evidenceRecordId`, approval revocation은 `approvalRecordId`, activation suspension 또는
  revocation은 `activationAuthorizationId`를 정확히 target한다. prerequisite revocation
  decision은 영향받은 current activation ID의 정렬된 전체 목록을 함께 가진다.

동일 applicability key의 여러 history record는 timestamp가 아니라 explicit
`supersedesRecordId`/target relation으로 연결한다. organization dimension을 approval에 넣거나
activation에서 빼는 식의 scope collapse는 금지한다.

### 9.2 `CapabilityEvidenceRecordV1`

필수 필드:

- `evidenceRecordId`, `canonicalCapabilityId`, `sourceCapabilityId`, `mappingVersion`.
- `integrationPath`, complete `equipmentScope`, `equipmentScopeDigest`, `testBuildDigest`,
  `policyScopeId`.
- `evidenceType` (`FIELD`, `HIL`, `REGRESSION`, `VENDOR_DECLARATION` 중 하나). vendor declaration은
  qualification authority가 없고 별도 semantic projection으로만 읽는다.
- immutable `evidenceArtifactRef`, lowercase `sha256:<64hex>` `evidenceDigest`, 재현 가능한
  `procedureRef`/`procedureDigest`.
- `performerPrincipalId`와 `verifierPrincipalId`, `performedAt`, `verifiedAt`.
- qualification-capable evidence의 `verificationResult` = `QUALIFIED`, `NOT_QUALIFIED`,
  `BLOCKED`; `validUntil`(UTC, `verifiedAt`보다 뒤).
- optional `testedDeploymentRef` = exact organization/site/gateway/edge device IDs. 이는
  provenance이지 approval scope가 아니다.
- optional `supersedesEvidenceRecordId`; revocation은 원본 수정이 아니라 별도 target event다.

`verifierPrincipalId`는 authenticated `OPERATOR` principal이다. performer와 동일 principal인 evidence는
수집은 가능하지만 product approval의 유일한 evidence가 될 수 없다. evidence record 자체는
`APPROVED`를 만들지 않는다.

### 9.3 `ProductCapabilityApprovalRecordV1`

필수 필드:

- `approvalRecordId`, `canonicalCapabilityId`, `mappingVersion`, `gateVersion`.
- complete `supportMatrix`와 `supportMatrixDigest`, `productBuildDigest`, `policyScopeId`.
- mapping entry가 요구하는 모든 `qualificationRecordId`와 각 immutable record digest.
- `evidenceSetDigest` = 위 qualification reference 정렬 목록의 canonical digest.
- `approverPrincipalId`, `approvedAt`, `validUntil`, `decision=APPROVED`.
- optional `supersedesApprovalRecordId`; revoke는 별도 target event.

approver는 authenticated human `OPERATOR`, `Role.ADMIN`, `Permission.CAPABILITY_PRODUCT_APPROVE`를
만족해야 한다. `approverPrincipalId`는
`performerPrincipalId`, `verifierPrincipalId`, `SpikeEvidence.operator`, gateway/device identity에서
추정하지 않는다. 최소한 evidence performer와 product approver는 달라야 한다. approval은
explicit support matrix에만 적용되며 새 hardware, firmware, build, path를 wildcard로 포함하지
않는다.

### 9.4 `OperationalCapabilityActivationRecordV1`

필수 필드:

- 새 activation마다 새 `activationAuthorizationId`와 command `operationId`.
- §9.1 C의 complete `activationScope`와 `activationScopeDigest`.
- exact `approvalRecordId`, `approvalRecordDigest`, `supportMatrixDigest`, `evidenceSetDigest`와
  selected route의 sorted `qualificationReferences`(`qualificationRecordId` + digest).
- trusted Core/operator config의 complete `configuredDeployment` snapshot과
  `configuredDeploymentDigest`. Snapshot은 source configuration record/revision,
  organization/site/gateway/edge identities, exact route/equipment/runtime-build/policy/version을
  포함하며 self-report에서 만들지 않는다.
- `freshnessPolicyId`와 `freshnessPolicyDigest`. 이 pair는 activation prerequisite identity이며
  CAP-5 observation의 같은 두 필드와 exact-match해야 한다.
- `prerequisiteSetDigest`: approval ID/digest, approval evidence/support-matrix digest, selected
  qualification references, complete activation scope, configured deployment digest,
  freshness-policy ID/digest의 canonical witness digest. transient observation은 포함하지 않는다.
- `activatingPrincipalId`, `activatedAt`, `validUntil`, `effectiveState=ACTIVE`.
- optional `supersedesActivationAuthorizationId`; suspend/revoke는 별도 exact-target event다.

activator는 authenticated human `OPERATOR`, `Role.ADMIN`, `Permission.CAPABILITY_ACTIVATE`를
모두 만족해야 한다. transient heartbeat/snapshot ID는 prerequisite digest에 넣지 않는다.
그것은 매 route 사용 시 별도로 current여야 하며 5분마다 새 activation을 만들지 않는다.
feature flag/config-ready는 runtime gate로 계속 검사하되 activation authority로 역추정하지
않는다.

`CapabilityActivationSuspendedV1`은 target activation ID, scope digest, suspension reason,
triggering evidence/approval/scope record, suspending principal 또는 deterministic policy actor,
`suspendedAt`을 가진다. `CapabilityActivationRevokedV1`은 영구 종료다. prerequisite 복구 후
reactivation event로 old ID를 되살리는 형식은 금지한다. 반드시 새
`activationAuthorizationId`의 새 activation record를 append한다.

evidence revocation, product/HIL approval revocation, trusted hardware/firmware configured-scope
invalidation은 각각 영향받는 current activation 전부를 같은 authority-store lock 아래에서
계산하고, prerequisite decision과 정렬된 `CapabilityActivationSuspendedV1` 집합을 **한
append/fsync compound decision**으로 기록해야 한다. replay는 이 suspension을 terminal fence로
복원한다. prerequisite restoration, restart 또는 replay 순서 재구성만으로 old ID가 current가
될 수 없다. legacy activation에 ID/prerequisite provenance가 없으면 §6.6대로
`INACTIVE_LEGACY_UNATTESTED`이며, 새 explicit activation 전에는 operational authority가 없다.

## 10. mappingVersion과 gateVersion

- `mappingVersion = ksi-dji-capability-map-v1`은 evidence, approval, activation, 관련
  revoke/suspend event에 저장한다.
- `gateVersion = ksi-capability-gate-v1`은 approval, activation, 관련 revoke/suspend event에
  저장한다. evidence는 mapping 의미만 고정하므로 gateVersion이 필요 없다.
- mappingVersion은 “어떤 source qualification 집합이 canonical/path approval에 필요한가”를,
  gateVersion은 “approval·activation·liveness·config를 어떤 AND 조건으로 operational
  projection하는가”를 정의한다. 서로 대체하지 않는다.
- replay는 record에 저장된 exact interpreter로 검증한다. 새 code가 old record를 최신
  mapping/gate로 재해석하지 않는다.
- old interpreter를 계속 지원하면 historical authority는 그 old semantics와 expiry 안에서만
  유효할 수 있다. interpreter가 없거나 version이 unknown이면 해당 capability/scope를
  `BLOCKED_UNSUPPORTED_VERSION`으로 격리한다.
- mapping 또는 gate를 바꿀 때 기존 approval/activation을 mutate하지 않는다. 새 version의
  qualification applicability 확인, 새 approval, 새 activation이 명시적으로 필요하다. 단순
  software upgrade나 version alias로 authority를 migration하지 않는다.

`ksi-capability-gate-v1`의 operational AND rule은 §13.2와 동일하며 별도 자유 형식 정책으로
덮어쓸 수 없다.

## 11. Capability authority journal

### 11.1 선택

Core가 **하나의** `capability-authority.jsonl` logical journal과 store를 소유한다. evidence,
qualification, approval, activation, suspension/revocation을 한 single-writer lock과 한 replay
순서에서 처리해야 prerequisite revocation과 affected activation suspension 목록을 한
append/fsync decision으로 결속할 수 있기 때문이다. existing `DurableJournal`의 short-write,
file/parent fsync, flock single-writer, torn-tail, sealed/replay primitives를 그대로 사용한다
(`durable_journal.py:1-48`, `:304-377`). database나 분산 lock은 추가하지 않는다.

기존 `acquisition-connectivity.jsonl`의 gateway observation은 그대로 두고 CAP-5 projection 시
§8.5.4의 exact route observation으로 검증·적응한 read-only input으로 합성한다. PSDK,
Manifold Direct, MSDK bridge subject는 Gateway receipt에서 추정하지 않고 별도 인증된
route-observation ingress가 필요하다. 어느 observation도 capability authority journal로
import하거나 approval/activation event로 변환하지 않는다. Gateway integration receipt journal도
그대로이며 authority journal로 import하지 않는다.

### 11.2 event envelope와 kinds

모든 event는 다음 envelope를 가진다.

```text
schemaVersion = "1.0"
eventId
operationId
kind
occurredAt
actorPrincipalId
actorPrincipalKind
payload
payloadSha256
```

`payloadSha256`는 **full canonical envelope**(`schemaVersion`, `eventId`, `operationId`,
`kind`, `occurredAt`, `actorPrincipalId`, `actorPrincipalKind`, `payload`)의 canonical JSON
hash이며, `payloadSha256` 자체만 제외한다. event ID와 operation ID는 path-safe opaque ID다. event kinds는
정확히 다음이다.

- `capability-evidence-recorded`
- `capability-evidence-revoked`
- `capability-product-approved`
- `capability-product-approval-revoked`
- `capability-activation-authorized`
- `capability-activation-suspended`
- `capability-activation-revoked`

evidence supersession은 새 `capability-evidence-recorded`의 explicit predecessor로 표현한다.
“reactivated” mutation/event는 두지 않고 새 `capability-activation-authorized`가 새 ID를
발급한다. prerequisite revoke event payload는 revoke target과 `affectedActivationIds` 및 각
suspension reason을 함께 담는 compound decision이다. store lock 아래 current projection을
확인하고 그 record 하나를 append/fsync한 뒤 revocation과 suspension을 동시에 투영한다.

`payloadSha256` tamper 회귀는 구현 테스트로 이미 고정되어 있다.
`tests/contract/test_capability_authority.py::test_payload_digest_corruption_isolates_attributable_chain` 과
`tests/contract/test_capability_runtime_projection.py::test_observation_journal_tamper_fails_closed_on_recovery`.

### 11.3 idempotency, replay, corruption

- `operationId`가 command idempotency identity다. first append의 request digest와 결과 event를
  memory index와 replay index에 보관한다.
- same `operationId` + same canonical command digest는 기존 event/result를 반환하고 새 event를
  append하지 않는다. same operation ID + different digest는 `IDEMPOTENCY_CONFLICT`다.
- duplicate `eventId`, reused record ID, missing predecessor, double supersession, invalid transition,
  incomplete required-source set은 corruption/conflict이고 timestamp로 덮지 않는다.
- replay는 file order가 causal order다. 모든 record digest, mapping/gate interpreter,
  prerequisite digest, target relation을 다시 검증하고 live execution과 같은 projection을
  만들어야 한다.
- structurally valid event가 한 canonical capability/scope에 귀속되지만 malformed provenance,
  unknown version, contradiction이 있으면 그 chain만 `BLOCKED_CORRUPT` 또는
  `BLOCKED_UNSUPPORTED_VERSION`으로 격리한다.
- JSON parse/top-level corruption처럼 scope를 식별할 수 없으면 capability authority subsystem
  전체를 sealed하고 **모든** `/capabilities` catalog projection과 operational projection을
  false로 만든다. 다른 Core domain을 capability seed로 대체해 기동하지 않는다.
- torn tail은 기존 `DurableJournal` 정의대로 ACK되지 않은 record이며 제거 후 replay한다.

## 12. Authority transition, downgrade, revocation, staleness

| Change | Immediate projection | Durable suspension? | New evidence? | New approval? | New activation? |
|---|---|---|---|---|---|
| evidence `validUntil` 만료 | affected route/runtime false; catalog approval non-current | old activation은 pinned expired prerequisite 때문에 영구 비유효; reconciliation이 suspension append | 예 | 예 | 예 |
| evidence explicit revoke/failure | affected route/runtime와 catalog false | **예**, same compound decision | 예 | 예 | 예 |
| product approval expiry | catalog/runtime false | old activation은 영구 비유효; reconciliation이 suspension append | policy에 따라 | 예 | 예 |
| product approval revoke | catalog/runtime false | **예**, same compound decision | 필요 원인에 따라 | 예 | 예 |
| configured hardware/firmware/build scope change | old-scope runtime false | binding change command가 affected activation을 suspend | exact new scope 예 | 예 | 예 |
| transient self-reported hardware/firmware mismatch | runtime false, authority records 유지 | 아니오; self-report alone은 revocation authority가 아님 | 아니오 | 아니오 | observation 회복만으로 가능하나 exact configured scope가 계속 같아야 함 |
| mappingVersion change | old interpreter가 있으면 old semantics 유지; 없으면 false | migration command 전까지 old authority mutate하지 않음 | 새 mapping applicability 필요 | 예 | 예 |
| gateVersion change | old interpreter가 있으면 old semantics 유지; 없으면 false | migration command 전까지 old authority mutate하지 않음 | policy에 따라 | 예 | 예 |
| runtime route observation expiry/unavailable | runtime false; catalog 유지 | 아니오; `TEMPORARY_RUNTIME_INEFFECTIVE` | 아니오 | 아니오 | fresh exact matching observation만으로 기존 current activation 재사용 가능 |
| activation explicit suspend/revoke | runtime false; catalog 유지 | 이미 durable event | 아니오 | current면 불필요 | **예**; suspend 후에는 새 ID 필요 |
| feature flag/config unavailable | runtime false; catalog 유지 | 아니오; emergency/config gate | 아니오 | 아니오 | flag 복구 시 activation이 여전히 current일 때만 가능 |

시간 만료는 wall-clock projection에서 즉시 false여야 하므로 reconciliation append를 기다리지
않는다. 더 중요한 fencing은 activation이 prerequisite record IDs/digests를 pin한다는 점이다.
새 evidence나 approval은 다른 digest이므로 old activation과 일치하지 않아 자동으로 다시
true가 될 수 없다. explicit revoke는 affected activation의 durable `SUSPENDED`를 같은 decision에
반드시 포함한다.

## 13. Authoritative projections와 `/capabilities`

### 13.1 현재 public endpoint의 정확한 의미

현재 `/capabilities`에는 organization/site/device 입력이 없으므로 특정 deployment의
“지금 operationally usable”을 진실하게 계산할 수 없다. 따라서 기존 public shape의
`state=VERIFIED`는 오직 **product catalog approved** compatibility serialization이다. 아래
catalog projection이 true일 때만 반환한다.

```text
CatalogVisible(capability) =
  supported mappingVersion
  AND supported gateVersion
  AND current, unexpired ProductCapabilityApproval
  AND every required qualification in its pinned support matrix is current
  AND exact evidence/equipment/build/policy scope matches
  AND no unresolved blocker/revocation/corruption
```

응답은 현재처럼 canonical ID/title/legacy state만 공개하고 tenant, device, firmware, evidence
URI/digest를 노출하지 않는다. public serialization의 `VERIFIED`는 approval을 **표현**할 뿐
생성하지 않는다. legacy 입력을 그대로 echo해서 catalog에 넣는 것은 금지한다.

### 13.2 scoped operational projection

runtime과 향후 authenticated scoped view는 durable authority와 current runtime state를 서로
다른 predicate로 계산한다.

```text
DurableAuthorityValid(scope, capability, route, now) =
  CatalogVisible(capability)
  AND exact support-matrix route/equipment/build/policy match
  AND current activationAuthorizationId for exact organization/site/device scope
  AND activation pins current approval + every required qualification digest
  AND activation mappingVersion/gateVersion are supported and exact-match
  AND activation is unexpired and not SUSPENDED/REVOKED
  AND no newer prerequisite revocation/scope invalidation

CurrentRuntimeReady(scope, capability, route, now) =
  route is one exact row in §8.5.2
  AND configuredDeploymentMatches(scope, route)
  AND feature flag ON
  AND selected port configuration ready
  AND allowed transport + exact route-port binding match
  AND (
        requiresCurrentRuntimeRouteObservation(route) = NO
        OR (
             requiresCurrentRuntimeRouteObservation(route) = YES
             AND one exact matching RuntimeRouteObservation is REPORTED_AVAILABLE
             AND observation.observedAt <= now < observation.expiresAt
             AND observation.freshnessPolicyId = activation.freshnessPolicyId
             AND observation.freshnessPolicyDigest = activation.freshnessPolicyDigest
             AND the exact pinned freshness policy interpreter/digest is supported
           )
      )

OperationallyUsable(scope, capability, route, now) =
  DurableAuthorityValid(scope, capability, route, now)
  AND CurrentRuntimeReady(scope, capability, route, now)
  AND current Mission Contract/policy independently allows the behavior
```

`DurableAuthorityValid`의 입력은 capability authority journal의 qualification, approval,
activation, suspension/revocation과 pinned mapping/gate/policy/equipment/build digest다.
`CurrentRuntimeReady`의 입력은 trusted configured deployment, feature/config/transport/port와
TTL-limited observation이다. 현재 12행은 모두 observation `YES`다. unknown route, observation
policy 또는 subject는 connected로 default하지 않는다.

Declared support와 device/gateway self-report는 approval을 만들지 않는다. raw field
`VERIFIED`, legacy `VERIFIED`, catalog endpoint 응답 중 어느 것도 activation token이 아니다.
현재 public `/capabilities`에 scope가 없으므로 `OperationallyUsable=true`를 표시하지 않는다.
그 값이 필요하면 scoped runtime projection path가 위 projector를 호출해야 하며, 이
현 단계의 구현 범위는 기존 공개 schema/API를 변경하지 않고 `/v1/capability-runtime` scope를 이용해
runtime gate를 평가한다.

Runtime route observation은 audit journal에 durable할 수 있지만 TTL 이후 current authority가
없는 transient input이다. 관측 소실은 runtime을 즉시 false로 만들되 product approval이나
activation record를 삭제·suspend하지 않는다. fresh matching observation은 liveness만 회복하며
revoked evidence/approval, invalidated configured scope 또는 suspended activation은 회복시키지
않는다.

## 14. Legacy compatibility matrix

| Legacy persisted/observable form | Parse behavior | Safe internal state | May serialize externally as `VERIFIED`? | Evidence authority | Approval authority | Activation authority | Migration |
|---|---|---|---|---|---|---|---|
| Core memory/fixture `VERIFIED` without durable approval record | preserve source value as audit metadata | `LEGACY_UNATTESTED` | **아니오** | 없음 | 없음 | 없음 | explicit evidence→approval required |
| durable approved record projected through old Core enum | validate record IDs/digests/versions first | `ProductCapabilityApproval.APPROVED` | 예, catalog compatibility only | referenced qualifications only | 예 | 없음 | automatic parse; no authority synthesis |
| Core `SPIKE_REQUIRED` | parse | `APPROVAL_REQUIRED` | 아니오 | 없음 | 없음 | 없음 | none |
| Core `BLOCKED` | parse blocker metadata | `BLOCKED_LEGACY` | 아니오 | negative/audit only | 없음 | 없음 | explicit new evidence/approval |
| Acquisition receipt `VERIFIED` | parse inside snapshot and validate exact subject/path/binding | legacy `GatewayCapabilityObservation.REPORTED_AVAILABLE`; valid하면 `RuntimeRouteObservation` input | source wire may remain `VERIFIED`; public catalog로 복사 금지 | self-report only | 없음 | 없음 | exact compatibility adapter only |
| Acquisition `NOT_VERIFIED/BLOCKED` | parse | `UNKNOWN/REPORTED_UNAVAILABLE` | 아니오 | self-report only | 없음 | 없음 | automatic adapter mapping |
| Gateway route evidence `VERIFIED` with exact scope but no authority record | preserve as legacy candidate | `LEGACY_ROUTE_EVIDENCE_UNATTESTED` | gateway legacy reader만 원문 가능 | durable verifier provenance 없으므로 없음 | 없음 | 없음 | explicit evidence verification required |
| Gateway `NOT_VERIFIED/BLOCKED` | parse | `NOT_QUALIFIED/BLOCKED_LEGACY` | 아니오 | negative/audit only | 없음 | 없음 | explicit resolution |
| legacy feature flag/config `true` without activation ID | parse config input | `INACTIVE_LEGACY_UNATTESTED` | 해당 없음 | 없음 | 없음 | 없음 | explicit new activation |
| unknown canonical ID, mappingVersion, gateVersion | preserve raw record in quarantine | `BLOCKED_UNSUPPORTED_VERSION` | 아니오 | 없음 | 없음 | 없음 | explicit supported migration only |

legacy output을 `VERIFIED`로 유지할 수 있는 유일한 경우는 current durable approval projector가
true인 catalog serialization이다. 문자열 호환은 provenance나 permission을 부여하지 않는다.

## 15. Golden replay fixtures

각 fixture는 journal bytes, replay projection, restart-after-replay를 고정한다. 아래
`/capabilities` 값은 현재 public catalog의 `VISIBLE_AS_VERIFIED` 또는 `ABSENT`이고,
`runtime`은 exact scoped projector의 결과다.

| # | Fixture | `/capabilities` | Runtime | Required replay assertion |
|---:|---|---|---|---|
| 1 | valid evidence only | `ABSENT` | false | qualification current, approval 없음 |
| 2 | valid evidence + approval | `VISIBLE_AS_VERIFIED` | false | activation 없음 |
| 3 | evidence + approval + activation + live gates | `VISIBLE_AS_VERIFIED` | true | exact prerequisite digest match |
| 4 | evidence revoked after activation | `ABSENT` | false | compound revoke projects activation `SUSPENDED` |
| 5 | approval revoked after activation | `ABSENT` | false | compound revoke projects activation `SUSPENDED` |
| 6 | activation explicitly suspended | `VISIBLE_AS_VERIFIED` | false | catalog approval unchanged |
| 7 | new evidence/approval restored after suspension, no new activation | `VISIBLE_AS_VERIFIED` | false | old activation ID remains fenced |
| 8 | explicit new activation after restoration | `VISIBLE_AS_VERIFIED` | true | new activation ID, new prerequisite digest |
| 9 | runtime hardware/firmware mismatch | `VISIBLE_AS_VERIFIED` | false | other scope is not authorized |
| 10 | legacy Core `VERIFIED` without provenance | `ABSENT` | false | `LEGACY_UNATTESTED` |
| 11 | unsupported mappingVersion | `ABSENT` | false | affected chain `BLOCKED_UNSUPPORTED_VERSION` |
| 12 | unsupported gateVersion | `ABSENT` | false | affected chain `BLOCKED_UNSUPPORTED_VERSION` |
| 13 | approval missing/digest-mismatched provenance | `ABSENT` | false | affected chain `BLOCKED_CORRUPT` |
| 14 | clean restart replay of fixture 3 | `VISIBLE_AS_VERIFIED` | true | byte-identical logical projection before/after restart |
| 15 | duplicate same operationId + same command digest | unchanged from first event | unchanged | one durable logical event/result; no duplicate transition |
| 16 | conflicting supersession/revocation graph | `ABSENT` | false | affected chain isolated; never latest-timestamp wins |

Fixture 3/8의 runtime true는 synthetic contract fixture일 뿐 실제 DJI/HIL capability가 검증됐다는
주장이 아니다. 모든 production seed와 flags는 실제 evidence가 생길 때까지 OFF/
`NOT_VERIFIED`다.

### 15.1 CAP-4/CAP-5 connectivity contract tests

이 절의 경계는 현재 구현에서 `capability_router`, `runtime_projection`, `runtime_api` 조합이
지켜야 한다. 실행 가능한 회귀는 다음 contract 테스트로 이미 고정된다.

1. §8.5.2의 exact 12개 tuple이 각각 deterministic `YES`를 반환한다.
2. unknown/unmapped tuple은 connected/observation-not-required로 default하지 않고 거부된다.
3. configured deployment digest/device/equipment/build 중 하나라도 다르면 false다.
4. required observation이 없으면 runtime false다.
5. `now >= expiresAt` observation은 false다.
6. `REPORTED_UNAVAILABLE/UNKNOWN`은 false다.
7. exact scope의 fresh `REPORTED_AVAILABLE` observation만 runtime prerequisite를 만족한다.
8. 미래 mapping에 명시적 `NO` row가 추가되면 observation을 발명하지 않되 다른 runtime gate는
   그대로 검사한다. 현재 v1에는 `NO` row가 없다.
9. self-report는 qualification, approval 또는 activation을 생성·선택하지 못한다.
10. temporary observation outage는 activation을 mutate/suspend하지 않고 runtime만 false로 한다.
11. evidence/approval/configured-scope authority revocation은 durable suspension이며 temporary
    observation loss와 같은 recovery path를 쓰지 않는다.
12. restart/replay는 stale observation의 `expiresAt`을 연장하거나 available로 되살리지 않는다.

### 15.2 non-blocking CAP-3 test maintenance and strict staffing policy

다음은 independently verified non-blocking test-depth backlog이며 CAP-4 gate를 막지 않는다.

- blocked approval chain에서 `effective_approvals(scope) == ()`를 직접 assert.
- evidence/approval cross-kind `operationId` collision fixture.
- duplicate raw approval `eventId` replay fixture.

현재 staffing rule은 `CURRENT_STRICT_POLICY`다. CAP-2는 performer와 verifier가 달라야 하고,
CAP-3는 approver가 performer 및 verifier와 모두 달라야 하므로 세 principal이 구분된다. 이는
connectivity decision이 아니며 별도 product decision 없이는 완화하지 않는다.

## 16. Minimal implementation split

### CAP-1 — canonical registry, mapping/gate interpreters, compatibility adapter

- Invariant: unknown ID/version과 legacy `VERIFIED`는 authority를 만들지 않는다.
- Status: implemented in pre-R3 local software (`services/core/src/ksi_core/capability/registry.py`,
  `services/dji-gateway/src/ksi_dji_gateway/domain/capabilities.py`,
  `services/dji-gateway/src/ksi_dji_gateway/adapters/catalog.py`).
- Dependencies: 없음.
- Tests: `tests/contract/test_capability_contract.py`, `tests/contract/test_capability_activation_authority.py`의
  경로 매핑 및 legacy truth table 검증 하위 세트.
- Gate: mapping/gate golden data canonical digest가 결정적이며 production projection은 기존 방식 유지.

### CAP-2 — authority journal와 durable evidence qualification

- Invariant: exact scope와 independent verifier가 없는 evidence는 approval input이 아니다.
- Status: implemented in pre-R3 local software (`services/core/src/ksi_core/capability/authority_store.py`).
- Dependencies: CAP-1, existing `DurableJournal`.
- Modules: `services/core/src/ksi_core/capability/authority_store.py`; existing acquisition
  connectivity journal은 read-only dependency.
- Tests: `tests/contract/test_capability_authority.py`.
- Gate: fixtures 1, 11, 15, 16 green; no `/capabilities` promotion.

### CAP-3 — product/HIL approval authority와 catalog projection

- Invariant: evidence performer/self-report/legacy value가 product approval principal을 대신하지
  못한다.
- Status: implemented in pre-R3 local software (`services/core/src/ksi_core/app.py`,
  `services/core/src/ksi_core/capability/authority_store.py`).
- Dependencies: CAP-2, `Permission.CAPABILITY_PRODUCT_APPROVE`.
- Modules: authority store/projector + `/capabilities` adapter.
- Tests: `tests/contract/test_capability_approval_authority.py`, `tests/contract/test_capability_contract.py`;
  fixtures 2, 5, 10, 13.
- Gate: public catalog에는 current durable approval만 legacy `VERIFIED`로 표시.

### CAP-4 — activation authority and durable suspension/revocation

- Invariant: exact current activation authorization만 operational이고 prerequisite 복구가 old
  activation을 되살리지 않는다.
- Status: implemented in pre-R3 local software (`services/core/src/ksi_core/capability/authority_store.py`,
  `services/core/src/ksi_core/app.py`, `services/core/src/ksi_core/capability/runtime_projection.py`,
  `services/dji-gateway/src/ksi_dji_gateway/routing/capability_router.py`).
- Dependencies: CAP-3, deployment profile/binding reads, Gateway router inputs.
- Creation check: exact current evidence/approval, exact configured deployment snapshot/digest,
  §8.5.2 mapped row, pinned observation requirement와 freshness policy identity를 검증한다. **live
  observation 자체는 activation 생성조건이 아니다.** component가 offline이어도 operations
  authority를 미리 발급할 수 있으며 CAP-5 runtime projection은 observation이 생길 때까지 false다.
- Persists: activation authorization, exact scope/prerequisite-set digest, configured deployment
  digest, mapping/gate/policy/freshness-policy identity, expiry, compound suspension/revocation.
- Does not wire: observation ingress, current config read, Gateway route selection, Mission/device
  consumer 또는 `OperationallyUsable` runtime output.
- Modules: capability authority store와 durable-authority projector (`services/core/src/ksi_core/capability/authority_store.py`).
- Tests: `tests/contract/test_capability_activation_authority.py` (activation scope, compound revoke+suspend,
  new-ID reactivation, restart, hardware/firmware mismatch, exact 12-row/unknown tuple fail-closed),
  fixtures 3, 4, 6~9, 14의 durable half.
- Gate: durable authority fixtures green; flags remain OFF. HIL 또는 runtime enable을 뜻하지 않는다.

### CAP-5 — authenticated runtime observation and scoped projection

- Invariant: public catalog response alone can never authorize mission behavior.
- Status: implemented in pre-R3 local software (`services/core/src/ksi_core/capability/runtime_api.py`,
  `services/core/src/ksi_core/capability/runtime_projection.py`, `services/core/src/ksi_core/app.py`,
  `services/dji-gateway/src/ksi_dji_gateway/runtime_observation.py`,
  `services/dji-gateway/src/ksi_dji_gateway/routing/capability_router.py`).
- Dependencies: CAP-4.
- Owns: `RuntimeRouteObservationV1` authenticated ingress/adapters, current configured deployment read,
  observation freshness evaluation, `CurrentRuntimeReady`/`OperationallyUsable`, Gateway route preflight,
  Mission/device consumer integration와 audit reason codes.
- Observation loss: current runtime false only. CAP-5는 transient loss를 authority journal의 durable
  suspension으로 쓰지 않는다. authoritative config/equipment scope change는 CAP-4 suspension
  command로 전달한다.
- Modules: Gateway routing preflight, Core internal scoped projector, acquisition observation
  adapters, audit metrics/reason codes.
- Tests: `tests/contract/test_capability_runtime_projection.py`, `tests/contract/test_capability_runtime_api.py`,
  end-to-end fail-closed route selection, config/transport/binding mismatch,
  reconnect, restart/retry, tenant isolation, signed Mission Contract non-retroactivity.
- Gate: HIL-free software gate only. 실제 capability enable은 별도 external evidence/owner activation
  gate를 요구한다.

CAP-5는 다음 observation-contract 규칙을 강제한다.

1. `MANIFOLD_DIRECT/EDGE_UPLINK`와 `PSDK_MANIFOLD/EDGE_UPLINK`는 같은 device/capability라도
   `integrationPath`와 `subjectPortId`가 모두 다른 exact observation key다. 한 관측을 다른
   route에 재사용하지 않는다.
2. legacy `ConnectivitySnapshotV1` adapter의 `integrationPath`와 `subjectPortId`는 receipt가
   아니라 trusted deployment profile + selected `AdapterRuntimeConfig`/port registry에서
   unique하게 유도한다. exact one-to-one derivation이 안 되면 observation을 만들지 않는다.
3. organization identity는 authenticated principal/request scope와 trusted deployment profile의
   exact match에서 얻는다. legacy `"legacy"` sentinel은 tenant isolation 근거가 아니며 CAP-5
   operational projection에서 거부한다.
4. CAP-5 tests에는 wrong-route same-device/same-capability observation, future-dated observation,
   feature flag OFF, Mission policy denial을 포함한다.

위 네 항목은 CAP-4 persistence/runtime authority에 관측값을 넣지 않으며 CAP-5에서 구현한다.

이 분리는 public API/schema를 이 설계 작업에서 바꾸지 않으며, CAP-1부터
순서대로 각 단계가 fail-closed 상태로 배포 가능하다.

## 17. 명시적 non-goals와 외부 gate

- Worker TASK-1A/1B와 Mission TASK-2 correctness를 수정하거나 재설계하지 않는다.
- `VERIFIED` 문자열을 전역 검색·치환하지 않는다.
- Gateway/device self-report, vendor document, feature flag를 field evidence/product approval로
  승격하지 않는다.
- 실제 HIL/field evidence 없이 현재 DJI capability를 승격하거나 operational enable하지 않는다.
- database, distributed lock, unrelated journal redesign, public enum aesthetic rename을 하지 않는다.
- active mission 도중 capability revocation이 이미 발급된 signed Mission Contract에 미치는
  execution 정책은 Mission safety contract의 별도 작업이다. 이 문서는 신규 route 선택을 즉시
  차단하되 기존 계약 authority를 소급 삭제하지 않는다.
- raw evidence retention/license/access-control과 실제 approver staffing/provisioning은 구현·운영
  gate다. semantic/persistence schema를 다시 열 이유는 아니다.

## 18. Decision summary

connectivity의 미해결 product semantic decision은 없다. 현재 12개 route는 모두 exact current
runtime route observation을 요구하고, configured deployment exact-match도 모두 요구한다.
Gateway-only naming은 canonical `RuntimeRouteObservation` + legacy Gateway adapter로 해소했다.
실제 evidence, approver/activator credential
provisioning, HIL execution, feature activation은 의도적으로 외부 acceptance gate로 남아 있다.
그 부재는 local persistence software verification에는 영향이 없으며, 실운영 승격과 mission 운용은 계속 차단한다.

```text
CAPABILITY_CONNECTIVITY_CONTRACT = READY
CONNECTIVITY_12_ROW_TABLE = COMPLETE
CONFIGURED_DEPLOYMENT_RULE = READY
OBSERVATION_FRESHNESS_SEMANTICS = READY
TEMPORARY_VS_DURABLE_SUSPENSION = READY
CAP4_IMPLEMENTATION_GATE = READY
CAPABILITY_MAPPING = READY
CAPABILITY_EVIDENCE_PERSISTENCE = READY
CAPABILITY_APPROVAL_AUTHORITY = READY
CAPABILITY_ACTIVATION_AUTHORITY = READY
CAPABILITIES_PROJECTION = READY
CAPABILITY_PERSISTENCE_DESIGN = READY
CAPABILITY_PERSISTENCE_LOCAL_SOFTWARE_IMPLEMENTATION = READY
CAPABILITY_EXTERNAL_ACTIVATION_GATE = NOT_VERIFIED
CAPABILITY_HIL_FIELD_ACTIVATION_GATE = NOT_VERIFIED
CAPABILITY_DEPLOYMENT_CONFIG_GATE = NOT_VERIFIED
```
