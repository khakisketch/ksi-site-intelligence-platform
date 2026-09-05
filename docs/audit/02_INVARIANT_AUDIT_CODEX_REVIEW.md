# `02_INVARIANT_AUDIT` 독립 코드 검토

> 검토일: 2026-09-01
>
> 코드 기준: `41d9f55270581d9660664f6c23c65ab0d7af0a4a` (`main`, 검토 시작 시
> `origin/main`과 동일) + 기존 uncommitted civil-readiness WIP
>
> 검토 대상: `docs/audit/02_INVARIANT_AUDIT.md`의 worker lease, Mission issuance
> TOCTOU, capability 용어, durable capability promotion 후보
>
> 원칙: 원 감사의 결론을 입력 가설로만 사용하고 실행 코드, 잠금, 원장, 배포 정의,
> 테스트와 직접 재현으로 독립 검증했다.

이 문서는 코드 검토 결과만 추가한다. 제품 코드, 계약, 테스트, 배포 설정, 기존 WIP는
수정하지 않았다. 실장비, HIL, 비행, device write도 수행하지 않았다.

## 작업 계약

- Requirement IDs: `REQ-MSN-104`, `REQ-ACQ-102/103`, `REQ-INT-101`,
  `REQ-SEC-101`의 기존 강제 상태를 검토했다. 요구사항 자체는 변경하지 않았다.
- Owner modules: Core(`mission_records`, `sites`, processing lease stores,
  acquisition), Processing Controller, DJI Gateway.
- Invariants touched: `INV-011`, `INV-040`, `INV-041`, `INV-051`, `INV-052`,
  `INV-060`.
- Acceptance criteria: 요청된 두 P1의 실행·소유·경합·영속·재시작·배포·결과를 모두
  확인하고, capability 의미 지도를 작성하며, 네 finding을 지정된 네 등급으로 분류한다.
- Contracts affected: 없음. OpenAPI와 journal wire를 읽기만 했다.
- Reference assets / adoption: reference repository를 사용하지 않았다. 제품 저장소의 현재
  코드만 `REFERENCE_ONLY`로 검토했다.
- HIL assumptions: capability의 실제 작동이나 실기 증거는 검증하지 않는다. 코드가 그
  증거를 어떤 의미로 받아들이는지만 검토한다.
- License/data implications: 없음. 합성 테스트 fixture와 임시 디렉터리만 사용했다.
- Rollback: 이 리뷰 파일 하나를 제거하면 된다. 제품 상태에는 rollback 대상이 없다.

## 결론 요약

| 검토 항목 | 분류 | 독립 결론 |
|---|---|---|
| Worker lease ownership | `CONFIRMED_WITH_CORRECTION` | 동일 token/principal을 쓰는 두 프로세스가 같은 lease owner로 인식되어 중복 실행할 수 있다. 다만 기본 Compose는 worker 1개이고, 저장소 안에 `docker compose --scale worker=N` 운용 문서는 없다. |
| Mission issuance TOCTOU | `CONFIRMED_WITH_CORRECTION` | 계약 단독·KMZ 짝 발급 모두 실제 HTTP interleaving으로 `SUSPENDED` 전이 뒤 201 durable issuance가 재현됐다. 다만 감사가 든 Processing `SUCCEEDED` 자동 전이 예시는 현재 허용표를 바꾸지 않는다. |
| Capability terminology | `CONFIRMED_WITH_CORRECTION` | 세 `VERIFIED`는 실제로 서로 다른 의미다. 이것은 즉시 하나의 상태로 합칠 문제가 아니라 scope가 다른 상태를 같은 단어로 표현하는 문제다. 감사와 달리 DJI Gateway capability evidence도 `GatewayJournal`에 영속되지 않는다. |
| Durable capability evidence/promotion 후보 | `CONFIRMED` | 유효한 개발 후보지만 identity/scope/mapping/approval/replay semantics가 미결이라 구현 준비 상태는 아니다. “영속 계층 하나만 없다”는 설명은 범위를 과소평가한다. |

---

## 1. P1 worker lease ownership

### 1.1 정확한 실행 경로

Production worker의 처리 작업 경로는 다음과 같다.

1. `runner.main()`이 `KSI_WORKER_CORE_TOKEN` 하나를 읽고
   `HttpCoreClient(token=...)`를 만든다
   (`services/processing-controller/src/ksi_processing_controller/runner.py:492-510`).
2. `run_forever()`/`run_pending_batch()`가 `GET /v1/processing-jobs`로 후보를 얻는다.
   후보 조회와 이후 lease 획득은 서로 다른 HTTP 요청이다
   (`core_client.py:698-709`, `processing_jobs.py:2350-2371`).
3. `run_job()`은 `acquire_lease(job_id)` → `get_input(job_id)` 순으로 호출한다
   (`worker.py:315-317`).
4. 입력 상태가 `QUEUED`일 때만 `RUNNING`으로 전이한다. 입력이 이미 `RUNNING`이면
   전이 없이 곧바로 사진 실측과 NodeODM 실행으로 진행한다(`worker.py:336-340`).
5. 장시간 NodeODM 실행 중 heartbeat도 동일한 `acquire_lease`를 호출한다
   (`worker.py:410-425`).
