"""프로덕션 조립 지점(ksi_core.production)의 계약 테스트.

``tests/contract/test_dev_assembly.py`` 가 저장소의 유일한 실행 가능 dev 조립을
검증하는 것과 대칭으로, 이 파일은 유일한 실행 가능 **운영** 조립을 검증한다.
핵심 우려는 세 가지다 — ①dev 토큰이 운영 빌드에 섞여 들어오지 않는다,
②필수 환경변수 부재가 조용히 기본값으로 넘어가지 않고 fail-closed 로 즉시
거부된다, ③``assemble_app`` 한 곳을 dev·production 이 공유하므로 그 공유
지점이 ``create_app`` 의 모든 store 파라미터를 실제로 채운다.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from pathlib import Path
from typing import Any

import ksi_core.app_assembly as app_assembly_module
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.app_assembly import assemble_app
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from test_external_analysis_activation import ActivationBindings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_SOURCE = (
    _REPO_ROOT / "services" / "core" / "src" / "ksi_core" / "production.py"
).read_text(encoding="utf-8")

_DEV_TOKEN_LITERALS = [
    "dev-admin-token",
    "dev-field-operator-token",
    "dev-viewer-token",
    "dev-edge-device-token",
    "dev-gateway-device-token",
    "dev-processing-worker-token",
]

_ALL_REQUIRED_ENV = (
    "KSI_CORE_DATA_DIR",
    "KSI_CORE_SIGNING_KEYS_DIR",
    "KSI_CORE_S3_ENDPOINT",
    "KSI_CORE_S3_BUCKET",
    "KSI_CORE_PRINCIPAL_TOKENS_JSON",
    "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE",
)


# ── 1. dev 토큰·dev 모듈 의존 부재 (소스 텍스트 검사) ───────────────────────


def test_production_source_contains_no_dev_token_literals() -> None:
    """production.py 소스에 dev 고정 토큰 문자열이 단 하나도 없다."""
    for literal in _DEV_TOKEN_LITERALS:
        assert literal not in _PRODUCTION_SOURCE, (
            f"production.py 에 dev 토큰 리터럴이 있다: {literal!r} — "
            "운영 빌드가 dev 자격증명을 끌고 들어올 수 있다"
        )


def test_production_does_not_import_run_core_dev() -> None:
    """production.py 는 run_core_dev 를 import 하지 않는다 — dev 모듈에 대한 의존 없음.

    모듈 docstring 은 산문으로 ``scripts/run_core_dev.py`` 를 **언급**한다(dev 조립과의
    대비 설명) — 그건 의존이 아니다. 여기서 거부하는 것은 실제 import 문뿐이다.
    """
    assert "import run_core_dev" not in _PRODUCTION_SOURCE
    assert "from run_core_dev" not in _PRODUCTION_SOURCE


# ── 2. 필수 환경변수 부재 → RuntimeError(fail-closed) ───────────────────────


def _write_signing_keys(keys_dir: Path) -> None:
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_id = "core-prod-test-key"
    key = Ed25519PrivateKey.generate()
    (keys_dir / f"{key_id}.private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (keys_dir / f"{key_id}.private.pem").chmod(0o600)
    (keys_dir / f"{key_id}.public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    (keys_dir / "keys.json").write_text(
        json.dumps({"active": key_id, "keys": [{"keyId": key_id, "status": "ACTIVE"}]}),
        encoding="utf-8",
    )


def _valid_env(tmp_path: Path) -> dict[str, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    signing_dir = tmp_path / "signing"
    _write_signing_keys(signing_dir)
    attestation_manifest = tmp_path / "device-attestation-keys.json"
    attestation_manifest.write_text(json.dumps({"keys": []}), encoding="utf-8")

    tokens = [
        {
            "tokenSha256": hashlib.sha256(b"prod-admin-token").hexdigest(),
            "principalId": "prod-admin",
            "kind": "OPERATOR",
            "role": "ADMIN",
            "deviceId": None,
        }
    ]
    return {
        "KSI_CORE_DATA_DIR": str(data_dir),
        "KSI_CORE_SIGNING_KEYS_DIR": str(signing_dir),
        "KSI_CORE_S3_ENDPOINT": "http://127.0.0.1:9000",
        "KSI_CORE_S3_BUCKET": "prod-evidence",
        "KSI_CORE_PRINCIPAL_TOKENS_JSON": json.dumps(tokens),
        "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE": str(attestation_manifest),
    }


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _enable_analysis_activation(
    tmp_path: Path,
    env: dict[str, str],
    *,
    activation_fields: dict[str, object] | None = None,
    add_ambiguous_worker: bool = False,
) -> tuple[AnalysisActivationV1, ActivationBindings]:
    from datetime import UTC, datetime, timedelta

    from test_external_analysis_activation import _bindings, _write_activation

    bindings = _bindings()
    tokens = json.loads(env["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
    tokens.append(
        {
            "tokenSha256": hashlib.sha256(b"analysis-worker-test-token").hexdigest(),
            "principalId": bindings["worker_principal"].principal_id,
            "kind": "ANALYSIS_WORKER",
            "role": None,
            "deviceId": None,
            "organizationId": bindings["organization_id"],
        }
    )
    if add_ambiguous_worker:
        tokens.append(
            {
                "tokenSha256": hashlib.sha256(b"analysis-worker-test-token-b").hexdigest(),
                "principalId": "analysis-worker-b",
                "kind": "ANALYSIS_WORKER",
                "role": None,
                "deviceId": None,
                "organizationId": bindings["organization_id"],
            }
        )
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(tokens)

    runtime = bindings["runtime"]
    policy = bindings["policy"]
    envelope = bindings["resource_envelope"]
    runtime_config = tmp_path / "local-analysis-runtime.json"
    runtime_config.write_text(
        json.dumps(
            {
                "version": "local-analysis-runtime.v1",
                "policy": policy.model_dump(by_alias=True, mode="json"),
                "runtime": {
                    "workerExecutableDigest": runtime.worker_executable_digest,
                    "workerBuildDigest": runtime.worker_build_digest,
                    "runtimeImageVersion": runtime.runtime_image_version,
                    "runtimeImageOciDigest": runtime.runtime_image_oci_digest,
                    "dependencyLockDigest": runtime.dependency_lock_digest,
                },
                "resourceEnvelope": envelope.model_dump(by_alias=True, mode="json"),
            }
        ),
        encoding="utf-8",
    )
    runtime_config.chmod(0o600)
    activation_dir = tmp_path / "activation"
    activation_dir.mkdir(mode=0o700)
    fields = activation_fields or {
        "issuedAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "validUntil": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    activation_path, keys_path, activation = _write_activation(
        activation_dir, bindings=bindings, activation_fields=fields
    )
    env["KSI_CORE_ANALYSIS_RUNTIME_CONFIG_FILE"] = str(runtime_config)
    env["KSI_CORE_ANALYSIS_ACTIVATION_FILE"] = str(activation_path)
    env["KSI_CORE_ANALYSIS_ACTIVATION_KEYS_FILE"] = str(keys_path)
    return activation, bindings


def test_copilot_runtime_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from ksi_core.production import _copilot_runtime_config_env

    monkeypatch.delenv("KSI_COPILOT_ENABLED", raising=False)
    assert _copilot_runtime_config_env() is None


def test_enabled_copilot_requires_complete_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _copilot_runtime_config_env

    key_file = tmp_path / "copilot-api-key"
    key_file.write_text("test-only-key", encoding="utf-8")
    monkeypatch.setenv("KSI_COPILOT_ENABLED", "true")
    monkeypatch.setenv("KSI_COPILOT_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("KSI_COPILOT_BASE_URL", "https://provider.example")
    monkeypatch.delenv("KSI_COPILOT_MODEL", raising=False)
    monkeypatch.setenv("KSI_COPILOT_PLANNER_VERSION", "planner-1")

    with pytest.raises(RuntimeError, match="KSI_COPILOT_MODEL"):
        _copilot_runtime_config_env()


def test_copilot_runtime_reads_secret_file_reference_without_reading_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _copilot_runtime_config_env

    key_file = tmp_path / "copilot-api-key"
    key_file.write_text("test-only-key", encoding="utf-8")
    monkeypatch.setenv("KSI_COPILOT_ENABLED", "true")
    monkeypatch.setenv("KSI_COPILOT_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("KSI_COPILOT_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("KSI_COPILOT_MODEL", "provider-model")
    monkeypatch.setenv("KSI_COPILOT_PLANNER_VERSION", "planner-2")
    monkeypatch.setenv("KSI_COPILOT_REQUEST_TIMEOUT_SECONDS", "12.5")

    config = _copilot_runtime_config_env()

    assert config is not None
    assert config.api_key_file == key_file
    assert config.model == "provider-model"
    assert config.timeout_seconds == 12.5
    assert "test-only-key" not in repr(config)


@pytest.mark.parametrize("missing", _ALL_REQUIRED_ENV)
def test_missing_required_env_var_raises_runtime_error(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다섯 필수 환경변수 중 하나라도 빠지면 RuntimeError — 조용히 기본값으로 넘어가지 않는다."""
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    del env[missing]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError):
        build_production_app()


