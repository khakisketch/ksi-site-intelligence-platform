# KSI Platform → KSI Site Intelligence 재사용 감사 보고서

- 감사일: 2026-07-24
- 대상 저장소: `khakisketch/ksi-platform`
- 기준 브랜치: `main`
- main 확인 커밋: `030ebd5a7ff0762e729b29fe7710f8f3a30e8604`
- 추가 검토: Draft PR #2 `agent/dji-mapping-upload-workflow`
- 감사 방식: GitHub 저장소의 문서, 설정, 핵심 코드 경로, 최근 커밋 및 PR에 대한 정적 감사
- 제한: 실제 장비·Docker 스택·테스트 스위트는 이번 감사에서 실행하지 않음

## 1. 결론

현재 저장소는 폐기할 프로토타입이 아니다. 이미 다음 기반이 구현되어 있다.

- Next.js 기반 멀티디바이스 안전 대시보드
- 사용자·기업·현장·구역·장비·권한
- DJI Cloud API 기반 텔레메트리 및 미디어 연동
- 드론/CCTV 실시간 영상 경로
- 사람·장비·PPE 탐지 및 추적
- 텔레메트리 기반 픽셀→지면 좌표 투영
- 사람·장비 근접 및 위험구역 침입 판정
- 인시던트 영속화, 감사로그, Outbox 알림
- ODM 기반 정사영상·3D 복원과 Babylon.js 뷰어
- 실영상 회귀검증과 비교적 큰 테스트 스위트

따라서 KSI Site Intelligence는 전면 재작성보다 **기존 제품의 운영·업무·데이터 계층을 보존하고, 실시간 판단 권한을 Next.js/GB10에서 Manifold로 이동시키는 점진적 재구성**이 적절하다.

그러나 현재 시스템의 핵심 런타임은 여전히 중앙 추론 및 웹 티어 판정 구조다. KSI Site Intelligence가 목표로 하는 Manifold 기반 자율순찰, 4D World Model, Active Perception, 장비 기구학 기반 Risk Field는 구현되어 있지 않다.

## 2. 현재 구현 상태

### 2.1 KSI Dashboard / Next.js

현재 구현:

- Next.js 16, React 19, TypeScript, Zustand
- 모바일·태블릿·데스크톱 대응
- 기업 관리자·안전관리자 역할
- 현장·운영구역·장비·담당자 관리
- 인시던트·보고서·알림·감사로그
- 실시간 영상, 박스 오버레이, 텔레메트리
- Babylon.js 기반 3D 현장 뷰
- 정사영상 기반 2D 구역 편집
- 3D 모델에서 위험구역 생성 및 GPS 정합

판단:

- **유지**
- `KSI Dashboard`의 기반으로 사용
- 전체 앱을 네이티브 또는 새 웹앱으로 재작성하지 않음
- 단, `src/app/system/page.tsx` 단일 대형 컴포넌트와 거대한 Zustand 탭 구조는 분해 필요

### 2.2 KSI Safety Pipeline / FastAPI

현재 구현:

- FastAPI + asyncpg + PostgreSQL
- MinIO 증거 저장
- 현장·구역·장비·인시던트·보고서 API
- 사용자 및 M2M 인증
- Site/Area 기반 테넌트 스코프
- 인시던트·이벤트·감사로그·추론로그·Outbox 단일 트랜잭션
- LISTEN/NOTIFY 및 SKIP LOCKED 워커
- Web Push·증거처리·알림
- CQRS용 Materialized View
- 중복 사건 병합 및 시간축 상태

판단:

- **KSI Core의 기반으로 적극 재사용**
- 다만 현재 `main.py`와 일부 워커의 책임을 도메인별 서비스로 분해
- 비행 중 판단·제어 로직은 이 서버에 추가하지 않음

### 2.3 GB10 추론 서버

현재 구현:

- 드론용 고해상도 사람 YOLO TensorRT
- CCTV용 경량 YOLO 라우팅
- 중장비 YOLO
- BoT-SORT + GMC 사람 추적
- 장비 픽셀 속도 및 캐시
- RF-DETR PPE 비동기 검증
- latest-frame-wins 지연 제어
- 디바이스별 워커
- 실영상 오프라인 A/B 도구

판단:

