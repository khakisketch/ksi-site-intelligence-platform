"""RecordedFrameDetector 의 typed 분기 CI 상시 커버 (W4 Part B).

``tests/contract/test_dfine_detector.py`` 의 conformance/실모델 스위트는 [dfine]
extra·모델·평가 이미지가 없으면 CI 에서 전량 skip 된다(``tests/_real_model_gate.py``).
그 결과 production ``RecordedFrameDetector.detect_frame`` 의 typed 분기
(``FRAME_NOT_FOUND``/``INVALID_FRAME``/``INFERENCE_FAILED``/``OK``)가 CI 에서 한
번도 실행되지 않았다 — 특히 ``INVALID_FRAME``(선언 크기≠실물 크기)은 어디에도
실측이 없었다.

이 파일은 :class:`~ksi_perception.dfine.DFineDetector` 의 **내부 추론기만**
서브클래스로 대체한다(``detect_image`` override) — 프레임 로딩·크기 검증·typed
분기 자체는 production 코드(``RecordedFrameDetector.detect_frame``) 그대로 실행된다.

이 파일이 실모델 게이트에 걸리지 않는 이유: ``DFineDetector``/``RecordedFrameDetector``
는 모듈 스코프에서 torch/transformers 를 import 하지 않는다(``detect_image`` 내부의
지연 import). ``_StubDFineDetector`` 는 ``detect_image`` 를 override 해 그 지연
import 경로 자체를 타지 않으므로, torch/transformers 미설치 환경(CI 기본)에서도
이 파일은 상시 실행된다.
"""

from __future__ import annotations

import numpy as np
import pytest
from ksi_domain.detection import BoundingBox, Detection
from ksi_domain.detection_adapter import AdapterResult, FrameDetectionStatus
from ksi_perception.dfine import DFineDetector, RecordedFrameDetector


class _StubDFineDetector(DFineDetector):
    """추론기만 대체하는 테스트 더블 — 실 model/processor 를 만들지 않는다.

    ``RecordedFrameDetector.detect_frame`` 은 ``dfine.detect_image`` 만 호출하므로
    이 더블은 그것만 override 한다. ``DFineDetector.__init__`` (model/processor/
    id2label/adapter 등 실물 요구)은 의도적으로 호출하지 않는다 — 그 속성들은
    override 된 ``detect_image`` 경로에서 쓰이지 않는다.
    """

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


# ── FRAME_NOT_FOUND ──────────────────────────────────────────────────────────


def test_missing_frame_id_returns_frame_not_found() -> None:
    """녹화 시퀀스에 없는 frame_id — 빈 장면이 아니라 소스 결손이다."""
    detector = RecordedFrameDetector(frames={}, dfine=_StubDFineDetector(outcome=_ok_result()))
    result = detector.detect_frame(frame_id=99, width=8, height=6)
    assert result.status is FrameDetectionStatus.FRAME_NOT_FOUND
    assert not result.ok
    assert result.detail is not None and "99" in result.detail
    assert result.detections == ()


# ── INVALID_FRAME (기존 CI 무커버 — 이 스위트가 최초 추가) ───────────────────


def test_declared_size_mismatch_returns_invalid_frame() -> None:
    """[최초 추가] 호출자가 선언한 크기 ≠ 실제 녹화 이미지 크기 → INVALID_FRAME.

    bbox 좌표계가 통째로 어긋나는 조건이라 이 프레임만 typed 실패시켜야 한다.
    """
    frame = _frame(width=8, height=6)
    detector = RecordedFrameDetector(
        frames={1: frame}, dfine=_StubDFineDetector(outcome=_ok_result())
    )
    result = detector.detect_frame(frame_id=1, width=640, height=480)
    assert result.status is FrameDetectionStatus.INVALID_FRAME
    assert not result.ok
    assert result.detail is not None
    assert "640x480" in result.detail
    assert "8x6" in result.detail


# ── INFERENCE_FAILED ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc", [RuntimeError("cuda oom"), OSError("disk read error"), ValueError("bad tensor shape")]
)
def test_inference_exception_returns_inference_failed_not_raised(exc: Exception) -> None:
    """추론기 예외(RuntimeError/OSError/ValueError) 3종이 typed 로 흡수되고

    배치를 죽이지 않는다(호출자는 예외를 받지 않는다).
    """
    detector = RecordedFrameDetector(
        frames={1: _frame()}, dfine=_StubDFineDetector(outcome=exc)
    )
    result = detector.detect_frame(frame_id=1, width=8, height=6)
    assert result.status is FrameDetectionStatus.INFERENCE_FAILED
    assert not result.ok
    assert result.detail is not None and type(exc).__name__ in result.detail


# ── OK ────────────────────────────────────────────────────────────────────────


def test_successful_detection_returns_ok_with_detections() -> None:
    ok = _ok_result()
    detector = RecordedFrameDetector(frames={1: _frame()}, dfine=_StubDFineDetector(outcome=ok))
    result = detector.detect_frame(frame_id=1, width=8, height=6)
    assert result.status is FrameDetectionStatus.OK
    assert result.ok
    assert result.detections == tuple(ok.detections)
    assert result.dropped == ()
    assert result.clipped == ()


# ── 호출 인자 계약 위반(비양수 크기)은 typed 로 삼키지 않는다(프로그래머 오류) ──


def test_nonpositive_declared_size_raises_not_typed() -> None:
    detector = RecordedFrameDetector(
        frames={1: _frame()}, dfine=_StubDFineDetector(outcome=_ok_result())
    )
    with pytest.raises(ValueError, match="양의 int"):
        detector.detect_frame(frame_id=1, width=0, height=6)
