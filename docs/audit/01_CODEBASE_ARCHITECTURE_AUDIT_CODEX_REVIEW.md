# Codex 독립 아키텍처 감사 검토

> 검토일: 2026-09-01
>
> 검토 대상: `docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT.md`
>
> 기준 커밋: `41d9f55270581d9660664f6c23c65ab0d7af0a4a`
>
> 결론: `ARCHITECTURE_AUDIT_REVIEW = VERIFIED_WITH_CORRECTIONS`

이 문서는 원 감사를 정본으로 취급하지 않고 실행 코드, 조립 경로, 배포 설정, 테스트와
권위 문서를 다시 대조한 결과다. 제품 코드는 변경하지 않았다.

## 검토 범위와 판정 원칙

- 요구사항 ID: 직접 기능 요구사항이 아니라 아키텍처 감사다. 관련 불변식은
  `INV-001`, `INV-011/012`, `INV-040/041`, `INV-050`, `INV-060`이며 이번 작업은 이들의
  의미나 강제 지점을 변경하지 않는다.
- Owner module: 감사 문서만 `docs/audit/`가 소유한다.
- Contracts affected: 없음.
- HIL/실장비 가정: 없음. 저장소만으로 확인할 수 없는 물리 capability는 계속
  `NOT_VERIFIED`다.
- Adoption decision: 실행 코드와 권위 문서는 `REFERENCE_ONLY`; 원 감사 결론은 독립 검증
  후에만 채택한다.
- Rollback: 이 검토 문서만 제거하면 된다. 제품 상태·원장·계약에는 영향이 없다.

분류는 주장 전체에 하나의 주 분류를 부여했다. 현재 코드 속성이 사실이어도 의도된 파일럿
제약이면 `REAL_TECHNICAL_DEBT`로 과장하지 않았다. 반대로 안전한 현재 기본값과, 그 상태를
운영에서 바꿀 수단이 없는 문제는 분리했다.

## 저장소 상태 확인

- `main`, 로컬 HEAD와 `origin/main`은 모두
  `41d9f55270581d9660664f6c23c65ab0d7af0a4a`였다.
- 검토 시작 전 작업트리는 dirty였다. `.ai/*`, `.ksi/*`, Phase Registry, civil acceptance,
  Core 조립/API, Dashboard와 계약 테스트에 civil-readiness WIP가 있었다.
- 원 감사 자체도 untracked인 `docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT.md`였다.
- 이 검토는 기존 수정 파일을 되돌리거나 정리·stage하지 않았다. civil-readiness WIP는
  `create_app` 크기와 라우트 수 같은 수치에는 영향을 줄 수 있지만 A~E의 영속 방식,
  writer lock, 배포 topology, DJI Gateway 배선, capability registry 수명에는 영향을 주지
  않는다.

## Finding A

### Claude claim

데이터베이스 기반 영속 계층이 없고, durable state는 주로 append-only JSONL journal에
기록된 뒤 시작 시 메모리 projection으로 전량 재생된다.

### Codex verification

PARTIAL

### Repository evidence

- Core의 현재 결정은 `docs/architecture/ADR-KSI-008-domain-persistence-and-auth.md:20-30`에
  명시돼 있다. `DurableJournal`과 인메모리 projection을 채택하고 PostgreSQL은 후속
  migration ADR까지 연기했다.
- `services/core/src/ksi_core/durable_journal.py:157-177`은 writer lock을 잡고 `_recover()`를
  호출한다. `:203-223`은 모든 segment와 활성 파일을 읽어 `_records`에 넣고,
  `:294-302`는 그 메모리 레코드의 snapshot을 반환한다.
- `services/core/src/ksi_core/app_assembly.py:141-151`부터 production 조립이 이름별 JSONL
  journal과 별도 `edge-sync.jsonl`을 연다. `services/core/src/ksi_core/production.py:499-500,
  556-585`는 `KSI_CORE_DATA_DIR` 아래 `DurableJournal`로 이를 실제 조립한다.
- Core의 `pyproject.toml`에는 PostgreSQL/SQLite/Redis/ORM driver가 없다. 다만 설명 문자열은
  아직 `PostGIS control plane`이라고 적혀 있다.
