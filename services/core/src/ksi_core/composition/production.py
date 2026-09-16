"""KSI Core 프로덕션 조립 지점 — 유일한 실행 가능한 운영 배선(ADR-KSI-008).

``scripts/run_core_dev.py`` 는 그 스크립트 자체가 명시하듯 프로덕션 조립이
아니다 — 고정 dev 토큰 5개를 하드코딩해 ``AuthRegistry`` 를 구성한다. 이
모듈은 dev 스크립트를 전혀 import 하지 않는다(``run_core_dev`` 에 대한 어떤
의존도 없다) — 이 파일만 읽어서는 dev 토큰의 존재조차 알 수 없어야, "운영
빌드가 실수로 dev 자격증명을 끌고 들어온다"는 사고 클래스 자체가 성립하지
않는다.

## 전부 환경변수로만 조립한다 — fail-closed

필수 환경변수가 하나라도 없거나 형식이 틀리면 :class:`RuntimeError` 로 즉시
거부한다. 무엇도 조용히 기본값·빈 값으로 대체하지 않는다 — 조용한 기본값은
"인증 없이 뜬 프로덕션 서버"라는, 이 작업이 막으려는 바로 그 사고다. 검증은
무거운 부수효과(S3 client 생성, journal 파일 열기 등)를 만들기 **전에** 전부
끝낸다 — 잘못된 배포가 부분적으로 조립되다 알 수 없는 지점에서 죽는 대신,
어느 환경변수가 왜 문제인지 첫 실패에서 명확히 말한다.

## 서명키는 여기서 부트스트랩하지 않는다

``scripts/run_core_dev.py`` 의 ``_bootstrap_key_set`` 은 dev 편의로 키가 없으면
새로 만든다. 이 모듈은 :func:`ksi_core.signing_keys.load_signing_keys` 를 직접
호출한다 — **이미 있는 키만 로드**하고 새로 만들지 않는다. 컨테이너는
재생성될 수 있는 존재다(오케스트레이터 재스케줄·롤링 배포). 재생성마다 새
서명키가 생기면, 그 이전 키로 서명된 Mission Contract 는 재검증 시 새 키
registry 에 없는 keyId 를 참조하게 되어 전부 검증 실패한다 — 이미 현장에
발급된 계약이 서버 재시작 한 번으로 무효가 되는 것은 이 제품의 근본 전제
(server loss must not invalidate a locally valid Mission Contract)를 정면으로
어긴다. 키 파일은 컨테이너 밖(영속 볼륨)에 살아야 하고, 회전은 운영 절차
(``docs/security/SIGNING_KEY_LIFECYCLE.md``)로 명시적으로 한다.

## evidence storage 는 선택이 아니라 필수다

dev 조립은 ``--s3-endpoint``/``--s3-bucket`` 없이도 뜬다(증거·3D 파이프라인
표면이 그냥 장착되지 않을 뿐) — 로컬 UI 개발에는 그걸로 충분하다. 프로덕션은
그 타협을 허용하지 않는다: evidence storage 없는 운영 배포는 증거·3D 파이프라인
전체가 조용히 404 인 서버이고, 그 상태를 "정상 기동"으로 보고하면 안 된다.
그래서 ``KSI_CORE_S3_ENDPOINT``/``KSI_CORE_S3_BUCKET`` 을 둘 다 필수로 둔다.

## 원문 토큰은 이 프로세스 어디에도 없다

``KSI_CORE_PRINCIPAL_TOKENS_JSON`` 은 토큰 원문이 아니라 sha256 **digest** 만
싣는다(``AuthRegistry`` 자체가 이미 그 규약이다, ``auth.py`` 모듈 docstring
참조). 배포자가 토큰을 만들고 digest 를 미리 계산해 이 JSON 에 실으므로,
프로세스 메모리·로그·환경변수 어디에도 원문 토큰이 존재하지 않는다 — dev
스크립트처럼 콘솔에 토큰을 찍어 보여주는 경로도 여기 없다(그 경로 자체가
원문을 프로세스가 알고 있어야만 가능하다).

각 항목은 선택 필드 ``status``("ACTIVE"/"REVOKED", 기본 ACTIVE)와
``notAfter``(ISO 8601 tz-aware, 기본 없음=만료 없음)를 가질 수 있다 — 회전
중에는 같은 ``principalId`` 로 이전 digest(``notAfter`` 로 유예기간 종료
시각)와 새 digest(``notAfter`` 없음) 두 항목을 함께 배포한다(``docs/security/
AUTH_TOKEN_ROTATION.md``).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_core.app_assembly import assemble_app
from ksi_core.auth import (
    AuthRegistry,
)
from ksi_core.composition.production_config import (
    _EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT,
    _JOURNAL_SEGMENT_BYTES_DEFAULT,
    _acquisition_coordination_env,
    _acquisition_issue_gate_env,
    _checkpoint_validation_registration_env,
    _copilot_runtime_config_env,
    _expose_docs_env,
    _external_authority_paths_env,
    _human_auth_config_env,
    _landxml_ingress_env,
    _mission_contract_writer_config,
    _optional_capability_freshness_policies,
    _optional_edge_runtime_profiles,
    _optional_positive_env,
    _optional_risk_policy_packs,
    _optional_runtime_route_configurations,
    _parse_principal_tokens,
    _processing_profile_issuance_env,
    _require_dir,
    _require_env,
)
from ksi_core.device_attestation import load_device_attestation_registry
from ksi_core.durable_journal import DurableJournal
from ksi_core.observability import configure_structured_logging
from ksi_core.oidc import OidcJwtVerifier
from ksi_core.signing_keys import load_signing_keys

if TYPE_CHECKING:
    from fastapi import FastAPI



def build_production_app() -> FastAPI:
    """환경변수만으로 프로덕션 Core 앱을 조립한다 — 실패는 전부 fail-closed.

    uvicorn 팩토리 진입점(``--factory``)으로 쓰인다:
    ``uvicorn ksi_core.production:build_production_app --factory``.
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
    signing_keys_dir = _require_dir("KSI_CORE_SIGNING_KEYS_DIR")
    s3_endpoint = _require_env("KSI_CORE_S3_ENDPOINT")
    s3_public_endpoint = os.environ.get("KSI_CORE_S3_PUBLIC_ENDPOINT", s3_endpoint)
    s3_bucket = _require_env("KSI_CORE_S3_BUCKET")
    principal_tokens_raw = _require_env("KSI_CORE_PRINCIPAL_TOKENS_JSON")
    device_attestation_keys_file = Path(_require_env("KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE"))
    if not device_attestation_keys_file.is_file():
        raise RuntimeError(
            "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE은 존재하는 파일이어야 한다"
        )

    journal_segment_bytes = _optional_positive_env(
        "KSI_CORE_JOURNAL_SEGMENT_BYTES", default=_JOURNAL_SEGMENT_BYTES_DEFAULT
    )
    edge_sync_snapshot_every = _optional_positive_env(
        "KSI_CORE_EDGE_SYNC_SNAPSHOT_EVERY", default=_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT
    )
    expose_docs = _expose_docs_env()
    acquisition_coordination_enabled = _acquisition_coordination_env()
    acquisition_issue_gate_enabled = _acquisition_issue_gate_env()
    processing_profile_issuance_enabled = _processing_profile_issuance_env()
    landxml_ingress_enabled = _landxml_ingress_env()
    checkpoint_validation_registration_enabled = _checkpoint_validation_registration_env()
    copilot_runtime_config = _copilot_runtime_config_env()
    human_auth_mode, oidc_config = _human_auth_config_env()
    mission_contract_writer_version, mission_contract_issuer_id = (
        _mission_contract_writer_config()
    )

    principal_records = _parse_principal_tokens(principal_tokens_raw)
    risk_policy_packs = _optional_risk_policy_packs()
    edge_runtime_profiles = _optional_edge_runtime_profiles()
    capability_freshness_policies = _optional_capability_freshness_policies()
    runtime_route_configurations = _optional_runtime_route_configurations(
        freshness_policies=capability_freshness_policies
    )
    device_attestation_registry = load_device_attestation_registry(
        device_attestation_keys_file
    )

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
            provider_path, clock=lambda: datetime.now(UTC)
        )
        external_result_workflow = load_external_result_workflow_config(
            workflow_path,
            participants=external_authority_provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )

    # ── 2단계: 무거운 조립 — 여기부터는 검증을 통과한 입력만 다룬다.

    # 서명키는 **로드만** 한다(부트스트랩 없음) — 모듈 docstring 참조.
    key_set = load_signing_keys(signing_keys_dir)

    # AWS 자격증명은 boto3 기본 체인(환경변수/IAM role)에 맡긴다 — 이 함수는
    # endpoint_url·bucket 만 넘긴다(evidence_s3.py 어댑터가 이미 이 관습이다).
    from ksi_core.evidence_s3 import S3EvidenceStorage  # noqa: PLC0415 -- 지연 import(boto3)

    evidence_storage = S3EvidenceStorage(
        bucket=s3_bucket,
        endpoint_url=s3_endpoint,
        public_endpoint_url=s3_public_endpoint,
    )

    auth_registry = AuthRegistry(principal_records)
    oidc_verifier = OidcJwtVerifier(oidc_config) if oidc_config is not None else None

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name, max_segment_bytes=journal_segment_bytes)
        opened.append(journal)
        return journal

    try:
        if external_authority_provider is not None:
            external_authority_provider.bind_receipt_journal(
                _journal("external-authority-provider-receipts.jsonl")
            )
        app = assemble_app(
            data_dir,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=edge_sync_snapshot_every,
            auth_registry=auth_registry,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
            evidence_storage=evidence_storage,
            mission_signing_key=key_set.active_private_key,
            mission_signing_key_id=key_set.active_key_id,
            mission_contract_writer_version=mission_contract_writer_version,
            mission_contract_issuer_id=mission_contract_issuer_id,
            risk_policy_packs=risk_policy_packs,
            edge_runtime_profiles=edge_runtime_profiles,
            device_attestation_registry=device_attestation_registry,
            acquisition_coordination_enabled=acquisition_coordination_enabled,
            acquisition_issue_gate_enabled=acquisition_issue_gate_enabled,
            processing_profile_issuance_enabled=processing_profile_issuance_enabled,
            landxml_ingress_enabled=landxml_ingress_enabled,
            checkpoint_validation_registration_enabled=checkpoint_validation_registration_enabled,
            capability_freshness_policies=capability_freshness_policies,
            runtime_route_configurations=runtime_route_configurations,
            copilot_runtime_config=copilot_runtime_config,
            external_result_workflow=external_result_workflow,
            expose_docs=expose_docs,
        )
        if external_authority_provider is not None:
            from ksi_core.external_authority_operations import mount_external_authority_operations

            external_authority_provider.attach_app(app)
            mount_external_authority_operations(app, external_authority_provider)
            app.state.external_authority_provider = external_authority_provider
        return app
    except BaseException:
        # dev 조립(build_dev_app)과 같은 이유 — 안 닫으면 재시도가 flock 에 막혀
        # 진짜 실패 원인이 "다른 프로세스가 journal 을 소유 중"으로 덮인다.
        for journal in opened:
            journal.close()
        raise


__all__ = ["build_production_app"]
