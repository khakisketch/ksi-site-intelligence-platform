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

import hashlib
import sys
import urllib.request
from pathlib import Path

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
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual == expected:
                print(f"= {name} 이미 있음 (digest 일치)")
                continue
            print(f"! {name} digest 불일치 — 다시 받는다")
        print(f"↓ {name} ← {base}/{name}")
        # 임시 파일로 받고 digest 통과 후에만 최종 이름으로 옮긴다 — 중단된 다운로드
        # (네트워크 단절·Ctrl-C)가 최종 파일명으로 남아 다음 사람을 속이는 것을 막는다.
        # (남아도 verify_local_model 이 거부하지만, 오염물 자체를 만들지 않는 것이 원칙.)
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with (
                urllib.request.urlopen(f"{base}/{name}", timeout=120) as resp,  # noqa: S310
                partial.open("wb") as out,
            ):
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
            actual = hashlib.sha256(partial.read_bytes()).hexdigest()
            if actual != expected:
                print(
                    f"✗ {name}: 받은 파일 digest {actual[:12]}… ≠ 원장 {expected[:12]}… — "
                    "폐기함. Registry revision 이 맞는지 확인하라",
                    file=sys.stderr,
                )
                return 1
        finally:
            # digest 미통과·중단 잔여물은 항상 제거(예외 경로 포함)
            if partial.is_file() and (
                hashlib.sha256(partial.read_bytes()).hexdigest() != expected
            ):
                partial.unlink()
        partial.replace(target)
        print(f"✓ {name} digest 일치")

    print(f"\n완료: {dest}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: uv run python tools/fetch_model.py <model_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(fetch(sys.argv[1]))
