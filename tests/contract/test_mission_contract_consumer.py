"""Mission Contract 생산 소비자 계약 (INV-011).

검증 라이브러리 존재가 아니라, 실행 후보가 실제로 ``load_verified_contract``를
통과한 뒤에만 활성 상태로 들어가며 실패 후보는 기존 로컬 계약을 보존함을 고정한다.
"""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_mission_contracts.consumer import (
    ContractInputError,
    MissionContractConsumer,
    VerificationKeyError,
    load_verification_keys,
    main,
)
from ksi_mission_contracts.signing import KeyRegistry, SignatureVerdict, sign_contract

_IN_WINDOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def _unsigned_contract(mission_id: str = "mission-001") -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "missionId": mission_id,
        "siteId": "site-001",
        "missionType": "UNIFIED_SITE_SURVEY",
        "validity": {
            "notBefore": "2026-07-25T00:00:00Z",
            "notAfter": "2026-07-26T00:00:00Z",
        },
        "siteFrame": {
            "crs": "EPSG:5186",
            "verticalDatum": "KNGeoid2018",
            "unit": "meter",
            "transformVersion": "1.0.0",
        },
        "flightEnvelope": {
            "allowedVolumes": ["vol-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
        },
        "objectives": ["현장 외곽 전체 커버리지 확보"],
        "policies": {
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": 0.97,
            },
            "communicationLossPolicy": {
                "serverLink": "CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
                "rcCommandLink": "DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
            },
            "batteryPolicy": {
                "mode": "RETURN_ENERGY_PLUS_RESERVE",
                "defaultReservePercent": 30,
            },
            "unknownObstaclePolicy": {
                "initialAction": "SLOW",
                "unresolvedAction": "RETREAT",
            },
            "evidencePolicy": {
                "candidatePrePostSeconds": 3,
                "highPrePostSeconds": 5,
                "criticalPrePostSeconds": 10,
            },
        },
        "artifacts": {"calibrationProfileId": "cal-1"},
    }


