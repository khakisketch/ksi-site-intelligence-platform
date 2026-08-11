"""Model Registry 기반 명시적 모델 다운로드 (MODEL-B1-001).

런타임 자동 다운로드는 금지다 — 모델 파일은 이 스크립트로만 받는다. Registry 의
고정 revision 에서 받아 sha256 을 대조하고, 불일치면 받은 파일을 지우고 실패한다
(잘못된 변형(예: obj2coco)이 로컬에 남아 다음 사람을 속이는 것을 막는다).

사용법::

    uv run python tools/fetch_model.py ksi-person-detector-dfine-s-coco

받은 파일은 ``models/<weights source 마지막 경로>/<revision>/`` 에 놓인다 —
:func:`ksi_perception.dfine.load_dfine_detector` 의 ``local_dir`` 로 그대로 쓴다.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from _digest import DigestMismatchError, fetch_with_digest_verification, sha256_file
from ksi_perception.registry import DEFAULT_REGISTRY_PATH, load_model_entry


def fetch(model_id: str) -> int:
    check = load_model_entry(model_id, registry_path=DEFAULT_REGISTRY_PATH)
    if not check.ok:
        print(f"✗ registry: {check.status} — {check.detail}", file=sys.stderr)
        return 1
    assert check.entry is not None
    entry = check.entry

    dest = Path("models") / entry.weights_source.rsplit("/", 1)[-1] / entry.revision
    dest.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/{entry.weights_source}/resolve/{entry.revision}"

    for name, expected in entry.file_digests.items():
        target = dest / name
        if target.is_file():
            if sha256_file(target) == expected:
                print(f"= {name} 이미 있음 (digest 일치)")
                continue
            print(f"! {name} digest 불일치 — 다시 받는다")
        print(f"↓ {name} ← {base}/{name}")

        def _download(partial: Path, name: str = name) -> None:
            with (
                urllib.request.urlopen(f"{base}/{name}", timeout=120) as resp,  # noqa: S310
                partial.open("wb") as out,
            ):
                while chunk := resp.read(1 << 20):
                    out.write(chunk)

        try:
            fetch_with_digest_verification(target, expected, _download)
        except DigestMismatchError as exc:
            print(f"✗ {exc} — Registry revision 이 맞는지 확인하라", file=sys.stderr)
            return 1
        print(f"✓ {name} digest 일치")

    print(f"\n완료: {dest}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: uv run python tools/fetch_model.py <model_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(fetch(sys.argv[1]))