6. 산출물마다 deterministic object key의 PUT URL을 받고, PUT을 마친 뒤 원장에
   artifact를 등록하고 마지막에 `SUCCEEDED`를 보고한다(`worker.py:431-500`).

Core의 lease endpoint는 인증 principal의 `principal_id`를 그대로 store의
`worker_id`로 넘긴다(`processing_jobs.py:2481-2498`). `/input`, transition,
upload target, artifact register도 같은 principal ID를 lease owner 판정에 사용한다.

같은 공유 `JobLease` 모델은 processing job뿐 아니라 comparison,
design-conformance, region-extraction request에도 쓰인다. 각 HTTP router도 모두
`principal.principal_id`를 `worker_id`로 넘긴다. 따라서 원인은 processing job 하나에
국한되지 않는다.

### 1.2 소유·상태 변수

| 변수 | 소유자 | 현재 의미 |
|---|---|---|
| bearer token | 배포/worker process | Core 인증 credential |
| `Principal.principal_id` | Core auth registry | 인증된 processing principal의 안정 식별자 |
| `JobLease.worker_id` | 각 durable work store | lease 소유자 식별자 |
| `granted_at`, `expires_at` | 각 work store | 최초 취득 시각과 현재 만료 시각 |
| job `status` | ProcessingJobStore | `QUEUED/RUNNING/...` 실행 원장 상태 |

`check_lease()`는 유효 lease의 `worker_id`와 요청 `worker_id`가 다를 때만
`HELD_BY_ANOTHER`를 반환한다(`leasing.py:80-95`). 같은 값이면 갱신이다.
따라서 인증 주체와 실행 인스턴스가 현재 같은 식별자 하나로 표현된다.

### 1.3 concurrency와 durability 경계

- 후보 목록은 잠금 밖의 별도 HTTP transaction이다. 두 프로세스가 같은 `QUEUED`
  job ID를 동시에 cache할 수 있다.
- 각 `acquire_lease()` 호출 자체는 store의 `self._lock` 안에서 원자적이다
  (`processing_jobs.py:1682-1740`). 이 잠금은 두 호출을 직렬화할 뿐, 두 호출의
  `worker_id`가 같으면 두 번째를 경쟁자로 구분하지 못한다.
- durability boundary는 `processing-job-leased`가 `DurableJournal.append()`로
  완료되는 지점이다(`processing_jobs.py:1721-1736`). 두 번째 호출은
  `renewal=true`인 새 durable record를 정상 append한다.
- lease lock은 NodeODM 실행 전체에 걸쳐 유지되는 mutex가 아니다. 실행 중에는 오직
  durable lease 값과 만료 시각만 소유권을 나타낸다.
- `/input`, transition, upload target, artifact registration은 각각 별도 store lock과
  별도 HTTP transaction이다. 그 사이에 다른 프로세스가 같은 owner로 갱신할 수 있다.

### 1.4 실제 가능한 interleaving

다음 순서를 실제 HTTP surface로 실행했다.

1. 프로세스 A와 B가 같은 token으로 후보 목록을 읽어 같은 `jobId`를 cache한다.
2. A가 lease 획득 → `LEASED`.
3. A가 입력을 읽음 → `QUEUED`.
4. A가 상태 전이 → `RUNNING`.
5. cache한 후보를 가진 B가 같은 token으로 lease 획득 → `LEASE_RENEWED`.
6. B가 입력을 읽음 → `RUNNING`.
7. `run_job()`은 `RUNNING` 입력에서는 transition을 생략하므로 A와 B 모두 NodeODM
   경로로 진행할 수 있다.

독립 재현 출력은 다음과 같았다.

```text
both_cached_same_candidate=True
worker_a_lease=LEASED
worker_a_input_status=QUEUED
worker_a_transition=TRANSITIONED
worker_b_same_token_lease=LEASE_RENEWED
worker_b_same_token_input_status=RUNNING
```

항상 중복되는 것은 아니다. 두 프로세스가 모두 `QUEUED` 입력을 읽은 뒤 동시에
`RUNNING` 전이를 시도하면 첫 전이만 성공하고 둘째는 불법 전이로 실패할 수 있다.
그러나 위 순서는 현재 worker 코드와 API가 모두 허용하므로 주장된 중복 실행은 실제로
가능하다.

### 1.5 배포 도달성

- `deploy/compose.yaml`의 기본 정의는 worker service 하나다(`:91-109`). 기본
  `docker compose up`만으로는 다중 프로세스 경합이 발생하지 않는다.
- `.env.example`은 `KSI_WORKER_CORE_TOKEN` 하나만 정의한다(`:142-146`). 같은 service를
  복제하면 모든 replica가 같은 credential/principal을 받는다.
- worker와 runner의 코드 문서는 동시성을 “프로세스를 여러 개 띄우는 것”으로 얻는다고
  명시한다(`worker.py:56-58`, `runner.py:25-29`).
- 그러나 저장소 문서에서 `docker compose up --scale worker=N` 또는 동등한 scale 절차는
  찾지 못했다. 원 감사의 “문서화된 확장 방식” 표현은 과장이다.

