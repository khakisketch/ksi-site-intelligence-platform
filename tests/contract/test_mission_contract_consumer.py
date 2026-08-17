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
    ActivationRefusal,
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


# ── rollback·견고성 회귀 (2026-08-14 독립 반증에서 실측 재현된 구멍) ──────────


def _contract_with(
    *,
    not_before: str,
    reserve_percent: int,
    max_altitude_m: float,
    mission_id: str = "mission-001",
) -> dict[str, Any]:
    """같은 임무의 다른 발급본 — validity.notBefore 와 안전 항목만 달리한다."""
    contract = _unsigned_contract(mission_id)
    contract["validity"]["notBefore"] = not_before
    contract["policies"]["batteryPolicy"]["defaultReservePercent"] = reserve_percent
    contract["flightEnvelope"]["maxAltitudeM"] = max_altitude_m
    return contract


def test_older_still_signed_contract_cannot_roll_back_active_policy(tmp_path: Path) -> None:
    """[high-risk regression] 서명이 살아있는 **이전 발급본**으로 되돌릴 수 없다.

    Core 가 임무 중 정책을 조여 재발급해도 이전 계약은 자기 validity 창이 끝나기
    전까지 암호학적으로 유효하다. 그것만으로 활성화를 허용하면 배터리 예비량·고도
    상한 같은 안전 항목이 조용히 되돌아간다(2026-08-14 실측: 40%→10%, 60m→120m).
    """
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"

    newer = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=40, max_altitude_m=60.0
    )
    _write_candidate(candidate, sign_contract(newer, key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated
    active_bytes = consumer.active_path.read_bytes()

    older = _contract_with(
        not_before="2026-07-25T00:00:00Z", reserve_percent=10, max_altitude_m=120.0
    )
    _write_candidate(candidate, sign_contract(older, key, "core-1"))
    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert not receipt.activated
    assert receipt.verdict is ActivationRefusal.SUPERSEDED_CONTRACT
    # 활성 파일이 바이트 단위로 그대로여야 한다 — 되돌림이 부분적으로도 없어야 한다.
    assert consumer.active_path.read_bytes() == active_bytes
    active = consumer.load_active(now=_IN_WINDOW)
    assert active.is_valid and active.model is not None
    assert active.model.policies.battery_policy.default_reserve_percent == 40
    assert active.model.flight_envelope.max_altitude_m == 60.0


def test_newer_reissue_and_same_contract_reactivation_still_activate(tmp_path: Path) -> None:
    """rollback 방어가 정상 재발급·동일 계약 재활성화를 막지 않는다."""
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"

    first = _contract_with(
        not_before="2026-07-25T00:00:00Z", reserve_percent=30, max_altitude_m=120.0
    )
    signed_first = sign_contract(first, key, "core-1")
    _write_candidate(candidate, signed_first)
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    # 같은 계약 재활성화(동일 digest) — 멱등하게 통과한다.
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    # 더 나중에 발급된 계약 — 통과해야 한다.
    newer = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=40, max_altitude_m=60.0
    )
    _write_candidate(candidate, sign_contract(newer, key, "core-1"))
    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert receipt.activated
    assert receipt.verdict is SignatureVerdict.VALID
    active = consumer.load_active(now=_IN_WINDOW)
    assert active.model is not None
    assert active.model.policies.battery_policy.default_reserve_percent == 40


def test_same_not_before_weaker_contract_cannot_replace_active(tmp_path: Path) -> None:
    """[high-risk regression] ``notBefore`` 가 **같은** 다른 내용의 계약은 거부한다.

    notBefore 가 같으면 어느 쪽이 나중 발급본인지 가릴 근거가 아예 없다. 그 상태에서
    통과시키면 예비량·고도 상한을 되돌리는 계약이 순서 판정을 우회한다(risk
    ``mission-contract-no-issuance-ordering-field`` 가 지목한 구멍). 순서 근거가
    없으면 fail-closed 로 거부한다.
    """
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"

    active_contract = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=40, max_altitude_m=60.0
    )
    _write_candidate(candidate, sign_contract(active_contract, key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated
    active_bytes = consumer.active_path.read_bytes()

    # notBefore 만 같고 안전 항목이 느슨해진 계약.
    weaker = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=10, max_altitude_m=120.0
    )
    _write_candidate(candidate, sign_contract(weaker, key, "core-1"))
    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert not receipt.activated
    assert receipt.verdict is ActivationRefusal.SUPERSEDED_CONTRACT
    assert consumer.active_path.read_bytes() == active_bytes
    active = consumer.load_active(now=_IN_WINDOW)
    assert active.is_valid and active.model is not None
    assert active.model.policies.battery_policy.default_reserve_percent == 40
    assert active.model.flight_envelope.max_altitude_m == 60.0


def test_same_not_before_identical_contract_reactivation_still_activates(
    tmp_path: Path,
) -> None:
    """동일 계약 재활성화는 순서 판정 대상이 아니다 — 엄격화 후에도 멱등 통과한다.

    digest 동일성 판정이 notBefore 비교보다 **앞에** 있어야 성립한다.
    """
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"

    contract = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=40, max_altitude_m=60.0
    )
    signed = sign_contract(contract, key, "core-1")
    _write_candidate(candidate, signed)
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)
    assert receipt.activated
    assert receipt.verdict is SignatureVerdict.VALID


