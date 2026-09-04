# Worker Lease Identity Corrective Contract

> 상태: 설계 확정, 구현하지 않음
>
> 근거 감사: `docs/audit/02_INVARIANT_AUDIT.md`,
> `docs/audit/02_INVARIANT_AUDIT_CODEX_REVIEW.md`
>
> 설계 기준 코드: `41d9f55270581d9660664f6c23c65ab0d7af0a4a`
>
> 2026-09-03 correction closure: authoritative artifact identity, lost-CLAIM
> idempotency, generation ownership, worker-local workspace isolation을 이 문서의
> normative contract로 확정했다.

이 문서는 같은 worker credential을 공유한 복수 프로세스가 한 작업의 같은 lease owner로
인식되는 결함을 고치는 **계약**만 정의한다. 제품 코드, OpenAPI, journal 또는 배포 설정을
이 문서에서 변경하지 않는다.

## 작업 계약

- Requirement IDs: `REQ-OPS-102`, `REQ-SEC-101`
- Owner module: Core의 공용 lease primitive와 네 durable work store, Processing Controller
- Acceptance criteria: 같은 credential의 서로 다른 프로세스는 경쟁자로 구분되고, 현재
  lease generation을 갖지 않은 actor의 heartbeat·입력·업로드·등록·완료·실패는 모두
  fail-closed 거부된다.
- Contracts affected: 후속 구현에서 worker 전용 HTTP wire, lease journal record,
  generation-scoped `AuthoritativeArtifactManifestV1`, attempt-local workspace. 이 설계
  작업에서는 runtime 계약을 변경하지 않는다.
- Reference assets: `leasing.py`, 네 work store의 append-only projection,
  `DurableJournal`, digest-bound S3 PUT capability.
- Adoption decisions: 기존 lease TTL·store lock·append/replay와 `idempotencyKey`의
  exact-fingerprint 재전송 규율은 `ADOPT`; 인증 principal을 owner로 쓰는 관습, artifact key
  재유도, job-wide artifact authority, 공용 flat `work_dir`는 `REPLACE`; generation 없는
  lease와 stable-key 직접 PUT은 신규 발급에서 `REPLACE`; worker별 credential은
  `REFERENCE_ONLY` 운영 완화책.
- Files to change: 이 문서 하나.
- Tests: 후속 구현에서 공용 순수 함수, 네 store contract/replay, HTTP/client/runner,
  stale upload 및 crash/retry 통합 테스트.
- HIL or real-device assumptions: 없음. 이 계약은 Core/worker 동시성 계약이다.
- License/data implications: 없음. generation-scoped orphan object의 보존·GC 정책은 아래에
  정의한다.
- Rollback: 구현 시 fenced writer만 중지하고 reader compatibility는 유지한다. 안전 게이트를
  풀어 generation 없는 다중 worker를 다시 허용하지 않는다.
- Invariants touched: `INV-040`의 production fail-closed와 `INV-051`의 산출물 계보를 지키며,
  `INV-060`의 조직 범위를 인증 principal에서 계속 유도한다. 인증 주체와 실행 소유권을
  분리해 이 세 불변식을 약화하지 않는다
  (`docs/product/DOMAIN_INVARIANTS.md:180-194`, `:236-251`, `:321-326`).

## 1. 현재 시스템의 정확한 모델

### 1.1 실행 경로와 경계

Production runner는 `KSI_WORKER_CORE_TOKEN` 하나로 `HttpCoreClient`를 만들며
(`services/processing-controller/src/ksi_processing_controller/runner.py:492-510`),
동시성은 프로세스를 여러 개 띄우는 방식이라고 명시한다
(`services/processing-controller/src/ksi_processing_controller/runner.py:25-29`).

처리 작업은 다음 순서로 실행된다.

1. 후보 목록 조회.
2. `POST .../{jobId}/lease`.
3. `/input` 조회.
4. 입력이 `QUEUED`일 때만 `RUNNING` 전이. 이미 `RUNNING`이면 그대로 작업 실행.
5. NodeODM polling마다 lease 재취득을 heartbeat로 사용.
6. presigned PUT으로 바이트 업로드, artifact 등록, `SUCCEEDED` 전이.

근거는 `worker.py:315-340`, `:410-428`, `:431-500`이다. Core lease route는
인증된 `principal.principal_id`를 변환 없이 `worker_id`로 전달한다
(`processing_jobs.py:2481-2498`). upload URL도 같은 principal을 사용하고
(`processing_jobs.py:2598-2648`), artifact 등록과 상태 전이도 principal ID를 actor와
lease owner로 사용한다(`processing_jobs.py:2433-2455`, `:2770-2796`).

`ProcessingJobStore.acquire_lease()`는 store lock 안에서 현재 lease를 검사하고 같은
`worker_id`면 renewal로 append한다(`processing_jobs.py:1669-1740`). 즉 store lock은 두
요청을 직렬화하지만 같은 credential의 두 프로세스를 구분하지 못한다. 현재 durable
lease record에는 `workerId`, `expiresAt`, `renewal`만 있고 generation이 없다
(`processing_jobs.py:1721-1728`).