따라서 결함은 code-supported multi-process 운용에서 도달 가능하지만, 현재 실제 배포가
worker를 2개 이상 운영했는지는 저장소로 확인할 수 없다. 그 운영 사실만
`NEEDS_EXTERNAL_EVIDENCE`다. 결함 자체는 외부 증거 없이 확인됐다.

### 1.6 restart/retry 동작

- 마지막 lease와 만료 시각은 journal replay로 복원된다.
- 정상 재시작 worker는 job ID를 기억하지 않는다. 활성 `RUNNING` lease는 pending 목록에서
  빠지므로, 일반 runner는 lease 만료 전 즉시 같은 job을 재개하지 않고 만료 후 후보로
  다시 받아 처음부터 실행한다.
- 서로 다른 principal은 활성 lease 동안 거부되고, 만료 후에만 회수한다.
- 같은 principal의 두 프로세스가 이미 같은 job을 실행 중이면 양쪽 heartbeat가 모두
  같은 lease를 갱신하므로 fencing이 일어나지 않는다.
- 같은 credential을 가진 새 프로세스가 이미 active인 job ID를 별도로 알고 직접
  호출하면 만료 전에도 갱신할 수 있지만, 현재 정상 polling runner는 그 job ID를
  pending surface에서 받지 않는다.

### 1.7 구체적 잘못된 결과

최소 결과는 같은 사진을 두 번 내려받고 NodeODM task를 두 번 돌리는 계산·스토리지 비용
중복이다. 더 나쁜 순서도 가능하다.

- worker는 job별 격리 디렉터리가 아니라 공유 `work_dir` 아래 동일 media filename과
  `all.zip`을 사용한다(`worker.py:313-345`, `:431-434`). Compose replica는 같은 named
  volume을 mount하므로 로컬 파일 쓰기·정리도 경합할 수 있다.
- artifact object key는 `siteId/jobId/artifactId[/filename]`의 결정적 함수다
  (`processing_jobs.py:717` 이하). 두 실행은 같은 key에 PUT한다.
- A가 bytes A를 PUT하고 digest A를 durable 등록한 뒤, B가 bytes B를 같은 key에 늦게
  PUT할 수 있다. B의 뒤이은 등록이 `DUPLICATE_ARTIFACT` 또는 terminal-state로 거부돼도
  이미 object bytes는 바뀌었다.
- 그 결과 Mission/Processing journal의 digest A와 object storage의 실제 bytes B가
  달라질 수 있다. 이 산출물이 비교·설계대비 입력으로 사용되면 잘못된 계보 또는 처리
  실패가 뒤 단계로 전파된다.

### 1.8 질문 A-D 판정

**A. 인증 identity와 lease ownership identity가 conflated됐는가? — 예.**

HTTP surface가 `principal.principal_id`를 추가 변환 없이 `JobLease.worker_id`로 쓴다.

**B. credential 하나를 쓰는 여러 worker process가 동시에 한 owner로 보이는가? — 예.**

Core는 token을 같은 principal로 인증하고 process identity를 받지 않는다. 위 HTTP 순서로
두 번째 lease가 실제 `LEASE_RENEWED`가 됐다.

**C. unique worker instance identity가 두 identity를 올바르게 분리하는가? — 개념적으로
예.**

인증 principal과 process-lifetime instance ID의 조합을 lease owner로 쓰면 동일 credential의
replica를 서로 다른 contender로 판정할 수 있다. 단, instance ID 생성·안정성, heartbeat와
모든 worker mutation에 전달하는 방식, server-issued lease/fencing token 필요 여부를 먼저
결정해야 한다. 임의 header 하나만 추가하는 것으로 설계를 끝냈다고 볼 수는 없다.

**D. worker마다 별도 token이 아키텍처 요구인가? — 아니다.**

현재 코드에서 다중 worker를 안전하게 운용하는 operational workaround는 별도 principal/token
부여다. 그러나 authentication principal과 execution instance는 서로 다른 축이므로 token
분리는 본질적 아키텍처 요구가 아니다. credential rotation·replica autoscaling을 고려하면
instance ownership을 별도로 표현하는 편이 개념에 맞다.

### 1.9 기존 테스트와 누락

관련 기존 테스트는 다음을 잘 고정한다.

- `test_processing_jobs.py`: 서로 다른 `worker_id`의 탈취 거부, 같은 ID 갱신,
  만료 후 회수, active RUNNING pending 제외, lease 없이는 input/transition/artifact 거부.
- `test_leasing.py`: 만료 경계와 `check_lease` 순수 함수.
- `test_core_client.py`: `LEASED`와 `LEASE_RENEWED`를 모두 성공으로 처리.
- `test_comparison_requests.py`, `test_design_conformance_requests.py`,
  `test_region_extraction_requests.py`: 동일 shared lease primitive의 서로 다른 worker ID
  경합과 회수.
- `test_worker.py`, `test_runner.py`, `test_comparison_worker.py`,
  `test_region_extraction_end_to_end.py`: worker가 lease를 먼저 얻고 heartbeat/retry하는
  client 실행 순서.
- `test_change_detection_api.py`, `test_phase2_unified_journey.py`는 lease를 포함하는 상위
  통합 흐름을 검증하지만 same-principal replica 경합은 만들지 않는다.

누락은 같은 credential/principal을 공유하는 두 실제 worker instance의 경쟁과, lease owner
identity를 모든 worker mutation에 일관되게 결속하는 계약 테스트다.

