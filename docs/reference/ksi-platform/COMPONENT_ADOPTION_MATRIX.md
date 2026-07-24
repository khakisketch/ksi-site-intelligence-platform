# Component Adoption Matrix

| 기존 자산 | 상태 | 활용 방식 | 목표 위치 | 비고 |
|---|---|---|---|---|
| Next.js Dashboard | EXTRACT | 화면·API·컴포넌트 참고 및 분해 | `apps/dashboard` | 전면 재작성 금지 |
| 역할·권한·Site·Area·Asset | ADOPT | 도메인 유지 | `services/core` | 스키마 정규화 |
| Incident/Report/Action | ADOPT | 업무흐름 유지 | `services/core` | Event Bundle 연결 |
| Transactional Outbox | ADOPT | 그대로 유지 | `services/core` | 알림·증거 |
| MinIO | ADOPT | Object Storage 기반 | Data Plane | 고객별 분리 |
| PostgreSQL | ADOPT | Core SSOT | Data Plane | PostGIS 확장 |
| GB10 YOLO 모델 | PORT | TensorRT Edge 이식 | `edge/manifold-runtime` | 모델 성능 재검증 |
| BoT-SORT + GMC | PORT | Edge Tracking | `edge/manifold-runtime` | 기체 운동보정 확대 |
| RF-DETR PPE | REFERENCE_ONLY | 2차 검증자 패턴 | Processing/Verifier | 온보드 여부 벤치마크 |
| latest-frame-wins | ADOPT | Edge 영상 큐 정책 | Edge Runtime | 지연 누적 방지 |
| 중앙 RTMP 추론 | REPLACE | 학습·Shadow만 유지 | Legacy/Validation | 주 비행경로 금지 |
| Telemetry Registry | EXTRACT | 계약·신선도 정책 참고 | Core + Edge | Edge SSOT 추가 |
| `proximity-distance.ts` | PORT | Golden Vector 후 Geo Core 이식 | `packages/geo-core` | 평지→3D 확장 |
| `zone-intrusion.ts` | EXTRACT | 고정 정책구역에 사용 | Geo/Risk | 동적 장비구역 아님 |
| Pixel Polygon zone | REMOVE | 레거시 호환 외 금지 | Legacy | 세계좌표 사용 |
| 장비 Circle/Capsule | REFERENCE_ONLY | Fallback 및 초기 비교 | Risk Engine | 기구학 Risk Field로 교체 |
| Temporal voter | EXTRACT | 사건 안정화 패턴 | Edge Event Engine | 상태 외부화 |
| Episode dedup | ADOPT | 사건 중심 정책 | Core/Edge | Detection 저장 금지 |
| Recon3D API | EXTRACT | Adapter API 참고 | Processing Controller | SQLite 제거 |
| ODM scripts | ADOPT | 첫 Reconstruction Engine | Worker | 엔진 종속 격리 |
| Nerfstudio path | SPIKE_REQUIRED | 구조물 모델 용도 검증 | Worker | 운영 mock 금지 |
| Babylon.js Viewer | ADOPT | 3D 결과 Viewer | Dashboard | 대용량 타일링 추가 |
| Ortho map affine | ADOPT | 2D 지도 좌표 SSOT | Processing/Dashboard | COG 고려 |
| DJI Cloud Sample | EXTRACT | 프로토콜 Gateway | `services/dji-gateway` | 제품 UI와 분리 |
| Draft PR #2 media flow | SPIKE_REQUIRED | Auto Photo Upload 참고 | Media Gateway | 테스트 후 채택 |
| Web Push | ADOPT | 이벤트 알림 | Core | 우선순위 정책 유지 |
| Live view UI | REFERENCE_ONLY | 진단·수동개입 | Dashboard | 기본 OFF |
| `page.tsx` 단일 화면 | REPLACE | 기능별 Route 분리 | Dashboard | 추가 확장 금지 |
| FastAPI 거대 `main.py` | REPLACE | 도메인별 Router/Service | Core | 점진 분해 |
| GB10 복제 app.py | REMOVE | 정본 단일화 | Legacy | 배포 divergence 제거 |
| SQLite Processing DB | REPLACE | PostgreSQL ProcessingJob | Core | 로컬 캐시는 허용 |
| Mock splat | REMOVE | 테스트 fixture에만 허용 | Tests | 운영 금지 |

## 신규 핵심 구성요소

| 신규 구성 | 목적 |
|---|---|
| Mission Orchestrator | 현장상태에 따른 임무 조합 |
| Mission Contract | Core→Edge 불변 계약 |
| Sensor Synchronizer | 영상·RTK·짐벌·기체 시간정합 |
| 4D World Model | 정적·준정적·동적 현장 상태 |
| Equipment Kinematics | 장비 자세·도달공간 |
| Probabilistic Risk Field | 현재·미래 위험공간 |
| Active Perception | 불확실성 감소를 위한 재관찰 |
| Viewpoint Planner | 위치·Yaw·짐벌·렌즈 계획 |
| Flight Supervisor | 안전제약 후 DJI 행동 실행 |
| Spatial Map Compiler | 3D 결과→비행용 지도 |
| Map Freshness Engine | 재스캔 범위·시점 자동 결정 |
| Processing Fabric | 분산 자체 3D 처리 |
| Dataset Builder | 운영검토→학습데이터 |
