# F-01 결정 제안 — Site bootstrap과 WorkArea grant 소유권 (2026-10-09)

- Status: **PROPOSAL FOR WRITTEN REVIEW** — 실행 권한 아님. F-01은 material auth/bootstrap
  결정이므로 Human 결정 전에는 어떤 코드·route·registry·grant도 변경하지 않는다.
- Date: 2026-10-09
- 결정 요청: D1(Site 생성 권한 소유) · D2(WorkArea grant 모델) · D3(F-01 완료 증거)
- 근거: [P5 통합 감사](../../audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md)의 F-01 행과
  "Smallest justified successor direction", ADR-KSI-037 D1("KSI performs the initial setup…"),
  INV-060, rebaseline spec RB-04.

## 0. 요약 (결정 카드)

| 질문 | 옵션 | 권장 |
| --- | --- | --- |
| D1 새 Site를 누가 만드는가 | 1안 KSI 운영자 전담(초기설정) / **2안 지정 고객 org-admin(명시 capability)** / 3안 scoped operator 전체 허용 | **2안** |
| D2 새 WorkArea 사용 grant | A안 정적 열거 유지 / **B안 grant level(사이트 단위 all-areas)** / C안 Core grant store | **B안** |
| D3 F-01 완료 증거 | 보호 registry v2 + 실제 auth 모드 + browser/API 온보딩 재현 + 교차 org 404 + actor 감사 | §4 |

권장 조합(2안+B안) 승인 시: KSI는 계약 단계에서 org와 org-admin capability를 발급하고(초기설정),
지정된 고객 org-admin이 자기 org의 Site를 스스로 만들며, 이미 허용된 site 안의 WorkArea는
level grant로 생성 즉시 사용 가능해진다. 일반 operator·교차 org·기존 grant 의미는 넓히지 않는다.

## 1. 현재 실제 동작 (검증 근거)

감사가 남긴 이번 결정 대상 두 행:

> "Create Site … Scoped OIDC allowlist lacks this method/path; human403 is intentional current
> contract. … **F-01** explicit human Site-bootstrap/grant ownership decision; no simple allowlist
> widening. Product target remains, not silently downgraded to precreated Sites"

> "Create/reuse WorkArea … New identity does not automatically enlarge a caller's allowed-area
> mapping … Grant provisioning for a newly created area's use needs the F-01 contract; do not
> broaden all resources"

1. **Site 생성**: `POST /v1/sites`(sites.py:986-1008)는 `SITES_WRITE`만 요구하고 org는 인증
   principal의 `organization_id`에서 취득한다(sites.py:999). 그러나 mapped OIDC principal은 요청
   경계에서 검토된 route matrix 밖의 route가 전부 403이다(auth.py:901-910). `POST /v1/sites`는
   matrix에 없다(auth.py:602-718). 의도된 현재 계약이며 test_oidc_route_scope.py:224-250이 `[403]`으로
   pin한다(토큰의 `ksi_role: ADMIN` 같은 주장은 매핑에 영향을 주지 않는다 — 같은 테스트 :52-54).
   즉 오늘 "새 Site"를 만들 수 있는 것은 unscoped opaque principal(운영자)뿐이다.
2. **WorkArea lockout**: scoped operator는 허용된 site에서 `POST .../work-areas`가 가능하지만
   (matrix auth.py:623), 생성된 area가 `allowed_work_area_ids`에 자동 포함되지 않아 목록 필터
   (work_areas.py:605-610)와 archive/supersedes grant 검사(work_areas.py:554-559)에서 걸리지
   않는다 — **만든 구역을 만든 사람이 쓸 수 없는** 상태다.
3. **Grant 표현**: registry v1(oidc_subject_registry.py:20-29)은 `allowedSiteIds`/
   `allowedWorkAreaIds` **명시 배열만** 표현한다(:104-107). "허용된 site의 모든 area" 같은 level
   표현이 없어 새 area마다 운영자가 registry를 재발행해야 한다. Principal의 `None`은 기존 opaque
   신원의 미분화 의미다(auth.py:244-247).
