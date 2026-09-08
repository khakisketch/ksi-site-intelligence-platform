# Mission Issuance Atomicity Corrective Contract

> 상태: local implementation and contract regression verified; deployment, production
> activation, physical HIL, and field acceptance remain NOT_VERIFIED/BLOCKED.
>
> 근거 감사: `docs/audit/02_INVARIANT_AUDIT.md`,
> `docs/audit/02_INVARIANT_AUDIT_CODEX_REVIEW.md`
>
> 설계 기준 코드: `41d9f55270581d9660664f6c23c65ab0d7af0a4a`
>
> 2026-09-03 correction closure: validated OCC/atomicity contract는 변경하지 않고,
> communication snapshot의 5-minute validity와 실제 issuance latency를 production
> activation 전에 대조하는 runtime gate를 명문화했다.

이 문서는 Site가 발급 도중 `SUSPENDED`로 바뀌어도 계약 단독과 KMZ 짝 발급이 durable
201로 끝나는 TOCTOU를 고치는 **원자성 계약**을 정의하고, Core의 local implementation과
contract regression이 이를 검증한 상태를 기록한다. 마지막 비원자 재조회는 해결책으로
채택하지 않는다. 이 local evidence는 deployment, production activation, physical HIL 또는
field acceptance를 증명하지 않으며 그 경계는 NOT_VERIFIED/BLOCKED로 유지한다.

## 작업 계약

- Requirement IDs: `REQ-MSN-101`, `REQ-MSN-104`, `REQ-ACQ-103`, `REQ-SEC-101`
- Owner module: Core의 Site/Mission/WorkOrder/Acquisition store와 Mission issuance router
- Acceptance criteria: 발급을 인가한 mutable prerequisite snapshot이 durable Mission append
  경계까지 동일할 때만 신규 Mission이 기록된다. 계약 단독과 KMZ 짝에 같은 commit
  primitive를 사용한다.
- Contracts affected: 후속 구현에서 internal authorization witness, Mission journal의
  request digest/witness, typed 409. 이 설계 작업에서는 변경 없음.
- Reference assets: `SiteStore`, `MissionStore`, `ObservationWorkOrder.version`,
  `ConnectivitySnapshotV1`, `DurableJournal`.
- Adoption decisions: 서명 전 cheap precheck와 append-only journal은 `ADOPT`; final authority가
  mission ID 중복만 검사하는 현재 `record_issuance()`는 `REPLACE`; store별 revision/snapshot은
  `ADOPT`; 장기 lock과 새 database는 `REJECT`.
- Files to change: 이 문서 하나.
- Tests: 후속 구현에서 두 HTTP surface barrier race, commit coordinator, journal replay,
  retry/crash/idempotency와 lock-order test.
- HIL or real-device assumptions: OCC 구현에는 없음. 다만 Acquisition issue gate를 production에
  활성화하기 전 §3.4의 representative runtime latency 측정이 필수이며, 비행·device write는
  하지 않는다.
- License/data implications: 없음. signed-but-unissued bytes는 durable authority가 아니며
  별도 보존하지 않는다.
- Rollback: 신규 발급 writer를 disable하고 기존 발급 조회는 유지한다. final atomicity gate를
  제거해 롤백하지 않는다.
- Invariants touched: `INV-011`의 signed contract durability, `INV-052`의 Site 상태별 발급,
  `INV-060`의 조직 격리를 강화한다
  (`docs/product/DOMAIN_INVARIANTS.md:295-317`, `:321-326`). Site 상태가 durability 경계에서
  여전히 유효하다는 것을 `INV-052`의 실제 강제 의미로 삼는다.

## 1. 현재 발급 transaction

### 1.1 공통 prerequisite와 현재 snapshot

`precheck_issuance()`는 journal 봉인, identifier, 조직 범위 Site 존재, siteFrame 일치,
mission ID 충돌, mission-type×Site-status를 순서대로 검사한다
(`services/core/src/ksi_core/mission_records.py:539-603`). `SiteLookupResult`는 같은 Site lock
스냅샷의 `site_frame`과 `status`만 담고 revision은 담지 않는다
(`mission_records.py:282-295`). 조립의 lookup도 `SiteStore.get_scoped()` 결과에서 이 두
값만 만든다(`services/core/src/ksi_core/app.py:859-873`).