- **모델, 추적 정책, 전처리, 평가도구는 재사용**
- **중앙 실시간 추론 배포 구조는 최종 제품에서 주 경로로 사용하지 않음**
- Manifold용 TensorRT 파이프라인으로 이식
- GB10은 학습·검증·Shadow 분석·대규모 오프라인 평가 노드로 전환

### 2.4 공간판정 엔진

현재 구현:

- 영상 픽셀과 드론 고도·짐벌·Yaw/Roll·FOV 결합
- 평지와 카메라 Ray 교차
- 사람 발점 및 장비 접지점 ENU 투영
- 장비 Bounding Box 기반 footprint 크기 추정
- 픽셀 속도를 ENU 속도로 변환
- 이동 장비의 캡슐형 위험구역
- GPS Polygon/Circle 침입 판정
- 지면고도 단일 보정값
- 텔레메트리 신선도·기체 안정성 게이트
- 불신 시 픽셀 폴백 또는 침묵

판단:

- **KSI Geo Core의 초기 자산으로 매우 중요**
- 현재 코드는 웹 티어 TypeScript 구현이며 평지 교차 중심
- 최종 SSOT로 그대로 유지하면 안 됨
- Manifold에 C++/Rust 또는 최적화된 Python/CUDA 모듈로 이식
- 다음 기능을 추가:
  - 프레임·텔레메트리 정밀 시간동기화
  - 카메라 캘리브레이션 및 렌즈별 모델
  - 3D Mesh/BIM/Raycast 교차
  - 다중 시점 삼각측량
  - 위치 covariance
  - 층·표면 판정
  - Track 단위 상태추정

### 2.5 위험구역

현재 구현:

- GPS Polygon
- GPS Circle
- Buffer
- 지면고도
- 구역 종류
- 화면 좌표 폴백
- 3D/정사영상 에디터에서 수동 생성

판단:

- 고정 법정구역, 촬영금지구역, 비행금지구역에는 재사용
- 장비 위험구역의 주 방식으로 사용하지 않음
- 향후 장비·인양물 상태로부터 자동 생성되는 3D/4D Risk Field가 주 방식
- 수동 Polygon은 Fallback 및 정책 입력으로 제한

### 2.6 Recon3D

현재 구현:

- FastAPI 프로젝트·캡처·자산 API
- ODM sibling container 실행
- Nerfstudio 명령 템플릿
- 사진/영상 업로드 및 FFmpeg 프레임 추출
- ODM georeferenced GLB export
- `reference_lla.json` 기반 ENU/GPS 정합
- 정사영상 WGS84 재투영
- `ortho.png` 및 affine sidecar 생성
- Babylon.js 모델 뷰
- 프로젝트별 접근 스코프
- 처리 상태와 ODM 로그 기반 진행률

판단:

- **KSI Processing의 첫 Reconstruction Adapter로 재사용**
- 현재 SQLite + 단일 `asyncio.Lock` + 로컬 파일시스템 구조는 제품 확장에 부적합
- 다음으로 이전:
  - Core의 PostgreSQL Job
  - Object Storage
  - Processing Agent/Worker
  - 재시도 및 lease
  - 여러 현장/노드 스케줄링
  - Engine Adapter(ODM/COLMAP/OpenMVS 등)
  - 변경영역 부분 재구성
  - Manifold용 Occupancy/Distance/Surface Map Compiler

### 2.7 DJI Cloud API

현재 구현:

- DJI Cloud API Sample 기반 Spring/EMQX/MySQL/Redis/nginx
- MQTT→WebSocket 텔레메트리 릴레이
- liveStart 및 스피커 연동
- Pilot UI 수정
- Draft PR #2에 자동 사진 업로드→MinIO→recon3d→2D 정사영상 흐름

판단:

- DJI 프로토콜, MQTT Topic, 미디어 업로드, Storage Credential 흐름은 재사용
- DJI 샘플 UI를 KSI 제품 UI의 본체로 사용하지 않음
- `KSI DJI Integration Gateway`로 격리
- PR #2는 유용하지만 Draft이며 main 미병합
- PR 설명상 Python 테스트는 의존성 부족으로 완료되지 않았으므로 병합 전 실행검증 필요

## 3. 재사용 분류

### A. 그대로 유지할 기반

