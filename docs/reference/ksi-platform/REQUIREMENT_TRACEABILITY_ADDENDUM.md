# Requirement Traceability Addendum

## 추적 형식

| 요구사항 | 기존 참고 자산 | 채택 상태 | 신규 구현 | 수용 기준 |
|---|---|---|---|---|
| 영상 객체 세계좌표화 | `proximity-distance.ts` | PORT | Geo Core + 3D Raycast | 위치오차 기준 충족 |
| 고정구역 침입 | `zone-intrusion.ts` | EXTRACT | Static Zone Engine | GPS/3D 구역 판정 |
| 동적 장비 위험 | 장비 캡슐 로직 | REFERENCE_ONLY | Kinematic Risk Field | TTC/궤적 기반 |
| PPE 탐지 | YOLO + RF-DETR | PORT | Edge Detector/Verifier | 거리별 Recall |
| 객체 추적 | BoT-SORT GMC | PORT | Edge Tracker | Track churn 기준 |
| 이벤트 영속 | Pipeline Outbox | ADOPT | Event Bundle 확장 | 유실 0 |
| 3D 재구성 | Recon3D + ODM | ADOPT | Processing Adapter | 품질 Gate |
| 정사영상 | ODM export | ADOPT | COG/Tile 확장 | 좌표오차 기준 |
| 지도 신선도 | 없음 | NEW | Freshness Engine | 자동 재스캔 |
| 자율재관찰 | 없음 | NEW | Active Perception | 증거확보율 |
| 비행제어 | 없음 | NEW/SPIKE | Manifold PSDK | 실기 수용시험 |
| 데이터 플라이휠 | 일부 학습도구 | EXTRACT | Dataset Builder | 재현가능 Dataset |

## 상태 정의

- `IMPLEMENTED`: 목표 아키텍처에서 구현·검증 완료
- `REFERENCE_AVAILABLE`: 기존 참고자산 존재
- `PORT_IN_PROGRESS`: 이식 중
- `SHADOW`: 신규·기존 병행 비교
- `SPIKE_REQUIRED`: 하드웨어·SDK 검증 필요
- `BLOCKED`: 외부 제약
- `DEPRECATED`: 신규 사용 금지
- `REMOVED`: 제거 완료

## 에이전트 출력 요구

에이전트는 작업계획에 반드시 다음을 포함합니다.

```text
Requirement ID
Existing Reference
Adoption Decision
Files to Read
Files to Change
New Contracts
Migration Strategy
Tests
Rollback
Open Assumptions
```
