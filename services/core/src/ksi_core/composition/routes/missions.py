"""Mission and source-media route mounting."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI


def mount_mission_routes(
    app: FastAPI,
    *,
    event_store: Any,
    evidence_storage: Any,
    mission_signing_key: Any,
    mission_signing_key_id: Any,
    mission_store: Any,
    site_store: Any,
    observation_work_order_store: Any,
    acquisition_connectivity_store: Any,
    acquisition_issue_gate_enabled: bool,
    mission_contract_writer_version: Literal["1.2", "1.3"],
    mission_contract_issuer_id: Any,
    mission_sequence_store: Any,
    acquisition_coordination_store: Any,
    flight_artifact_store: Any,
    coverage_report_store: Any,
    mission_execution_store: Any,
    site_lifecycle: Any,
    source_media_store: Any,
    design_surface_store: Any,
    landxml_ingress_enabled: bool,
) -> None:
    if event_store is not None:
        from ksi_core.events import mount_events

        # edge_sync_store 유무와 무관하게 /v1/events 조회·트리아지 표면은 event_store
        # 가 있으면 항상 장착된다 — edge 수신이 있는 배포에서도 트리아지 화면이
        # 필요하다(mount_edge_sync 는 ingest 라우터만 소유한다).
        # evidence_storage 가 없으면 증거 경로는 장착되지 않는다(404) — 스토리지
        # 없이 라우트만 살려두면 "업로드했는데 어디에도 없다"가 2xx 로 보인다
        # (ADR-KSI-010 §1).
        mount_events(app, event_store, evidence_storage=evidence_storage)

    if mission_signing_key is not None:
        # 위 결합 검증이 mission_signing_key_id·mission_store·site_store 를
        # 전부 non-None 으로 보장한다.
        assert mission_signing_key_id is not None  # noqa: S101
        assert mission_store is not None  # noqa: S101
        assert site_store is not None  # noqa: S101

        from ksi_core.mission_atomicity import MissionIssuanceCommitter
        from ksi_core.mission_issuance import mount_mission_issuance
        from ksi_core.mission_plans import mount_mission_plans

        _mission_store = mission_store
        issuance_committer = MissionIssuanceCommitter(
            site_store=site_store,
            mission_store=_mission_store,
            work_order_store=observation_work_order_store,
            acquisition_store=acquisition_connectivity_store,
            acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
        )

        mount_mission_issuance(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            issuance_committer=issuance_committer,
            writer_version=mission_contract_writer_version,
            issuer_id=mission_contract_issuer_id,
            sequence_store=mission_sequence_store,
        )
        mount_mission_plans(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            issuance_committer=issuance_committer,
            # 스토리지가 있으면 발급 KMZ 바이트를 보관한다 — 서버 안전상수 한 줄이
            # 바뀌면 그 이전 발급분 전량이 영구 409 가 되던 경로를 닫는다(risk
            # kmz-regeneration-determinism-timebomb). 없으면 재생성에만 의존한다.
            kmz_storage=evidence_storage,
            writer_version=mission_contract_writer_version,
            issuer_id=mission_contract_issuer_id,
            sequence_store=mission_sequence_store,
            observation_work_order_store=observation_work_order_store,
            acquisition_coordination_store=acquisition_coordination_store,
        )

    if mission_store is not None:
        from ksi_core.mission_records import mount_mission_records

        # coverage_report_store 는 mission_store 보다 늦게(279행) 조건부 장착되지만,
        # 이 시점에 이미 함수 인자로 들어와 있다(결합 검증이 mission_store 동반을
        # 보장) — 목록/상세 응답에 파생 커버리지 필드를 싣기 위해 여기서 넘긴다.
        mount_mission_records(
            app, mission_store=mission_store, coverage_report_store=coverage_report_store
        )

    if flight_artifact_store is not None:
        from ksi_core.flight_artifacts import mount_flight_artifacts

        mount_flight_artifacts(app, flight_artifact_store)

    if coverage_report_store is not None:
        from ksi_core.coverage_reports import mount_coverage_reports

        mount_coverage_reports(app, coverage_report_store, mission_execution_store)

    if mission_execution_store is not None:
        # 임무 실행 생애주기(ADR-KSI-019 G2) — 발급 기록만으로는 "이 임무가 실제로
        # 날았는가"에 답할 수 없다. 이 표면이 그 축을 연다.
        from ksi_core.mission_execution import mount_mission_execution

        mount_mission_execution(
            app,
            mission_execution_store,
            mission_store=mission_store,
            # 운영자의 "기체로 넘겼다" 선언이 매핑 계열이면 현장도 함께 전진한다.
            site_lifecycle=site_lifecycle,
        )

    if source_media_store is not None and evidence_storage is not None:
        # evidence_storage 없이는 라우트를 장착하지 않는다(evidence 라우트와 같은
        # 관습) — presigned URL 을 낼 스토리지가 없으면 "업로드했는데 어디에도
        # 없다"가 2xx 로 보이는 경로를 만들지 않는다. store 자체(journal)는
        # evidence_storage 없이도 구성될 수 있지만(위 결합 검증은 mission_store만
        # 요구), 그 경우 이 표면은 존재하지 않는다.
        from ksi_core.source_media import mount_source_media

        mount_source_media(app, source_media_store, evidence_storage)

    if design_surface_store is not None and evidence_storage is not None:
        # source_media 와 같은 관습 — presigned URL 을 낼 스토리지가 없으면 이
        # 표면 자체가 존재하지 않는다(등록만 받고 올릴 곳이 없는 구성을 만들지
        # 않는다). store 자체는 evidence_storage 없이도 구성될 수 있다.
        from ksi_core.design_surfaces import mount_design_surfaces

        mount_design_surfaces(
            app,
            design_surface_store,
            evidence_storage,
            landxml_ingress_enabled=landxml_ingress_enabled,
        )
