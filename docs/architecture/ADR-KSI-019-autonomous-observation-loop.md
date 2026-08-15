# ADR-KSI-019 — Autonomous Observation Loop: 관측 자율성 3단계 정의와 순서 고정

- 상태: ACCEPTED (2026-08-15, 대표자 지시)
- 관련: ADR-KSI-018(Phase 3 재정의·폐루프 최우선 — 본 ADR이 그 루프를 **단계로 분해**한다),
  ADR-KSI-004(DJI 연동 이원화), ADR-KSI-007(임무 이원 산출물), ADR-KSI-011(비행 상한·매핑 촬영),
  ADR-KSI-017(현장 운용 UX 경계), `00_SYSTEM_OVERVIEW.md`,
  목표 원장 `autonomous-acquisition-closed-loop`(부모 목표)
- 본 ADR은 **구현 지시가 아니라 목표 구조·순서의 고정**이다. 실측 근거는 §2, 미구현 항목은 §4.

## 1. 맥락 — "Point Cloud 기반 자율비행"이라고 쓰면 순환논리가 된다

목표를 "3D/Point Cloud를 이용한 자율비행"으로 적으면, 공간모델이 아직 없는 **최초
현장**에서 3D를 만들려면 3D가 먼저 필요해진다. 목표 문장 자체가 순환한다.

동시에, 2026-08-15 전수 실사에서 그 반대쪽 오해도 확인됐다 — **"경로 계획기가 아직
없다"는 전제가 틀렸다.** AOI(현장 경계) → lawnmower 격자 → 촬영 간격 → WPML/KMZ +
서명 계약 짝 발급까지는 이미 구현·검증돼 있고, 변화영역 → 재관측 AOI → 실제 비행
가능한 KMZ 경로까지도 이어져 있다(§2). 이 상태에서 "자율비행 기능 개발"을 통째로
지시하면 이미 있는 것을 다시 만들 위험이 크다.

따라서 이 ADR이 고정하는 것은 두 가지다: **목표 루프의 정의**와 **단계 순서**다.

## 2. 실측 결과 — 이미 있는 것 (재구현 금지)

| 능력 | 실체 | 근거 |
|---|---|---|
| 현장 경계(AOI) 영속 | `PUT /v1/sites/{siteId}/aoi`, 재발급 시 기본값으로 재사용 | `services/core/src/ksi_core/sites.py:756` |
| 카메라·고도·중복도 → 격자 간격 계산 | GSD·footprint에서 `spacingM`/`captureIntervalM` 유도, 최소 중복도 하한 강제 | `packages/mission-planning/src/ksi_mission_planning/camera.py:107` |
| 면 커버리지 경로(lawnmower) | AOI + 간격 + FlightEnvelope → 웨이포인트 + 계획 커버리지 비율 | `packages/mission-planning/src/ksi_mission_planning/coverage.py:464` |
| 외곽 순회 경로(perimeter) | 순찰·사고조사 계열 | `.../coverage.py:196` |
| DJI 실행 파일(WPML/KMZ) 생성 | `wpmz/` 템플릿+웨이라인, 웨이포인트별 촬영 액션 | `.../wpml.py:372` |
| 계약+KMZ **짝** 발급(단일 진입점) | `POST /v1/missions/plans` — 같은 요청에서 서명 계약과 경로가 함께 나온다 | `services/core/src/ksi_core/mission_plans.py:586` |
| 계획 커버리지 사전 게이트 | 계획 추정치가 계약 약속 미만이면 발급 거부 | `.../mission_plans.py:342` |
| 임무타입 × 현장상태 게이트(INV-052) | `UNMAPPED`에 순찰 임무 발급 불가 등 8×10 표 | `packages/domain/src/ksi_domain/mission_gating.py:106` |
| 현장 상태 10종 상태머신 | `UNMAPPED`…`MODEL_STALE`·`REMAP_REQUIRED` | `packages/domain/src/ksi_domain/enums.py:110` |
| 변화영역 → 재관측 AOI 초안 | 영역 볼록껍질(WGS84) → `AreaOfInterest` | `services/core/src/ksi_core/region_extraction_reports.py:476` |
| 초안 → 실제 발급 위저드 자동 채움 | 변화영역 화면에서 넘어온 AOI로 `SPATIAL_REFRESH` 짝 발급 | `apps/dashboard/src/app/sites/[siteId]/surveys/new/page.tsx:22` |
| 임무 → 사진 → 처리작업 계보 | 미디어 키·번들 봉인·`jobId = f(missionId, seq)` | `.../source_media.py:209`, `.../processing_jobs.py:619` |
| 임무 완료 판정 계약(수신측) | CoverageReport 수신·완료 주장 검증(INV-010) | `services/core/src/ksi_core/coverage_reports.py` |
| Manifold 임무 전달 계약 | 서명 `MissionDispatchEnvelope` + activation receipt | `services/core/src/ksi_core/edge_dispatch.py` |
| 비행제어 금지 경계(negative gate) | 빌드된 Edge 바이너리에 DJI 비행제어 심볼이 있으면 실패 | `tools/edge/check_shadow_flight_boundary.py`, `tests/contract/test_shadow_flight_boundary_gate.py` |

