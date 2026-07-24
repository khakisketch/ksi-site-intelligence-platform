# KSI-Terra 구현 현황 및 KSI Site Intelligence 채택 감사

- 감사일: 2026-07-24
- 대상: `khakisketch/KSI-Terra`
- 대상 브랜치: GitHub 저장소 기본 브랜치 `main`
- 감사 시점 최신 커밋: `8d62cd38cb627af5c7f1c108537fc5dda89ca103`
- 방식: 저장소 문서·계약·API·Worker·사진측량·공간연산·AI·뷰어·CI에 대한 정적 코드 감사
- 제외: 실제 Docker 스택 기동, NodeODM 실행, GPU 추론, DJI 기체 연결, 브라우저 렌더 실증
- 법적 성격: 기술·라이선스 리스크 정리이며 법률의견서가 아님

## 1. 최종 결론

KSI-Terra는 단순한 화면 목업이나 빈 스캐폴딩 단계가 아니다. 현재 저장소에는 다음이 실제 코드로 존재한다.

- Organization / Project / Survey / RawImageSet / Artifact / AccuracyReport 정규 계약
- PostgreSQL/PostGIS 기반 멀티테넌트 데이터 모델과 RLS 방향
- JobRunner 추상화, PostgreSQL SKIP LOCKED 큐, 재시도·dead-letter·resume checkpoint
- NodeODM REST 연동과 COG·DSM·DTM·GLB·COPC 산출물 처리
- DJI 이미지 EXIF/XMP RTK·짐벌·고도 텔레메트리 파싱
- DSM 시계열 정렬·차분, 절토·성토 체적 계산
- GCP/CP, 정확도 리포트, 미검증 절대정확도 비노출
- Grounding DINO 정사영상 타일 감지
- SceneObject, 관계, 회차 간 identity, 변화 API
- S3/MinIO ObjectStore, signed URL, native multipart와 체크섬
- Next.js/MapLibre/Three 기반 현장·회차·산출물 UI
- 정적 분석·타입·마이그레이션·정확도·AI 모델 회귀·보안 스캔 CI 정의

따라서 KSI Site Intelligence는 KSI-Terra를 별도 완제품으로 그대로 붙이는 것이 아니라 다음처럼 사용해야 한다.

> KSI-Terra의 공간진실, 측량정직성, Processing Fabric, 시계열 분석 및 Scene Graph 자산을 KSI Site Intelligence의 `Spatial Data Platform`과 `Processing` 기준 구현으로 채택하고, 실시간 Edge Autonomy·4D World Model·장비 동역학은 별도 신규 계층으로 구현한다.

## 2. 실제 구현 성숙도

| 영역 | 실제 상태 | 판단 |
|---|---|---|
| 정규 도메인 계약 | 구현 | 적극 채택 |
| PostGIS/RLS 멀티테넌시 | 상당 부분 구현 | Core 기준으로 채택, 통합 검증 필요 |
| Processing JobQueue/Worker | 구현 | 적극 채택 |
| NodeODM 연동 | 구현 | 기본 OSS 엔진 Adapter로 채택 |
| 정사영상 COG | 구현 | 채택 |
| DSM/DTM | 구현 | 채택, 품질 검증 필요 |
| GLB | 구현 | 채택 |
| COPC | 변환·ODM fetch 연결 구현 | 채택, 대용량 성능 검증 필요 |
| 3D Tiles | 단일 타일 + georef 구현 | 부분 채택, 계층 LOD 신규 필요 |
| GCP 데이터 모델 | 구현 | 채택 |
| NodeODM GCP 적용 | 미완성 | 신규 구현 필요 |
| 정확도 정직성 | 구현 | 플랫폼 불변식으로 승격 |
| DSM 차분·절토/성토 | 구현 | 적극 채택 |
| DJI 사진 XMP 분석 | 구현 | 채택 후보, M4D 실사진 검증 필요 |
| 실시간 드론 자율비행 | 없음/과거 범위 밖 | KSI Edge에서 신규 |
| 실시간 4D World Model | 없음 | 신규 |
| 정사영상 객체 감지 | 구현 | 후처리/검증용으로 채택 |
| 온보드 실시간 감지 | 없음 | Manifold에서 신규 |
| Scene Graph | 정적·회차 기반 구현 | 확장 후 채택 |
| 회차 간 객체 identity | 단순 거리 기반 | 참고만 하고 교체 |
| LLM 자연어 질의 | Tool-use 구현 | 사후 분석용 채택 |
| Production CI 증거 | Workflow 정의는 존재, 최신 head 실행 증거 미확인 | 재검증 필수 |
| 기본 Worker runner | `placeholder`가 기본 | 운영에서는 금지 |

