# services/core

KSI Core: identity, site, Mission Contract, event workflow, map/model registry and audit.

Core는 장비별 SDK 코드를 소유하지 않는다. 장비 배치·연결 정책은
`ksi_core/acquisition/`의 profile/readiness store와 `coordination` 원장·API로
분리하고, 실제 연결 선택과
전송은 `services/dji-gateway`가 소유한다. `GATEWAY_DEVICE`와 `EDGE_DEVICE`는 별도
Principal이며 서로의 ingest 권한을 공유하지 않는다.

readiness projection은 항상 fail-closed 상태를 보여주지만 신규 Mission 발급에 이를
강제하는 `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED`는 기본 OFF다. 실장비 capability
receipt와 기존 Site profile migration이 끝난 뒤에만 `true`로 rollout한다.

승인된 WorkOrder는 `(organizationId, workOrderId, cycleNumber)`로 멱등한
`AcquisitionRun`을 만든다. Run은 Mission 연결과 capability별 Gateway operation
receipt만 소유한다. 실제 activation, 원본 봉인·검증, Processing 상태는 각각 기존
MissionExecution·SourceMedia·ProcessingJob 원장이 계속 권위이며
`GET /v1/observation-work-orders/{id}/acquisition-progress`가 이를 합쳐 보여준다.
