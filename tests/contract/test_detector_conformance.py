"""Detector 구현 공통 conformance suite (Track B-1).

어떤 Detector 구현이든 — 결정적 stub 이든, adapter 를 낀 실모델이든 — 파이프라인이
기대하는 같은 계약을 지켜야 한다. 이 모듈은 그 계약을 **재사용 가능한 테스트 묶음**
으로 고정한다: 구현별 테스트 클래스가 :class:`DetectorConformanceSuite` 를 상속하고
``detector`` fixture 만 제공하면 전 계약이 자동 적용된다.

실모델 adapter 가 붙는 시점(B1-7, recorded input 통합)에 그 구현의 테스트 클래스를
여기 추가한다 — conformance 를 다시 발명하지 않는다.

## 계약 내용

1. **탐지 없음 = 빈 목록** — 예외·None 금지. 빈 프레임은 정상 입력이다.
2. **비양수 프레임 크기 = ValueError** — 호출 계약 위반은 typed drop 이 아니라
   호출자 버그다(:meth:`Detector.detect` docstring 규약).
3. **반환 Detection 은 전부 프레임 안** — geo projection 의 픽셀 범위 검증
   (``0<=u<=width`` 포함 상한, P0-4)이 경계 밖 foot point 를 거부하므로, Detector 가
   경계 밖 bbox 를 내면 하류에서 조용히 탈락한다. 그 손실을 Detector 계약 위반으로
   앞당겨 잡는다.
4. **결정성** — 같은 (frame_id, width, height) 입력에 같은 출력. 재현성 규약(P0-6)의
   Detector 계층 대응물이다. GPU 비결정성이 있는 실모델 구현은 이 항목을 구현별로
   재정의·완화할 수 있으나, 완화한다는 사실 자체를 테스트 코드에 명시해야 한다.
"""

from __future__ import annotations

import pytest
from ksi_domain.detection import BoundingBox, Detection, Detector
from ksi_domain.detection_adapter import (
    AdapterBackedDetector,
    BoxFormat,
    DetectionAdapter,
    RawDetection,
)
from ksi_domain.ontology import COCO_ONTOLOGY

_WIDTH = 1920
_HEIGHT = 1080


class DetectorConformanceSuite:
    """모든 Detector 구현이 통과해야 하는 공통 계약.

    사용법: 구현별 테스트 클래스가 상속하고 ``detector`` fixture 를 제공한다.
    fixture 는 **frame_id 1 에 최소 1건을 탐지하는** 구성이어야 한다(빈 구현이
    전 항목을 공허하게 통과하는 것을 막는다 — vacuous pass 방지).
    """

    @pytest.fixture
    def detector(self) -> Detector:
        raise NotImplementedError("구현별 테스트 클래스가 detector fixture 를 제공해야 한다")

    def test_detects_at_least_one_on_seeded_frame(self, detector: Detector) -> None:
        """frame 1 에 최소 1건 — suite 전체의 비공허성(non-vacuity) 앵커."""
        assert detector.detect(1, _WIDTH, _HEIGHT), (
            "conformance fixture 는 frame 1 에 최소 1건을 탐지해야 한다 — "
            "빈 구현은 아래 계약들을 공허하게 통과한다"
        )

    def test_no_detection_returns_empty_list(self, detector: Detector) -> None:
        """탐지 없음은 빈 목록 — 예외·None 이 아니다."""
        result = detector.detect(999_999, _WIDTH, _HEIGHT)
        assert result == []

    @pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (-1, 100), (100, -1)])
    def test_invalid_frame_size_rejected(
        self, detector: Detector, width: int, height: int
    ) -> None:
        with pytest.raises(ValueError, match="프레임 크기"):
            detector.detect(1, width, height)

    def test_all_detections_within_frame(self, detector: Detector) -> None:
        """반환 bbox 는 전부 프레임 안(경계 포함) — 하류 projection 계약과 정합."""
        for detection in detector.detect(1, _WIDTH, _HEIGHT):
            bbox = detection.bbox
            assert 0.0 <= bbox.x_min < bbox.x_max <= _WIDTH, f"x 범위 위반: {bbox!r}"
            assert 0.0 <= bbox.y_min < bbox.y_max <= _HEIGHT, f"y 범위 위반: {bbox!r}"

    def test_deterministic_for_same_input(self, detector: Detector) -> None:
        """같은 입력 반복 호출 = 같은 출력(값 동일성)."""
        first = detector.detect(1, _WIDTH, _HEIGHT)
        second = detector.detect(1, _WIDTH, _HEIGHT)
        assert first == second

    def test_interleaved_frames_do_not_leak_state(self, detector: Detector) -> None:
        """다른 프레임을 끼워 호출해도 결과가 오염되지 않는다(호출 시퀀스 계약).

        Detector 구현은 상태(탈락 기록·모델 컨텍스트)를 가질 수 있다 — 프레임 A→B→A
        시퀀스에서 A 의 결과가 B 처리의 부수효과에 영향받으면 안 된다. 단발 결정성
        (위 테스트)만으로는 이 계약이 고정되지 않는다.
        """
        first = detector.detect(1, _WIDTH, _HEIGHT)
        detector.detect(999_999, _WIDTH, _HEIGHT)  # 빈 프레임(상태 변화 유발 시도)
        with pytest.raises(ValueError):
            detector.detect(1, 0, _HEIGHT)  # 실패 호출도 끼운다
        third = detector.detect(1, _WIDTH, _HEIGHT)
        assert first == third

    def test_caller_mutation_of_result_is_isolated(self, detector: Detector) -> None:
        """호출자가 반환 리스트를 변조해도 이후 호출 결과가 오염되지 않는다."""
        first = detector.detect(1, _WIDTH, _HEIGHT)
        expected = list(first)
        first.clear()  # 호출자 측 변조
        assert detector.detect(1, _WIDTH, _HEIGHT) == expected


