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


# 허용 이미지 모드 — 이 밖의 모드는 convert("RGB") 가 조용히 망가뜨린다(반증 리뷰
# F-G 실측: 16-bit "I;16" 은 예외 없이 전 픽셀 백색 garbage 가 되어 uint8 검사를
# 전부 통과한다 → 모델이 흰 이미지를 보고 무경고 성능 붕괴).
_ALLOWED_MODES = frozenset({"RGB", "L", "P", "RGBA"})


def load_frame_sequence(image_paths: list[Path]) -> dict[int, np.ndarray]:
    """이미지 경로 목록 → ``frame_id → HWC uint8 RGB``.

    ## frame_id 는 호출자가 준 순서다 (P0-6 주의)

    ``frame_id`` 는 ``image_paths`` 의 위치에서 온다 — **"같은 입력"의 정의가
    호출자의 정렬에 위임돼 있다.** ``sorted(dir.glob(...))`` 는 사전순이라
    ``frame_2 < frame_10`` 오정렬을 조용히 만든다(관측 id·fingerprint 가 통째로
    달라짐). 디렉토리에서 만들 때는 숫자 순서를 호출자가 보장하라.

    ## 메모리 계약

    전 프레임을 **eager 로 적재**한다 — 짧은 클립·이미지 시퀀스용이다. 장시간
    영상(예: 4K 1분 ≈ 45GB)에는 구조적으로 부적합하며, 그 경우 스트리밍 소스로
    별도 구현해야 한다(이 함수의 반환 계약을 바꾸지 말 것).

    Raises:
        ValueError: 목록이 비었거나, 파일이 없거나, 프레임 크기가 서로 다르거나,
            이미지 모드가 허용 밖(고비트심도 등)이거나, 멀티프레임 컨테이너일 때.
        PIL.UnidentifiedImageError: 이미지가 아니거나 손상된 파일(OSError 계열).
        PIL.Image.DecompressionBombError: 픽셀 수가 PIL 안전 한도를 넘는 파일.
    """
    import numpy as np
    from PIL import Image, ImageOps

    if not image_paths:
        raise ValueError("이미지 경로 목록이 비어 있다 — 빈 시퀀스는 프레임 소스가 아니다")

    frames: dict[int, np.ndarray] = {}
    size: tuple[int, int] | None = None
    for frame_id, path in enumerate(image_paths):
        if not path.is_file():
            raise ValueError(f"녹화 이미지가 없다: {path}")
        with Image.open(path) as img:
            n_frames = int(getattr(img, "n_frames", 1))  # 정적 타입에 없는 동적 속성
            if n_frames > 1:
                raise ValueError(
                    f"{path}: 멀티프레임 컨테이너({n_frames}프레임) — 첫 프레임만 "
                    "조용히 쓰지 않는다. 프레임을 개별 파일로 분해해 넘겨라"
                )
            if img.mode not in _ALLOWED_MODES:
                raise ValueError(
                    f"{path}: 이미지 모드 {img.mode!r} 불허(허용: {sorted(_ALLOWED_MODES)}) — "
                    "고비트심도 등은 RGB 변환에서 조용히 망가진다(F-G 실측: I;16 → 전 픽셀 백색)"
                )
            # EXIF Orientation 적용(F-F) — DJI 스틸 포함 회전 태그 JPEG 은 PIL 이
            # 자동 회전하지 않아, 같은 W×H 로 크기 검사를 통과한 채 프레임마다
            # 좌표계가 90° 돌아가는 조용한 좌표 오염이 된다.
            upright = ImageOps.exif_transpose(img)
            array = np.asarray(upright.convert("RGB"), dtype=np.uint8)
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
