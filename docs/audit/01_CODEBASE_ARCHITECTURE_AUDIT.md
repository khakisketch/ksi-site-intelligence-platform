# 코드베이스 아키텍처 감사 (읽기 전용)

> 작성 2026-09-01 · 범위: 저장소 실제 내용만. 문서·ADR은 "의도"의 근거로만 인용하고,
> "현재 동작"의 근거는 항상 실행 코드다. 파일명·디렉터리 이름으로 추정한 결론은 넣지 않았다.
> 검증 기준 커밋: `41d9f55` + uncommitted WIP(civil-readiness, 아래 §Unknown 참조).

---

# Executive Summary

이 저장소는 **드론 기반 건설현장 관측 플랫폼**이고, 코드상 실체는 다음과 같다.

**실제로 기동 가능한 프로세스는 3종뿐이다.**

| 프로세스 | 진입점 | 증거 |
|---|---|---|
| KSI Core (HTTP control plane) | `uvicorn ksi_core.production:build_production_app --factory` | `Dockerfile:57`, `services/core/src/ksi_core/production.py:484` |
| 처리 워커 (폴링 데몬, HTTP 표면 없음) | 콘솔 스크립트 `ksi-processing-worker` | `Dockerfile.worker:38`, `services/processing-controller/pyproject.toml:49` |
| Operations Console (Next.js) | `next start` | `apps/dashboard/package.json:9`, `deploy/compose.vm.yaml:30-33` |

여기에 3rd-party 컨테이너 3종(MinIO·NodeODM·Caddy, `deploy/compose.yaml:104-140`,
`deploy/compose.vm.yaml:64`)과, 기체 위에서 도는 **C/C++ 바이너리**(`ksi_psdk_app` DPK,
`edge/psdk-app/CMakeLists.txt:167`)가 붙는다.

**핵심 아키텍처 성격 5가지 (전부 코드로 확인함):**

1. **DB가 없다.** RDBMS·Redis·ORM 의존이 서버 코드 전체에 0건이다(`grep sqlite3|psycopg|sqlalchemy|asyncpg|redis` → services/packages 에서 no match).
   영속은 전부 **append-only JSONL journal + 기동 시 전량 재생 → 인메모리 projection** 이다
   (`services/core/src/ksi_core/durable_journal.py:118` `DurableJournal`).
   `assemble_app` 이 여는 journal 은 30개 + `edge-sync.jsonl` 1개다(`app_assembly.py`).
2. **메시지 브로커가 없다.** 모든 구간이 HTTPS/REST JSON 이다. `contracts/api/asyncapi-edge.yaml`
   이 MQTT 토픽 형태 채널을 선언하지만 이를 구현하는 코드는 저장소에 없다(runtime 코드 전체 mqtt grep → 문자열 주석 3건뿐).
3. **조립이 곧 인가 경계다.** `create_app` 은 store 조합 위반을 `ValueError` 로 기동 자체에서 거부한다
   (`services/core/src/ksi_core/app.py:92` 36행짜리 결합 규칙표 → `app.py:677-689` 검증 루프).
   "인증 없는 보호 표면"은 타입이 아니라 조립에서 막힌다.
4. **Core는 비행제어를 하지 않고, Edge 바이너리는 기본 빌드에서 아무 것도 켜지 않는다.**
   psdk-app 의 native activation·perception·core sync·media offload·wayline upload 는 **전부 `OFF` 기본값**이다
   (`edge/psdk-app/CMakeLists.txt:19,33,52,86,207`).
5. **단일 프로세스 전제가 구조에 박혀 있다.** journal 마다 `flock(LOCK_EX|LOCK_NB)` 단일 writer 강제
   (`durable_journal.py:91`)이고 Core CMD 에 `--workers` 가 없다(`Dockerfile:57`).
   같은 data dir 로 Core 2개를 띄우면 두 번째가 기동 거부된다 — 수평 확장 경로가 현재 없다.

**문서상 4개 서비스(CORE/SPATIAL/INTELLIGENCE/PLANNER, `docs/architecture/00_SYSTEM_OVERVIEW.md:38-44`)는
프로세스가 아니라 Core 프로세스 안의 모듈 + 워커의 역할 분담이다.** 이 차이가 이 감사에서 가장 중요한
"의도 vs 구현"의 간극이다.

---

# Runtime Components

## 1. KSI Core — FastAPI control plane

- **조립**: `services/core/src/ksi_core/app.py:385` `create_app(...)` — 48개 키워드 인자 전부 optional.
  주입된 store 조합에 따라 라우터를 **조건부로 장착**한다(`app.py:700-1105`).
  store 가 없으면 라우트가 404가 아니라 **존재하지 않는다**(설계 의도, `app.py:475-484` docstring).
- **배선 SSOT**: `services/core/src/ksi_core/app_assembly.py:106` `assemble_app(...)` — dev/production 공용.
  `production.py`(env 전용) 와 `scripts/run_core_dev.py`(고정 dev 토큰) 두 진입점이 이 함수만 부른다.
- **모듈 수**: `services/core/src/ksi_core/` 아래 65개 `.py`, 약 40,500 LOC.
  가장 큰 것: `processing_jobs.py`(2,906), `events.py`(2,177), `design_conformance_requests.py`(2,036),
  `source_media.py`(2,011).
- **API 표면**: 실제 장착 경로 **114개**, operation(path×method) **136개**
  (최대 조립으로 `app.openapi()` 실행해 실측). 그 중 `/v1/*` 112개, 공개 2개(`/health`, `/capabilities`).
- **무인증 표면**: `/health`(`app.py:582`), `/capabilities`(`app.py:587`),
  docs 4종(`expose_docs=True` 일 때), 그리고 `assemble_app` 이 얹는 `/metrics`(`app_assembly.py:619`)·
  `/ready`(`app_assembly.py:631`). 이 목록은 테스트 allowlist 로 고정돼 있다
  (`tests/contract/test_api_contract_sync.py:953,1022`).

Core가 소유하는 도메인 원장(각각 별도 journal + 별도 store 클래스):

| 도메인 | 모듈 | 클래스 |
|---|---|---|
| 현장 상태머신 | `sites.py:230` | `SiteStore` (10개 상태, `ksi_domain/enums.py:111`) |
| 사건 projection·트리아지 | `events.py:824` | `EventStore` (7개 상태, `enums.py:46`) |
| 임무 발급 기록 | `mission_records.py` | `MissionStore` |
| Edge 수신 | `edge_sync.py:219` | `EdgeSyncStore` (자체 journal 구현 + 스냅샷) |
| Edge dispatch | `edge_dispatch.py:239` | `EdgeDispatchStore` |
| 원본 사진 번들 | `source_media.py` | `SourceMediaStore` |
| 3D 처리 작업 | `processing_jobs.py:864` | `ProcessingJobStore` |
| 설계면·설계대비·변화영역 | `design_surfaces.py` / `design_conformance_*.py` / `region_extraction_*.py` | 각 store |
| 관측 작업지시·수집 조정 | `observation_work_orders.py`, `acquisition/` | `ObservationWorkOrderStore`, `AcquisitionCoordinationStore` |
| Copilot 대화 | `copilot_conversations.py` | `CopilotConversationService` |