검증: `tests/contract/test_mission_plans.py` · `test_mission_planning.py` ·
`test_camera_grid.py` · `test_mission_site_status_gate.py` ·
`test_region_extraction_end_to_end.py` — 170 passed (2026-08-15 실행).

**중요:** 위 경로 어디에도 DSM·Point Cloud 입력이 없다. 즉 **최초 매핑 임무는 이미
공간모델 없이 생성 가능하다** — §3 D3의 반순환 불변식은 신규 요구가 아니라 현재
성질의 **회귀 금지 선언**이다.

## 3. 결정

### D1 — 목표 루프 (Autonomous Observation Loop)

```text
현장 등록 → 공간모델 유무·최신도 판단
   │
   ├─ 없음/오래됨 → 매핑 임무 계획(경계·고도·중복도·안전조건)
   │                   → 운영자 승인 → 비행·촬영
   │                   → 사진 회수 → 재구성 → 공간모델 등록
   │
   └─ 있음 → 설계 대비/시계열 분석 → 변화·재확인 영역 판단
                → 재관측 임무 계획 → 운영자 승인 → 재관측 비행
                → 새 데이터 → 공간모델 갱신 ─────────────↺
```

### D2 — 관측 자율성 3단계와 **순서 고정**

- **AOL-1 매핑 자율(Mapping Autonomy)** — 공간모델이 없어도 성립한다.
  `현장 경계 → 매핑 경로 → 승인 → 실행 → 촬영 → 재구성 → 공간모델 등록`.
- **AOL-2 분석 기반 재관측(Intelligence-driven Reobservation)** — 공간모델 + 분석
  결과에서 대상 영역을 정하고 재관측 경로를 낸다.
- **AOL-3 공간모델 인지 비행(Spatially-aware Flight Autonomy)** — DSM/Point Cloud/3D를
  **경로계획 입력으로** 쓴다: 지형 추종, 구조물 이격 관측, 장애물 인지 경로,
  데이터 부족 영역 적응 촬영, 임무 중 동적 재계획.

**AOL-3을 AOL-1보다 먼저 구현하지 않는다.** 이 순서는 선호가 아니라 D3의 귀결이다.

### D3 — 반순환 불변식 (회귀 금지)

**최초 매핑 임무는 그 현장의 공간모델(Point Cloud·DSM·Mesh) 없이 생성 가능해야
한다.** 경로 생성기·계약 발급 경로에 공간모델을 **필수 입력으로** 추가하는 변경은
이 불변식 위반이다. AOL-3의 지형 인지 기능은 반드시 **선택적 강화(optional
refinement)** 로 들어가야 하며, 없으면 AOL-1 경로가 그대로 나와야 한다.

### D4 — 자율성 경계는 이 단계에서 넓히지 않는다

| 주체 | 책임 |
|---|---|
| KSI | 관측 필요성 판단 · 임무/경로 계획 · 실행 준비 |
| 사람 | 비행 시작 전 승인 · 필요 시 중단·통제권 회수 |
| DJI 비행 시스템 | 승인된 임무의 실제 실행(저수준 비행·회피·RTH) |

