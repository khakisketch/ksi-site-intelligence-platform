# F-01 결정 제안 — Site bootstrap과 WorkArea grant 소유권 (v2, 2026-10-09)

- Status: v2 — Human이 **2안(지정 고객 org-admin self-bootstrap) + B안(site 단위 grant level)** 을
  승인했고, 검토 지시("권장되는방향으로 개선")에 따라 조건 C1–C5를 이 판에 반영했다.
  **실행 권한은 아니다** — 실행은 다음 단계인 상세 구현 계획의 Human 승인 후다.
- Date: 2026-10-09 (v1 2026-10-09, 159e7c5)
- v1→v2 변경 요지 (승인 직후 검토에서 도출):
  - 제기 조건 ① "site-level grant는 동일 Site 내부 WorkArea에만 상속, 다른 Site·Org로 비전파" →
    C1(same-Site 상속 한정)과 scope-only 원칙으로 명문화(INV-F01-1/2).
  - 제기 조건 ② "org-admin capability 최초 발급은 KSI가 통제·감사" → C2로 수명주기(발급·변경·회수)
    전체로 확장(INV-F01-3).
  - C3: 신규 Site 생성자의 접근 출처를 확정(INV-F01-4) — capability와 scope는 분리된 KSI 발급 결정이고,
    생성 행위 자체는 scope를 확대하지 않는다.
  - C4: D3에 부정·회귀 테스트 매트릭스(f)를 추가. C5: "Role.ADMIN=KSI 전용"으로 읽힐 수 있는
    서술을 ADR-KSI-015 매핑에 맞게 정정(§2).
- 결정 요청: 이 판은 승인된 방향의 계약 개선판이다. 실행 전 상세 구현 계획 승인이 필요하다.

## 0. 요약 (결정 카드)

| 질문 | 결정 (승인됨) |
| --- | --- |
| D1 새 Site를 누가 만드는가 | **2안** — registry v2의 명시 capability(`SITE_BOOTSTRAP`)를 가진 지정 고객 principal, 자기 org 한정. 일반 operator·VIEWER 불허 |
| D2 새 WorkArea 사용 grant | **B안** — `allowedWorkAreaIds: null` = 허용된 site들의 모든 area(site 단위). 명시 배열은 최소권한 모드로 유지 |
| D3 F-01 완료 증거 | §4 (a)–(f): 실제 auth 모드 온보딩 재현 + 부정·회귀 매트릭스(C4) |

승인된 조합의 의미(변경 없음): KSI는 계약 단계에서 org와 org-admin capability를 발급하고(초기설정),
지정된 고객 org-admin이 자기 org의 Site를 스스로 만든다. 일반 operator·교차 org·기존 grant 의미는
넓히지 않는다. v2는 여기에 상속 범위(C1), 능력의 수명주기(C2), 신규 Site 접근의 출처(C3)를 명확히 한다.

## 1. 현재 실제 동작 (검증 근거)

감사(P5 통합 감사)가 남긴 이번 결정 대상 두 행:
"Create Site … Scoped OIDC allowlist lacks this method/path; human403 is intentional current
contract. … **F-01** explicit human Site-bootstrap/grant ownership decision; no simple allowlist
widening. Product target remains, not silently downgraded to precreated Sites" /
"Create/reuse WorkArea … New identity does not automatically enlarge a caller's allowed-area
mapping … Grant provisioning for a newly created area's use needs the F-01 contract; do not
broaden all resources".

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
   표현이 없어 새 area마다 운영자가 registry를 재발행해야 한다. Principal의 기존 `None`은 opaque
   신원의 미분화 의미다(auth.py:244-247) — v2의 `null` level은 이와 구분되어야 한다(§3).
4. **Provisioning 경로**: org/identity/grant의 원천은 보호된 registry 파일뿐이고 Core에 관리 API가
   없다. roster(auth.py:225-227)는 배정 메타데이터이며 grant가 아니다. 이 파일은 production에서
   필수이고(platform_production.py:80-96) boot 시 1회 로드된다(platform_production.py:83,173;
   oidc.py:55-64) — 변경 반영은 재시작/재배포 절차가 필요하다.
5. **영향**: 감사 기록 "P4 does not establish onboarding success", "no complete default-account
   first-onboarding browser proof". 첫 흐름의 "등록" 앞단이 실제로 막혀 있다.

이 판도 위 코드·route·registry·grant를 변경하지 않는다(실행 아님).

## 2. 지켜야 할 경계

- 감사 지침: "no simple allowlist widening", "do not broaden all resources", "not silently
  downgraded to precreated Sites".
- ADR-KSI-037 D1: "KSI performs the initial setup, then the same weekly request should be reusable
  without a bespoke customer script." — 초기설정(계약 단계)은 KSI 몫이라는 방향과 정합해야 한다.
