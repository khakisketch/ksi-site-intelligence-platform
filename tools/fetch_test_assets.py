"""평가 입력 자산 취득 — docs/models/TEST_ASSETS.yaml 원장 기반 (F-A).

원본(퍼블릭 도메인)을 내려받아 원장에 기록된 변환(800px 축소·JPEG q92)을 적용하고
sha256 을 원장과 대조한다. 불일치는 fail-closed — Pillow 버전 차이로 재인코딩
바이트가 달라졌을 수 있으며, 그 경우 조용히 교체하지 말고 대표자 보고와 함께
원장을 갱신해야 한다(원장 헤더 참조).

사용법::

    uv run python tools/fetch_test_assets.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import yaml
from _digest import DigestMismatchError, fetch_with_digest_verification, sha256_file

LEDGER = Path("docs/models/TEST_ASSETS.yaml")
DEST = Path("models/test-assets")

# Pillow는 save() 시 format= 이 없으면 대상 경로의 확장자로 포맷을 추론한다.
# fetch_with_digest_verification 은 항상 ``<target>.part`` 임시 경로에 쓰므로
# 확장자가 ``.part`` 가 되어 추론이 실패한다 — 최종 파일명(target)의 확장자로
# 명시적으로 매핑해 넘긴다.
_PIL_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


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
            if sha256_file(target) == expected:
                print(f"= {asset['name']} 이미 있음 (digest 일치)")
                continue
            print(f"! {asset['name']} digest 불일치 — 원장 기준으로 다시 받는다")

        print(f"↓ {asset['name']} ← {asset['source_url']}")

        def _fetch_and_reencode(
            target_tmp: Path, asset: dict[str, str] = asset, target: Path = target
        ) -> None:
            with urllib.request.urlopen(asset["source_url"], timeout=120) as resp:  # noqa: S310
                raw = resp.read()
            image = Image.open(BytesIO(raw)).convert("RGB")
            image.thumbnail((800, 800))
            suffix = target.suffix.lower()
            try:
                pil_format = _PIL_FORMAT_BY_SUFFIX[suffix]
            except KeyError:
                raise ValueError(
                    f"{asset['name']}: 알 수 없는 확장자 {suffix!r} — "
                    "_PIL_FORMAT_BY_SUFFIX 에 저장 포맷 매핑을 추가하라"
                ) from None
            image.save(target_tmp, format=pil_format, quality=92)

        try:
            fetch_with_digest_verification(target, expected, _fetch_and_reencode)
        except DigestMismatchError as exc:
            print(
                f"✗ {asset['name']}: 재인코딩 digest {exc.actual[:12]}… ≠ 원장 "
                f"{exc.expected[:12]}… — Pillow 버전 차이 가능성. 조용히 교체하지 말고 "
                "원장 갱신 절차를 따르라(TEST_ASSETS.yaml 헤더)",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(f"✓ {asset['name']} digest 일치")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(fetch())
