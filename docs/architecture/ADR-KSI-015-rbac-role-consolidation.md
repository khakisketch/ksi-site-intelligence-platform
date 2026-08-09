# ADR-KSI-015 — 역할 3개 축소와 자율운영 승인 권한 분리

- 상태: ACCEPTED (2026-08-05, 대표자 확정)
- 관련: `docs/product/FINAL_DECISION_LEDGER_v1.0.md`(실사용자 정의), MASTER_PRD
  §4.1(페르소나 카탈로그), ADR-KSI-008(§2 인증·역할 권한표 최초 도입, `##
  대표자 후속 확인` 항목 1), `docs/architecture/03_DASHBOARD_UX_GOALS.md`
  (§7 risk `dashboard-wizard-rbac-mismatch`), `docs/product/DOMAIN_INVARIANTS.md`
  (INV-040)

## 맥락

`FINAL_DECISION_LEDGER_v1.0.md`는 실사용자를 "현장소장·안전관리자"로
못박았다. 그런데 `services/core/src/ksi_core/auth.py`의 `_ROLE_PERMISSIONS`는
`SITE_MANAGER`에 `MISSIONS_ISSUE`를 주지 않는다(`SITES_READ`·`SITES_WRITE`·
`MISSIONS_READ`·`EVENTS_READ`·`EVENTS_TRIAGE`뿐) — 발급 권한은 `DRONE_OPERATOR`·
`ADMIN`에만 있다. 결과적으로 **실사용자로 못박힌 현장소장이 조사계획을 못
낸다.**

이 어긋남은 이미 `03_DASHBOARD_UX_GOALS.md`에 risk
`dashboard-wizard-rbac-mismatch`(공동 결정 레인, 미해소)로 기록되어 있다 —
현장등록/조사 Wizard가 `SITES_WRITE`+`MISSIONS_ISSUE`를 동시에 요구해
`ADMIN` 외 전 역할이 403을 받는다. 지금은 이를 `SiteRegistrationOnlyWizard`
(SITES_WRITE만 요구)로 위저드를 둘로 쪼갠 임시 분기로 덮고 있다
(`apps/dashboard/src/app/sites/new/SiteRegistrationOnlyWizard.tsx`,
`apps/dashboard/src/app/sites/[siteId]/SiteAoiEditor.tsx`). 화면을 늘릴
때마다 같은 문제가 재발한다 — 근본 원인인 role→permission 표를 고치지 않으면
분기가 계속 늘어난다.

## 결정

### D1 — 역할 3개: `ADMIN` · `FIELD_OPERATOR` · `VIEWER`

`SITE_MANAGER`·`SAFETY_MANAGER`·`DRONE_OPERATOR`를 `FIELD_OPERATOR`
(현장운영자) 하나로 합친다. 대시보드는 이미 역할이 아니라 권한으로 분기하고
있어(9개 분기 지점 전부 permission 기반, `03_DASHBOARD_UX_GOALS.md` 확인)
역할 수를 5개로 유지할 이득이 없다.

**기존 표 (5역할, `auth.py:166-200`)**

| 역할 | SITES_READ | SITES_WRITE | MISSIONS_READ | MISSIONS_ISSUE | EVENTS_READ | EVENTS_TRIAGE |
|---|---|---|---|---|---|---|
| `ADMIN` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `SITE_MANAGER` | ✓ | ✓ | ✓ | | ✓ | ✓ |
| `SAFETY_MANAGER` | ✓ | | ✓ | | ✓ | ✓ |
| `DRONE_OPERATOR` | ✓ | | ✓ | ✓ | | |
| `VIEWER` | ✓ | | ✓ | | ✓ | |

**새 표 (3역할 + 신설 권한)**

| 역할 | SITES_READ | SITES_WRITE | MISSIONS_READ | MISSIONS_ISSUE | EVENTS_READ | EVENTS_TRIAGE | SITES_AUTONOMY_APPROVE |
|---|---|---|---|---|---|---|---|
| `ADMIN` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `FIELD_OPERATOR` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `VIEWER` | ✓ | | ✓ | | ✓ | | |

`EDGE_DEVICE`(장비)는 role 표와 무관하게 `{EDGE_SYNC_INGEST}` 고정이다
(`auth.py` `_EDGE_DEVICE_PERMISSIONS`) — 이번 결정이 건드리지 않는다.

### D2 — `SITES_AUTONOMY_APPROVE` 신설

