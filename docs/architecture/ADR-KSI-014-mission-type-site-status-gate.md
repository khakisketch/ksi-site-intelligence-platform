# ADR-KSI-014 — 임무 발급은 현장 상태를 본다: 임무 타입 × 현장상태 게이트

- 상태: ACCEPTED (2026-08-05, 대표자 확정)
- 관련: `docs/product/DOMAIN_INVARIANTS.md`(INV-052 신설), MASTER_PRD §6.1/§6.3/§7.4,
  FINAL_DECISION_LEDGER_v1.0(DEC-013), ADR-KSI-007(이원 산출물), ADR-KSI-008(발급
  경로 fail-closed 조립), ADR-KSI-011(§ 서버 422를 마지막 단계에서 만나지 않는다
  원칙)

## 맥락

"먼저 매핑, 그 다음 사전지도 기반 자율"은 MASTER_PRD §6.1의 현장 생애주기가
정본으로 못박은 이 제품의 핵심 독트린이다. 현장 상태머신(`UNMAPPED →
BASELINE_MAPPING → MODEL_PROCESSING → MODEL_VALIDATION → PROVISIONAL_AUTONOMY →
PATROL_READY → PATROL_ACTIVE`, 그 외 `MODEL_STALE`·`REMAP_REQUIRED`·`SUSPENDED`)
자체는 `packages/domain/src/ksi_domain/enums.py`에 이미 구현·강제돼 있었다.

그런데 임무 발급이 이 상태를 전혀 보지 않았다 — 짝 발급(`mission_plans.py`)과
계약 단독 발급(`mission_issuance.py`) 둘 다 `site_frame_lookup`으로 site
존재·좌표계만 대조하고 `record.status`는 버렸다. 결과적으로 `UNMAPPED` 현장에도
`AUTONOMOUS_PATROL` 계약이 그대로 서명·발급됐다 — 사전지도 없이 "사전지도 기반
자율" 계약이 나가는 상태였다. `mission_type`도 계약 단독 발급 경로에서는 전혀
제약되지 않아(짝 발급만 route pattern 매핑으로 일부 걸렸다) 8종 임무 타입
전부가 아무 현장상태에서나 발급 가능했다.

## 결정

### D1 — 임무 타입 × 현장상태 허용표를 도메인 SSOT로 둔다

`packages/domain/src/ksi_domain/mission_gating.py`가 `MISSION_TYPE_ALLOWED_
SITE_STATUSES` 표(8개 `MissionType` 멤버 전수, 표 완전성 자가검증 포함)를
소유한다 — `enums.py`의 `assert_site_transition`과 같은 배치 원칙(도메인 규칙은
Core가 아니라 domain 패키지)을 따른다.

| 임무 타입 | 허용 현장상태 | 근거 |
|---|---|---|
| `BASELINE_MAPPING` | `UNMAPPED`·`REMAP_REQUIRED` | §6.1 최초 매핑은 UNMAPPED 직후. REMAP_REQUIRED→BASELINE_MAPPING 은 상태머신 정적 간선. `MODEL_STALE`은 제외(상태머신이 `MODEL_STALE→BASELINE_MAPPING` 직행 간선을 두지 않는다) |
| `SURVEY_GRADE_MAPPING` | `UNMAPPED`·`REMAP_REQUIRED` | 문서에 별도 근거 없음 — BASELINE_MAPPING과 같은 lawnmower 매핑 계열로 보수적 통일 |
| `SPATIAL_REFRESH` | `PROVISIONAL_AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE`·`MODEL_STALE` | §6.2 "모델이 오래됐으면 부분 재매핑을 선행" — 이 임무 자체가 그 선행 조치. `MODEL_STALE→MODEL_PROCESSING` 간선과 정합 |
| `PROGRESS_CAPTURE` | `PROVISIONAL_AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE`·`MODEL_STALE` | 문서에 별도 근거 없음 — SPATIAL_REFRESH와 동일 전제(기존 매핑 대비 비교)로 보수적 통일 |
| `AUTONOMOUS_PATROL` | `PROVISIONAL_AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE` | "사전지도 기반 자율" 그 자체 — 검증되고 현재인 모델 필요. `MODEL_STALE` 제외(품질 검증 우회 금지 원칙, enums.py와 동형) |
| `ASSET_INSPECTION` | `PROVISIONAL_AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE` | 문서 명시 없음 — 보수적 유추(자산 위치는 World Model 필요, AUTONOMOUS_PATROL과 동일 전제) |
| `UNIFIED_SITE_SURVEY` | 위 매핑 계열 ∪ 갱신 계열(`UNMAPPED`·`REMAP_REQUIRED`·`PROVISIONAL_AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE`·`MODEL_STALE`) | §6.4 내부 그래프의 `BASELINE_OR_REFRESH_CAPTURE` 스테이지가 baseline/refresh를 스스로 선택 |
| `INCIDENT_SURVEY` | `SUSPENDED` 제외 전 상태 | **판단이 갈리는 지점.** FINAL_DECISION_LEDGER DEC-013 "미매핑 공간은 제한속도·거리·행동으로 탐색"으로부터의 **추론**(문서가 이 표를 문자 그대로 말하지 않는다) — 사고는 매핑 여부와 무관하게 발생하고 안전순찰이 최우선 가치(DEC-005)이므로 허용 쪽으로 판단했다. 반대 결정도 방어 가능 — 대표자 재검토 대상 |