## 2. 처리 워커 (`services/processing-controller`)

- **루프**: `runner.py:380` `run_forever` → `runner.py:189` `run_pending_batch` →
  종류별 `_try_candidates`(`runner.py:126`).
- **처리하는 일감 6종**(같은 프로세스, 우선순위 순): 재구성, 설계면 검증, checkpoint 검증,
  비교, 설계 대비 잔량, 변화영역 추출 (`runner.py:243-310`).
- **한 프로세스 = 동시 1작업.** 동시성은 프로세스 복제로 얻고 경합은 lease 가 막는다
  (`worker.py` 모듈 docstring, `processing_jobs.py:254` `DEFAULT_LEASE_TTL = 15분`).
- **재구성 실행**: `worker.py:274` `run_job` — lease → 입력 수신 → RUNNING → 원본 실측 보고 →
  NodeODM 제출/폴링(폴링 콜백에서 lease heartbeat) → 산출물 등록 → SUCCEEDED.
- NodeODM 은 **무수정 상류 이미지를 REST로만 호출**한다(AGPL 프로세스 경계,
  `deploy/compose.yaml:8-12`, `deploy/compose.yaml:129` digest 고정).

## 3. Operations Console (`apps/dashboard`)

- Next.js 16 / React 19 / next-auth 5 beta (`apps/dashboard/package.json:15-27`), src 약 31,800 LOC.
- **BFF 패턴**: 브라우저는 Core를 직접 호출하지 않는다. 서버 컴포넌트/route handler 가
  `coreFetch`(`src/lib/core-api/client.ts:145`)로 Core에 프록시한다. `client.ts:1` 이 `server-only`.
- **세션**: OIDC/DUAL 모드는 NextAuth 세션의 access token, OPAQUE 모드는 **Core bearer 원문을
  httpOnly 쿠키에 그대로** 담는다(`src/lib/core-api/session.ts:22-36`, 의도적 트레이드오프가 주석에 명시).
- **CSRF 방어**: mutating route handler 마다 `isCrossSiteMutation`(`src/lib/core-api/origin-guard.ts:21`).
- BFF route handler 43개(`src/app/api/**/route.ts`).

## 4. Edge (기체 위)

- **`ksi_edge_runtime` 정적 라이브러리** (`edge/manifold-runtime`, C++17, 약 13,500 LOC .cpp).
  주요 구성: `store_forward.cpp`(1,877 — SQLite WAL 저장후전달), `flight_execution.cpp`(1,840),
  `core_sync_http.cpp`(1,484 — Core REST 어댑터), `media_offload.cpp`(1,085), `media_control.cpp`(960).
- **`ksi_control_plane` 라이브러리**: `FlightSupervisor` 결정적 상태기
  (`include/ksi/control_plane/supervisor.hpp`), 부팅 기본값 `kFailClosed`.
- **`ksi_psdk_app`** (`edge/psdk-app/src/main.cpp`, 2,298 LOC): PSDK 기동 + 제한된 센서 수집.
  DJI Flight Control 헤더/호출 0개가 소스 수준 불변식이고, 빌드 게이트가 이를 강제한다
  (`tools/edge/check_shadow_flight_boundary.py`).
- **`psdk_tap`** (`edge/psdk-tap`, C, 약 2,779 LOC): liveview + FC subscription 콜백을 raw NDJSON 으로
  적는 **수집 전용** CLI — "수집기는 판정하지 않는다"(`edge/psdk-tap/src/main.c:1-6`).
- CLI 도구 4종: `ksi_edge_flight_arm/abort`, `ksi_edge_media_prepare/trigger`
  (`edge/manifold-runtime/CMakeLists.txt:277-292`).
- **Python 동반 CLI 3종**(활성화·동기화용, PSDK 콜백 밖에서 돈다):
  `ksi-mission-contract-consumer`, `ksi-edge-dispatch-activate`, `ksi-edge-dispatch-sync`
  (`packages/mission-contracts/pyproject.toml:8-11`).

## 5. `services/` 아래에 있지만 **서비스가 아닌 것** (중요)

| 경로 | 실제 정체 | 증거 |
|---|---|---|
| `services/dji-gateway` (2,785 LOC) | 서버 진입점 없음. `open_platform_probe.main` CLI 하나뿐. **어떤 런타임도 import 하지 않는다** | `pyproject.toml` 에 `[project.scripts]` 없음; import 검색 결과 `tests/test_workspace_smoke.py:15` 뿐 |
| `services/change-detection` (2,234 LOC) | 워커가 import 하는 계산 라이브러리 | `processing-controller/comparison_worker.py:46`, `design_conformance_worker.py:47` |
| `services/defect-detection` (9,430 LOC, 대부분 vendored VMamba) | 선택 extra. 런타임 서비스 없음 | `.github/workflows/ci.yml` `defect-detection-extra` job |
| `services/bim-integration` (467 LOC) | `tools/convert_ifc_design_surface.py` 전용 | import 검색 결과 tools/tests 뿐 |

`deploy/compose.yaml:20-21` 이 이를 명시적으로 인정한다 — "DJI Gateway: 실제 HIL에서 선택된 adapter가
아직 없으므로 빈 컨테이너나 가짜 runtime을 만들지 않는다."

---

# Data Flow

## A. 관측 → Core (Edge 상향)

```
기체 센서/PSDK 콜백
  └─ ksi_psdk_app (perception OFF 기본) → EventBundle 후보
      └─ store_forward.cpp  SQLite WAL 로컬 원장 (Candidate → ACK → evidence 등록 → PUT → prune)
          └─ core_sync_http.cpp:1250  POST {core}/v1/edge-sync/event-bundles
              └─ Core edge_sync.py:721  라우터
                  └─ SyncLedger.ingest (packages/event-contracts/.../offline_sync.py:173)  멱등 판정
                      └─ EdgeSyncStore._append_durable (edge_sync.py:592)  fsync 후에만 ACK
                          └─ EventStore projection (events.py:824)
```

- **ACK는 durable 이후에만.** `edge_sync.py:9-25` 가 이 순서를 문서화하고 코드가 지킨다.
- 멱등 규칙(4중 신원·순번·digest)은 Core가 재구현하지 않고 `SyncLedger` 에 위임한다
  (`edge_sync.py:3-6`).
- 상태 비대칭이 store-forward 쪽에도 있다: ACK 하나로는 evidence 미완료 candidate 를 지우지 않는다
  (`edge/manifold-runtime/include/ksi/edge/store_forward.hpp:3-9`).

