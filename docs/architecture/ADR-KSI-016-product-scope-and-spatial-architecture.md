# ADR-KSI-016 — 제품 범위 재정의와 공간 데이터 아키텍처 확정

- 상태: ACCEPTED (2026-08-07, 대표자 확정)
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

동시에 대표자가 제품 방향을 재정의했다: 실시간 안전(KSI Safety)과 공간 지능
(Site Intelligence)을 분리하고, 드론을 "능동적으로 데이터를 수집하는 로봇"으로
보며, 핵심 경쟁력을 시계열 공간 이해·설계 대비 비교·능동 재수집에 둔다.

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

### D2 — 핵심 가치 우선순위 재배치

| | 기존 (PRODUCT_CONSTITUTION 동결본) | 개정 |
|---|---|---|
| 1 | 자율 안전순찰 | **반복 수집 기반 시계열 공간 이해** |
| 2 | 지속적인 공간지도 최신화 | **공정·변화·물량 분석** |
| 3 | 공정·변화·물량 분석 | **설계 대비 시공 상태 비교** |
| 4 | 구조물·시설물 점검 | **구조물·시설물 점검** |

**자율 안전순찰은 삭제가 아니라 이동이다.** 실시간 안전관리는 KSI Safety 제품
축으로 옮긴다 — 그쪽은 입력 센서가 드론에 종속되지 않고(CCTV·작업자 단말·중장비
위치·IoT), 고가의 Matrice + Manifold를 전제하지 않는다.

**두 제품은 코드베이스를 분리하지 않는다.** 임무 루프·증거 저장·site frame은 두
제품의 공용 기반이고, 같은 순찰 비행이 공정 epoch와 안전 증거를 동시에 채집한다는
것이 오히려 경쟁 우위다(MASTER_PRD §23.4의 "동일 반복비행 데이터 루프" 논지).
분리는 제품 정의·UX·영업 레벨에서 수행한다.

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
→ Design layer                IFC/도면 → site frame 정합(services/bim-integration)
→ Temporal state              epoch 간 diff: 변화 후보·구역 체적·진척
→ Intelligence                재촬영 권고 → 임무 초안(폐루프)
   ↘ 별도 실시간 축            Edge 프레임 → 이벤트 → 증거 (KSI Safety)
```

**두 축은 접점만 공유하고 합류하지 않는다.** 실시간 축은 프레임 기반(비행 중),
공간 축은 재구성 기반(비행 후)이다. 이 분리는 ADR-KSI-003 §결과 2항이 이미
선언했고 ADR-KSI-012 D6(서버 second-pass 재탐지 기각)이 재확인했다 — 본 ADR은
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

**이미 DJI나 기존 제품이 잘 해결하는 문제를 핵심 기술로 삼지 않는다** — 드론
매핑·정사영상 생성·자동 비행·단순 객체 탐지는 기존 생태계가 제공한다. 우리 자리는
그 산출물들 **사이**, 즉 시점 간 비교와 설계 대비와 다음 행동 결정에 있다.

### D5 — 우선순위를 낮추는 것

구현물을 버리지는 않되 추가 투자를 중단한다. 재논의 시 이 목록이 기준이다.

- **Phase 3 장비 kinematics·CPA/TTC·위험장 고도화** — 구현물 유지, SI 로드맵에서
  제외. KSI Safety 자산으로 재분류한다.
- **Phase 5 Dock·Fleet·산업중립 팩** — 동결 유지. "산업 중립"은 아키텍처 원칙
  으로만 남기고 시장 전략에서 제거한다. 첫 유료 건설 현장 이전에 다른 산업은 없다.
- **Edge perception 신규 코드** — 하드웨어 스파이크 전에는 착수하지 않는다
  (ADR-KSI-006이 세운 규율의 연장).
- **자연어 질의·LLM 보고서 표면** — 데이터 계층이 서기 전에는 데모다.
- **뷰어·측정 UX의 정면 경쟁** — 성숙한 기존 제품을 따라잡는 게임을 시작하지
  않는다.

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

## 결과 — 알려진 대가

- **안전순찰 강등의 대가**: Phase 3의 장비 위험 판단 자산(kinematic state·CPA/TTC·
  risk field)이 SI 로드맵에서 당분간 유휴 상태가 된다. KSI Safety가 제품으로
  진행될 때 회수되며, 그때까지 이 코드의 유지보수 비용은 계속 발생한다.
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