- INV-060 tenant 비노출(범위 불일치는 동일 404로 접음, DOMAIN_INVARIANTS.md:339-344).
- registry v1 배포 파일은 계속 유효해야 한다(하위호환).
- **[C5 정정]** 역할 경계: v1의 "Role.ADMIN은 KSI측" 표현은 근거가 부족했다. ADR-KSI-015 D3는
  고객 "본사 관리자"→`ADMIN`을 매핑하므로 ADMIN 역할 자체는 KSI 전용이 아니다. 역할 표
  (`_ROLE_PERMISSIONS` auth.py:495-541)와 ADR-KSI-015 매핑은 이번 변경으로 바뀌지 않으며,
  KSI의 통제는 **capability 발급 경로(보호 registry)** 에 있다. `SITE_BOOTSTRAP`은 role과 독립으로
  발급되고, role=ADMIN이라는 사실이 capability를 자동 부여하지 않는다(그 반대도 같다).

## 3. 승인 결과와 구현 불변조건 (C1–C3)

승인: D1 2안, D2 B안. 기각 기록(요지): 1안 KSI 전담=신규 site마다 마찰·은폐성 downgrade 위험,
3안 전체 허용=감사 위반; D2 A안=lockout 잔존, C안 Core grant store=후속 별도 제안.

### INV-F01-1 — 같은 Site 안에서만 상속한다 (C1)

site-level grant(B안 `null` 포함)는 그 Site에 속한 WorkArea에만 적용된다. WorkArea 판정은 항상
서버 원장의 부모-자식 관계(`WorkArea.site_id` = 요청 경로 site)와 site grant를 먼저 통과해야 하며,
다른 Site·다른 Org로 전파되지 않는다. explicit area 목록이 다른 site의 area id를 담아도 부모 site가
scope 밖이면 404다. 강제: 기존 site-선행 검사(`require_site_scope` work_areas.py:541-552,
`_require_path` external_analysis_api.py:1752-1759, `get_scoped` sites.py:566-571)를 모든 scoped
표면에서 유지하고 회귀 테스트로 고정한다.

### INV-F01-2 — grant는 자원 범위만 확장한다 (C1 보강)

v2의 grant level은 자원 가시성 범위만 넓힌다. 쓰기 권한(role→permission), 데이터 제공/반출·동의
(`SPATIAL_DATA_*` rights, `aiEgressAllowed`, `dataResidency` — grants.py:228-283), 검사·검증·정량
적격성, 감사 기록을 하나도 바꾸지 않는다. scope·permission·policy는 각각 독립 게이트로 계속
강제되며, 이 원칙은 `allowedSiteIds: null`(org 전체)에도 동일하게 적용된다. SPATIAL_DATA_CLIENT/MCP
신원의 "None scope 거부" 현행 동작(delivery/source.py:133-138, delivery/grants.py:234-239)도 유지한다.

### INV-F01-3 — capability 수명주기 전체를 KSI가 통제한다 (C2)

`SITE_BOOTSTRAP`(및 향후 capability)의 **발급뿐 아니라 변경·회수**도 KSI가 통제하는 보호 registry
배포로만 이루어진다. 고객에게 자기·타인 재위임 표면은 없다. JWT claim은 권한을 부여하지 않는다
(기존 검증 유지 — test_oidc_auth.py가 pin). 회수·축소는 registry 재발급/REVOKED로 유효해지고
반영 시점은 재시작/재배포 절차를 따른다(§5 Ops 문서). 감사 근거는 KSI가 버전 관리하는 보호
registry 배포 자산이다.

### INV-F01-4 — 신규 Site 접근의 출처 (C3 확정)

- 생성(부트스트랩) capability와 접근 scope는 **분리된 발급 결정**이다. capability만으로는 어떤
  Site도 보이지 않는다(생성도 불가능하다 — capability가 생성의 전제).
- org-admin의 접근은 KSI가 발급하는 scope가 결정한다: `allowedSiteIds: null` = 자기 org 전체
  (신규 site 포함). 이 발급이 있어야 새 Site가 생성자에게 즉시 보인다.
- **생성 행위는 scope를 확대하지 않는다**: per-site grant 레코드를 만들지 않는다. 새 Site의
  가시성은 이미 발급된 scope(org 전체)와 서버 원장의 `organizationId` 귀속(sites.py:999,
  get_scoped)이 결정한다.
- 발급 지침(ops): `SITE_BOOTSTRAP`은 원칙적으로 org 전체 scope(`null`)와 함께 발급하고, org 전체
  scope는 본사 관리자급(ADR-KSI-015의 ADMIN 매핑)에게 발급한다. explicit site 목록과 함께
  발급하면 새 Site는 그 목록에 추가되기 전까지 생성자에게도 보이지 않는다(계약상 허용, ops 문서에
  명시; parse-time 강제 여부는 구현 계획에서 결정).
- 저장·유지: registry v2 파일(발급) + `SiteRecord`의 `organizationId`(귀속). 재시작 후 동일하게
  재현된다.
- 회수: registry 재발급(범위 축소) 또는 REVOKED(신원 전체). org 전체 모드에는 개별 site만 제외하는
  표현이 없다 — 필요하면 재발급을 explicit 목록으로 전환한다(잔여 한계; C안 Core grant store가
  후속 경로).

## 4. D3 완료 증거 (C4 포함)

