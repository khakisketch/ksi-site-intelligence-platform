# Existing KSI Platform Reference Policy

## 1. 목적

기존 `ksi-platform`은 KSI Site Intelligence의 복제 대상이 아니라
**검증된 문제해결 방식, 도메인 모델, 수학, 운영경험, 테스트 자산의 참조 저장소**로 사용한다.

## 2. 기본 방침

### 보존할 것

- 기업·현장·구역·장비·담당자 도메인
- 인시던트·조치·보고서·알림 업무흐름
- Postgres·MinIO·Outbox
- DJI Cloud API 메시지 흐름
- ODM 기반 공간처리
- 2D·3D Viewer
- 추적·투영·판정의 회귀 테스트
- 운영 장애와 실패사유 기록

### 그대로 계승하지 않을 것

- 중앙 서버가 비행 중 판단의 필수 경로인 구조
- RTMP 전체영상이 AI 입력의 유일한 경로인 구조
- Next.js 내부 판정 루프
- 수동 Polygon 중심 장비 위험판정
- 화면좌표 안전구역
- 단일 거대 컴포넌트·거대 API 파일
- 로컬 SQLite·파일시스템 중심 Processing SSOT
- 실제 배포와 저장소 코드가 다른 운영방식

## 3. 참고 단계

### Step 1 — 문제 대응 여부 확인

기존 코드가 현재 구현하려는 요구사항과 같은 문제를 해결하는지 확인한다.

### Step 2 — 자산 유형 분류

- Domain asset
- Algorithm asset
- Infrastructure asset
- UI asset
- Test asset
- Operational knowledge
- Legacy workaround

### Step 3 — 채택 방식 결정

| 방식 | 의미 |
|---|---|
| ADOPT | 설계·구현을 유지 |
| EXTRACT | 독립 모듈로 분리 |
| PORT | 다른 런타임으로 이식 |
| REFERENCE_ONLY | 아이디어·테스트만 참고 |
| REPLACE | 새 구조로 교체 |
| REMOVE | 사용하지 않음 |
| SPIKE_REQUIRED | 실기 검증 필요 |

### Step 4 — 목표 아키텍처 적합성 검증

다음 질문에 모두 답한다.

- Edge-first 원칙과 맞는가?
- 서버 장애가 비행 안전에 영향을 주는가?
- 오프라인 운용 가능한가?
- 4D World Model과 통합 가능한가?
- 다중 현장·다중 Processing Node로 확장 가능한가?
- 테넌트 격리가 유지되는가?
- 데이터 계보를 보존하는가?

## 4. 소유권 경계

### KSI Dashboard

기존 Next.js 화면과 UI 컴포넌트를 참고하되,
새 메뉴·임무·이벤트 중심 Information Architecture에 맞춰 재조합한다.

### KSI Core

기존 Pipeline의 인증·영속·Outbox·업무흐름을 참고한다.
실시간 자율판단과 비행행동은 소유하지 않는다.

### KSI Edge

기존 GB10의 모델·추적·전처리와 웹 티어의 공간수학을 이식한다.
새로운 Edge Runtime의 소유권은 Manifold에 있다.

### KSI Processing

기존 Recon3D/ODM 파이프라인을 첫 Adapter로 사용한다.
Job·Storage·Worker Scheduling은 새 Processing Fabric이 소유한다.