### 1.10 분류와 fix readiness

**Classification: `CONFIRMED_WITH_CORRECTION`.** 결함과 결과는 확인됐다. 기본 Compose가
다중 worker라는 주장과 repository-documented scale 절차라는 주장은 확인되지 않았다.

기존 `JobLease`/`check_lease` primitive는 재사용할 수 있지만, 저장소에는 인증과 instance
ownership을 분리하는 wire contract나 server-issued fencing primitive가 없다. 변경은 네 work
store와 모든 worker client call을 함께 다뤄야 한다. 따라서 해결 방향은 정당하지만 아직
하나의 구현안으로 고정할 설계가 남는다.

---

## 2. P1 Mission issuance TOCTOU

### 2.1 정확한 실행 경로

두 production 발급 surface가 같은 optimistic precheck를 사용한다.

**계약 단독** (`POST /v1/missions/contracts`):

```text
auth(MISSIONS_ISSUE)
→ precheck_issuance(siteFrame + SiteStatus + missionId)
→ acquisition readiness
→ v1.3 sequence reserve (설정 시, durable)
→ issue_mission_contract / Ed25519 signing
→ MissionStore.record_issuance / missions journal append
→ 201
```

근거는 `mission_issuance.py:213-292`다.

**계약+KMZ 짝** (`POST /v1/missions/plans`):

```text
auth(MISSIONS_ISSUE)
→ precheck_issuance
→ WorkOrder lookup + APPROVED check (선택)
→ acquisition readiness
→ v1.3 sequence reserve (설정 시, durable)
→ route/KMZ generation + contract signing
→ MissionStore.record_issuance / missions journal append
→ KMZ persistence + WorkOrder lineage link
→ 201
```

근거는 `mission_plans.py:762-920`다. 둘 다 sync `def` route다. Production Uvicorn은
worker process 하나지만 `--workers` 없이도 FastAPI/Starlette가 sync endpoint를 thread
pool에서 실행하므로 같은 process 안의 다른 sync request와 겹칠 수 있다.

### 2.2 소유·상태 변수

`precheck_issuance()`가 읽는 authorization facts는 다음이다.

- organization-scoped Site 존재;
- canonical `site_frame`과 요청 `siteFrame`의 일치;
- `mission_id` 미사용;
- `mission_type × SiteStatus` 허용표(`INV-052`).

`SiteLookupResult`는 `site_frame`과 `status`만 담고 version/epoch는 담지 않는다
(`mission_records.py:282-294`). `SiteRecord`에는 `updated_at`이 있지만 precheck 결과에
포함되지 않으며 전용 authorization revision도 없다.

짝 발급에는 선택적으로 WorkOrder `APPROVED`와 acquisition readiness도 추가된다.
WorkOrder store 자체에는 `version/expectedVersion` primitive가 있지만, 발급 함수는 읽은
WorkOrder version을 Mission durability boundary에서 다시 대조하지 않는다. Acquisition
snapshot은 최대 5분 TTL을 가진 별도 원장 projection이다.

### 2.3 concurrency와 durability 경계

- `SiteStore.get()`은 SiteStore lock 안에서 immutable `SiteRecord` snapshot 하나를 읽는다
  (`sites.py:720-728`). 이 한 번의 읽기 안에서 frame과 status가 섞이지는 않는다.
- `SiteStore.transition()`은 자기 lock 안에서 상태 검사 → site journal append → projection
  변경을 수행한다(`sites.py:543-593`).
- `MissionStore.record_issuance()`는 별도의 MissionStore lock 안에서 `mission_id` 중복
  검사 → mission journal append를 수행한다(`mission_records.py:464-481`). Site 상태를
  받거나 검사하지 않는다.
- 두 store lock 사이에는 공통 lock, transaction, compare-and-append token이 없다.
- durability boundary는 `missions.jsonl` append가 fsync되어
  `record_issuance()`가 `RECORDED`를 반환하는 순간이다. 서명 bytes 생성만으로는 durable
  issuance가 아니며 v1.3 sequence reserve는 별도의 선행 durability boundary다.

현재 locking은 각각의 journal/projection 일관성과 중복 mission ID는 보호하지만,
“이 Site snapshot으로 인가한 Mission append”를 하나의 원자 동작으로 만들지 않는다.

### 2.4 interleaving 실재 여부와 독립 재현

계약 단독 route는 서명 함수 진입에서, 짝 route는 `build_mission_plan()` 진입에서 각각
barrier로 멈췄다. 그 사이 같은 `SiteStore`를 정상 API와 동일한 transition primitive로
`UNMAPPED → SUSPENDED` 전이한 뒤 발급을 계속했다.

```text
contract_only TRANSITIONED SUSPENDED 201 mission-toctou-contract
pair          TRANSITIONED SUSPENDED 201 mission-toctou-pair
```

두 경우 모두 precheck 당시 `UNMAPPED`에서 허용된 `BASELINE_MAPPING`이었고, durable
append 당시에는 모든 Mission을 금지하는 `SUSPENDED`였다. 그럼에도 201과 signed Mission
record가 생성됐다. claimed interleaving은 실제로 가능하다.

### 2.5 어떤 Site 변경이 실제로 경합을 만든다