공용 `JobLease`도 `worker_id`, `granted_at`, `expires_at`만 가진다. 활성 lease의
`worker_id`가 요청 값과 다를 때만 경쟁자로 거부한다
(`services/core/src/ksi_core/leasing.py:39-62`, `:80-95`). 같은 primitive와 같은
principal-to-worker 매핑은 comparison, design-conformance, region-extraction에도 쓰인다
(`comparison_requests.py:1392,1430,1500`,
`design_conformance_requests.py:1651,1680,1759,1846,1922,1962`,
`region_extraction_requests.py:775,804,871`).

Durability boundary는 해당 store lock 안에서 lease journal append의 `fsync`가 끝난
시점이다. `DurableJournal.append()`는 성공을 `fsync` 뒤에만 반환하고, 동일 journal의
프로세스 간 writer는 `flock`으로 하나만 허용한다
(`durable_journal.py:91-129`, `:304-377`). 실행 중 NodeODM에는 그 lock을 유지하지 않는다.

### 1.2 현재 identity와 state

| 개념 | 현재 값 | 실제 현재 의미 | 문제 |
|---|---|---|---|
| Authentication credential | bearer token | Core에 `PROCESSING_WORK` 권한을 증명 | replica가 공유 가능 |
| Authentication identity | `Principal.principal_id` | token이 가리키는 안정된 보안 주체 | 아래 owner로 재사용됨 |
| Worker logical identity | 별도 필드 없음 | 사실상 principal ID가 대신함 | deployment/pool과 process가 구분되지 않음 |
| Worker process/instance identity | 없음 | Core가 관측할 수 없음 | 같은 token의 프로세스를 구분 불가 |
| Claim/acquisition identity | 없음 | CLAIM response 유실과 신규 취득을 구분 못함 | retry가 자기 generation을 바꿀 수 있음 |
| Lease ownership identity | `JobLease.worker_id` | 현재는 principal ID | 인증과 실행 소유권이 합쳐짐 |
| Lease fencing/version | 없음 | TTL과 시간 비교만 존재 | stale actor를 세대별로 거부 불가 |
| Job identity | `jobId`/각 request ID | durable work item의 안정 ID | 유지 가능 |

### 1.3 artifact side effect와 현행 reader 경계

현재 artifact object key는 site/job/artifact 식별자의 결정적 함수이고 같은 artifact는
항상 같은 key를 쓴다(`processing_jobs.py:717-751`). Core는 lease를 검사한 뒤 presigned
PUT만 발급하고 bytes는 Core를 통과하지 않는다(`processing_jobs.py:2598-2620`). 따라서
URL 발급 뒤 lease를 잃은 actor가 늦게 stable key에 PUT하면, 뒤의 artifact 등록이
거부되어도 이미 등록된 digest와 실제 object bytes를 갈라놓을 수 있다.

스토리지 어댑터에는 digest-bound SigV4 PUT primitive가 이미 있지만
(`evidence_s3.py:98-162`), 현재 processing artifact route는 digest를 받지 않는 일반
`presigned_put()`을 쓴다(`processing_jobs.py:2642-2648`). fencing은 Core journal mutation뿐
아니라 이 외부 side effect에도 적용되어야 한다.

현행 processing artifact 위치·metadata 소비자는 한 곳이 아니다. 다음은 후속 구현에서
**모두** accepted manifest resolver로 전환해야 하는 완전한 known-reader inventory다.

| 현재 consumer | 현재 읽는 사실 | 전환 요구 |
|---|---|---|
| Download — `processing_jobs.py::download_processing_artifact` | 주 파일과 `auxiliary_files` object key | accepted manifest의 primary/auxiliary binding |
| Comparison — `comparison_requests.py::_presigned_url`과 comparison preflight | point cloud/DSM 선택, worker input presigned URL | accepted generation metadata와 recorded object binding |
| Checkpoint registration/replay — `checkpoint_validations.py::register`, replay validation | DSM identity·digest·CRS·vertical reference 대조 | accepted DSM binding과 recorded metadata |
| Accuracy verification worker input — `checkpoint_validations.py::get_pending_checkpoint_validation` | immutable DSM download URL | accepted DSM primary object binding만 presign |
| Design-vs-actual — `design_conformance_requests.py::_artifact_object_key`과 preflight | DSM 선택·preflight·수직기준과 design-vs-actual worker URL | accepted DSM binding |
| Report/reference validation — `artifact_refs.py`의 consumer (`change_detection.py`, `volume_reports.py`, `design_conformance_reports.py`) | job-wide artifact ID/kind 존재 | accepted artifact reference만 검증 |
| Civil comparison eligibility — `civil_preflight.py` | artifact lineage/profile/CRS/수직기준 | accepted generation의 artifact 집합만 판정 |
| Processing completion/result validation — `processing_jobs.py::assert_succeeded_is_backed`, `artifact_of`, `resolve_artifact`, replay | job-wide source artifact 존재 | 완료를 주장하는 generation의 candidate manifest만 판정하고 성공 record가 accepted set을 결속 |
| Spatial-model projection — `spatial_model.py` | source artifact 존재와 최신 성공 epoch | accepted source artifact만 공간모델 근거로 사용 |
| Site-workspace result availability — `site_workspace.py` | 성공 작업의 available result kind | accepted manifest의 kind만 표시 |