4. **Provisioning 경로**: org/identity/grant의 원천은 보호된 registry 파일뿐이고 Core에 관리 API가
   없다. roster(auth.py:225-227)는 배정 메타데이터이며 grant가 아니다. 이 파일은 production에서
   필수이고(platform_production.py:80-96) boot 시 1회 로드된다(platform_production.py:83,173;
   oidc.py:55-64) — 변경 반영은 재시작/재배포 절차가 필요하다.
5. **영향**: 감사 기록 "P4 does not establish onboarding success", "no complete default-account
   first-onboarding browser proof". 첫 흐름의 "등록" 앞단이 실제로 막혀 있다.

이 제안은 위 코드·route·registry·grant를 변경하지 않는다(실행 아님).

## 2. 지켜야 할 경계

- 감사 지침: "no simple allowlist widening", "do not broaden all resources", "not silently
  downgraded to precreated Sites".
- ADR-KSI-037 D1: "KSI performs the initial setup, then the same weekly request should be reusable
  without a bespoke customer script." — 초기설정(계약 단계)은 KSI 몫이라는 방향과 정합해야 한다.
- INV-060 tenant 비노출, 기존 명시 grant 규율, 검토된 route matrix, Role.ADMIN의 KSI측 제품 권한
  의미(_ROLE_PERMISSIONS auth.py:495-541)를 바꾸지 않는다.
- registry v1 배포 파일은 계속 유효해야 한다(하위호환).

## 3. 옵션

### D1 — 새 Site 생성 권한(bootstrap)

- **1안 — KSI 운영자 전담(초기설정)**: unscoped opaque 운영자 절차를 문서화하고, 온보딩 수용을
  "KSI 개입 포함"으로 정의. 장점: 변경 최소. 단점: 신규 site마다 KSI 티켓; audit이 경고한
  "precreated Sites로의 은폐성 downgrade"를 피하려면 product 문서와 F-01 acceptance를 함께
  명시적으로 갱신해야 한다.
- **2안 — 지정 고객 org-admin self-bootstrap (권장)**: registry v2의 명시 capability(예:
  `capabilities: ["SITE_BOOTSTRAP"]`)를 가진 고객 principal이 **자기 org 한정**으로 Site 생성.
  일반 operator·VIEWER는 불허. 생성 actor/시각은 기존 SiteRecord 감사를 그대로 사용. 장점: 실제
  고객 온보딩이 성립("KSI does the initial setup"과 정합 — 초기설정은 org/capability 발급).
  단점: 새 auth surface → 위협모델·계약테스트·운영문서 필요.
- **3안 — scoped operator 전체 허용**: 감사 위반("no simple allowlist widening"), 자원·남용 위험.
  비권장.

### D2 — 새 WorkArea의 사용 grant

- **A안 — 정적 열거 유지**: 마찰과 lockout이 남는다. B안 없이 첫 흐름 등록을 닫을 수 없다.
- **B안 — grant level 도입 (권장)**: v2에서 `allowedWorkAreaIds: null` = "허용된 site들의 모든
  area"(site 단위 grant). 명시 배열은 최소권한 모드로 그대로 유지. 새 area가 즉시 사용 가능해
  creator lockout이 해소된다. **필수 동반 가드**: mapped principal의 scope 판정을 `None` 추론
  (auth.py:901-903)으로 두면 `null` 도입이 스코프 채널 이탈(allowlist 우회)을 만들 수 있으므로,
  **양성 marker**(registry로 매핑된 principal임을 나타내는 필드)로 경계 검사를 바꾼다.
- **C안 — Core 소유 grant store + 관리 API**: 조직 self-service grant 관리는 장기 방향이나 새
  계약·감사·보안검토 범위가 크다. F-01 결정 후 별도 제안으로 다룬다.

### D3 — F-01 완료 증거