- 운영자의 `POST /v1/sites/{siteId}/transitions`는 별도 sync route이며 실제 경합
  producer다. `SUSPENDED` 진입은 추가 autonomy approval을 요구하지만 정상 운영 경로다.
- staleness sweep은 `PATROL_READY/PATROL_ACTIVE → MODEL_STALE`로 바꿔 autonomous
  mission eligibility를 제거할 수 있다. 운영자 또는 외부 scheduler가 부르는 별도 sync
  surface다(`spatial_model.py:580-599`).
- Mission dispatch가 `UNMAPPED → BASELINE_MAPPING`으로 전진시키는 경로도 다른 신규
  baseline Mission의 eligibility를 바꿀 수 있다.
- 원 감사가 예로 든 Processing `SUCCEEDED`는
  `MODEL_PROCESSING → MODEL_VALIDATION`만 수행한다(`spatial_model.py:269-277`). 현재
  mission gating 표에서 두 상태는 모두 `INCIDENT_SURVEY`만 허용하므로 이 전이는
  authorization 결과를 바꾸지 않는다. “worker SUCCEEDED만으로 허용→거부 경합이 된다”는
  예시는 확인되지 않았다.

### 2.6 배포 도달성

Default production은 Core process 하나이지만 세 endpoint가 모두 sync route이고 각각 다른
store lock을 사용한다. 별도 Core replica가 없어도 두 concurrent HTTP request만으로
재현된다. 따라서 repository 기본 배포 구조에서 code-reachable하다. 실제 운영에서 같은
짧은 창이 발생한 적이 있는지는 외부 운영 로그가 필요한 별도 질문이며, 결함 성립 조건은
아니다.

### 2.7 restart/retry 동작

- 잘못된 상태에서 append된 MissionRecord는 restart 후 그대로 replay된다. replay는 발급
  당시 SiteStatus를 저장하지도, 현재 SiteStatus로 재심사하지도 않는다. 이미 발급된 계약을
  현재 상태로 소급 무효화하지 않는 기존 idempotency 정책과는 정합하지만, 그래서 잘못된
  최초 결정을 자동 복구하지 못한다.
- 같은 pair request의 retry는 저장된 request digest가 같으면 현재 SiteStatus와 무관하게
  200으로 기존 artifact를 재생성한다. 이것은 이미 durable한 정상 발급에 필요한 정책이며
  유지해야 한다.
- contract-only retry는 기존 mission ID 때문에 409 `MISSION_ID_CONFLICT`다.
- 최종 거부를 나중에 추가하면 v1.3 sequence가 이미 예약된 경우 gap이 남는다. 현재
  `MissionIssuanceSequenceStore`는 gap을 명시적으로 허용하고 예약 번호 재사용을 금지한다
  (`mission_records.py:138-207`, `test_mission_records.py`의 durable gap 테스트). 그러므로
  sequence gap은 오염이 아니라 수용된 retry 의미론이다.
- pair route의 KMZ object persistence와 WorkOrder link는 MissionRecord append 뒤다. 최종
  boundary에서 거부되면 이 두 후속 side effect는 아직 발생하지 않는다. 단, WorkOrder
  acquisition run의 선행 `ensure_run`은 이미 durable할 수 있어 별도 reconciliation 검토가
  필요하다.

### 2.8 구체적 잘못된 결과

- Site가 `SUSPENDED`인데도 `INV-052`상 발급 금지 Mission의 signed contract와 pair artifact
  authority가 durable Mission ledger에 존재한다.
- Mission execution transition은 발급 record의 존재와 실행 전이표를 보지만 SiteStatus를
  다시 gate하지 않는다. 따라서 이 record는 뒤에 `DISPATCHED`로 기록될 수 있다.
- 실제 비행까지는 device activation, Pilot/operator, FC 안전 경계 등이 더 남아 있어 이
  코드 결함만으로 즉시 motor/flight를 만들지는 않는다. 그러나 Core가 “그 상태에서 발급한
  적 없는 계약”을 이미 authoritative하게 만든 것이 직접적인 incorrect state다.

### 2.9 제안된 invariant 판정

사용자가 제시한 문장은 **방향상 맞다**.

> A mission may be durably issued only if the site/mission prerequisite state used to
> authorize issuance is still current at the durability boundary.

다만 “state”를 `SiteRecord.updated_at` 전체로 해석하면 안 된다. AOI나 model age policy처럼
해당 Mission authorization 결과에 영향을 주지 않는 변경도 같은 timestamp를 바꿀 수 있다.
이 검토 범위에서 정확한 표현은 다음과 같다.

> 신규 Mission의 durable append는 그 발급을 인가한 organization-scoped Site 존재,
> canonical siteFrame, MissionType×SiteStatus 판정이 append 순간에도 동일한 경우에만
> 성공한다. 선택적으로 발급을 인가한 WorkOrder/readiness fact가 있다면 그 fact의 명시된
> snapshot/revision도 같은 규칙을 가져야 한다. 이미 durable한 동일 mission의 idempotent
> retry에는 현재 Site gate를 소급 적용하지 않는다.

### 2.10 enforcement mechanism 평가

