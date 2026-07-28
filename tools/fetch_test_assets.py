"""평가 입력 자산 취득 — docs/models/TEST_ASSETS.yaml 원장 기반 (F-A).

원본(퍼블릭 도메인)을 내려받아 원장에 기록된 변환(800px 축소·JPEG q92)을 적용하고
sha256 을 원장과 대조한다. 불일치는 fail-closed — Pillow 버전 차이로 재인코딩
바이트가 달라졌을 수 있으며, 그 경우 조용히 교체하지 말고 대표자 보고와 함께
원장을 갱신해야 한다(원장 헤더 참조).

사용법::

    uv run python tools/fetch_test_assets.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

import yaml

LEDGER = Path("docs/models/TEST_ASSETS.yaml")
DEST = Path("models/test-assets")


def fetch() -> int:
    from io import BytesIO

    from PIL import Image

    ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    DEST.mkdir(parents=True, exist_ok=True)
    failures = 0

    for asset in ledger["assets"]:
        target = DEST / asset["name"]
        expected = asset["sha256"]
        if target.is_file():
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual == expected:
                print(f"= {asset['name']} 이미 있음 (digest 일치)")
                continue
            print(f"! {asset['name']} digest 불일치 — 원장 기준으로 다시 받는다")

        print(f"↓ {asset['name']} ← {asset['source_url']}")
        with urllib.request.urlopen(asset["source_url"], timeout=120) as resp:  # noqa: S310
            raw = resp.read()
        image = Image.open(BytesIO(raw)).convert("RGB")
        image.thumbnail((800, 800))
        target_tmp = target.with_suffix(target.suffix + ".part")
        image.save(target_tmp, quality=92)
        actual = hashlib.sha256(target_tmp.read_bytes()).hexdigest()
        if actual != expected:
            target_tmp.unlink()
            print(
                f"✗ {asset['name']}: 재인코딩 digest {actual[:12]}… ≠ 원장 {expected[:12]}… — "
                "Pillow 버전 차이 가능성. 조용히 교체하지 말고 원장 갱신 절차를 따르라"
                "(TEST_ASSETS.yaml 헤더)",
                file=sys.stderr,
            )
            failures += 1
            continue
        target_tmp.replace(target)
        print(f"✓ {asset['name']} digest 일치")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(fetch())