## 3. 가장 가치가 높은 재사용 자산

### 3.1 Shared Site / Survey / Artifact 계약

KSI-Terra는 현장을 Project, 비행 회차를 Survey, 원본을 RawImageSet, 결과를 Artifact로 분리한다. Artifact는 반드시 Survey에서 파생되고, Project 단위 CRS와 수직기준을 고정한다.

KSI Site Intelligence에서는 명칭을 다음처럼 수렴한다.

```text
Terra Project       → KSI Site
Terra Survey        → Spatial Capture / Survey Run
Terra RawImageSet   → Capture Dataset
Terra Artifact      → Spatial Artifact
Terra AccuracyReport→ Spatial Quality Report
Terra Zone          → Site Semantic Zone / Policy Volume
```

기존 UUID와 데이터 계보를 보존하고 물리 rename을 서두르지 않는다. API 계약에서 정본 용어를 먼저 통일한다.

### 3.2 Accuracy Honesty

다음 원칙은 그대로 채택한다.

- RTK Fix는 정확도 신호이지 GCP 검증 자체가 아니다.
- 독립 Checkpoint가 없는 경우 절대 RMSE를 표시하지 않는다.
- 서로 다른 CRS·수직기준 산출물을 직접 비교하지 않는다.
- 클라이언트가 보낸 측정값을 신뢰하지 않고 서버가 재계산한다.
- 결과가 존재한다는 이유만으로 품질이 검증된 것으로 표시하지 않는다.

이는 KSI Site Intelligence의 다음 기능에 공통 적용한다.

- 지도 품질
- 객체 세계좌표 오차
- 위험공간 위치 불확실성
- 변화탐지
- 체적
- 결함 위치
- Coverage Assurance

### 3.3 Processing Fabric

다음 패턴은 직접 활용 가치가 높다.

- `JobRunner.submit / poll / fetch`
- `ComputeTarget`
- PostgreSQL `FOR UPDATE SKIP LOCKED`
- lease/reaper
- transient/permanent 오류 분류
- 지수 backoff와 dead-letter
- 엔진 JobRef resume checkpoint
- Managed/BYO 동일 Artifact 계약
- ObjectStore abstraction

KSI Site Intelligence에서는 `Survey`만 처리하는 큐를 범용 `ProcessingJob`으로 확장한다.

```text
RECONSTRUCT_SITE
GENERATE_ORTHO
GENERATE_DSM_DTM
GENERATE_COPC
GENERATE_3D_TILES
ALIGN_MAP_VERSION
DETECT_CHANGE
COMPILE_EDGE_MAP
BUILD_DATASET
RUN_MODEL_BENCH
```

### 3.4 ODM Adapter

실제 ODMRunner는 다음 산출물을 처리한다.

- Orthophoto COG
- DSM COG
- DTM COG
- GLB
- COPC

따라서 기존 `ksi-platform/recon3d-server`보다 KSI-Terra 쪽 구조를 KSI Processing의 기준으로 삼는 것이 낫다.

단, 현재 ODM submit에서 GCP/geo 입력을 NodeODM 옵션으로 연결하지 않으므로, 측량급 품질을 주장하기 전에 이 경로를 완성해야 한다.

### 3.5 DSM 변화와 물량

`align_and_diff` 계열은 다음을 이미 구현한다.

- CRS 일치 검증
- 공간 교차영역
- 공통 그리드 재표본화
- target - base 차분
- 데드밴드
- 절토·성토·순변화 체적
- Zone 내부 체적
- 정확도 정보가 있을 때만 불확실성 표기

이 기능은 다음 제품 임무에 바로 연결한다.

- 공정 진척
- 토공량
- 자재 더미
- 정기 재스캔
- Map Freshness
- 계획고 대비 이탈

### 3.6 Scene Graph 계약

다음 개념은 채택한다.

- 객체마다 persistent ID
- 관측/주석 provenance
- 객체와 Zone 분리
- 관계 사전계산
- raw geometry를 LLM에 직접 입력하지 않음
- LLM은 구조화된 Tool을 통해 결정론적 계산을 호출
- 모델이 없거나 키가 없으면 degraded로 정직하게 동작

다만 현재 Scene Graph는 비행 회차별 정적/준정적 객체 중심이다. KSI의 실시간 4D 계층으로 확장하려면 아래 필드가 필요하다.

```text
observed_at
valid_from / valid_to
track_ref
world_position_xyz
velocity_xyz
orientation
covariance
observation_refs
source_edge_device
model_version
state
kinematic_type
```

## 4. 참고만 하고 그대로 사용하지 않을 영역

### 4.1 객체 identity

