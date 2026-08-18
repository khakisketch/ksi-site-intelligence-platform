# 시스템 완성 로드맵 — 실행 순서와 근거 (2026-08-18)

> 이 문서는 **실행 순서를 정한 문서**다. "지금 무엇이 진행중인가"의 정본은
> goal-ledger(`.ksi/goals.json`)와 PHASE_REGISTRY이며, 이 문서에 상태를 복제하지 않는다.
> 각 하위 계획은 착수 시점에 별도 실행 계획 문서로 상세화한다(YAGNI — 미리 다 쓰지 않는다).

## "완성"의 정의 (문서 근거)

- `docs/product/MASTER_PRD_v3.0.md` §26 — 7개 완료 기준(Architecture / Autonomy /
  Spatial Intelligence / Unified Mission / Event & Workflow / Reliability / Data Governance)
  동시 만족.
- `docs/architecture/ADR-KSI-018-phase3-redefinition-closed-loop.md` — 폐루프 1회
  **Field Proven**(실비행 종단 검증). 2026-08-14 기준 Field Proven 0건.
- 완료 등급 어휘: Product Ready / Backend Ready / Edge Ready / HIL Proven / Field Proven.
  보고 시 반드시 구분한다.

## 현재 위치 (2026-08-18 조사 결과 — 시점 스냅샷)

- 폐루프 서버 결선(발급→배포→커버리지→사진회수→재구성작업→산출물→모델갱신→재관측 임무)은
  e2e 2건(`tests/e2e/test_aol1_mapping_autonomy.py`, `test_aol2_reobservation.py`)으로
  **Backend Ready**. 사람 개입 없는 상태 전이까지 검증됨.
- e2e 2건이 재구성 워커를 **대역(mock)으로 돌리는 것은 사실이나**, 그것이 "실엔진 경로가
  미완"이라는 뜻은 아니다 — 실엔진 계약은 별도 파일(`tests/contract/test_odm_live.py`)이
  실 NodeODM·실 MinIO 대상으로 검증한다. 아래 정정 참조.

