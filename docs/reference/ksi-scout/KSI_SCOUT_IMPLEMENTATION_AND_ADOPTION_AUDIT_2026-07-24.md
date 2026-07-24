# KSI-Scout 구현 현황 및 KSI Site Intelligence 채택 감사

- 감사일: 2026-07-24
- 대상 저장소: `khakisketch/KSI-Scout`
- 기준 브랜치: `main`
- 감사 시점 최신 확인 커밋: `42ccc0db9a274db94746284bdfbf73db847f5afd`
- 감사 방법: README, PRD, 아키텍처, 정규 계약, DAL, DJI Adapter, 시간동기화, Geo, Rule, Event, Evidence, Mission, DB, Worker, Dataset Registry, Frontend, 검증 스크립트 및 최근 커밋에 대한 정적 코드 감사
- 제외: 실제 M4D/RC Plus 2/Manifold 3 연결, RTMP·MQTT 왕복, TensorRT 벤치, Docker 기동, 전체 테스트 실행
- 법적 성격: 기술·라이선스 위험 정리이며 법률의견서가 아님

## 1. 결론

KSI-Scout는 폐기할 프로토타입이 아니다. 다음 자산이 실제 코드로 구현돼 있다.

- 제조사 중립 Frame/Telemetry/Capability/Detection 계약
- DroneAdapter와 DJI MQTT/RTMP Adapter
- 영상·텔레메트리 시간보간
- Frame quality, Detection, Tracking, Association, Size Gate, PPE 상태
- 단일 프레임 확정 방지 Temporal Voting
- 영상 객체의 지면 좌표 투영, confidence와 error radius
- 위험구역 진입 및 사람-장비 근접 후보
- Event 상태머신, Dedup, Evidence Bundle
- FastAPI, 조직·현장·역할, 감사로그, Idempotency, 알림, 리포트
- Mission/Wayline/Schedule/Run 상태와 WPML 생성
- 공개 데이터셋 Registry, 상업사용 플래그, Dedup/Provenance
- Next.js 관제 콘솔

그러나 KSI-Scout의 과거 Locked Decision 중 다음은 KSI Site Intelligence 목표와 충돌한다.

- 서버 중앙 추론
- 수동 비행 우선
- RTMP 기반 5~15초 알림
- 자동비행은 인터페이스만
- 평지 기반 Geo를 라이브 최종 판단으로 사용
- Dock 중심 Mission 실행
- 측량 산출물을 외부에서 받아 Viewer만 제공

KSI Site Intelligence에서는 KSI-Scout를 그대로 실행하는 것이 아니라 다음과 같이 사용한다.

> KSI-Scout의 안전 판단 계약·이벤트·증빙·운영 백엔드를 참고하고, 실시간 AI/Geo/Rule 파이프라인은 Manifold Edge Runtime으로 이식한다. 서버는 Mission Contract, 이벤트 검토, 영속화, 보고서와 모델 거버넌스를 담당한다.

## 2. 실제 구현 성숙도

| 영역 | 구현 상태 | KSI 판단 |
|---|---|---|
| Frame/Telemetry/Capability 계약 | 구현 | 채택·확장 |
| DroneAdapter | 구현 | Interface 참고 |
| DJI MQTT/RTMP Adapter | 구현, 실기 검증 TODO | Cloud/diagnostic 참고 |
| TelemetryInterpolator | 구현 | 적극 이식 |
| Detection abstraction | 구현 | 적극 이식 |
| Tracking fallback | 구현 | 참고 후 Edge tracker 통합 |
| PPE 상태·Size Gate | 구현 | 적극 채택 |
| Temporal Voter | 구현 | 채택하되 시간기반 확장 |
| Live Geo Projection | 구현, 평지 가정 | Golden baseline으로 이식 |
| Geo confidence/error radius | 구현 | 적극 채택 |
| Zone Layer | 구현, 2D GPS polygon | 고정 정책구역으로 채택 |
| Equipment proximity | 구현, 장비별 정적 반경+속도 | 초기 baseline만 |
| Event Engine | 구현, 메모리 상태 | 계약 채택·Runtime 재구현 |
| Evidence Builder | 구현 | Event Bundle로 확장 |
| Notification/Report | 구현 | Core에 참고·채택 |
| JWT/RBAC/Org isolation | 구현 | Core 기반 |
| Idempotency/Audit | 구현 | 적극 채택 |
| Mission state machine | 구현 | 참고 후 Mission Contract로 교체 |
| WPML KMZ | 구현, 자기 round-trip만 검증 | Spike용 참고 |
| Weather gate | 구현, 실 KMA onboarding 남음 | 정책 Gate로 참고 |
| DB Mission rows | 구현 | 일부 계약 참고 |
| Dataset Registry | 구현 | License Ledger로 확장 |
| Ultralytics training path | 구현 | 상용 라이선스 전제 아니면 제외 |
| RF-DETR optional path | 구현 골격 | 허용 모델 후보 |
| Frontend | 구현 | 컴포넌트·UX 참고 |
| CI | 없음, local verify script | 중앙 CI 필수 신규 |