현재 회차 간 identity는 같은 클래스의 중심점 최근접 거리와 Greedy 1:1 매칭이다.

이 방식은 다음 상황에 약하다.

- 같은 종류 장비가 여러 대 밀집
- 장비가 크게 이동
- 일부 회차에서 미검출
- 가림
- 객체 형상 변화
- 장비 방향·규격·특징을 고려해야 하는 경우

따라서 KSI에서는 다음으로 교체한다.

```text
class
+ geometry/size
+ appearance embedding
+ motion history
+ site constraints
+ observation uncertainty
+ assignment optimization
```

기존 구현은 테스트 fixture와 초기 baseline으로만 사용한다.

### 4.2 Grounding DINO

정사영상 후처리와 신규 클래스 탐색에는 유용하다. 그러나 Manifold의 실시간 사람·장비·PPE 추론 주 모델로 사용하지 않는다.

권장 역할:

- 정사영상 객체 후보 생성
- 데이터셋 bootstrap
- 저신뢰 Event의 후처리 검증
- 신규 장비 클래스 탐색
- Offline model comparison

온보드 실시간 경로는 TensorRT 최적화 전용 모델을 사용한다.

### 4.3 자연어 질의

Scene Graph Tool-use 경계는 채택한다. 그러나 LLM은 다음을 직접 수행할 수 없다.

- 비행좌표 생성
- Local Planner 목표 강제
- 충돌회피 판단
- 위험 이벤트 최종 확정
- 안전 수치 추측

LLM은 사후 질의, 보고서 서술, 검토 지원에만 사용한다.

### 4.4 Terra Frontend

MapLibre, Three, 현장/회차/산출물 UX와 정확도 Seal은 참고한다. 별도 KSI-Terra 앱을 사용자에게 추가로 제공하지 않는다.

KSI Dashboard 안에 다음으로 흡수한다.

```text
Sites
Site Twin
Spatial Captures
Progress & Quantities
Map Quality
Exports
```

## 5. 교체하거나 제거할 영역

| 항목 | 결정 | 이유 |
|---|---|---|
| `TERRA_RUNNER=placeholder` 기본값 | REPLACE | 운영 오배선 시 합성 산출물 생성 위험 |
| Production mock fallback | REMOVE | 실제 데이터 실패를 데모로 가리면 안 됨 |
| InMemorySpatialIndex | REPLACE | 4D/다중노드/영속 질의 불가 |
| 단일 타일 3D Tiles | REPLACE | 대형 현장 LOD 스트리밍 부적합 |
| 중심점 Greedy identity | REPLACE | 실시간·다중장비에 부족 |
| Terra 별도 제품 Shell | REMOVE | KSI Dashboard와 중복 |
| “직접 드론 제어는 범위 밖” 결정 | SUPERSEDE | KSI Edge는 임무 수준 로컬 자율행동이 핵심 |
| Metashape 기본 경로 | REFERENCE_ONLY | 비용·서비스 라이선스 부담 |
| 주문·청구·지원 전체 도메인 | DEFER | 초기 Site Intelligence 코어 아님 |
| 지적도·공공조달·CSAP | DEFER | 민간 파일럿 이후 |
| `master` 전용 CI publish 조건 | FIX | 기본 브랜치 `main`과 불일치 |
| 문서의 스텁/완료 상태 불일치 | FIX | 코드와 문서 drift 발생 |

## 6. KSI Site Intelligence에 새로 필요한 영역

KSI-Terra가 제공하지 않는 핵심은 다음이다.

### 6.1 Manifold Edge Autonomy

- Sensor Synchronizer
- Perception Runtime
- Multi-Object Tracker
- Geo-Referenced Localization
- Local 4D World Model
- Equipment Pose/Kinematics
- Probabilistic Risk Field
- Active Perception
- Viewpoint Planner
- Local Planner
- Flight Supervisor
- Edge Event Store
- Offline Synchronization

### 6.2 Spatial Map Compiler

Terra Artifact를 Manifold에서 사용할 경량 지도로 변환한다.

- Terrain Height Map
- Occupancy Octree/Grid
- ESDF/Distance Field
- Flight Volume
- Exclusion Volume
- Surface Map
- Occlusion Map
- Semantic Layer
- Map Freshness Tiles

### 6.3 Unified Mission

KSI-Terra의 Survey는 KSI Mission 안의 한 Capture Obligation으로 편입한다.

```text
Unified Site Mission
├─ Baseline Mapping
├─ Spatial Refresh
├─ Autonomous Patrol
├─ Adaptive Inspection
└─ Coverage Recovery
```

## 7. 적법한 활용을 위한 라이선스 정책