- 원 감사의 “플랫폼 전체에 DB가 없다”는 표현은 너무 넓다. Edge의
  `edge/manifold-runtime/src/store_forward.cpp`는 SQLite WAL을 사용하고, Core의 대용량
  evidence는 S3-compatible object storage에 둔다. 즉 정확한 명제는 “현재 Core의 도메인
  영속이 DB-backed가 아니다”이다.

### Current runtime behavior

Production Core는 여러 도메인 JSONL을 시작 시 읽고 각 store의 메모리 projection을 만든다.
쓰기 성공은 file/directory fsync 이후에만 반환되며, 대용량 원본은 journal이 아니라
MinIO/S3에 저장한다. Edge store-and-forward는 별도 SQLite 저장소다.

### Intended architecture

결정 가능한 의도다. ADR-KSI-008은 이를 파일럿·단일 프로세스 단계의 명시적 선택으로
기록하고 PostgreSQL/PostGIS 목표를 폐기하지 않았다. `docs/product/MASTER_PRD_v3.0.md:1359-1370`
역시 PostgreSQL/PostGIS와 message bus를 권장 목표 구성으로 유지한다.

### Classification

CORRECT_BUT_INTENTIONAL

### Actual risk

현재 데이터 규모가 커지면 시작 시간과 RSS가 원장 레코드 수에 따라 증가하고, DB가 제공하는
공유 writer·query·online migration 기능을 사용할 수 없다. 그러나 실제 운영 원장 크기와 시작
시간 자료가 없으므로 위험의 현재 심각도는 확정할 수 없다. 기술부채 심각도는 이 finding에는
부여하지 않는다.

### Should we act now?

LATER

### Reason

현재 구현이 설계 결정과 일치하며 파일럿에서 곧바로 데이터 손실을 뜻하지 않는다. 먼저 원장별
record/byte 수, cold-start 시간, peak RSS와 복구 시간을 계측해야 migration 시점을 판단할 수
있다.

### Possible next task

Production-like journal fixture로 원장별 replay/RSS benchmark를 만들고 migration trigger의
수치 기준을 ADR-KSI-008 후속 결정에 기록한다.

## Finding B

### Claude claim

Core는 single-writer locking 때문에 같은 durable storage를 공유하는 여러 인스턴스로 실행할 수
없다.

### Codex verification

VERIFIED

### Repository evidence

- `services/core/src/ksi_core/durable_journal.py:91-115`의 `_acquire_writer_lock()`은
  `flock(LOCK_EX | LOCK_NB)` 실패 시 단일 writer 위반으로 기동을 거부한다.
- `services/core/src/ksi_core/durable_journal.py:126-128`은 process 간 단일 writer와 process
  내부 thread 직렬화를 구분한다. `EdgeSyncStore`도 같은 lock helper를 사용한다.
- `Dockerfile:57`의 production CMD는 uvicorn worker 하나이며 `deploy/compose.yaml:51-89`에
  Core replica 설정이 없다.
- `tests/contract/test_durable_journal.py:234-240`과
  `tests/contract/test_edge_sync_ingest.py:507-516`은 두 번째 writer가 거부됨을 고정한다.
  `tests/contract/test_production_assembly.py:423-425`도 두 앱 조립에 다른 data directory가
  필요한 이유를 이 lock으로 명시한다.
- 독립 실행 결과:
  `test_second_instance_is_refused_while_first_open`,
  `test_second_process_writer_is_refused`, `test_valid_env_builds_fastapi_app` 모두 통과했다
  (`3 passed`).

### Current runtime behavior

같은 `KSI_CORE_DATA_DIR`를 가리키는 두 번째 Core는 첫 journal lock 획득 단계에서 실패한다.
서로 다른 data directory로 둘을 띄울 수는 있지만 두 인스턴스 상태가 갈라지므로 HA가 아니다.
현재 배포는 단일 Core 재시작 모델이며 rolling/blue-green shared-state 전환을 지원하지 않는다.

### Intended architecture

원 감사의 “의도인지 ADR에 없다”는 결론은 틀렸다.
`docs/architecture/ADR-KSI-008-domain-persistence-and-auth.md:138-140`은 파일 journal로 시작하고,
파일럿·단일 프로세스 전제가 깨지는 다중 인스턴스 또는 Dashboard 동시성을 DB 전환 trigger로
명시한다.

