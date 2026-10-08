"""서명키 공급 계약 (ADR-KSI-010 §2).

키 공급이 조용히 잘못되면 발급된 계약이 **전부 검증 실패**하는데 그 사실이
발급 시점에는 드러나지 않는다. 그래서 여기 거부 사유는 전부 기동 거부다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.signing_keys import SigningKeyError, load_signing_keys
from ksi_mission_contracts.signing import KeyStatus


def _write_key(keys_dir: Path, key_id: str, *, private: bool = True) -> Ed25519PrivateKey:
    keys_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    (keys_dir / f"{key_id}.public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    if private:
        path = keys_dir / f"{key_id}.private.pem"
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)
    return key


def _manifest(keys_dir: Path, active: str, keys: list[dict[str, object]]) -> None:
    (keys_dir / "keys.json").write_text(
        json.dumps({"active": active, "keys": keys}), encoding="utf-8"
    )


def test_single_active_key_loads(tmp_path: Path) -> None:
    key = _write_key(tmp_path, "core-2026-08")
    _manifest(tmp_path, "core-2026-08", [{"keyId": "core-2026-08", "status": "ACTIVE"}])

    key_set = load_signing_keys(tmp_path)
    assert key_set.active_key_id == "core-2026-08"
    assert key_set.registry.get("core-2026-08") is not None
    # 같은 키 재료여야 한다 — 서명과 검증이 갈라지면 발급 시점에 드러나지 않는다.
    assert key_set.active_private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ) == key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def test_rotation_keeps_previous_key_for_verification(tmp_path: Path) -> None:
    """회전 직후에도 이전 키로 서명된 계약이 기체에 남아 있다 — 검증은 과거를 포함한다."""
    _write_key(tmp_path, "core-2026-02", private=False)
    _write_key(tmp_path, "core-2026-08")
    _manifest(
        tmp_path,
        "core-2026-08",
        [
            {"keyId": "core-2026-08", "status": "ACTIVE"},
            {
                "keyId": "core-2026-02",
                "status": "ACTIVE",
                "notAfter": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        ],
    )

    key_set = load_signing_keys(tmp_path)
    assert key_set.active_key_id == "core-2026-08"
    assert key_set.registry.get("core-2026-02") is not None, "이전 키가 검증에서 사라졌다"


def test_revoked_key_is_registered_for_refusal(tmp_path: Path) -> None:
    """폐기는 발급 중단이 아니라 검증 거부 — registry 에 남아야 거부할 수 있다."""
    _write_key(tmp_path, "core-2025-11", private=False)
    _write_key(tmp_path, "core-2026-08")
    _manifest(
        tmp_path,
        "core-2026-08",
        [
            {"keyId": "core-2026-08", "status": "ACTIVE"},
            {"keyId": "core-2025-11", "status": "REVOKED"},
        ],
    )

    record = load_signing_keys(tmp_path).registry.get("core-2025-11")
    assert record is not None
    assert record.status is KeyStatus.REVOKED


def test_revoked_active_key_refuses_startup(tmp_path: Path) -> None:
    _write_key(tmp_path, "core-2026-08")
    _manifest(tmp_path, "core-2026-08", [{"keyId": "core-2026-08", "status": "REVOKED"}])
    with pytest.raises(SigningKeyError, match="REVOKED"):
        load_signing_keys(tmp_path)


def test_mismatched_private_key_refuses_startup(tmp_path: Path) -> None:
    """서명은 A 로 하고 검증은 B 로 하는 상태 — 발급 시점에는 드러나지 않는다."""
    _write_key(tmp_path, "core-2026-08")
    # 공개키만 다른 키로 덮어쓴다.
    other = Ed25519PrivateKey.generate()
    (tmp_path / "core-2026-08.public.pem").write_bytes(
        other.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    _manifest(tmp_path, "core-2026-08", [{"keyId": "core-2026-08", "status": "ACTIVE"}])

    with pytest.raises(SigningKeyError, match="일치하지 않는다"):
        load_signing_keys(tmp_path)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_loose_private_key_permission_refuses_startup(tmp_path: Path, mode: int) -> None:
    """파일 공급을 택한 이상 파일 권한이 유일한 보호막이다."""
    _write_key(tmp_path, "core-2026-08")
    (tmp_path / "core-2026-08.private.pem").chmod(mode)
    _manifest(tmp_path, "core-2026-08", [{"keyId": "core-2026-08", "status": "ACTIVE"}])

    with pytest.raises(SigningKeyError, match="권한이 너무 열려"):
        load_signing_keys(tmp_path)


def test_active_key_missing_from_manifest_refuses(tmp_path: Path) -> None:
    _write_key(tmp_path, "core-2026-08")
    _manifest(tmp_path, "core-2026-09", [{"keyId": "core-2026-08", "status": "ACTIVE"}])
    with pytest.raises(SigningKeyError, match="keys 에 없다"):
        load_signing_keys(tmp_path)


def test_duplicate_key_material_refuses(tmp_path: Path) -> None:
    """같은 키 재료의 쌍둥이 keyId — signature.keyId 만 바꿔 폐기를 우회할 수 있다."""
    key = _write_key(tmp_path, "core-2026-08")
    (tmp_path / "twin.public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    _manifest(
        tmp_path,
        "core-2026-08",
        [
            {"keyId": "core-2026-08", "status": "ACTIVE"},
            {"keyId": "twin", "status": "ACTIVE"},
        ],
    )
    with pytest.raises(ValueError):
        load_signing_keys(tmp_path)


@pytest.mark.parametrize(
    "manifest",
    [
        {},
        {"active": "k"},
        {"active": "", "keys": [{"keyId": "k"}]},
        {"active": "k", "keys": []},
        {"active": "k", "keys": [{"status": "ACTIVE"}]},
        {"active": "k", "keys": [{"keyId": "k", "status": "UNKNOWN"}]},
        {"active": "k", "keys": [{"keyId": "k", "notAfter": "2026-08-04T00:00:00"}]},
        {"active": "k", "keys": [{"keyId": "k", "notAfter": 12345}]},
    ],
)
def test_malformed_manifest_refuses(tmp_path: Path, manifest: dict[str, object]) -> None:
    _write_key(tmp_path, "k")
    (tmp_path / "keys.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SigningKeyError):
        load_signing_keys(tmp_path)


def test_missing_manifest_refuses(tmp_path: Path) -> None:
    with pytest.raises(SigningKeyError, match="읽을 수 없다"):
        load_signing_keys(tmp_path)
