# ADR-KSI-016 — 제품 범위 재정의와 공간 데이터 아키텍처 확정

- 상태: ACCEPTED (2026-08-07, 대표자 확정 · 2026-08-08 D2 오기 정정)
- 관련: `docs/product/PRODUCT_CONSTITUTION.md`(§제품 정체성·§핵심 가치 — 본 ADR로
  개정), `docs/product/FINAL_DECISION_LEDGER_v1.0.md`(§고객·가치 우선순위 — 본
  ADR로 개정), MASTER_PRD §15(Mapping·Continuous World Model)·§23(시장 적용),
  ADR-KSI-003(Point Cloud 원본 SSOT / Mesh 파생), ADR-KSI-012(재구성 엔진·
  라이선스 경계·과금 뼈대·D6 온보드 단일 탐지경로), ADR-KSI-005(연결 아키텍처와
  스코프 경계), ADR-KSI-006(온보드 기동 — 하드웨어 검증 대기),
  `docs/product/DOMAIN_INVARIANTS.md`(INV-020·INV-024·INV-050·INV-051·INV-052)

## 맥락

2026-08-07 전체 저장소 실태 조사(문서 권위 체계 + 코드 6축 병렬 감사)에서 **제품이
약속한 것과 구현된 것 사이의 비대칭**이 드러났다. 비대칭의 방향이 통상적인 경우와
반대다 — 어렵고 미루기 쉬운 쪽(계약·불변식·감사 체계)이 서 있고, 고객이 눈으로
보고 값을 치르는 쪽(공간 데이터의 실체)이 비어 있다.

**서 있는 것.** Ed25519 서명 Mission Contract와 실제 WPML/KMZ 생성·발급
(`services/core/src/ksi_core/mission_issuance.py`), 현장 상태머신 10종과 "먼저
매핑" 발급 게이트(INV-052), 비행 후 CoverageReport 검증(INV-010), 데이터 반출
게이트(INV-050), 산출물 계보 강제(INV-051). 각각이 fail-closed 테스트와 replay
재현 테스트를 함께 갖고 있다.

**비어 있는 것.**

- **재구성 산출물의 바이트가 버려진다.** `services/processing-controller/src/
  ksi_processing_controller/odm.py:319` `plan_artifacts`가 `all.zip` 엔트리별
  sha256만 계산하고 파일을 폐기한다 — 모듈 docstring(60-63행)이 "산출물 바이트
  전송... KSI 스토리지로 올리는 경로는 아직 없다"고 이미 자백하고 있다. 재구성이
  성공해도 사람이 볼 수 있는 것이 남지 않는다.
- **좌표변환이 없다.** 저장소 전체에서 `pyproj` 사용 0건, 수직기준(지오이드)
  처리 0건. `packages/geo-core/src/ksi_geo_core/frames.py`는 구형 지구 반경 기반
  ENU 등장방형 근사뿐이고, CRS는 `ProcessingArtifact.crs` 문자열 태그로만 흐른다.
- **토공량·체적 계산 0건.** `volume` 문자열 검색 결과는 전부 비행금지구역
  (`allowed_volumes`/`excluded_volumes`)이며 cut/fill 계산 코드가 없다.
- **정사영상·점군 뷰어 0건.** 대시보드 지도는 Leaflet 2D AOI 편집기 하나다.

동시에 대표자가 제품 방향을 재정의했다: 드론을 "능동적으로 데이터를 수집하는
로봇"으로 보고, 핵심 경쟁력을 시계열 공간 이해·설계 대비 비교·능동 재수집에
둔다. 실시간 안전관리를 드론 밖 센서까지 확장하는 별도 제품(KSI Safety) 구상도
함께 있었으나, **그것이 이 제품에서 안전순찰을 빼는 결정은 아니었다**(§D2 정정
기록 참조).

이 방향은 `PRODUCT_CONSTITUTION.md`가 동결한 핵심 가치 1순위("자율 안전순찰")와
**우선순위가 역전된다.** 코드를 더 쌓기 전에 권위 문서를 정합시키지 않으면, 이후
모든 우선순위 판단이 "이미 구현된 코드가 있으니까"로 되돌아간다. 본 ADR이 그
정합을 수행한다.

## 결정

### D1 — 제품 정의 한 문장

