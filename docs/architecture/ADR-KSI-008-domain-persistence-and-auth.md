# ADR-KSI-008 — S2 도메인 영속·인증 경계: journal 영속 + bearer 신원 + fail-closed 조립

- 상태: ACCEPTED (2026-07-30, 기술 결정 — §대표자 후속 확인 2건 별도)
- 관련: ADR-KSI-001(FastAPI+PostgreSQL/PostGIS 목표), ADR-KSI-002(Ed25519 서명),
  ADR-KSI-007(이원 산출물), MASTER_PRD §4.1/§5.2/§6.3/§17.2/§19.2/§22.1,
  risk `mission-issuance-unauthenticated-signing-oracle` ·
  `edge-sync-preauth-sequence-lockout` (둘 다 이 ADR의 인증 경계가 해소 경로)

## 맥락

S2(core-domain-query)는 Core에 Site 상태머신 영속, Mission 발급 이력 영속·조회,
Event 트리아지(확정/오탐/배정), 인증·권한을 도입한다. 현재 Core에는 DB 계층이
전혀 없고(pyproject에 드라이버 없음), 유일한 영속 선례는 edge_sync.py의
fail-closed append-only journal(flock 단일 writer·fsync·torn-tail 격리·예외 시
봉인)이다. openapi-core.yaml에는 security scheme이 없고, 무인증 서명 오라클·
사전인증 순번 봉쇄 리스크가 원장에 기록되어 있다.

## 결정

### 1. 영속: append-only journal + 인메모리 projection (PostgreSQL 채택은 연기)

Site/Mission/Event/Audit 영속은 **재사용 DurableJournal**(edge_sync와 동일한
6요소 — 짧은쓰기 루프, fsync 파일+신규생성 시 부모 디렉터리, flock 단일 writer,
torn-tail 격리, 예외 시 봉인, 기동 시 fail-closed 재생) 위의 저장소 모듈로
구현한다. 조회는 재생으로 만든 인메모리 projection이 담당한다.

- ADR-KSI-001의 PostgreSQL/PostGIS는 **목표 유지**. 채택 시점은 별도
  마이그레이션 ADR(운영 표면 S4의 인증·DB 결정과 결합)로 넘긴다. 저장소
  모듈의 공개 표면을 좁게 유지해(등록/전이/조회 메서드) DB 전환 시 교체
  경계가 저장소 클래스 하나가 되게 한다.
- edge_sync.py의 **durable journal 내부(잠금·fsync·복구 경로)는 재작성하지
  않는다** — 무겁게 재검토된 코드의 회귀 위험이 공용 베이스 추출 이득보다
  크다. S2가 edge_sync.py에 가하는 변경은 장착부(라우터/mount)에 국한된
  추가(인증 장비 바인딩·event projection 훅·순번 조회)뿐이다. 중복은 인지된
  부채로, S4 journal 회전 작업에서 통합을 재검토한다.
- 파일 위치는 조립 시 명시 경로만 받는다(저장소 안 기본 경로 상수 금지 —
  repo hygiene). 테스트는 tmp_path 격리.

### 2. 인증: bearer 토큰 + 역할 권한표 + 장비 신원 바인딩

- `Authorization: Bearer <token>`. 서버는 **토큰 원문을 저장하지 않는다** —
  AuthRegistry는 `sha256(token)` digest→Principal 매핑만 보유한다(조립 시
  digest 레코드 주입). JWT/OAuth·사용자 관리 API는 도입하지 않는다(외부 IdP
  없는 파일럿 규모에 과잉 — S3 대시보드 로그인도 이 토큰으로 시작).