### Classification

ALREADY_PLANNED_OR_IN_PROGRESS

### Actual risk

현재는 replica 기반 무중단 배포, 자동 failover, shared-state horizontal scale이 불가능하다.
Core 장애나 배포 중 planned downtime이 생길 수 있다. 다만 현재 실제 SLA, 요청량, 복구목표
증거 없이 원 감사가 매긴 “높음”을 확정할 수 없으므로 기술부채 심각도는 부여하지 않는다.

### Should we act now?

LATER

### Reason

대체 방향과 trigger가 이미 결정돼 있다. 제품이 99.9% Core API 목표를 실제 계약하거나,
다중 인스턴스·무중단 배포가 필요해지는 시점 전에 migration을 시작해야 한다.

### Possible next task

PostgreSQL adoption ADR을 작성하되 store public interface, append-only audit semantics, replay
compatibility, organization isolation, idempotency와 rollback migration을 수용기준으로 둔다.

## Finding C

### Claude claim

문서의 Site/Core, Spatial, Intelligence/Analytics, Planner “서비스”는 각각 독립 배포 프로세스가
아니라 Core 내부 module이다.

### Codex verification

PARTIAL

### Repository evidence

- `docs/architecture/00_SYSTEM_OVERVIEW.md:36-42,128-140`은 Core, Spatial,
  Intelligence, Planner를 책임 단위로 표시하지만 각 상자를 독립 process라고 정의하지 않는다.
- 더 구체적인 accepted decision인 `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md:14-25`는 현재
  별도 repository/service 분리를 불채택하고 bounded context + adapter 구조와 논리적 KSI Cloud
  배포 경계를 채택했다.
- 같은 문서 `:51-68`은 dependency direction을 정의하며, 디렉터리 이름과 deployable process를
  동일시하지 않는다.
- 실제 first-party cloud 실행 단위는 Core, processing worker, Dashboard다. Spatial
  reconstruction은 worker가 NodeODM REST process를 호출하고, change/design/volume
  intelligence도 processing worker가 관련 계산 library를 import해 실행한다. Planner의 정책과
  mission planning은 Core/packages 경계에 있다.
- 따라서 “전부 Core 내부 module”도 정확하지 않다. 일부는 Core에 있고, 고비용 Spatial 및
  Intelligence 작업은 별도 worker process에 있다.

### Current runtime behavior

Core는 정책·계약·원장과 API를, worker는 장시간 Spatial/분석 작업을 수행한다. NodeODM은
별도 third-party process다. Spatial/Intelligence/Planner 이름별로 각각 독립 network service가
배포되지는 않는다.

### Intended architecture

현재 팀과 배포 단계에서는 책임별 bounded context를 유지하고, 실제 독립 배포 주기·권한·팀
소유권이 갈라질 때만 물리 분리를 재검토하는 것이 accepted architecture다. 시스템 개요의 네
상자는 logical responsibility map이다.

### Classification

CORRECT_BUT_INTENTIONAL

### Actual risk

Core에 남아 있는 책임은 독립 fault isolation과 scaling을 얻지 못한다. 반면 가장 무거운
재구성/분석 실행은 이미 worker로 격리돼 있다. 현재 요구사항만으로 각 logical component를
microservice로 쪼갤 근거는 없다. 기술부채 심각도는 부여하지 않는다.

### Should we act now?

NO

### Reason

현재 topology가 accepted boundary와 일치한다. 프로세스 수를 늘리는 것 자체는 제품 능력이나
안전성을 올리지 않고 distributed transaction·배포·관측 비용을 추가한다.

### Possible next task

없음. Core/worker별 CPU, latency, failure domain과 release cadence가 실제로 갈라질 때 deployment
boundary review를 수행한다.

## Finding D

### Claude claim

`services/` 아래 component, 특히 `dji-gateway`,가 현재 executable runtime graph에 참여하지 않을
수 있다.

### Codex verification

PARTIAL

### Repository evidence

- `services/processing-controller/pyproject.toml`은 `ksi-processing-worker` 실행점을 제공하고,
  processing worker는 `services/change-detection`을 실제 import한다. 따라서 `services/` 아래
  component가 전부 runtime 밖이라는 해석은 틀렸다.
