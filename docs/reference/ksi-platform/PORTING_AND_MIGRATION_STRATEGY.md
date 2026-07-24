# Porting and Migration Strategy

## 1. 전환 원칙

KSI Site Intelligence는 Big Bang Rewrite를 하지 않는다.

```text
기존 기능 유지
→ 계약 정의
→ 신규 모듈 병행
→ Shadow 검증
→ 트래픽/제어권 이동
→ 레거시 격리
```

## 2. 공간인지 이식

### 기존

```text
GB10 Detection
→ Next.js Telemetry Registry
→ TypeScript Ground Projection
→ Proximity/Zone Incident
```

### 목표

```text
Manifold Camera + Aircraft State
→ Sensor Synchronizer
→ Edge Detection/Tracking
→ Geo Core
→ 4D World Model
→ Risk Field
→ Event Bundle
→ Core
```

### 절차

1. 기존 TS 수학에 대한 Golden Fixture 생성
2. 위도·경도·ENU·고도·카메라 좌표계 명세
3. Edge Geo Core 구현
4. 기존 결과와 회귀비교
5. 3D Surface Raycast 추가
6. 다중 시점과 covariance 추가
7. 웹 판정은 Shadow Mode로 전환
8. Edge 결과가 안정되면 웹 판정 제거

## 3. 추론 이식

1. GB10 모델 Inventory 고정
2. 드론 원본과 Manifold 프레임의 전처리 일치
3. TensorRT 엔진 빌드환경 고정
4. Offline A/B 도구로 정확도 비교
5. Edge 지연·전력·온도 측정
6. 중앙 GB10과 Shadow 비교
7. Edge가 Event 후보를 생성
8. 중앙은 2차 재검증만 수행

## 4. Core 전환

### 유지

- 인증
- 권한
- Site/Area/Asset
- Incident
- Report
- Audit
- Outbox
- Evidence

### 추가

- Mission
- MissionContract
- EdgeDevice
- EdgeDeployment
- MapVersion
- WorldModelSnapshot
- ProcessingJob
- ModelRegistry
- DatasetVersion

### 제거

- Next.js process 내부 상시 판정루프
- 웹서버 메모리의 실시간 판단 SSOT

## 5. Processing 전환

### 기존

- Recon3D FastAPI
- SQLite
- Local filesystem
- ODM sibling container
- 단일 lock

### 목표

- Core PostgreSQL `ProcessingJob`
- Processing Agent
- Object Storage manifest
- Worker lease
- Engine Adapter
- Retry/Resume
- Quality Gate
- Map Compiler

### 단계

1. 기존 Recon3D를 ODM Adapter로 감싼다.
2. Capture와 Asset API를 Core 계약에 연결한다.
3. 원본 파일을 Manifest화한다.
4. 작업 상태를 Core로 이동한다.
5. SQLite는 로컬 캐시로 격하한다.
6. 두 번째 Worker를 붙여 분산성을 검증한다.
7. 부분 재구성과 Map Freshness를 추가한다.

## 6. UI 전환

기존 탭을 새 Information Architecture로 점진 이전한다.

```text
기존 실시간 관제
→ Mission Runtime

기존 인시던트
→ Events & Findings

기존 3D
→ Site Twin

기존 장비
→ Fleet & Edge

기존 설정
→ Policy & AI
```

라이브뷰는 기본 화면에서 제거하고 예외·진단용으로 유지한다.