## 3. 적극 활용할 자산

### 3.1 정규화 계약

다음 개념을 KSI Edge 계약의 시작점으로 사용한다.

- `NormalizedFrame`
- `NormalizedTelemetry`
- `Capability`
- `Detection`
- `BBox`
- `SourceQuality`

필수 확장:

```text
sensor_timestamp
monotonic_timestamp
aircraft_attitude
velocity_ned
angular_rates
camera_id
lens_id
intrinsics_id
exposure
focus_state
gimbal_mode
rtk_quality
covariance
sequence_number
source_provenance
```

### 3.2 시간 동기화

`TelemetryInterpolator`의 다음 패턴은 그대로 활용 가치가 높다.

- 역순 도착 샘플 정렬
- 선형 보간
- Heading/Yaw 최단호 보간
- 최대 Gap에 따른 Quality 강등
- MQTT Callback과 소비 Thread 동시성 보호
- 외삽 대신 가장 가까운 샘플+Degraded

Manifold에서는 Python List 기반 구현을 그대로 쓰기보다 Ring Buffer/C++ 또는 Rust 모듈로 이식하고, Camera Hardware Timestamp와 Aircraft State timestamp를 사용한다.

### 3.3 Detection·PPE 계약

다음 원칙을 KSI 불변식으로 채택한다.

- Detector는 객체 후보만 만든다.
- PPE 미검출을 즉시 미착용으로 확정하지 않는다.
- 작은 사람은 `unverifiable`.
- 단일 프레임으로 사건을 확정하지 않는다.
- 사람과 PPE를 공간적으로 Association한다.
- 2차 검증자는 실시간 주 경로를 막지 않는다.

### 3.4 Geo baseline

현재 Geo 코드는 다음을 실제 구현한다.

- OpenCV Camera Ray
- ENU 좌표계
- Heading/Gimbal Pitch/Yaw/Roll 합성
- 지평선 위 광선 거부
- 평면 지면 교차
- ENU→WGS84
- Geo confidence
- Position error radius
- Zone boundary uncertainty

KSI에서는 이 코드를 Golden Test Vector로 고정한 후 다음으로 확장한다.

```text
Flat Ground Raycast
→ Terrain Height Raycast
→ Mesh/BIM Surface Raycast
→ Multi-view Triangulation
→ Track State Estimation
→ Covariance Propagation
```

### 3.5 Event Candidate·Event Lifecycle

다음은 KSI Edge/Core 공통 계약으로 활용한다.

- `EventCandidate`
- Event type catalog
- Severity
- `suspected → confirmed/false_positive/resolved`
- Track 기반 Dedup
- Secondary key로 장비·구역 구분
- 프레임당 한 번만 누적
- 미관측 시간 후 Resolve
- Evidence 기반 검토

KSI 최종 흐름은 다음으로 확장한다.

```text
Detection
→ Observation
→ Candidate
→ Evidence Collection
→ Finding
→ Confirmed Event
→ Action
→ Resolution
```

### 3.6 Evidence

기존 Evidence Bundle의 다음 구성은 참고 가치가 높다.

- 원본 프레임
- Annotated 프레임
- Crop
- Detection JSON
- Rule decision
- Telemetry snapshot
- Event JSON

추가할 항목:

- Mission Contract hash
- MapVersion ID
- Edge Runtime version
- Model/Engine revision
- Camera calibration ID
- Observation lineage
- World position/covariance
- Pre/post event clip
- Viewpoint history
- Map snapshot
- Risk field snapshot
- Digital signature

### 3.7 Core 운영 자산

다음은 KSI Core에 채택할 패턴이다.

- Organization/Site/User/Role
- `session_epoch`
- Revoked token
- Device inventory and assignment
- Idempotency key
- Audit log
- Event status transition
- Action/Evidence/Notification
- Report and trend
- Multi-site org isolation
- External notification delivery status honesty

