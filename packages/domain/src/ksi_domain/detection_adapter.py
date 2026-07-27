"""모델 raw output → Detection 계약 정규화 Adapter (Track B-1).

## 왜 모델 선정 전에 이것부터 만드는가

Detector 실모델은 아직 미선정이다(license 게이트 — :mod:`ksi_domain.detection`
docstring 참고). 그러나 어떤 모델을 고르든 raw output 은 "bbox 좌표(포맷 다양) +
score + 클래스 라벨"의 변형이며, 그것을 :class:`~ksi_domain.detection.Detection`
계약으로 정규화하는 규칙은 모델과 무관하게 확정할 수 있다. 이 경계를 먼저 굳히면
모델·런타임 문제가 파이프라인 계약에 침투하지 않는다(대표자 승인 2026-07-27 B1 순서).

## 정규화 규칙 (fail-closed, typed drop)

모델 출력은 신뢰하지 않는 외부 입력으로 다룬다. 입력 1건의 문제는 예외가 아니라
**typed drop**(사유 포함)으로 기록한다 — INV-023의 typed 실패 원칙과 동형이며,
조용한 탈락은 없다(vertical slice의 ``DroppedDetection`` 과 같은 정신).

- 구조 자체가 어긋난 입력(box 원소 4개 아님·좌표가 숫자 아님) → drop ``MALFORMED``
- 좌표·score 의 NaN/Inf → drop ``NON_FINITE``. **포맷 변환 산술이 새로 만든**
  overflow/NaN 도 같은 사유로 잡는다(원본이 finite 여도 normalized×width 곱이나
  코너 합성에서 inf/NaN 이 생길 수 있다 — projection 의 "최종 안전망" 패턴과 동형)
- score 가 [0,1] 밖 → drop ``SCORE_OUT_OF_RANGE`` (조용한 clamp 금지 — P0 검토에서
  zoom_factor 의 조용한 clamp 가 blocker 였던 것과 같은 이유)
- 등록되지 않은 클래스 라벨 → drop ``UNKNOWN_LABEL`` (임의 통과 금지 — 미등록
  클래스가 하류 위험 판정에 무단 진입하지 않게 하되, 죽인 사실은 기록한다).
  라벨 타입은 str 또는 **bool 이 아닌** int 만 허용 — Python 은 ``False == 0`` 이라
  bool 을 허용하면 int 키에 조용히 매칭돼 fail-closed 를 우회한다
- 프레임 경계를 벗어난 bbox → 경계로 클리핑 (탐지 모델의 흔한 동작). 단,
  **클리핑으로 면적 절반 이상을 잃으면** drop ``EXCESSIVE_CLIP`` — 대부분 프레임
  밖인 bbox 를 경계 bbox 로 둔갑시키면 접지점(foot point)이 크게 이동한 편향
  위치가 정상 관측처럼 하류에 들어간다. 문턱 0.5 는 **실측 미검증 보수 임시값**
  이다(이 저장소의 다른 임시 문턱과 같은 지위 — 검증된 값으로 취급하지 않는다)
- 클리핑 후 면적이 0 이거나 완전히 프레임 밖 → drop ``DEGENERATE_BOX``
- confidence threshold 미달 → drop ``BELOW_CONFIDENCE`` (기본 threshold 는 0.0 =
  전부 통과. 안전 파이프라인에서 threshold 를 올리면 미탐이 늘어나는 방향이므로,
  거르는 결정은 기본값이 아니라 호출자의 명시적 선택이어야 한다. 하류가
  ``detection_confidence`` min 병합으로 신뢰도를 계속 들고 간다.)

살아남았지만 실제로 잘린 bbox 는 ``AdapterResult.clipped`` 에 기록된다 — 클리핑은
접지점을 이동시키므로(잘린 방향으로 편향) 그 사실을 산출물에서 지우지 않는다.
하류가 아직 이 기록을 소비하지 않더라도 관측 가능성은 계약 계층이 보장한다.

클리핑 상한은 ``width``/``height`` **포함**이다 — geo projection 의 픽셀 범위 검증이
``0<=u<=width`` 포함 상한이므로(P0-4 우측 경계 골든벡터) 경계로 클리핑된 bbox 의
foot point 가 그대로 유효하다. 이 정합은 우연에 맡기지 않고
``tests/contract/test_detection_adapter.py`` 의 커플링 테스트가 고정한다.

## 이 adapter 가 하지 않는 것 (전제 명시)

- **NMS·중복 억제를 하지 않는다.** ``raw_source`` 는 후처리(NMS 등)가 끝난 최종
  후보 목록을 전제한다 — 대부분의 모델에서 진짜 raw(pre-NMS 수천 박스)를 그대로
  넣으면 중복 Detection 이 하류로 흐른다. 실모델 adapter 구성 시 이 전제를 지켜라.
- **normalized/absolute 오설정을 감지하지 못한다.** ``normalized=False`` 인데
  모델이 [0,1] 좌표를 내면 프레임 좌상단의 초소형 bbox 가 유효 Detection 으로
  통과한다(기하적으로는 합법이라 일반 규칙으로 걸러낼 수 없다). 실모델 통합 시
  known-input 골든 프레임으로 산출 좌표를 검증하는 것이 방어선이다(B1-7).

## Detection 은 여전히 Event 가 아니다 (INV-031)

이 adapter 는 화면 좌표 후보를 만들 뿐이다. 세계좌표·불확실성·이벤트 상태는 하류
(projection → Observation → 상태머신)의 일이며, 여기서 만들지 않는다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from ksi_domain.detection import BoundingBox, Detection, Detector

# 클리핑 후 잔존 면적비 하한 — 이보다 많이 잘리면 접지점(foot point)이 원래 대상과
# 무관한 편향 위치가 되므로 drop 한다(EXCESSIVE_CLIP). 0.5 = "절반 이상 잘리면 기하를
# 신뢰하지 않는다"는 보수적 **실측 미검증 임시값**이다 — assembly 의 trace 문턱과 같은
# 지위로, 실기 데이터로 확정되기 전까지 검증된 값으로 취급하지 않는다.
MIN_AREA_KEPT_AFTER_CLIP = 0.5


class BoxFormat(StrEnum):
    """모델 raw bbox 좌표 포맷.

    Attributes:
        XYXY: ``(x_min, y_min, x_max, y_max)``.
        XYWH: ``(x_min, y_min, width, height)`` — 좌상단 코너 기준.
        CXCYWH: ``(center_x, center_y, width, height)`` — 중심 기준 (DETR 계열 관습).
    """

    XYXY = "XYXY"
    XYWH = "XYWH"
    CXCYWH = "CXCYWH"


@dataclass(frozen=True, slots=True)
class RawDetection:
    """모델 원 출력 1건의 중립 표현 — **아직 아무것도 검증되지 않았다.**

    :class:`~ksi_domain.detection.Detection` 과 달리 생성 시 검증하지 않는다.
    모델 출력을 일단 담아 오는 그릇이며, 검증·정규화는 :class:`DetectionAdapter`
    가 typed drop 으로 수행한다 — 여기서 예외를 던지면 배치 전체가 죽는다.

    Attributes:
        label: 모델의 클래스 라벨. 이름(str) 또는 index(int) — 모델마다 다르다.
        score: 모델 신뢰도. 범위 미보장(정규화가 검증한다).
        box: ``box_format`` 해석의 좌표 4개. absolute 픽셀 또는 normalized [0,1]
            (``DetectionAdapter(normalized=...)`` 가 해석을 결정한다).
    """

    label: str | int
    score: float
    box: tuple[float, float, float, float]


class DropReason(StrEnum):
    """raw detection 이 Detection 으로 승격되지 못한 사유."""

    MALFORMED = "malformed"  # 구조 위반(box 원소 수·숫자 아닌 좌표/score)
    NON_FINITE = "non_finite"  # 좌표·score 의 NaN/Inf(변환 산술이 만든 것 포함)
    SCORE_OUT_OF_RANGE = "score_out_of_range"  # score 가 [0,1] 밖
    BELOW_CONFIDENCE = "below_confidence"  # threshold 미달(명시적 필터)
    UNKNOWN_LABEL = "unknown_label"  # class_map 에 없는 라벨(비허용 타입 포함)
    EXCESSIVE_CLIP = "excessive_clip"  # 클리핑으로 면적 절반 이상 손실
    DEGENERATE_BOX = "degenerate_box"  # 클리핑 후 면적 0 또는 완전히 프레임 밖


@dataclass(frozen=True, slots=True)
class DroppedRawDetection:
    """탈락한 raw detection — 무엇이 왜 죽었는지 보존한다(조용한 탈락 금지)."""

    raw: RawDetection
    reason: DropReason
    detail: str


@dataclass(frozen=True, slots=True)
class ClippedDetection:
    """살아남았지만 경계 클리핑이 실제로 일어난 건의 기록.

    클리핑은 접지점(foot point)을 잘린 방향으로 이동시키므로, 그 사실을 산출물에서
    지우면 편향 위치와 온전한 위치를 하류가 구분할 수 없다. ``area_kept`` 는 원본
    면적 대비 잔존 비율(0~1] 이다.
    """

    raw: RawDetection
    detection: Detection
    area_kept: float


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """정규화 결과. 승격·탈락·클리핑 기록을 함께 반환한다."""

    detections: list[Detection]
    dropped: list[DroppedRawDetection]
    clipped: list[ClippedDetection]


class DetectionAdapter:
    """모델 raw output 배치 → Detection 목록 정규화.

    모델 1종에 adapter 인스턴스 1개를 구성한다(포맷·클래스 매핑이 모델 속성이므로).
    상태를 갖지 않으며 같은 입력에 같은 출력을 낸다(재현성 규약).

    Args:
        box_format: raw bbox 좌표 포맷.
        normalized: True 면 좌표를 [0,1] 정규화 값으로 해석해 프레임 크기로 환산한다.
        class_map: 모델 라벨 → 도메인 클래스명. **여기 없는 라벨은 drop 된다** —
            모델의 전체 클래스 중 이 시스템이 소비하는 부분집합을 명시하는 자리다.
        min_confidence: 이 값 미만 score 는 drop. 기본 0.0(전부 통과) — 근거는 모듈
            docstring(threshold 는 미탐을 늘리는 방향이라 명시적 선택이어야 한다).
    """

    def __init__(
        self,
        *,
        box_format: BoxFormat,
        normalized: bool,
        class_map: Mapping[str | int, str],
        min_confidence: float = 0.0,
    ) -> None:
        if not (
            isinstance(min_confidence, float)
            and math.isfinite(min_confidence)
            and 0.0 <= min_confidence <= 1.0
        ):
            raise ValueError(
                f"min_confidence 는 [0,1] 범위의 finite float 이어야 한다 ({min_confidence!r})"
            )
        if not class_map:
            raise ValueError(
                "class_map 이 비어 있다 — 소비할 클래스가 없으면 adapter 가 무의미하다"
            )
        for label, mapped in class_map.items():
            # bool 은 int 의 subclass 라 dict 에서 0/1 키와 충돌·붕괴한다({1: "A", True: "B"}
            # 는 리터럴 단계에서 조용히 1개가 된다) — 키로 금지한다.
            if isinstance(label, bool) or not isinstance(label, str | int):
                raise ValueError(f"class_map 라벨 키는 str 또는 int 여야 한다 ({label!r})")
            if isinstance(label, str) and not label.strip():
                raise ValueError("class_map 의 라벨 키는 공백일 수 없다")
            if not mapped.strip():
                raise ValueError(f"class_map[{label!r}] 의 도메인 클래스명이 공백이다")
        self._box_format = box_format
        self._normalized = normalized
        self._class_map = dict(class_map)
        self._min_confidence = min_confidence

    def convert(
        self, raws: list[RawDetection], *, width: int, height: int
    ) -> AdapterResult:
        """raw 배치를 정규화한다. 입력 순서를 보존하며 예외를 던지지 않는다.

        단, 프레임 크기가 비양수인 것은 개별 입력의 문제가 아니라 **호출 계약 위반**
        (호출자 버그)이므로 ValueError 다 — :meth:`Detector.detect` 와 같은 규약.
        """
        # int 강제까 겸한다 — float NaN 은 `width <= 0` 비교가 False 라 가드를 그냥
        # 통과한다(NaN-blind). 시그니처 위반을 조기에 명시적으로 끊는다.
        if not (isinstance(width, int) and isinstance(height, int)) or width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양의 int 여야 한다 ({width!r}x{height!r})")

        detections: list[Detection] = []
        dropped: list[DroppedRawDetection] = []
        clipped_records: list[ClippedDetection] = []

        for raw in raws:
            # 구조 검증 — RawDetection 은 "검증되지 않은 그릇"이므로 타입힌트가
            # 런타임을 보장하지 않는다. 구조가 어긋난 입력이 아래 산술에서 TypeError/
            # unpack 오류로 새어 나가 배치 전체를 죽이지 않게 여기서 끊는다.
            if len(raw.box) != 4 or not all(
                isinstance(v, float | int) and not isinstance(v, bool)
                for v in (*raw.box, raw.score)
            ):
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.MALFORMED,
                        f"box 는 숫자 4개, score 는 숫자여야 한다 ({raw.box!r}, {raw.score!r})",
                    )
                )
                continue

            values = (*raw.box, raw.score)
            if not all(math.isfinite(v) for v in values):
                dropped.append(
                    DroppedRawDetection(raw, DropReason.NON_FINITE, f"비유한 값 포함: {values!r}")
                )
                continue

            if not (0.0 <= raw.score <= 1.0):
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.SCORE_OUT_OF_RANGE,
                        f"score {raw.score!r} 가 [0,1] 밖 — 조용한 clamp 금지",
                    )
                )
                continue

            if raw.score < self._min_confidence:
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.BELOW_CONFIDENCE,
                        f"score {raw.score:.4f} < threshold {self._min_confidence:.4f}",
                    )
                )
                continue

            # bool 은 False==0/True==1 로 int 키에 조용히 매칭돼 UNKNOWN_LABEL
            # fail-closed 를 우회한다 — 허용 타입을 명시적으로 제한한다.
            if isinstance(raw.label, bool) or not isinstance(raw.label, str | int):
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.UNKNOWN_LABEL,
                        f"라벨 타입 불허 {type(raw.label).__name__} ({raw.label!r})",
                    )
                )
                continue

            mapped_class = self._class_map.get(raw.label)
            if mapped_class is None:
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.UNKNOWN_LABEL,
                        f"미등록 라벨 {raw.label!r} — 소비 클래스 집합에 없음",
                    )
                )
                continue

            x_min, y_min, x_max, y_max = self._to_xyxy(raw.box, width=width, height=height)

            # 변환 산술이 새로 만든 overflow/NaN 을 잡는 최종 안전망 — 원본 finite
            # 검사는 이 경로를 덮지 못한다(normalized×width 곱·코너 합성에서 발생).
            # projection.py 의 "알고리즘 경로 자체의 발산까지 잡는다" 패턴과 동형.
            converted = (x_min, y_min, x_max, y_max)
            if not all(math.isfinite(v) for v in converted):
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.NON_FINITE,
                        f"포맷 변환 산술이 비유한 값 생성: {converted!r} (원본 {raw.box!r})",
                    )
                )
                continue

            # 경계 클리핑 — 상한 포함(geo projection 픽셀 검증과 정합, 모듈 docstring).
            clipped_x_min = min(max(x_min, 0.0), float(width))
            clipped_y_min = min(max(y_min, 0.0), float(height))
            clipped_x_max = min(max(x_max, 0.0), float(width))
            clipped_y_max = min(max(y_max, 0.0), float(height))
            if clipped_x_max <= clipped_x_min or clipped_y_max <= clipped_y_min:
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.DEGENERATE_BOX,
                        (
                            f"클리핑 후 퇴화 bbox ({clipped_x_min}, {clipped_y_min}, "
                            f"{clipped_x_max}, {clipped_y_max}) — 원본 {raw.box!r}"
                        ),
                    )
                )
                continue

            # 과도 클리핑 — 면적 대부분이 프레임 밖이면 잘린 bbox 의 접지점은 원래
            # 대상과 무관한 편향 위치다. 잔존 비율 문턱은 실측 미검증 임시값(docstring).
            original_area = (x_max - x_min) * (y_max - y_min)
            clipped_area = (clipped_x_max - clipped_x_min) * (clipped_y_max - clipped_y_min)
            area_kept = clipped_area / original_area  # original_area > 0 (위에서 보장)
            if area_kept < MIN_AREA_KEPT_AFTER_CLIP:
                dropped.append(
                    DroppedRawDetection(
                        raw,
                        DropReason.EXCESSIVE_CLIP,
                        (
                            f"클리핑 잔존 면적비 {area_kept:.4f} < "
                            f"{MIN_AREA_KEPT_AFTER_CLIP} — 접지점 신뢰 불가 (원본 {raw.box!r})"
                        ),
                    )
                )
                continue

            detection = Detection(
                detection_class=mapped_class,
                confidence=raw.score,
                bbox=BoundingBox(
                    x_min=clipped_x_min,
                    y_min=clipped_y_min,
                    x_max=clipped_x_max,
                    y_max=clipped_y_max,
                ),
            )
            detections.append(detection)
            if area_kept < 1.0:
                clipped_records.append(
                    ClippedDetection(raw=raw, detection=detection, area_kept=area_kept)
                )

        return AdapterResult(detections=detections, dropped=dropped, clipped=clipped_records)

    def _to_xyxy(
        self, box: tuple[float, float, float, float], *, width: int, height: int
    ) -> tuple[float, float, float, float]:
        """포맷·정규화 해석을 픽셀 XYXY 로 통일한다."""
        a, b, c, d = box
        if self._normalized:
            a, c = a * width, c * width
            b, d = b * height, d * height
        if self._box_format is BoxFormat.XYXY:
            return a, b, c, d
        if self._box_format is BoxFormat.XYWH:
            return a, b, a + c, b + d
        # CXCYWH
        return a - c / 2.0, b - d / 2.0, a + c / 2.0, b + d / 2.0


class AdapterBackedDetector(Detector):
    """raw output 소스 + :class:`DetectionAdapter` 를 :class:`Detector` 로 조립한다.

    ``raw_source`` 가 실모델 inference 호출이면 이것이 실제 Detector 구현이 되고,
    녹화된 raw output 재생이면 recorded-input 검증 구현이 된다 — 두 경우 모두
    정규화·계약 준수는 adapter 한 곳에서 보장되므로 conformance 를 다시 증명할
    필요가 없다.

    탈락·클리핑 기록은 ``last_dropped``·``last_clipped`` 로 노출한다
    (:meth:`Detector.detect` 시그니처는 Detection 목록만 반환하므로). 프레임 간
    누적하지 않으며, **호출 시작 시점에 비운다** — 실패한 호출 뒤에 이전 프레임
    기록이 남아 현재 프레임 것으로 오독되는 stale 경로를 막는다.

    이 기록의 파이프라인 소비(slice 탈락 사유로의 배선)는 B1-7(recorded input
    통합)에서 AdapterBackedDetector 가 슬라이스에 물릴 때 붙는다 — 그 전까지는
    테스트·진단 채널이다.
    """

    def __init__(
        self,
        *,
        raw_source: Callable[[int, int, int], list[RawDetection]],
        adapter: DetectionAdapter,
    ) -> None:
        self._raw_source = raw_source
        self._adapter = adapter
        self.last_dropped: list[DroppedRawDetection] = []
        self.last_clipped: list[ClippedDetection] = []

    def detect(self, frame_id: int, width: int, height: int) -> list[Detection]:
        # 기록을 먼저 비운다 — 아래에서 예외가 나가면(크기 위반·raw_source 실패)
        # 이전 프레임 기록이 stale 로 남지 않게(위 docstring).
        self.last_dropped = []
        self.last_clipped = []
        if not (isinstance(width, int) and isinstance(height, int)) or width <= 0 or height <= 0:
            raise ValueError(f"프레임 크기는 양의 int 여야 한다 ({width!r}x{height!r})")
        result = self._adapter.convert(
            self._raw_source(frame_id, width, height), width=width, height=height
        )
        self.last_dropped = result.dropped
        self.last_clipped = result.clipped
        return result.detections
