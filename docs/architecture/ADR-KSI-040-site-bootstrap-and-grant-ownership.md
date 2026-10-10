# ADR-KSI-040 — Site bootstrap and grant ownership (F-01)

- Status: ACCEPTED — F-01 contract decision (2안 + B안 + C1–C5, 서버 발급 ID); 구현은 별도 상세 계획 승인 후
- Date: 2026-10-10 (제안 v1 2026-10-09 159e7c5, v2 2026-10-09 ff3a5d0)
- Human approval: 2026-10-09 "2안 + B안" 승인과 C1–C5 채택 지시("권장되는방향으로 개선해주세요"),
  2026-10-10 상세 구현 계획 승인(서버 발급 Site ID·Org당 기본 1,000 상한 포함).
  승인 provenance와 상세 계획 결속은
  [rebaseline 원장](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)의
  "F-01 상세 구현 계획 승인 — 2026-10-10" 항목을 따른다.
- Origin: [F-01 결정 제안 v2](../superpowers/plans/2026-10-09-f01-site-bootstrap-and-grant-ownership.md)
  (SHA256 `bc5143828d9be6e4195d045d74cfedc18b2dda9c8dd4ba4bb29ed9732e599305`),
  상세 계획 `/home/ksi/.opencode/plan/2026-10-10-0103-feat-f01-bootstrap-grant-implementation-plan.md`
  (SHA256 `cbba7fe5924a4caca810b9c52a476d212222a133e6282dd70dde44d12ba649ca`, repo 밖 승인 산출물)
- Preserves: ADR-KSI-015 role/permission 표(ADMIN=고객 본사 관리자 포함), ADR-KSI-036/037/038/039의
  권위·수치 의미·취득 제외 경계, INV-020/040/050/051/053/055/060/061.
- Runtime status: 이 ADR은 계약 결정 기록이다. 구현·검증의 실제 상태와 한계는 rebaseline 원장의
  구현/수용 항목으로만 판단한다 — 이 문서만으로 runtime 수용·배포·고객 수용을 추정하지 않는다.

## Context

첫-flow 온보딩의 앞단이 막혀 있었다. mapped OIDC 신원은 `POST /v1/sites` 가 검토된 route matrix
밖이라 전부 403이었고(의도된 현 계약), 허용된 Site에 WorkArea를 만들어도 v1 registry의 명시 area
목록에 새 id가 자동 포함되지 않아 **만든 구역을 만든 사람이 다시 쓸 수 없었다**. 해법 후보 중
"KSI 전담 생성"(1안)은 신규 Site마다 마찰과 은폐성 downgrade 위험이, "전체 허용"(3안)은 감사 위반이
있어 기각됐다. 감사 지침은 "no simple allowlist widening", "do not broaden all resources",
"not silently downgraded to precreated Sites"였다.

또한 고객이 고른 siteId의 전역 중복 조회는 다른 조직의 Site 존재를 알려주는 오라클이 된다
(INV-060 — 조직 밖 자원은 존재 여부도 노출하지 않는다). 중복 **응답**을 동일하게 만드는 것만으로는
충분하지 않다.

## Decision

### D1 — 지정 고객 self-bootstrap(2안)

새 Site를 만드는 주체는 registry v2의 명시 capability `SITE_BOOTSTRAP`를 가진 지정 고객
principal이며, 자기 조직 한정이다. 일반 operator·VIEWER는 capability가 없으면 403이다.
`SITE_BOOTSTRAP`은 role에서 추론하지 않고 permission으로 변환하지 않는다 — `ADMIN`이라는 사실은
capability를 주지 않으며(고객 본사 관리자→ADMIN 매핑은 ADR-KSI-015 유지), VIEWER+capability도
`SITES_WRITE` 부족으로 403이다.

### D2 — site 단위 grant level(B안)

`allowedWorkAreaIds: null`은 허용된 Site들의 모든 area(site 단위)를 뜻하고, 명시 배열은 최소권한
모드로 유지한다. site-level grant는 그 Site에 속한 WorkArea에만 상속되고 다른 Site·Org로
전파되지 않는다 — WorkArea 판정은 항상 서버 원장의 부모-자식 관계(`WorkArea.site_id` = 요청 경로
site)와 site grant를 먼저 통과한다. explicit area 목록이 다른 site의 area id를 담아도 부모 site가
scope 밖이면 404다.

### C1/C5 — scope-only와 역할 경계

v2 grant level은 자원 가시성 범위만 넓힌다. 쓰기 권한(role→permission), 데이터 제공/반출 권리,
AI 동의, data residency, provenance, 검사·admission·정량 적격성, 감사 기록을 하나도 바꾸지 않는다
(scope·permission·policy는 각각 독립 게이트). 이 원칙은 `allowedSiteIds: null`에도 동일하다.
"ADMIN=KSI 전용"이라는 해석은 근거가 없다 — KSI의 통제는 역할 라벨이 아니라 **capability 발급
경로(보호 registry)** 에 있다.

### C2 — capability 수명주기 전체를 KSI가 통제

발급뿐 아니라 변경·회수도 KSI가 통제하는 보호 registry 배포로만 이루어진다. 고객에게 자기·타인
재위임 표면은 없다. JWT claim은 권한을 부여하지 않는다(매핑이 유일한 출처). 회수·축소는 registry
재발급/`REVOKED`로 유효해지고 반영 시점은 재시작/재배포 절차를 따른다.