| 후보 | 이 invariant를 단독으로 만족하는가 | 평가 |
|---|---|---|
| append 직전 재조회 | 아니오 | 창을 줄이지만 재조회 반환 직후와 Mission append 사이에서 Site transition이 가능하다. final check라고 이름 붙여도 원자적이지 않다. |
| version/epoch OCC | 단독으로는 아니오 | expected revision을 잠금 밖에서 대조하면 같은 race가 남는다. Site revision 대조와 Mission append가 하나의 serialization boundary 안에 있어야 한다. 다만 authorization-specific revision은 정확한 stale-request 판정에 유용하다. |
| 발급 전체 lock | 과도함 | route 생성·KMZ·서명을 Site lock 안에서 하면 정합은 되지만 긴 계산 동안 Site transition을 막는다. 필요 이상으로 큰 critical section이다. |
| 최종 validate+append 구간 lock | 가능 | expensive work는 밖에서 하고 Site의 authorization facts 재대조부터 Mission append까지만 Site transition과 직렬화한다. 현재 single-node/file-journal architecture에 가장 가까운 형태다. 단, Site→Mission lock order와 실패 복구를 설계해야 한다. |
| 기존 cross-store transaction primitive | 없음 | WorkOrder `expectedVersion`은 같은 store 안의 OCC 선례일 뿐, Site journal과 Mission journal을 원자 결합하지 않는다. DurableJournal도 journal 하나의 append만 보장한다. |

따라서 “즉시 재검증”만 구현하는 것은 충분하지 않다. 가장 작은 일관된 방향은 기존
SiteStore lock과 MissionStore append를 이용해 **최종 짧은 구간을 직렬화**하는 것이지만,
현재 public primitive가 없고 repository가 다른 lifecycle에서 중첩 store lock을 의도적으로
피해 왔으므로 lock order, callback/transaction API, WorkOrder·readiness 포함 범위를 먼저
결정해야 한다. 새로운 분산 아키텍처가 필요한 것은 아니지만 구현 전 작은 설계가 필요하다.

### 2.11 기존 테스트와 누락

관련 기존 테스트는 다음을 고정한다.

- `test_mission_site_status_gate.py`: MissionType×SiteStatus 표를 두 발급 endpoint에서
  순차적으로 검증한다.
- `test_mission_records.py`: mission ID conflict, pair idempotent retry, SiteStatus가 바뀐 뒤의
  retry 의미, v1.3 sequence durability/gap/replay를 검증한다.
- `test_mission_plans.py`, `test_mission_issuance.py`: signing, route generation, journal failure,
  contract/KMZ response를 검증한다.
- `test_spatial_model.py`, Site API tests: Site transition과 automatic lifecycle을 각자
  검증한다.

누락은 final authorization snapshot과 Mission append를 함께 검증하는 동시성 계약 테스트다.
새 테스트는 두 endpoint, `SUSPENDED`, authorization-changing staleness/dispatch,
idempotent retry, sequence gap, journal failure를 포함해야 한다.

### 2.12 분류와 fix readiness

**Classification: `CONFIRMED_WITH_CORRECTION`.** 두 실제 endpoint에서 결함을 재현했다.
Processing `SUCCEEDED`가 authorization을 바꾼다는 원 감사의 구체 예시는 틀렸고, append 직전
재조회만으로 충분하다는 인상도 정정해야 한다.

현재 repository에 cross-store atomic primitive가 없고, 보호할 prerequisite 범위와 lock
order를 결정해야 하므로 바로 한 구현으로 들어갈 준비 상태는 아니다.

---

## 3. Capability terminology semantic map

### 3.1 현재 의미 지도

| CURRENT TERM | CURRENT SOURCE | CURRENT PERSISTENCE | CURRENT CONSUMER | ACTUAL MEANING | SAFETY/AUTHORITY EFFECT |
|---|---|---|---|---|---|
| `CapabilityVerificationState.VERIFIED` | `packages/domain/.../capability.py`; Core `CapabilityRegistry.transition()` + 11-field `SpikeEvidence` | 없음. Core registry는 process-memory dict이며 production 조립은 매 기동 9개 `SPIKE_REQUIRED`를 seed | 공개 `GET /capabilities`의 `list_operational()` | `SPIKE-DJI-01…09` API/연동 기능이 구조화된 real-world/HIL evidence로 검증됐다는 제품 전역에 가까운 acceptance 주장 | `VERIFIED`만 공개 operational 목록에 노출. 현재 production에는 promotion/load 경로가 없어 목록은 비어 있음. 직접 Mission route 선택에는 연결되지 않음 |
| Acquisition `CapabilityStatus.VERIFIED` | Gateway device가 제출하는 `ConnectivitySnapshotV1.capabilities[]` | 있음. organization/site-scoped `acquisition-connectivity.jsonl`의 TTL snapshot 안에 저장 | `AcquisitionConnectivityStore.readiness()`; issue gate가 ON이면 신규 Mission precheck | 인증된 Gateway가 “이 hardware/firmware capability가 이 시각에 VERIFIED이고 evidenceRef가 있다”고 **보고한 ephemeral operational observation**. Core는 evidenceRef의 실제 bytes나 승인 원장을 대조하지 않음 | snapshot 미만료·device/profile binding·network와 함께 readiness를 `READY`로 만들 수 있음. 배포 기본 flag는 OFF. active contract를 취소하지 않음 |
| DJI Gateway `CapabilityStatus.VERIFIED` / `field_status` | `ksi_dji_gateway.domain.CapabilityEvidence`의 path+capability+hardware+firmware field evidence | **없음.** `CapabilityRegistry`는 memory dict. `GatewayJournal`은 capability evidence가 아니라 operation/idempotency receipt만 저장 | `CapabilityRouter.select()`와 legacy `ZeroTouchGateway.require_verified()` | 특정 integration path와 exact hardware/firmware 조합에서 해당 route가 Field/HIL evidence로 검증됐다는 route-local 판정 | feature flag ON, port config/binding/transport, field status VERIFIED가 모두 있어야 route 선택. 현재 package에 production runtime host/entrypoint가 없어 배포 효과 없음 |
| `VendorDocumentationStatus.DOCUMENTED_*` | 같은 DJI Gateway `CapabilityEvidence`의 별도 vendor axis | 없음(부모 evidence가 memory-only) | 현재 route selection은 읽지 않음; audit/test 설명용 | vendor 문서가 지원·부분지원·미기재·충돌·미지원 중 무엇을 말하는가 | route를 활성화하지 않음. field `VERIFIED`를 추론할 수 없음 |
| capability feature flag `true` | DJI Gateway `CapabilityRouter` runtime mapping | 현재 host/config persistence 없음 | route selector | 운영자가 이미 검증된 route를 이 배포에서 사용하도록 별도로 연 것 | evidence를 대신하지 못함. evidence가 있어도 flag OFF면 fail-closed |