> KSI Site Intelligence는 **건설 현장의 반복 비행 데이터를 자동으로 수집·정합·
> 비교해, 현장의 상태·변화·물량을 시계열로 답하고 부족한 데이터의 재수집을 스스로
> 계획하는 폐루프(closed-loop) 현장 공간 인텔리전스 플랫폼**이다.

이 문장은 표어가 아니라 **범위 판정 도구**다. "수집을 스스로 계획한다"가 임무
거버넌스를 만드는 근거이고, "비교해서 답한다"가 epoch 정합·측지·물량을 만드는
근거이며, 그 밖의 것은 만들지 않는 근거다.

### D2 — 선형 우선순위를 폐기하고 두 축으로 정의한다

**기존 목록의 문제는 순서가 아니라 분류였다.** 동결본의 네 항목과 2026-08-07
개정본의 다섯 항목 모두 **종류가 다른 것들을 한 줄에 세웠다**:

| 항목 | 실제 종류 |
|---|---|
| 시계열 공간 이해 / 지도 최신화 | 플랫폼 기술 |
| 공정·변화·물량 분석 | 분석 기능 |
| 자율 안전순찰 / 구조물·시설물 점검 | **드론이 수행하는 임무 유형** |

마지막 행이 결정적이다. `AUTONOMOUS_PATROL`과 `ASSET_INSPECTION`은
`ksi_domain.enums.MissionType`의 **형제**이고, 8개 유형 전부가
`ksi_domain.mission_gating`의 같은 허용표를 탄다. 한 enum의 형제 둘을 제품
가치 4위·5위로 갈라 적으면 "구조물 점검이 안전순찰보다 중요한가" 같은 답이
없는 논쟁이 생긴다 — 둘은 **같은 수집 엔진이 수행하는 다른 임무**이고, 엔진은
한 번 만든다.

**대신 두 축으로 정의한다.**

```text
KSI Site Intelligence Platform
│
├─ Site Intelligence Core ─────────────────────── WHAT / WHY
│   Spatial/Temporal World State · Reality↔Design ·
│   Change/Progress/Quantity · Uncertainty · Mission Planning
│
└─ Autonomous Acquisition ─────────────────────── HOW
    Manifold Runtime · Perception · Local World Model ·
    Viewpoint/Path Decision · Mission Execution
```

두 축은 계약으로 닫힌다 — 하행 `mission-contract.v1.2.json`, 상행
`event-bundle.v1.2.json`·`coverage-report.v1.1.json`·`action-intent.v1.json`.
**이 폐루프(Observe → Understand → Decide → Re-observe)를 닫는 것이 제품의
본체이며, 어느 한 축만으로는 제품이 성립하지 않는다.**

**이것은 신설 설계가 아니라 코드가 이미 하는 일이다.** `SiteStatus` 상태머신이
`UNMAPPED → BASELINE_MAPPING → MODEL_PROCESSING → MODEL_VALIDATION →
PROVISIONAL_AUTONOMY → PATROL_READY → PATROL_ACTIVE → MODEL_STALE →
REMAP_REQUIRED`로 두 축을 번갈아 지나가고, INV-052가 "검증된 최신 모델 없이
`AUTONOMOUS_PATROL`을 발급하지 않는다"로 그 의존 방향을 강제한다. 이 ADR은
문서를 코드에 맞추는 것이다.

**임무 유형 목록을 문서에 복제하지 않는다** — 정본은 `MissionType` enum이고,
유형별 발급 가능 현장상태는 `mission_gating` 모듈 docstring이 SSOT다.

**진행 상태는 여기에도 적지 않는다.** 어느 축이 지금 진행 중이고 어느 축이
막혀 있는지는 `docs/goals/PHASE_REGISTRY.yaml`과 goal-ledger가 소유한다.