**이 권한이 없으면 `ADMIN`의 권한집합이 `FIELD_OPERATOR`와 글자 하나까지
같아져 관리자 역할이 라벨로 전락한다.** 그게 신설 이유다.

죽은 권한이 아니다 — 기존 `POST /v1/sites/{site_id}/transitions`가 받는
전이 요청 중 **blast radius가 큰 대상 전이만** 가른다. `SiteStatus`
10종·`_ALLOWED_SITE_TRANSITIONS`(`packages/domain/src/ksi_domain/enums.py`)
9개 정적 간선 + `SUSPENDED` 동적 resume 규칙을 다음처럼 나눈다.

**관리자 전용 전이 (`SITES_AUTONOMY_APPROVE` 필요)**

| 전이 (from → to) | 의미 |
|---|---|
| `MODEL_VALIDATION → PROVISIONAL_AUTONOMY` | 자율 시작 승인 |
| `PROVISIONAL_AUTONOMY → PATROL_READY` | 정식 순찰 승인 |
| 모든 상태 `→ SUSPENDED` | 운영중단 |
| `SUSPENDED →` 직전 상태(동적 resume) | 운영중단 복귀 |

**현장운영자가 그대로 하는 전이 (`SITES_WRITE`만으로 충분)**

| 전이 (from → to) |
|---|
| `UNMAPPED → BASELINE_MAPPING` · `REMAP_REQUIRED → BASELINE_MAPPING` |
| `BASELINE_MAPPING → MODEL_PROCESSING` · `MODEL_STALE → MODEL_PROCESSING` |
| `MODEL_PROCESSING → MODEL_VALIDATION` |
| `MODEL_VALIDATION → REMAP_REQUIRED` · `PROVISIONAL_AUTONOMY → REMAP_REQUIRED` · `MODEL_STALE → REMAP_REQUIRED` |
| `PATROL_READY ↔ PATROL_ACTIVE`(양방향) |
| `PATROL_READY → MODEL_STALE` · `PATROL_ACTIVE → MODEL_STALE` |

**주의(구현 시 정확히 지킬 것)**: `PATROL_READY`는 들어오는 정적 간선이
둘이다 — `PROVISIONAL_AUTONOMY → PATROL_READY`(최초 정식 승인, 관리자
전용)와 `PATROL_ACTIVE → PATROL_READY`(순찰 후 정상 복귀, 현장운영자).
같은 목적지라도 **출발 상태에 따라 요구 권한이 갈린다** — 이 게이트는
목적지 상태 하나만 보고 결정할 수 없고 `(from, to)` 간선 쌍으로 판정해야
한다. `SUSPENDED`도 마찬가지로 이질적이다: 진입(모든 상태 → `SUSPENDED`)은
목적지 기준, 복귀(`SUSPENDED →` 직전 상태)는 출발 상태 기준으로 관리자
전용이 걸린다 — "대상 상태만 가른다"는 근사적 표현이고, 정확한 SSOT는
간선 단위 판정이다.

근거: 일상 현장 진행(매핑·처리·검증·재매핑·일반 순찰 on/off)은 관리자
대기 없이 굴러가야 하고, blast radius가 큰 승인(자율비행 개시·운영중단과
그 복귀)만 게이트를 탄다. `FINAL_DECISION_LEDGER_v1.0.md` "하드웨어·자율성"
절의 "현장정책 승인 후 정기임무 자동실행"이 이 경계의 근거다 — 정기임무의
자동실행 자체는 정책 승인 이후 현장운영자 개입 없이 굴러가야 한다는 뜻이고,
그 "정책 승인"에 해당하는 것이 자율 시작(`PROVISIONAL_AUTONOMY`)·정식 순찰
개시(`PATROL_READY`) 전이다. `PRODUCT_CONSTITUTION.md` "제어 철학"의 "KSI
Core는 Mission Contract, 정책, 지도·모델 버전, 이벤트·증거·검토와 운영을
담당한다"도 정책적 승인 권한이 현장 실무와 분리된 자리(Core)에 있다는
전제와 정합한다.

**경계 배치**: 대상 전이 집합(어떤 `(from, to)`가 관리자 전용인가)은
도메인 개념이므로 `packages/domain/src/ksi_domain/enums.py`의
`_ALLOWED_SITE_TRANSITIONS` 옆에 둔다. 권한 매핑(그 전이 집합에
`SITES_AUTONOMY_APPROVE`를 요구할지)은 `services/core/src/ksi_core/sites.py`
라우트에서 한다 — 도메인 패키지가 auth(`Permission`·`Role`)를 모르게
유지하는 기존 배치 원칙(ADR-KSI-014 D1과 동형: 도메인 규칙은 domain
패키지, 강제는 Core)을 따른다.