### 3.2 원 감사에서 필요한 정정

1. 세 `VERIFIED`가 같은 의미라는 가정은 틀리다. 제품-level HIL acceptance, Gateway가
   제출한 TTL observation, path/hardware/firmware route evidence는 scope와 trust source가
   다르다.
2. 반대로 “하나의 capability에는 반드시 하나의 상태만 있어야 한다”도 그대로는 적절한
   invariant가 아니다. 같은 기능에 대해 vendor documentation, field acceptance,
   current device health가 동시에 서로 다른 상태를 갖는 것은 정상이다. 필요한 것은 각
   축의 명시적 이름, authority, mapping과 서로를 추론하지 않는 규칙이다.
3. Acquisition의 `VERIFIED`는 Core가 검증한 실기 evidence가 아니다. Gateway device
   identity/binding과 TTL은 강제하지만 `evidenceRef`는 비어 있지 않은 문자열이면 되고
   Core authoritative registry와 대조하지 않는다(`acquisition/models.py:266-280`,
   `store.py:231-246`). 현재 코드 주석의 “실기 검증” 표현보다 실제 trust가 약하다.
4. 원 감사의 “DJI Gateway axis는 GatewayJournal에 영속” 주장은 틀리다.
   `GatewayJournal`은 `IntegrationReceipt`만 encode/replay하고 capability registry를 받지
   않는다(`persistence/journal.py:17-100`). Gateway evidence도 restart 후 자동 복원되지 않는다.
5. Core의 9개 `SPIKE-DJI-*` identity와 Gateway/Acquisition의 5개 semantic capability
   identity 사이에 canonical mapping이 없다. 따라서 Core durable registry 하나를 만드는
   것만으로 route promotion이 자동 해결되지 않는다.

### 3.3 public/contract rename 필요성

즉시 public enum 값을 바꿀 필요는 없고, 지금 바꾸는 편이 더 위험하다.

- Acquisition `VERIFIED`는 JSON schema와 durable connectivity journal에 이미 기록되는 wire
  value다. 같은 `1.0` reader에서 값을 바꾸면 과거 journal replay를 깨뜨린다.
- Core `/capabilities`의 `VERIFIED`는 그 endpoint 안에서는 구조화 evidence를 통과한
  operational acceptance라는 의미로 일관된다.
- DJI Gateway는 아직 runtime host가 없지만 v1.2/v1.3 compatibility reader와 테스트가 있다.

더 안전한 순서는 wire compatibility를 유지하면서 내부에서 다음 semantic 이름을 명시하는
것이다.

- Core: `field_evidence_acceptance_state` 또는 동등한 제품/HIL acceptance 의미;
- Acquisition: `gateway_reported_capability_state` / `reported_verified` 판정;
- DJI Gateway: 이미 제공되는 `field_status` 이름을 primary internal 의미로 사용;
- vendor documentation은 계속 별도 axis;
- 경계마다 legacy wire `VERIFIED` ↔ 명시적 internal semantic 값의 compatibility mapping을
  둔다.

public wire를 꼭 명확히 해야 하는 시점에는 기존 journal/API를 같은 버전에서 바꾸지 말고
versioned contract로 이동해야 한다. 이 검토는 이름 변경을 구현하지 않는다.

### 3.4 분류

**Classification: `CONFIRMED_WITH_CORRECTION`.** 같은 단어가 세 의미로 쓰여 오해 가능성이
있다는 finding은 맞다. 하지만 이것을 “반드시 하나의 authoritative status로 통합해야 하는
위반”으로 정의한 부분과 Gateway evidence persistence 설명은 정정해야 한다.

---

## 4. Durable capability evidence/promotion 후보