Site의 상태 전이는 `SiteStore._lock` 안에서 before/after를 검사하고 Site journal을 append한
뒤 projection을 갱신한다(`services/core/src/ksi_core/sites.py:543-593`). 발급 precheck가
끝난 뒤에는 이 lock을 유지하지 않는다.

### 1.2 계약 단독 발급

`POST /v1/missions/contracts`의 실행 순서는 다음과 같다.

```text
auth(MISSIONS_ISSUE)
→ precheck_issuance(siteFrame, SiteStatus, missionId)
→ optional acquisition readiness
→ optional v1.3 site sequence reserve (durable)
→ Mission Contract build/sign
→ MissionStore.record_issuance
→ HTTP 201
```

실제 경로는 `services/core/src/ksi_core/mission_issuance.py:213-292`다. sequence reserve는
서명 전에 별도 journal에 기록되고(`:253-273`), 최종 Mission record는 signing 뒤에
기록된다(`:276-292`).

### 1.3 계약+KMZ 짝 발급

`POST /v1/missions/plans`의 실행 순서는 다음과 같다.

```text
auth(MISSIONS_ISSUE)
→ canonical request digest
→ precheck_issuance
→ optional WorkOrder APPROVED check + AcquisitionRun ensure
→ optional acquisition readiness
→ optional v1.3 site sequence reserve (durable)
→ route generation + KMZ build + Mission Contract signing
→ one MissionRecord append(contract + kmzSha256 + request/digest)
→ best-effort KMZ object persistence
→ WorkOrder/AcquisitionRun linkage reconciliation
→ HTTP 201
```

근거는 `services/core/src/ksi_core/mission_plans.py:762-920`이다. WorkOrder는 발급 전
`APPROVED`인지 검사하고 run을 보장한다(`mission_plans.py:682-719`). 발급 뒤 linkage가
실패하면 503/409를 주고 같은 요청 retry가 reconciliation path로 돌아온다
(`mission_plans.py:721-760`, `:796-852`).

짝의 authoritative durable record는 이미 **하나의** `MissionRecord`다. 이 record는 signed
contract, `kmzSha256`, route metadata, canonical plan request와 digest를 함께 가진다
(`mission_records.py:297-320`, `mission_plans.py:900-917`). KMZ object write는 Mission append
뒤의 best-effort cache이며 실패해도 issuance를 무효화하지 않는다
(`mission_plans.py:614-641`, `:917-919`).

### 1.4 현재 durability와 lock

`MissionStore.record_issuance()`는 `MissionStore._lock` 안에서 mission ID 중복과 Mission
journal append만 원자적으로 묶는다(`mission_records.py:425-481`). Site status나 그
revision을 다시 보지 않는다. Mission journal과 Site journal은 별도
`DurableJournal`이다(`app_assembly.py:141-154`). 각 journal은 `fsync`와 single writer를
보장하지만 서로 다른 journal 사이의 compare-and-append primitive는 없다
(`durable_journal.py:91-129`, `:304-377`).

따라서 현재 concurrency boundary는 각각의 HTTP call/store call이고, 신규 Mission의
durability boundary는 Mission journal append의 `fsync` 완료다. precheck와 이 boundary
사이에 Site transition이 실행 가능하다.

### 1.5 자동 Site transition

Processing worker가 job 상태를 성공적으로 바꾼 뒤 router는 별도의
`SpatialModelLifecycle.advance_for_job_status()`를 호출한다
(`processing_jobs.py:2457-2469`). Lifecycle은 `QUEUED`와 `SUCCEEDED`를 Site 전진으로
매핑하며(`spatial_model.py:263-278`), work store lock을 놓은 뒤 SiteStore를 호출해 nested
lock을 피한다(`spatial_model.py:305-319`). 수동 Site transition과 이 자동 transition은
모두 같은 `SiteStore._lock`을 통과하므로 권장 commit guard와 직렬화할 수 있다.