- Core는 Docker CMD의 uvicorn module factory로 실행되므로 `[project.scripts]`가 없다는 사실만으로
  runtime 부재를 뜻하지 않는다.
- `services/bim-integration`은 현재 IFC 변환 tool/tests에서, `services/defect-detection`은 선택
  extra와 test 경계에서 사용된다. 둘은 상시 독립 서비스가 아니다.
- `services/dji-gateway/pyproject.toml`에는 server/daemon script가 없고,
  `open_platform_probe.py::main`은 수동 probe다. production Core/worker/compose가 Gateway를 import
  또는 실행하지 않는다.
- 이 부재는 `deploy/compose.yaml:14-20`이 명시한다. HIL에서 adapter가 선택되지 않았으므로 빈
  container나 가짜 runtime을 만들지 않는다.
- `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md:70-100`은 Gateway port/adapter 경계를 미리
  정의하되 실제 path/hardware/firmware evidence 전에는 runtime route와 flag 활성화를 금지한다.

### Current runtime behavior

Change detection은 worker 실행 그래프 안에 있다. DJI Gateway는 library/candidate/probe와 테스트는
있지만 production host가 없고 어떤 concrete device adapter도 활성화되지 않는다. 따라서 자동
Pilot/RC/Dock 전달·업링크·media 경로는 현재 production runtime에서 제공되지 않는다.

### Intended architecture

DJI Gateway의 runtime 부재는 알려진 Phase 3/HIL gate다. Phase Registry의
`capability-evidence-two-axis`는 `GATED`이고 field `VERIFIED`만 route selection에 사용한다
(`docs/goals/PHASE_REGISTRY.yaml:263-269`). System Overview도 candidate software와 실장비
`NOT_VERIFIED`를 구분한다.

### Classification

ALREADY_PLANNED_OR_IN_PROGRESS

### Actual risk

현재 제품은 DJI 자동 동기화 경로를 상용 기능으로 제공할 수 없고 manual/ground ingress 및 복구
경로에 의존한다. 이것은 숨은 runtime 결함이 아니라 사용자에게 `NOT_VERIFIED/OFF`로 유지해야
하는 알려진 제품 gate다. 기술부채 심각도는 부여하지 않는다.

### Should we act now?

LATER

### Reason

실제 M4D + RC Plus 2 + firmware + transport 조합에서 사용할 adapter가 선택되기 전에 host를
만들면 production mock fallback 또는 근거 없는 route가 된다(`INV-040/041` 위반).

### Possible next task

승인된 read-only HIL로 capability별 path를 검증한 뒤, 통과한 port 하나만 별도 host에 조립하고
그 capability의 feature flag만 켜는 runtime acceptance를 작성한다.

## Finding E

### Claude claim

`/capabilities`는 verified capability를 code/config 변경 없이 승격하는 runtime 경로가 없어 계속
빈 응답일 수 있다.

### Codex verification

VERIFIED

### Repository evidence

- `services/core/src/ksi_core/capability/registry.py:57-65`의 registry는 메모리 dict일 뿐 journal이나
  repository adapter가 없다.
- `:80-110`은 초기 `VERIFIED` 등록을 거부하고, `:115-179`의 `transition()`만 구조화
  `SpikeEvidence`와 함께 승격할 수 있게 한다. `:185-193`은 `VERIFIED`만 operational 목록에
  넣는다.
- `:202-223`은 9개 PRD spike를 모두 `SPIKE_REQUIRED`로 seed한다.
- `services/core/src/ksi_core/app.py:561-563`은 registry가 주입되지 않으면 새 registry를 seed하고,
  `:586-607`의 공개 API는 그 registry의 operational 목록만 반환한다.
- production 조립인 `services/core/src/ksi_core/app_assembly.py:534-608`은 `create_app(registry=...)`를
  전달하지 않는다. `production.py`에도 capability evidence/config loader가 없다.
- non-test Core/Gateway runtime에서 Core registry의 `transition()`을 호출하는 HTTP route, CLI,
  startup config 또는 journal replay 경로를 찾지 못했다. 테스트만 직접 transition을 호출한다.