## 4. 참고 후 교체할 자산

### 4.1 DJI Adapter

DJI MQTT OSD 파싱, 연결 복구, 프레임/OSD Pairing은 참고한다.

그러나 Manifold Runtime의 주 입력이 다음이 되어서는 안 된다.

```text
RTMP → OpenCV VideoCapture → Server
```

목표:

```text
Aircraft Camera/PSDK Stream
+ PSDK Aircraft/Gimbal State
→ Manifold local Sensor Bus
```

Cloud MQTT/RTMP는 원격 관제·진단·Fallback이다.

### 4.2 EventEngine/TemporalVoter의 메모리 상태

현재 구현은 단일 프로세스 내 메모리 누적이다. Edge Runtime에서는 다음이 필요하다.

- monotonic time 기반
- 프레임 수가 아닌 duration/confidence 융합
- Edge restart checkpoint
- Track generation ID
- State expiry
- Event lineage
- Offline persistent event journal

### 4.3 장비 근접 반경

현재 장비별 Circle과 `speed × reaction_time`은 초기 비교용으로는 유용하다.

최종 판단은 다음으로 교체한다.

- 장비 종류와 실제 크기
- 기체/붐/암/버킷/후크 Pose
- 속도·회전·가속도
- Reachable volume
- Swept volume
- 사람 예상 궤적
- TTC/CPA
- Position/Track uncertainty

### 4.4 Mission/WPML

유용한 부분:

- 상태 전이표
- Flight ID
- Pause/Resume Breakpoint
- Duplicate ACK no-op
- Daytime/Approved zone/Weather Gate
- WPML/KMZ parser security
- Schedule and mission history

교체할 부분:

- 서버가 Waypoint 전체를 미리 작성하는 구조
- Dock 중심 상태명
- 단순 Wayline 실행을 자율순찰로 간주
- `exitOnRCLost=goContinue` 같은 고정 정책
- Server scheduler가 실시간 판단을 소유

KSI 목표:

```text
Human Approval
→ Signed Mission Contract
→ Manifold Mission Executive
→ Local exploration/viewpoint/path decisions
→ High-level DJI intents
```

### 4.5 Scout Frontend

활용:

- 사건 Timeline
- Evidence review
- Device readiness
- Zone editor UX
- Report/trend
- Role-based operations
- Mobile state handling

제외:

- 별도 Scout 제품 Shell
- RTMP 라이브뷰 중심 정보구조
- KSI Dashboard와 중복되는 조직·현장 관리

## 5. 제거·대체할 결정

| Scout 결정/구현 | KSI 결정 |
|---|---|
| 수동 비행 우선 | RC 이착륙 + Manifold 자율순찰 |
| 서버 중앙 추론 | Manifold Edge 추론 |
| 5~15초 알림 | Edge 즉시 판단, 서버 동기화는 비동기 |
| 자동 순찰 인터페이스만 | 핵심 제품 기능 |
| 평지 Geo만 | Terrain/Mesh/BIM 융합 |
| RTMP가 AI 주 입력 | PSDK/local sensor stream |
| 수동 경로 재생 | Mission Contract 기반 탐색 |
| Dock 자율순찰 중심 | MVP는 RC Plus 2, Dock은 후속 |
| 서버 연결 단절 시 의존 | Mission Contract 범위에서 로컬 계속 |
| MapLayer 흡수 전용 | KSI Processing이 자체 MapVersion 생성 |
| Uniform Circle risk | Kinematic probabilistic risk field |
| 인프로세스 Queue | Edge task supervisor + Core persistent job |
| 단일 서버 SSE Bus | Durable event stream/WS fanout |
| Local verify only | 중앙 CI와 hardware-in-loop gate |
| Ultralytics 기본 상용 경로 | Enterprise 계약 또는 permissive model |

## 6. 데이터셋과 모델 정책

사용자 결정은 다음으로 해석한다.

> 공개 데이터셋으로 합법적으로 확보 가능한 장비·사람·PPE 클래스는 범용 탐지까지 최대한 지원한다. 그러나 심층 기구학·안전 보증 수준은 자체 현장 데이터와 실기 검증이 확보된 장비에만 선언한다.

지원 상태를 구분한다.

```text
DISCOVERED
DATASET_AVAILABLE
BASELINE_DETECTOR
FIELD_VALIDATED
GEO_VALIDATED
RISK_VALIDATED
PRODUCTION_SUPPORTED
```