- Principal 2종(2-enum 분리 관습):
  - `OPERATOR`(사람): role ∈ {ADMIN, SITE_MANAGER, SAFETY_MANAGER,
    DRONE_OPERATOR, VIEWER}. 권한은 모듈 상수 role→permission 표 하나로만
    결정된다(엔드포인트 산재 금지). **ADR-KSI-015로 3역할(ADMIN·
    FIELD_OPERATOR·VIEWER)로 축소(2026-08-05)** — SITE_MANAGER·
    SAFETY_MANAGER·DRONE_OPERATOR는 FIELD_OPERATOR로 합쳐졌다. 이 절의
    5역할 서술은 최초 도입 당시 기록으로 남긴다.
  - `EDGE_DEVICE`(장비): role 없음. `device_id` 바인딩 필수 — edge-sync
    수신은 **인증 장비의 device_id == 요청 edgeDeviceId**일 때만 수락
    (불일치는 typed 403). 위조 순번 주입이 장비 신원 뒤로 차단되어
    `edge-sync-preauth-sequence-lockout`의 전제가 사라진다. 장비는 자기
    last_sequence 조회 API(복구 경로)를 갖는다.
- 권한 배치(권고안 — §대표자 후속 확인 1, **해소: ADR-KSI-015**): 발급
  (missions:issue)은 DRONE_OPERATOR·ADMIN(DEC-010 운영자 승인), Site
  쓰기·트리아지는 SITE_MANAGER(+트리아지는 SAFETY_MANAGER), VIEWER는 read
  전용.