def test_missing_env_var_fails_before_heavy_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 엔드포인트가 없으면 boto3 client 조립(무거운 부수효과) 전에 이미 죽는다.

    가장 뒤에 검증되는 값 중 하나(S3_BUCKET)를 지워 이 순서를 확인한다 — 이보다
    앞서 조립되는 무거운 자원(journal 파일 등)이 생기기 전에 실패해야 한다.
    """
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    del env["KSI_CORE_S3_BUCKET"]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv("KSI_CORE_S3_BUCKET", raising=False)

    with pytest.raises(RuntimeError, match="KSI_CORE_S3_BUCKET"):
        build_production_app()
    # 검증 실패 시점에는 아직 어떤 journal 파일도 만들어지지 않았어야 한다 —
    # 무거운 조립(2단계)에 진입하기 전에 1단계 검증이 전부 끝난다는 증거.
    data_dir = Path(env["KSI_CORE_DATA_DIR"])
    assert list(data_dir.iterdir()) == []


def test_malformed_principal_tokens_json_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = "not-json"
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_production_app()


def test_unknown_principal_kind_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "NOT_A_KIND",
                "role": None,
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError):
        build_production_app()


def test_analysis_mcp_production_principal_requires_explicit_nonempty_scope() -> None:
    from ksi_core.composition.production_config import _parse_principal_tokens

    row = {
        "tokenSha256": hashlib.sha256(b"analysis-mcp-production-token").hexdigest(),
        "principalId": "analysis-mcp-production",
        "kind": "ANALYSIS_MCP_CLIENT",
        "role": None,
        "deviceId": None,
        "organizationId": "org-prod",
        "allowedSiteIds": ["site-prod"],
        "allowedWorkAreaIds": ["wa-site-prod-0001"],
    }
    parsed = _parse_principal_tokens(json.dumps([row]))
    assert parsed[0].principal.allowed_site_ids == frozenset({"site-prod"})
    assert parsed[0].principal.allowed_work_area_ids == frozenset({"wa-site-prod-0001"})

    invalid_rows = (
        {key: value for key, value in row.items() if key != "allowedSiteIds"},
        {key: value for key, value in row.items() if key != "allowedWorkAreaIds"},
        {**row, "allowedSiteIds": []},
        {**row, "allowedWorkAreaIds": []},
        {**row, "allowedSiteIds": ["site-prod", "site-prod"]},
        {**row, "allowedWorkAreaIds": ["wa-site-prod-0001", "wa-site-prod-0001"]},
        {**row, "allowedSiteIds": ["site/prod"]},
        {**row, "allowedWorkAreaIds": [" "]},
        {**row, "allowedSiteIds": "site-prod"},
        {**row, "allowedWorkAreaIds": [3]},
    )
    for invalid in invalid_rows:
        with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
            _parse_principal_tokens(json.dumps([invalid]))


def test_plaintext_token_sha256_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tokenSha256`` 에 원문 토큰(digest 아님)이 실리면 1단계 검증에서 즉시 거부한다.

    ``AuthRegistry`` 도 같은 값을 거부하지만(``_TOKEN_SHA256_RE``) 그건 2단계(무거운
    조립 이후)다 — 이 테스트는 형식 검증이 그보다 앞서 fail-closed 로 걸린다는 것과,
    예외 메시지가 어느 env 가 문제인지 이름을 남긴다는 것(독립 재검토 지적 A2)을 함께
    고정한다.
    """
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": "dev-admin-token",
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_production_app()


