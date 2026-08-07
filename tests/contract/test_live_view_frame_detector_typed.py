"""LiveFrameBuffer + LiveViewFrameDetector 의 typed 분기 상시 커버 (Track B, PSDK
정적 개발 — 실기 없이 Python 쪽 프레임 소스만 검증).

``RecordedFrameDetector`` 와 동일 계약(``detect_frame`` 의 4분기)을 링버퍼
백엔드로도 지킨다는 것과, ``LiveFrameBuffer`` 고유의 링버퍼 폐기·dtype/채널
검증을 실측한다. ``_StubDFineDetector`` 는
``tests/contract/test_recorded_frame_detector_typed.py`` 와 동일 트릭 —
torch/transformers 지연 import 를 안 타므로 실모델 게이트 없이 상시 실행된다.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest
from ksi_domain.detection import BoundingBox, Detection
from ksi_domain.detection_adapter import AdapterResult, FrameDetectionStatus
from ksi_perception.dfine import DFineDetector
from ksi_perception.live_view import LiveFrameBuffer, LiveViewFrameDetector


class _StubDFineDetector(DFineDetector):
    def __init__(self, *, outcome: AdapterResult | Exception) -> None:
        self._outcome = outcome

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _frame(*, width: int = 8, height: int = 6) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def _ok_result() -> AdapterResult:
    detection = Detection(
        detection_class="Person",
        confidence=0.9,
        bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
        source_class_id=0,
        source_class_name="person",
    )
    return AdapterResult(detections=[detection], dropped=[], clipped=[])


# ── LiveFrameBuffer 자체 ─────────────────────────────────────────────────────


def test_push_assigns_sequential_frame_ids() -> None:
    buf = LiveFrameBuffer(capacity=10)
    assert buf.push_frame(_frame(), capture_ts_utc=1700000000.0) == 0
    assert buf.push_frame(_frame(), capture_ts_utc=1700000000.0) == 1
    assert buf.push_frame(_frame(), capture_ts_utc=1700000000.0) == 2


def test_get_returns_pushed_frame() -> None:
    buf = LiveFrameBuffer(capacity=10)
    frame = _frame(width=16, height=9)
    frame_id = buf.push_frame(frame, capture_ts_utc=1700000000.0)
    retrieved = buf.get(frame_id)
    assert retrieved is not None
    assert retrieved.shape == frame.shape
    np.testing.assert_array_equal(retrieved, frame)


def test_get_missing_frame_id_returns_none() -> None:
    buf = LiveFrameBuffer(capacity=10)
    assert buf.get(999) is None


def test_capacity_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="capacity"):
        LiveFrameBuffer(capacity=0)


def test_ring_buffer_evicts_oldest_beyond_capacity() -> None:
    """[핵심] 상한을 넘으면 가장 오래된 프레임부터 폐기 — 무한정 메모리 성장 방지
    (load_frame_sequence 의 eager-load 계약이 스트림엔 부적합하다는 원칙의 실체)."""
    buf = LiveFrameBuffer(capacity=3)
    ids = [buf.push_frame(_frame(), capture_ts_utc=1700000000.0) for _ in range(5)]
    assert ids == [0, 1, 2, 3, 4]
    # 가장 오래된 0·1 은 폐기됐고, 최근 2·3·4 만 남는다.
    assert buf.get(0) is None
    assert buf.get(1) is None
    assert buf.get(2) is not None
    assert buf.get(3) is not None
    assert buf.get(4) is not None


def test_push_frame_copies_defensively() -> None:
    """[핵심] push_frame 은 원본 버퍼를 참조하지 않는다 — PSDK 콜백은 통상 버퍼를
    재사용하므로, 참조만 저장하면 검증을 통과한 프레임이 콜백 스레드의 다음
    쓰기로 조용히 바뀐다(reviewer 지적)."""
    buf = LiveFrameBuffer(capacity=10)
    frame = _frame()
    frame_id = buf.push_frame(frame, capture_ts_utc=1700000000.0)
    frame[:] = 255  # 호출자가(=PSDK 콜백이) 원본 버퍼를 그 자리에서 재사용/변조
    stored = buf.get(frame_id)
    assert stored is not None
    assert not np.array_equal(stored, frame), "저장된 프레임이 원본과 같은 메모리를 본다"
    np.testing.assert_array_equal(stored, np.zeros_like(stored))


def test_concurrent_push_assigns_unique_sequential_ids() -> None:
    """[핵심] 여러 스레드가 동시에 push 해도 frame_id 충돌·누락이 없다(단일 lock)."""
    buf = LiveFrameBuffer(capacity=1000)
    collected: list[int] = []
    lock = threading.Lock()

    def _worker() -> None:
        frame_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
        with lock:
            collected.append(frame_id)

    threads = [threading.Thread(target=_worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(collected) == list(range(50)), "frame_id 가 중복되거나 비어 있다"


def test_latest_frame_id_tracks_most_recent_push() -> None:
    buf = LiveFrameBuffer(capacity=10)
    assert buf.latest_frame_id is None
    buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    second_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    assert buf.latest_frame_id == second_id


def test_get_capture_ts_utc_returns_pushed_value() -> None:
    """[live-view-buffer-missing-capture-timestamp] 프레임별 촬영 시각이 frame_id
    와 별개로 조회 가능해야 한다 — pipeline.py 의 SliceFrame.capture_ts_utc 정렬·
    텔레메트리 보간이 여기서 값을 받는다(아직 미배선, 값 자체는 유실되면 안 됨)."""
    buf = LiveFrameBuffer(capacity=10)
    frame_id = buf.push_frame(_frame(), capture_ts_utc=1712345678.5)
    assert buf.get_capture_ts_utc(frame_id) == 1712345678.5


def test_get_capture_ts_utc_missing_frame_id_returns_none() -> None:
    buf = LiveFrameBuffer(capacity=10)
    assert buf.get_capture_ts_utc(999) is None


def test_get_capture_ts_utc_evicted_frame_returns_none() -> None:
    """[핵심] 링버퍼 폐기는 image 뿐 아니라 capture_ts_utc 도 함께 버린다 — 이미지만
    사라지고 시각만 유령처럼 남아 있으면 재조회 시 잘못된 짝을 만들 수 있다."""
    buf = LiveFrameBuffer(capacity=1)
    evicted_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    buf.push_frame(_frame(), capture_ts_utc=1700000001.0)
    assert buf.get_capture_ts_utc(evicted_id) is None


@pytest.mark.parametrize("bad_ts", [float("nan"), float("inf"), float("-inf")])
def test_push_rejects_non_finite_capture_ts_utc(bad_ts: float) -> None:
    """[핵심] 조용한 기본값(예: 0.0)이 "시각 없음"을 "1970 epoch"으로 위장시키던
    클래스의 재발 방지(production edge runtime 재검토 R5 지적과 동일 사유) —
    NaN/Inf 는 애초에 저장을 거부한다."""
    buf = LiveFrameBuffer(capacity=10)
    with pytest.raises(ValueError, match="capture_ts_utc"):
        buf.push_frame(_frame(), capture_ts_utc=bad_ts)


@pytest.mark.parametrize(
    "bad_frame",
    [
        np.zeros((6, 8, 3), dtype=np.float32),  # dtype 위반
        np.zeros((6, 8, 4), dtype=np.uint8),  # 채널 수 위반(RGBA)
        np.zeros((6, 8), dtype=np.uint8),  # 채널 축 자체 없음
    ],
)
def test_push_rejects_non_conforming_frame(bad_frame: np.ndarray) -> None:
    """[핵심] dtype·채널 계약 위반은 조용히 통과시키지 않는다 — recorded.py 의
    fail-closed 원칙과 동일(잘못된 채널 순서·정밀도가 모델 입력으로 새지 않는다)."""
    buf = LiveFrameBuffer(capacity=10)
    with pytest.raises(ValueError):
        buf.push_frame(bad_frame, capture_ts_utc=1700000000.0)


# ── LiveViewFrameDetector — RecordedFrameDetector 와 동일 4분기 계약 ─────────


def test_missing_frame_id_returns_frame_not_found() -> None:
    buf = LiveFrameBuffer(capacity=10)
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=_ok_result()))
    result = detector.detect_frame(frame_id=99, width=8, height=6)
    assert result.status is FrameDetectionStatus.FRAME_NOT_FOUND
    assert not result.ok
    assert result.detail is not None and "99" in result.detail


def test_evicted_frame_id_returns_frame_not_found_not_empty_scene() -> None:
    """[핵심] 링버퍼에서 밀려난 frame_id 도 FRAME_NOT_FOUND — 무탐지로 위장하지 않는다."""
    buf = LiveFrameBuffer(capacity=1)
    evicted_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    buf.push_frame(_frame(), capture_ts_utc=1700000000.0)  # capacity=1 이라 evicted_id 는 밀려난다
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=_ok_result()))
    result = detector.detect_frame(frame_id=evicted_id, width=8, height=6)
    assert result.status is FrameDetectionStatus.FRAME_NOT_FOUND


def test_declared_size_mismatch_returns_invalid_frame() -> None:
    buf = LiveFrameBuffer(capacity=10)
    frame_id = buf.push_frame(_frame(width=8, height=6), capture_ts_utc=1700000000.0)
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=_ok_result()))
    result = detector.detect_frame(frame_id=frame_id, width=640, height=480)
    assert result.status is FrameDetectionStatus.INVALID_FRAME
    assert result.detail is not None
    assert "640x480" in result.detail
    assert "8x6" in result.detail


@pytest.mark.parametrize(
    "exc", [RuntimeError("cuda oom"), OSError("disk read error"), ValueError("bad tensor shape")]
)
def test_inference_exception_returns_inference_failed_not_raised(exc: Exception) -> None:
    buf = LiveFrameBuffer(capacity=10)
    frame_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=exc))
    result = detector.detect_frame(frame_id=frame_id, width=8, height=6)
    assert result.status is FrameDetectionStatus.INFERENCE_FAILED
    assert result.detail is not None and type(exc).__name__ in result.detail


def test_successful_detection_returns_ok_with_detections() -> None:
    buf = LiveFrameBuffer(capacity=10)
    frame_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    ok = _ok_result()
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=ok))
    result = detector.detect_frame(frame_id=frame_id, width=8, height=6)
    assert result.status is FrameDetectionStatus.OK
    assert result.ok
    assert result.detections == tuple(ok.detections)


def test_nonpositive_declared_size_raises_not_typed() -> None:
    buf = LiveFrameBuffer(capacity=10)
    frame_id = buf.push_frame(_frame(), capture_ts_utc=1700000000.0)
    detector = LiveViewFrameDetector(buffer=buf, dfine=_StubDFineDetector(outcome=_ok_result()))
    with pytest.raises(ValueError, match="양의 int"):
        detector.detect_frame(frame_id=frame_id, width=0, height=6)
