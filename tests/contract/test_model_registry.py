"""Model Registry 계보 계약 (INV-043, MODEL-B1-001) — 모델 파일 없이 상시 실행.

원장(docs/models/MODEL_REGISTRY.yaml)이 대표자 결정의 불변식을 계속 지키는지
고정한다: digest 신원, BLOCKED 계보 차단, production 게이트 유지.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ksi_perception.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryStatus,
    load_model_entry,
    verify_local_model,
)

_MODEL_ID = "ksi-person-detector-dfine-s-coco"


def test_primary_model_is_registered_and_valid() -> None:
    check = load_model_entry(_MODEL_ID)
    assert check.ok, check.detail
    assert check.entry is not None
    assert check.entry.weights_source == "ustc-community/dfine-small-coco"
    assert len(check.entry.revision) == 40  # git SHA — 브랜치명·태그로의 퇴화 방지
    assert check.entry.person_label_id == 0


def test_registry_digests_are_hex64() -> None:
    check = load_model_entry(_MODEL_ID)
    assert check.ok and check.entry is not None
    assert set(check.entry.file_digests) == {
        "model.safetensors",
        "config.json",
        "preprocessor_config.json",
    }
    for digest in check.entry.file_digests.values():
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


def test_production_stays_blocked_until_legal_review() -> None:
    """[대표자 지정] ENGINEERING 승인 ≠ PRODUCTION 승인 — 게이트 전 상태 변경 금지.

    이 테스트를 바꾸는 것은 MODEL-B1-001 production_gate 5항목 전부의 통과 증거와
    대표자 승인이 있을 때만 허용된다.
    """
    check = load_model_entry(_MODEL_ID)
    assert check.ok and check.entry is not None
    assert check.entry.production_status == "BLOCKED_LEGAL_REVIEW"


def _registry_yaml(
    *,
    source: str = "someone/clean-model",
    objects365_used: object = False,
    visdrone_used: object = False,
    file_name: str = "model.safetensors",
) -> str:
    return yaml.safe_dump(
        {
            "models": [
                {
                    "model_id": "probe-model",
                    "weights": {
                        "source": source,
                        "revision": "a" * 40,
                        "files": [{"name": file_name, "sha256": "b" * 64}],
                    },
                    "model_facts": {"person_label_id": 0},
                    "pretraining": {
                        "objects365_used": objects365_used,
                        "visdrone_used": visdrone_used,
                    },
                    "deployment_status": {"production": "BLOCKED_LEGAL_REVIEW"},
                }
            ]
        },
        allow_unicode=True,
    )


def test_blocked_lineage_markers_rejected(tmp_path: Path) -> None:
    """[2차 방어] 이름에 obj365/obj2coco/visdrone 마커가 있으면 선언과 무관하게 거부."""
    for marker in ("dfine-small-obj2coco", "dfine-small-obj365", "visdrone-ft"):
        registry = tmp_path / "registry.yaml"
        registry.write_text(_registry_yaml(source=f"someone/{marker}"), encoding="utf-8")
        check = load_model_entry("probe-model", registry_path=registry)
        assert check.status is RegistryStatus.BLOCKED_LINEAGE, marker


def test_declared_blocked_lineage_rejected_even_with_clean_name(tmp_path: Path) -> None:
    """[1차 방어 — 반증 리뷰 F4] 이름이 깨끗해도 **선언 필드**가 true 면 거부.

    RF-DETR 처럼 repo 이름에 마커가 없는 Objects365 계보가 실제 사례다 — 이름
    휴리스틱만으로는 100% 통과하므로 원장의 선언 필드가 주 방어선이어야 한다.
    """
    for kwargs in (
        {"objects365_used": True},
        {"visdrone_used": True},
        {"objects365_used": None},  # 누락·모호값도 fail-closed
        {"objects365_used": "unknown"},
    ):
        registry = tmp_path / "registry.yaml"
        registry.write_text(_registry_yaml(**kwargs), encoding="utf-8")
        check = load_model_entry("probe-model", registry_path=registry)
        assert check.status is RegistryStatus.BLOCKED_LINEAGE, kwargs


def test_malformed_yaml_returns_typed_result(tmp_path: Path) -> None:
    """[반증 리뷰 F2] 문법이 깨진 원장은 traceback 이 아니라 typed 결과다."""
    registry = tmp_path / "registry.yaml"
    registry.write_text("models: [ {broken", encoding="utf-8")
    check = load_model_entry("probe-model", registry_path=registry)
    assert check.status is RegistryStatus.MALFORMED_REGISTRY


def test_path_component_in_file_name_rejected(tmp_path: Path) -> None:
    """[반증 리뷰 F6] 파일명에 경로 성분이 있으면 원장 자체를 거부.

    pathlib 은 우변 절대경로가 좌변을 버린다 — 원장 한 줄이 임의 경로 읽기/쓰기로
    번역되는 것을 막는다.
    """
    for bad_name in ("/etc/passwd", "../escape.bin", "sub/dir.bin"):
        registry = tmp_path / "registry.yaml"
        registry.write_text(_registry_yaml(file_name=bad_name), encoding="utf-8")
        check = load_model_entry("probe-model", registry_path=registry)
        assert check.status is RegistryStatus.MALFORMED_REGISTRY, bad_name


def test_missing_file_takes_precedence_over_extra_file(tmp_path: Path) -> None:
    """검증 순서 고정: 원장 파일이 없으면 잉여 파일 여부와 무관하게 FILE_MISSING.

    잉여 파일 거부(반증 리뷰 F3) 자체의 실증은 실모델 파일이 필요하므로
    test_dfine_detector 의 test_extra_file_in_model_dir_blocks_load 가 담당한다.
    """
    local = tmp_path / "model"
    local.mkdir()
    (local / "stray.bin").write_bytes(b"x")
    result = verify_local_model(_MODEL_ID, local)
    assert result.status is RegistryStatus.FILE_MISSING


def test_digest_mismatch_rejected(tmp_path: Path) -> None:
    """[핵심 회귀] 이름이 같아도 내용이 다르면 거부 — obj2coco 오다운로드 방지의 실체.

    'coco' 라는 이름의 디렉토리에 다른 내용물이 있으면(잘못된 변형·변조·손상)
    digest 대조가 잡는다.
    """
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
    assert result.detail is not None and "fetch_model" in result.detail


def test_unregistered_model_rejected() -> None:
    check = load_model_entry("no-such-model")
    assert check.status is RegistryStatus.MODEL_NOT_REGISTERED


def test_registry_decision_cross_reference() -> None:
    """Registry 항목은 결정 원장(MODEL_DECISIONS.yaml)의 승인 결정을 참조해야 한다."""
    registry = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    decisions = yaml.safe_load(
        Path("docs/models/MODEL_DECISIONS.yaml").read_text(encoding="utf-8")
    )
    decision_ids = {d["id"] for d in decisions["decisions"]}
    approved = {
        d["id"] for d in decisions["decisions"] if d.get("verdict") == "APPROVED"
    }
    for model in registry["models"]:
        ref = model.get("decision_ref")
        assert ref in decision_ids, f"{model['model_id']} 의 decision_ref {ref!r} 가 원장에 없다"
        assert ref in approved, f"{model['model_id']} 가 미승인 결정 {ref!r} 을 참조한다"


def test_export_nonstr_names_are_malformed_registry(tmp_path: Path) -> None:
    """[재검토 P2 → 폐쇄] export 입출력 이름의 true/7/dict/list 는 문자열로
    coercion 되지 않고 즉시 MALFORMED_REGISTRY 다."""
    base = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    for bad_name in (True, 7, {"x": 1}, ["a"]):
        registry = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
        registry["models"][0]["export"]["outputs"] = ["logits", bad_name]
        p = tmp_path / "reg.yaml"
        p.write_text(yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
        check = load_model_entry(_MODEL_ID, registry_path=p)
        assert check.status is RegistryStatus.MALFORMED_REGISTRY, repr(bad_name)
    assert base["models"][0]["export"]["outputs"] == ["logits", "pred_boxes"]