upload target은 reader가 아니지만 recorded binding의 producer이므로 같은 전환 단위에 포함한다.
새 consumer는 `ProcessingJobStore`의 accepted-artifact resolver를 통해서만 읽어야 하며 위
inventory test가 직접 key 유도 함수의 신규 호출을 거부한다. 이 목록은 설계 기준 코드에서
발견된 authoritative processing-result reader의 전수 목록이다. 구현 중 새 reader가 발견되면
그 reader까지 resolver로 전환하고 inventory test에 추가하기 전에는 신규 manifest writer나
multi-worker activation을 켤 수 없다.

## 2. 질문 A-F의 답

### A. 어떤 identity가 lease를 소유해야 하는가?

Lease owner는 **process lifetime마다 새로 생성된 `worker_instance_id`와 Core가 발급한
현재 `lease_generation`의 조합**이어야 한다. 정확한 소유권 key는 다음이다.

```text
(organization_id, work_kind, job_id, worker_instance_id, lease_generation)
```

`job_id`는 무엇을 소유하는지, `worker_instance_id`는 어느 실행 인스턴스인지,
`lease_generation`은 그 job의 몇 번째 유효 소유권인지 나타낸다. 인증 principal은 이
소유권을 요청할 권한과 조직 범위를 증명할 뿐 owner key가 아니다.

### B. Authentication identity와 lease ownership identity가 같아도 되는가?

의미상 **같으면 안 된다**. 한 credential이 한 process에만 배포된 우연한 구성에서도 두
개념은 별도 필드여야 한다. credential rotation, autoscaling, crash restart는 인증 수명과
process 수명을 다르게 만든다. 현재 route가 principal ID를 직접 넘기는 것이 확인된
conflation이다(`processing_jobs.py:2486-2498`).

### C. 두 프로세스가 같은 credential을 쓰면 어떻게 되어야 하는가?

두 프로세스는 서로 다른 cryptographically-random `worker_instance_id`를 생성해야 한다.
첫 번째 active lease를 얻은 instance만 현재 generation을 받는다. 두 번째는 같은 인증
principal이어도 `LEASE_HELD_BY_ANOTHER`로 거부된다. 별도 credential은 필요하지 않다.

### D. lifecycle·retry 계약

| 사건 | 필수 동작 |
|---|---|
| Worker restart | 새 process는 반드시 새 `worker_instance_id`와 새 `lease_acquisition_id`를 만든다. 이전 generation을 갱신할 수 없고, lease 만료 뒤 새 generation으로 회수한다. |
| Process crash | heartbeat가 끊기고 TTL 만료 후에만 회수된다. 별도 release 성공을 전제로 하지 않는다. 현재의 시간 기반 만료 원칙은 유지한다(`leasing.py:41-51`). |
| Lease expiry | 새 acquisition identity의 다음 성공 CLAIM만 generation을 1 증가시킨다. 만료된 acquisition ID의 재전송은 stale이며, 같은 instance가 새 acquisition으로 다시 잡아도 새 generation이다. |
| 이전 owner의 delayed completion/failure | instance 또는 generation이 현재 active lease와 다르면 `STALE_LEASE_GENERATION`으로 거부하며 journal을 append하지 않는다. |
| Delayed heartbeat | `RENEW`는 이전 generation을 되살리거나 expiry를 옮기지 못한다. 현재 owner가 존재하면 stale, 아직 새 owner가 없어도 만료 generation은 stale다. 명시적 `CLAIM`을 새로 해야 한다. |
| Duplicate completion | 같은 current generation의 동일 terminal mutation은 append 없이 기존 결과를 반환한다. payload가 다르면 `IDEMPOTENCY_CONFLICT`; 이전 generation이면 stale 거부다. |
| Lost CLAIM response / same worker retry | 동일 `lease_acquisition_id`의 exact retry는 active 상태라면 최초 durable CLAIM의 같은 generation과 expiry를 재반환하며 append하지 않는다. 만료·supersede 뒤에는 `STALE_ACQUISITION`이고 lease를 되살리지 않는다. `RENEW`는 별도 heartbeat다. |

정상 runner는 active `RUNNING` lease를 pending 목록에서 받지 않고, 만료된 `RUNNING`만
회수한다는 현재 동작을 유지한다(`processing_jobs.py:1865-1904`).

### E. `worker_instance_id`만으로 충분한가?

충분하지 않다.

- instance ID가 restart에서 실수로 재사용되는 ABA를 서버가 구별하지 못한다.
- lease가 만료된 뒤 같은 instance가 재취득했을 때 이전 비동기 heartbeat와 현재
  heartbeat를 ID 하나로 구별할 수 없다.
- 이미 발급된 presigned URL은 Core lease 검사 뒤에도 사용될 수 있다. stable object key에
  대한 늦은 PUT은 instance 비교만으로 취소할 수 없다.

따라서 monotonically increasing `lease_generation`과 generation-scoped upload location이
필수다. generation은 client timestamp가 아니라 store lock 안에서 Core가 발급한다.

### F. database 없이 강제할 수 있는가?

가능하다. 현재 각 store는 check→append→projection update를 하나의 process lock으로
직렬화하고(`processing_jobs.py:1683-1740`), underlying journal은 single writer와 fsync를
보장한다(`durable_journal.py:91-129`, `:304-377`). 같은 임계구역에서 per-job generation
high-water mark를 계산하고 append하면 된다. replay는 journal 순서대로 generation의
단조 증가와 renewal 불변식을 재검증할 수 있다. 새 database는 필요하지 않다.

