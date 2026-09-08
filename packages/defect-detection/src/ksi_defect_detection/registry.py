"""Model Registry 로드·무결성 검증 — 결함탐지 모델용 (INV-043, MODEL-P4-001).

``docs/models/MODEL_REGISTRY.yaml`` 이 모델 계보의 SSOT 다(``ksi_perception.registry``
와 같은 파일을 공유한다). 이 모듈은 그 원장에서 결함탐지 항목을 읽고, 로컬 모델
파일이 원장의 sha256 과 실제로 일치하는지 검증한다.

``ksi_perception.registry`` 를 재사용하지 않고 이 패키지에 별도로 두는 이유:
그쪽의 ``ModelEntry`` 는 D-FINE/COCO 계보의 위험 프로파일(``person_label_id``,
``pretraining.objects365_used``/``visdrone_used``)에 맞춰진 필드를 필수로 요구한다
— 결함탐지 모델(크랙 세그멘테이션, COCO/Objects365 와 무관)에 이 필드들을 억지로
채우면 있지도 않은 사실을 선언하는 꼴이다. 검증 원칙(digest 대조·로컬 전용
로드·fail-closed typed 결과)은 동일하게 유지하되, 필드는 이 도메인에 맞게 최소로
둔다.

검증 실패는 예외가 아니라 typed 결과로 반환한다(``ksi_perception.registry`` 와
동형, INV-023 동형) — 호출자가 사유를 잃지 않고 fail-closed 로 처리한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

# 저장소 루트 기준 원장 위치 — ksi_perception.registry.DEFAULT_REGISTRY_PATH 와 같은 파일.
DEFAULT_REGISTRY_PATH = Path("docs/models/MODEL_REGISTRY.yaml")


class RegistryStatus(StrEnum):
    OK = "ok"
    REGISTRY_NOT_FOUND = "registry_not_found"
    MODEL_NOT_REGISTERED = "model_not_registered"
    FILE_MISSING = "file_missing"
    DIGEST_MISMATCH = "digest_mismatch"
    UNVERIFIED_EXTRA_FILE = "unverified_extra_file"  # 원장에 없는 파일이 모델 디렉토리에 존재
    MALFORMED_REGISTRY = "malformed_registry"


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """원장 1건의 로드 결과 — 검증에 필요한 필드만 추린다."""

    model_id: str
    weights_source: str  # tools/fetch_defect_model.py 가 다운로드 출처 판별에 쓴다
    revision: str
    file_digests: dict[str, str]  # 파일명 → sha256(hex64)
    input_width_px: int
    input_height_px: int
    production_status: str


@dataclass(frozen=True, slots=True)
class RegistryCheck:
    """검증 결과. ``status`` 가 OK 일 때만 ``entry``/``local_dir`` 가 유효하다."""

    status: RegistryStatus
    entry: ModelEntry | None = None
    local_dir: Path | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is RegistryStatus.OK


def load_model_entry(
    model_id: str, *, registry_path: Path = DEFAULT_REGISTRY_PATH
) -> RegistryCheck:
    """원장에서 모델 항목을 읽는다. 파일 검증은 :func:`verify_local_model` 이 한다."""
    if not registry_path.is_file():
        return RegistryCheck(status=RegistryStatus.REGISTRY_NOT_FOUND, detail=str(registry_path))
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        models = raw["models"]
        found = next((m for m in models if m["model_id"] == model_id), None)
        if found is None:
            return RegistryCheck(
                status=RegistryStatus.MODEL_NOT_REGISTERED,
                detail=f"{model_id} 가 {registry_path} 에 없다",
            )
        weights = found["weights"]
        model_facts = found["model_facts"]
        entry = ModelEntry(
            model_id=found["model_id"],
            weights_source=str(weights["source"]),
            revision=str(weights["revision"]),
            file_digests={f["name"]: f["sha256"] for f in weights["files"]},
            input_width_px=int(model_facts["input_width_px"]),
            input_height_px=int(model_facts["input_height_px"]),
            production_status=str(found["deployment_status"]["production"]),
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError, OSError) as exc:
        return RegistryCheck(
            status=RegistryStatus.MALFORMED_REGISTRY,
            detail=f"원장 구조가 예상과 다르다: {exc!r}",
        )

    if not entry.file_digests:
        return RegistryCheck(
            status=RegistryStatus.MALFORMED_REGISTRY,
            detail=f"{entry.model_id} 에 파일 digest 가 없다 — digest 없는 계보는 신원이 없다",
        )
    for name, digest in entry.file_digests.items():
        # 파일명이 경로로 해석되면 원장 한 줄이 임의 경로 읽기/쓰기로 번역된다
        # (ksi_perception.registry 와 동일 방어, 반증 리뷰 F6). 순수 파일명만.
        if "/" in name or "\\" in name or name in ("..", ".") or Path(name).is_absolute():
            return RegistryCheck(
                status=RegistryStatus.MALFORMED_REGISTRY,
                detail=f"파일명에 경로 성분 불허: {name!r}",
            )
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            return RegistryCheck(
                status=RegistryStatus.MALFORMED_REGISTRY,
                detail=f"{name} 의 sha256 형식이 hex64 가 아니다: {digest!r}",
            )
    return RegistryCheck(status=RegistryStatus.OK, entry=entry)


def verify_local_model(
    model_id: str,
    local_dir: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> RegistryCheck:
    """로컬 모델 디렉토리가 원장의 digest 와 일치하는지 검증한다.

    파일 하나라도 없거나 digest 가 다르면 fail-closed — ``ksi_perception.registry.
    verify_local_model`` 과 동일 절차.
    """
    loaded = load_model_entry(model_id, registry_path=registry_path)
    if not loaded.ok:
        return loaded
    assert loaded.entry is not None
    for name, expected in loaded.entry.file_digests.items():
        path = local_dir / name
        if not path.is_file():
            return RegistryCheck(
                status=RegistryStatus.FILE_MISSING,
                entry=loaded.entry,
                detail=(
                    f"{path} 없음 — tools/fetch_defect_model.py 로 명시적으로 받아라"
                    "(자동 다운로드 금지)"
                ),
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            return RegistryCheck(
                status=RegistryStatus.DIGEST_MISMATCH,
                entry=loaded.entry,
                detail=(
                    f"{name} digest 불일치 — 원장 {expected[:12]}… vs 실물 {actual[:12]}…. "
                    "파일이 변조·손상됐거나 다른 체크포인트를 받았다"
                ),
            )

    extras = sorted(p.name for p in local_dir.iterdir() if p.name not in loaded.entry.file_digests)
    if extras:
        return RegistryCheck(
            status=RegistryStatus.UNVERIFIED_EXTRA_FILE,
            entry=loaded.entry,
            detail=(
                f"원장에 없는 파일이 모델 디렉토리에 있다: {extras} — 검증 불가 파일이 "
                "로드에 개입할 수 있어 거부한다(fail-closed)"
            ),
        )
    return RegistryCheck(status=RegistryStatus.OK, entry=loaded.entry, local_dir=local_dir)


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "ModelEntry",
    "RegistryCheck",
    "RegistryStatus",
    "load_model_entry",
    "verify_local_model",
]