> **정정 기록 (2026-08-08, 대표자 지적 2건).**
>
> 1. 최초 작성본은 자율 안전순찰을 "KSI Safety 제품 축으로 **이동**"이라고
>    적었다. 사실이 아니다 — 대표자가 별도 실시간 안전 제품을 구상 중이라는
>    것과, 이 제품이 안전순찰을 하지 않는다는 것은 다른 말인데 작성자가 둘을
>    같은 말로 취급했다.
> 2. 그 정정본은 안전순찰을 5순위로 되살렸는데, **줄 세우기 자체가 분류
>    오류**였다(위 표). 두 번 다 같은 성질의 실수다 — 확정되지 않은 함의를
>    작성자가 확장해 문서에 박았다.
>
> 헌법·결정원장·PRD·PHASE_REGISTRY·REMAINING_WORK_PLAN에 같은 오기가 전파됐고
> 함께 정정했다. 기록을 지우지 않는 이유는, 동결 문서가 조용히 바뀌면 나중에
> "원래 뭐였나"를 복원할 수 없기 때문이다.

### D3 — 공간 데이터 계층 (정본)

```
Physical site
→ Site reference frame        EPSG:5186 + KNGeoid 수직기준. RTK는 정확도 신호이지
                              절대정확도 검증이 아니다(INV-024)
→ Capture epoch               임무 1회 = 사진+텔레메트리+계보 봉인(SourceMediaBundle,
                              구현됨)
→ Reconstruction epoch        Point Cloud = 원본 SSOT / DSM·정사영상·Mesh = 파생
                              (ADR-KSI-003, INV-051). ProcessingJobRecord가 이
                              개념의 실체이며 별도 aggregate를 만들지 않는다
→ Serving layer               COG 타일·COPC — 원본에서 재생성 가능한 캐시
→ Semantic layer              구역·구조물·결함 후보
→ Design layer                IFC/도면 → site frame 정합(packages/bim-integration)
→ Temporal state              epoch 간 diff: 변화 후보·구역 체적·진척
→ Intelligence                재촬영 권고 → 임무 초안(폐루프)
   ↘ 실시간 축                 Edge 프레임 → 이벤트 → 증거 (자율 안전순찰)
```

**두 축은 접점만 공유하고 합류하지 않는다.** 실시간 축은 프레임 기반(비행 중),
공간 축은 재구성 기반(비행 후)이다. **둘 다 이 제품의 것이다** — 실시간 축이
다른 제품으로 나간다는 뜻이 아니라, 같은 제품 안에서 처리 경로가 다르다는
뜻이다. 이 분리는 ADR-KSI-003 §결과 2항이 이미 선언했고 ADR-KSI-012 D6(서버 second-pass 재탐지 기각)이 재확인했다 — 본 ADR은
그것을 계층도로 명시할 뿐 새 경계를 만들지 않는다.

### D4 — Build vs Buy

| Build (KSI 내부 핵심) | Buy / Adopt |
|---|---|
| 임무 폐루프: 분석 → 재촬영 권고 → 서명 임무 → 커버리지 검증 | 비행 안정화·저수준 제어·반응형 회피·RTH·기본 waypoint (DJI) |
| 시계열 현장 모델: epoch 정합, 변화 의미론, 물량·진척 지표 | 사진측량 재구성 엔진 (ODM 기본 — 전환 트리거는 ADR-KSI-012 D3) |
| 설계↔현실 정합 (IFC/도면 → site frame) | IFC 파싱(ifcopenshell)·좌표변환(pyproj)·래스터 처리(rasterio/GDAL) |
| 한국 측지 정합 (EPSG:5186 + KNGeoid) | 뷰어 (Leaflet·Potree·Cesium 등 오픈소스 조립) |
| 계보·감사 체계 (서명 계약·산출물 lineage·검증된 완료 판정) | DJI Cloud API/MQTT (Dock 단계 진입 시 그대로 채택 — ADR-KSI-004) |
| 온보드 수집 품질 게이트, 이후 이벤트 인지 | 기반 탐지 모델 가중치 (공개 모델 + 자사 데이터 파인튜닝) |

**이미 DJI나 기존 제품이 잘 해결하는 문제를 핵심 기술로 삼지 않는다** — 비행
안정화·반응형 회피·기본 waypoint 매핑은 DJI가 기본 제공한다(Pilot 2·Terra로
자동 매핑 비행 자체는 이미 된다).

**그렇다고 해자가 서버 한쪽에 있는 것은 아니다.** 해자는 두 계층이 각자 다른
결정을 내리고 그 둘이 이어지는 데 있다:

- **Core — WHAT / WHY**: "동쪽 사면의 토공 변화 신뢰도가 낮으니 다시 확인해야
  한다." 무엇을 왜 관측할지, 무엇이 부족한지의 판단.