def test_negative_journal_segment_bytes_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``KSI_CORE_JOURNAL_SEGMENT_BYTES=-1`` 도 다른 형식 오류처럼 RuntimeError 다.

    ``cli_optional_positive`` (dev CLI 와 공유하는 라이브러리 계약)는 음수를
    ``ValueError`` 로 거부한다 — 이 함수는 환경변수 검증 경계이므로 모듈 docstring
    이 약속한 "형식이 틀리면 RuntimeError"를 이 입력에 대해서도 지켜야 한다(독립
    재검토 지적 A3, 이전 버전은 여기서 ValueError 가 새어 나갔다).
    """
    env = _valid_env(tmp_path)
    env["KSI_CORE_JOURNAL_SEGMENT_BYTES"] = "-1"
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError):
        build_production_app()


def test_unknown_token_status_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "status": "SUSPENDED",
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="status"):
        build_production_app()


def test_naive_not_after_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``notAfter`` 에 tz 없는 ISO 문자열이 오면 거부한다 — signing_keys.py 의
    같은 검증(naive datetime 은 만료 비교에서 fail-closed 를 깬다)과 동일 이유."""
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "notAfter": "2026-01-01T00:00:00",
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="notAfter"):
        build_production_app()


def test_rotation_overlap_lets_old_and_new_token_both_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] 회전 절차의 핵심 성질 — 같은 ``principalId`` 로 발급된 새 토큰과
    유예기간이 아직 안 지난 이전 토큰이 **동시에** 인증된다. 문서
    (``docs/security/AUTH_TOKEN_ROTATION.md``)가 약속하는 겹침 구간이 실제
    ``build_production_app`` 조립에서도 성립하는지 HTTP 경계로 확인한다."""
    old_token = "old-rotating-token"  # noqa: S105 -- 테스트 고정값
    new_token = "new-rotating-token"  # noqa: S105 -- 테스트 고정값
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(new_token.encode()).hexdigest(),
                "principalId": "rotating-admin",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
            },
            {
                "tokenSha256": hashlib.sha256(old_token.encode()).hexdigest(),
                "principalId": "rotating-admin",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "notAfter": "2099-01-01T00:00:00Z",
            },
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    client = TestClient(build_production_app())
    old_response = client.get("/v1/auth/whoami", headers={"Authorization": f"Bearer {old_token}"})
    new_response = client.get("/v1/auth/whoami", headers={"Authorization": f"Bearer {new_token}"})

    assert old_response.status_code == 200
    assert new_response.status_code == 200
    assert old_response.json()["principalId"] == "rotating-admin"
    assert new_response.json()["principalId"] == "rotating-admin"


# ── 3. 정상 env → FastAPI 인스턴스 ─────────────────────────────────────────


def test_valid_env_builds_fastapi_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 환경변수 세트로 ``build_production_app`` 이 FastAPI 인스턴스를 반환한다.

    S3 엔드포인트 값 자체는 검증만 되고 실제 연결은 만들어지지 않는다 —
    boto3 client 생성은 네트워크 왕복 없이 성공한다(어댑터가 지연 발급하는
    presigned URL 시점에만 실제 통신이 일어난다).
    """
    _apply_env(monkeypatch, _valid_env(tmp_path))

    from ksi_core.production import build_production_app

    app = build_production_app()
    assert isinstance(app, FastAPI)
    paths = set(app.openapi()["paths"])
    assert "/v1/sites/{site_id}/analysis-observations" not in paths
    assert "/v1/internal/analysis-jobs" not in paths