`MODEL_PROCESSING`·`MODEL_VALIDATION`(전이 처리 중)은 `INCIDENT_SURVEY`를
제외한 모든 타입에서 막는다 — 직전 캡처가 처리·검증 중인데 새 임무를 겹쳐
발급해도 되는지 근거가 문서에 없어 fail-closed 기본값을 택했다. `SUSPENDED`는
임무 타입과 무관하게 전부 막는다(작업 지시 명시 — 운영 중단은 전부를 멈추는
것이 자연스럽다).

전체 근거는 표로 요약하지 않고 `mission_gating.py` 모듈 docstring에 산다 —
이 표가 낡으면 코드가 먼저 갱신되고 ADR은 뒤따르는 문서이길 원해서다.

### D2 — 강제 지점은 `precheck_issuance` 한 곳, 양쪽 발급 경로 모두

`ksi_core.mission_records.precheck_issuance`가 짝 발급(`mission_plans.py`)과
계약 단독 발급(`mission_issuance.py`) 둘 다의 공용 사전 게이트라는 기존 구조를
그대로 활용한다 — 새 게이트를 두 곳에 각각 구현하지 않고, 이 함수 한 곳에
`mission_type × site_status` 검사를 추가해 두 라우터가 자동으로 같은 규칙을
받는다. 우회로(계약 단독 발급이 mission_type을 전혀 제약하지 않던 구멍)가
이걸로 구조적으로 닫힌다 — 세 번째 발급 경로가 생겨도 `precheck_issuance`를
거치는 한 자동으로 이 게이트를 받는다.

검사 순서: journal 봉인 → id 문자 제약 → site 등록 대조 → siteFrame 일치 →
mission_id 충돌 → **임무타입×현장상태 게이트(신설)**.

