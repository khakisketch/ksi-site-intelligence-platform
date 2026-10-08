"""원본 사진 실측 — 워커가 신고값이 아니라 **잰 값**을 만드는 유일한 지점.

``source_media.py`` 가 워커에게 신고값을 주지 않는 이유가 이 함수의 존재
이유다: 여기서 실제로 파일을 열어(``Image.open``) 픽셀 크기를 읽고, 스트리밍
으로 sha256 을 계산한다. 지어낼 수 있는 값이 없다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


class MeasurementError(RuntimeError):
    """파일을 열 수 없거나 손상됐다 — 워커가 이 파일에 대해 아무것도 주장할 수 없다."""


def measure_image(path: Path) -> tuple[str, int, int, int]:
    """``(sha256, size_bytes, width, height)`` — 전부 이 파일에서 실측한 값.

    sha256 은 스트리밍으로 계산한다(포인트 클라우드급은 아니어도 원본 사진이
    수십 MB 일 수 있어 통째로 메모리에 올리지 않는다). 해상도는 Pillow 의
    헤더 파싱으로 읽는다 — 전체 디코드가 아니라 크기 정보만 필요하다.
    """
    if not path.is_file():
        raise MeasurementError(f"파일이 없다: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001 -- Pillow 예외 계층이 넓고, 여기선 전부 같은 결론이다
        raise MeasurementError(f"이미지를 열 수 없다({path}): {exc}") from exc
    return digest.hexdigest(), size, width, height


__all__ = ["MeasurementError", "measure_image"]
