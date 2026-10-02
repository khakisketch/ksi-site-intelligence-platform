#!/usr/bin/env python3
"""KSI Core 로컬 개발 서버 — apps/dashboard 연동용.

프로덕션 조립이 아니다. durable 저장소를 로컬 디스크(--data-dir)에 열고, 고정
장비·워커 opaque 자격을 구성해 uvicorn으로 기동한다. 사람 인증은 기본 OPAQUE
legacy 경로 또는 명시한 OIDC issuer를 쓸 수 있다. 일반 Dashboard 개발은
``npm run dev``가 OIDC 모드를 선택한다. 데이터는 재기동해도 보존된다(--reset으로
초기화). 서명키는 최초 기동 시 생성해 data-dir에 저장하고 이후 재사용한다.

Usage:
    uv run python scripts/run_core_dev.py [--host 127.0.0.1] [--port 8000] [--reset]
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app_assembly import assemble_app, cli_optional_positive  # noqa: F401 -- re-export
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_result_workflow_assembly import ExternalResultWorkflowAssemblyConfig
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.observability import configure_structured_logging
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_core.signing_keys import SigningKeySet, load_signing_keys

_DEV_TOKENS: dict[Role, str] = {
    Role.ADMIN: "dev-admin-token",
    Role.FIELD_OPERATOR: "dev-field-operator-token",
    Role.VIEWER: "dev-viewer-token",
}
_DEV_EDGE_TOKEN = "dev-edge-device-token"  # noqa: S105 — 로컬 dev 전용 고정값
_DEV_EDGE_DEVICE_ID = "edge-dev-001"
_DEV_GATEWAY_TOKEN = "dev-gateway-device-token"  # noqa: S105 — 로컬 dev 전용 고정값
_DEV_GATEWAY_DEVICE_ID = "gateway-dev-001"
# 처리 워커 토큰이 따로 있는 이유 — 사람 토큰으로는 처리 작업의 RUNNING·
# SUCCEEDED·FAILED 를 보고할 수 없다(PROCESSING_WORK 는 어느 Role 에도 없다).
# 이 토큰 없이는 재구성 경로를 dev 에서 끝까지 돌려볼 수 없다.
_DEV_WORKER_TOKEN = "dev-processing-worker-token"  # noqa: S105


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _dev_oidc_subject_registry(issuer: str) -> OidcSubjectRegistry:
    """KSI-owned mappings for the local-only issuer; production never imports this."""
    accounts = (
        ("local-admin", "org-local-pilot", Role.ADMIN.value),
        ("local-field-operator", "org-local-pilot", Role.FIELD_OPERATOR.value),
        ("local-viewer", "org-local-pilot", Role.VIEWER.value),
        ("local-empty-org-admin", "org-local-empty", Role.ADMIN.value),
    )
    return OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v1",
            "subjects": [
                {
                    "issuer": issuer,
                    "subject": subject,
                    "principalId": subject,
                    "organizationId": organization_id,
                    "role": role,
                    "status": "ACTIVE",
                    "allowedSiteIds": [],
                    "allowedWorkAreaIds": [],
                }
                for subject, organization_id, role in accounts
            ],
        },
        expected_issuer=issuer,
    )


def _auth_registry() -> AuthRegistry:
    records = [
        PrincipalTokenRecord(
            token_sha256=_digest(token),
            principal=Principal(
                principal_id=f"dev-{role.value.lower()}",
                kind=PrincipalKind.OPERATOR,
                role=role,
                device_id=None,
            ),
        )
        for role, token in _DEV_TOKENS.items()
    ]
    records.append(
        PrincipalTokenRecord(
            token_sha256=_digest(_DEV_GATEWAY_TOKEN),
            principal=Principal(
                principal_id="dev-gateway-principal",
                kind=PrincipalKind.GATEWAY_DEVICE,
                role=None,
                device_id=_DEV_GATEWAY_DEVICE_ID,
            ),
        )
    )
    records.append(
        PrincipalTokenRecord(
            token_sha256=_digest(_DEV_EDGE_TOKEN),
            principal=Principal(
                principal_id="dev-edge-principal",
                kind=PrincipalKind.EDGE_DEVICE,
                role=None,
                device_id=_DEV_EDGE_DEVICE_ID,
            ),
        )
    )
    records.append(
        PrincipalTokenRecord(
            token_sha256=_digest(_DEV_WORKER_TOKEN),
            principal=Principal(
                principal_id="dev-processing-worker",
                kind=PrincipalKind.PROCESSING_WORKER,
                role=None,
                device_id=None,
            ),
        )
    )
    return AuthRegistry(records)


def _bootstrap_key_set(signing_dir: Path) -> SigningKeySet:
    """dev 키 세트를 준비한다 — 없으면 만들고, 있으면 **검증해서** 읽는다.

    부트스트랩만 dev 편의이고 로드는 운영과 같은 경로(:func:`load_signing_keys`)를
    탄다 — 개인키 권한·공개키 불일치·활성 키 REVOKED 를 여기서도 똑같이 거부한다.
    dev 조립이 느슨한 경로를 따로 가지면 그 검사들이 운영에서 처음 실행된다.

    회전은 이 함수가 하지 않는다(docs/security/SIGNING_KEY_LIFECYCLE.md 절차) —
    keys.json 이 이미 있으면 손대지 않는다.
    """
    manifest = signing_dir / "keys.json"
    if not manifest.exists():
        signing_dir.mkdir(parents=True, exist_ok=True)
        key_id = "core-dev-key-1"
        key = Ed25519PrivateKey.generate()
        private_path = signing_dir / f"{key_id}.private.pem"
        private_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        # 0600 — load_signing_keys 가 이 권한을 강제한다(운영과 같은 규칙).
        private_path.chmod(0o600)
        (signing_dir / f"{key_id}.public.pem").write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        manifest.write_text(
            json.dumps({"active": key_id, "keys": [{"keyId": key_id, "status": "ACTIVE"}]}),
            encoding="utf-8",
        )
    return load_signing_keys(signing_dir)


@dataclass(frozen=True, slots=True)
class DevAssembly:
    """조립된 앱 + 종료 시 닫아야 할 원장들.

    ``main`` 만 쓰던 조립을 함수로 뽑은 이유: 이 스크립트가 저장소의 **유일한 실행
    가능한 조립 지점**인데, 여기 무엇이 장착되는지를 검증하는 테스트가 없었다.
    실제로 2026-08-08 reviewer 지적 F1 이 그 사각지대를 짚었다 — Phase 3/4 신설 API
    4종이 ``create_app`` 배선은 정확한데 이 스크립트가 저장소를 넘기지 않아, 띄울 수
    있는 서버에서는 전부 404 였다. 라이브러리를 API 로 만든 작업이 다시 "아무도 못
    쓰는 것"이 되는 자리라, 조립을 테스트 가능한 표면으로 만든다.
    """

    app: Any
    journals: tuple[Any, ...]

    def close(self) -> None:
        for journal in self.journals:
            journal.close()


def build_dev_app(
    data_dir: Path,
    *,
    segment_bytes: int | None,
    edge_sync_snapshot_every: int | None,
    s3_endpoint: str | None = None,
    s3_bucket: str | None = None,
    human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE,
    oidc_verifier: OidcJwtVerifier | None = None,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None,
    external_analysis_local_graph: Any | None = None,
    external_authority_provider: Any | None = None,
) -> DevAssembly:
    """dev 조립 — 디렉터리는 호출자가 이미 만들어 뒀다고 가정한다.

    조립 도중 실패하면 **이미 연 원장을 전부 닫고** 예외를 올린다. 안 닫으면 같은
    프로세스에서 같은 data-dir 로 재시도할 때 flock 에 막혀, 진짜 실패 원인이
    "다른 프로세스가 journal 을 소유 중"으로 덮인다(reviewer 재검증 지적 N5 —
    ``DurableJournal.__init__`` 이 정확히 이 이유로 자기 fd 를 닫는 관습과 대칭).
    """
    _validate_dev_opt_in_graph(
        s3_endpoint=s3_endpoint,
        s3_bucket=s3_bucket,
        external_result_workflow=external_result_workflow,
        external_analysis_local_graph=external_analysis_local_graph,
        external_authority_provider=external_authority_provider,
    )
    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name, max_segment_bytes=segment_bytes)
        opened.append(journal)
        return journal

    try:
        return _build_dev_app_locked(
            data_dir,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=edge_sync_snapshot_every,
            s3_endpoint=s3_endpoint,
            s3_bucket=s3_bucket,
            human_auth_mode=human_auth_mode,
            oidc_verifier=oidc_verifier,
            external_result_workflow=external_result_workflow,
            external_analysis_local_graph=external_analysis_local_graph,
            external_authority_provider=external_authority_provider,
        )
    except BaseException:
        for journal in opened:
            journal.close()
        raise


def _build_dev_app_locked(
    data_dir: Path,
    *,
    journal: Any,
    opened: list[Any],
    edge_sync_snapshot_every: int | None,
    s3_endpoint: str | None,
    s3_bucket: str | None,
    human_auth_mode: HumanAuthMode,
    oidc_verifier: OidcJwtVerifier | None,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None,
    external_analysis_local_graph: Any | None,
    external_authority_provider: Any | None,
) -> DevAssembly:
    """실제 조립 — 열린 원장은 ``opened`` 에 누적돼 실패 시 호출자가 닫는다.

    store 조립 본문은 ``ksi_core.app_assembly.assemble_app`` 으로 옮겼다
    (dev·production 두 조립 지점의 공용부, 모듈 docstring 참조). 여기 남는 것은
    dev 만의 관심사(키 부트스트랩, CLI 의 --s3-* 조건부 evidence storage)뿐이다.
    """
    _validate_dev_opt_in_graph(
        s3_endpoint=s3_endpoint,
        s3_bucket=s3_bucket,
        external_result_workflow=external_result_workflow,
        external_analysis_local_graph=external_analysis_local_graph,
        external_authority_provider=external_authority_provider,
    )
    key_set = _bootstrap_key_set(data_dir / "signing")

    evidence_storage = None
    if s3_endpoint is not None and s3_bucket is not None:
        # 둘 다 있을 때만 만든다 — CLI 는 이미 "함께 주어야 한다"를 강제하지만,
        # 이 함수는 CLI 밖(테스트·다른 조립)에서도 불리므로 여기서 다시 본다.
        from ksi_core.evidence_s3 import S3EvidenceStorage

        evidence_storage = S3EvidenceStorage(bucket=s3_bucket, endpoint_url=s3_endpoint)

    if external_authority_provider is not None:
        external_authority_provider.bind_receipt_journal(
            journal("external-authority-provider-receipts.jsonl")
        )

    app = assemble_app(
        data_dir,
        journal=journal,
        opened=opened,
        edge_sync_snapshot_every=edge_sync_snapshot_every,
        auth_registry=_auth_registry(),
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        evidence_storage=evidence_storage,
        mission_signing_key=key_set.active_private_key,
        mission_signing_key_id=key_set.active_key_id,
        external_result_workflow=external_result_workflow,
        external_analysis_local_graph=external_analysis_local_graph,
    )
    if external_authority_provider is not None:
        from ksi_core.external_authority_operations import mount_external_authority_operations

        external_authority_provider.attach_app(app)
        mount_external_authority_operations(app, external_authority_provider)
        app.state.external_authority_provider = external_authority_provider

    # 열린 순서 그대로 닫는다 — 목록을 손으로 유지하면 새 원장을 추가하면서
    # 빠뜨리기 쉽고, 그 누락은 "재기동이 flock 으로 막힌다"로만 드러난다.
    return DevAssembly(app=app, journals=tuple(opened))


def _validate_dev_opt_in_graph(
    *,
    s3_endpoint: str | None,
    s3_bucket: str | None,
    external_result_workflow: ExternalResultWorkflowAssemblyConfig | None,
    external_analysis_local_graph: Any | None,
    external_authority_provider: Any | None,
) -> None:
    if bool(s3_endpoint) != bool(s3_bucket):
        raise ValueError("s3 endpoint and bucket must be supplied together")
    if external_analysis_local_graph is not None and (
        s3_endpoint is None
        or s3_bucket is None
        or external_result_workflow is None
        or external_authority_provider is None
    ):
        raise ValueError(
            "local analysis requires S3 endpoint/bucket and workflow/provider authority"
        )


def _literal_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _absolute_config_path(value: str, *, option: str, parser: argparse.ArgumentParser) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        parser.error(f"{option} must be an absolute path without '..'")
    return path


def _load_dev_external_authority(
    *,
    workflow_path: Path,
    provider_path: Path,
) -> tuple[ExternalResultWorkflowAssemblyConfig, Any]:
    from ksi_core.external_authority_provider import load_external_authority_provider
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config

    provider = load_external_authority_provider(
        provider_path, clock=lambda: datetime.now(UTC)
    )
    workflow = load_external_result_workflow_config(
        workflow_path,
        participants=provider.participants,
        build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    return workflow, provider


def main() -> None:
    # 사람이 터미널에서 읽는 스크립트라 JSON 이 아니라 한 줄 텍스트로 —
    # production.py 는 반대(json_format=True, 로그 수집기가 읽는다). 형식만
    # 다르고 correlation id 필터는 dev 도 그대로 받는다(같은 함수).
    configure_structured_logging(json_format=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=".dev-data/core")
    parser.add_argument("--reset", action="store_true", help="기존 데이터 삭제 후 새로 시작")
    parser.add_argument(
        "--journal-segment-bytes",
        type=int,
        default=64 * 1024 * 1024,
        help="journal 세그먼트 회전 임계(바이트, 기본 64MiB). 0 이면 회전하지 않는다.",
    )
    parser.add_argument(
        "--edge-sync-snapshot-every",
        type=int,
        default=500,
        help=(
            "edge-sync 원장 스냅샷 주기(수락 건수, 기본 500). 0 이면 스냅샷을 쓰지 않는다 "
            "— 재기동이 전 항목의 본문 정규화·digest 재계산을 다시 치른다."
        ),
    )
    # Evidence 스토리지(ADR-KSI-010 §1) — **주지 않으면 증거 경로가 장착되지 않는다**(404).
    # 조립되지 않은 기능이 2xx 로 보이는 것보다 없는 편이 정직하다.
    parser.add_argument(
        "--s3-endpoint",
        default=None,
        help="S3 호환 엔드포인트(예: http://127.0.0.1:9000). --s3-bucket 과 함께 준다.",
    )
    parser.add_argument("--s3-bucket", default=None, help="증거 버킷 이름")
    parser.add_argument(
        "--local-analysis-config",
        default=None,
        help=(
            "sealed local Analysis runtime material. It requires --s3-* and the "
            "external workflow/provider configuration pair."
        ),
    )
    parser.add_argument(
        "--external-result-workflow-config",
        default=None,
        help="protected external-result workflow configuration; pair with provider config",
    )
    parser.add_argument(
        "--external-authority-provider-config",
        default=None,
        help="protected signed external-authority provider configuration; pair with workflow",
    )
    parser.add_argument(
        "--human-auth-mode",
        choices=[mode.value for mode in HumanAuthMode],
        default=HumanAuthMode.OPAQUE.value,
        help="사람 인증 방식. 일반 Dashboard 개발은 local stack이 OIDC로 설정한다.",
    )
    parser.add_argument("--oidc-issuer", default=None, help="OIDC issuer origin")
    parser.add_argument(
        "--oidc-audience",
        default=None,
        help="Core가 받는 OIDC access token audience",
    )
    parser.add_argument("--oidc-jwks-url", default=None, help="OIDC JWKS endpoint")
    parser.add_argument(
        "--oidc-jwks-ttl-seconds",
        type=int,
        default=60,
        help="개발 OIDC JWKS cache TTL(초, 기본 60)",
    )
    args = parser.parse_args()

    if bool(args.s3_endpoint) != bool(args.s3_bucket):
        parser.error("--s3-endpoint 와 --s3-bucket 은 함께 주어야 한다")
    if bool(args.external_result_workflow_config) != bool(
        args.external_authority_provider_config
    ):
        parser.error(
            "--external-result-workflow-config 와 "
            "--external-authority-provider-config 는 함께 주어야 한다"
        )
    if args.local_analysis_config is not None:
        if not (args.s3_endpoint and args.s3_bucket):
            parser.error("--local-analysis-config 는 --s3-endpoint/--s3-bucket 을 요구한다")
        if not (
            args.external_result_workflow_config
            and args.external_authority_provider_config
        ):
            parser.error(
                "--local-analysis-config 는 workflow/provider configuration pair를 요구한다"
            )
        if not _literal_loopback_host(args.host):
            parser.error("--local-analysis-config 는 literal loopback --host만 허용한다")

    workflow_path = (
        _absolute_config_path(
            args.external_result_workflow_config,
            option="--external-result-workflow-config",
            parser=parser,
        )
        if args.external_result_workflow_config is not None
        else None
    )
    provider_path = (
        _absolute_config_path(
            args.external_authority_provider_config,
            option="--external-authority-provider-config",
            parser=parser,
        )
        if args.external_authority_provider_config is not None
        else None
    )
    analysis_path = (
        _absolute_config_path(
            args.local_analysis_config,
            option="--local-analysis-config",
            parser=parser,
        )
        if args.local_analysis_config is not None
        else None
    )

    human_auth_mode = HumanAuthMode(args.human_auth_mode)
    oidc_values = (args.oidc_issuer, args.oidc_audience, args.oidc_jwks_url)
    if human_auth_mode is HumanAuthMode.OPAQUE:
        if any(value is not None for value in oidc_values):
            parser.error("--human-auth-mode OPAQUE에는 --oidc-* 설정을 함께 쓸 수 없다")
        oidc_verifier = None
    else:
        if not all(oidc_values):
            parser.error(
                "--human-auth-mode OIDC/DUAL에는 issuer, audience, jwks URL이 모두 필요하다"
            )
        if args.oidc_jwks_ttl_seconds <= 0:
            parser.error("--oidc-jwks-ttl-seconds는 양수여야 한다")
        oidc_verifier = OidcJwtVerifier(
            OidcVerifierConfig(
                issuer=args.oidc_issuer,
                audience=args.oidc_audience,
                jwks_url=args.oidc_jwks_url,
                jwks_ttl_seconds=args.oidc_jwks_ttl_seconds,
            ),
            subject_registry=_dev_oidc_subject_registry(args.oidc_issuer),
        )

    # Validate/load all optional trusted material before --reset can remove
    # durable state or key bootstrap can create any new local authority.
    external_result_workflow = None
    external_authority_provider = None
    if workflow_path is not None and provider_path is not None:
        try:
            external_result_workflow, external_authority_provider = _load_dev_external_authority(
                workflow_path=workflow_path, provider_path=provider_path
            )
        except Exception as exc:
            parser.error("external workflow/provider configuration is unavailable")
            raise AssertionError("argparse parser.error always exits") from exc

    external_analysis_local_graph = None
    if analysis_path is not None:
        from ksi_core.composition.local_analysis_runtime_config import (
            LocalAnalysisRuntimeConfigUnavailable,
            load_local_analysis_runtime_config,
        )

        try:
            external_analysis_local_graph = load_local_analysis_runtime_config(analysis_path)
        except LocalAnalysisRuntimeConfigUnavailable as exc:
            parser.error("local analysis configuration is unavailable")
            raise AssertionError("argparse parser.error always exits") from exc

    data_dir = Path(args.data_dir)
    if args.reset and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    assembly = build_dev_app(
        data_dir,
        segment_bytes=cli_optional_positive(
            args.journal_segment_bytes, name="--journal-segment-bytes"
        ),
        edge_sync_snapshot_every=cli_optional_positive(
            args.edge_sync_snapshot_every, name="--edge-sync-snapshot-every"
        ),
        s3_endpoint=args.s3_endpoint,
        s3_bucket=args.s3_bucket,
        human_auth_mode=human_auth_mode,
        oidc_verifier=oidc_verifier,
        external_result_workflow=external_result_workflow,
        external_analysis_local_graph=external_analysis_local_graph,
        external_authority_provider=external_authority_provider,
    )

    print("=" * 72)
    print(f"KSI Core dev server — data: {data_dir.resolve()}")
    if human_auth_mode is HumanAuthMode.OPAQUE:
        print("Legacy local human authentication: opaque bearer tokens are enabled.")
    else:
        print(f"Human authentication: {human_auth_mode.value} via {args.oidc_issuer}")
        print(
            "Local Dashboard users must use the OIDC login redirect; "
            "no bearer token entry is required."
        )
    print("Device/worker opaque credentials remain available only for adapter integration tests.")
    print("=" * 72)

    try:
        uvicorn.run(assembly.app, host=args.host, port=args.port)
    finally:
        assembly.close()


if __name__ == "__main__":
    main()