- **Edge — HOW**: 어느 방향에서 접근할지, 어떤 거리에서 볼지, 가림이 생겼으니
  옆으로 옮길지, 목표가 프레임에서 빠졌으니 다시 잡을지. **실시간이고 현장에서
  결정되어야 한다** — 서버가 하려 들면 통신 지연·단절 때문에 로봇 시스템이
  성립하지 않는다(INV-001, 헌법 §제어 철학).

그 둘이 Mission Contract와 EventBundle로 이어져 `Observe → Understand →
Decide → Re-observe`를 닫는 것이 KSI의 핵심 기술이다. 한 축만 떼어내면
남는 것은 상품화된 조각이다.

### D5 — 지금 추가 투자를 하지 않는 것

D2로 선형 순위를 폐기했으므로 이 목록은 "몇 순위"가 아니라 **"지금 새 투자를
넣지 않는다"**만 말한다. 전부 범위 안에 있고, 구현물도 유지한다.

- **Phase 3 장비 kinematics·CPA/TTC·위험장 고도화** — Acquisition 축의 기능이고
  그 축이 하드웨어 게이트에 걸려 있는 동안 추가 투자를 하지 않는다. 범위에서
  빼거나 다른 제품으로 옮기지 않는다.
- **Phase 5 Dock·Fleet·산업중립 팩** — 동결 유지. "산업 중립"은 아키텍처 원칙
  으로만 남기고 시장 전략에서 제거한다. 첫 유료 건설 현장 이전에 다른 산업은 없다.
- **Edge perception 신규 코드** — 하드웨어 스파이크 전에는 착수하지 않는다
  (ADR-KSI-006이 세운 규율의 연장). Acquisition 축의 목표 기능이지 포기 항목이
  아니다.
- **자연어 질의·LLM 보고서 표면** — 데이터 계층이 서기 전에는 데모다.
- **뷰어·측정 UX의 정면 경쟁** — 성숙한 기존 제품을 따라잡는 게임을 시작하지
  않는다.

**어느 축이 지금 진행 가능하고 어느 축이 막혀 있는지는 이 문서가 아니라
`PHASE_REGISTRY.yaml`·goal-ledger가 소유한다** — 그 상태는 몇 주 만에 뒤집힌다.

### D6 — 정확도 등급: 상대 비교로 시작한다

**현장 관리용 상대 비교**를 목표로 한다. 같은 RTK 좌표계 안에서 시점 간 변화
(체적 증감·진척)를 신뢰하고, **절대 정확도는 주장하지 않는다**(INV-024).

정확도 계층이 나중에 들어올 자리는 **이미 비어 있다** —
`packages/event-contracts/src/ksi_event_contracts/processing_artifact.py`의
`ArtifactAccuracy(gcp_count, rmse, report_uri)`와 `ProcessingArtifact.accuracy:
ArtifactAccuracy | None`이 그것이고, ODM 경로는 이 값을 지어내지 않고 명시적으로
`None`을 싣는다(`odm_assets.py` §정확도는 None이다 — null 비율 자체가 Pix4D 전환
트리거의 계측점). 따라서 지금 새로 만들 것이 없다.

**계승하는 것은 코드가 아니라 규칙이다**: 비교하는 두 epoch 모두 검증된 RMSE를
가질 때만 오차한계를 산출하고, 하나라도 없으면 `null`로 두되 **왜 없는지를 함께
싣고 화면에도 "미산출"로 표기한다.** 숫자만 크게 보여주고 한계를 숨기면 INV-024를
UI에서 깨는 것이다.

### D7 — 배포 경계는 유지하고, 저장소·제품은 분리하지 않는다

세 층위를 구분한다. 앞의 둘은 이미 결정돼 있고 셋째만 이 절의 대상이다.

| 층위 | 결정 | 상태 |
|---|---|---|
| 온타깃 런타임/앱 | **분리한다** | 이미 그렇다 — Manifold 3의 자동 기동 PSDK 앱(ADR-KSI-006) |
| 코드 모듈·빌드 경계 | **분리한다** | 이미 그렇다 — `edge/`는 uv workspace·mypy·ruff에서 제외, 자체 CMake·`manifoldctl`·CI 잡 3종 |
| **저장소·제품** | **분리하지 않는다** | 본 결정 |

