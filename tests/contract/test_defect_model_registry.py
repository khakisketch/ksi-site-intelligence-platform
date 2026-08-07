"""Defect Detection Model Registry 계보 계약 (INV-043, MODEL-P4-001) — 모델
가중치 파일 없이 상시 실행(reviewer 지적 F2/F7 — 실모델 게이트 뒤에 숨어 상시
증거가 0건이던 것을 닫는다).

원장(docs/models/MODEL_REGISTRY.yaml)의 ksi-crack-segmenter-mixercseg-deepcrack
항목이 digest 신원·production 게이트를 계속 지키는지 고정한다 —
tests/contract/test_model_registry.py(D-FINE) 와 동일 원칙, 다른 모델 항목.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ksi_defect_detection.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryStatus,
    load_model_entry,
    verify_local_model,
)

_MODEL_ID = "ksi-crack-segmenter-mixercseg-deepcrack"


def test_model_is_registered_and_valid() -> None:
    check = load_model_entry(_MODEL_ID)
    assert check.ok, check.detail
    assert check.entry is not None
    assert check.entry.input_width_px == 512
    assert check.entry.input_height_px == 512
    assert len(check.entry.revision) == 64  # sha256 자기서술 식별자


def test_registry_digests_are_hex64() -> None:
    check = load_model_entry(_MODEL_ID)
    assert check.ok and check.entry is not None
    assert set(check.entry.file_digests) == {"checkpoint_DeepCrack.pth"}
    for digest in check.entry.file_digests.values():
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


def test_production_stays_blocked_until_legal_review() -> None:
    """[대표자 지정] ENGINEERING 승인 ≠ PRODUCTION 승인 — 게이트 전 상태 변경 금지.

    이 테스트를 바꾸는 것은 MODEL-P4-001 이 상용 배포 승인까지 확장됐다는 별도
    대표자 결정이 있을 때만 허용된다(review F7 — 신규 항목엔 이 가드가 없었다).
    """
    check = load_model_entry(_MODEL_ID)
    assert check.ok and check.entry is not None
    assert check.entry.production_status == "BLOCKED_LEGAL_REVIEW"


def _registry_yaml(
    *,
    file_name: str = "checkpoint_DeepCrack.pth",
    digest: str = "a" * 64,
) -> str:
    return yaml.safe_dump(
        {
            "models": [
                {
                    "model_id": _MODEL_ID,
                    "weights": {
                        "source": "google_drive:folder/file",
                        "revision": "b" * 64,
                        "files": [{"name": file_name, "sha256": digest}],
                    },
                    "model_facts": {"input_width_px": 512, "input_height_px": 512},
                    "deployment_status": {"production": "BLOCKED_LEGAL_REVIEW"},
                }
            ]
        }
    )


def test_malformed_yaml_returns_typed_result(tmp_path: Path) -> None:
    """문법이 깨진 원장은 traceback 이 아니라 typed 결과다."""
    registry = tmp_path / "registry.yaml"
    registry.write_text("models: [ {broken", encoding="utf-8")
    check = load_model_entry("probe-model", registry_path=registry)
    assert check.status is RegistryStatus.MALFORMED_REGISTRY


def test_path_component_in_file_name_rejected(tmp_path: Path) -> None:
    """파일명에 경로 성분이 있으면 원장 자체를 거부(pathlib 우변 절대경로 흡수 방지)."""
    for bad_name in ("/etc/passwd", "../escape.bin", "sub/dir.bin"):
        registry = tmp_path / "registry.yaml"
        registry.write_text(_registry_yaml(file_name=bad_name), encoding="utf-8")
        check = load_model_entry(_MODEL_ID, registry_path=registry)
        assert check.status is RegistryStatus.MALFORMED_REGISTRY, bad_name


def test_missing_file_takes_precedence_over_extra_file(tmp_path: Path) -> None:
    """검증 순서 고정: 원장 파일이 없으면 잉여 파일 여부와 무관하게 FILE_MISSING."""
    local = tmp_path / "model"
    local.mkdir()
    (local / "stray.bin").write_bytes(b"x")
    result = verify_local_model(_MODEL_ID, local)
    assert result.status is RegistryStatus.FILE_MISSING


def test_digest_mismatch_rejected(tmp_path: Path) -> None:
    """이름이 같아도 내용이 다르면 거부."""
    local = tmp_path / "model"
    local.mkdir()
    check = load_model_entry(_MODEL_ID)
    assert check.ok and check.entry is not None
    for name in check.entry.file_digests:
        (local / name).write_bytes(b"wrong-variant-content")
    result = verify_local_model(_MODEL_ID, local)
    assert result.status is RegistryStatus.DIGEST_MISMATCH


def test_missing_files_fail_closed_with_fetch_guidance(tmp_path: Path) -> None:
    """파일 부재는 자동 다운로드가 아니라 typed 실패 + fetch 안내다."""
    result = verify_local_model(_MODEL_ID, tmp_path)
    assert result.status is RegistryStatus.FILE_MISSING
    assert result.detail is not None and "fetch_defect_model" in result.detail


def test_unregistered_model_rejected() -> None:
    check = load_model_entry("no-such-defect-model")
    assert check.status is RegistryStatus.MODEL_NOT_REGISTERED


def test_registry_decision_cross_reference() -> None:
    """Registry 항목은 결정 원장(MODEL_DECISIONS.yaml)의 승인 결정을 참조해야 한다."""
    registry = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    decisions = yaml.safe_load(
        Path("docs/models/MODEL_DECISIONS.yaml").read_text(encoding="utf-8")
    )
    approved = {d["id"] for d in decisions["decisions"] if d.get("verdict") == "APPROVED"}
    entry = next(m for m in registry["models"] if m["model_id"] == _MODEL_ID)
    assert entry["decision_ref"] in approved
