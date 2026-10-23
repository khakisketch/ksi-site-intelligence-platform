"""Platform Core 프로덕션 조립 지점 — 외부 등록·조회·운영 전용 명시적 프로파일.

유일한 실행 가능 **플랫폼** 운영 배선이다. 레거시 ``build_production_app`` 과
같은 환경변수-전용 fail-closed 규약을 따르되, Mission 서명키 디렉터리
(``KSI_CORE_SIGNING_KEYS_DIR``)와 장비 증명 파일
(``KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE``)을 요구하지도 읽지도 않는다 —
이 프로파일은 Mission/비행/Edge 저널을 열지 않으므로 그 신뢰 출발점이
필요 없다.

필수 입력은 기존 데이터 디렉터리, S3 endpoint/bucket, principal
digest/OIDC 설정뿐이다. 선택 입력은 기존과 동일한 형식 그대로다 — 서명된
Analysis 3종(런타임 설정·활성화·검증키)과 외부 권한 쌍(워크플로 설정·권한
제공자 설정). 새 설정 형식, 기본 신뢰, dev 토큰, 서명 부트스트랩은 없다.

검증은 무거운 부수효과(S3 client 생성, journal 파일 열기) **전에** 전부
끝낸다. 조립 실패 시 이미 열린 저널은 전부 닫는다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    PrincipalKind,
)
from ksi_core.composition.platform_assembly import assemble_platform_app
from ksi_core.composition.runtime_config import (
    _JOURNAL_SEGMENT_BYTES_DEFAULT,
    _analysis_activation_paths_env,
    _audit_working_set_path_env,
    _expose_docs_env,
    _external_authority_paths_env,
    _human_auth_config_env,
    _optional_positive_env,
    _parse_principal_tokens,
    _require_dir,
    _require_env,
    _site_bootstrap_max_sites_per_org_env,
    _spatial_data_config_path_env,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.oidc_subject_registry import load_oidc_subject_registry
from ksi_core.observability import configure_structured_logging
from ksi_core.oidc import OidcJwtVerifier

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_platform_production_app() -> FastAPI:
    """환경변수만으로 플랫폼 Core 앱을 조립한다 — 실패는 전부 fail-closed.

    uvicorn 팩토리 진입점으로 쓰인다:
    ``uvicorn ksi_core.composition.platform_production:build_platform_production_app --factory``.
    """
    # 검증보다도 먼저다 — 검증 실패 메시지 자체도 구조화 로그로 남아야
    # 배포 사고 조사에서 "그때 무슨 환경변수가 문제였는지"가 로그 수집기에서
    # 검색 가능하다. correlation id 는 아직 없다(요청 밖이므로 "-"로 찍힌다).
    configure_structured_logging(
        level=os.environ.get("KSI_CORE_LOG_LEVEL", "INFO"), json_format=True
    )
    external_authority_paths = _external_authority_paths_env()

    # ── 1단계: 검증(가벼운 것부터) — 무거운 부수효과(S3 client·journal open) 이전에
    # 전부 끝낸다. 잘못된 배포는 어느 환경변수가 문제인지 즉시 알아야 한다.
    data_dir = _require_dir("KSI_CORE_DATA_DIR")
    s3_endpoint = _require_env("KSI_CORE_S3_ENDPOINT")
    s3_public_endpoint = os.environ.get("KSI_CORE_S3_PUBLIC_ENDPOINT", s3_endpoint)
    s3_bucket = _require_env("KSI_CORE_S3_BUCKET")
    principal_tokens_raw = _require_env("KSI_CORE_PRINCIPAL_TOKENS_JSON")

    journal_segment_bytes = _optional_positive_env(
        "KSI_CORE_JOURNAL_SEGMENT_BYTES", default=_JOURNAL_SEGMENT_BYTES_DEFAULT
    )
    site_bootstrap_max_sites_per_org = _site_bootstrap_max_sites_per_org_env()
    expose_docs = _expose_docs_env()
    human_auth_mode, oidc_config = _human_auth_config_env()
    oidc_subject_registry = None
    if oidc_config is not None:
        if oidc_config.subject_registry_file is None:
            raise RuntimeError("production OIDC requires a protected subject registry file")
        try:
            oidc_subject_registry = load_oidc_subject_registry(
                oidc_config.subject_registry_file,
                expected_issuer=oidc_config.issuer,
            )
        except ValueError as exc:
            raise RuntimeError("protected OIDC subject registry is invalid") from exc

    principal_records = _parse_principal_tokens(principal_tokens_raw)
    if (
        human_auth_mode in (HumanAuthMode.OIDC, HumanAuthMode.DUAL)
        and oidc_subject_registry is not None
    ):
        opaque_principal_ids = {record.principal.principal_id for record in principal_records}
        if oidc_subject_registry.principal_ids & opaque_principal_ids:
            raise RuntimeError("OIDC subject principalId collides with opaque principalId")
    spatial_config_path = _spatial_data_config_path_env()
    audit_working_set_path = _audit_working_set_path_env()
    spatial_config = None
    spatial_rights = None
    audit_working_set = None
    if audit_working_set_path is not None:
        from ksi_core.domains.external.delivery.audit_working_set import (
            load_spatial_data_audit_working_set,
        )

        try:
            audit_working_set = load_spatial_data_audit_working_set(audit_working_set_path)
        except ValueError as exc:
            raise RuntimeError("protected audit working-set configuration is invalid") from exc
    if spatial_config_path is not None:
        from ksi_core.composition.spatial_data_production import (
            SpatialDataCoreConfigError,
            load_spatial_data_core_config,
            load_spatial_data_rights_file,
        )

        try:
            spatial_config = load_spatial_data_core_config(
                spatial_config_path, principal_records=principal_records
            )
            spatial_rights = load_spatial_data_rights_file(
                spatial_config,
                principal_records=principal_records,
                oidc_subject_registry=oidc_subject_registry,
            )
        except SpatialDataCoreConfigError as exc:
            raise RuntimeError("protected spatial data configuration is invalid") from exc
    external_analysis_local_graph = None
    analysis_activation = None
    analysis_paths = _analysis_activation_paths_env()
    if analysis_paths is not None:
        from ksi_core.composition.local_analysis_runtime_config import (
            load_local_analysis_runtime_config,
        )
        from ksi_core.domains.external.quantity.analysis_activation_authority import (
            load_analysis_activation,
        )

        runtime_path, activation_path, verification_keys_path = analysis_paths
        try:
            external_analysis_local_graph = load_local_analysis_runtime_config(runtime_path)
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError("protected Analysis runtime configuration is invalid") from exc
        analysis_workers = {
            record.principal
            for record in principal_records
            if record.principal.kind is PrincipalKind.ANALYSIS_WORKER
        }
        if len(analysis_workers) != 1:
            raise RuntimeError(
                "Analysis activation requires exactly one registered ANALYSIS_WORKER identity"
            )
        worker_principal = next(iter(analysis_workers))
        try:
            analysis_activation = load_analysis_activation(
                activation_path,
                verification_keys_path,
                organization_id=worker_principal.organization_id,
                policy=external_analysis_local_graph.policy,
                runtime=external_analysis_local_graph.runtime,
                resource_envelope=external_analysis_local_graph.resource_envelope,
                worker_principal=worker_principal,
                now=datetime.now(UTC),
                allow_out_of_window=True,
            )
        except ValueError as exc:
            raise RuntimeError("signed Analysis activation is invalid") from exc

    external_authority_provider = None
    external_result_workflow = None
    if external_authority_paths is not None:
        from ksi_core.external_authority_provider import load_external_authority_provider
        from ksi_core.external_relative_volume_s3_capabilities import (
            ExternalRelativeVolumeS3InputCapabilityIssuer,
        )
        from ksi_core.external_result_workflow_config import load_external_result_workflow_config

        workflow_path, provider_path = external_authority_paths
        external_authority_provider = load_external_authority_provider(
            provider_path, clock=lambda: datetime.now(UTC), allow_out_of_window=True
        )
        external_result_workflow = load_external_result_workflow_config(
            workflow_path,
            participants=external_authority_provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
            allow_historical_catalog_binding=True,
        )

    # ── 2단계: 무거운 조립 — 여기부터는 검증을 통과한 입력만 다룬다.

    # AWS 자격증명은 boto3 기본 체인(환경변수/IAM role)에 맡긴다 — 이 함수는
    # endpoint_url·bucket 만 넘긴다(evidence_s3.py 어댑터가 이미 이 관습이다).
    from ksi_core.evidence_s3 import S3EvidenceStorage  # noqa: PLC0415 -- 지연 import(boto3)

    evidence_storage = S3EvidenceStorage(
        bucket=s3_bucket,
        endpoint_url=s3_endpoint,
        public_endpoint_url=s3_public_endpoint,
    )

    auth_registry = AuthRegistry(principal_records)
    oidc_verifier = (
        OidcJwtVerifier(oidc_config, subject_registry=oidc_subject_registry)
        if oidc_config is not None and oidc_subject_registry is not None
        else None
    )
    spatial_data = None
    if spatial_config is not None and spatial_rights is not None:
        from ksi_core.composition.spatial_data_production import (
            build_spatial_data_production,
        )

        spatial_data = build_spatial_data_production(
            spatial_config,
            spatial_rights,
            auth_registry=auth_registry,
            oidc_subject_registry=oidc_subject_registry,
            bucket=s3_bucket,
            endpoint_url=s3_endpoint,
            audit_working_set=audit_working_set,
        )

    opened: list[Any] = []

    def _journal(
        name: str,
        *,
        retain_records: bool = True,
        max_line_bytes: int | None = None,
        max_recover_bytes: int | None = None,
        recover_deadline: float | None = None,
        recover_cpu_budget: float | None = None,
        recover_cpu_start: float | None = None,
        tolerate_torn_tail: bool = True,
        line_validator: Callable[[bytes], None] | None = None,
    ) -> DurableJournal:
        journal = DurableJournal(
            data_dir / name,
            max_segment_bytes=journal_segment_bytes,
            retain_records=retain_records,
            max_line_bytes=max_line_bytes,
            max_recover_bytes=max_recover_bytes,
            recover_deadline=recover_deadline,
            recover_cpu_budget=recover_cpu_budget,
            recover_cpu_start=recover_cpu_start,
            tolerate_torn_tail=tolerate_torn_tail,
            line_validator=line_validator,
        )
        opened.append(journal)
        return journal

    try:
        if external_authority_provider is not None:
            external_authority_provider.bind_receipt_journal(
                _journal("external-authority-provider-receipts.jsonl")
            )
        app = assemble_platform_app(
            data_dir,
            journal=_journal,
            opened=opened,
            auth_registry=auth_registry,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
            evidence_storage=evidence_storage,
            external_result_workflow=external_result_workflow,
            external_analysis_local_graph=external_analysis_local_graph,
            analysis_activation=analysis_activation,
            spatial_data=spatial_data,
            site_bootstrap_max_sites_per_org=site_bootstrap_max_sites_per_org,
            expose_docs=expose_docs,
        )
        if external_authority_provider is not None:
            from ksi_core.external_authority_operations import mount_external_authority_operations

            external_authority_provider.attach_app(app)
            mount_external_authority_operations(app, external_authority_provider)
            app.state.external_authority_provider = external_authority_provider
        if spatial_data is not None and spatial_config is not None:
            from ksi_core.composition.spatial_data_production import (
                SpatialDataCleanupDisabledError,
                start_spatial_data_cleanup,
            )

            wiring = getattr(app.state, "spatial_data", None)
            if wiring is None:
                raise RuntimeError("spatial data wiring was not mounted by the platform app")
            try:
                cleanup = start_spatial_data_cleanup(
                    wiring, interval_seconds=float(spatial_config.cleanup_interval_seconds)
                )
            except SpatialDataCleanupDisabledError as exc:
                import logging as _logging  # noqa: PLC0415 -- boot-path loud refusal

                _logging.getLogger("ksi_core.composition.platform_production").warning(
                    "spatial data cleanup not started: %s", exc
                )
                app.state.spatial_data_cleanup = None
            else:
                app.state.spatial_data_cleanup = cleanup
                app.router.add_event_handler("shutdown", cleanup.stop)
        return app
    except BaseException:
        # 레거시 프로덕션 조립과 같은 이유 — 안 닫으면 재시도가 flock 에 막혀
        # 진짜 실패 원인이 "다른 프로세스가 journal 을 소유 중"으로 덮인다.
        for journal in opened:
            journal.close()
        raise


__all__ = ["build_platform_production_app"]
