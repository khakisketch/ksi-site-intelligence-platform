"""Model Registry 로드·무결성 검증 (INV-043, MODEL-B1-001).

``docs/models/MODEL_REGISTRY.yaml`` 이 모델 계보의 SSOT 다. 이 모듈은 그 원장을
읽고, 로컬 모델 파일이 원장의 revision·sha256 과 **실제로 일치하는지** 검증한다.

## 왜 이름이 아니라 digest 인가 (대표자 지정 2026-07-27)

모델 이름에 "coco" 가 들어 있다는 것만으로 계보를 신뢰하면 안 된다 — HF 의
D-FINE 배포는 ``_coco``/``_obj365``/``_obj2coco`` 변형을 나란히 두므로, 잘못된
변형(Objects365 계보 = 권리 승인 전 BLOCKED)을 내려받아도 파일명·구조가 같아
조용히 로드된다. digest 대조가 그 경로를 기계적으로 끊는다.

검증 실패는 예외가 아니라 typed 결과로 반환한다(INV-023 동형) — 호출자가
사유를 잃지 않고 fail-closed 로 처리한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

# 저장소 루트 기준 원장 위치. 테스트·도구가 경로를 주입할 수 있게 함수 인자로도 연다.
DEFAULT_REGISTRY_PATH = Path("docs/models/MODEL_REGISTRY.yaml")

# 권리 승인 전 BLOCKED 계보의 식별 문자열(MODEL-B1-001 excluded_without_legal_clearance).
# weights.source·revision 문자열에 이들이 나타나면 등록 자체를 거부한다.
BLOCKED_LINEAGE_MARKERS = ("obj365", "objects365", "obj2coco", "visdrone")


class RegistryStatus(StrEnum):
    OK = "ok"
    REGISTRY_NOT_FOUND = "registry_not_found"
    MODEL_NOT_REGISTERED = "model_not_registered"
    BLOCKED_LINEAGE = "blocked_lineage"  # obj365/obj2coco/visdrone 계보(선언 필드 또는 이름 마커)
    FILE_MISSING = "file_missing"
    DIGEST_MISMATCH = "digest_mismatch"
    UNVERIFIED_EXTRA_FILE = "unverified_extra_file"  # 원장에 없는 파일이 모델 디렉토리에 존재
    MALFORMED_REGISTRY = "malformed_registry"


@dataclass(frozen=True, slots=True)
class OnnxExportEntry:
    """Registry `export` 섹션 — ONNX 산출물의 **외부 권위 앵커** (재검토 P0).

    manifest 는 산출물 옆에 놓이는 자기 서술이라, ONNX+manifest 를 함께 교체하면
    자체 일관성 검사를 통과한다. Registry(코드리뷰 대상 원장)의 이 레코드가
    manifest 를 대조하는 기준이 되어야 `PyTorch 원본 → ONNX` 계보가 강제된다.
    """

    schema: str
    onnx_sha256: str
    exporter: str
    opset: int
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """원장 1건의 로드 결과 — 검증에 필요한 필드만 추린다."""

    model_id: str
    weights_source: str
    revision: str
    file_digests: dict[str, str]  # 파일명 → sha256(hex64)
    person_label_id: int
    production_status: str
    export: OnnxExportEntry | None = None  # export 섹션 미기록 모델은 None


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
        return RegistryCheck(
            status=RegistryStatus.REGISTRY_NOT_FOUND, detail=str(registry_path)
        )
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
        pretraining = found["pretraining"]
        objects365_used = pretraining["objects365_used"]
        visdrone_used = pretraining["visdrone_used"]
        export_raw = found.get("export")
        export_entry = (
            OnnxExportEntry(
                schema="ksi-onnx-export-manifest/1",
                onnx_sha256=str(export_raw["onnx_sha256"]),
                exporter=str(export_raw["exporter"]),
                opset=int(export_raw["opset"]),
                input_names=tuple(i["name"] for i in export_raw["inputs"]),
                output_names=tuple(export_raw["outputs"]),
            )
            if export_raw is not None
            else None
        )
        entry = ModelEntry(
            model_id=found["model_id"],
            weights_source=weights["source"],
            revision=weights["revision"],
            file_digests={f["name"]: f["sha256"] for f in weights["files"]},
            person_label_id=int(found["model_facts"]["person_label_id"]),
            production_status=str(found["deployment_status"]["production"]),
            export=export_entry,
        )
    # yaml.YAMLError·OSError 는 ValueError 서브클래스가 아니다 — 문법이 깨진 원장
    # (가장 흔한 오염 형태)·읽기 실패도 raw traceback 이 아니라 typed 결과여야
    # 모듈 계약("예외가 아니라 typed 결과")이 성립한다(반증 리뷰 F2).
    except (KeyError, TypeError, ValueError, yaml.YAMLError, OSError) as exc:
        return RegistryCheck(
            status=RegistryStatus.MALFORMED_REGISTRY,
            detail=f"원장 구조가 예상과 다르다: {exc!r}",
        )

    # BLOCKED 계보 1차 방어: 원장의 **선언 필드**가 권위다(반증 리뷰 F4 — 이름에
    # 마커가 없는 Objects365 계보(예: RF-DETR)는 이름 검사로 잡히지 않는다).
    # 필드는 명시적 false 만 통과 — true 는 물론 누락·모호값도 거부한다(fail-closed).
    if objects365_used is not False or visdrone_used is not False:
        return RegistryCheck(
            status=RegistryStatus.BLOCKED_LINEAGE,
            detail=(
                f"{entry.model_id}: objects365_used={objects365_used!r}, "
                f"visdrone_used={visdrone_used!r} — 명시적 false 가 아니면 권리 승인 전 "
                "상용 경로 사용 금지(MODEL-B1-001)"
            ),
        )

    # 2차 방어: 출처 문자열의 이름 마커 — 선언 필드가 거짓말할 때(원장 오기입)를
    # 위한 보조 휴리스틱이다. 1차(선언 필드)가 주 방어선이다.
    haystack = f"{entry.weights_source} {entry.revision}".lower()
    for marker in BLOCKED_LINEAGE_MARKERS:
        if marker in haystack:
            return RegistryCheck(
                status=RegistryStatus.BLOCKED_LINEAGE,
                detail=(
                    f"{entry.model_id} 의 가중치 출처에 BLOCKED 계보 마커 {marker!r} — "
                    "권리 승인 전 상용 경로 사용 금지(MODEL-B1-001)"
                ),
            )

    if not entry.file_digests:
        return RegistryCheck(
            status=RegistryStatus.MALFORMED_REGISTRY,
            detail=f"{entry.model_id} 에 파일 digest 가 없다 — digest 없는 계보는 신원이 없다",
        )
    for name, digest in entry.file_digests.items():
        # 파일명이 경로로 해석되면 원장 한 줄이 임의 경로 읽기/쓰기로 번역된다
        # (반증 리뷰 F6 — pathlib 은 우변 절대경로가 좌변을 버린다). 순수 파일명만.
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

    통과해야만 adapter 가 로드를 허용한다 — "이름이 coco 라서 믿는" 경로를 끊는
    2차(실물 대조) 방어선이다. 파일 하나라도 없거나 digest 가 다르면 fail-closed.
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
                    f"{path} 없음 — tools/fetch_model.py 로 명시적으로 받아라"
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
                    "다른 변형(예: obj2coco)을 받았거나 파일이 변조·손상됐다"
                ),
            )

    # 원장에 없는 잉여 파일 거부(반증 리뷰 F3) — 로더 프레임워크(transformers)는
    # 디렉토리에서 원장이 모르는 파일(예: PEFT adapter_config.json)을 집을 수 있다.
    # "digest 검증이 통과한 디렉토리 = 원장에 고정된 파일들뿐"을 가정이 아니라
    # 검사로 만든다. fetch_model.py 산출 디렉토리에는 원장 파일만 있으므로 정상
    # 경로 마찰은 없다.
    extras = sorted(
        p.name for p in local_dir.iterdir() if p.name not in loaded.entry.file_digests
    )
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