**순서 정정(독립 재검토 D1, 2026-08-05)**: 최초 구현은 게이트를 mission_id
충돌보다 앞에 뒀다("이 요청이 이 site에 대해 구조적으로 유효한가를 다 확인한
뒤에야 mission_id가 비어있는가를 본다"는 순서가 자연스럽다는 판단). 그런데
짝 발급의 멱등 재발급(`mission_plans.py` — 같은 missionId + 동일 요청 digest
재시도는 201 유실 시에도 200 재반환)은 verdict가 `MISSION_ID_CONFLICT`일 때만
그 분기에 진입한다. 게이트가 먼저면, 발급 당시엔 허용됐던 임무타입×현장상태
조합이 그 사이 site가 전이해 더는 허용되지 않을 때 재시도가
`MISSION_TYPE_SITE_STATUS_MISMATCH`(409)로 막혀 멱등 분기에 도달조차 못한다
— 이미 인가되고 원장에 기록된 임무의 재반환이 나중에 바뀐 site 상태에
좌우되는 것이다. mission_id 충돌 검사를 게이트보다 앞으로 옮겨 이를
닫았다(신규 발급에는 영향 없음 — 게이트는 여전히 mission_id가 비어 있을 때만
의미가 있다).

**site_frame과 status를 한 콜백(`site_lookup: Callable[[str], SiteLookupResult
| None]`)이 함께 반환**하도록 기존 `site_frame_lookup` 콜백을 확장했다(별도
콜백 두 개로 나누지 않음) — 별개 콜백이면 동시 site 전이 경합 시 site_frame은
A 시점, status는 B 시점 값이 섞여 들어올 수 있다. `SiteStore.get()` 한 번의
스냅샷을 그대로 묶어 넘기는 것이 유일한 정합 보장이다.

### D3 — verdict는 `MISSION_TYPE_SITE_STATUS_MISMATCH`, 상태코드 409

`SITE_FRAME_MISMATCH`(422)와 달리 409를 택했다 — 요청 자체는 구조적으로
유효하고(스키마·타입 문제가 아니다) 현재 자원 상태(site.status)와 충돌하는
것이므로, 이 저장소가 "현재 상태가 막는다" 클래스에 이미 쓰고 있는 상태코드
(`ILLEGAL_TRANSITION`·`AOI_LOCKED`·`MISSION_ID_CONFLICT`)와 같은 계열로
맞춘다(`docs/architecture/03_DASHBOARD_UX_GOALS.md` §3.4 에러 마이크로카피
표와도 일치 — 409는 "왜 막혔는지와 현재 실제 상태를 함께 보여준다").

### D4 — 대시보드는 서버 표를 미러링해 발급 전에 막는다

`apps/dashboard/src/lib/core-api/missionSiteGate.ts`가 서버 표를 그대로
미러링한다(정본은 여전히 서버 — 이 파일은 위저드가 발급 전에 미리 보여주기
위한 것뿐이고, 서버 표가 바뀌면 이 파일도 같이 고쳐야 하는 이중유지 리스크를
안고 간다). 새 현장조사 Wizard(§7.4) Step 2(목적)는 이 표로 현재 현장상태에서
발급 불가능한 목적을 비활성 + 사유로 보여준다 — ADR-KSI-011이 고도 상한에서
쓴 것과 같은 원칙("서버 422를 마지막 단계에서 만나지 않는다").

## 결과 — 알려진 대가

- **기존 테스트 다수가 현장 상태를 신경 쓰지 않고 임무를 발급하던 픽스처였다**
  — 게이트를 느슨하게 고치는 대신 픽스처가 올바른 현장 상태를 갖도록 고쳤다
  (`tests/_site_lifecycle.py` 공유 헬퍼 신설).
- **이중유지 리스크**: 대시보드 표가 서버 표와 수동으로 동기화된다(D4) —
  `test_api_contract_sync.py`류의 자동 대조 게이트는 이번 범위에 없다. 표가
  갈리면 대시보드가 "발급 가능"이라 보여준 것을 서버가 409로 거부하는 회귀가
  가능하다(사후 스캐폴딩 후보).
- **INCIDENT_SURVEY 허용표는 추론이다**(D1 표 참조) — 문서가 명시하지 않은
  결정이므로 대표자 재검토가 필요하다.
- **자동 상태 전이·MODEL_STALE 자동 계산은 이번 범위 밖**이다 — 현장 상태
  전이는 여전히 수동(`/v1/sites/{id}/transitions`)이고, 이 ADR은 "현재 상태에서
  발급 가능한가"만 본다.
- **게이트는 발급 시점에만 걸린다 — 발급된 계약을 사후 무효화하지 않는다**
  (독립 재검토 D5, 2026-08-05). `PATROL_READY`에서 발급된 `AUTONOMOUS_PATROL`
  계약은 최대 168시간(`mission_issuance._MAX_VALID_FOR_HOURS`) 유효하고, 그
  사이 site가 `MODEL_STALE`·`REMAP_REQUIRED`로 떨어져도(예: 재매핑이 필요할
  만큼 큰 변화가 감지됨) 이미 서명된 계약은 무효화되지 않는다 — Manifold는
  로컬에 유효한 계약을 여전히 유효한 것으로 실행할 수 있다. 이것을 결함으로
  적지 않는다 — `CLAUDE.md`의 "Server loss must not invalidate a locally valid
  Mission Contract"와 의도적 긴장 관계에 있고, 자동 무효화가 정답이라고 이
  ADR이 단정하지 않는다(반대로 "서버가 상태를 안다고 로컬에서 이미 유효한
  계약을 걷어가면" 그 자체가 이 원칙 위반이 될 수 있다). **알려진 잔여**로만
  남긴다 — 재검토 대상이지 자동 해결책이 정해진 것은 아니다.