## 2. 요구 correctness invariant

정본 invariant는 다음이다.

> **Mission M은 M의 route/contract를 생성하고 발급을 인가하는 데 사용한 Site 및 기타
> mutable prerequisite witness가 M의 Mission journal durable append 경계에서도 현재일
> 때만 durably issued가 될 수 있다.**

이는 질문에 제시된 “A mission may be durably issued only if the site/mission prerequisite
state used to authorize issuance is still current at the durability boundary”와 동등하다.
단순히 append 직전에 값을 한 번 더 읽는 것은 비교와 append 사이에 다시 전이가 가능하므로
충분하지 않다. **비교와 Mission append가 prerequisite mutation과 같은 lock 경계로
직렬화되어야 한다.**

이미 발급된 Mission은 이후 Site 상태가 바뀌어도 과거 발급 사실을 잃지 않는다.
`INV-052`는 신규 issuance boundary를 제어하며, 과거 record replay를 현재 Site 상태로
재심사하지 않는다. 현재 precheck도 기존 mission ID는 현재 Site gate보다 먼저 처리한다는
원칙을 명시한다(`mission_records.py:556-562`, `:596-603`).

## 3. Authorization witness

두 발급 경로는 precheck 성공 시 internal `IssuanceAuthorizationWitness`를 받아야 한다.
이것은 public request가 제출하는 권한 주장이 아니라 Core store projection에서 유도한다.

```text
IssuanceAuthorizationWitness
  organization_id
  site_id
  site_issuance_revision
  site_status
  site_frame_digest
  request_digest
  optional work_order_id / version / cycle_number / status
  optional acquisition_profile_digest / snapshot_id / expires_at
  captured_at
```

### 3.1 Site revision

`site_issuance_revision`은 Site registration을 1로 하고 각 `site-transitioned` event마다 1
증가하는 per-Site 정수다. 현재 발급 gate가 읽는 mutable fact는 status이고 siteFrame은
등록 후 immutable projection이다. AOI와 model-age policy는 현재 mission precheck의
인가 입력이 아니므로 revision을 올리지 않는다. 향후 route authorization이 AOI를 읽으면
그 digest/revision을 witness에 추가해야 한다.

과거 Site journal을 replay하면서 registration/transition event를 세면 revision이
결정적으로 복원된다. 현재 replay가 event kind와 before/after 적법성을 순서대로 검사한다는
근거는 `sites.py:252-270`, `:342-372`다. 과거 record에 revision을 추정해 써넣거나 journal을
rewrite하지 않는다.

같은 status로 돌아오는 `A→B→A`도 revision이 달라져 stale route/signature를 막는다.
`updated_at`은 AOI/policy 변경에도 바뀌므로(`sites.py:374-431`) issuance revision 대신
사용하지 않는다.

### 3.2 WorkOrder witness

짝 발급이 WorkOrder를 사용하면 `work_order_id`, `version`, `cycle_number`, `APPROVED` 상태를
witness에 넣는다. WorkOrder projection은 이미 update마다 version+1을 replay에서 강제한다
(`observation_work_orders.py:118-162`). route/signing 중 approval·cycle이 변하면 commit은
거부한다.

### 3.3 Acquisition witness

issue gate가 켜져 있으면 readiness의 boolean/string만 저장하지 않고 현재 profile canonical
digest, unique `snapshot_id`, `expires_at`을 witness에 넣는다. Connectivity snapshot은
unique ID, device binding, 최대 5분 TTL을 이미 계약으로 가진다
(`acquisition/models.py:283-323`). Store는 profile 변경 시 기존 snapshot을 폐기하고,
out-of-order/reused snapshot을 replay와 live에서 거부한다
(`acquisition/store.py:52-83`, `:123-155`). commit 시점에도 같은 profile/snapshot이며
만료되지 않았고 readiness가 true여야 한다.

### 3.4 Production pre-activation runtime latency gate