def test_production_mounts_analysis_only_from_valid_explicit_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    activation, _bindings_for_config = _enable_analysis_activation(tmp_path, env)
    _apply_env(monkeypatch, env)

    app = build_production_app()
    paths = set(app.openapi()["paths"])

    assert "/v1/sites/{site_id}/analysis-observations" in paths
    assert "/v1/sites/{site_id}/work-areas/{work_area_id}/analyses" in paths
    assert "/v1/internal/analysis-jobs" in paths

    from fastapi.testclient import TestClient
    from ksi_core.domains.external.quantity import external_analysis_api as analysis_api
    from ksi_core.domains.external.quantity import (
        external_analysis_worker_api as worker_api,
    )
    from ksi_event_contracts.external_analysis_api import (
        AnalysisObservationSelectorV1,
        CreateAnalysisRequestV1,
    )
    from ksi_event_contracts.external_relative_volume_calculation import (
        RelativeVolumeCalculationFailureV2,
        RelativeVolumeCalculationReportV2,
        RelativeVolumeCoverageWitnessV2,
        RelativeVolumeMetricsV2,
        RelativeVolumeNumericResultV2,
    )
    from test_external_analysis_worker_api import _expired_attempt

    class _Clock:
        value = activation.issued_at + timedelta(seconds=1)

        @classmethod
        def now(cls, _tz: object = UTC) -> datetime:
            return cls.value

    monkeypatch.setattr(analysis_api, "datetime", _Clock)
    monkeypatch.setattr(worker_api, "datetime", _Clock)
    client = TestClient(app)
    worker_headers = {"Authorization": "Bearer analysis-worker-test-token"}
    operator_headers = {"Authorization": "Bearer prod-admin-token"}
    create_body = CreateAnalysisRequestV1(
        baseline=AnalysisObservationSelectorV1(
            work_order_id="work-order-a",
            submission_ref="ers-v1-" + "a" * 64,
            revision=1,
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id="work-order-b",
            submission_ref="ers-v1-" + "b" * 64,
            revision=1,
        ),
    ).model_dump(by_alias=True)
    active_create = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={**operator_headers, "Idempotency-Key": "activation-live-create"},
        json=create_body,
    )
    assert active_create.status_code == 404  # Current activation reached normal scoped lookup.
    assert client.get("/v1/internal/analysis-jobs", headers=worker_headers).status_code == 200

    _Clock.value = activation.valid_until + timedelta(seconds=1)
    expired_create = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={**operator_headers, "Idempotency-Key": "activation-expired-create"},
        json=create_body,
    )
    assert expired_create.status_code == 503
    assert expired_create.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"

    attempt = _expired_attempt(_Clock.value)
    assert attempt.execution_attempt_digest is not None
    failure = RelativeVolumeCalculationFailureV2(
        failure_id="activation-test-failure",
        attempt=attempt,
        attempt_digest=attempt.execution_attempt_digest,
        reason_code="TEST_FAILURE",
        failed_at=_Clock.value,
    ).sealed()
    coverage = RelativeVolumeCoverageWitnessV2(
        rows=1,
        columns=1,
        row_offset=0,
        column_offset=0,
        selected_mask_b64="gA==",
        common_valid_mask_b64="gA==",
        unavailable_mask_b64="AA==",
        threshold_excluded_mask_b64="AA==",
        selected_cell_count=1,
        common_valid_cell_count=1,
        unavailable_cell_count=0,
        threshold_excluded_cell_count=0,
        cell_area_m2=1.0,
        selected_area_m2=1.0,
        common_valid_area_m2=1.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
    ).sealed()
    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest=attempt.authorization.calculation_identity_digest,
        profile_digest="sha256:" + "c" * 64,
        metrics=RelativeVolumeMetricsV2(
            cut_m3=0.0, fill_m3=0.0, net_m3=0.0, threshold_m=0.0
        ),
        coverage=coverage,
    ).sealed()
    assert numeric.numeric_result_identity_digest is not None
    report = RelativeVolumeCalculationReportV2(
        report_id="activation-test-report",
        attempt=attempt,
        attempt_digest=attempt.execution_attempt_digest,
        numeric_result=numeric,
        numeric_result_identity_digest=numeric.numeric_result_identity_digest,
        computed_at=_Clock.value,
        reported_at=_Clock.value,
    ).sealed()
    worker_requests = (
        ("GET", "/v1/internal/analysis-jobs", None),
        (
            "POST",
            "/v1/internal/analysis-jobs/missing:lease",
            {"workerInstanceId": "analysis-worker-a", "leaseAcquisitionId": "lease-a"},
        ),
        ("GET", "/v1/internal/analysis-jobs/missing/input", None),
        (
            "POST",
            "/v1/internal/analysis-jobs/missing:renew",
            {"attempt": attempt.model_dump(by_alias=True, mode="json")},
        ),
        (
            "POST",
            "/v1/internal/analysis-jobs/missing:report",
            {"report": report.model_dump(by_alias=True, mode="json")},
        ),
        (
            "POST",
            "/v1/internal/analysis-jobs/missing:failure",
            {"failure": failure.model_dump(by_alias=True, mode="json")},
        ),
    )
    for method, path, body in worker_requests:
        response = client.request(method, path, headers=worker_headers, json=body)
        assert response.status_code == 503, (method, path, response.text)
        assert response.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"


@pytest.mark.parametrize(
    "activation_fields",
    [
        {"runtimeDigest": "sha256:" + "f" * 64},
        {"workerPrincipalId": "different-analysis-worker"},
    ],
)
def test_production_rejects_signed_activation_bound_to_another_runtime_or_worker(
    activation_fields: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    _enable_analysis_activation(tmp_path, env, activation_fields=activation_fields)
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="signed Analysis activation is invalid"):
        build_production_app()