`데이터셋에 클래스가 있다`는 이유만으로 `안전 지원 장비`라고 표시하지 않는다.

### 상업 데이터 Gate

- CC BY: 상업 사용 가능하나 Attribution과 변경 고지 필요
- NC/BY-NC-SA: 상업 모델 학습에서 제외
- License 불명확: Commercial-safe가 아님
- Roboflow 페이지의 현재 License를 Snapshot/Hash로 보존
- 원본 Dataset/이미지별 출처와 License를 Manifest에 보존
- 얼굴·근로자 영상은 개인정보·초상권·현장 계약 검토

### 모델 Gate

- Ultralytics YOLO: 비공개 상용·Embedded Edge 사용은 Enterprise 계약 또는 AGPL 공개전략 확정 전 Production 금지
- RF-DETR Apache-designated package/weights: 후보로 사용하되 정확한 Size/Revision/Weight license를 Registry에 고정
- 외부 Weight는 코드 License와 별도로 검토
- Model Registry에 license, dataset lineage, benchmark, export toolchain을 기록

## 7. 발견된 기술부채·드리프트

1. README의 테스트 수와 최근 커밋의 테스트 수가 다르다.
2. `geo/__init__.py` 설명은 NoOp 중심이라고 적혀 있으나 LiveGeoProjector가 구현돼 있다.
3. 실제 기체 도착 전 C1/C2 TODO가 남아 있으나 현재 보유 장비는 RC Plus 2 + M4D + Manifold 3이므로 검증계획을 재작성해야 한다.
4. GitHub Actions CI가 없고 로컬 `verify.sh` 의존이다.
5. API 앱에 Demo Evidence Seed 코드가 포함돼 있어 production profile 격리가 필요하다.
6. Mission WPML은 자기 round-trip만 증명하며 실제 기체 수락을 증명하지 않는다.
7. Weather provider가 미설정이면 Static always-go가 가능하므로 production fail-closed 정책이 필요하다.
8. Root `LICENSE`가 감사 시점에 확인되지 않았다.
9. Public dataset registry의 일부 항목이 “확인 권장” 상태다.
10. 실시간 Worker는 DB·Evidence 실패를 fail-open으로 계속하므로 손실 복구 Journal이 필요하다.

## 8. 사용자 인터뷰 결정 반영

### 확정

- 미매핑 공간은 Manifold가 판단하되 속도·거리·행동 제한
- Mission Contract 사전 승인
- 현장 정책 승인 후 정기 임무 자동 실행
- MVP 이착륙은 RC Plus 2
- 비행 중 탐색·우회·재관찰은 Manifold
- 새 장애물은 위험도와 인지신뢰도에 따른 차등 대응
- 통신 두절 시 유효 Mission Contract 범위에서 임무 계속 후 귀환
- 반개방 공간은 사전 매핑된 회랑 안 제한 자율순찰
- AI 사건 확정은 심각도별 정책
- 장비 범위는 상업 사용 가능한 공개데이터+자체데이터로 단계적 확대

### 중요한 해석

통신 두절 계속 수행은 무조건적 계속이 아니다.

다음 중 하나면 임무 중단·안전행동으로 전환한다.

- Position uncertainty 상한 초과
- Map confidence 하한 미달
- 새로운 Unknown obstacle
- Battery reserve 침범
- Flight Controller warning
- Edge health degraded
- Mission Contract TTL 만료
- Localization loss
- Sensor disagreement
- 사람이 개입한 RC command

## 9. 우선 조치

### P0

1. Scout를 KSI PRD의 Reference Implementation으로 등록
2. Frame/Telemetry/Event/PPE 계약 Golden Test 추출
3. TelemetryInterpolator Edge 이식
4. Geo Projection Golden Vector 생성
5. Event/Evidence 계약을 Event Bundle로 확장
6. Manifold PSDK Camera/State spike
7. Ultralytics Production 사용 중지 Gate
8. Dataset License Manifest
9. production demo/static weather fail-closed
10. GitHub Actions CI 추가

### P1

1. Terrain/Mesh raycast
2. Edge Persistent Event Journal
3. Equipment generic detector
4. Excavator kinematics
5. Tower crane/load limited scenario
6. Mission Executive
7. Coverage/Active Perception
8. Communication-loss HIL test
9. Semi-open corridor localization
10. Scout Core workflow를 KSI Dashboard에 통합