- Next.js/React/TypeScript 기술 스택
- 인증·권한·기업·현장·구역·장비 모델
- 인시던트·보고서·조치·알림 UX
- PostgreSQL·MinIO
- Transactional Outbox
- Site/Area 멀티테넌시
- 3D/정사영상 Viewer
- DJI Cloud API 텔레메트리·미디어 연동 지식
- 오프라인 실영상 회귀도구
- 안전 정직성·테넌트 격리·관측성 원칙
- 기존 테스트의 수학·판정 Golden Case

### B. 추출·리팩터 후 재사용

- `proximity-distance.ts`
- `zone-intrusion.ts`
- `telemetry-freshness.ts`
- `live-zone-overlay.ts`
- `live-people-gps.ts`
- `live-vehicle-overlay.ts`
- GB10 전처리·YOLO·BoT-SORT·PPE verifier
- Recon3D ODM script와 georef export
- Next.js BFF API route
- DJI Cloud API Sample 커스터마이징
- 현장·구역 API
- 모델 프로파일 UI

### C. 운영 Fallback/진단 전용으로 격하

- RTMP/WebRTC 라이브 관제
- 중앙 GB10 실시간 추론
- 픽셀 기반 위험판정
- 수동 장비 반경
- 사용자가 매일 그리는 동적 위험구역
- 원격 서버가 초단위 비행행동을 결정하는 구조
- 전체 영상 상시 업로드

### D. 폐기 또는 격리

- `safety-zone.ts` localStorage 화면좌표 구역
- 정본이 아닌 GB10 `app.py` 복제본
- Mock splat 생성 경로의 운영 사용
- Next.js 내부 1초 판정루프를 Flight Control에 확대하는 설계
- 8천 줄 단일 화면을 계속 확장하는 방식
- 6천 줄 FastAPI `main.py`에 새 도메인을 계속 추가하는 방식
- SQLite 기반 Recon3D Job을 다중 고객 SaaS의 최종 Job DB로 사용
- DJI 샘플 Vue UI를 최종 제품 Dashboard로 확장하는 방식

## 4. 새로 구현해야 하는 핵심

현재 저장소에 없거나 실질적으로 미구현인 KSI Site Intelligence 핵심:

1. **Mission Orchestrator**
   - Baseline Mapping
   - Spatial Refresh
   - Autonomous Patrol
   - Asset Inspection
   - Coverage Recovery

2. **Mission Contract**
   - 조사대상
   - 허용 비행 Volume
   - 금지 Volume
   - 모델·정책
   - 카메라·Viewpoint 정책
   - 실패·배터리·통신두절 정책

3. **Manifold Edge Runtime**
   - Sensor Synchronizer
   - Perception Runtime
   - Multi-Object Tracker
   - Geo-Referenced Localization
   - Local 4D World Model
   - Active Perception
   - Viewpoint Planner
   - Local Planner
   - Flight Supervisor
   - Edge Event Store
   - Offline Sync

4. **4D Site World Model**
   - Static / Semi-static / Dynamic Layer
   - Occupancy
   - Semantic Surface
   - Occlusion
   - Uncertainty
   - Entity Relationship Graph

5. **Equipment Kinematic Library**
   - 타워크레인
   - 이동식 크레인
   - 굴착기
   - 지게차
   - 덤프트럭
   - 인양물

6. **Probabilistic Risk Field**
   - 현재 위험공간
   - 미래 도달 가능공간
   - TTC
   - 예상 최근접거리
   - 위치·추적 불확실성

7. **Spatial Map Compiler**
   - Terrain Height Map
   - Occupancy Grid/Octree
   - ESDF/Distance Field
   - Flight Volume
   - Surface Map
   - Semantic Map
   - Map Freshness Tiles

8. **Processing Fabric**
   - Worker Registration
   - Job Lease
   - Engine Adapter
   - Partial Reconstruction
   - Temporal Alignment
   - Dynamic Masking
   - Change Detection
   - Quality Gate

9. **Data Flywheel**
   - Event Bundle
   - Observation Lineage
   - Review→Label
   - Dataset Builder
   - Model Registry
   - Shadow/Canary/Rollback

## 5. 권장 저장소 구조