> **2026-08-18 정정.** 이 문서 초판은 S2(실재구성 종단)를 "미완"으로 적었으나, 근거로 삼은
> 것이 2026-08-07 시점의 낡은 관측이었다. 목표 원장을 직접 확인한 결과
> `m1-spatial-epoch-pipeline`(바이트 영속→정좌표→체적 리포트→화면)이 **2026-08-09에
> 완료 판정**됐고(증거: 실 NodeODM+MinIO+Core 대상 `test_odm_live.py`,
> `test_geo_spatial_vertical.py`, `test_dsm_diff.py` 골든값, PR #2 merge 1419c5f),
> `site-intelligence-e2e-sw`·`m3-processing-worker-runtime`·`m2-change-detection-submission-ui`·
> `m4a-design-conformance` 도 모두 completed 다. 좌표변환(pyproj·지오이드)·물량(DSM diff)·
> 산출물 presigned 서빙은 이미 구현돼 있다. **S2 는 신규 과제가 아니라 회귀 확인 대상이다.**
- 하드웨어 없이는 불가: track-a/b(Manifold 3 전원+네트워크), FIELD-0~3(실기·현장),
  phase-5(Dock 조달 판단).
- 대표자 서면 결정 대기 4건: PSDK 직접 실행 허용 여부, 비행 상한 기준 분리,
  C2-S2(무프로펠러 START), C2-S3(감시 하 실비행).

## 실행 순서 — 소프트웨어 트랙 (지금 진행 가능)

우선순위 근거: 2026-08-14 대표자 확정(P0 HIL → P1 실촬영·ingest·재구성 → P2 분석·재관측
→ P3 지도 하나 UI). 기능 추가보다 폐루프 완주가 우선.

### S1. M4D 비행파일 신뢰성 ← 다음 실행 계획
- 내용: 2026-08-18 DJI 공식 문서 조사로 확정된 값 반영 — 기종값(M4D=100, 현재 99는
  M4E 값)·페이로드값(98, 현재 65534)·카메라 공식 스펙 유도값(현재는 1인치급 대체값).
  high 리스크 2건(`mission-drone-enum-value-is-not-m4d` 해소,
  `mapping-camera-constants-are-not-m4d` 는 실측 전까지 open 유지) + FIELD-0a 킷 재생성.
  KMZ 형식 차이 8건은 **이 범위가 아니다** — 실기 임포트 증거로 판정한다는 기존 결정
  (FIELD_0A_CHECKLIST §3)을 유지한다.
- 근거: FIELD-1(첫 실비행)의 유일한 전제인 `field-0a-kmz-acceptance`에 직결.
  실비행이 가능해지는 순간(하드웨어 연결)에 소프트웨어가 병목이 되지 않게 미리 닫는다.
  모든 발급 비행파일의 사진 밀도·기종 정합에 영향 — 작은 작업량 대비 효과 최대.
- 상세 계획: `docs/superpowers/plans/2026-08-18-m4d-flight-file-fidelity.md`
- 한계(정직): 코드 교정은 Backend Ready까지다. 실기 수용성(기체가 파일을 받아들이는가)과
  카메라 실측은 FIELD-0a에서만 확정된다.

### S2. 실재구성 경로 회귀 확인 (신규 구현 아님)
- 내용: 이미 완료된 실엔진 경로가 **현재 코드에서도 여전히 성립하는지** 재확인한다.
  로컬 상주 환경으로 실행 가능하다: NodeODM `127.0.0.1:13000`(컨테이너 `ksi-nodeodm`,
  NodeODM 2.2.4 / ODM 3.5.6), MinIO `127.0.0.1:19000`(컨테이너 `ksi-minio-m1`,
  자격은 컨테이너 env), 실 DJI 드론 사진
  `~/Desktop/KSI-Projects/datasets/odm_data_toledo/images`(87장)·`odm_data_bellus`(122장).

```bash
KSI_NODEODM_URL=http://127.0.0.1:13000 \
KSI_ODM_IMAGES=/home/ksi/Desktop/KSI-Projects/datasets/odm_data_toledo/images \
KSI_S3_ENDPOINT=http://127.0.0.1:19000 KSI_S3_KEY=... KSI_S3_SECRET=... \
  uv run pytest tests/contract/test_odm_live.py -q -rs
```

- 근거: 이 경로는 CI 기본 경로에서 skip 되므로(컨테이너에 CI 를 묶지 않는 의도된 결정)
  **회귀가 조용히 들어올 수 있는 구간**이다. 주기적 실행이 그 침묵을 메운다.
- 남는 것(정직): 실 M4D 기체 사진으로의 완주는 여전히 FIELD-1 소관이다 — 지금 쓰는
  toledo/bellus 는 공개 샘플이다.

### S3. P3 — 지도 하나 UI ← 소프트웨어 트랙의 실질적 다음 과제
- 내용: 한 지도에서 "지난 현장 → 현재 → 변화 영역 → 재확인 → 다음 비행"이 한 흐름으로
  보이는 화면. 대표자 P3 문언 그대로.
- 2026-08-18 조사로 확인된 현재 상태:
  - 5요소 중 **"지난 현장" 시각화만 없고** 나머지 넷은 구현돼 있으나 세 화면에 흩어져 있다
    (`/reports`, `/sites/[siteId]/changes`, `/sites/[siteId]/report`).
  - **한 지도에 겹칠 수 없는 구조다** — `AoiPolygonMapInner`·`ChangeRegionMapInner`·
    `DiffHeatmapOverlayInner`·`OrthophotoOverlayInner` 가 각자 `MapContainer` 를 소유하고
    각자 `fitBounds` 를 건다. 레이어를 `MapContainer` 밖으로 빼는 리팩터가 선행돼야 한다
    (각 Inner 가 이미 레이어를 별도 함수 컴포넌트로 분리해 둬 이식 자체는 크지 않다).
  - **새 Core API 는 필요 없다** — `fetchOrthophotoArtifactId(jobId)` 가 임의 jobId 를 받는데
    지금은 current 로만 호출된다. baseline jobId 로 한 번 더 부르면 "지난 현장" 레이어가 생긴다.
    (baseline epoch 에 ortho 산출물이 실제로 있는지는 **확인 필요** — 실데이터 확인 사항.)
  - 변화 영역 → 재관측 발급 동선이 현재 **화면 3개·클릭 8~9회**다.
- 착수 전 사용자 확인 필요: "한 지도"가 **레이어를 겹쳐 보는 것**인지 **좌우로 두 시점을
  나란히 두는 것**인지 — 코드로는 판단 불가. 모호하면 얇게 하나 만들어 보여주고 정한다.
- 상세 계획: 착수 시 작성.

### S4. 신뢰·증거 하드닝 (사이사이 소화 가능)
- regressed 리스크 `critical-event-riskfield-evidence-gate-presence-only`(INV-021 게이트가
  존재 여부만 확인) 강화
- `evidence-artifact-content-not-bound-to-registration` — 증거 바이트를 등록 레코드에 결합
- `source-media-sealed-bundle-identity-count-only` — 봉인 번들 내용 대조
- `coverage-reconciliation-not-in-print-or-csv` — 인쇄/CSV 반영
- `edge-runtime-tests-silently-skip-without-sqlite`, `region-extraction-multipolygon-branch-untested`
- 상세 계획: 묶음 착수 시 작성.

### S5. 미구현 불변식
- INV-024 Spatial Quality Report 로직, INV-042 Edge 서명 로더(HIL 전 소프트웨어 부분),
  INV-040 Production 프로파일 테스트.
- INV-043 Dataset Ledger 확장은 자체 학습 데이터 확보 시(뒤로).

## 하드웨어·결정 트랙 (사용자·대표자 행동 필요 — 소프트웨어로 대체 불가)

- H1. Manifold 3 전원 인가 + 네트워크 연결 → track-a(DPK 기동→PSDK 수신) → track-b(Perception 실기 입력)
- H2. FIELD-0(지상 통합) → FIELD-0a(비행파일 수용성·카메라 실측) → FIELD-1(첫 매핑 비행)
  → FIELD-2(현장 폐루프) → FIELD-3(지형추종)
- H3. 결정 4건: PSDK 직접 실행 허용 / 비행 상한 기준 분리 / C2-S2 / C2-S3 (각 건별 서면 승인)
- H4. `patrol-backbone-capture-cadence-hardware-unvalidated` 등 실기 검증 리스크는 FIELD 단계에 귀속

## 뒤로 미룬 것 (ADR-KSI-018 — 먼저 제안하지 않는다)

IFC 업로드 UI · 균열 탐지 UI · 박락/부식/백화 추가 학습 · Dock 3 조합 · 다기체 운영.

## 열린 PR (이 로드맵과 별개로 병합 대기)

- PR #8 `fix/unblocked-hardening-2026-08-17` — 미해소 리스크 4건·표기 정직성·게이트 무음 skip
- PR #9 `feat/coverage-report-reconciliation` — 커버리지 완료 판정 게이밍 차단