위 commit-time snapshot validity 요구는 유지하며 완화하지 않는다. Acquisition issue gate를
production에서 enable하기 전에 representative 실제 issuance workload로 다음 end-to-end 구간을
측정해야 한다.

```text
authorization witness capture
→ route generation
→ KMZ/contract materialization과 기타 issuance pre-commit work
→ Ed25519 signing
→ conditional commit 진입 직전
```

측정에는 최소 route generation duration, signing duration, 그 밖의 queueing·KMZ build·canonical
serialization을 포함한 모든 pre-commit latency와 합계가 있어야 한다. 소형 happy-path 평균이
아니라 실제 운영에서 대표적인 worst-case AOI/waypoint/work-order 조합과 반복 분포를 사용한다.

```text
observed issuance pre-commit latency
  = route generation duration
  + signing duration
  + every other issuance pre-commit latency
```

판정 threshold를 새로 만들지 않는다. 유일한 기준은 기존 communication snapshot의 실제
validity window와 commit 시 `snapshot`이 unexpired여야 한다는 §3.3 규칙이다. 현재 계약의
snapshot TTL 상한은 5분(300초)이지만, 300초를 별도의 성공 budget이나 새 threshold로
간주하지 않고 각 witness가 기록한 실제 `expiresAt`까지 남은 시간으로 판정한다.

> **PRE-ACTIVATION RUNTIME GATE:** representative worst-case issuance가 기존 snapshot-validity
> 요구를 지키면서 신뢰성 있게 commit까지 완료할 수 있음을 **실제 route generation duration +
> signing duration + 그 밖의 issuance pre-commit latency** 실측으로 입증하지 못하면 production
> activation은 반드시 `BLOCKED`다. snapshot TTL을 우회하거나 commit expiry 검사를 제거하지
> 말고, operational/design issue를 먼저 해결한 뒤 다시 측정한다.

이 runtime gate는 feature flag가 OFF인 동안 OCC revision/witness/atomic commit 메커니즘 자체를
구현하거나 contract test하는 선행조건은 아니다. 단, representative worst-case latency가 기존
snapshot-validity 요구 안에서 신뢰성 있게 완료됨을 입증하지 못하면 feature activation은
operational/design issue가 해결될 때까지 반드시 `BLOCKED`다. 구현 완료와 production activation
evidence를 별도 상태로 기록한다.

runtime validation evidence는 각 대표 workload의 witness `capturedAt`/`expiresAt`, route generation,
KMZ/contract materialization, signing, queueing/serialization, conditional commit 진입 시각과 성공·
`ACQUISITION_WITNESS_STALE` 결과를 보존해야 한다. 별도의 숫자 threshold를 만들지 않으며, 각
실행이 기존 snapshot-validity predicate를 만족했는지만 판정한다. 이 evidence가 없거나
representative worst-case에서 반복적으로 predicate를 만족하지 못하면 feature가 disabled인
상태를 유지한다. OCC mechanism 구현·replay·contract test는 feature가 disabled인 동안 이 실측을
기다리지 않는다.

## 4. 선택지 비교

| 선택지 | Atomicity | Append-only 적합성 | Crash/retry | Signing latency·contention | Pair atomicity | Replay | Blast radius |
|---|---|---|---|---|---|---|---|
| Option A — validation부터 append까지 장기 lock | 충분 | 가능 | 단순 | route/KMZ/signing 동안 Site·WorkOrder·heartbeat를 막음 | 충분 | 단순 | 중간 |
| **Option B — revision/witness OCC + commit 시 짧은 lock** | **충분** | **Mission record 한 append 유지** | request digest로 멱등 | signing은 lock 밖, fsync 동안만 contention | **한 logical record** | witness와 revision 결정 재생 | 중간 |
| Option C — journal CAS/conditional append | 한 journal 내부만 가능 | Site/Mission 두 journal CAS가 현재 없음 | 새 cross-log protocol 필요 | 낮을 수 있음 | 별도 transaction 필요 | 복잡 | 큼 |
| Option D — reservation/issuance state machine | 충분하게 만들 수 있음 | reservation/revoke/expiry event 다수 | recovery 정책 복잡 | signing lock 없음 | reservation aggregate 필요 | 복잡 | 가장 큼 |
| Option E — 기존 primitive 그대로 | Mission ID 중복만 원자적 | 현재와 같음 | pair retry만 일부 해결 | 낮음 | record는 하나 | 현재 가능 | 낮지만 race 미해결 |