**사용자에게 두 제품으로 보이지 않아야 한다.** "KSI Site Intelligence를 샀더니
드론이 알아서 매핑하고 순찰하고 점검하고, 서버가 결과를 이해한다"가 되어야
한다 — 자동차의 ECU와 중앙 컴퓨터가 다른 소프트웨어라고 해서 구매자가 두 제품을
산다고 여기지 않는 것과 같다.

**아래는 자동 분리 조건이 아니라 재검토 신호다.** 하나가 발생했다고 저장소를
쪼개지 않는다 — 그 시점에 **새 ADR을 작성해 비용과 이득을 비교한 뒤** 결정한다.

1. Edge가 Core와 **독립적인 릴리스·버전 정책**을 실제로 요구하게 됨
2. KSI Site Intelligence 외의 **두 번째 독립 소비자**가 Edge Runtime을 사용하게 됨
3. Edge와 Core의 **담당 팀·소유권이 실질적으로 분리**됨
4. Autonomous Acquisition Runtime 자체를 **SDK·제품·OEM 형태로 외부 제공**하게 됨
5. 모노레포 때문에 **CI·배포·권한·변경 조율 비용이 실제 운영상 문제**라는 증거가 생김

**코드 줄 수는 기준으로 쓰지 않는다.** 8천 줄이어도 독립 릴리스·독립 사용자가
있으면 분리가 맞고, 5만 줄이어도 한 제품·한 팀·한 릴리스면 모노레포가 낫다.
규모는 경계의 성질을 말해주지 않는다.

## 결과 — 알려진 대가

- **Acquisition 축이 하드웨어에 걸려 있는 대가**: Phase 3의 장비 위험 판단
  자산(kinematic state·CPA/TTC·risk field)이 당분간 유휴 상태가 된다. 축이
  열리는 시점에 그대로 회수되지만, 그때까지 유지보수 비용은 계속 발생한다.
  **진짜 위험은 유지비가 아니라 "안전을 안 한다"·"자율을 포기했다"는 오해**다 —
  이 ADR 자체가 최초 작성본에서 그 오해를 문서로 만들었다(§D2 정정 기록).
  대외 자료·영업 설명에서 같은 혼동이 재발하지 않게 해야 한다.
- **두 축 구조를 정체성으로 삼은 대가**: 목표 아키텍처(perception·tracking·
  local world model·next-best-view)가 곧 현재 능력이라는 오해를 부를 수 있다.
  실제 `edge/`에 그 기능들은 **아직 없다**(명령 유효성 판정·안전 상태기·PSDK
  탭). 헌법과 이 ADR은 제품이 무엇인지를 말하고, **지금 무엇이 되는지는
  `PHASE_REGISTRY.yaml`·goal-ledger가 말한다** — 그 분리를 지키지 않으면
  "문서가 되어 있다고 하니 된 것"이라는 판단이 다시 생긴다.
- **상대 비교의 대가**: 산출한 물량을 **계약 정산 근거로 쓸 수 없다.** 이 한계는
  고객에게 명시해야 하며, 영업 자료에서 "측량"이라는 단어를 쓰지 않는다. 정산
  등급이 계약 요건으로 요구되는 순간이 곧 ADR-KSI-012 D3의 Pix4D 재검토 트리거
  ①("고객이 GCP 기반 측량 정확도 리포트를 계약 요건으로 요구")과 같은 지점이다.
- **KNGeoid 격자 미확보**: 정표고 변환은 격자 데이터 없이 성립하지 않는다. 격자
  파일의 정식 취득 경로와 정확도가 검증되기 전까지 **수직기준 변환은 상용 경로에서
  쓰지 않으며**, 시점 간 상대 비교는 두 epoch가 같은 파이프라인의 타원체고를
  공유한다는 전제로만 성립한다(risk `geoid-grid-provenance-unverified`).
- **기존 ADR을 뒤집지 않는다**: ADR-KSI-003(계보)·005(연결·스코프)·012(엔진·
  라이선스·과금)의 결정은 그대로 유효하며 본 ADR은 그 위에 제품 범위와 계층
  구조를 얹는다. 뒤집힌 결정은 없다.