def test_production_rejects_ambiguous_analysis_worker_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    _enable_analysis_activation(tmp_path, env, add_ambiguous_worker=True)
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="exactly one registered ANALYSIS_WORKER"):
        build_production_app()


def test_production_rejects_invalid_activation_signature_before_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    _enable_analysis_activation(tmp_path, env)
    activation_path = Path(env["KSI_CORE_ANALYSIS_ACTIVATION_FILE"])
    record = json.loads(activation_path.read_text(encoding="utf-8"))
    signature = record["signature"]
    record["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    activation_path.write_text(json.dumps(record), encoding="utf-8")
    activation_path.chmod(0o600)
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="signed Analysis activation is invalid"):
        build_production_app()


def test_production_rejects_partial_analysis_activation_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    env["KSI_CORE_ANALYSIS_ACTIVATION_FILE"] = str(tmp_path / "activation.json")
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="requires all three explicit file paths"):
        build_production_app()


def test_expired_activation_boot_keeps_analysis_read_routes_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    _enable_analysis_activation(
        tmp_path,
        env,
        activation_fields={
            "issuedAt": (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace(
                "+00:00", "Z"
            ),
            "validUntil": (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
        },
    )
    _apply_env(monkeypatch, env)

    app = build_production_app()
    paths = set(app.openapi()["paths"])
    assert "/v1/sites/{site_id}/analyses/{analysis_id}/result" in paths
    client = TestClient(app)
    read = client.get(
        "/v1/sites/site-a/analyses/historical-result-id/result",
        headers={"Authorization": "Bearer prod-admin-token"},
    )
    create = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={
            "Authorization": "Bearer prod-admin-token",
            "Idempotency-Key": "expired-production-create",
        },
        json={
            "baseline": {
                "workOrderId": "work-order-a",
                "submissionRef": "ers-v1-" + "a" * 64,
                "revision": 1,
            },
            "current": {
                "workOrderId": "work-order-b",
                "submissionRef": "ers-v1-" + "b" * 64,
                "revision": 1,
            },
        },
    )
    worker = client.get(
        "/v1/internal/analysis-jobs",
        headers={"Authorization": "Bearer analysis-worker-test-token"},
    )
    assert read.status_code == 404  # The historical read route remains available.
    assert create.status_code == worker.status_code == 503


def test_expose_docs_defaults_closed_and_opens_when_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KSI_CORE_EXPOSE_DOCS 미설정이면 /docs 가 404, "true" 면 열린다."""
    from ksi_core.production import build_production_app

    # 서로 다른 data-dir — 같은 디렉터리로 두 번 조립하면 첫 조립이 연 journal 의
    # flock 을 아직 쥐고 있어(테스트가 close 하지 않는다) 두 번째 조립이
    # JournalRecoveryError("다른 프로세스가 소유 중")로 실패한다(단일 writer 불변식).
    closed_env = _valid_env(tmp_path / "closed")
    _apply_env(monkeypatch, closed_env)
    monkeypatch.delenv("KSI_CORE_EXPOSE_DOCS", raising=False)
    closed_app = build_production_app()
    closed_client = TestClient(closed_app)
    assert closed_client.get("/docs").status_code == 404

    open_env = _valid_env(tmp_path / "open")
    _apply_env(monkeypatch, open_env)
    monkeypatch.setenv("KSI_CORE_EXPOSE_DOCS", "true")
    open_app = build_production_app()
    open_client = TestClient(open_app)
    assert open_client.get("/docs").status_code == 200


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("false", False), ("0", False), ("true", True), ("1", True)],
)
def test_acquisition_issue_gate_requires_explicit_rollout_flag(
    value: str | None, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _acquisition_issue_gate_env

    if value is None:
        monkeypatch.delenv("KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED", value)
    assert _acquisition_issue_gate_env() is expected


def test_acquisition_issue_gate_rejects_ambiguous_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import _acquisition_issue_gate_env

    monkeypatch.setenv("KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED", "enabled")
    with pytest.raises(RuntimeError, match="true.*false"):
        _acquisition_issue_gate_env()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("false", False), ("0", False), ("true", True), ("1", True)],
)
def test_acquisition_coordination_has_independent_rollback_flag(
    value: str | None, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _acquisition_coordination_env

    if value is None:
        monkeypatch.delenv("KSI_CORE_ACQUISITION_COORDINATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("KSI_CORE_ACQUISITION_COORDINATION_ENABLED", value)
    assert _acquisition_coordination_env() is expected


def test_acquisition_coordination_rejects_ambiguous_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import _acquisition_coordination_env

    monkeypatch.setenv("KSI_CORE_ACQUISITION_COORDINATION_ENABLED", "enabled")
    with pytest.raises(RuntimeError, match="true.*false"):
        _acquisition_coordination_env()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("false", False), ("0", False), ("true", True), ("1", True)],
)
def test_checkpoint_validation_registration_requires_explicit_rollout_flag(
    value: str | None, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _checkpoint_validation_registration_env

    if value is None:
        monkeypatch.delenv("KSI_CORE_CHECKPOINT_VALIDATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("KSI_CORE_CHECKPOINT_VALIDATION_ENABLED", value)
    assert _checkpoint_validation_registration_env() is expected


def test_checkpoint_validation_registration_rejects_ambiguous_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import _checkpoint_validation_registration_env

    monkeypatch.setenv("KSI_CORE_CHECKPOINT_VALIDATION_ENABLED", "enabled")
    with pytest.raises(RuntimeError, match="true.*false"):
        _checkpoint_validation_registration_env()


def test_human_auth_mode_defaults_opaque_for_existing_local_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.auth import HumanAuthMode
    from ksi_core.production import _human_auth_config_env

    monkeypatch.delenv("KSI_CORE_HUMAN_AUTH_MODE", raising=False)
    mode, config = _human_auth_config_env()
    assert mode is HumanAuthMode.OPAQUE
    assert config is None


@pytest.mark.parametrize(
    "missing",
    ["KSI_CORE_OIDC_ISSUER", "KSI_CORE_OIDC_AUDIENCE", "KSI_CORE_OIDC_JWKS_URL"],
)
def test_oidc_human_auth_requires_all_verification_inputs(
    missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import _human_auth_config_env

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "OIDC")
    monkeypatch.setenv("KSI_CORE_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("KSI_CORE_OIDC_AUDIENCE", "ksi-core")
    monkeypatch.setenv("KSI_CORE_OIDC_JWKS_URL", "https://issuer.example.test/jwks.json")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=missing):
        _human_auth_config_env()


@pytest.mark.parametrize("mode", ["OIDC", "DUAL"])
def test_human_auth_requires_subject_registry_path(
    mode: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import _human_auth_config_env

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", mode)
    monkeypatch.setenv("KSI_CORE_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("KSI_CORE_OIDC_AUDIENCE", "ksi-core")
    monkeypatch.setenv("KSI_CORE_OIDC_JWKS_URL", "https://issuer.example.test/jwks.json")
    monkeypatch.delenv("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE", raising=False)
    with pytest.raises(RuntimeError, match="KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE"):
        _human_auth_config_env()


def test_production_oidc_verifier_uses_loaded_subject_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app
    from test_oidc_auth import _jwk, _token

    env = _valid_env(tmp_path)
    subject_path = tmp_path / "oidc-subjects.json"
    subject_path.write_text(
        json.dumps(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": "https://issuer.example.test",
                        "subject": "provider-subject-1",
                        "principalId": "prod-oidc-user",
                        "organizationId": "org-prod-1",
                        "role": "FIELD_OPERATOR",
                        "status": "ACTIVE",
                        "allowedSiteIds": ["site-prod-1"],
                        "allowedWorkAreaIds": ["area-prod-1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subject_path.chmod(0o600)
    env.update(
        {
            "KSI_CORE_HUMAN_AUTH_MODE": "OIDC",
            "KSI_CORE_OIDC_ISSUER": "https://issuer.example.test",
            "KSI_CORE_OIDC_AUDIENCE": "ksi-core",
            "KSI_CORE_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE": str(subject_path),
        }
    )
    _apply_env(monkeypatch, env)

    app = build_production_app()
    verifier = app.state.oidc_verifier
    signing_key = generate_private_key(public_exponent=65537, key_size=2048)
    verifier._fetch_jwks = lambda: {"keys": [_jwk(signing_key, "production-test-key")]}
    token = _token(
        signing_key,
        kid="production-test-key",
        claims={
            "iss": "https://issuer.example.test",
            "aud": "ksi-core",
            "sub": "provider-subject-1",
            "exp": int(time.time()) + 600,
            "nbf": int(time.time()) - 30,
            "ksi_principal_id": "forged-user",
            "ksi_organization_id": "forged-org",
            "ksi_role": "ADMIN",
        },
    )
    principal = verifier.verify(token)

    assert principal is not None
    assert principal.principal_id == "prod-oidc-user"
    assert principal.organization_id == "org-prod-1"
    assert principal.role.value == "FIELD_OPERATOR"
    assert principal.allowed_site_ids == frozenset({"site-prod-1"})
    assert principal.allowed_work_area_ids == frozenset({"area-prod-1"})


def test_production_dual_rejects_oidc_subject_collision_with_opaque_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    token_rows = json.loads(env["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
    token_rows[0]["organizationId"] = "org-collision"
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(token_rows)
    subject_path = tmp_path / "oidc-subjects.json"
    subject_path.write_text(
        json.dumps(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": "https://issuer.example.test",
                        "subject": "provider-subject-1",
                        "principalId": "prod-admin",
                        "organizationId": "org-collision",
                        "role": "ADMIN",
                        "status": "ACTIVE",
                        "allowedSiteIds": [],
                        "allowedWorkAreaIds": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subject_path.chmod(0o600)
    env.update(
        {
            "KSI_CORE_HUMAN_AUTH_MODE": "DUAL",
            "KSI_CORE_OIDC_ISSUER": "https://issuer.example.test",
            "KSI_CORE_OIDC_AUDIENCE": "ksi-core",
            "KSI_CORE_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE": str(subject_path),
        }
    )
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="OIDC.*opaque.*principalId"):
        build_production_app()


@pytest.mark.parametrize(
    ("mode", "opaque_kind", "record_status", "oidc_status"),
    [
        ("OIDC", "PROCESSING_WORKER", "ACTIVE", "ACTIVE"),
        ("DUAL", "GATEWAY_DEVICE", "REVOKED", "REVOKED"),
    ],
)
def test_production_oidc_modes_reject_all_opaque_principal_id_collisions(
    mode: str,
    opaque_kind: str,
    record_status: str,
    oidc_status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    token_rows = json.loads(env["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
    opaque_record: dict[str, object] = {
        "tokenSha256": hashlib.sha256(b"colliding-opaque-token").hexdigest(),
        "principalId": "shared-opaque-id",
        "kind": opaque_kind,
        "role": None,
        "deviceId": "gateway-collision" if opaque_kind == "GATEWAY_DEVICE" else None,
        "organizationId": "org-shared",
        "status": record_status,
    }
    token_rows.append(opaque_record)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(token_rows)
    subject_path = tmp_path / "oidc-subjects.json"
    subject_path.write_text(
        json.dumps(
            {
                "version": "oidc-subject-registry.v1",
                "subjects": [
                    {
                        "issuer": "https://issuer.example.test",
                        "subject": "provider-subject-1",
                        "principalId": "shared-opaque-id",
                        "organizationId": "org-shared",
                        "role": "FIELD_OPERATOR",
                        "status": oidc_status,
                        "allowedSiteIds": [],
                        "allowedWorkAreaIds": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subject_path.chmod(0o600)
    env.update(
        {
            "KSI_CORE_HUMAN_AUTH_MODE": mode,
            "KSI_CORE_OIDC_ISSUER": "https://issuer.example.test",
            "KSI_CORE_OIDC_AUDIENCE": "ksi-core",
            "KSI_CORE_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE": str(subject_path),
        }
    )
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="OIDC.*opaque.*principalId"):
        build_production_app()


def test_oidc_human_auth_rejects_unknown_mode_and_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ksi_core.production import _human_auth_config_env

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "MAYBE")
    with pytest.raises(RuntimeError, match="OPAQUE, DUAL, OIDC"):
        _human_auth_config_env()

    monkeypatch.setenv("KSI_CORE_HUMAN_AUTH_MODE", "OIDC")
    monkeypatch.setenv("KSI_CORE_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("KSI_CORE_OIDC_AUDIENCE", "ksi-core")
    monkeypatch.setenv("KSI_CORE_OIDC_JWKS_URL", "https://issuer.example.test/jwks.json")
    monkeypatch.setenv("KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE", "/tmp/subjects.json")
    monkeypatch.setenv("KSI_CORE_OIDC_ALLOWED_ALGORITHMS", "none")
    with pytest.raises(RuntimeError, match="RS256, ES256"):
        _human_auth_config_env()


def test_production_oidc_rejects_symlinked_subject_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    source = tmp_path / "subjects-real.json"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o600)
    symlink = tmp_path / "subjects-link.json"
    symlink.symlink_to(source)
    env.update(
        {
            "KSI_CORE_HUMAN_AUTH_MODE": "OIDC",
            "KSI_CORE_OIDC_ISSUER": "https://issuer.example.test",
            "KSI_CORE_OIDC_AUDIENCE": "ksi-core",
            "KSI_CORE_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
            "KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE": str(symlink),
        }
    )
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="protected OIDC subject registry"):
        build_production_app()


def test_acquisition_coordination_rollback_keeps_legacy_mission_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    env["KSI_CORE_ACQUISITION_COORDINATION_ENABLED"] = "false"
    _apply_env(monkeypatch, env)
    app = build_production_app()
    paths = set(app.openapi()["paths"])

    assert "/v1/missions/plans" in paths
    assert "/v1/observation-work-orders/{work_order_id}/acquisition-progress" not in paths
    assert "/v1/gateway-sync/operation-receipts" not in paths
    assert not (Path(env["KSI_CORE_DATA_DIR"]) / "acquisition-runs.jsonl").exists()


# ── 4. assemble_app 이 create_app 의 모든 *_store 파라미터를 채운다 ─────────
#
# dev(run_core_dev.py)와 production 양쪽이 assemble_app 하나를 거치므로, 이
# 인트로스펙션 대조는 여기 한 번만 있으면 충분하다(test_dev_assembly.py 의
# test_max_assembly_passes_every_store_parameter 와 동형 — 대상만 assemble_app).


def test_assemble_app_wires_every_create_app_store_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``assemble_app`` 이 ``create_app`` 의 모든 ``*_store`` 인자를 실제로 채우는지,
    이름 집합을 서로 대조해 확인한다.

    이전 버전은 ``store_params``(``create_app`` 시그니처에서 뽑은 집합)를 어디와도
    대조하지 않고 ``assert store_params``/``assert paths`` 두 비어있음 검사만 했다 —
    ``assemble_app`` 이 ``equipment_support_store`` 등을 통째로 안 넘기게 되어도
    그 버전은 green 이었다(독립 재검토 지적 A1). ``ksi_core.app_assembly.create_app`` 을
    가로채 실제로 넘어온 kwargs 이름을 캡처해 ``store_params`` 와 진짜 차집합을 낸다.
    """
    store_params = {
        name for name in inspect.signature(create_app).parameters if name.endswith("_store")
    }

    captured_kwargs: dict[str, Any] = {}
    original_create_app = create_app

    def _capturing_create_app(**kwargs: Any) -> FastAPI:
        captured_kwargs.update(kwargs)
        return original_create_app(**kwargs)

    monkeypatch.setattr(app_assembly_module, "create_app", _capturing_create_app)

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / name)
        opened.append(journal)
        return journal

    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    auth_registry = AuthRegistry(
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
    )

    class _NullEvidenceStorage:
        def presigned_put_bound_digest(
            self,
            object_key: str,
            *,
            content_type: str,
            content_digest: str,
            ttl: Any,
        ) -> DigestBoundUploadCapability:
            del ttl
            return DigestBoundUploadCapability(
                upload_url=f"https://storage.invalid/{object_key}",
                required_headers={
                    "Content-Type": content_type,
                    "x-amz-checksum-sha256": content_digest,
                },
            )

        def observe_object(self, object_key: str) -> ObjectStorageObservation:
            return ObjectStorageObservation(object_key=object_key, exists=False)

        def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
            raise NotImplementedError

        def presigned_get(self, object_key: str, *, ttl: Any) -> str:
            raise NotImplementedError

        def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
            del object_key, data, content_type

        def get_bytes(self, object_key: str) -> bytes:
            raise NotImplementedError

        def delete(self, object_key: str) -> None:
            raise NotImplementedError

    app = assemble_app(
        tmp_path,
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=_NullEvidenceStorage(),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="assemble-app-test-key",
    )
    try:
        paths = {p for p in app.openapi()["paths"] if p.startswith("/v1/")}
    finally:
        for journal in opened:
            journal.close()

    assert store_params, "create_app 시그니처에서 *_store 파라미터를 하나도 못 찾았다(테스트 결함)"
    assert paths, "assemble_app 이 어떤 /v1 경로도 장착하지 않았다"
    external_base = (
        "/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
    )
    assert {
        external_base,
        external_base + "/{submission_ref}/revisions/{revision}",
        external_base + "/{submission_ref}/revisions/{revision}/upload-grants",
        external_base + "/{submission_ref}/revisions/{revision}/seal",
    } <= paths

    # 핵심 대조 — assemble_app 이 create_app 에 실제로 넘긴 kwargs 이름과 시그니처의
    # *_store 파라미터 이름 집합의 차집합. 여기가 비지 않으면 새 store 파라미터를
    # create_app 에 추가하고 assemble_app 을 안 고쳐도 이 테스트가 조용히 통과하던
    # 사각지대가 다시 열린 것이다.
    missing = store_params - set(captured_kwargs)
    assert not missing, (
        f"assemble_app 이 create_app 의 store 파라미터를 넘기지 않는다: {sorted(missing)} "
        "— assemble_app 이 evidence_storage 를 받았으므로 조건부 store 도 전부 채워져야 한다"
    )