**선택: Option B.** 구현은 기존 store lock을 재사용하는 짧은 conditional commit coordinator로
한다. 이는 새로운 generic distributed transaction이나 database가 아니다. Option E의
`SiteStore._lock`, WorkOrder lock, Acquisition `RLock`, `MissionStore._lock`과 journal append를
재사용하되, 비교와 append를 한 critical section으로 묶는다.

## 5. 권장 commit contract

### 5.1 commit 순서

1. Cheap validation과 duplicate lookup을 수행하고 authorization witness를 캡처한다.
2. sequence가 필요한 v1.3은 기존처럼 reserve한다. 실패한 issuance의 sequence gap은
   허용하며 이미 signed contract의 sequence를 재사용하지 않는다.
3. route generation, KMZ build, signing을 lock 밖에서 수행한다.
4. `MissionIssuanceCommitter.commit(record, witness)`가 canonical 순서로 필요한 store lock을
   잡는다: `Site → WorkOrder(있을 때) → Acquisition(있을 때) → Mission`.
5. lock을 모두 보유한 상태에서 witness의 exact equality와 현재 readiness를 재검증한다.
6. 모두 같을 때만 Mission journal record를 append/fsync하고 Mission projection을 갱신한다.
7. lock을 해제하고 KMZ cache persistence 및 WorkOrder/AcquisitionRun linkage를 기존처럼
   idempotent reconciliation한다.

어떤 mutation path도 이 순서의 역방향으로 여러 lock을 잡지 않도록 contract test로
inventory한다. 현재 Site transition은 Site lock 하나, WorkOrder update는 WorkOrder lock 하나,
Acquisition observation은 Acquisition lock 하나, Mission append는 Mission lock 하나를 잡으므로
후속 구현 전에 reverse nested path가 없음을 구조 테스트로 고정한다
(`sites.py:561-593`, `observation_work_orders.py:89-172`,
`acquisition/store.py:123-155`, `mission_records.py:464-481`).

### 5.2 하나의 logical issuance record

계약 단독과 짝 발급 모두 **MissionRecord 한 건**이 issuance authority다.

- contract-only: signed contract + canonical issuance request digest + authorization witness.
- pair: signed contract + KMZ digest + canonical plan request/digest + authorization witness.

짝의 contract와 KMZ를 독립 조건부 record 두 건으로 만들지 않는다. 현재 한 MissionRecord가
이미 두 산출물을 digest로 결속한다(`mission_records.py:297-320`). KMZ bytes object와
WorkOrder link는 materialization/reconciliation이며 issuance authority가 아니다. object
write 실패가 발급을 취소하지 않는 현재 경계를 유지한다(`mission_plans.py:614-641`).

### 5.3 request idempotency

신규 contract-only MissionRecord에도 canonical `issuanceRequestDigest`를 기록한다. pair는
현재 `planRequestDigest` 관습을 유지한다. 같은 `missionId` retry는 다음과 같다.

- 같은 artifact kind + 같은 request digest: stored signed contract/pair를 HTTP 200으로
  반환하고 새 signing·append를 하지 않는다.
- 다른 digest 또는 artifact kind: 기존 `409 MISSION_ID_CONFLICT`.
- legacy contract-only record처럼 digest가 없으면 동일 요청이라고 추정하지 않고 409.

pair의 현재 same-digest 200 경로는 `mission_plans.py:774-776`, `:796-852`에 이미 있다.
이 관습을 contract-only로 확장하면 “append 성공 후 HTTP 응답 전 crash”를 안전하게
복구할 수 있다.

