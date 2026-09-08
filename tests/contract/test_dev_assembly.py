"""dev 조립 지점(scripts/run_core_dev.py)의 CLI→생성자 변환 계약.

이 스크립트는 저장소에 존재하는 **유일한 조립 지점**이다 — 라이브러리 테스트가
전부 green 이어도 여기 배선이 틀리면 실제로 뜨는 서버만 잘못 조립된다. 독립
재검토가 "이 파일을 도는 테스트가 0건"으로 지적한 자리다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.acquisition import AcquisitionConnectivityStore, AcquisitionCoordinationStore
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.capability.authority_store import CapabilityAuthorityStore
from ksi_core.capture_quality_reports import CaptureQualityReportStore
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.checkpoint_validations import CheckpointValidationStore
from ksi_core.comparison_requests import ComparisonRequestStore
from ksi_core.coverage_reports import CoverageReportStore
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.design_conformance_reports import DesignConformanceStore
from ksi_core.design_conformance_requests import DesignConformanceRequestStore
from ksi_core.design_surfaces import DesignSurfaceStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_dispatch import (
    EdgeDispatchStore,
    EdgeRuntimeProfileRegistry,
    RiskPolicyPackRegistry,
)
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.equipment_states import EquipmentStateStore
from ksi_core.equipment_support import EquipmentSupportStore
from ksi_core.events import EventStore
from ksi_core.evidence import EvidenceStorageError
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.flight_artifacts import FlightArtifactStore
from ksi_core.mission_execution import MissionExecutionStore
from ksi_core.mission_records import MissionIssuanceSequenceStore, MissionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.region_extraction_reports import RegionExtractionStore
from ksi_core.region_extraction_requests import RegionExtractionRequestStore
from ksi_core.report_exports import ReportExportStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_core.volume_reports import VolumeChangeStore
from ksi_core.work_areas import WorkAreaStore

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dev_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_core_dev", _REPO_ROOT / "scripts" / "run_core_dev.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # exec_module 전에 sys.modules 에 넣는 것이 importlib 표준 절차다 — 넣지 않으면
    # 모듈 안의 @dataclass 가 어노테이션을 해석할 때 sys.modules[cls.__module__] 를
    # 찾다 None 을 받아 AttributeError 로 죽는다(실측, 2026-08-08).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, None), (1, 1), (500, 500), (64 * 1024 * 1024, 64 * 1024 * 1024)],
)
def test_zero_means_disabled_positive_passes_through(value: int, expected: int | None) -> None:
    """CLI 의 '0 = 없음' 규약이 생성자의 None 으로 정확히 옮겨진다."""
    module = _load_dev_module()
    assert module.cli_optional_positive(value, name="--x") is expected


def test_negative_is_rejected_with_the_cli_flag_name() -> None:
    """음수는 argparse 를 통과한다 — 생성자까지 흘리면 실패 메시지가 인자명을 잃는다."""
    module = _load_dev_module()
    with pytest.raises(ValueError, match="--journal-segment-bytes"):
        module.cli_optional_positive(-1, name="--journal-segment-bytes")


def test_defaults_are_within_constructor_contracts() -> None:
    """기본값이 생성자 규약(양수 또는 None)을 만족한다 — 기본 조립이 즉시 죽지 않게."""
    module = _load_dev_module()
    for default in (64 * 1024 * 1024, 500):
        converted = module.cli_optional_positive(default, name="--x")
        assert converted is not None and converted > 0


# ── 조립 표면 대조 (2026-08-08 reviewer 지적 F1) ────────────────────────────
#
# create_app 의 배선이 정확해도 이 스크립트가 저장소를 안 넘기면 **띄울 수 있는
# 서버에서는 404 다.** 실제로 Phase 3/4 신설 API 4종이 그 상태였다 — 라이브러리를
# API 로 만든 작업이 다시 "아무도 못 쓰는 것"이 되는 자리라, 이 대조를 게이트로 둔다.


class _NullEvidenceStorage:
    """포트 계약만 만족하는 조립용 스텁 — 이 게이트는 경로 존재만 본다."""

    _blobs: dict[str, bytes] = {}  # noqa: RUF012 -- 테스트 스텁

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> Any:
        raise NotImplementedError

    def observe_object(self, object_key: str) -> Any:
        raise NotImplementedError

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        """포트가 요구하는 서버측 직접 쓰기 — 이 스텁은 메모리에만 담는다."""
        del content_type
        self._blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        """부재도 오류다(포트 계약) — 조용히 빈 바이트를 돌려주지 않는다."""
        blob = self._blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _max_assembly_kwargs(tmp_path: Path) -> dict[str, Any]:
    """모든 조건부 라우터를 장착하는 ``create_app`` 인자.

    dict 로 돌려주는 이유는 :func:`test_max_assembly_passes_every_store_parameter` 가
    **인자 이름 집합**을 ``create_app`` 시그니처와 대조하기 위해서다 — 그 대조가
    없으면 이 함수 자체가 손으로 유지되는 복제본이라, 새 store 를 추가하면서 여기를
    안 고치면 아래 경로 대조가 조용히 통과한다(F1 의 실패 양식이 그대로 재발).
    """
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    signing_key = Ed25519PrivateKey.generate()
    signing_key_id = "dev-assembly-test-key"
    # 최대 조립은 route 장착 범위를 확인하는 테스트다. 빈 registry는 명시적으로
    # fail-closed(204)이며, 임의 risk policy를 만들어 이 조립 테스트가 정책을
    # 발급하는 경로가 되지 않게 한다.
    edge_dispatch_store = EdgeDispatchStore(
        DurableJournal(tmp_path / "edge-dispatch.jsonl"),
        mission_store=mission_store,
        risk_policy_packs=RiskPolicyPackRegistry(()),
        edge_runtime_profiles=EdgeRuntimeProfileRegistry(()),
        private_key=signing_key,
        key_id=signing_key_id,
    )
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    processing_job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    checkpoint_validation_store = CheckpointValidationStore(
        DurableJournal(tmp_path / "checkpoint-validations.jsonl"),
        processing_jobs=processing_job_store,
        mission_store=mission_store,
    )
    design_surface_store = DesignSurfaceStore(
        DurableJournal(tmp_path / "design-surfaces.jsonl"), site_store=site_store
    )
    storage = _NullEvidenceStorage()
    # M4-A — 리포트 원장은 요청 원장과 스토리지를 둘 다 물고 있어야 만들어진다
    # (리포트 수신 시 차분 래스터 바이트를 직접 재해싱한다).
    work_area_store = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"),
        site_exists=lambda site_id: site_store.get(site_id) is not None,
    )
    observation_work_order_store = ObservationWorkOrderStore(
        DurableJournal(tmp_path / "observation-work-orders.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_connectivity_store = AcquisitionConnectivityStore(
        DurableJournal(tmp_path / "acquisition-connectivity.jsonl"),
        site_exists=lambda site_id, organization_id: (
            site_store.get_scoped(site_id, organization_id) is not None
        ),
    )
    acquisition_coordination_store = AcquisitionCoordinationStore(
        DurableJournal(tmp_path / "acquisition-runs.jsonl")
    )
    flight_artifact_store = FlightArtifactStore(
        DurableJournal(tmp_path / "flight-artifacts.jsonl"),
        mission_store=mission_store,
        storage=storage,
    )
    capture_quality_report_store = CaptureQualityReportStore(
        DurableJournal(tmp_path / "capture-quality-reports.jsonl"),
        mission_store=mission_store,
        work_order_store=observation_work_order_store,
        coordination_store=acquisition_coordination_store,
    )
    design_conformance_request_store = DesignConformanceRequestStore(
        DurableJournal(tmp_path / "design-conformance-requests.jsonl"),
        mission_store=mission_store,
        processing_job_store=processing_job_store,
        design_surface_store=design_surface_store,
        work_area_store=work_area_store,
    )
    design_conformance_report_store = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance.jsonl"),
        mission_store=mission_store,
        processing_job_store=processing_job_store,
        request_store=design_conformance_request_store,
        storage=storage,
    )
    # M4-E — 변화 영역 추출 요청/리포트는 RECORDED 된 설계 대비 잔량 리포트가
    # 있어야만 만들어진다(design_conformance_report_store 뒤에 조립한다).
    region_extraction_request_store = RegionExtractionRequestStore(
        DurableJournal(tmp_path / "region-extraction-requests.jsonl"),
        mission_store=mission_store,
        design_conformance_report_store=design_conformance_report_store,
    )
    coverage_report_store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"), mission_store=mission_store
    )
    return {
        "evidence_storage": storage,
        "auth_registry": AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"x").hexdigest(),
                    principal=Principal(
                        principal_id="op-1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                    ),
                )
            ]
        ),
        "edge_sync_store": EdgeSyncStore(tmp_path / "edge-sync.jsonl"),
        "edge_dispatch_store": edge_dispatch_store,
        "event_store": EventStore(DurableJournal(tmp_path / "events.jsonl")),
        "site_store": site_store,
        "mission_store": mission_store,
        "mission_sequence_store": MissionIssuanceSequenceStore(
            DurableJournal(tmp_path / "mission-sequences.jsonl")
        ),
        "coverage_report_store": coverage_report_store,
        "mission_execution_store": MissionExecutionStore(
            DurableJournal(tmp_path / "mission-execution.jsonl"), mission_store=mission_store
        ),
        "source_media_store": source_media_store,
        "design_surface_store": design_surface_store,
        "work_area_store": work_area_store,
        "observation_work_order_store": observation_work_order_store,
        "external_reconstruction_store": ExternalReconstructionStore(
            DurableJournal(tmp_path / "external-reconstruction.jsonl")
        ),
        "acquisition_connectivity_store": acquisition_connectivity_store,
        "acquisition_coordination_store": acquisition_coordination_store,
        "capture_quality_report_store": capture_quality_report_store,
        "processing_job_store": processing_job_store,
        "checkpoint_validation_store": checkpoint_validation_store,
        "defect_candidate_store": DefectCandidateStore(
            DurableJournal(tmp_path / "defects.jsonl"),
            mission_store=mission_store,
            source_media_store=source_media_store,
        ),
        "change_detection_store": ChangeDetectionStore(
            DurableJournal(tmp_path / "change-detection.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        "volume_change_store": VolumeChangeStore(
            DurableJournal(tmp_path / "volume-changes.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
        ),
        "comparison_request_store": ComparisonRequestStore(
            DurableJournal(tmp_path / "comparison-requests.jsonl"),
            mission_store=mission_store,
            processing_job_store=processing_job_store,
            checkpoint_rmse_lookup=checkpoint_validation_store.validated_rmse_for,
        ),
        "design_conformance_request_store": design_conformance_request_store,
        "design_conformance_report_store": design_conformance_report_store,
        "report_export_store": ReportExportStore(
            DurableJournal(tmp_path / "report-exports.jsonl"),
            site_store=site_store,
            design_conformance_store=design_conformance_report_store,
            coverage_report_store=coverage_report_store,
        ),
        "region_extraction_request_store": region_extraction_request_store,
        "region_extraction_report_store": RegionExtractionStore(
            DurableJournal(tmp_path / "region-extraction.jsonl"),
            mission_store=mission_store,
            request_store=region_extraction_request_store,
            design_conformance_report_store=design_conformance_report_store,
        ),
        "equipment_state_store": EquipmentStateStore(
            DurableJournal(tmp_path / "equipment-states.jsonl"), site_store=site_store
        ),
        "equipment_support_store": EquipmentSupportStore(
            DurableJournal(tmp_path / "equipment-support.jsonl")
        ),
        "mission_signing_key": signing_key,
        "mission_signing_key_id": signing_key_id,
        "flight_artifact_store": flight_artifact_store,
    }


def _max_assembly_paths(tmp_path: Path) -> set[str]:
    """모든 조건부 라우터를 장착한 앱의 /v1 경로 집합."""
    app = create_app(**_max_assembly_kwargs(tmp_path))
    return {p for p in app.openapi()["paths"] if p.startswith("/v1/")}


def test_max_assembly_passes_every_store_parameter(tmp_path: Path) -> None:
    """[자체 갱신 앵커] ``create_app`` 의 ``*_store`` 파라미터를 최대 조립이 하나도
    빠뜨리지 않는다.

    아래 경로 대조(:func:`test_dev_assembly_mounts_every_v1_surface`)의 기준집합은
    손으로 유지되는 복제본이다 — 새 store 를 추가하면서 그 복제본을 안 고치면
    ``missing`` 이 공집합이 되어 조용히 통과한다. F1(신설 API 4종이 어떤 실행 가능한
    조립에도 없었다)의 실패 양식이 **재발 방지 게이트 안에서 그대로 재발**하는
    자리다(2026-08-08 reviewer 재검증 지적 N1). 시그니처에서 직접 뽑아 대조하면
    그 자리가 닫힌다 — 새 store 파라미터를 추가하는 순간 이 테스트가 먼저 깨진다.
    """
    store_params = {
        name for name in inspect.signature(create_app).parameters if name.endswith("_store")
    }
    missing = store_params - set(_max_assembly_kwargs(tmp_path))
    assert not missing, (
        f"create_app 의 store 파라미터를 최대 조립이 넘기지 않는다: {sorted(missing)} "
        "— 이 함수를 갱신하지 않으면 dev 조립 대조가 그 표면을 아예 보지 못한다"
    )


def test_dev_assembly_mounts_every_v1_surface(tmp_path: Path) -> None:
    """dev 서버가 최대 조립의 /v1 경로를 하나도 빠뜨리지 않는다.

    빠뜨리면 그 기능은 "구현됐지만 띄운 서버에서는 404" 다 — 계약 테스트가 전부
    green 이어도 아무도 못 쓴다.
    """
    module = _load_dev_module()
    dev = module.build_dev_app(
        tmp_path / "dev",
        segment_bytes=None,
        edge_sync_snapshot_every=None,
        s3_endpoint="http://127.0.0.1:9000",
        s3_bucket="dev-evidence",
    )
    try:
        dev_paths = {p for p in dev.app.openapi()["paths"] if p.startswith("/v1/")}
        assert isinstance(dev.app.state.capability_authority_store, CapabilityAuthorityStore)
    finally:
        dev.close()
    missing = _max_assembly_paths(tmp_path / "max") - dev_paths
    assert not missing, (
        f"dev 조립(scripts/run_core_dev.py)이 장착하지 않는 /v1 경로: {sorted(missing)} "
        "— create_app 배선만으로는 서버에서 도달할 수 없다"
    )


def test_dev_assembly_closes_every_journal_it_opened(tmp_path: Path) -> None:
    """열어둔 원장을 전부 닫는다 — 하나라도 새면 재기동이 flock 으로 막힌다."""
    module = _load_dev_module()
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir(parents=True)
    first = module.build_dev_app(dev_dir, segment_bytes=None, edge_sync_snapshot_every=None)
    first.close()
    # 같은 디렉터리로 두 번째 조립이 되면 단일 writer 잠금이 전부 풀린 것이다.
    second = module.build_dev_app(dev_dir, segment_bytes=None, edge_sync_snapshot_every=None)
    second.close()


def test_external_reconstruction_requires_complete_supported_assembly_and_is_absent_without_storage(
    tmp_path: Path,
) -> None:
    """Mounting byte ingress without every scope/auth/storage dependency creates a false surface."""
    kwargs = _max_assembly_kwargs(tmp_path / "max")
    external_base = (
        "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    )
    minimal = {
        name: kwargs[name]
        for name in (
            "auth_registry",
            "site_store",
            "observation_work_order_store",
            "evidence_storage",
            "external_reconstruction_store",
        )
    }
    for absent in (
        "auth_registry",
        "site_store",
        "observation_work_order_store",
        "evidence_storage",
    ):
        invalid = dict(minimal)
        invalid[absent] = None
        with pytest.raises(ValueError):
            create_app(**invalid)

    class UnsupportedStorage:
        def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
            del object_key, content_type, ttl
            raise NotImplementedError

        def presigned_get(self, object_key: str, *, ttl: Any) -> str:
            del object_key, ttl
            raise NotImplementedError

        def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
            del object_key, data, content_type

        def get_bytes(self, object_key: str) -> bytes:
            del object_key
            raise NotImplementedError

        def delete(self, object_key: str) -> None:
            del object_key

    invalid = dict(minimal)
    invalid["evidence_storage"] = UnsupportedStorage()
    with pytest.raises(ValueError, match="digest-bound PUT"):
        create_app(**invalid)
    without_store = dict(minimal)
    without_store["external_reconstruction_store"] = None
    without_store["evidence_storage"] = None
    assert external_base not in create_app(**without_store).openapi()["paths"]

    module = _load_dev_module()
    dev = module.build_dev_app(
        tmp_path / "storage-less-dev",
        segment_bytes=None,
        edge_sync_snapshot_every=None,
    )
    try:
        assert external_base not in dev.app.openapi()["paths"]
    finally:
        dev.close()