## B. Core → Edge (임무 하향, **pull 모델**)

```
운영자 → Console → POST /v1/missions/plans (mission_plans.py)
    Ed25519 서명 Mission Contract + KMZ 짝 발급 (mission_issuance.py, signing.py:70)
        └─ MissionStore durable 기록 후에만 201
            └─ EdgeDispatchStore 서명 MissionDispatchEnvelope 발급 (edge_dispatch.py:239)
                └─ 장비가 GET /v1/edge-sync/missions/next  (edge_dispatch.py:802)
                    └─ 로컬 서명 검증 → activation → POST .../activation-receipts (edge_dispatch.py:844)
```

Core가 장비에 push 하지 않는다 — 장비가 당긴다. 미확인 dispatch 가 남아 있으면 Core는 같은 것을
계속 돌려준다(`packages/mission-contracts/.../edge_dispatch_sync.py:10-14`).

## C. 사진 → 3D → 분석 (긴 폐루프)

```
SD카드 오프로드(수동) → tools/ingest_watch.py → tools/upload_source_bundle.run_sync
  ├─ POST /v1/missions/{id}/source-media           등록(신고값 = 주장)
  ├─ presigned PUT → S3/MinIO                      Core는 바이트를 중계하지 않는다
  ├─ POST .../source-media/seal                    봉인 = digest 확정 (source_media.py:7-20)
  └─ POST /v1/missions/{id}/processing-jobs        입력을 요청이 주장할 수 없다(봉인 번들에서 유도)
        └─ 워커 runner.py 폴링 → worker.py:274 run_job
              ├─ GET .../input            mediaId + 다운로드 URL만. 신고 sha256/해상도는 안 준다
              ├─ 실측 보고 → Core compare_measurements 가 판정
              ├─ NodeODM REST 제출/완주
              └─ 산출물 등록 → RUNNING→SUCCEEDED (assert_succeeded_is_backed, processing_jobs.py:322)
                    └─ 비교/설계대비/체적/변화영역 요청 → 같은 워커 루프가 소비
```

**"워커에게 정답을 주지 않는다"** 가 이 흐름의 설계 축이다(`source_media.py:33-45`) — 되읊기가
구조적으로 불가능하도록 입력 응답에서 신고값을 뺐다.

## D. 브라우저 데이터 경로

브라우저는 Core 토큰을 갖지 않는다. 모든 조회가 Next 서버(BFF)를 거치고, 대용량 산출물만
presigned URL 로 스토리지에서 직접 받는다(`evidence.py:14-19`).

---

# Control / Authority Flow

## 권한 모델 (`services/core/src/ksi_core/auth.py`)

- **Principal 4종**(`auth.py:97`): `OPERATOR`(사람, role 필수, device_id 금지),
  `GATEWAY_DEVICE`(RC/Dock), `EDGE_DEVICE`(기체), `PROCESSING_WORKER`(워커).
- **역할 3종**(`auth.py:83`): `ADMIN` / `FIELD_OPERATOR` / `VIEWER`.
- **권한표는 한 곳뿐**(`auth.py:352` `_ROLE_PERMISSIONS`). 장비·워커는 role 표와 무관한 **고정 집합**이다
  (`auth.py:391` `_EDGE_DEVICE_PERMISSIONS`, `auth.py:402` `_GATEWAY_DEVICE_PERMISSIONS`,
  `auth.py:409` `_PROCESSING_WORKER_PERMISSIONS = {PROCESSING_WORK}`).
- **`PROCESSING_WORK` 는 어느 role 에도 매핑되지 않는다** — 사람이 처리 작업 상태를 손으로 찍을 수 없다
  (`auth.py:29-33`).
- **인증 경로 이원화**: 사람은 OIDC JWT(`oidc.py`, JWKS 만료 시 fail-closed),
  장비/워커는 sha256 digest opaque 토큰. 원문 토큰은 서버 어디에도 없다(`production.py:44-52`).
- **조직 경계**: 인증된 요청의 `organizationId` 가 ContextVar 로 흐르고
  (`auth.py:449` `_REQUEST_PRINCIPAL`), MissionStore 가 이를 읽어 타 조직 mission 을 "없는 것"으로 만든다
  (INV-060).

## 제어 권한 경계 (INV-001)

코드가 실제로 강제하는 것:

1. **Core에 프레임 단위 비행제어 엔드포인트가 없다.** 114개 경로 중 조종 명령 표면 0개
   (`app.py:1-12` 모듈 docstring이 이를 명시하고 경로 목록이 이를 뒷받침).
2. **Edge 바이너리에 DJI Flight Control 심볼이 없다.** 소스 include·직접 호출·최종 ELF 외부 참조·
   vendor archive 정의까지 4층으로 검사한다(`tools/edge/check_shadow_flight_boundary.py:1-30`).
   금지 대상은 `DjiFlightController_*` 뿐 아니라 `DjiWaypointV3_UploadKmzFile`+`Action(START)` 조합까지 확장됐다.
3. **`FlightSupervisor` 는 기체를 멈추지 않는다.** "KSI가 새 행동을 요청해도 되는가"만 판단한다
   (`edge/manifold-runtime/include/ksi/control_plane/supervisor.hpp:8-13`).
4. **Edge는 사건을 확정할 수 없다.** `CONFIRMED_EVENT`/`DISMISSED` 를 실어 보내면
   `STATUS_NOT_EDGE_ASSERTABLE` 로 거부하고 ACK 하지 않는다(`events.py:34-42`).
5. **LLM은 승인·발급·좌표 권한이 없다.** Copilot 은 typed tool allowlist 안에서만 돌고
   (`copilot.py:22-24` 라운드/호출/응답 크기 상한), presigned URL·object key 류 키는 어댑터가 거부한다
   (`copilot_openai.py:22-30` `_FORBIDDEN_KEYS`).
6. **capability 노출 게이트**: `/capabilities` 는 `list_operational()`(VERIFIED만)만 부른다
   (`app.py:594`, `capability/registry.py:185`).

## 상태 전이 권한

- 현장 상태 전이표·SUSPENDED 복귀 규칙 SSOT: `packages/domain/src/ksi_domain/enums.py`
  (`assert_site_transition`). `sites.py` 는 위임만 한다.
- **재생(replay)도 같은 전이표를 다시 탄다** — journal 을 손으로 고쳐 FAILED를 SUCCEEDED로 바꿀 수 없다
  (`processing_jobs.py:50-55`, `sites.py:22-28`).

---

# Persistence

## 계층 1 — DurableJournal (`services/core/src/ksi_core/durable_journal.py`)

6요소가 한 클래스에 모여 있다:

| 요소 | 위치 |
|---|---|
| POSIX short-write 루프 | `durable_journal.py:340` `_append_durable` |
| 파일 + **부모 디렉터리** fsync | `durable_journal.py:82` `_fsync_dir` |
| flock 단일 writer | `durable_journal.py:91` `_acquire_writer_lock` (`LOCK_EX \| LOCK_NB`) |
| torn-tail 격리 | `durable_journal.py:225` `_read_records` (개행 없는 마지막 줄은 "기록된 적 없음") |
| 예외 시 봉인 | `durable_journal.py:304` `append` → `JournalSealedError`(`:78`) |
| 세그먼트 회전 | `durable_journal.py:379` `_rotate_if_needed` (기본 OFF, production 기본 64MiB) |

**회전은 아무 것도 지우지 않는다**(`durable_journal.py:40-47`) — 폐기는 보관 정책의 소관이다.

## 계층 2 — 도메인 store

각 store 가 `__init__` 에서 journal 전량 replay → 인메모리 dict projection 구성
(`sites.py:238-263` 이 전형). 오염·불법 전이는 `*RecoveryError` 로 **기동 거부**(fail-closed).
동시성은 store 별 `threading.Lock` (core 안 20+ 모듈에서 사용).

## 계층 3 — EdgeSyncStore (별도 구현)

`edge_sync.py:219`. journal 회전 대신 **스냅샷**을 쓴다 — 재기동 비용이 파일 크기가 아니라
항목당 정규화+sha256 이기 때문(`edge_sync.py:36-40`). 신뢰 방향이 명시돼 있다:
스냅샷은 journal 이 부정하는 것을 주장할 수 없고, journal 이 스냅샷 경계와 어긋나면 기동 거부.

## 계층 4 — 오브젝트 스토리지

`EvidenceStorage` Protocol 이 Core가 아는 유일한 포트(`evidence.py:115`).
유일 구현체는 S3 호환 어댑터(`evidence_s3.py`, `boto3` 는 optional extra `ksi-core[s3]`).
**Core는 미디어 바이트를 중계하지 않는다** — presigned URL만 발급하고 TTL은 분 단위
(`evidence.py:31-33`: upload 15분 / view 5분). 객체 키는 **서버가 만든다**
(`evidence.py:239` `build_object_key`) — 경로 탈출·타 현장 덮어쓰기 차단.
허용 content-type 은 화이트리스트(`evidence.py:40-50`) — HTML/SVG/JS 계열 거부.

## 계층 5 — Edge 로컬

