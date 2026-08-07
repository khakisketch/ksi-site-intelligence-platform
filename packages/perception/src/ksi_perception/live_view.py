"""PSDK Live View frame source — Track B, `recorded.py`의 실기 전환 지점.

## 정적 개발 범위 (2026-08-06, DJI 기체·Manifold 3 물리 접근 없이 진행)

이 모듈은 :func:`~ksi_perception.recorded.load_frame_sequence` 를 대체하는
**Python 쪽** 프레임 소스다 — PSDK ``DjiLiveview_ImageCallback`` 이 디코딩된
프레임을 넘길 때마다 :meth:`LiveFrameBuffer.push_frame` 을 호출하면, 그 프레임이
:class:`LiveViewFrameDetector` 를 통해 기존 파이프라인(D-FINE→Tracking→…→Evidence)
에 :class:`~ksi_domain.detection.Detector` 계약으로 그대로 꽂힌다. 하류는 무변경 —
:class:`~ksi_perception.dfine.RecordedFrameDetector` 와 같은 ``detect_frame`` 계약.

**여기 없는 것— C↔Python 프레임 인계 메커니즘.** PSDK SDK(``edge/third_party/psdk``)
는 C 라이브러리이고, 콜백은 ``edge/psdk-tap``(C) 프로세스에서 받는다. 그 C 프로세스가
디코딩된 버퍼를 이 Python 프로세스로 어떻게 넘기는지(공유메모리·소켓·named pipe 등)는
아직 결정되지 않았다 — 이 저장소의 다른 C↔Python 경계(Stage C "언어중립 계약")와 달리
이미지 프레임처럼 대역폭이 큰 스트림 데이터의 인계 방식은 실기 스트림으로 검증해야
할 사안이라(레이턴시·프레임 드롭 정책이 실측 종속) 이번 세션에서 만들지 않는다.
:meth:`push_frame` 은 그 인계가 어떤 형태로 결정되든 마지막에 호출할 **Python 쪽
착지점**이다.

## 왜 eager dict 가 아니라 ring buffer 인가

``load_frame_sequence`` 의 메모리 계약은 "전 프레임 eager 적재 — 짧은 클립 전용,
장시간 스트림엔 부적합"이라고 이미 선언돼 있다(recorded.py 의
``load_frame_sequence`` 함수 docstring). Live
View 는 정의상 스트림이라 그 계약을 그대로 쓰면 무한정 메모리가 자란다 —
:class:`LiveFrameBuffer` 는 상한(``capacity``) 밖으로 밀려난 오래된 프레임을
버린다. 그 결과 아직 처리되지 않은 채 밀려난 frame_id 조회는
``FRAME_NOT_FOUND`` 다 — recorded 경로의 "없는 frame_id 는 빈 장면이 아니다"
원칙(dfine.py)과 동일하게, 밀려남도 데이터 없음이지 무탐지가 아니다.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ksi_domain.detection import Detector
from ksi_domain.detection_adapter import FrameDetectionResult, FrameDetectionStatus

if TYPE_CHECKING:
    import numpy as np

    from ksi_perception.dfine import DFineDetector

# recorded.py 의 _ALLOWED_MODES 와 동일 사상 — 여기선 이미 디코딩된 numpy 배열만
# 받으므로 PIL 모드 검사 대신 dtype·채널 수를 검사한다(콜백 경계에서 온 배열은
# PIL Image 가 아니다).
_EXPECTED_DTYPE_NAME = "uint8"
_EXPECTED_CHANNELS = 3  # HWC RGB


@dataclass(frozen=True, slots=True)
class _StoredFrame:
    image: np.ndarray
    capture_ts_utc: float


class LiveFrameBuffer:
    """PSDK 콜백이 미는 프레임을 유계 링버퍼로 보관 — frame_id 는 push 순서로 할당.

    스레드 세이프: PSDK 콜백은 별도(C) 스레드에서 fire 하고, ``detect_frame`` 호출은
    파이프라인 스레드에서 일어난다는 전제(실기 스레딩 모델은 psdk-tap 확정 종속) —
    ``push_frame``/``get``/``latest_frame_id`` 를 단일 lock 으로 직렬화한다.
    """

    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity 는 1 이상이어야 한다 (got {capacity!r})")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._frames: OrderedDict[int, _StoredFrame] = OrderedDict()
        self._next_frame_id = 0

    def push_frame(self, image: np.ndarray, *, capture_ts_utc: float) -> int:
        """디코딩된 HWC uint8 RGB 프레임 1장을 넣고 할당된 frame_id 를 돌려준다.

        ``capture_ts_utc``: 이 프레임의 촬영/수신 시각(절대 UTC epoch 초) —
        ``pipeline.py`` 의 ``SliceFrame.capture_ts_utc`` 와 동일 계약(정렬·
        텔레메트리 보간에 쓰인다, recorded_pipeline.py 참고). C tap
        (``edge/psdk-tap/include/psdk_tap/liveview_tap.h``)은 ``recv_mono_ns``
        (``CLOCK_MONOTONIC``, 절대 UTC 아님)만 정직한 시각원으로 확정해뒀다 —
        C↔Python 프레임 인계 메커니즘(아직 미설계, 모듈 docstring 참고)이 그
        monotonic 값을 실제 UTC 로 해석해(``pairing.c`` 류의 wall-clock
        페어링) 여기 넘겨야 한다. 필수 키워드 인자인 이유: 조용한 기본값
        (예: 0.0)은 "시각 없음"을 "1970 epoch"으로 위장시킨다(reviewer 지적,
        production edge runtime 재검토 R5 의 1970 하드코딩 재발 클래스와 동일 사유).

        ``image`` 는 방어적으로 복사해 저장한다 — PSDK 콜백은 통상 버퍼를
        재사용하므로, 참조만 들고 있으면 검증을 통과한 프레임이 콜백 스레드가
        같은 버퍼를 다음 프레임으로 덮어쓴 뒤 조용히 바뀐다(reviewer 지적,
        현재 테스트로는 잡히지 않는 클래스의 오염). 호출자는 복사 여부를 신경
        쓰지 않아도 된다.

        Raises:
            ValueError: dtype·채널 **수**가 계약을 벗어남. 채널 **순서**(RGB
                인지 BGR 인지)는 dtype·shape 만으로 구조적으로 판별 불가능하므로
                여기서 검증하지 않는다 — RGB 보장은 이 버퍼 이전 단계(디코딩
                경계, 아직 미결정)의 책임이다. ``capture_ts_utc`` 가 유한하지
                않아도(NaN/Inf) 거부한다.
        """
        if image.dtype.name != _EXPECTED_DTYPE_NAME:
            raise ValueError(
                f"프레임 dtype 은 {_EXPECTED_DTYPE_NAME} 여야 한다 (got {image.dtype.name!r}) "
                "— PSDK 콜백 버퍼는 이 경계 이전에 디코딩·정규화돼야 한다"
            )
        if image.ndim != 3 or image.shape[2] != _EXPECTED_CHANNELS:
            raise ValueError(
                f"프레임은 HWC RGB({_EXPECTED_CHANNELS}채널)여야 한다 (got shape={image.shape!r})"
            )
        if not math.isfinite(capture_ts_utc):
            raise ValueError(f"capture_ts_utc 는 유한해야 한다 (got {capture_ts_utc!r})")
        with self._lock:
            frame_id = self._next_frame_id
            self._next_frame_id += 1
            self._frames[frame_id] = _StoredFrame(image=image.copy(), capture_ts_utc=capture_ts_utc)
            while len(self._frames) > self._capacity:
                self._frames.popitem(last=False)  # 가장 오래된(FIFO) 프레임 폐기
            return frame_id

    def get(self, frame_id: int) -> np.ndarray | None:
        with self._lock:
            stored = self._frames.get(frame_id)
            return stored.image if stored is not None else None

    def get_capture_ts_utc(self, frame_id: int) -> float | None:
        """``frame_id`` 의 촬영 시각(절대 UTC epoch 초) — 없으면(미도착·폐기됨)
        ``None``. Live View → ``pipeline.py`` ``SliceFrame`` 조립 시 이 값을
        읽어야 한다(아직 미배선 — 모듈 docstring "C↔Python 프레임 인계" 참고)."""
        with self._lock:
            stored = self._frames.get(frame_id)
            return stored.capture_ts_utc if stored is not None else None

    @property
    def latest_frame_id(self) -> int | None:
        with self._lock:
            if not self._frames:
                return None
            return next(reversed(self._frames))


class LiveViewFrameDetector(Detector):
    """:class:`LiveFrameBuffer` + :class:`~ksi_perception.dfine.DFineDetector` 를
    :class:`~ksi_domain.detection.Detector` 로 조립 — Live View 판 ``RecordedFrameDetector``.

    ``detect_frame`` 계약은 dfine.py 의 ``RecordedFrameDetector`` 와 동일하다:
    없는(또는 링버퍼에서 밀려난) frame_id → ``FRAME_NOT_FOUND``, 선언 크기 불일치
    → ``INVALID_FRAME``, 예상 가능한 추론 실패 → ``INFERENCE_FAILED``.
    """

    def __init__(self, *, buffer: LiveFrameBuffer, dfine: DFineDetector) -> None:
        self._buffer = buffer
        self._dfine = dfine

    def detect_frame(self, frame_id: int, width: int, height: int) -> FrameDetectionResult:
        if not (isinstance(width, int) and isinstance(height, int)) or width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양의 int 여야 한다 ({width!r}x{height!r})")
        image = self._buffer.get(frame_id)
        if image is None:
            # 콜백이 아직 안 밀었거나 링버퍼 상한에 밀려 폐기된 경우 — 둘 다
            # "그 frame_id 의 데이터가 없다"이지 무탐지가 아니다(모듈 docstring).
            return FrameDetectionResult(
                frame_id=frame_id,
                status=FrameDetectionStatus.FRAME_NOT_FOUND,
                detail=f"frame {frame_id}: Live View 버퍼에 없음(미도착 또는 폐기됨)",
            )
        if (int(image.shape[1]), int(image.shape[0])) != (width, height):
            return FrameDetectionResult(
                frame_id=frame_id,
                status=FrameDetectionStatus.INVALID_FRAME,
                detail=(
                    f"frame {frame_id}: 선언 크기 {width}x{height} ≠ 이미지 "
                    f"{int(image.shape[1])}x{int(image.shape[0])}"
                ),
            )
        try:
            result = self._dfine.detect_image(image)
        except (RuntimeError, OSError, ValueError) as exc:
            return FrameDetectionResult(
                frame_id=frame_id,
                status=FrameDetectionStatus.INFERENCE_FAILED,
                detail=f"{type(exc).__name__}: {exc}",
            )
        return FrameDetectionResult(
            frame_id=frame_id,
            status=FrameDetectionStatus.OK,
            detections=tuple(result.detections),
            dropped=tuple(result.dropped),
            clipped=tuple(result.clipped),
        )


__all__ = ["LiveFrameBuffer", "LiveViewFrameDetector"]