권장 기준: (a) 보호된 registry v2 파일과 실제 auth 모드(OIDC 또는 DUAL; OPAQUE 테스트 모드는
불인정)에서 재현, (b) 지정 org-admin이 browser/API로 Site 생성→목록/상세 확인→WorkArea 생성→
생성 area 즉시 조회/사용, (c) 일반 operator는 여전히 403, 교차 org는 404·목록 비노출, (d) 생성
actor/시각 감사 기록, (e) v1 파일 하위호환 검증. F-02..04(보호 스토리지/그래프/실자료·소비자)는
계속 별도 게이트다.

## 4. 승인 시 구현 개요 (권장 2안+B안 기준)

Owner modules: `services/core/src/ksi_core/identity/`, `services/core/src/ksi_core/domains/sites/`,
`services/core/src/ksi_core/composition/platform_production.py`, `tests/contract/`,
`apps/dashboard`(기능 검증), `docs/ops`(발급/재시작 절차).

- **registry v2 (additive)**: `capabilities`(초기 토큰 `SITE_BOOTSTRAP`)와 nullable grant 필드.
  v1 파일은 그대로 로드된다(하위호환). 정확한 버전/필드 명명은 구현 계획에서 확정.
- **Principal/경계**: mapped-scope 양성 marker 추가(예: `grant_source="oidc-registry"`).
  auth.py:901-910의 조건식을 marker 기반으로 바꾸되 v1 동작은 byte-동등 유지. null이 스코프
  채널을 벗어나지 못하는 회귀 테스트를 추가.
- **`POST /v1/sites`**: mapped principal에는 capability 요구(없으면 handler 403), org는 기존대로
  principal에서 취득(타 org 생성 불가). siteId는 현재 클라이언트 입력이므로 path-safe 규칙과
  교차 org 충돌/존재 oracle 방지 응답을 이 단계에서 확정한다(예: org 범위 충돌은 동일 409로
  접고 응답에 타 org 정보를 넣지 않음). unscoped opaque 동작은 유지.
- **WorkArea**: `allowed_work_area_ids=None`(v2 null) = 사이트 단위 all-areas를 목록·보관·
  supersedes에 일관 적용. 명시 배열 모드 불변.
- **Dashboard**: 사이트 등록 위저드/프록시가 scoped org-admin으로 실제 동작하는지 기능 검증,
  필요한 최소 수정만. 시각 변경은 디자인 소유 경계(OpenDesign)로 분리.
- **Ops 문서**: registry v2 발급·capability 부여·재시작/재배포 절차.
- **결정 기록**: 승인 시 새 ADR(ADR-KSI-040, 가칭) 또는 ADR-KSI-015 후속으로 결정을 기록하고
  product/문서를 동기화한다.

Tests(신규/갱신):
- `tests/contract/test_oidc_route_scope.py` — 검토된 matrix 갱신(403 → capability 조건부)과
  null-null mapped principal의 채널 이탈 금지 케이스.
- 신규 `tests/contract/test_site_bootstrap_and_work_area_grant_levels.py` — v1 하위호환, v2
  파싱, bootstrap 201(capability)/403(일반), 교차 org 404·목록 비노출, actor 기록, all-areas
  level 즉시 사용, explicit 모드 불변.
- `tests/contract/test_platform_core_production.py`(배선) — v2 registry 로드 확인.
- Dashboard 회귀는 P4 방식(별도 렌더/기능 검증)으로 수행.

수용기준(초안): D3 (a)–(e)의 실제 증거 + 전체 active suite green + 기존 broad/static 상태 유지.

Rollback: route/capability를 제거하면 v1 동작 그대로 복귀(레지스트리를 v1 파일로 되돌리면
완전 원복, 데이터 마이그레이션 없음). Site/WorkArea 기록은 append-only 유지.

## 5. 결정 요청

- **"F-01 권장안(2안+B안) 승인"** — 이후 상세 구현 계획(파일/테스트/작업 분해)을 작성해 실행한다.
- 또는 "1안+B안" 등 다른 조합을 지정하면 §4를 그 조합에 맞게 수정한 구현 계획으로 진행한다.

이 문서는 실행 승인이 아니다. 승인 기록 전에는 코드·배포·grant 변경을 하지 않는다.
