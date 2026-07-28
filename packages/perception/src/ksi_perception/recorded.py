"""녹화 입력 로더 — 이미지 파일(들) → 프레임 시퀀스 (Track B-7, MODEL-B1-001).

PSDK Live View 이전 단계의 frame source 다: 디스크의 녹화 이미지(단일 컷·연속
프레임 시퀀스)를 :class:`~ksi_perception.dfine.RecordedFrameDetector` 가 소비하는
``frame_id → HWC uint8 RGB`` 매핑으로 만든다. 실기 전환 시 이 로더 자리만 Live
View 콜백으로 바뀌고 하류(D-FINE→Tracking→…→Evidence)는 그대로다.

## RGB 강제

OpenCV 계열(BGR)과 달리 여기서는 PIL 로 읽어 **RGB 를 로더가 보장**한다 —
:meth:`DFineDetector.detect_image` 의 채널 순서는 구조적으로 감지 불가능한 호출
계약이므로(BGR 을 넣으면 조용히 성능만 무너진다) 경계를 로더 한 곳에 고정한다.

## 프레임 크기 동일 강제

한 시퀀스의 프레임은 전부 같은 크기여야 한다 — 녹화 중 해상도가 바뀌는 스트림은
별개 시퀀스로 다뤄야 하며, 섞이면 bbox 좌표계·투영 계산이 프레임마다 달라져
조용한 좌표 오염이 된다(fail-closed).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def load_frame_sequence(image_paths: list[Path]) -> dict[int, np.ndarray]:
    """이미지 경로 목록 → ``frame_id → HWC uint8 RGB`` (경로 순서 = frame_id 순서).

    Raises:
        ValueError: 목록이 비었거나, 파일이 없거나, 프레임 크기가 서로 다를 때.
    """
    import numpy as np
    from PIL import Image

    if not image_paths:
        raise ValueError("이미지 경로 목록이 비어 있다 — 빈 시퀀스는 프레임 소스가 아니다")

    frames: dict[int, np.ndarray] = {}
    size: tuple[int, int] | None = None
    for frame_id, path in enumerate(image_paths):
        if not path.is_file():
            raise ValueError(f"녹화 이미지가 없다: {path}")
        with Image.open(path) as img:
            array = np.asarray(img.convert("RGB"), dtype=np.uint8)
        current = (int(array.shape[1]), int(array.shape[0]))  # (width, height)
        if size is None:
            size = current
        elif current != size:
            raise ValueError(
                f"프레임 크기 불일치: {path} 는 {current}, 시퀀스 첫 프레임은 {size} — "
                "해상도가 다른 스트림을 한 시퀀스로 섞을 수 없다"
            )
        frames[frame_id] = array
    return frames


def sequence_dimensions(frames: dict[int, np.ndarray]) -> tuple[int, int]:
    """시퀀스의 (width, height). :func:`load_frame_sequence` 산출물 전제."""
    if not frames:
        raise ValueError("빈 시퀀스")
    first = next(iter(frames.values()))
    return int(first.shape[1]), int(first.shape[0])