- 공개 allowlist는 `/health`·`/capabilities`(이미 최소 필드, 감사 #49)와
  FastAPI 기본 문서 라우트(`/openapi.json`·`/docs`·`/redoc` — `create_app(...,
  expose_docs=False)`로 끌 수 있다)뿐이며, 나머지 전 경로는 인증 필수. 401은
  WWW-Authenticate 헤더, 오류 detail에 존재 여부 힌트 금지(열거 오라클 방지
  관습 유지). (재검토 2026-07-30: 최초 서술이 문서 라우트를 누락해 실제와
  어긋났음 — `expose_docs` 스위치 도입으로 정정.)

### 3. 조립: 인증 없는 보호 표면은 존재할 수 없다 (fail-closed 강화)

`create_app`은 다음 결합을 위반한 조립을 ValueError로 즉시 거부한다:

- 보호 표면(edge_sync_store·서명키·site/mission/event store) 주입 시
  `auth_registry` 필수 — 기존의 "무인증 배포 아님" docstring 경고를 코드
  강제로 승격.
- 서명키 ⇒ `mission_store`·`site_store` 필수(발급 미기록·고아 발급 금지 —
  발급 레코드가 durable 기록되기 전에는 201을 반환하지 않는다).
- `edge_sync_store` ⇒ `event_store` 필수(수신은 ACK했는데 트리아지에 안
  보이는 조용한 유실 표면 차단). ACK(201/200)는 event projection까지
  성공했을 때만 반환한다 — projection 실패는 봉인+503, eventId 멱등
  upsert로 재전송이 안전하다.
- 감사 기록은 **별도 audit 저장소가 아니라 각 도메인 journal 레코드 자체에
  내장**한다(인증 주체·전이 전후·사유·evidence·UTC 시각을 전이 레코드의
  필수 필드로) — 이중 journal 원자성 문제(도메인 기록은 성공했는데 감사
  기록이 실패하는 창)를 구조적으로 제거한다. 도메인 journal이 곧 append-only
  감사 원장이며, 이를 끄는 경로는 어떤 역할에도 없다(MASTER_PRD §5.2 Hard
  Limit). 자원 횡단 감사 조회 표면은 S4에서 journal 병합으로 제공한다.
- **경로-세그먼트 식별자는 전부 경로-안전 문자만 허용한다**(2차 독립 재검토
  P1/P2 — `siteId`·`missionId`·`event_key` 구성요소(`edgeDeviceId`·
  `eventId`) 전부 라우터 경로 세그먼트로 쓰인다. `ksi_core.identifiers`가
  SSOT: 영숫자 시작 + 영숫자/`_`/`.`/`-`만 허용, `/`·공백·제어문자·예약
  구분자(`::`) 거부). 검증 없이 기록되면 durable 등록/발급/projection은
  성공하고 이후 상세 조회·전이 라우트에는 영구히 도달할 수 없는 레코드가
  만들어진다 — 최저신뢰 주체(Edge 장비)가 공급하는 `eventId`가 가장 위험한
  경로다. `__init__` 재생 실패로 저장소 생성이 실패하면 `journal.close()`로
  flock을 해제한다(해제하지 않으면 재조립 재시도조차 "다른 프로세스가 소유
  중"으로 오도한다).
- **Edge가 공급하는 시각(`bundle.occurredAt`)은 tz-aware를 강제한다**(2차
  독립 재검토 P2) — naive 값에 `astimezone(UTC)`를 적용하면 서버 프로세스의
  로컬 타임존으로 재해석돼 감사 시간축이 조용히 어긋난다. 서버가 만드는
  시각(`received_at`·전이 `now`)은 이미 이 요구를 만족하므로, 이 가드는
  외부 입력 경계(`classify_edge_bundle`·projection)에만 필요하다.

### 4. 도메인 상태머신 배치

- `SiteStatus`(§6.3 전체 10상태)와 전이표는 `ksi_domain.enums`에
  EventStatus와 대칭으로 둔다. PATROL_READY 도달은 반드시
  MODEL_VALIDATION→PROVISIONAL_AUTONOMY 경유(품질 검증 생략 금지, §6.1).
- **EventStatus는 확장하지 않는다.** event-bundle.v1.2 스키마 enum과 1:1
  잠금이 ingest 검증 강도의 근거다(확장하면 edge가 서버측 워크플로 상태를
  주입 가능). 서버측 배정 이후 워크플로(§17.2 ASSIGNED→ACTION_IN_PROGRESS→
  REINSPECTION_REQUESTED→RESOLVED→CLOSED)는 별도 `TriageStatus` +
  자체 전이표로 둔다(2-enum 분리 관습, P0-5와 동형). 배정 이후 전이는
  status==CONFIRMED_EVENT인 사건에만 허용된다.
- 확정(FINDING→CONFIRMED_EVENT)은 INV-021 게이트를 통과해야 한다 — 전이
  적법성(assert_event_transition)에 더해, 심각도별 Evidence 정책(§17.1)
  충족 검사와 비공백 확정 근거를 요구하고 spatialContext 스냅샷을 감사
  레코드에 남긴다. 서버가 기하학적 위험중첩을 재계산하지는 않는다(그건
  Edge 산출물의 소관 — 서버는 근거 보존과 fail-closed 거부를 소유).

## 비범위

- Evidence 미디어 presigned 업로드·retention 집행·journal 회전(S4)
- 서명키 공급(KMS/HSM) 운영 ADR(ADR-KSI-002 비범위 그대로 — S4)
- Mission 요청 Wizard 추상화(POST /sites/{siteId}/missions planned 스케치 —
  S3 대시보드는 우선 /v1/missions/plans를 직접 호출)
- 사용자 관리·토큰 발급 API(조립 시 digest 주입만 — 운영화는 S4)

## 대표자 후속 확인

1. **역할·권한 매트릭스**(공동 결정 레인): PRD §4.1은 페르소나 카탈로그일 뿐
   RBAC 표가 없어 §2의 권고 매트릭스로 구현했다. 역할 명칭·발급 권한 소재
   (운영자 vs 현장소장)는 대시보드 S3 착수 전 확인을 권장한다.
   **해소 — ADR-KSI-015(2026-08-05)**: 역할을 3개(ADMIN·FIELD_OPERATOR·
   VIEWER)로 축소하고 발급 권한(MISSIONS_ISSUE)을 FIELD_OPERATOR(현장소장
   포함)에 부여해 "실사용자=현장소장"과 "발급은 DRONE_OPERATOR만"의 어긋남을
   닫았다. 자율운영 승인(`SITES_AUTONOMY_APPROVE`)은 신설해 ADMIN에만
   남겼다.
2. **PostgreSQL 채택 시점**(공동 결정 레인): 본 ADR은 파일 journal로 시작하고
   DB 전환을 S4 결합 ADR로 넘겼다. 파일럿 규모·단일 프로세스 전제가 깨지는
   시점(다중 인스턴스·대시보드 동시성)이 전환 트리거다.