### 7.1 KSI-Terra 자체 코드

감사 시점 루트에서 명시적 `LICENSE` 파일을 찾지 못했다.

사내에서 사용하기 전에 다음을 확인한다.

- 모든 커밋 작성자의 저작재산권이 회사 또는 프로젝트 소유자에게 귀속되는가
- 외주·공동개발 코드에 양도/이용허락 계약이 있는가
- 다른 저장소에서 복사한 파일의 원출처와 라이선스가 기록돼 있는가
- AI 도구가 생성한 코드에 제3자 코드의 실질적 복제가 없는가

루트에 다음을 추가한다.

- `LICENSE` 또는 `PROPRIETARY_LICENSE.md`
- `THIRD_PARTY_NOTICES.md`
- `DEPENDENCY_LICENSE_POLICY.md`
- SPDX 기반 SBOM
- 모델 가중치·데이터셋 권리대장

### 7.2 ODM/NodeODM

ODM과 NodeODM은 AGPL-3.0이다.

REST 별도 프로세스 격리는 기술적으로 좋은 경계지만, 그 사실만으로 AGPL 의무가 자동 소멸한다고 단정하지 않는다.

운영 정책:

- ODM/NodeODM 소스 수정은 별도 fork와 commit으로 관리
- 수정한 AGPL 서비스에 원격 사용자가 상호작용하는 경우 Corresponding Source 제공 경로 검토
- 고객사 온프렘 이미지에 AGPL 구성요소를 동봉할 경우 배포 의무 검토
- KSI 독점 코드는 ODM 프로세스 내부에 결합하지 않고 공개 HTTP 계약으로 호출
- 법무 승인 전 “AGPL 문제 없음” 문구 사용 금지

### 7.3 Grounding DINO

공식 구현 코드는 Apache-2.0으로 표시된다. 코드 사용 시 NOTICE와 저작권 고지를 보존한다.

별도로 확인할 것:

- 실제 사용하는 Hugging Face 모델 revision
- 모델 weight의 이용조건
- 학습 데이터셋의 이용조건
- 파생 fine-tune weight의 배포조건

### 7.4 Metashape

일반 Node-Locked/Floating 라이선스는 제3자에게 인터넷 기반 서비스로 제공하는 권리를 자동으로 주지 않는다. 자동 처리 서비스는 별도 Service Provider License 검토 대상이다.

따라서 KSI 기본 엔진으로 두지 않고 다음에만 사용한다.

- 내부 전문가 Benchmark
- 고객이 자기 라이선스로 실행하는 명시적 Adapter
- 별도 Service Provider License 계약 후 선택적 엔진

### 7.5 Viewer 및 OSS

MapLibre GL JS는 BSD-3-Clause, CesiumJS는 Apache-2.0으로 공개되어 있다. 배포 시 고지문을 유지한다.

Potree, copclib 및 나머지 Python/NPM 의존성은 빌드마다 SBOM과 License Scan으로 확인하고, 허용목록에 없는 라이선스가 들어오면 배포를 차단한다.

## 8. 즉시 조치

### P0

1. KSI-Terra를 KSI Site Intelligence의 `Spatial Processing Reference`로 등록
2. `placeholder` 기본 Runner를 production fail-closed로 변경
3. main/master CI publish 조건 수정
4. 현재 head에서 CI 전부 실행
5. NodeODM GCP/geo 옵션 연결
6. Root LICENSE/Third Party Notices/SBOM 추가
7. mock frontend fallback을 dev 전용으로 제한
8. Shared Site Contract를 KSI Master PRD와 정합

### P1

1. Terra ProcessingJob를 KSI 공통 Job 계약으로 확장
2. Survey를 Unified Mission의 Capture Obligation과 연결
3. Artifact→Edge Map Compiler
4. SceneObject 스키마에 시간·운동·불확실성 확장
5. 계층형 3D Tiles
6. 실 M4D 이미지 XMP 검증
7. 실제 NodeODM 대형 현장 벤치
8. Map Freshness와 부분 재구성

## 9. 채택 판단

KSI-Terra는 KSI Site Intelligence에서 다음 역할을 맡는다.

> Spatial Truth, Mapping/Processing, Accuracy, Timeline Change, Quantity, Spatial Artifact, Static/Semi-static Scene Graph의 기준 구현.

KSI-Terra가 맡지 않는 역할:

> 실시간 비행 안전, Manifold 자율행동, 동적 객체 Tracking SSOT, 장비 기구학, 실시간 Risk Field, 비행 제어.

두 영역은 하나의 Site/Mission/Event 계약으로 연결하되 GPU batch processing과 Edge real-time runtime은 물리적으로 격리한다.
