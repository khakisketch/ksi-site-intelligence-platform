"""Model Registry 기반 명시적 결함탐지 모델 다운로드 (MODEL-P4-001).

``tools/fetch_model.py`` 와 같은 원칙(런타임 자동 다운로드 금지, 이 스크립트로만
받는다, digest 불일치는 폐기)이지만 별도 스크립트다 — MixerCSeg 가중치는
HuggingFace 가 아니라 Google Drive 배포라 ``fetch_model.py`` 의 HF resolve URL
구성이 그대로 통하지 않는다(``gdown`` 으로 confirm-token 우회가 필요).

사용법::

    uv run python tools/fetch_defect_model.py ksi-crack-segmenter-mixercseg-deepcrack

받은 파일은 ``models/<weights source 마지막 경로>/<revision>/`` 에 놓인다 —
:func:`ksi_defect_detection.mixercseg_adapter.load_mixercseg_detector` 의
``local_dir`` 로 그대로 쓴다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _digest import DigestMismatchError, fetch_with_digest_verification, sha256_file
from ksi_defect_detection.registry import DEFAULT_REGISTRY_PATH, load_model_entry


def _google_drive_file_id(weights_source: str) -> str:
    """``google_drive:<folder_id>/<file_id>`` → ``<file_id>``."""
    if not weights_source.startswith("google_drive:"):
        raise ValueError(f"이 스크립트는 google_drive: 출처만 다룬다 ({weights_source!r})")
    return weights_source.rsplit("/", 1)[-1]


def fetch(model_id: str) -> int:
    check = load_model_entry(model_id, registry_path=DEFAULT_REGISTRY_PATH)
    if not check.ok:
        print(f"✗ registry: {check.status} — {check.detail}", file=sys.stderr)
        return 1
    assert check.entry is not None
    entry = check.entry

    # model_id 로 디렉토리를 딴다(fetch_model.py 의 "weights source 마지막 경로"와
    # 달리) — google_drive: 출처 문자열은 폴더/파일 ID 뿐이라 사람이 읽을 이름이
    # 없다. model_id 는 항상 서술적이고 이 스크립트가 유일한 파생 지점이라
    # load_mixercseg_detector 호출자도 같은 규칙으로 재계산할 수 있다.
    dest = Path("models") / entry.model_id / entry.revision
    dest.mkdir(parents=True, exist_ok=True)
    file_id = _google_drive_file_id(entry.weights_source)

    try:
        import gdown
    except ImportError:
        print("✗ gdown 미설치 — uv sync 로 dev 그룹을 설치하라", file=sys.stderr)
        return 1

    for name, expected in entry.file_digests.items():
        target = dest / name
        if target.is_file():
            if sha256_file(target) == expected:
                print(f"= {name} 이미 있음 (digest 일치)")
                continue
            print(f"! {name} digest 불일치 — 다시 받는다")

        print(f"↓ {name} ← google drive file {file_id}")

        # gdown 은 자체 임시파일을 쓰지 않으므로 여기서 .part 로 받는다 —
        # fetch_with_digest_verification 이 digest 통과 후에만 최종 이름으로 옮긴다.
        def _download(partial: Path) -> None:
            result = gdown.download(id=file_id, output=str(partial), quiet=False)
            if result is None:
                raise RuntimeError(f"gdown 다운로드 실패: {file_id}")

        try:
            fetch_with_digest_verification(target, expected, _download)
        except DigestMismatchError as exc:
            print(f"✗ {exc} — Registry revision·file_id 가 맞는지 확인하라", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"✗ {name}: {exc}", file=sys.stderr)
            return 1
        print(f"✓ {name} digest 일치")

    print(f"\n완료: {dest}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: uv run python tools/fetch_defect_model.py <model_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(fetch(sys.argv[1]))