## 3. 선택지 비교

| 선택지 | Correctness | Stale-owner 보호 | Restart | 운영 복잡도 | 호환·migration | Testability | Blast radius |
|---|---|---|---|---|---|---|---|
| Option A — unique instance + 현 lease | 동시 replica는 구분 | expiry/restart ABA와 delayed URL은 불완전 | ID 재사용 금지에 의존 | 낮음 | 비교적 쉬움 | 쉬움 | 네 store+clients |
| **Option B — unique instance + generation/fencing** | **충분** | **Core mutation과 storage side effect 모두 fence 가능** | 새 ID+새 generation으로 명확 | 중간 | legacy generation 0 reader 필요 | 결정적 interleaving 테스트 가능 | 네 store+clients+artifact storage binding |
| Option C — process별 credential | 정상 운용에서는 구분 | credential이 process와 같은 수명일 때만; delayed PUT 별도 | 매 restart/scale에서 secret 관리 | 매우 높음 | 배포 secret 대량 변경 | 가능하나 auth fixture에 결합 | auth·ops 전체 |
| Option D — 기존 journal/store lock 확장 | 현재 acquire 한 번은 원자적 | identity/generation을 추가하지 않으면 실행 시간 전체 소유권은 보호 못함 | TTL 회수만 가능 | 낮음 | 변경 없음 | 이미 테스트됨 | 낮지만 단독으로 결함 미해결 |

**선택: Option B.** Option C는 아키텍처 요구가 아니라 현재 결함을 피하는 operational
workaround다. Option D의 store/journal primitive는 generation 발급과 재생에 재사용하되,
그 자체가 process identity를 만들어주지는 않는다.

## 4. 권장 corrective contract

### 4.1 정본 불변식

1. **Lease ownership** — Job `J`의 현재 active lease generation `G`를 소유한 worker
   instance만 `J`를 renew, read input, transition, request upload authority, register
   artifact, complete 또는 fail할 수 있다.
2. **Authentication is not ownership** — 인증 credential은 permission과 organization을
   증명하고 lease ownership을 대신하지 않는다.
3. **Monotonic fencing** — 새로운 acquisition identity가 만료됐거나 다른 acquisition을
   대체해 새 소유권을 취득할 때만 `G+1`이다. 같은 active acquisition의 exact CLAIM retry와
   current-owner RENEW는 `G`를 유지한다. generation은 감소·재사용·client 지정되지 않는다.
4. **Expired means fenced** — expiry에 도달한 generation의 모든 mutation과 heartbeat는
   새 owner의 유무와 무관하게 거부된다.
5. **Side-effect fencing** — artifact upload authority와 storage object location은
   generation에 결속된다. stale generation의 늦은 PUT은 current artifact bytes를
   덮어쓸 수 없다.
6. **Replay-verifiable fencing** — generation 단조성, acquisition identity의 immutable
   binding, owner 일치, renewal high-water 규칙은 replay가 재검증한다. 발급 당시 wall-clock
   만료 판정은 replay가 재현하지 않으며 저장된 `expiresAt`으로 현재 유효성만 계산한다.
7. **One credential, many contenders** — 같은 principal의 서로 다른 instance는 서로 다른
   lease contender다.
8. **Authoritative artifact manifest** — 신규 성공 작업의 유일한 artifact authority는 그
   성공 record가 digest로 결속한 `AuthoritativeArtifactManifestV1`이다. **MUST:** durable
   reference가 있는 artifact를 읽는 어떤 authoritative reader도 site/job/artifact ID에서
   현재 object location을 독립적으로 재유도해서는 안 된다.
9. **Attempt-local files** — 서로 동시에 유효할 수 있는 두 processing attempt는 어떤 writable
   temporary path도 공유해서는 안 된다.

### 4.2 identity 생성과 수명

- `worker_instance_id`: worker process 시작 시 secure random UUIDv4로 생성, process 내
  모든 work kind에 유지, restart마다 새 값. env에 고정하거나 volume에 영속하지 않는다.
- `lease_acquisition_id`: wire `leaseAcquisitionId`. CLAIM이라는 **한 소유권 취득 시도**마다
  worker가 생성하는 UUIDv4 idempotency identity다. response가 유실돼도 같은 요청을 재전송할
  수 있도록 그 attempt 동안 유지한다. process restart, lease expiry 뒤 재취득, 명시적 abandon
  뒤에는 반드시 새 값을 만든다. 다른 job·instance·organization에 재사용할 수 없다.
- `lease_generation`: Core가 job별로 발급하는 1 이상 정수. renewal에서는 유지, 만료 후
  재취득에서 증가한다.
- `lease_request_mode`: `CLAIM` 또는 `RENEW`. `RENEW`는 현재 generation을 반드시 보내며
  expiry 뒤 자동 `CLAIM`으로 해석하지 않는다. 이 구분이 늦은 heartbeat가 빈 job을 우연히
  다시 잡는 것을 막는다.