### D3 — 페르소나 7개 → 기술 역할 3개 매핑

`MASTER_PRD_v3.0.md` §4.1 원문 명칭을 그대로 인용한다.

| PRD §4.1 페르소나 | 기술 역할 | 근거 |
|---|---|---|
| 현장소장 | `FIELD_OPERATOR` | 조사계획 발급 주체 — 이번 결정의 출발점(`FINAL_DECISION_LEDGER` 실사용자 정의와 `_ROLE_PERMISSIONS` 불일치 해소) |
| 안전관리자 | `FIELD_OPERATOR` | 트리아지(`EVENTS_TRIAGE`) + 현장 대응, 실사용자로 못박힌 두 페르소나 중 하나 |
| 드론 운영자 | `FIELD_OPERATOR` | 임무 발급(`MISSIONS_ISSUE`) 주체 — 구 `DRONE_OPERATOR` 역할의 핵심 책무 승계 |
| 공사·운영관리자 | `VIEWER` | 해당 화면(공정·물량·자재 파악)이 아직 Core API 범위 밖 — 실구현 표면이 없으므로 열람 이상을 줄 근거가 없다 |
| 구조·시설 점검자 | `VIEWER` | 결함후보·증거 검토 화면이 아직 범위 밖. 확정 권한은 해당 화면 착수 시 재검토 |
| 본사 관리자 | `ADMIN` | 다현장 감사 + 자율 승격 승인(`SITES_AUTONOMY_APPROVE`) — PRD가 명시한 "다현장 사건·추세·감사" 책무가 관리자 경계와 일치 |
| AI/Data 관리자 | **대응 역할 없음** | Dataset·Model 배포·성능 감시 표면이 Core API에 존재하지 않는다(엔드포인트·스키마 없음) — 없는 것을 있는 척 매핑하지 않는다. INV-040("Production에서 mock/placeholder/static always-go 금지. 외부 의존 실패는 데모 데이터로 가리지 않고 fail-closed로 정직하게 드러낸다")과 같은 정신 — 없는 표면에 역할을 미리 발급하지 않는다. 해당 표면이 생기면 이 ADR을 개정한다 |

## 기각한 대안

1. **역할은 그대로 두고 `SITE_MANAGER`에 `MISSIONS_ISSUE`만 추가** — 결함은
   닫히지만 역할이 5개로 남아 화면을 늘릴 때마다 5가지를 계속 고려해야
   한다. 대시보드가 이미 역할이 아니라 권한으로 분기하고 있어(9개 분기
   지점 전부 permission 기반) 역할 수를 유지할 이득이 없다.
2. **역할 2개(현장운영자·열람자)로 더 줄이기** — 자율비행을 승인하는
   사람과 현장에서 일하는 사람이 같아진다. `SITES_AUTONOMY_APPROVE`를 둘
   차이가 사라져 D2의 존재 이유가 무너진다.
3. **전이 엔드포인트 전체를 관리자 전용** — 규칙은 단순하지만
   `UNMAPPED → BASELINE_MAPPING` 같은 일상 전이까지 관리자 대기에 묶여
   현장소장이 매핑조차 스스로 시작할 수 없게 된다.

## 결과 — 알려진 대가

- 세분화된 권한 구분(예: 트리아지는 하되 현장 등록은 못 하는 역할)이
  사라진다. 필요해지면 **다시 나누는 것이 합치는 것보다 쉽다**는 판단이다.
- 기존 dev 토큰 5개가 3개로 바뀌어 재로그인이 필요하다
  (`scripts/run_core_dev.py` 프로비저닝 갱신 대상 — 이번 ADR 범위 밖, 코드
  변경 시 후속).
- journal의 `actor`에 남은 구 역할 유래 문자열(`dev-site_manager` 등)은
  append-only 감사 기록이므로 **재작성하지 않는다** — 과거 기록은 과거
  역할 이름을 그대로 보존한다.
- `PATROL_READY` 간선의 출발-상태 의존 판정(D2 주의 항목)은 구현 시
  "목적지 상태만 보는 단순 표"로 착각하기 쉬운 함정이다 — 코드 리뷰에서
  `(from, to)` 쌍 단위 검사인지 반드시 확인한다.