- (a) 보호된 registry v2 파일과 실제 auth 모드(OIDC 또는 DUAL; OPAQUE 테스트 모드는 불인정)에서 재현
- (b) 지정 org-admin(org 전체 scope 발급): browser/API로 Site 생성→목록/상세 확인→WorkArea
  생성→생성 area 즉시 조회/사용
- (c) 일반 operator 403·교차 org 404·목록 비노출
- (d) 생성 actor/시각 감사 기록
- (e) v1 파일 하위호환(v2 배열-전용 발급의 v1 동등성 포함)
- (f) 부정·회귀 매트릭스: capability 없는 principal 403(위조 claim 포함), capability 회수·REVOKED
  반영 후 거부, null-null mapped principal의 검토된 route matrix 이탈 금지(roster/transitions/AOI
  등 403 유지), 다른 site의 area id 주입 404(INV-F01-1), cross-org siteId 중복은 same-org 중복과
  동일한 status/body(조직 귀속 비노출 — 남는 전역 존재 신호는 잔여 위험으로 문서화하고 서버 발급
  id 전환 여부를 구현 계획에서 검토), v2 `[]`(빈 집합)와 `null`(전체)의 구분 동작.

F-02..04(보호 스토리지/그래프/실자료·소비자)는 계속 별도 게이트다.

## 5. 구현 개요 (v2, 승인 시 상세 계획으로 확장)

Owner modules: `services/core/src/ksi_core/identity/`, `domains/sites/`,
`composition/platform_production.py`, `tests/contract/`, `apps/dashboard`(기능 검증),
`docs/ops`(발급/재시작·회수 절차).

- **registry v2 (additive)**: `capabilities`(+`SITE_BOOTSTRAP`)와 nullable grant 필드(§3),
  strictness·bounded 검증은 v1과 동일 수준 유지. v1 파일은 그대로 로드(하위호환). 정확한 버전·
  필드 명명은 구현 계획에서 확정.
- **Principal/경계**: mapped-scope 양성 marker(예: `registry_scoped`)와 `capabilities` 필드 추가.
  경계 조건(auth.py:901-910)을 marker 기반으로 바꾸되 v1 동작은 byte-동등 — `null`이 스코프
  채널(검토된 route matrix)을 벗어나지 못한다. (`POST`, `/v1/sites`)를 **capability 조건부** 항목으로
  검토 매트릭스에 추가한다: capability 없는 mapped principal은 403, 있는 principal만 핸들러 도달.
  강제 위치(경계 map vs 핸들러)는 구현 계획에서 정하되, 계약 테스트가 두 조건을 고정한다.
- **`POST /v1/sites`**: org는 기존대로 인증 principal에서 취득(타 org 생성 불가), actor 기록 유지.
  중복 siteId는 same-org/cross-org 동일 응답(조직 정보 없음). 남용 상한(org당 site 수 등)의
  수치·기본값은 구현 계획에서 확정.
- **scoped 표면 전반**: 기존 `is not None` 게이트가 v2 `null`에서 의도대로 동작하는지 §4 (f)
  매트릭스로 고정 — 사이트 목록/상세(sites.py:1010-1036), WorkArea(work_areas.py:541-559,605-610),
  분석(external_analysis_api.py:1761-1798), 딜리버리·카탈로그·워크플로·증거.
- **Dashboard**: 기존 `SiteRegistrationOnlyWizard`(SITES_WRITE만 요구) 흐름이 scoped org-admin으로
  실제 동작하는지 기능 검증, 필요한 최소 수정만. 시각 변경은 디자인 소유 경계(OpenDesign).
- **Ops 문서**: v2 발급 지침(capability×scope 짝), 변경·회수·재시작 절차, 교차 org 중복 응답 의미,
  org 전체 모드의 부분 회수 한계.
- **기록**: 실행 시 새 ADR(ADR-KSI-040, 가칭) 또는 ADR-KSI-015 후속으로 결정을 기록하고 제품
  문서를 동기화한다.

Tests(신규/갱신):
- `tests/contract/test_oidc_route_scope.py` — 매트릭스 갱신(403 → capability 조건부) + null 채널
  가드 케이스.
- 신규 `tests/contract/test_site_bootstrap_and_work_area_grant_levels.py` — §4 (a)–(f) 전체.
- `tests/contract/test_platform_core_production.py`(배선) — v2 registry 로드 확인.
- Dashboard 회귀는 P4 방식(별도 렌더/기능 검증)으로 수행.

수용기준(초안): §4 (a)–(f)의 실제 증거 + 전체 active suite green + 기존 broad/static 상태 유지.

Rollback: capability 항목·route 조건 제거 + registry v1 재배포로 완전 원복(데이터 마이그레이션
없음). Site/WorkArea 기록은 append-only 유지.

## 6. 다음 단계

- 이 v2를 기준으로 상세 구현 계획(파일/테스트/작업 분해)을 작성한다.
- 실행은 그 계획의 Human 승인 후 시작한다. 승인 전에는 코드·route·registry·grant를 변경하지 않는다.