# ── 구현 1: 결정적 stub (vertical slice 의 ScriptedDetector 와 동형) ─────────


class _ScriptedDetector(Detector):
    """conformance 대상 최소 stub.

    tests/replay/vertical_slice.py 의 ScriptedDetector 를 import 하지 않고 동형을
    재정의하는 이유: tests/contract 는 계약 패키지만 의존해야 하고(레이어 방향),
    replay 하네스의 헬퍼를 끌어오면 contract 테스트가 replay 구현에 결합된다.
    """

    def __init__(self, script: dict[int, list[Detection]]) -> None:
        self._script = script

    def detect(self, frame_id: int, width: int, height: int) -> list[Detection]:
        if width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양수여야 한다 ({width}x{height})")
        return list(self._script.get(frame_id, []))


class TestScriptedDetectorConformance(DetectorConformanceSuite):
    @pytest.fixture
    def detector(self) -> Detector:
        return _ScriptedDetector(
            {
                1: [
                    Detection(
                        detection_class="Person",
                        confidence=0.9,
                        bbox=BoundingBox(x_min=100.0, y_min=200.0, x_max=180.0, y_max=420.0),
                    )
                ]
            }
        )


# ── 구현 2: adapter-backed (실모델 자리에 raw output 재생을 꽂은 구성) ────────


class TestAdapterBackedDetectorConformance(DetectorConformanceSuite):
    """raw output 소스 + DetectionAdapter 조합이 같은 계약을 통과한다.

    raw 에 경계 밖 좌표를 일부러 넣는다 — adapter 의 클리핑이 conformance 의
    "프레임 안" 계약을 실제로 지켜주는지 이 경로로 확인된다.
    """

    @pytest.fixture
    def detector(self) -> Detector:
        def raw_source(frame_id: int, width: int, height: int) -> list[RawDetection]:
            if frame_id != 1:
                return []
            return [
                # 정상 1건 + 경계 살짝 밖 1건(클리핑 대상) — 모델의 흔한 출력 형태.
                RawDetection(label=0, score=0.9, box=(100.0, 200.0, 80.0, 220.0)),
                RawDetection(label=0, score=0.8, box=(-5.0, -3.0, 60.0, 90.0)),
            ]

        return AdapterBackedDetector(
            raw_source=raw_source,
            adapter=DetectionAdapter(
                box_format=BoxFormat.XYWH,
                normalized=False,
                ontology=COCO_ONTOLOGY,
            ),
        )
