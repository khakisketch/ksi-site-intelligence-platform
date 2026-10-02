# 첫 제품 FPC-01 현재 상태 대조 — 2026-09-28

범위: [첫 제품 로드맵](../superpowers/plans/2026-09-28-first-product-completion-roadmap.md)의 FPC-01. 현재 제품 slice는 [EXT-VAL](../superpowers/plans/2026-09-07-external-artifact-validation.md)이며 이 대조는 수용 판정이 아니다. 기준 Git HEAD는 `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`이고, 그 위의 미커밋 126개 일반 파일 경로·해시는 `.opencode/artifacts/first-product-completion-20260928/baseline.json`에 보존했다. 따라서 아래 구현은 릴리스된 코드가 아니라 작업본이다.

| 수용 항목 | 현재 코드·시험 근거 | 남은 증거/결손 |
| --- | --- | --- |
| EXT-VAL-01/02 파일 관측과 신고값 구분 | `external_artifact_inspections.py`, `external_geotiff_inspector.py`, `external_evidence_validations.py`; `tests/contract/test_external_quantitative_production_flow.py` | 새 고객 파일을 독립 검사 런타임에서 읽어 선언과 비교한 운영 증거 없음. Terra export 자료 없음. |
| EXT-VAL-03/04 용도별 판단과 보완 | `external_relative_volume_analysis.py`, `external_analysis_api.py`; `tests/contract/test_external_analysis_execution_integration.py` | 합성 fixture의 정책·차단·잠정 경로는 검증됐으나 새 업로드의 검사→적합성→수치 전 구간은 미수용. 알려진 검사 실패는 잠정 수치로 우회 금지. |
| EXT-VAL-05 보안·내구성 | Core 원장과 lease/fence, `tests/replay/test_external_analysis_api_replay.py`, `test_external_analysis_http_integration.py` | 실제 독립 워커 장기 실행·장애·재시작·고객 권한/객체저장소 통합 증거 없음. |
| EXT-VAL-06 독립 실행 | `external_inspector_daemon.py`, `external_analysis_worker.py`, `deploy/external-runtime/README.md` | 기존 EXT-VAL 원장의 결정대로 준비된 호스트, release evidence, 별도 계정·격리·ACL이 필요. 로컬 fixture가 이를 대체하지 않음. |
| EXT-VAL-07/08 검토·수용 | AX/MCP/PX 원장과 로컬 검증 기록 | 같은 소스 SHA의 종합 검토·배포·실자료/현장 수용 없음. 제품 책임자 acceptance 없음. |

첫 요청 계약과 비교한 추가 결손:

- 현재 `ExternalReconstructionSubmissionV1`은 `external_reconstruction.py`에서 정사영상을 정확히 하나 요구한다. [첫 요청 계약](../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md)은 V2 물량 입력을 시점당 DSM 하나로 정하고 정사영상은 선택 사항으로 둔다. V1 이력/스키마를 완화하지 않고 별도 버전의 등록 계약과 Core 라우트를 설계·검증해야 한다. 이것은 FPC-03/04의 구체적 입력 결손이며, 현 로컬 fixture는 정사영상을 함께 등록해 이를 드러내지 않는다.
- `docs/acceptance/CIVIL_FIELD_DATA_INTAKE.md`는 과거 **managed Civil Processing v1**의 원본 JPEG·GCP·LandXML 수집 절차다. 첫 제품의 고객 측 재구성 산출물 접수 안내로 사용하면 입력 범위를 잘못 넓힌다. FPC-02의 별도 고객 자료 패킷은 DSM·처리 보고서 중심으로 작성하고, 해당 과거 문서에는 적용 범위를 명시해야 한다.
- PX 원장의 실제 Core HTTP·S3 새 업로드는 검사 미완으로 `NOT_STARTED + BLOCKED`, 수치 `null`이었다. AX의 합성 자료 수치 결과와 합쳐서 하나의 실제 종단 성공이라고 주장할 수 없다.
- `t0→t1` 다음 `t1→t2`에서 WorkArea/설정만 재사용하고 새 입력 결속·pair authority·결과를 생성하는 시험과 현장 반복 업무 증거가 없다. FPC-09의 선행 소프트웨어 시험은 기존 두 시점 fixture를 세 시점으로 확장해 수행할 수 있으나 고객 수용은 FPC-02/10/11 뒤에만 가능하다.
- `EXT-VAL` 원장은 만료된 authority snapshot의 Core 기동 위험을 기록한다. 무관한 Core 경로는 살아 있고 외부 분석만 차단되는 정책은 FPC-15의 별도 설계·수정 과제다.

2026-09-28 집중 검사: `uv run pytest tests/contract/test_external_analysis_http_integration.py tests/contract/test_external_analysis_execution_integration.py tests/replay/test_external_analysis_api_replay.py -q` → **14 passed** (기존 `/tmp/pytest-of-ksi` 청소 권한 경고 12건). 이 결과는 위 시험 파일만 입증한다.

후속 소프트웨어 작업: V1 불변을 지키는 DSM-only V2 입력 **계약** 증분은 [FPC-03A](../superpowers/plans/2026-09-28-dsm-only-ingress-contract.md)에서 로컬 검증했다. 다음 bounded task는 이 계약의 Core 등록·봉인/manifest·검사/Analysis 선택자 배선이다. V2 계약 모델이 있다고 새 DSM-only 파일을 등록할 수 있는 것은 아니다. 운영 호스트·실제 고객 파일·반출 권리는 별도 입력/승인 게이트로 유지한다.