```text
ksi-platform/
├─ apps/
│  └─ dashboard/                 # 기존 ksi-safety 이전
├─ services/
│  ├─ core/                      # 기존 pipeline 도메인 분해
│  ├─ dji-gateway/               # cloud-api 격리
│  ├─ processing-controller/
│  └─ media-gateway/
├─ workers/
│  ├─ reconstruction-odm/
│  ├─ reconstruction-structure/
│  ├─ change-detection/
│  └─ dataset-builder/
├─ edge/
│  └─ manifold-runtime/          # 신규 PSDK/Edge Autonomy
├─ packages/
│  ├─ contracts/
│  ├─ domain/
│  ├─ geo-core/
│  ├─ telemetry/
│  ├─ event-model/
│  ├─ ui/
│  └─ test-vectors/
├─ legacy/
│  ├─ gb10-live-runtime/
│  └─ dji-sample-ui/
└─ docs/
```

모노레포 구조 변경은 한 번에 하지 않는다. 기존 경로를 유지하면서 새 디렉터리로 추출하고, Adapter를 통해 점진적으로 전환한다.

## 6. 권장 전환 순서

### Phase 0 — 정본화

- GB10 라이브 코드와 저장소 정본 일치
- Draft PR #2 검증 및 병합 판단
- 현재 테스트 전체 실행
- 배포 환경과 실제 버전 Inventory 생성

### Phase 1 — 계약과 도메인 추출

- `MissionContract`
- `Observation`
- `WorldEntity`
- `RiskAssessment`
- `EventBundle`
- `ProcessingJob`
- `MapVersion`

### Phase 2 — KSI Core 정리

- FastAPI `main.py` 분해
- Next.js in-process 판정 루프를 독립 Core Worker로 이동
- Outbox·인시던트·조치 시스템 유지
- 텔레메트리와 Edge 상태 API 추가

### Phase 3 — Geo Core 이식

- 기존 TypeScript 투영 수식을 Golden Test Vector로 고정
- Edge용 Geo Core 구현
- TypeScript 구현은 UI 재생·검증용 Mirror로 유지
- 프레임 타임스탬프 보간 및 covariance 추가

### Phase 4 — Manifold Runtime

- 카메라 프레임·기체·짐벌 데이터 수집 Spike
- Person/Equipment 모델 TensorRT 이식
- Edge Tracking
- Event 생성
- 서버 연결 없이 로컬 동작

### Phase 5 — 3D 기반 순찰

- Recon3D 결과에서 비행용 Map Compiler 구현
- Manifold에 경량 공간지도 배포
- Active Perception
- Coverage 및 Map Freshness

### Phase 6 — 장비 기구학과 Risk Field

- 장비 한 종류를 깊게 구현
- 권장 첫 대상: 타워크레인+인양물 또는 굴착기
- 다중 시점 재관찰과 위험 이벤트 완성

## 7. PR #2 판단

`Add DJI mapping upload workflow` Draft PR은 KSI Site Intelligence의 Baseline Mapping 흐름에 직접 유용하다.

재사용할 항목:

- Pilot Auto Photo Upload
- MinIO media import
- SN→Project 매핑
- 2D 우선 생성, 3D 지연 실행
- Recon3D capture 연동
- 정사영상 자동 export

병합 전 필수:

- Python unit test 실제 실행
- auth/tenant scope 검증
- idempotency 및 중복 업로드
- 세션 crash recovery
- 대용량 업로드
- MinIO/MySQL 장애
- Job 상태를 Core의 공통 ProcessingJob으로 변환
- SQLite를 장기 SSOT로 사용하지 않도록 분리

## 8. 최종 판단

KSI Site Intelligence는 별도 신규 저장소에서 처음부터 만드는 프로젝트가 아니다.

정확한 방향은:

> 기존 KSI Safety의 운영 플랫폼, 공간판정 수학, 이벤트 파이프라인, DJI 연동, 3D 재구성을 보존하고, 실시간 지능과 자율 임무 권한을 Manifold로 이전하면서 4D World Model과 Risk Field를 추가하는 것.

현재 저장소는 **Dashboard/Core/Processing의 상당 부분을 제공**한다. 가장 큰 미구현 영역은 **Edge Autonomy와 World Model**이다.

따라서 개발비를 기존 기능 재작성에 쓰지 말고 다음에 집중해야 한다.

- Manifold PSDK 통합
- Geo Core 고도화
- 4D World Model
- Active Perception
- 장비 기구학
- Risk Field
- Map Freshness
- 부분 재구성