- `worker logical identity`: 현재는 별도 권한에 필요하지 않다. principal ID를 audit actor로
  기록할 수 있지만 owner 비교에는 사용하지 않는다.
- `lease handle`: `{jobId, workerInstanceId, leaseAcquisitionId, leaseGeneration}`. bearer
  secret의 대체물이 아니며, 요청은 여전히 인증되어야 한다.

따라서 네 identity는 분리된다: bearer token은 인증, `worker_instance_id`는 process,
`lease_acquisition_id`는 CLAIM 멱등성, `lease_generation`은 stale actor fencing을 뜻한다.
`worker_instance_id`는 정상 프로세스의 우발적 동일시를 없애지만 같은 credential을 가진
악성 프로세스의 instance 사칭을 막는 secret은 아니다.

#### 4.2.1 CLAIM idempotency truth table

| 실행 | durable 결과 |
|---|---|
| 첫 `CLAIM(R, W, J)` | store lock 안에서 generation `N`을 할당하고 `(R,W,J,principal,organization)→N`을 append/fsync한 뒤 반환 |
| 성공 response 유실 뒤 exact retry `CLAIM(R, W, J)` | active라면 저장된 `N` 재반환; generation 증가와 second append **금지** |
| 같은 `R`의 concurrent duplicate | store lock과 durable idempotency index로 모두 같은 `N`/result를 관측 |
| expiry 뒤 새 `CLAIM(R2, W, J)` | `R2 != R`을 요구하고 generation `N+1` 할당 |
| 다른 owner가 더 높은 generation을 얻은 뒤 old `CLAIM(R, W, J)` | `STALE_ACQUISITION`; old lease 부활·expiry 연장·현재 owner 변경 금지 |
| worker process restart | 새 `worker_instance_id`와 새 `lease_acquisition_id`; 과거 handle 사용 금지 |
| Core restart | journal replay로 동일 acquisition index와 generation high-water 복원; 위 결과 불변 |

같은 `R`을 다른 worker/job/principal/organization 또는 다른 canonical payload에 쓰면 exact retry가
아니며 `IDEMPOTENCY_CONFLICT`다.

`R`의 durable association은 journal 수명 동안 제거하거나 다른 generation에 재결속하지 않는다.
response 유실 뒤 lease가 아직 active인 exact retry는 **최초 성공 response와 동일한 `N`,
`grantedAt`, `expiresAt`을 반환**하며 renewal로 처리하지 않는다. 이미 만료됐거나 더 높은
generation이 current이면 Core는 그 historical association을 확인한 뒤
`STALE_ACQUISITION(originalLeaseGeneration=N)`을 반환할 수 있지만, active lease success로
반환하거나 expiry를 연장하거나 `N+1`을 할당해서는 안 된다. 따라서 exact retry의 결과가
success인지 stale인지는 현재 유효성에 달려도, `R→N` 결속과 generation high-water는 절대로
바뀌지 않는다.

### 4.3 필요한 후속 API 변경

보호된 worker surface 전부가 다음 값을 받거나 반환해야 한다.

- acquire request: `workerInstanceId`, `mode=CLAIM|RENEW`; `CLAIM`에는
  `leaseAcquisitionId`가 필수이고 client generation은 금지한다. `RENEW`에는 현재
  `leaseGeneration`과 그 generation을 만든 `leaseAcquisitionId`가 필수다.
- acquire response: `workerInstanceId`, `leaseAcquisitionId`, `leaseGeneration`,
  `leaseExpiresAt`.
- input, transition, upload-url, artifact registration, completion/failure: instance ID,
  acquisition ID와 generation.
- comparison, design-conformance, region-extraction의 동형 route에도 같은 wire를 적용.

wire 위치는 OpenAPI 구현 단계에서 하나로 결정하되, body가 없는 GET `/input`까지 동일하게
전달할 수 있는 versioned worker header가 가장 작은 변경이다. 예:
`X-KSI-Worker-Instance-Id`, `X-KSI-Lease-Acquisition-Id`, `X-KSI-Lease-Generation`. 이름은
구현 시 OpenAPI와 함께 고정하며 query parameter로는 노출하지 않는다. 현재 OpenAPI가
leaseWorkerId와 expiry만
노출한다는 근거는 `contracts/api/openapi-core.yaml:3740-3790`, `:6775-6827`이다.

### 4.4 필요한 journal/schema 변경

신규 lease event:

```json
{
  "kind": "processing-job-leased",
  "workerInstanceId": "uuid",
  "leaseAcquisitionId": "uuid",
  "authenticatedActorId": "processing-controller",
  "leaseGeneration": 7,
  "expiresAt": "...",
  "renewal": false
}
```

- `renewal=true`이면 이전 record와 instance·acquisition·generation이 같고 expiry만 증가해야
  한다.
- `renewal=false`는 "신규 generation"과 동의어가 아니다. 같은
  `(organizationId, workKind, jobId, workerInstanceId, leaseAcquisitionId)` CLAIM의 exact retry는
  최초 durable result를 반환하고 append하지 않는다. 새 acquisition identity가 실제 새
  ownership을 취득할 때만 이전 high-water mark+1을 append한다.