def test_other_mission_contract_is_not_blocked_by_rollback_guard(tmp_path: Path) -> None:
    """다른 임무의 계약은 순서를 비교할 공통 축이 없다 — 막지 않는다."""
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"

    active_first = _contract_with(
        not_before="2026-07-25T06:00:00Z", reserve_percent=40, max_altitude_m=60.0
    )
    _write_candidate(candidate, sign_contract(active_first, key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    other = _contract_with(
        not_before="2026-07-25T00:00:00Z",
        reserve_percent=10,
        max_altitude_m=120.0,
        mission_id="mission-002",
    )
    _write_candidate(candidate, sign_contract(other, key, "core-1"))
    receipt = consumer.activate_file(candidate, now=_IN_WINDOW)

    assert receipt.activated
    assert receipt.mission_id == "mission-002"


def test_deeply_nested_candidate_is_refused_not_crashed(tmp_path: Path) -> None:
    """[regression] 깊게 중첩된 JSON 은 typed 거부여야 한다 — 프로세스가 죽으면 안 된다.

    CPython json 디코더는 재귀식이라 크기 상한 안에서도 RecursionError 를 던진다.
    RuntimeError 계열이라 기존 except 에 걸리지 않아, 후보 파일 하나로 소비자를
    크래시 루프에 빠뜨릴 수 있었다.
    """
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"
    depth = 200_000
    candidate.write_bytes(b"[" * depth + b"]" * depth)

    with pytest.raises(ContractInputError, match="중첩"):
        consumer.activate_file(candidate, now=_IN_WINDOW)
    assert not consumer.active_path.exists()


def test_symlinked_active_contract_is_refused_on_read(tmp_path: Path) -> None:
    """읽기 경로도 쓰기 경로와 같이 symlink 를 거부한다(방어 비대칭 제거)."""
    key = Ed25519PrivateKey.generate()
    consumer = _consumer(tmp_path, key)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, sign_contract(_unsigned_contract(), key, "core-1"))
    assert consumer.activate_file(candidate, now=_IN_WINDOW).activated

    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(consumer.active_path.read_bytes())
    consumer.active_path.unlink()
    consumer.active_path.symlink_to(elsewhere)

    loaded = consumer.load_active(now=_IN_WINDOW)
    assert not loaded.is_valid
    assert loaded.verdict is SignatureVerdict.MALFORMED_CONTRACT
    assert loaded.detail is not None and "symlink" in loaded.detail
