"""Protected production opt-in for the optional saved-line profile lane."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_spatial_data_production_adapter as spatial_fixture
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from ksi_core.domains.external.delivery.surface_profile_jobs import SurfaceProfileDomainError
from surface_profile_job_fixture import profile_policy, profile_runtime

PROFILE_WORKER_ID = "surface-profile-worker-1"
PROFILE_WORKER_TOKEN = b"surface-profile-test-worker-token"


def _now() -> datetime:
    return datetime.now(UTC)


def _profile_worker_record() -> Any:
    from ksi_core.auth import Principal, PrincipalKind, PrincipalTokenRecord

    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(PROFILE_WORKER_TOKEN).hexdigest(),
        principal=Principal(
            principal_id=PROFILE_WORKER_ID,
            kind=PrincipalKind.SPATIAL_DATA_WORKER,
            role=None,
            device_id=None,
            organization_id=spatial_fixture.ORG,
        ),
    )


def _profile_payload(
    *,
    invalid_signature: bool = False,
    organization_id: str = spatial_fixture.ORG,
    worker_principal_id: str = PROFILE_WORKER_ID,
    worker_instance_id: str = "profile-instance-1",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> dict[str, Any]:
    from ksi_event_contracts.surface_profile_job import SurfaceProfileActivationV1

    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={
                "max_input_bytes": 1_000_000,
                "max_streamed_bytes": 1_000_000,
                "resource_envelope_digest": None,
            }
        )
        .sealed()
    )
    policy = profile_policy(resource_envelope=envelope)
    runtime = profile_runtime()
    activation = SurfaceProfileActivationV1(
        activation_id="production-profile-test",
        organization_id=organization_id,
        worker_principal_id=worker_principal_id,
        worker_instance_id=worker_instance_id,
        policy_digest=policy.policy_digest or "",
        runtime_digest=runtime.runtime_digest or "",
        trusted_endpoint_origins=("https://objects.invalid",),
        valid_from=valid_from or _now() - timedelta(minutes=1),
        valid_until=valid_until or _now() + timedelta(hours=1),
    ).sealed()
    key = Ed25519PrivateKey.generate()
    signed = (
        key.sign(b"invalid activation")
        if invalid_signature
        else key.sign(activation.signing_bytes())
    )
    return {
        "version": "surface-profile-core-config.v1",
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "runtime": runtime.model_dump(by_alias=True, mode="json"),
        "activation": activation.model_dump(by_alias=True, mode="json"),
        "activationSignature": base64.b64encode(signed).decode("ascii"),
        "trustedPublicKey": base64.b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode("ascii"),
        "revokedActivationDigests": [],
        "httpLimits": {
            "requestMaxBytes": 4096,
            "completeMaxBytes": 500_000,
            "timeoutSeconds": 1.0,
        },
    }


def _production_inputs(
    tmp_path: Path, *, profile_payload: dict[str, Any] | None = None
) -> tuple[Path, Path | None, dict[str, str]]:
    now = _now()
    native_payload, _, _ = spatial_fixture._config_payload(
        tmp_path,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
    )
    native_path = spatial_fixture._write_private(tmp_path / "spatial.json", native_payload)
    spatial_fixture._write_private(
        Path(native_payload["grantsFile"]),
        {"version": "spatial-data-rights.v1", "grants": [], "revocations": []},
    )
    profile_path = None
    if profile_payload is not None:
        profile_path = spatial_fixture._write_private(
            tmp_path / "surface-profile.json", profile_payload
        )
    env = spatial_fixture._production_env(tmp_path, config_path=native_path)
    if profile_path is not None:
        env["KSI_CORE_SURFACE_PROFILE_CONFIG_FILE"] = str(profile_path)
        principal = _profile_worker_record()
        records = json.loads(env["KSI_CORE_PRINCIPAL_TOKENS_JSON"])
        records.append(
            {
                "tokenSha256": principal.token_sha256,
                "principalId": principal.principal.principal_id,
                "kind": principal.principal.kind.value,
                "role": None,
                "deviceId": None,
                "organizationId": principal.principal.organization_id,
            }
        )
        env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(records)
    return native_path, profile_path, env


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    spatial_fixture._apply_env(monkeypatch, env)
    if "KSI_CORE_SURFACE_PROFILE_CONFIG_FILE" not in env:
        monkeypatch.delenv("KSI_CORE_SURFACE_PROFILE_CONFIG_FILE", raising=False)


def test_platform_production_keeps_profile_unmounted_without_its_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    _, _, env = _production_inputs(tmp_path)
    _apply_env(monkeypatch, env)
    app = build_platform_production_app()
    try:
        assert getattr(app.state, "surface_profile", None) is None
        assert not any("surface-profile" in path for path in app.openapi()["paths"])
    finally:
        app.state.spatial_data_cleanup.stop()


def test_production_factory_uses_one_signed_catalog_for_profile_comparisons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient
    from ksi_core.composition.platform_production import build_platform_production_app
    from test_external_profile_difference_signed_core_lifecycle import _signed_provider_files

    _, _, env = _production_inputs(tmp_path, profile_payload=_profile_payload())
    signer_dir = tmp_path / "comparison-authority"
    signer_dir.mkdir(mode=0o700)
    provider, workflow, _, _ = _signed_provider_files(signer_dir, now=_now().replace(microsecond=0))
    env["KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"] = str(provider)
    env["KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"] = str(workflow)
    _apply_env(monkeypatch, env)
    app = build_platform_production_app()
    with TestClient(app) as client:
        readiness = client.get("/ready/external-authority")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "PROVIDER_CONFIGURED"
        assert app.state.external_authority_provider.status()["businessEligible"] is False
        catalog = app.state.external_relative_volume_mapping_authority
        selected = app.state.external_use_evaluator._profile_difference_authority  # noqa: SLF001
        assert selected._catalog is catalog  # noqa: SLF001 -- exact normal-factory ownership
        assert selected.currentness_coordinator is app.state.external_authority_currentness
        assert app.state.surface_profile is not None


def test_profile_opt_in_requires_spatial_lane_before_opening_journals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = spatial_fixture._production_env(tmp_path, config_path=None)
    profile_path = spatial_fixture._write_private(
        tmp_path / "surface-profile.json", _profile_payload()
    )
    env["KSI_CORE_SURFACE_PROFILE_CONFIG_FILE"] = str(profile_path)
    _apply_env(monkeypatch, env)

    with pytest.raises(RuntimeError, match="requires the protected spatial data"):
        build_platform_production_app()
    assert list(data_dir.glob("*.jsonl")) == []


def test_profile_signature_failure_is_rejected_before_journal_or_s3_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core import evidence_s3
    from ksi_core.composition.platform_production import build_platform_production_app

    def reject_s3_creation(**_: Any) -> Any:
        pytest.fail("invalid profile authority must fail before S3 construction")

    monkeypatch.setattr(evidence_s3, "S3EvidenceStorage", reject_s3_creation)

    _, _, env = _production_inputs(
        tmp_path, profile_payload=_profile_payload(invalid_signature=True)
    )
    _apply_env(monkeypatch, env)
    with pytest.raises(RuntimeError, match="surface profile configuration is invalid"):
        build_platform_production_app()
    data_dir = Path(env["KSI_CORE_DATA_DIR"])
    assert list(data_dir.glob("*.jsonl")) == []


@pytest.mark.parametrize(
    "profile_payload",
    [
        _profile_payload(
            valid_from=datetime(2025, 12, 31, tzinfo=UTC),
            valid_until=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        _profile_payload(worker_principal_id="unregistered-worker"),
        _profile_payload(organization_id="another-organization"),
    ],
    ids=("expired", "unregistered-worker", "organization-mismatch"),
)
def test_profile_activation_out_of_scope_or_expired_fails_before_journal_or_s3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_payload: dict[str, Any],
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    _, _, env = _production_inputs(tmp_path, profile_payload=profile_payload)
    _apply_env(monkeypatch, env)
    with pytest.raises(RuntimeError, match="surface profile configuration is invalid"):
        build_platform_production_app()
    data_dir = Path(env["KSI_CORE_DATA_DIR"])
    assert list(data_dir.glob("*.jsonl")) == []


def test_signed_profile_factory_rechecks_revocation_for_workers_and_new_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    payload = _profile_payload()
    _, profile_path, env = _production_inputs(tmp_path, profile_payload=payload)
    assert profile_path is not None
    _apply_env(monkeypatch, env)
    app = build_platform_production_app()
    try:
        wiring = app.state.surface_profile
        assert wiring is not None
        assert any("surface-profile" in path for path in app.openapi()["paths"])
        principal = _profile_worker_record().principal
        now = _now()
        wiring.jobs.require_worker(worker=principal, instance_id="profile-instance-1", now=now)
        with pytest.raises(SurfaceProfileDomainError, match="PERMISSION_DENIED"):
            wiring.jobs.require_worker(worker=principal, instance_id="other-instance", now=now)
        with pytest.raises(SurfaceProfileDomainError, match="PERMISSION_DENIED"):
            wiring.authority.admit(
                site_id="site-1",
                work_area_id="area-1",
                request=None,
                principal=replace(
                    spatial_fixture._operator_record().principal,
                    organization_id="another-organization",
                ),
                policy=wiring.jobs.policy,
                now=now,
            )

        revoked = dict(payload)
        revoked["revokedActivationDigests"] = [payload["activation"]["activationDigest"]]
        spatial_fixture._write_private(profile_path, revoked)

        with pytest.raises(SurfaceProfileDomainError, match="PERMISSION_DENIED"):
            wiring.jobs.require_worker(
                worker=principal, instance_id="profile-instance-1", now=_now()
            )
        with pytest.raises(SurfaceProfileDomainError, match="POLICY_UNAVAILABLE"):
            wiring.authority.admit(
                site_id="site-1",
                work_area_id="area-1",
                request=None,
                principal=spatial_fixture._operator_record().principal,
                policy=wiring.jobs.policy,
                now=_now(),
            )
    finally:
        app.state.spatial_data_cleanup.stop()
