"""실모델 게이트 공통 조건 — 3개 스위트가 공유하는 단일 판정 (감사 #20·#57).

skip 조건·모델 경로 파생이 파일마다 복붙돼 있으면 한 곳만 갱신될 때 그 파일만
조용히 전량 skip 되는 회귀가 재발한다(F8 계열). 판정은 여기 한 곳이다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

DEFAULT_MODEL_ID = "ksi-person-detector-dfine-s-coco"


def real_model_runtime_available() -> bool:
    """[dfine] extra 전체가 있는가 — transformers 누락(감사 #20)까지 포함해 판정."""
    return all(
        importlib.util.find_spec(module) is not None
        for module in ("torch", "transformers", "onnxruntime")
    )


def registry_model_dir(model_id: str = DEFAULT_MODEL_ID) -> Path:
    """Registry 계보로부터 로컬 모델 디렉토리를 파생한다(원장이 SSOT)."""
    from ksi_perception.registry import load_model_entry

    check = load_model_entry(model_id)
    if not check.ok or check.entry is None:
        return Path("models/__registry_unreadable__")
    return Path("models") / check.entry.weights_source.rsplit("/", 1)[-1] / check.entry.revision