- Core는 CLAIM record를 journal 수명 동안 idempotency index로 replay한다. 동일 acquisition ID의
  다른 job/instance/principal binding은 `IDEMPOTENCY_CONFLICT`; active exact retry는 같은
  generation; 만료 또는 더 높은 generation 뒤의 retry는 `STALE_ACQUISITION`이고 journal과
  lease를 변경하지 않는다. Core restart도 이 결과를 바꾸지 않는다. 이는
  `AcquisitionCoordinationStore`의 `idempotencyKey + fingerprint` 규율을 lease에 적용한 것이다.

#### 4.4.1 Artifact provenance state와 takeover policy

후속 journal은 다음 세 상태를 구분한다.

- `TEMPORARY_ARTIFACT`: attempt-local workspace 또는 generation-scoped staging object의 bytes.
  durable processing result authority가 없다.
- `CANDIDATE_ARTIFACT`: current lease owner가 등록해 journal에 기록됐지만 아직 해당 generation의
  성공을 뒷받침하도록 accepted되지 않은 manifest entry.
- `ACCEPTED_AUTHORITATIVE_ARTIFACT`: `processing-job-succeeded` record가
  `acceptedLeaseGeneration`과 `artifactManifestDigest`로 결속한 candidate entry.

각 candidate는 최소 `(jobId, artifactId, workerInstanceId, leaseAcquisitionId,
leaseGeneration, kind, lineage, digest/integrity metadata, storage binding)`을 가진다.

**Takeover policy는 POLICY A다.** generation `N`의 candidate/temporary artifact는 generation
`N+1`의 completion, `derivedFrom`, source authority 또는 result projection을 절대로 만족하지
못한다. cross-generation adoption/transfer API는 만들지 않는다. 회수 worker는 자기 generation의
artifact set을 다시 생산·등록해야 한다.

- artifact identity와 `derivedFrom` 해석 범위는 `(jobId, leaseGeneration, artifactId)`다.
- `derivedFrom` 부모는 같은 generation에서 먼저 등록된 candidate여야 한다.
- completion validation은 **완료를 주장하는 current generation의 candidate 집합만** 보고,
  profile-required artifacts와 source-backed lineage를 모두 검사한다. job-wide "어느 generation에든
  matching artifact가 하나 있음" 판정은 신규 record에서 금지한다.
- stale generation의 등록·완료는 거부한다. 이미 durable candidate가 있더라도 accepted가
  아니며 historical/audit projection에만 남는다.
- live와 replay는 성공 record가 가리키는 generation의 candidate set과 manifest digest를
  재계산한다. 누락·다른 generation 혼입·digest 불일치는 store recovery를 fail-closed한다.

#### 4.4.2 Durable authoritative representation

정확한 표현은 journal에 값으로 저장하는 **`AuthoritativeArtifactManifestV1` 구조체**다.
신규 `processing-job-succeeded` event의 accepted processing result payload가
`acceptedLeaseGeneration`, **manifest 전체 값**, `artifactManifestDigest`를 함께 저장한다.
즉 digest만 저장하고 위치를 다시 유도하거나 별도 mutable manifest를 조회하는 표현이 아니다.
성공 record가 그 canonical digest를 결속하고, manifest는 다음을 포함한다.

```text
AuthoritativeArtifactManifestV1
  manifestVersion = "AuthoritativeArtifactManifestV1"
  jobId
  producingWorkerInstanceId
  leaseAcquisitionId
  leaseGeneration
  entries[]
    artifactId / kind / format / lineage / CRS / verticalReference / artifactDigest
    producingWorkerInstanceId / leaseAcquisitionId / leaseGeneration
    primary: ArtifactObjectBinding(objectKey, sha256, sizeBytes, contentType)
    auxiliaryFiles: map<logicalName, ArtifactObjectBinding(objectKey, sha256, sizeBytes, contentType)>
  manifestDigest
```

`auxiliaryFiles`는 basename 목록이 아니라 logical name에서 immutable object binding으로 가는
정렬된 map이다. primary와 각 auxiliary는 generation-scoped object key와 자기 SHA-256/size를
가진다. entry의 producer/acquisition/generation은 manifest 상위 값과 exact-match해야 한다.
`storageObjectKey` 같은 별도 inferred identity는 두지 않으며, primary와 auxiliary의
`ArtifactObjectBinding.objectKey`가 storage locator의 유일한 기록 값이다. manifest
canonicalization은 key 순서와 entry 순서를 고정한다. digest를 계산한 worker는
upload-url 요청에 digest를 보내고 기존 `presigned_put_bound_digest()`를 재사용한다
(`evidence_s3.py:129-162`).

accepted-artifact resolver는 신규 record에서 이 manifest만 읽는다. object key가 누락되거나
manifest digest/entry digest가 맞지 않으면 fail-closed한다. historical journal record가 manifest를
**실제로 포함하지 않을 때만** `LEGACY_UNFENCED` adapter가 종전 결정적 key를 유도할 수 있다.
신규-format record의 누락을 legacy로 추정하거나 conventional key로 fallback해서는 안 된다.
이 규칙은 primary와 모든 auxiliary에 동일하다.