def _write_candidate(path: Path, contract: dict[str, Any]) -> bytes:
    raw = json.dumps(contract, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _write_public_registry(
    keys_dir: Path, key: Ed25519PrivateKey, *, status: str = "ACTIVE"
) -> None:
    keys_dir.mkdir()
    (keys_dir / "keys.json").write_text(
        json.dumps({"keys": [{"keyId": "core-1", "status": status}]}),
        encoding="utf-8",
    )
    (keys_dir / "core-1.public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _consumer(tmp_path: Path, key: Ed25519PrivateKey) -> MissionContractConsumer:
    registry = KeyRegistry()
    registry.register("core-1", key.public_key())
    return MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")


def test_valid_candidate_is_verified_then_activated_atomically(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    candidate = tmp_path / "candidate.json"
    raw = _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    consumer = _consumer(tmp_path, key)

    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert receipt.activated
    assert receipt.verdict is SignatureVerdict.VALID
    assert receipt.mission_id == "mission-001"
    assert receipt.contract_digest is not None
    assert consumer.active_path.read_bytes() == raw
    assert stat.S_IMODE(consumer.active_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(consumer.active_path.stat().st_mode) == 0o600
    assert consumer.load_active(now=_IN_WINDOW).is_valid


def test_invalid_candidate_never_replaces_previous_active_contract(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    candidate = tmp_path / "candidate.json"
    original = _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    consumer = _consumer(tmp_path, key)
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    tampered = sign_contract(_unsigned_contract("mission-next"), key, "core-1")
    tampered["missionId"] = "mission-tampered-after-signing"
    _write_candidate(candidate, tampered)
    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert not receipt.activated
    assert receipt.verdict is SignatureVerdict.DIGEST_MISMATCH
    assert consumer.active_path.read_bytes() == original
    active = consumer.load_active(now=_IN_WINDOW)
    assert active.is_valid and active.model is not None
    assert active.model.mission_id == "mission-001"


def test_active_contract_is_reverified_for_ttl_and_revocation(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    registry = KeyRegistry()
    registry.register("core-1", key.public_key())
    consumer = MissionContractConsumer(registry=registry, state_dir=tmp_path / "state")
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    expired = consumer.load_active(now=datetime(2026, 7, 27, tzinfo=UTC))
    assert expired.verdict is SignatureVerdict.EXPIRED_CONTRACT

    registry.revoke("core-1")
    revoked = consumer.load_active(now=_IN_WINDOW)
    assert revoked.verdict is SignatureVerdict.REVOKED_KEY


def test_duplicate_json_keys_are_refused_without_touching_active(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"
    candidate.write_text('{"schemaVersion":"1.2","schemaVersion":"1.2"}', encoding="utf-8")

    with pytest.raises(ContractInputError, match="중복 없는"):
        consumer.activate_file(candidate, now=_IN_WINDOW)
    assert not consumer.active_path.exists()


def test_symlink_active_path_is_refused(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    consumer.active_path.parent.mkdir(mode=0o700, parents=True)
    target = tmp_path / "outside.json"
    target.write_text("outside", encoding="utf-8")
    consumer.active_path.symlink_to(target)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))

    with pytest.raises(ContractInputError, match="symlink"):
        consumer.activate_file(candidate, now=_IN_WINDOW)
    assert target.read_text(encoding="utf-8") == "outside"


def test_group_or_other_accessible_state_directory_is_refused(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    consumer.active_path.parent.mkdir(mode=0o700, parents=True)
    consumer.active_path.parent.chmod(0o770)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))

    with pytest.raises(ContractInputError, match="group/other"):
        consumer.activate_file(candidate, now=_IN_WINDOW)
    assert not consumer.active_path.exists()


def test_symlink_state_directory_is_refused(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    trusted_target = tmp_path / "outside-state"
    trusted_target.mkdir(mode=0o700)
    state_link = tmp_path / "state"
    state_link.symlink_to(trusted_target, target_is_directory=True)
    registry = KeyRegistry()
    registry.register("core-1", key.public_key())
    consumer = MissionContractConsumer(registry=registry, state_dir=state_link)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))

    with pytest.raises(ContractInputError, match="상태 디렉터리가 symlink"):
        consumer.activate_file(candidate, now=_IN_WINDOW)
    assert list(trusted_target.iterdir()) == []


def test_active_load_refuses_state_directory_permission_drift(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated
    consumer.active_path.parent.chmod(0o750)

    with pytest.raises(ContractInputError, match="group/other"):
        consumer.load_active(now=_IN_WINDOW)


def test_public_only_registry_loads_and_preserves_revoked_state(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    keys_dir = tmp_path / "keys"
    _write_public_registry(keys_dir, key, status="REVOKED")

    registry = load_verification_keys(keys_dir)

    record = registry.get("core-1")
    assert record is not None and record.status.value == "REVOKED"
    assert not (keys_dir / "core-1.private.pem").exists(), "소비자는 개인키를 요구하면 안 된다"


def test_public_registry_rejects_path_escaping_key_id(tmp_path: Path) -> None:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "keys.json").write_text(
        json.dumps({"keys": [{"keyId": "../../private"}]}),
        encoding="utf-8",
    )

    with pytest.raises(VerificationKeyError, match="경로-안전하지 않은"):
        load_verification_keys(keys_dir)


def test_cli_activates_using_public_keys_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = Ed25519PrivateKey.generate()
    keys_dir = tmp_path / "keys"
    _write_public_registry(keys_dir, key)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    state_dir = tmp_path / "state"

    exit_code = main(
        [
            "--keys-dir",
            str(keys_dir),
            "--state-dir",
            str(state_dir),
            "--now",
            _IN_WINDOW.isoformat(),
            "activate",
            str(candidate),
        ]
    )

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["verdict"] == "VALID"
    assert body["activated"] is True
    assert body["missionId"] == "mission-001"