### C3 — 신규 Site 접근의 출처와 서버 발급 ID

생성(부트스트랩) capability와 접근 scope는 **분리된 발급 결정**이다:

- capability만으로는 어떤 Site도 보이지 않는다(생성도 불가능하다 — capability가 생성의 전제).
- 접근은 KSI가 발급하는 scope가 결정한다: `allowedSiteIds: null` = 자기 org 전체(신규 Site 포함).
  이 발급이 있어야 새 Site가 생성자에게 즉시 보인다. explicit site 목록과 함께 발급하면 새 Site는
  재발급 전까지 생성자에게도 보이지 않는다(계약상 허용 — lockout을 숨기지 않는다).
- **생성 행위는 scope를 확대하지 않는다**: per-site grant 레코드를 만들지 않는다.
- **신규 v2 bootstrap은 서버 발급 Site ID를 쓴다**: 요청은 canonical UUID
  `bootstrapRequestId`(클라이언트 요청 키)만 보내고, 서버가 무작위 UUID 기반 경로-안전
  `siteId`를 발급하며 응답의 `site.siteId`가 유일한 후속 참조다. 재시도는
  `(organizationId, principalId, requestKey)` namespace의 durable binding(등록 레코드 한 건에
  원자적으로 기록)으로 해소된다 — 같은 키·같은 payload는 같은 Site, 바뀐 payload는 typed 409
  `BOOTSTRAP_REQUEST_CONFLICT`, 내부 ID 충돌은 재시도 후 generic 503. scope 축소 후 재시도는
  숨겨진 영수증을 반환하지 않고 미지 Site와 같은 404로 접는다. 기존 v1/opaque의 client 지정 ID
  계약과 저장된 ID는 불변이다.

### 문법과 fail-closed

- `oidc-subject-registry.v1`: 기존 그대로 — 두 scope 필드가 필수 배열, capability 표현 없음.
- `oidc-subject-registry.v2`: `capabilities` 필수(알려진 값만; 지금은 `SITE_BOOTSTRAP`) + 두 scope
  필드 **필수**(명시 null 또는 배열). 필드 누락·invalid·미지원 버전은 로드 실패다 — 누락이
  null(전체 허용)로 승격되는 fail-open 경로를 만들지 않고, v2 실패 후 v1 재시도도 하지 않는다.
  파싱에 성공한 매핑만 route matrix 경계 marker를 세운다(nullable scope가 미검토 route로 새지 않게).
- opaque 토큰 설정은 capability 발급 표면이 아니다 — `registryScoped`/`capabilities` 예약 필드
  주입은 부팅 실패다.
- Org당 bootstrap 상한: `KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG`(기본 1,000). 0·음수·비정수는
  부팅 실패(0은 "상한 없음"이 아니다). 상한은 측정된 용량이나 SLA가 아니며 legacy opaque 등록에
  소급 적용하지 않는다.

### Rollback

- 권한 rollback: v1 명시 배열 재발급+재시작으로 capability와 wildcard scope를 제거할 수 있다.
  자원·journal은 삭제하지 않는다(append-only). 목록은 KSI가 승인한 실제 최소권한만 담고, 승인
  목록이 v1 필드 한계(512개)나 파일 크기 한계를 넘으면 **목록을 자르지 않고 전환을 거부**한다.
  wildcard를 v1에 표현할 수 없으면 compatible reader와 v2 기존 scope를 유지한 채 capabilities만
  빈 배열로 재발급해 생성만 회수한다 — 이때 wildcard scope rollback 완료를 주장하지 않는다.
- 코드 downgrade: 신규 binding metadata를 읽는 리더 호환 증거(replay fixture) 없이는 허용하지
  않는다. journal의 bootstrap metadata를 지우는 것은 rollback이 아니다.

## Consequences

- 첫-flow "등록" 앞단이 계약상 열린다: 지정 고객 org-admin이 자기 조직 Site와 WorkArea를 만들고
  즉시 다시 조회·사용할 수 있다. 실제 수용은 D3 (a)–(f) 증거(실제 OIDC/DUAL, 브라우저, 재시작,
  회수, 부정·회귀 매트릭스)로만 판단한다.
- 계약 변경은 additive다: v1 파일·일반 operator·opaque/worker/MCP 계약, role 표, 권리·동의
  게이트, 수치 의미가 비회귀다. 새 dependency·서비스·endpoint가 없다.
- 잔여 한계(문서화된 그대로): org 전체 모드에는 개별 Site 제외 표현이 없다(필요 시 explicit 목록
  전환). 다중 프로세스 동시 writer를 지원한다는 주장은 하지 않는다(journal 단일 writer 경계).
  서버 발급 ID는 legacy opaque client-ID 경로의 전역 존재 oracle을 없애지 않는다 — 그 경로는
  기존 계약 유지가 우선이며 잔여 위험으로 기록된다.
- 이 ADR은 F-02..04(보호 스토리지/실자료·소비자/반복 수용), 배포 활성화, P7-A2/Task3, 고객/EXT-VAL을
  닫지 않는다. 비행·자율 취득·고객 production 재구성 경계(ADR-KSI-039)를 변경하지 않는다.