**Normative artifact-authority invariant:** 신규-format 성공 record에서는 durable
`AuthoritativeArtifactManifestV1`가 primary와 모든 auxiliary artifact의 유일한 권위다.
모든 authoritative reader는 이 manifest의 recorded object binding을 **MUST** 사용하고,
manifest가 존재할 때 site/job/artifact identifier나 conventional filename에서 현재 위치를
독립적으로 유도하거나 누락 binding을 보충해서는 안 된다. 다른 generation의 conventional
path에 matching bytes가 있어도 current 또는 accepted artifact가 될 수 없다.

이 MUST는 §1.3에 열거한 download, comparison, checkpoint registration/replay, accuracy
verification, design-vs-actual, report/reference validation, civil comparison eligibility,
processing completion/result validation, spatial-model projection, site-workspace projection과
향후 추가되는 모든 authoritative consumer에 적용한다. inventory 밖의 direct key derivation을
발견하면 그 reader가 resolver로 전환될 때까지 신규 manifest writer와 multi-worker activation은
차단한다.

따라서 stale generation의 conventional path나 늦은 PUT은 물리적 orphan일 수는 있어도,
accepted manifest에 기록되지 않았으므로 authoritative가 될 수 없다.

#### 4.4.3 Worker-local workspace namespace

canonical conceptual namespace는 다음이다.

```text
<work_root>/<work_kind>/<job_id>/<worker_instance_id>/<lease_generation>/
```

- worker는 lease handle을 받은 뒤 이 attempt directory를 owner-only 권한으로 새로 만들고,
  exclusive creation으로 생성한다. 이미 존재하는 leaf, symlink·비정상 기존 경로·다른 owner는
  fail-closed 거부하며 이전 attempt directory를 writable workspace로 재사용하지 않는다.
- 모든 입력, mask, GCP, archive, 추출물과 임시 filename은 이 directory 아래에만 둔다. `all.zip`
  같은 고정 basename은 **attempt directory 안에서만** 허용된다.
- 다른 job, 같은 job의 다른 generation, 다른 worker instance는 항상 다른 directory다.
- process restart는 새 `worker_instance_id`와 새 acquisition을 사용하므로 기존 directory를
  재사용하지 않는다.
- 성공·실패 finalization 뒤 worker는 자기가 만든 attempt directory만 정리한다. parent/root,
  glob, 다른 generation은 삭제하지 않는다. cleanup 실패는 orphan으로 계측한다.
- crash/failed attempt의 leftovers는 authority가 아니며 active lease가 없고 retention이 지난 뒤
  generation-aware GC만 삭제한다. accepted object storage는 workspace cleanup 대상이 아니다.

**MUST:** 동시에 유효할 수 있는 두 processing attempt는 writable temporary path를 하나도
공유하지 않는다. multi-worker에서 `work_dir/all.zip`, `work_dir/<media_id>` 같은 global fixed
path를 사용하는 구성은 금지하며 workspace isolation 전에는 replica를 2 이상 활성화할 수 없다.

### 4.5 compatibility와 migration

1. Reader/resolver를 먼저 배포해 legacy lease event의 generation 누락을 reserved sentinel
   `0`으로 읽고 legacy artifact record만 conventional key로 해석한다. 모든 known reader를
   resolver로 전환하기 전에는 generation-scoped writer를 켜지 않는다. 과거 세대 수를
   추정하지 않는다.
2. 신규 server는 response에 generation을 추가하되 잠시 legacy worker를 관측한다. 이 기간은
   **다중 process 안전 보장 전**이므로 scale-out 금지를 유지한다.
3. 모든 worker client가 instance/acquisition/generation을 echo하도록 배포한다.
4. enforcement를 켜면 active generation 0 lease는 renew/mutate하지 못하고 자연 expiry 후
   generation 1로 회수한다. 강제 rewrite하지 않는다.
5. generation-scoped manifest writer, accepted resolver, attempt-local workspace isolation이 모두
   켜진 뒤에만 multi-process scale-out을 허용한다.
6. 구버전 API field는 reader compatibility 동안 유지하고 새 public enum 이름 변경은 하지
   않는다.

### 4.6 rejection behavior

| 조건 | 결과 |
|---|---|
| instance/generation 누락(강제 이후) | `409 LEASE_FENCE_REQUIRED` |
| 다른 active instance | `409 LEASE_HELD_BY_ANOTHER` |
| 같은 active acquisition의 exact CLAIM retry | 최초 lease result 재반환, append 없음 |
| 만료/supersede된 acquisition ID의 retry | `409 STALE_ACQUISITION`, lease 변경 없음 |
| generation 불일치 또는 만료 | `409 STALE_LEASE_GENERATION` |
| 같은 generation 동일 durable mutation retry | 기존 결과, append 없음 |
| 같은 idempotency identity에 다른 payload | `409 IDEMPOTENCY_CONFLICT` |
| journal sealed | 기존 `503 STORE_UNAVAILABLE` + `Retry-After` 유지 |

다른 조직의 job은 `INV-060`에 따라 지금처럼 unknown과 같은 404를 유지하며 fence detail로
존재를 누출하지 않는다.

### 4.7 observability

구조화 로그와 metric에는 token을 남기지 않고 다음만 남긴다.

- `work_kind`, `job_id`, `worker_instance_id`의 안전한 축약, `lease_generation`.
- acquire/renew/reclaim/stale rejection 수.
- expired lease age, generation별 실행 시간.
- generation-scoped orphan upload 수·bytes·GC 결과.
- attempt workspace collision/refusal과 cleanup orphan 수.
- 동일 principal 아래 concurrent instance 수(운영 용량 신호이지 권한 판정이 아님).