## 6. timing·failure별 필수 동작

1. **Site state가 signing 전에 변경** — expensive work를 조기에 중단할 수 있으면
   중단한다. 놓쳐도 final revision comparison이 409로 거부하며 Mission append는 없다.
2. **Signing 중 변경** — signing은 계속될 수 있으나 결과는 authority 없는 임시 bytes다.
   commit comparison 실패, Mission append 없음.
3. **Signing 뒤 append 전 변경** — final commit lock에서 revision mismatch, append 없음.
4. **state/version comparison 실패** — `409 ISSUANCE_PRECONDITION_CHANGED`와 typed subreason.
   signed bytes나 reserved sequence를 Mission으로 기록하지 않는다. 새 snapshot으로 다시
   요청해야 한다.
5. **Client retry** — 같은 mission ID+request digest가 이미 durable이면 stored result 200.
   durable record가 없으면 현재 prerequisite로 새 attempt를 시작하고 새 sequence를 받을 수
   있다.
6. **Signing 뒤 process crash** — Mission append가 없으므로 issued가 아니다. sequence gap은
   허용한다. retry는 새 attempt다.
7. **Durable append 뒤 HTTP response 전 crash** — issued다. restart replay 뒤 동일 retry는
   stored record 200, 다른 request는 409다.
8. **Restart replay** — Site revision은 Site journal event 순서에서 복원하고 Mission witness와
   request digest의 형식·내부 digest를 검증한다. 이후 Site 상태와 과거 witness가 다르다는
   이유로 과거 Mission을 거부하지 않는다.

Site transition이 Mission append의 `fsync`가 끝난 **뒤** 실행되는 것은 허용한다. invariant가
요구하는 것은 durability boundary까지의 currentness다. 이후 `SUSPENDED`는 새 Mission을
막지만 이미 발급된 signed contract의 별도 activation/execution 정책을 소급 변경하지 않는다.

## 7. 필요한 후속 변경

### 7.1 Internal API

- `precheck_issuance()`는 verdict만이 아니라 immutable witness를 반환한다.
- SiteStore는 lock 안에서 issuance revision과 frame/status snapshot을 읽고, commit 시
  expected revision을 비교하는 internal guard를 제공한다.
- WorkOrder/Acquisition store는 public mutable object를 우회해 lock 안에서 witness를
  비교하는 internal guard를 제공한다.
- MissionStore는 coordinator가 이미 prerequisite lock을 가진 상태에서 duplicate
  check→journal append→projection update를 수행하는 좁은 method를 제공한다.
- 두 router는 같은 `MissionIssuanceCommitter`를 사용한다.

store의 raw `_lock`을 router가 직접 다루지 않는다. coordinator와 store-owned guard가 lock
순서와 projection update를 캡슐화한다.

### 7.2 Mission journal

신규 record에 추가할 의미:

```json
{
  "issuanceRequestDigest": "sha256:...",
  "authorizationWitness": {
    "siteIssuanceRevision": 7,
    "siteStatus": "PATROL_READY",
    "siteFrameDigest": "sha256:...",
    "workOrder": null,
    "acquisition": null
  }
}
```

- witness는 record의 organization/site/request와 정확히 일치해야 한다.
- pair의 기존 `planRequestDigest`는 유지하고 `issuanceRequestDigest`와 동일 canonical payload
  정의를 공유한다.
- legacy record는 witness/request digest가 없음을 `None`으로 재생한다. 값을 추정하거나
  과거 journal을 rewrite하지 않는다.
- 신규 writer record의 witness 누락·digest 불일치·invalid revision은 replay에서
  fail-closed recovery error다.

### 7.3 Rejection과 observability

| subreason | 의미 |
|---|---|
| `SITE_ISSUANCE_REVISION_CONFLICT` | status/frame authorization snapshot이 바뀜 |
| `WORK_ORDER_REVISION_CONFLICT` | version/cycle/approval이 바뀜 |
| `ACQUISITION_WITNESS_STALE` | profile/snapshot 변경 또는 commit 시 expiry |
| `MISSION_ID_CONFLICT` | 같은 ID의 다른 요청/종류 |
| `STORE_UNAVAILABLE` | 어느 required journal이 sealed |

