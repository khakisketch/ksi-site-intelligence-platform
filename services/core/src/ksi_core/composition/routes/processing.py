"""Processing, analysis, and equipment route mounting."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_processing_routes(
    app: FastAPI,
    *,
    processing_job_store: Any,
    evidence_storage: Any,
    site_lifecycle: Any,
    auth_registry: Any,
    checkpoint_validation_store: Any,
    checkpoint_validation_registration_enabled: bool,
    site_store: Any,
    defect_candidate_store: Any,
    change_detection_store: Any,
    volume_change_store: Any,
    comparison_request_store: Any,
    design_conformance_request_store: Any,
    region_extraction_request_store: Any,
    design_conformance_report_store: Any,
    report_export_store: Any,
    work_area_store: Any,
    region_extraction_report_store: Any,
    equipment_state_store: Any,
    equipment_support_store: Any,
) -> None:
    if processing_job_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 원본을 받아갈
        # 다운로드 URL 발급에 필요 — GET .../input).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.processing_jobs import mount_processing_jobs

        mount_processing_jobs(app, processing_job_store, evidence_storage, site_lifecycle)
    elif auth_registry is not None:
        # 처리 실행 표면은 evidence storage 없이는 계속 404다. 다만 Resource Policy는
        # tenant 데이터나 실행 상태가 아닌 Core 전역의 고정 admission envelope다.
        # 인증된 축소 조립(dev/E2E 포함)에서도 이를 조회할 수 있어야 Dashboard가
        # "정책을 모름"과 "실행 인프라가 없음"을 혼동하지 않는다. 수정 API는 없고,
        # processing_job_store가 있는 조립은 위에서 같은 store registry를 노출한다.
        from ksi_core.processing_jobs import build_processing_resource_policies_router
        from ksi_core.processing_resource_policy import ProcessingResourcePolicyRegistry

        app.include_router(
            build_processing_resource_policies_router(ProcessingResourcePolicyRegistry())
        )

    if checkpoint_validation_store is not None:
        # evidence_storage 는 위 결합 검증이 보장한다. 등록 flag가 false여도 sealed
        # 증거의 조회·worker 검증 표면은 유지한다; 신규 operator 등록만 닫는다.
        assert evidence_storage is not None  # noqa: S101 -- assembly postcondition
        from ksi_core.checkpoint_validations import mount_checkpoint_validations

        mount_checkpoint_validations(
            app,
            checkpoint_validation_store,
            evidence_storage,
            registration_enabled=checkpoint_validation_registration_enabled,
        )

    if site_store is not None and processing_job_store is not None:
        # 공간모델 조회(ADR-KSI-019 G1)는 **두 저장소가 모두 있을 때만** 장착한다 —
        # 재구성 원장이 없는 조립에서 이 표면을 열면 모든 현장이 영원히 ABSENT 라고
        # 답하는 거짓 표면이 된다. 없는 편이 정직하다(source_media·evidence 라우트가
        # 같은 이유로 이미 그렇게 동작한다).
        from ksi_core.spatial_model import mount_spatial_model

        mount_spatial_model(
            app,
            site_store=site_store,
            processing_job_store=processing_job_store,
            # 노후 스윕 표면도 함께 장착한다 — 주기 실행은 배포 운영이 소유한다.
            lifecycle=site_lifecycle,
        )

    if defect_candidate_store is not None:
        from ksi_core.defect_candidates import mount_defect_candidates

        mount_defect_candidates(app, defect_candidate_store)

    if change_detection_store is not None:
        from ksi_core.change_detection import mount_change_detection

        mount_change_detection(app, change_detection_store)

    if volume_change_store is not None:
        from ksi_core.volume_reports import mount_volume_reports

        mount_volume_reports(app, volume_change_store)

    if comparison_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 원본을 받아갈
        # presigned URL 발급에 필요 — GET .../input, processing_job_store 와 동일 근거).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.comparison_requests import mount_comparison_requests

        mount_comparison_requests(app, comparison_request_store, evidence_storage)

    if design_conformance_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 설계면·DSM 을
        # 읽어갈 presigned GET 과 차분 래스터 업로드 PUT 을 이 표면이 발급한다).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.design_conformance_requests import mount_design_conformance_requests

        # region_extraction_request_store 는 design_conformance_report_store 뒤에만
        # 만들어지므로(아래 참조) 이 시점엔 아직 None 일 수 있다 — 그래도 안전하다,
        # mount_design_conformance_requests 의 자동 연동은 optional 이라 나중에
        # 다시 장착하지 않는다(성공 전이마다 그 값을 다시 읽지 않고 라우터 생성
        # 시점에 한 번 닫힌다는 뜻 — 그래서 이 아래에서 순서를 보장한다: region
        # extraction 관련 store 조립은 app_assembly.py 에서 이미 design_conformance
        # 계열보다 먼저 끝나 있고, create_app 은 그 결과를 인자로 받을 뿐이다).
        mount_design_conformance_requests(
            app,
            design_conformance_request_store,
            evidence_storage,
            region_extraction_store=region_extraction_request_store,
        )

    if design_conformance_report_store is not None:
        # 같은 사후조건 — 이 표면은 리포트를 받을 때 스토리지 바이트를 직접 읽는다.
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.design_conformance_reports import mount_design_conformance_reports

        mount_design_conformance_reports(app, design_conformance_report_store, evidence_storage)
        # 진척(M4-C)은 같은 원장을 읽는 파생 조회다 — 별도 store 를 만들지 않고
        # 리포트 저장소 위에 라우터만 얹는다. 작업구역 저장소는 구역 이름을 붙이는
        # 데만 쓰이므로 없어도 표는 나온다(zoneId 만 보인다).
        from ksi_core.design_progress import mount_design_progress

        mount_design_progress(app, design_conformance_report_store, work_area_store)

    if report_export_store is not None:
        from ksi_core.report_exports import mount_report_exports

        mount_report_exports(app, report_export_store)

    if region_extraction_request_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 diffRaster 를
        # 읽어갈 presigned GET 을 이 표면이 발급한다).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        assert design_conformance_report_store is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.region_extraction_requests import mount_region_extraction_requests

        mount_region_extraction_requests(
            app, region_extraction_request_store, design_conformance_report_store, evidence_storage
        )

    if region_extraction_report_store is not None:
        from ksi_core.region_extraction_reports import mount_region_extraction

        mount_region_extraction(app, region_extraction_report_store)

    if work_area_store is not None:
        from ksi_core.work_areas import mount_work_areas

        mount_work_areas(app, work_area_store, site_store=site_store)

    if equipment_state_store is not None:
        from ksi_core.equipment_states import mount_equipment_states

        mount_equipment_states(app, equipment_state_store)

    if equipment_support_store is not None:
        from ksi_core.equipment_support import mount_equipment_support

        mount_equipment_support(app, equipment_support_store)