`check_shadow_flight_boundary` 게이트(KSI Edge 바이너리에 DJI 비행제어 심볼 금지)는
AOL-1~3 어느 단계에서도 완화하지 않는다. KSI가 직접 이륙·착륙·비상제어를 수행하는
확장은 본 ADR의 범위 밖이며 별도 결정을 요구한다.

### D5 — 용어: `AOL-n` 은 PRD §25의 `Phase n` 과 **다른 축**이다

PRD §25/`docs/goals/PHASE_REGISTRY.yaml`의 Phase 0~5는 제품 로드맵 축이다. 본 ADR의
AOL-1/2/3은 **관측 자율성 성숙도 축**이다. 혼동을 막기 위해 숫자를 공유하지 않는
접두사(`AOL-`)를 쓴다. 대응 관계: AOL 전체는 ADR-KSI-018이 재정의한 Phase 3
("자율 현장 수집")의 내용 축이다.

## 4. GAP — 목표까지 비어 있는 것

| # | GAP | 현재 상태 | 단계 |
|---|---|---|---|
| G1 | 공간모델 최신도 판단이 자동이 아니다 | 상태머신·`MODEL_STALE`은 있으나 전이는 전부 사람이 화면에서 누른다. 재구성 성공이 상태를 전진시키지 않고, 나이 기준 노후 판정 규칙이 없다 | AOL-1 |
| G2 | 임무에 실행 생애주기가 없다 | `MissionRecord`는 **발급 기록**뿐 — 배포됨/비행중/완료 상태가 없다. CoverageReport 수신 계약은 있으나 임무 상태와 이어져 있지 않다 | AOL-1 |
| G3 | 임무를 기체까지 보내는 공식 경로가 없다 | 운영자가 KMZ를 내려받아 손으로 옮긴다. `services/dji-gateway`는 3줄 골격이고, M4D의 Pilot Cloud 지원 자체가 미확인(ADR-KSI-004) | AOL-1 |
| G4 | 촬영 → 서버 자동 ingest가 없다 | 사람이 사진을 손으로 올린다(ADR-KSI-018 P1과 동일 항목) | AOL-1 |
| G5 | 재관측 임무 계획에 사람 단계가 남아 있다 | 초안 AOI까지는 자동, 발급은 위저드를 사람이 끝까지 눌러야 한다. 촬영밀도를 변화 정도에 맞춰 조정하지 않는다 | AOL-2 |
| G6 | 경로계획이 지형을 모른다 | 고도는 이륙점 상대 단일값(`altitudeReference: relativeToStartPoint`)이고 계획기에 DSM 입력이 없다 — 지형 추종·이격·장애물 인지 전부 미구현 | AOL-3 |

## 5. 최소 개발 순서 (실측 반영)

1. **G1 공간모델 생애주기** — 재구성 성공이 현장 상태를 전진시키고, "없음/있음/오래됨"을
   서버가 판단한다. (AOL-1·AOL-2 양쪽의 분기 조건이라 먼저다)
2. **G2 임무 실행 생애주기** — 발급 이후 상태 + CoverageReport 결선. 3·4번의 수신처다.
3. **G4 촬영 자동 ingest** — 사람 손 업로드 제거. ADR-KSI-018 P1.
4. **G3 임무 배포 경로** — DJI 실기 확인이 관문(ADR-KSI-004 §2026-08-14 갱신). 실기
   확인 전까지 "운영자 수동 이관"이 공식 경로로 남는다.
5. **AOL-1 종단 1회** — 경계 → 매핑 임무 → 실행 → 촬영 → 재구성 → 공간모델 등록.
6. **G5 재관측 계획 자동화 심화** → **AOL-2 종단 1회**.
7. 실제 현장 검증(`SITE-INTELLIGENCE-E2E-FIELD`).
8. **그 다음에만 G6(AOL-3)** — 지형/공간모델 인지 경로계획.

## 6. 결과

- 목표 원장에 AOL 자식 목표 5건이 `autonomous-acquisition-closed-loop` 아래로 등록된다.
- `00_SYSTEM_OVERVIEW.md`의 "현재 도달점"은 유효하다 — 본 ADR은 그 표의 PLANNER 행을
  단계·GAP 단위로 분해한 것이다.
- MASTER_PRD는 FROZEN이므로 수정하지 않는다(개정은 ADR 계층 누적, ADR-KSI-018 관례).