# ── 5. /ready — 봉인 원장이 있으면 503 ──────────────────────────────────────


def test_ready_is_200_when_nothing_sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_env(monkeypatch, _valid_env(tmp_path))
    from ksi_core.production import build_production_app

    app = build_production_app()
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_ready_is_503_when_a_journal_is_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """opened 원장 하나를 append 실패로 봉인시키면 /ready 가 503 이다.

    봉인 유발 관용구는 test_durable_journal.py::test_write_failure_seals_and_rejects_
    subsequent_appends 를 그대로 재사용한다(``_WRITE`` 모듈 참조를 예외로 대체).
    production 이 여는 원장도 ``assemble_app`` 이 연 것과 동일 클래스(``DurableJournal``)
    이므로, ``assemble_app`` 을 직접 불러 조립한 앱으로 확인하면 production 경로의
    ``/ready`` 배선(같은 함수)을 그대로 검증한 것과 같다.
    """
    from ksi_core import durable_journal as durable_journal_module

    def broken_write(_fd: int, _data: Any) -> int:
        raise OSError("disk full (주입 실패)")

    from ksi_core.app_assembly import assemble_app as _assemble_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / "ready-seal" / name)
        opened.append(journal)
        return journal

    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"y").hexdigest(),
                principal=Principal(
                    principal_id="op-2",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    seal_app = _assemble_app(
        tmp_path / "ready-seal",
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=None,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="ready-seal-test-key",
    )
    try:
        client = TestClient(seal_app)
        assert client.get("/ready").status_code == 200

        monkeypatch.setattr(durable_journal_module, "_WRITE", broken_write)
        with pytest.raises(Exception):  # noqa: B017, PT011 -- JournalSealedError, 원인만 필요
            opened[0].append({"n": 0})
        monkeypatch.undo()

        assert opened[0].sealed_reason is not None
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["ready"] is False
    finally:
        for journal in opened:
            journal.close()


def test_ready_is_503_when_edge_sync_store_is_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``EdgeSyncStore`` 봉인도 ``/ready`` 에 반영된다(P0-1 회귀 고정).

    수정 전에는 ``EdgeSyncStore`` 가 ``sealed_reason`` property 를 노출하지
    않아 ``app_assembly.ready()`` 의 ``getattr(j, "sealed_reason", None)`` 이
    기본값 ``None`` 에 걸렸다 — 이 store 가 봉인돼도 ``/ready`` 는 계속 200 을
    냈다(edge-sync 수신 전부가 503 인데 오케스트레이터는 정상으로 오판).
    """
    from ksi_core.app_assembly import assemble_app as _assemble_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / "ready-seal-edge" / name)
        opened.append(journal)
        return journal

    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"z").hexdigest(),
                principal=Principal(
                    principal_id="op-3",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    seal_app = _assemble_app(
        tmp_path / "ready-seal-edge",
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=None,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="ready-seal-edge-test-key",
    )
    try:
        client = TestClient(seal_app)
        assert client.get("/ready").status_code == 200

        edge_sync_store = next(o for o in opened if isinstance(o, EdgeSyncStore))
        # close() 는 EdgeSyncStore.close() 문서화대로 sealed_reason 을 "closed"
        # 로 남긴다 — DurableJournal 과 동일한 봉인 의미론(durable_journal.py:396
        # 대칭)이므로, append 실패를 재현하지 않고도 봉인 상태를 만들 수 있다.
        edge_sync_store.close()

        assert edge_sync_store.sealed_reason is not None
        response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["sealedCount"] >= 1
    finally:
        # close() 는 두 원장 타입 모두 멱등이다 — 이미 닫힌 edge_sync_store 도
        # 안전하게 다시 닫을 수 있다(위 close() 문서 참조).
        for journal in opened:
            journal.close()
