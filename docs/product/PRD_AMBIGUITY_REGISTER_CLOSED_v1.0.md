# PRD Ambiguity Register — CLOSED v1.0

제품 범위·책임·기본정책의 모호성은 MASTER_PRD v3.0에서 해소됐다.

남은 항목은 제품 의사결정이 아니라 실제 하드웨어 시험으로 결정하는 Versioned Parameter다.

| Parameter | 결정방법 | 저장위치 |
|---|---|---|
| 접근속도·정지거리 | M4D+Manifold HIL/Field | Vehicle Safety Profile |
| 구조물·사람·전선 이격 | 위험분석+실기 | Vehicle Safety Profile |
| 위치불확실성 중단상한 | Geo Calibration Test | Geo Safety Profile |
| 반개방 복구시간 | Corridor HIL | Localization Profile |
| 장비별 TTC/CPA Threshold | Dataset+Field Validation | Equipment Risk Pack |
| 렌즈별 위치오차 | Calibration | Calibration Profile |

Parameter가 검증되지 않은 경우 보수적 Default 또는 기능비활성으로 처리하며, 임의 추정값을 상용지원으로 표시하지 않는다.