### 4.8 tests

기존 테스트는 same worker renewal, 다른 worker 거부, expiry 회수, active `RUNNING` pending
제외를 고정한다(`tests/contract/test_leasing.py:26-78`, `:93-105`,
`tests/contract/test_processing_jobs.py:1774-1869`). Worker는 이미 `RUNNING` 입력에서 전이를
생략하고 계속 실행하는 동작과 heartbeat renewal을 고정한다
(`tests/contract/test_worker.py:363-370`, `:413-429`). 이 테스트는 유지한다.

관련 기존 inventory는 Core client verdict 처리의 `test_core_client.py`, polling 경쟁의
`test_runner.py`, 공용 lease를 사용하는 `test_comparison_requests.py`,
`test_design_conformance_requests.py`, `test_region_extraction_requests.py`, 실행 orchestration의
`test_comparison_worker.py`와 `test_region_extraction_end_to_end.py`, 상위 흐름의
`test_change_detection_api.py`와 `test_phase2_unified_journey.py`까지 포함한다. 예를 들어 client는
현재 `LEASED`와 `LEASE_RENEWED`를 모두 성공으로 취급하고 다른 owner만 거부한다
(`tests/contract/test_core_client.py:275-295`); runner는 lease conflict가 나면 다음 후보로
이동한다(`tests/contract/test_runner.py:299-319`).

후속 구현은 최소 다음을 추가한다.

1. 같은 credential + 서로 다른 instance의 실제 HTTP 경쟁: 정확히 하나만 lease 획득.
2. 같은 instance + 같은 generation `RENEW`, expiry 후 stale renewal, 새 acquisition identity의
   명시적 `CLAIM`에서만 generation 증가.
3. old generation heartbeat/completion/failure/artifact registration 전수 거부.
4. process crash→expiry→new instance 회수→old delayed request 거부.
5. old presigned URL의 늦은 PUT이 current generation object에 영향을 주지 않음.
6. 동일 artifact retry는 멱등, 다른 digest는 conflict.
7. lease generation journal 역행·누락 renewal·owner 변경 renewal replay 거부.
8. 네 store와 모든 Processing Controller client가 동일 contract를 사용한다는 contract
   inventory test.
9. legacy generation 0 replay와 enforcement 전환 test.
10. 동일 credential replica integration test를 Compose가 아니라 in-process HTTP barrier로
    결정적으로 재현.
11. 최초 CLAIM append 뒤 response 유실→동일 acquisition exact retry가 같은 generation 반환;
    concurrent duplicate도 append 1건; Core restart replay 뒤에도 동일.
12. 만료 후 새 acquisition은 `N+1`, old acquisition retry는 `STALE_ACQUISITION`이며 현재 lease를
    바꾸지 않음.
13. generation N 부분 candidate 뒤 N+1 회수: N+1 completion이 N artifact를 보지 못하고,
    same-generation 재생산만 accepted됨.
14. accepted manifest primary/auxiliary를 download·comparison·checkpoint·design-conformance 및
    metadata consumers 전부가 resolver로 읽고 direct key derivation 신규 호출은 구조 테스트 실패.
15. 서로 다른 job과 같은 job의 다른 generation을 barrier로 실행해 모든 writable path가 다르고,
    한 attempt cleanup이 다른 attempt file에 영향을 주지 않음.

### 4.9 rollout order

1. 공용 fenced lease model, durable acquisition idempotency index와 replay reader, typed verdict 추가.
2. accepted-artifact resolver를 추가하고 위 known reader 전부를 resolver로 전환한다. legacy
   record만 conventional key를 쓰는 inventory test를 먼저 green으로 만든다.
3. 네 store의 generation 발급 및 검증을 같은 변경 단위로 적용.
4. 모든 worker client에 process-lifetime instance ID, acquisition ID와 generation echo 적용.
5. attempt-local workspace isolation을 적용한다.
6. generation-scoped digest-bound upload와 `AuthoritativeArtifactManifestV1`, generation-scoped
   completion/replay validation을 적용한다.
7. production에서 generation enforcement 활성화, legacy active lease expiry 확인.
8. stale rejection/orphan/workspace metric 관측 후에만 worker replica 수를 2 이상으로 확대.
9. 안정화 뒤 legacy generation-less writer compatibility를 제거하되 legacy reader는 보존한다.

## 5. 명시적으로 하지 않는 것

- worker process마다 bearer token을 발급하는 것을 아키텍처 요구로 만들지 않는다.
- lease 전체 시간 동안 store mutex나 file lock을 잡지 않는다.
- clock-based TTL을 fencing generation 대신 사용하지 않는다.
- stale object를 즉시 삭제해 current bytes를 손상시킬 수 있는 destructive cleanup을 하지
  않는다. generation별 orphan은 보존기간 뒤 별도 GC한다.
- generation N의 artifact를 N+1로 adopt하거나 job-wide artifact 검색으로 재사용하지 않는다.
- database나 외부 distributed lock을 이 문제 하나 때문에 도입하지 않는다.

WORKER_LEASE_DESIGN = READY_FOR_IMPLEMENTATION