다른 조직 resource는 계속 404와 동등하게 접고 revision 값을 노출하지 않는다
(`INV-060`, `DOMAIN_INVARIANTS.md:321-326`). Metric은 issuance attempt, precheck reject,
commit-conflict subreason, signing duration, commit lock duration, sequence gap, idempotent replay,
post-commit reconciliation failure를 센다. 로그에는 request digest와 revision을 안전하게
축약하고 signed contract/private key는 남기지 않는다.

## 8. tests

기존 테스트는 Site 상태별 gate와 pair idempotency를 유지한다. 관련 inventory는
`tests/contract/test_mission_site_status_gate.py`, `test_mission_records.py`,
`test_mission_plans.py`, `test_sites_api.py`이며, 현재 pair same-digest retry는
`mission_plans.py:796-852`가 구현 근거다.

후속 구현은 최소 다음을 추가한다.

1. contract-only signing barrier에서 Site→`SUSPENDED`: append 0, typed 409.
2. pair route/signing barrier에서 Site→`SUSPENDED`: append 0, typed 409.
3. Site `A→B→A`: status는 같아도 revision conflict.
4. 자동 processing Site transition과 issuance commit의 경쟁: 선형화 순서별 기대 결과.
5. WorkOrder version/cycle/status 변경 race와 acquisition snapshot/profile/expiry race.
6. 비교를 통과한 뒤 append 전에 transition을 시도해 commit lock이 실제로 직렬화함.
7. pair record가 contract+KMZ digest 한 logical append임을 journal count로 검증.
8. crash injection: signing 뒤, fsync 직후, projection update/response 전.
9. contract-only와 pair의 same request retry 200 / different digest 409.
10. legacy witness-less replay는 조회 가능하되 same-request 추정 재발급은 409.
11. corrupted witness/request digest/revision replay fail-closed.
12. lock-order inventory와 timeout 기반 deadlock regression.
13. 현재 Site가 나중에 SUSPENDED여도 과거 issued Mission replay/조회는 유지됨.
14. feature OFF 상태에서 OCC tests는 runtime benchmark 없이 수행 가능하되, production
    activation gate는 representative route-generation + signing + 기타 pre-commit latency
    evidence가 snapshot validity window 안의 reliable completion을 입증하지 못하면 BLOCKED.

## 9. rollout order

1. Site issuance revision projection과 legacy deterministic replay.
2. internal witness types와 store-owned comparison guards.
3. Mission journal reader에 optional witness/request digest compatibility.
4. 공통 commit coordinator와 contract-only idempotency.
5. contract-only router를 coordinator로 전환하고 barrier tests green.
6. pair router를 같은 coordinator로 전환하고 WorkOrder/Acquisition witness를 결속.
7. 신규 writer의 witness 필수화와 replay enforcement.
8. post-commit reconciliation metric을 관측한 뒤 old writer path 제거.
9. production feature activation 전에 §3.4 실측을 수행하고 PASS evidence를 release/operations
   gate에 결속한다. 미실측 또는 불충분한 worst-case headroom은 activation BLOCKED다.

## 10. 명시적으로 하지 않는 것

- append 직전의 잠금 없는 재조회로 해결했다고 주장하지 않는다.
- route generation·KMZ build·Ed25519 signing 동안 Site lock을 잡지 않는다.
- Site와 Mission journal에 두 개의 “commit marker”를 쓰는 불완전한 2-phase commit을 만들지
  않는다.
- KMZ object storage와 WorkOrder link를 Mission issuance authority로 승격하지 않는다.
- 실패한 sequence reservation을 재사용하거나 journal을 압축해 gap을 숨기지 않는다.
- 이 문제 하나 때문에 database나 distributed transaction coordinator를 도입하지 않는다.

MISSION_ISSUANCE_DESIGN = LOCALLY_IMPLEMENTED_CONTRACT_VERIFIED