- 독립 실행한 `tests/contract/test_capability_gate.py`는 `35 passed`였다. 즉 무증거 승격 거부와
  미노출 안전 게이트는 정상이다. 이 결과는 durable promotion 경로가 있다는 증거는 아니다.

### Current runtime behavior

기본/production 조립은 시작할 때마다 9개 `SPIKE_REQUIRED`를 메모리에 새로 만들고
`GET /capabilities`에 0개를 노출한다. 테스트처럼 custom registry를 직접 주입한 process 안에서는
VERIFIED를 노출할 수 있지만 재시작 후 보존되거나 production config로 재현되지 않는다.

### Intended architecture

“실기 검증 전 빈 응답”은 `INV-041`과 PRD의 의도다. 그러나 authoritative artifacts는 실기 통과
후 evidence를 Core의 durable registry로 승인·재생하는 운영 절차를 정의하지 않는다. Phase
Registry는 evidence의 두 축과 route-selection gate를 계획하지만 Core registry promotion
mechanism 자체를 구현 완료로 표시하지 않는다.

### Classification

REAL_TECHNICAL_DEBT

### Actual risk

심각도: **중간**.

현재 빈 응답은 안전하지만, 첫 capability가 실제로 HIL 통과해도 운영자가 증거를 durable하게
반영할 수 없다. 임시 code/config 주입으로 해결하려 하면 증거 승인, 감사 계보, 회귀 차단과 재시작
결정성이 배포마다 달라질 위험이 있다. 반대로 이 기능이 없다는 이유로 미검증 capability가
노출되거나 비행이 실행되지는 않는다.

### Should we act now?

YES

### Reason

물리 HIL이 끝난 뒤 급하게 우회 승격하지 않도록, 실제 승격 전에 fail-closed한 durable promotion
contract를 준비해야 한다. 이 작업은 capability를 자동으로 `VERIFIED`로 올리거나 현재 flag를
켜는 작업과 분리해야 한다.

### Possible next task

Core-owned append-only capability evidence store와 replay projection을 설계한다. ADMIN-only 또는
offline signed attestation import, 11-field `SpikeEvidence`, hardware/firmware/path/transport/build
binding, organization/global scope 결정, evidence digest, duplicate/replay 방어, VERIFIED→BLOCKED
회귀, startup replay, public 최소 응답과 내부 감사 조회를 계약 테스트로 고정한다. 초기 data에는
여전히 `SPIKE_REQUIRED/NOT_VERIFIED`만 넣고 feature flag는 OFF로 유지한다.

## 원 감사의 나머지 부채 주장 빠른 대조

| 원 감사 항목 | 독립 판정 | 보정 |
|---|---|---|
| D1 수평 확장 없음 | `VERIFIED`, `ALREADY_PLANNED_OR_IN_PROGRESS` | Finding B. “의도 미상”은 ADR-KSI-008 §대표자 후속 확인과 충돌한다. |
| D2 replay/RSS 선형 | 코드 속성 `VERIFIED`, 현재 심각도 `NEEDS_EXTERNAL_RUNTIME_EVIDENCE` | `DurableJournal._recover()`와 `_records`는 선형이다. 실제 원장 크기·cold-start·RSS가 없어 “높음”은 미검증이다. |
| D3 `create_app` 대형 factory | `VERIFIED`, `REAL_TECHNICAL_DEBT` | 현재 WIP 기준 keyword-only 인자 48개, 727줄이다. 안전 결합표는 유지한 채 assembly bundle 분리가 가능한 중간 이하 유지보수 부채다. |
| D4 capabilities 빈 응답 | `VERIFIED`, `REAL_TECHNICAL_DEBT` | Finding E. 빈 기본값은 의도, durable promotion 부재만 부채다. |
| D5 AsyncAPI 구현 공백 | `PARTIAL`, `REAL_TECHNICAL_DEBT` | `asyncapi-edge.yaml`은 server/protocol/operation 없이 channel/payload만 선언한다. 이를 현재 MQTT runtime topology라고 단정한 원 감사는 과하다. 다만 planned/implemented 상태가 없어 권위가 모호한 것은 낮은 계약 부채다. |
| D6 dji-gateway runtime 없음 | `VERIFIED`, `ALREADY_PLANNED_OR_IN_PROGRESS` | Finding D. HIL-selected adapter 전 host 금지가 명시돼 있다. “완성 서비스”가 아니라 candidate subsystem이다. |
| D7 원본 2회 download | `VERIFIED`, `CORRECT_BUT_INTENTIONAL` | `worker.py:52-56`이 trade-off를 명시한다. storage/worker가 원격으로 분리될 때 재평가한다. |
| D8 fixed polling | `VERIFIED`, `REAL_TECHNICAL_DEBT` | 현재 규모에서는 낮음. worker 수가 늘기 전 jitter/exponential backoff와 server hint를 검토한다. |
| D9 test LOC 비율 | `FACTUALLY_VERIFIED` 성격의 관찰 | 비율 자체는 architecture defect가 아니며 행동 근거가 아니다. |
| D10 schema 세대 병존 | `CORRECT_BUT_INTENTIONAL` | backward reader와 writer-version 선택이 있는 호환 정책이다. 지원 종료 기준을 별도 기록할 가치는 있다. |
| D11 PostGIS 설명 문자열 | `VERIFIED`, `REAL_TECHNICAL_DEBT` | `services/core/pyproject.toml`과 `ksi_core/__init__.py`가 현재 runtime보다 앞선 목표를 현재형으로 쓴 낮은 문서 부채다. |