SQLite WAL 저장후전달(`edge/manifold-runtime/include/ksi/edge/store_forward.hpp:1`).
EventBundle 계열과 원본 사진 회수가 **같은 DB·같은 연결·같은 뮤텍스**를 쓴다 — 테이블만 나눈다
(`store_forward.hpp:52-58`, 이유: 두 WAL이 전원 손실을 서로 다른 시점에 견디면 "사진은 올라갔는데
사건은 없다"는 복구 상태가 생긴다).
미디어 스풀은 **창고가 아니라 컨베이어**다 — Manifold 여유 8.6GB vs 20MP 3,000장 ≈ 30GB
(`media_offload.hpp:1-14`).

## 백업 대상 (명시적)

`ksi-data` 명명 볼륨(원장) + `deploy/signing-keys/` **호스트 디렉터리 바인드**
(`deploy/compose.yaml:60-73`). 서명키가 명명 볼륨이 아닌 이유가 주석에 있다 — 컨테이너 재생성마다
새 키가 생기면 이미 발급된 Mission Contract 가 전부 검증 실패한다.

---

# Networking / Transport

| 구간 | 프로토콜 | 인증 | 증거 |
|---|---|---|---|
| 브라우저 → Console | HTTPS (Caddy) | NextAuth 세션 쿠키 | `deploy/Caddyfile:6-17` |
| Console → Core | HTTP (사설망) | Bearer (세션 토큰 전달) | `client.ts:106-110`, `compose.vm.yaml:35` |
| Edge → Core | HTTPS | EDGE_DEVICE opaque bearer | `core_sync_http.cpp:1250` |
| Edge → 스토리지 | HTTPS presigned PUT | URL 자체가 인가 | `core_sync_http.hpp:26-32` |
| 워커 → Core | HTTP | PROCESSING_WORKER bearer | `runner.py:418`, `core_client.py:612` |
| 워커 → NodeODM | HTTP REST | 없음(사설망) | `http_node_odm.py` |
| Core → OIDC IdP | HTTPS (JWKS) | 없음 | `oidc.py` |
| Core → AI provider | HTTPS `/v1/chat/completions` | API key 파일 | `copilot_openai.py:1-7` |

**포트 노출**: 기본 compose 는 전부 `127.0.0.1` 바인드(`compose.yaml:75,120-122,136`).
외부 VM 조합은 이를 `!reset []` 로 없애고 Caddy 만 80/443 을 연다(`compose.vm.yaml:8,23,27,69-71`).

**TLS 정책이 Edge 쪽에서 타입으로 분리돼 있다**: `HttpsEndpoint::{kCore, kEvidenceUpload}`
(`core_sync_http.hpp:28-32`) — "Core bearer 를 presigned URL 로 보내지 않는다"를 테스트로 증명할 수
있게 만든 것. 실행기 계약은 HTTPS·피어 검증·리다이렉트 거부·응답 크기 상한이고,
어댑터가 크기 검사를 **한 번 더** 한다(fail-open 방지).

**Edge 전송은 기본 빌드에서 꺼져 있다**: `KSI_ENABLE_CURL_EDGE_TRANSPORT` OFF
(`edge/manifold-runtime/CMakeLists.txt:60`), `KSI_PSDK_APP_ENABLE_CORE_SYNC` OFF
(`edge/psdk-app/CMakeLists.txt:52`).

---

# Failure Handling

## 조립 단계 (기동 전)

- **결합 규칙표 36행**(`app.py:92-357`) → `app.py:677-682` 루프가 위반 시 `ValueError`.
  예: `edge_sync_store` 만 있고 `event_store` 가 없으면 "ACK는 했는데 트리아지에 안 보이는"
  유실 표면이므로 기동 거부.
- **보호 표면 + auth 없음 = 거부**(`app.py:683-689`).
- **production 은 환경변수 검증을 무거운 부수효과 전에 전부 끝낸다**(`production.py:497-534`).
- **서명키를 부트스트랩하지 않는다**(`production.py:22-33`) — 있는 키만 로드.

## 런타임

| 실패 | 처리 | 증거 |
|---|---|---|
| journal append 예외 | 즉시 봉인, 이후 모든 append 거부 | `durable_journal.py:304` |
| 봉인된 원장 존재 | `/ready` 503 (`/health` 는 200 유지) | `app_assembly.py:631-645` |
| torn tail | 잘라내고 정상 기동(경고 로그) | `edge_sync.py:27-33` |
| 요청 검증 422 렌더 실패 | 전용 핸들러로 항상 JSON | `app.py:571` `mount_validation_error_handler` |
| 워커 lease 만료 | `list_pending` 이 만료 RUNNING 도 후보로 반환 → 다른 워커가 회수 | `processing_jobs.py:1865`, `runner.py:57-70` |
| ODM 장시간 작업 | 폴링 콜백에서 lease 갱신(heartbeat) | `worker.py:410-419` |
| 워커 작업 중 예외 | 종류 불문 `Exception` 포착 → FAILED 전이 시도 → 원 예외 재던짐 | `worker.py:25-40` |
| Core 장애 | 그 폴링 라운드를 빈 것으로 취급, 워커 프로세스는 살아남음 | `runner.py:154-157` |
| lease 경합 패배 | 실패가 아님 — 다음 후보로 | `runner.py:175-179` |
| work_dir 누적 | 성공·실패 모두 끝에 정리 | `worker.py:47-54` |
| Edge heartbeat 상실 | `kDegraded` → `kFailClosed`, 신규 행동 금지(진행 중 행동은 유지) | `supervisor.hpp:29-33` |
| Edge NTP 점프 | 미래 heartbeat 허용창 1초, 초과 시 기록 거부(영구 FAIL_CLOSED 래치 방지) | `supervisor.hpp:48-51` |
| 서버 통신 단절 | 유효한 로컬 계약은 무효화되지 않음(INV-012) | `supervisor.hpp:5-9` |

**없는 것**: 지수 백오프. 워커는 고정 `poll_interval` 로 쉬고, 일을 하나 했으면 즉시 다음 라운드로 간다
(`runner.py:412-416`). Core쪽 재시도 정책도 없다 — 판정은 호출자 몫이라고 명시
(`core_client.py:6-13`).

**보관 정책 집행에 스케줄러가 없다**(의도적): `retention.py:19-24` — "데이터를 지우는 코드가
아무도 부르지 않았는데 도는 것보다, 운영자가 부르는 편이 낫다". 실행은 `tools/enforce_retention.py:116`,
판정만 하는 dry-run 은 `tools/retention_scheduler.py:79`.

---

# Configuration

## Core (전부 환경변수, 기본값 없음 = fail-closed)

**필수**: `KSI_CORE_DATA_DIR`, `KSI_CORE_SIGNING_KEYS_DIR`, `KSI_CORE_S3_ENDPOINT`,
`KSI_CORE_S3_BUCKET`, `KSI_CORE_PRINCIPAL_TOKENS_JSON`, `KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE`
(`production.py:499-509`).

**기능 플래그 6종** (전부 rollout 게이트, 기본 보수적):

| 변수 | 기본 | 의미 |
|---|---|---|
| `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED` | false | 발급 전 RC readiness 강제 |
| `KSI_CORE_ACQUISITION_COORDINATION_ENABLED` | true | AcquisitionRun 원장 |
| `KSI_CORE_PROCESSING_PROFILE_ISSUANCE_ENABLED` | true | |
| `KSI_CORE_LANDXML_INGRESS_ENABLED` | false | |
| `KSI_CORE_CHECKPOINT_VALIDATION_ENABLED` | false | 신규 checkpoint 등록만 차단 |
| `KSI_COPILOT_ENABLED` | false | 외부 AI 호출 |

**인증 모드**: `KSI_CORE_HUMAN_AUTH_MODE ∈ {OPAQUE, DUAL, OIDC}`(`auth.py:117`),
OIDC 는 `RS256`/`ES256` 만 허용(`production.py:105`).

**계약 writer 버전**: `KSI_CORE_MISSION_CONTRACT_WRITER_VERSION ∈ {1.2, 1.3}`.
`1.3` 은 서명키 + issuerId + durable sequence store 를 모두 요구한다(`app.py:625-631`).

**문서 표면 차단**: `KSI_CORE_EXPOSE_DOCS=0` 이면 `/docs`·`/redoc`·`/openapi.json`·
`/docs/oauth2-redirect` 4개 라우트가 존재하지 않는다(`app.py:441-450`).

## 워커

`KSI_WORKER_CORE_BASE_URL`, `KSI_WORKER_CORE_TOKEN`, `KSI_WORKER_NODEODM_BASE_URL`,
`KSI_WORKER_WORK_DIR` (필수), + poll/heartbeat 간격·로그 형식·동적객체 모델 디렉터리
(`runner.py:418-482`).

## Console

`CORE_API_BASE_URL`(필수, `src/lib/core-api/env.ts:12`),
`KSI_DASHBOARD_*`(배포 프로필·인증 모드·공개 origin·OIDC·세션 시크릿 파일, `compose.vm.yaml:34-43`),
`DASHBOARD_COOKIE_INSECURE_HTTP`(HTTPS 없는 사내망 대비 명시적 스위치, `session.ts:41-46`).

## 런타임 환경 전제 (코드에 박힌 것)

- Python 3.12 고정(`pyproject.toml:5` `>=3.12,<3.13`).
- uv workspace: `packages/*` + `services/*`. `references/`·`edge/`·`apps/` 는 **의존성 해석에서 제외**
  (`pyproject.toml:28`).
- 컨테이너 이미지가 전부 digest 로 고정되고 CI가 이를 검사한다
  (`tools/check_runtime_image_pins.py`, `.github/workflows/ci.yml`).
- Core/워커 컨테이너는 non-root(uid 10001/10002)이고 **런타임에 아무 것도 쓰지 않는다**
  (venv 직접 실행 — `uv run` 이 요구하는 쓰기 권한을 제거해 RCE 지속화 경로를 없앰, `Dockerfile:38-50`).
- 명명 볼륨 소유권을 `init-volumes` 컨테이너가 한 번 맞춘다(`compose.yaml:33-51`).

---

# Test Architecture

## 규모 (실측)

| 스위트 | 수량 |
|---|---|
| Python 테스트(전체 수집) | **4,262개** (`pytest --collect-only`) |
| `tests/contract` | 173 파일 / 77,754 LOC |
| `tests/replay` | 9 파일 / 3,238 LOC |
| `tests/hil` | 2 파일 / 1,631 LOC |
| `tests/e2e` | 2 파일 / 1,481 LOC |
| `tests/golden` | 6 파일 / 1,398 LOC |
| Dashboard vitest | 63 파일 |
| Dashboard Playwright | 5 spec |
| C++ ctest | manifold-runtime 12, psdk-tap 2, psdk-app 1 |

## 게이트의 성격별 분류

**① 계약 동기화 게이트** (`tests/contract/test_api_contract_sync.py`, 1,313 LOC)
문서가 구현보다 낡는 사각지대를 닫는다:
- 비-planned OpenAPI 경로가 실제 앱에 존재하는가 (`:373`)
- 문서가 선언한 메서드가 실제로 있는가 (`:412`)
- 구현된 `/v1/*` 가 문서에서 빠지지 않았는가 (`:432`)
- allowlist 밖 경로가 전부 `security` 를 선언하는가 (`:448`)
- **무인증 라우트가 allowlist 밖에 없는가** — `create_app` 경로(`:996`)와 `assemble_app` 경로(`:1029`) **둘 다**
- 대시보드 TS 타입이 계약 스키마와 일치하는가 (`:767`)
- 문서·구현 간 수치 제약 드리프트 (`:1240`) + **그 allowlist가 낡지 않았는가** (`:1282`)

실측 결과: 문서 115경로 중 미구현 **1개뿐**이고 그것은 `x-status: planned` 로 표시돼 있다
(`/sites/{siteId}/missions`, `contracts/api/openapi-core.yaml:4892-4893`). 구현됐는데 문서에 없는 경로는 0개.

**② 조립 게이트** (`tests/contract/test_core_app_assembly.py`)
결합 규칙 4갈래 전수 — 오염된 부분 조립이 조용히 기동하지 못함을 증명.

**③ 언어 간 conformance 벡터**
`contracts/conformance/action-intent-verdicts.v1.json` 을 **Python과 C++가 각자 실행**해
같은 verdict 를 내야 한다(`tests/contract/test_action_intent_conformance.py` +
`edge/manifold-runtime/tests/conformance_tests.cpp`, 벡터는 `tools/generate_action_intent_vectors.py`
가 `.hpp` 로 생성). 같은 방식이 `payload-canonicalization.v1.json` 에도 있다.

**④ 재생 결정성** (`tests/replay/test_replay_determinism.py`)
event_fingerprint·observation_hash·anchor_position·transitions 4값이 실행 순서·입력 순서와
무관하게 동일한지 실행으로 확인.

**⑤ 종단(소프트웨어)** (`tests/e2e/test_aol1_mapping_autonomy.py:1-22`)
무엇이 진짜이고 무엇이 대역인지 파일 상단에 명시: Core는 진짜(`assemble_app`), HTTP를 실제로 거침,
사진도 실제 JPEG. **기체·촬영·재구성 엔진은 대역.** 결론을 스스로 한정한다 —
"실제로 날 수 있다"가 아니라 "서버 쪽 결선에 끊긴 곳이 없다", 완료 등급은 `Backend Ready`.

**⑥ HIL 도구 검증** (`tests/hil/`)
숫자가 나오는지가 아니라 "위조/오기된 입력을 실제로 거부하는가", "CLI로 판정 기준을 완화할 수
없는가"를 본다.

**⑦ 환경 게이트로 skip 되는 실연동 테스트**
`test_odm_live.py`, `test_odm_two_epoch_live.py`, `test_evidence_s3_live.py`,
`test_civil_live_workflow.py`, `test_mixercseg_detector.py`(가중치 없으면 skip).
**CI에서는 돌지 않는다.**

## CI (`.github/workflows/ci.yml`)

`gates` job: `uv lock --check` → `uv sync --locked` → 이미지 digest 핀 검사 → ruff → mypy
(`packages services tests tools`) → pytest → 저장소 위생 → reference import 가드 →
reference gitlink 핀 → PSDK 핀.
별도 job: `defect-detection-extra`(x86_64 이식성), `dashboard`(tsc/eslint/vitest/next build),
`edge-control-plane`(C++17 `-Werror` + ASan/UBSan ctest), `edge-psdk-tap`,
`edge-manifold-target`(QEMU arm64 실기 툴체인 재현 + 툴체인 드리프트 검사 + ABI 게이트 +
device Python 3.8 호환 스모크).

---

# Architectural Invariants

코드가 **실제로 강제하는** 불변식만 적는다(문서 선언이 아니라 실행 경로 기준).
정본 ID 목록은 `docs/product/DOMAIN_INVARIANTS.md`.

| # | 불변식 | 강제 지점 |
|---|---|---|
| A1 | 인증 없는 보호 표면은 조립될 수 없다 | `app.py:683-689` |
| A2 | 절반 조립으로 기동하지 않는다 (36행 결합표) | `app.py:92`, `app.py:677-682` |
| A3 | durable fsync 이후에만 ACK | `edge_sync.py:592`, `durable_journal.py:340` |
| A4 | append 중 예외 = 봉인, 재시작 전 모든 쓰기 거부 | `durable_journal.py:304` |
| A5 | 하나의 journal 에 writer는 하나 | `durable_journal.py:91` (flock) |
| A6 | 재생은 live 와 같은 전이표를 탄다 (원장 수기 조작 무효) | `processing_jobs.py:50-55`, `sites.py:22-28` |
| A7 | 종단 상태에서 나가는 전이 없음 | `processing_jobs.py:48-50` |
| A8 | `SUCCEEDED` 는 산출물 + 입력 실측 두 근거가 있어야 열린다 | `processing_jobs.py:322` `assert_succeeded_is_backed` |
| A9 | 워커는 판정하지 않는다 — 잰 값만 보고, 대조는 Core | `source_media.py:28-45` |
| A10 | 입력 사양은 요청이 주장할 수 없다 (봉인 번들에서 유도) | `processing_jobs.py:9-18` |
| A11 | 객체 키는 서버가 만든다 | `evidence.py:239` |
| A12 | Core는 미디어 바이트를 중계하지 않는다 | `evidence.py:1-8` |
| A13 | presigned URL 발급은 항상 권한 검사 뒤 | `evidence.py:14-19` |
| A14 | Edge는 사건을 확정/기각할 수 없다 | `events.py:34-42` |
| A15 | 사건 신원은 장비 스코프 (`edgeDeviceId::eventId`) | `events.py:21-30` |
| A16 | VERIFIED 아닌 capability 는 운영 API로 새지 않는다 | `capability/registry.py:185`, `app.py:594` |
| A17 | VERIFIED 승격에는 구조화 SpikeEvidence 11필드 필수 | `capability/registry.py:141-147` |
| A18 | Mission Contract 서명은 digest가 아니라 정규화 바이트열에 | `mission_contracts/signing.py:30-48` |
| A19 | 검증 실패는 예외가 아니라 typed verdict (fail-closed) | `signing.py:160` `SignatureVerdict` |
| A20 | 서명키는 런타임이 만들지 않는다 (서버 재시작이 발급 계약을 무효화하지 않도록) | `production.py:22-33` |
| A21 | 토큰 원문은 프로세스 어디에도 없다 (sha256 digest만) | `auth.py:3-7`, `production.py:44-52` |
| A22 | 인증 실패 사유는 단일 문구로 접힌다 (열거 오라클 방지) | `auth.py:432` |
| A23 | 사람은 `PROCESSING_WORK` 권한을 가질 수 없다 | `auth.py:409`, `auth.py:29-33` |
| A24 | 조직 경계는 read filter 로 중앙 상속된다 | `auth.py:449-465` |
| A25 | KSI 바이너리는 기체를 움직이지 않는다 (4층 빌드 게이트) | `tools/edge/check_shadow_flight_boundary.py` |
| A26 | Edge 부팅 기본값은 fail-closed ("증거 없음"≠"정상") | `supervisor.hpp:14-17` |
| A27 | Edge 상태기는 시계를 읽지 않는다 (replay/HIL 결정성) | `supervisor.hpp:56-59` |
| A28 | ActionIntent 판정은 두 언어가 같은 벡터로 증명한다 | `contracts/conformance/action-intent-verdicts.v1.json` |
| A29 | 감사 원장은 별도 저장소가 아니라 도메인 레코드에 내장 (끄는 경로 없음) | `sites.py:9-13`, `events.py:9-18` |
| A30 | 회전은 아무 것도 지우지 않는다 (폐기는 보관 정책 소관) | `durable_journal.py:40-47` |
| A31 | 외부 AI는 승인·발급·좌표 권한이 없고 반출 미동의 현장은 fail-closed | `copilot.py`, `app_assembly.py:365-370` `ai_egress_policy` |
| A32 | 최초 매핑 임무는 공간모델 없이 생성 가능해야 한다 (반순환) | `docs/architecture/00_SYSTEM_OVERVIEW.md:216`, 경로 생성기 시그니처 |

---

# Suspected Architectural Debt

> 심각도는 "지금 제품에 미치는 영향" 기준이다. 이론적 개선점은 넣지 않았다.

## D1 — Core 수평 확장 경로가 구조적으로 없다 (높음)

`flock(LOCK_EX|LOCK_NB)`(`durable_journal.py:91`) + 인메모리 projection + `--workers` 없는 uvicorn
(`Dockerfile:57`) 의 조합이다. 같은 data dir 로 Core 2번째 인스턴스를 띄우면
`JournalRecoveryError("다른 프로세스가 journal 을 소유 중")` 로 죽는다.
**결과**: 롤링 배포·blue-green·가용성 이중화가 현재 배포 모델에서 불가능하다.
compose 에도 replica 선언이 없다. 이것이 의도된 선택인지(파일럿 규모) 미인지 부채인지는
ADR에 명시돼 있지 않다 — `ADR-KSI-008` 은 저장소 설계를 다루되 확장 축을 다루지 않는다.

## D2 — 재기동 비용·메모리가 원장 크기에 선형 (높음)

모든 store 가 `__init__` 에서 전량 replay 한다(`sites.py:243`). 세그먼트 회전은 **파일만** 나누고
재생 총량과 메모리 상주량을 줄이지 않는다(`durable_journal.py:40-47`이 명시).
EdgeSync 만 스냅샷으로 이 비용을 잡는다(`edge_sync.py:36`). 31개 원장 중 스냅샷이 있는 것은 1개다.
**징후**: 운영 기간이 길어질수록 부팅 시간과 RSS 가 단조 증가하고, 상한이 코드 어디에도 없다.

## D3 — `create_app` 이 단일 신(神) 팩토리 (중간)

48개 인자 · 720줄(`app.py:385-1105`) · 36행 결합표. 새 표면 하나를 추가할 때마다
인자 + 표 1행 + mount 블록 + `_provided` dict 1줄 + `app_assembly` 배선이 **5곳** 동시 수정된다.
결합표 자체는 훌륭한 안전장치지만(D3는 그 표를 없애자는 뜻이 아니다), 팩토리와 표가
한 함수에 붙어 있어 변경 지점이 흩어진다.

## D4 — `/capabilities` 는 운영 배포에서 구조적으로 항상 빈 응답이다 (중간)

`CapabilityRegistry` 는 인메모리이고(`capability/registry.py`), journal 이 없고,
`transition()` 을 호출하는 **HTTP 라우트도 조립 경로도 없다**. `assemble_app` 은
`registry=` 를 넘기지 않으므로 매 기동마다 9개 SPIKE_REQUIRED 만 시드된다
(`app.py:576-578`, `registry.py:216-223`).
따라서 `GET /capabilities` 는 항상 `{"capabilities": [], "count": 0}` 다.
이는 fail-closed 로서는 정확하지만, **"VERIFIED로 올릴 수 있는 경로가 없다"**는 뜻이기도 하다 —
실기 검증이 끝나도 코드 변경 없이는 반영할 수 없다.

## D5 — `contracts/api/asyncapi-edge.yaml` 이 구현 없는 토폴로지를 서술한다 (중간)

MQTT 토픽 3종(`ksi/v1/edge/{edgeId}/status|mission-contract|event`)을 선언하지만
브로커 클라이언트가 저장소에 없다. 계약 동기화 게이트는 이 파일에 대해 **`$ref` 신선도만** 검사한다
(`test_api_contract_sync.py:469`) — 채널 자체가 구현되는지는 아무도 안 본다.
OpenAPI 쪽은 양방향 대조가 있는데 AsyncAPI 쪽은 없어서, 권위 체인 4위가 여기서만 검증 공백이다.

## D6 — `services/dji-gateway` 가 런타임 호스트 없는 완성 서브시스템 (중간)

2,785 LOC + 자체 테스트 + capability catalog + pinned HTTPS/Unix bridge 가 있는데
어떤 프로세스도 import 하지 않는다. 의도적 보류임이 문서화돼 있고
(`compose.yaml:20-21`, `00_SYSTEM_OVERVIEW.md` "실제 장비 HIL은 전 항목 NOT_VERIFIED")
그 판단 자체는 옳다. 부채는 **이것이 uv workspace 멤버로 lock·mypy·pytest·CI 표면에
계속 올라 있다**는 점이다 — 쓰이지 않는 코드가 매 빌드 비용을 낸다.

## D7 — 워커가 원본을 두 번 내려받는다 (낮음, 명시적 수용)

`worker.py:50-55` 가 스스로 밝힌다: 실측용 1회 + NodeODM 제출용 1회.
매핑 번들이 수십 GB 인 것을 감안하면 스토리지 egress 가 2배다. "스토리지와 워커가 보통 같은
인프라에 있다"는 전제 위의 수용이고, 그 전제가 깨지는 배포(클라우드 S3 + 온프렘 워커)에서는
비용 성격이 달라진다.

## D8 — 백오프 없는 고정 간격 폴링 (낮음)

`runner.py:412-416`. Core가 장시간 다운되면 워커는 같은 간격으로 계속 두드린다.
현재 규모에서는 문제가 아니지만 워커 프로세스를 늘리면 선형으로 증가한다.

## D9 — 테스트 코드가 대상 코드의 1.9배 (관찰)

`tests/contract` 77,754 LOC vs `services/core` 40,580 LOC.
테스트가 사실상 명세 역할을 하는 구조라 이 비율 자체가 결함은 아니지만,
계약 변경 1건의 비용이 구현보다 테스트 쪽에서 더 크게 발생한다는 뜻이다.

## D10 — 계약 세대가 병존한다 (낮음)

`contracts/schemas/` 에 `event-bundle` v1/v1.1/v1.2, `mission-contract` v1/v1.1/v1.2/v1.3,
`processing-artifact` v1/v1.1/v1.2/v1.3, `coverage-report` v1/v1.1 가 공존하고
writer 버전은 환경변수로 고른다(`KSI_CORE_MISSION_CONTRACT_WRITER_VERSION`).
읽기 측 호환은 `parse_mission_contract`(`mission_contracts/models.py`)가 흡수한다.
현재는 관리되고 있으나 세대가 더 늘면 조합 폭발 지점이다.

## D11 — 문서 문자열 드리프트 (사소)

`services/core/pyproject.toml:4` 가 Core 를 "…·PostGIS control plane" 이라고 서술하지만
PostGIS·PostgreSQL 의존이 저장소 전체에 없다. 신규 기여자를 오도할 수 있는 유일한 잔존 서술.

---

# Unknown / Unverified Areas

> 이 절은 "감사자가 확인하지 못한 것"과 "저장소가 스스로 미검증이라고 선언한 것"을 나눈다.

## U1 — 저장소가 스스로 `NOT_VERIFIED` 로 선언한 것 (문서 + 코드 일치 확인함)

- **DJI capability 9종 전부 SPIKE_REQUIRED**: M4D 카메라 프레임 접근, 렌즈 전환·촬영 제어,
  Yaw/짐벌 API 지연, FlyTo/Hold/Rejoin, 회피 동시동작, 동시 제어권, Manifold 이벤트 네트워크 경로,
  Dock 3 운용, 비행시간/발열 (`capability/registry.py:202-212`).
- **Manifold Edge SW 실기 0회** (`00_SYSTEM_OVERVIEW.md` 현재 도달점 표).
- **온보드 임무 실행(WaypointV3)**: candidate 소스는 있으나 strict built-target gate 가
  candidate 링크를 거부하는 상태 — 지원으로 표시하지 않음.
- **RC 게이트웨이 전 항목 NOT_VERIFIED** — adapter 미선정.
- **외부 AI provider 실연동 없음** (`KSI_COPILOT_ENABLED=false` 기본).

## U2 — 빌드 기본값이 OFF라서 "기본 산출물의 실제 동작"이 미상인 영역

`edge/psdk-app` 의 기본 DPK는 PSDK 기동 + 제한된 센서 수집만 한다. 아래는 전부 opt-in 이고,
**켠 상태의 실기 동작을 이 감사는 확인할 수 없다**:

| 옵션 | 기본 | 위치 |
|---|---|---|
| `KSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION` | OFF | `psdk-app/CMakeLists.txt:19` |
| `KSI_PSDK_APP_ENABLE_PERCEPTION` | OFF | `:33` |
| `KSI_PSDK_APP_ENABLE_CORE_SYNC` | OFF | `:52` |
| `KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD` | OFF | `:86` |
| `KSI_PSDK_APP_ENABLE_WAYLINE_UPLOAD_ONLY` | OFF | `:207` |
| `KSI_ENABLE_TENSORRT` | OFF | `manifold-runtime/CMakeLists.txt:53` |
| `KSI_ENABLE_CURL_EDGE_TRANSPORT` | OFF | `:60` |
| `KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION` | OFF | `:65` |

## U3 — CI에서 실행되지 않아 감사 범위 밖인 것

- **실연동 테스트 전부**(NodeODM live, S3 live, civil live workflow, MixerCSeg 실모델).
  env 변수가 있어야만 돌고 CI에는 없다.
- **Playwright E2E 5종** — `ci.yml` dashboard job 은 `vitest`+`next build` 까지만 돈다.
- **arm64 실기 이미지의 런타임 동작** — QEMU 빌드/ctest/ABI 게이트까지만 검증된다.

## U4 — 이 감사가 확인하지 못한 것 (정직한 공백)

1. **운영 중인 원장의 실제 크기·기동 시간.** D1/D2 의 심각도는 원장 규모에 비례하는데,
   `.dev-data/` 는 개발 스냅샷이라 운영 값의 근거가 아니다. **확인 필요.**
2. **`/metrics` 를 실제로 스크레이프하는 Prometheus 배치가 있는지.** compose 에 스크레이퍼가 없다 —
   표면만 있고 소비자가 저장소 안에 없다.
3. **보관 정책이 실제로 집행된 적 있는지.** 스케줄러가 없으므로 수동 실행 이력에 달렸는데
   그 이력은 저장소에 없다. **확인 필요.**
4. **`hil_raw_logs/` 9개 세션의 판정 결과.** 디렉터리명이 `PENDING-SN`/`PENDING-AIRCRAFT` 로
   끝나는 것이 다수라 미결 상태로 보이지만, 이름만으로 결론 내지 않는다 — 내용 대조 필요.
5. **Console 의 OPAQUE 모드가 운영에서 쓰이는지.** OIDC 모드면 D-급 부채가 아니지만
   `compose.vm.yaml` 은 OIDC 를 강제하고 `compose.yaml` 은 인증 모드를 지정하지 않는다.

## U5 — 진행 중인 미커밋 변경 (감사 시점 상태)

`git status` 기준 civil-readiness 기능이 Core·Console·계약·테스트에 걸쳐 작업 중이다:
- 신규: `services/core/src/ksi_core/civil_readiness.py`(`CivilReadinessProjector:154`,
  `mount_civil_readiness:403`), `apps/dashboard/src/components/site/CivilReadinessCard.tsx`,
  `apps/dashboard/src/lib/civil-readiness.ts`, `tests/contract/test_civil_readiness.py`
- 수정: `app.py`, `app_assembly.py`, `openapi-core.yaml`, `test_api_contract_sync.py`,
  `test_core_app_assembly.py`, dashboard 타입/페이지

계약 동기화 게이트 기준으로는 이미 정합 상태다(문서 115 경로 중 미구현은 planned 1건뿐).
**이 감사의 다른 결론은 이 WIP 에 의존하지 않는다.**

---

## 부록 — 이 감사가 사용한 검증 방법

- 실행 코드·헤더·CMake·compose·CI 정의를 직접 읽음. 파일명 기반 추론은 배제.
- API 표면은 **최대 조립으로 앱을 실제로 만들어** `app.openapi()` 를 실행해 실측
  (114 경로 / 136 operation), OpenAPI 문서와 집합 차분.
- 테스트 수는 `pytest --collect-only -p no:cacheprovider` 실측(4,262).
- 서비스 간 결합은 import 검색으로 확인 — 특히 "서비스처럼 보이지만 호스트가 없는" 4개
  (`dji-gateway`, `change-detection`, `defect-detection`, `bim-integration`)를 이 방법으로 판별.
- 이 문서는 파일을 하나도 수정하지 않았다(신규 생성한 이 문서 제외).
