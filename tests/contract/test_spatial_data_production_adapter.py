"""Protected production spatial-data adapter — disabled by default (item 4).

Absent ``KSI_CORE_SPATIAL_DATA_CONFIG_FILE`` keeps the lane unmounted. A
present configuration is owner-protected, signature-verified and identity- and
policy-bound before any journal or S3 side effect; rights come from an
operator-provisioned file; retired/expired authority blocks work while
retained history still replays.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.composition.spatial_data_production import (
    SpatialDataCleanupLoop,
    SpatialDataCoreConfigError,
    SpatialDataProductionCurrentness,
    build_spatial_data_production,
    load_spatial_data_core_config,
    load_spatial_data_rights_file,
    spatial_data_source_key_resolver,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.grants import SpatialDataGrantStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from spatial_data_fixture import (
    NOW,
    make_activation,
    make_grant,
    make_policy,
    make_revocation,
    make_runtime,
)
from spatial_data_source_fixture import source_identity, source_resolver, source_stores

ORG = "organization-1"
WORKER_ID = "data-worker-1"
OPERATOR_ID = "operator-1"
ISSUER = "https://issuer.example"

Policy = Any


def _worker_record() -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"worker-token").hexdigest(),
        principal=Principal(
            principal_id=WORKER_ID,
            kind=PrincipalKind.SPATIAL_DATA_WORKER,
            role=None,
            device_id=None,
            organization_id=ORG,
        ),
    )


def _operator_record() -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
        principal=Principal(
            principal_id=OPERATOR_ID,
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN,
            device_id=None,
            organization_id=ORG,
        ),
    )


def _authority(
    valid_from: datetime = NOW - timedelta(minutes=1),
    valid_until: datetime = NOW + timedelta(hours=1),
) -> tuple[Any, Any, Any, Any]:
    policy = make_policy(policy_id="production-adapter-test")
    runtime = make_runtime()
    activation = make_activation(
        organization_id=ORG,
        worker_principal_id=WORKER_ID,
        worker_instance_id="instance-1",
        policy_digest=policy.policy_digest,
        runtime_digest=runtime.runtime_digest,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return policy, runtime, activation, public


def _sign(key: Ed25519PrivateKey, activation: Any) -> str:
    return base64.b64encode(key.sign(activation.signing_bytes())).decode("ascii")


def _write_private(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> Path:
    path.parent.chmod(0o700)
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def _config_payload(
    tmp_path: Path,
    *,
    valid_from: datetime = NOW - timedelta(minutes=1),
    valid_until: datetime = NOW + timedelta(hours=1),
    revoked: tuple[str, ...] = (),
    sign_mismatch: bool = False,
) -> tuple[dict[str, Any], Any, Any]:
    policy, runtime, activation, public = _authority(valid_from=valid_from, valid_until=valid_until)
    key = Ed25519PrivateKey.generate()
    if sign_mismatch:
        signature = base64.b64encode(key.sign(b"not-the-activation")).decode("ascii")
        trusted = public
    else:
        signature = _sign(key, activation)
        trusted = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    del public
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700, exist_ok=True)
    spool.chmod(0o700)
    grants_file = tmp_path / "rights.json"
    payload: dict[str, Any] = {
        "version": "spatial-data-core-config.v1",
        "processingLocation": "site_onprem",
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "runtime": runtime.model_dump(by_alias=True, mode="json"),
        "activation": activation.model_dump(by_alias=True, mode="json"),
        "activationSignature": signature,
        "trustedPublicKey": base64.b64encode(trusted).decode("ascii"),
        "revokedActivationDigests": list(revoked),
        "spoolRoot": str(spool),
        "operationTimeoutSeconds": 5.0,
        "grantsFile": str(grants_file),
        "cleanupIntervalSeconds": 300.0,
    }
    return payload, policy, activation


def _grant(policy: Any, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "organization_id": ORG,
        "beneficiary_principal_id": OPERATOR_ID,
        "site_id": "site-1",
        "work_area_id": "area-1",
        "allowed_bounds": (0, 0, 2, 2),
        "observed_crs_digest": "sha256:" + "c" * 64,
        "policy_digest": policy.policy_digest,
        "valid_from": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(hours=1),
    }
    payload.update(overrides)
    return make_grant(**payload)


def _load_config(tmp_path: Path, **kwargs: Any) -> tuple[Any, Any, Path]:
    payload, policy, _activation = _config_payload(tmp_path, **kwargs)
    config_path = tmp_path / "config.json"
    _write_private(config_path, payload)
    config = load_spatial_data_core_config(
        config_path, principal_records=[_worker_record(), _operator_record()]
    )
    _write_private(
        Path(payload["grantsFile"]),
        {"version": "spatial-data-rights.v1", "grants": [], "revocations": []},
    )
    return config, policy, config_path


def _production_env(tmp_path: Path, *, config_path: Path | None) -> dict[str, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "tokenSha256": _worker_record().token_sha256,
            "principalId": WORKER_ID,
            "kind": "SPATIAL_DATA_WORKER",
            "role": None,
            "deviceId": None,
            "organizationId": ORG,
        },
        {
            "tokenSha256": _operator_record().token_sha256,
            "principalId": OPERATOR_ID,
            "kind": "OPERATOR",
            "role": "ADMIN",
            "deviceId": None,
            "organizationId": ORG,
        },
    ]
    env = {
        "KSI_CORE_DATA_DIR": str(data_dir),
        "KSI_CORE_S3_ENDPOINT": "http://127.0.0.1:9000",
        "KSI_CORE_S3_BUCKET": "platform-prod-evidence",
        "KSI_CORE_PRINCIPAL_TOKENS_JSON": json.dumps(records),
    }
    if config_path is not None:
        env["KSI_CORE_SPATIAL_DATA_CONFIG_FILE"] = str(config_path)
    return env


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_absent_configuration_keeps_the_lane_unmounted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    _apply_env(monkeypatch, _production_env(tmp_path, config_path=None))
    app = build_platform_production_app()
    assert getattr(app.state, "spatial_data", None) is None
    assert getattr(app.state, "spatial_data_cleanup", None) is None


def test_unprotected_configuration_fails_before_journals_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    payload, _policy, _activation = _config_payload(tmp_path)
    config_path = _write_private(tmp_path / "config.json", payload, mode=0o644)
    env = _production_env(tmp_path, config_path=config_path)
    _apply_env(monkeypatch, env)
    with pytest.raises(RuntimeError, match="spatial data"):
        build_platform_production_app()
    assert list(Path(env["KSI_CORE_DATA_DIR"]).glob("*.jsonl")) == []


def test_invalid_signature_fails_boot(tmp_path: Path) -> None:
    payload, _policy, _activation = _config_payload(tmp_path, sign_mismatch=True)
    config_path = _write_private(tmp_path / "config.json", payload)
    with pytest.raises(SpatialDataCoreConfigError):
        load_spatial_data_core_config(
            config_path, principal_records=[_worker_record(), _operator_record()]
        )


def test_worker_identity_must_be_registered(tmp_path: Path) -> None:
    payload, _policy, _activation = _config_payload(tmp_path)
    config_path = _write_private(tmp_path / "config.json", payload)
    with pytest.raises(SpatialDataCoreConfigError):
        load_spatial_data_core_config(config_path, principal_records=[_operator_record()])


def test_revoked_activation_digest_fails_boot(tmp_path: Path) -> None:
    payload, _policy, activation = _config_payload(tmp_path)
    assert activation.activation_digest is not None
    payload["revokedActivationDigests"] = [activation.activation_digest]
    config_path = _write_private(tmp_path / "config.json", payload)
    with pytest.raises(SpatialDataCoreConfigError):
        load_spatial_data_core_config(
            config_path, principal_records=[_worker_record(), _operator_record()]
        )


def test_expired_authentic_activation_loads_but_is_not_current(tmp_path: Path) -> None:
    config, policy, _path = _load_config(
        tmp_path,
        valid_from=NOW - timedelta(hours=2),
        valid_until=NOW - timedelta(minutes=1),
    )
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    currentness = SpatialDataProductionCurrentness(
        coordinator=coordinator,
        policy=config.policy,
        runtime=config.runtime,
        activation=config.activation,
        revoked_activation_digests=tuple(config.revoked_activation_digests),
        auth_registry=AuthRegistry([_worker_record(), _operator_record()]),
        oidc_subject_registry=None,
    )
    assert currentness.is_current(
        policy=config.policy,
        runtime=config.runtime,
        activation=config.activation,
        now=NOW,
    ) is False
    assert policy.policy_digest == config.policy.policy_digest


def test_spatial_data_mcp_client_scope_registration_and_rejection(tmp_path: Path) -> None:
    from ksi_core.composition.runtime_config import _parse_principal_tokens

    records = _parse_principal_tokens(
        json.dumps(
            [
                {
                    "tokenSha256": hashlib.sha256(b"mcp-rotation").hexdigest(),
                    "principalId": "mcp-client-a",
                    "kind": "SPATIAL_DATA_MCP_CLIENT",
                    "role": None,
                    "deviceId": None,
                    "organizationId": ORG,
                    "allowedSiteIds": ["site-1"],
                    "allowedWorkAreaIds": ["area-1"],
                }
            ]
        )
    )
    principal = records[0].principal
    assert principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT
    assert principal.allowed_site_ids == frozenset({"site-1"})
    assert principal.allowed_work_area_ids == frozenset({"area-1"})
    with pytest.raises(RuntimeError, match="only valid"):
        _parse_principal_tokens(
            json.dumps(
                [
                    {
                        "tokenSha256": hashlib.sha256(b"opaque-scope").hexdigest(),
                        "principalId": "opaque-scope",
                        "kind": "OPERATOR",
                        "role": "ADMIN",
                        "deviceId": None,
                        "organizationId": ORG,
                        "allowedSiteIds": ["site-1"],
                        "allowedWorkAreaIds": ["area-1"],
                    }
                ]
            )
        )


def test_worker_identity_allows_rotating_duplicate_digests(tmp_path: Path) -> None:
    payload, _policy, _activation = _config_payload(tmp_path)
    config_path = _write_private(tmp_path / "config.json", payload)
    rotated = PrincipalTokenRecord(
        token_sha256=hashlib.sha256(b"worker-token-next").hexdigest(),
        principal=_worker_record().principal,
    )
    config = load_spatial_data_core_config(
        config_path, principal_records=[_worker_record(), rotated, _operator_record()]
    )
    assert config.activation.worker_principal_id == WORKER_ID


def test_rights_must_bind_current_policy_and_resolvable_beneficiary(tmp_path: Path) -> None:
    config, _policy, _path = _load_config(tmp_path)
    other_policy = make_policy(policy_id="production-adapter-other")

    wrong_policy = make_grant(
        organization_id=ORG,
        beneficiary_principal_id=OPERATOR_ID,
        site_id="site-1",
        work_area_id="area-1",
        allowed_bounds=(0, 0, 2, 2),
        observed_crs_digest="sha256:" + "c" * 64,
        policy_digest=other_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    _write_private(
        config.grants_file_path,
        {
            "version": "spatial-data-rights.v1",
            "grants": [wrong_policy.model_dump(by_alias=True, mode="json")],
            "revocations": [],
        },
    )
    with pytest.raises(SpatialDataCoreConfigError):
        load_spatial_data_rights_file(
            config, principal_records=[_worker_record(), _operator_record()],
            oidc_subject_registry=None,
        )

    unknown = make_grant(
        organization_id=ORG,
        beneficiary_principal_id="stranger",
        site_id="site-1",
        work_area_id="area-1",
        allowed_bounds=(0, 0, 2, 2),
        observed_crs_digest="sha256:" + "c" * 64,
        policy_digest=config.policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    _write_private(
        config.grants_file_path,
        {
            "version": "spatial-data-rights.v1",
            "grants": [unknown.model_dump(by_alias=True, mode="json")],
            "revocations": [],
        },
    )
    with pytest.raises(SpatialDataCoreConfigError):
        load_spatial_data_rights_file(
            config, principal_records=[_worker_record(), _operator_record()],
            oidc_subject_registry=None,
        )


def test_protected_boot_mounts_lane_imports_rights_and_starts_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ksi_core.composition.platform_production import build_platform_production_app

    payload, policy, _activation = _config_payload(tmp_path)
    grant = _grant(policy)
    revocation = make_revocation(
        grant_id=grant.grant_id,
        revision=grant.revision,
        organization_id=ORG,
        grant_digest=grant.grant_digest,
        revoked_at=NOW,
    )
    config_path = _write_private(tmp_path / "config.json", payload)
    _write_private(
        Path(payload["grantsFile"]),
        {
            "version": "spatial-data-rights.v1",
            "grants": [grant.model_dump(by_alias=True, mode="json")],
            "revocations": [revocation.model_dump(by_alias=True, mode="json")],
        },
    )
    env = _production_env(tmp_path, config_path=config_path)
    _apply_env(monkeypatch, env)
    app = build_platform_production_app()
    try:
        wiring = app.state.spatial_data
        assert wiring is not None
        assert wiring.jobs.policy.policy_digest == policy.policy_digest
        assert wiring.downloads is not None
        journal_text = (Path(env["KSI_CORE_DATA_DIR"]) / "spatial-data-grants.jsonl").read_text(
            encoding="utf-8"
        )
        assert "spatial-data-grant.provisioned.v1" in journal_text
        assert "spatial-data-grant.revoked.v1" in journal_text
        assert wiring.grants.is_revoked(
            organization_id=ORG, grant_id=grant.grant_id, revision=grant.revision
        )
        cleanup = app.state.spatial_data_cleanup
        assert cleanup.running is True
        cleanup.stop()
        assert cleanup.running is False
    finally:
        cleanup = getattr(app.state, "spatial_data_cleanup", None)
        if cleanup is not None:
            cleanup.stop()


def test_import_rights_is_idempotent_and_applies_revocation(tmp_path: Path) -> None:
    config, policy, _path = _load_config(tmp_path)
    grant = _grant(policy)
    revocation = make_revocation(
        grant_id=grant.grant_id,
        revision=grant.revision,
        organization_id=ORG,
        grant_digest=grant.grant_digest,
        revoked_at=NOW,
    )
    rights_path = tmp_path / "rights-import.json"
    _write_private(
        rights_path,
        {
            "version": "spatial-data-rights.v1",
            "grants": [grant.model_dump(by_alias=True, mode="json")],
            "revocations": [revocation.model_dump(by_alias=True, mode="json")],
        },
    )
    config = config.model_copy(update={"grants_file": str(rights_path)})
    rights = load_spatial_data_rights_file(
        config,
        principal_records=[_worker_record(), _operator_record()],
        oidc_subject_registry=None,
    )
    assembly = build_spatial_data_production(
        config,
        rights,
        auth_registry=AuthRegistry([_worker_record(), _operator_record()]),
        oidc_subject_registry=None,
        bucket="platform-prod-evidence",
        endpoint_url="http://127.0.0.1:9000",
    )
    assert assembly.import_rights is not None
    store = SpatialDataGrantStore(
        DurableJournal(tmp_path / "grants.jsonl"),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    assembly.import_rights(store)
    assembly.import_rights(store)
    records = (tmp_path / "grants.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum("provisioned" in line for line in records) == 1
    assert sum("revoked" in line for line in records) == 1
    assert store.is_revoked(
        organization_id=ORG, grant_id=grant.grant_id, revision=grant.revision
    )


def test_currentness_resolves_opaque_and_oidc_identities(tmp_path: Path) -> None:
    config, _policy, _path = _load_config(tmp_path)
    registry = OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v2",
            "subjects": [
                {
                    "issuer": ISSUER,
                    "subject": "subject-1",
                    "principalId": "oidc-operator",
                    "organizationId": ORG,
                    "role": "ADMIN",
                    "status": "ACTIVE",
                    "allowedSiteIds": None,
                    "allowedWorkAreaIds": None,
                    "capabilities": [],
                },
                {
                    "issuer": ISSUER,
                    "subject": "subject-2",
                    "principalId": "oidc-revoked",
                    "organizationId": ORG,
                    "role": "ADMIN",
                    "status": "REVOKED",
                    "allowedSiteIds": None,
                    "allowedWorkAreaIds": None,
                    "capabilities": [],
                },
            ],
        },
        expected_issuer=ISSUER,
    )
    currentness = SpatialDataProductionCurrentness(
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
        policy=config.policy,
        runtime=config.runtime,
        activation=config.activation,
        revoked_activation_digests=(),
        auth_registry=AuthRegistry([_worker_record(), _operator_record()]),
        oidc_subject_registry=registry,
    )
    now = datetime.now(UTC)
    assert currentness.resolve_requester(
        principal_id=OPERATOR_ID, organization_id=ORG, now=now
    ) is not None
    assert currentness.resolve_requester(
        principal_id="oidc-operator", organization_id=ORG, now=now
    ) is not None
    assert currentness.resolve_requester(
        principal_id="oidc-revoked", organization_id=ORG, now=now
    ) is None
    assert currentness.resolve_requester(
        principal_id="unknown", organization_id=ORG, now=now
    ) is None
    assert currentness.resolve_requester(
        principal_id=OPERATOR_ID, organization_id="other-org", now=now
    ) is None
    assert currentness.is_current(
        policy=config.policy,
        runtime=config.runtime,
        activation=config.activation,
        now=NOW,
    ) is True
    other_policy = make_policy(policy_id="production-adapter-other")
    assert currentness.is_current(
        policy=other_policy,
        runtime=config.runtime,
        activation=config.activation,
        now=NOW,
    ) is False


def test_source_key_resolution_requires_exact_manifest_entry(tmp_path: Path) -> None:
    graph = source_stores(tmp_path / "stores")
    graph.data_policy = make_policy()
    graph.sources = source_resolver(graph)
    source = graph.sources.resolve(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=source_identity(graph),
        principal=graph.principal,
    )
    resolver = spatial_data_source_key_resolver(graph.reconstruction)
    key = resolver(source)
    revision = graph.reconstruction.resolve_sealed_subject(source.sealed_subject)
    assert revision is not None and revision.manifest is not None
    entry = next(
        item for item in revision.manifest.entries if item.artifact_id == source.artifact_id
    )
    assert key == entry.object_key
    with pytest.raises(SpatialDataDomainError):
        resolver(
            source.model_copy(
                update={
                    "observed_size_bytes": source.observed_size_bytes + 1,
                    "source_digest": None,
                }
            )
        )


def test_cleanup_loop_runs_and_stops() -> None:
    class Jobs:
        def __init__(self) -> None:
            self.calls = 0
            self.policy = SimpleNamespace(max_pending_records=4)

        def cleanup_pending(self, *, limit: int, now: datetime) -> tuple[()]:
            self.calls += 1
            return ()

    jobs = Jobs()
    audit = SimpleNamespace(policy=jobs.policy)
    loop = SpatialDataCleanupLoop(
        jobs=jobs, storage=object(), audit=audit, interval_seconds=0.05
    )
    assert loop.run_once() == 0
    loop.start()
    deadline = time.monotonic() + 5.0
    while jobs.calls < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    loop.stop()
    assert loop.running is False
    assert jobs.calls >= 2
    with pytest.raises(ValueError):
        SpatialDataCleanupLoop(jobs=jobs, storage=object(), audit=audit, interval_seconds=0)