## 검증 실행

- `uv run --locked pytest -q`로 single-writer 및 production 조립 관련 표적 3개:
  **3 passed**.
- `uv run --locked pytest -q tests/contract/test_capability_gate.py`:
  **35 passed**.
- `create_app(expose_docs=False)`를 `TestClient`로 직접 호출한 결과
  `GET /capabilities`는 HTTP 200과 `{"capabilities": [], "count": 0}`을 반환했고,
  내부 seed 9건은 모두 `SPIKE_REQUIRED`였다.
- AST로 현재 dirty tree의 `create_app`을 측정: keyword-only 인자 48개, 727줄.
- import/search 대조: Core production assembly에 capability registry 주입·promotion 경로 없음,
  processing worker의 change-detection import 존재, DJI Gateway production host 없음.
- 실장비/HIL, production journal 크기, cold-start/RSS, 실제 SLA는 실행하지 않았고 이 문서에서도
  검증됐다고 주장하지 않는다.

## 최종 판정

`ARCHITECTURE_AUDIT_REVIEW = VERIFIED_WITH_CORRECTIONS`

원 감사는 현재 실행 구조를 대체로 정확히 찾았지만 다음 해석은 수정해야 한다.

1. “DB 없음”은 Core 도메인 영속에 한정해야 하며 Edge SQLite와 object storage를 제외하면 안 된다.
2. single-writer와 DB migration trigger는 ADR-KSI-008에 명시된 의도이므로 미인지 고위험 부채가
   아니다.
3. Core/Spatial/Intelligence/Planner는 logical responsibility이고, 전부 Core 내부도 아니며 각각
   microservice여야 한다는 정본 결정도 없다.
4. `services/` 전체가 runtime 밖인 것이 아니다. DJI Gateway만은 HIL 전 의도적으로 host가 없다.
5. `/capabilities`의 빈 기본값은 올바르지만, durable·감사 가능한 promotion 경로 부재는 실제
   중간 기술부채다.

## 가장 가치가 높은 다음 분석

1. **Capability promotion contract 설계**: Finding E의 durable evidence/replay/admin boundary를
   코드 작성 전에 ADR과 acceptance로 고정한다.
2. **Journal 규모·복구 benchmark**: 원장별 bytes/records, cold-start, RSS, replay failure recovery를
   측정해 PostgreSQL migration trigger를 숫자로 만든다.
3. **AsyncAPI authority 정리**: 현재 transport-neutral/planned contract인지, 미래 DJI MQTT
   contract인지 결정하고 `x-status`, server/protocol/operation 또는 명시적 reference-only 표시를
   추가할지 검토한다.
4. **Core assembly decomposition 분석**: 48-argument safety table의 불변식을 유지하면서 domain
   bundle/registrar로 변경 지점을 줄일 수 있는지 설계만 검증한다.