### 4.1 개발 후보로서의 타당성

후보 자체는 정당하다.

- Core의 `CapabilityRegistry`는 증거 없는 초기 `VERIFIED`를 막고, 전이표와 11-field
  `SpikeEvidence`, operational exposure gate를 갖는다.
- production 조립은 매 restart마다 9개 `SPIKE_REQUIRED`를 다시 만들 뿐, 승인된 evidence를
  load/replay하는 경로가 없다.
- DJI Gateway route registry 역시 memory-only라 실제 route-specific evidence를 재시작에
  걸쳐 보존하는 authoritative source가 없다.
- HIL이 실제 통과하는 순간 수동 code/config injection으로 우회할 압력이 생기므로 durable,
  auditable, replayable promotion은 제품 방향과 맞다.
- `DurableJournal`, evidence storage, authenticated admin approval, EquipmentSupportStore 같은
  repository primitive는 재사용 후보가 된다.

### 4.2 아직 implementation-ready가 아닌 이유

원 감사의 “판정 로직은 끝났고 persistence 하나만 없다”보다 남은 설계가 크다.

1. Core 9개 Spike ID와 route 5개 capability의 canonical identity/mapping이 없다.
2. product-global acceptance와 organization/site/device/path/hardware/firmware-scoped evidence 중
   무엇이 authoritative record이고 무엇이 projection인지 결정되지 않았다.
3. Acquisition Gateway self-report가 durable promotion을 참조해야 하는지, 단순 health
   observation으로만 남을지 계약이 없다.
4. promotion approver, demotion actor, offline signed import 대 authenticated HTTP 중 승인
   surface가 결정되지 않았다.
5. `SpikeEvidence` wire schema, evidence digest, raw evidence existence/digest verification,
   replay gate version과 migration fixture가 없다.
6. Core capability transition은 **모든 전이**에 evidence 문자열을 요구한다
   (`capability.py:64-93`). 원 감사가 후보 invariant C4에서 말한 “VERIFIED→BLOCKED는
   evidence 없이 즉시”는 현재 코드와 다르다. 보수적 차단에 사유/증거를 요구할지 먼저
   결정해야 한다.
7. `list_operational()` public exposure와 Gateway route enablement 사이에 소비/mapping 계약이
   없다.
8. 실제 promotion은 여전히 HIL/field evidence가 있어야 한다. store 구현 green이 capability
   `VERIFIED`를 뜻해서는 안 된다.

따라서 개발 목표는 유효하지만, semantic model과 authority flow가 먼저다. public enum
rename부터 하는 것도, 현재 memory registry에 journal만 붙이는 것도 충분하지 않다.

### 4.3 분류

**Classification: `CONFIRMED`.** Durable evidence/promotion은 올바른 후보지만 현재 상태는
설계 후보이지 구현 티켓으로 바로 고정할 단계가 아니다.

---

## 5. 실행 검증

### 5.1 독립 interleaving probes

- Same-token worker HTTP probe: 두 candidate cache → `LEASED` → `RUNNING` → 같은 token
  `LEASE_RENEWED` → `RUNNING` input을 확인했다.
- Mission contract-only HTTP probe: signing boundary에서 Site를 `SUSPENDED`로 전이한 뒤
  201 issuance를 확인했다.
- Mission pair HTTP probe: route/KMZ generation boundary에서 Site를 `SUSPENDED`로 전이한 뒤
  201 issuance를 확인했다.

probe는 `TemporaryDirectory`, 기존 test fixture, `unittest.mock.patch` barrier만 사용했다.
파일을 저장소에 추가하거나 제품 코드를 바꾸지 않았다.

### 5.2 기존 회귀 실행

다음을 실행했다.

```text
uv run --locked pytest -q \
  tests/contract/test_mission_site_status_gate.py \
  tests/contract/test_mission_records.py \
  tests/contract/test_processing_jobs.py \
  tests/contract/test_leasing.py \
  tests/contract/test_capability_gate.py \
  tests/contract/test_core_app.py \
  tests/contract/test_acquisition_connectivity.py \
  services/dji-gateway/tests/test_gateway.py \
  services/dji-gateway/tests/test_candidate_adapters.py
```

결과:

```text
308 passed, 1 warning in 11.09s
```

warning은 FastAPI TestClient의 Starlette/httpx deprecation warning이다. 테스트 실패는 없다.
이 green은 현재 동작을 검증한 것이며, 위 두 race를 막는 테스트가 존재한다는 뜻은 아니다.

## 최종 판정

원 감사는 두 P1의 핵심 원인을 정확히 찾았고 durable capability promotion의 필요성도 올바르게
식별했다. 그러나 worker deployment 도달성, Mission automatic-transition 예시, Gateway
capability persistence, capability 단일-authority 정의와 구현 범위를 수정해야 한다. 따라서
전체 결론은 material disagreement가 아니라 corrections를 포함한 verification이다.

```text
INVARIANT_AUDIT_REVIEW = VERIFIED_WITH_CORRECTIONS

WORKER_LEASE_FIX_READINESS = NEEDS_DESIGN

MISSION_ISSUANCE_FIX_READINESS = NEEDS_DESIGN

CAPABILITY_PROMOTION_READINESS = BLOCKED_BY_SEMANTICS
```
