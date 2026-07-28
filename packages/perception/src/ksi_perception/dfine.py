"""D-FINE 실모델 → Detection 계약 통합 (Track B-1, MODEL-B1-001).

파이프라인 위치::

    Image/Frame
      → D-FINE preprocessing (RTDetrImageProcessor, 640×640)
      → raw logits/boxes
      → post_process (원본 이미지 픽셀 xyxy 복원)
      → RawDetection (라벨명 문자열)
      → DetectionAdapter (기존 정규화 규칙 전부 적용)
      → Detection

정규화(fail-closed typed drop·클리핑·라벨 검증)는 **기존**
:class:`~ksi_domain.detection_adapter.DetectionAdapter` 를 그대로 쓴다 — 실모델
통합이 새 검증 경로를 만들지 않는다(stub 과 실모델이 같은 계약을 같은 코드로
통과한다는 것이 B1 수용기준이다).

## 로드 게이트 (대표자 지정 2026-07-27)

- **런타임 자동 다운로드 금지**: 명시적 로컬 디렉토리에서만 로드하며
  ``local_files_only=True`` 를 강제한다. 파일이 없으면 다운로드하지 않고 typed
  실패를 반환한다(``tools/fetch_model.py`` 로 받으라는 사유 포함).
- **미고정 revision 금지**: 로드 전 :func:`~ksi_perception.registry.verify_local_model`
  이 Model Registry 의 sha256 과 실물을 대조한다. "이름에 coco 가 들어 있다"는
  digest 불일치(예: obj2coco 오다운로드)를 구제하지 못한다.

## 라벨은 index 가 아니라 이름으로

RawDetection.label 에 모델 내부 index 대신 ``id2label`` 의 라벨명("person")을
넣는다. index 는 모델 재학습·교체(D-FINE-N, RT-DETRv2 fallback)에서 바뀔 수 있는
내부 사정이고, 라벨명은 계약이다. config.json 은 digest 로 고정돼 있으므로
id2label 도 고정된 사실이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_domain.detection import Detector
from ksi_domain.detection_adapter import (
    AdapterResult,
    BoxFormat,
    DetectionAdapter,
    FrameDetectionResult,
    FrameDetectionStatus,
    RawDetection,
)
from ksi_domain.ontology import COCO_ONTOLOGY, OntologyMapping

from ksi_perception.registry import (
    DEFAULT_REGISTRY_PATH,
    verify_local_model,
)

if TYPE_CHECKING:
    import numpy as np


# 모델 후보 1차 선별 문턱 — D-FINE 은 NMS-free 고정 300 query 를 내므로 대부분이
# 무의미한 저신뢰 후보다. 0.05 는 실질 탐지를 거의 버리지 않으면서 프레임당 수백 건의
# 노이즈가 drop 기록을 뒤덮는 것을 막는 **진단 잡음 제거** 수준이다. 실운용 필터링은
# 이 값이 아니라 DetectionAdapter.min_confidence(명시적 선택)의 몫이다.
DEFAULT_SCORE_FLOOR = 0.05


class DFineLoadStatus(StrEnum):
    OK = "ok"
    REGISTRY_REJECTED = "registry_rejected"  # digest·계보 검증 실패(사유는 detail)
    RUNTIME_MISSING = "runtime_missing"  # torch/transformers 미설치([dfine] extra)
    LOAD_FAILED = "load_failed"  # 로드·구성 단계의 실패(사유는 detail) — typed 계약 유지


@dataclass(frozen=True, slots=True)
class DFineLoadResult:
    status: DFineLoadStatus
    detector: DFineDetector | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is DFineLoadStatus.OK


class DFineDetector:
    """D-FINE 추론 + 기존 adapter 정규화. :func:`load_dfine_detector` 로만 만든다.

    직접 생성하지 않는 이유: 생성 경로를 하나로 좁혀야 digest 검증·offline 강제를
    우회하는 코드가 리뷰에서 눈에 띈다.
    """

    def __init__(
        self,
        *,
        model: Any,
        processor: Any,
        id2label: dict[int, str],
        adapter: DetectionAdapter,
        score_floor: float,
        model_id: str,
        source_digests: dict[str, str],
    ) -> None:
        self._model = model
        self._processor = processor
        self._id2label = id2label
        self._adapter = adapter
        self._score_floor = score_floor
        # Registry 상의 신원 — 파생 산출물(ONNX 등)에 계보 앵커로 박힌다.
        self.model_id = model_id
        # 원본 artifact digest(파일명→sha256) — Export Manifest 가 소비한다.
        self.source_digests = dict(source_digests)

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        """이미지 1장(HWC uint8 RGB) → 정규화된 Detection 목록.

        결정성: eval 모드 + ``inference_mode`` + CPU 경로로 같은 입력·같은 모델
        artifact 에 같은 출력을 낸다(B1 수용기준 — 동일성 테스트가 고정).

        구조가 어긋난 입력(2D grayscale·RGBA·비 uint8)은 ValueError 다 — 조용히
        돌리면 성능만 무너져 원인 추적이 안 된다. 단 **BGR(OpenCV 기본)은 구조가
        같아 감지할 수 없다** — 프레임 소스가 RGB 를 보장해야 한다(호출 계약).
        """
        import torch

        if image.ndim != 3 or image.shape[2] != 3 or image.dtype.name != "uint8":
            raise ValueError(
                f"이미지는 HWC uint8 RGB 여야 한다 (shape={image.shape}, dtype={image.dtype})"
            )
        height, width = int(image.shape[0]), int(image.shape[1])
        inputs = self._processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            outputs = self._model(**inputs)
        # threshold 는 score_floor 만 — 실질 필터링은 adapter 의 몫(모듈 상수 참고).
        processed = self._processor.post_process_object_detection(
            outputs, target_sizes=[(height, width)], threshold=self._score_floor
        )[0]
        raws = [
            RawDetection(
                # 미등록 index 는 라벨명 없이 그대로 흘려 UNKNOWN_LABEL 기록에 남긴다.
                label=self._id2label.get(int(label), int(label)),
                score=float(score),
                box=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                # 원시 index 계보 — 라벨명과 함께 보존한다(digest 고정 config 의
                # id2label 이 대응표이므로 둘의 자기모순은 구조적으로 불가능).
                source_class_id=int(label),
            )
            for score, label, b in zip(
                processed["scores"].tolist(),
                processed["labels"].tolist(),
                processed["boxes"].tolist(),
                strict=True,
            )
        ]
        return self._adapter.convert(raws, width=width, height=height)


def load_dfine_detector(
    *,
    local_dir: Path,
    model_id: str = "ksi-person-detector-dfine-s-coco",
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    ontology: OntologyMapping = COCO_ONTOLOGY,
    min_confidence: float = 0.0,
    score_floor: float = DEFAULT_SCORE_FLOOR,
) -> DFineLoadResult:
    """Registry digest 검증 → 로컬 전용 로드 → Detector 구성.

    class 매핑은 자유 dict 가 아니라 **검증된** :class:`OntologyMapping` 만 받는다
    (독립 재검토 Blocker 1) — ``{"truck": "Person"}`` 같은 의미 변조는 OntologyMapping
    생성 시점에 거부되므로 이 로더로는 주입할 수 없다. 소비 범위를 좁히려면 권위
    매핑의 부분집합으로 OntologyMapping 을 구성해 넘긴다.

    예외를 던지지 않는다 — 실패는 :class:`DFineLoadResult` 로 반환된다(사유 포함).
    """
    if not isinstance(ontology, OntologyMapping):
        return DFineLoadResult(
            status=DFineLoadStatus.LOAD_FAILED,
            detail=(
                f"ontology 는 OntologyMapping 이어야 한다 ({type(ontology).__name__}) — "
                "자유 dict 주입 금지(독립 재검토 Blocker 1)"
            ),
        )
    import math

    if not (
        isinstance(score_floor, float)
        and math.isfinite(score_floor)
        and 0.0 <= score_floor <= 1.0
    ):
        # score_floor 는 post_process threshold 로 직행해 adapter 기록 없이 후보를
        # 소멸시킨다(반증 리뷰 F-D) — 검증 없이는 NaN/0.9 오설정이 무경고로 필터를
        # 무력화하거나 대부분을 죽인다. min_confidence 와 동일 규약으로 강제한다.
        _detail = f"score_floor 는 [0,1] 범위의 finite float 이어야 한다 ({score_floor!r})"
        return DFineLoadResult(status=DFineLoadStatus.LOAD_FAILED, detail=_detail)

    check = verify_local_model(model_id, local_dir, registry_path=registry_path)
    if not check.ok:
        return DFineLoadResult(
            status=DFineLoadStatus.REGISTRY_REJECTED,
            detail=f"{check.status}: {check.detail}",
        )
    assert check.entry is not None

    try:
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
    except ImportError as exc:
        return DFineLoadResult(
            status=DFineLoadStatus.RUNTIME_MISSING,
            detail=f"[dfine] extra 미설치({exc}) — uv sync --extra dfine",
        )

    try:
        # local_files_only: 자동 다운로드 금지의 코드 강제. digest+잉여파일 검증이
        # 통과한 디렉토리만 여기 도달한다(verify_local_model 이 원장 외 파일을 거부
        # 하므로 로더가 원장이 모르는 파일을 집는 경로도 없다).
        model = AutoModelForObjectDetection.from_pretrained(local_dir, local_files_only=True)
        model.eval()
        processor = AutoImageProcessor.from_pretrained(local_dir, local_files_only=True)

        id2label = {int(k): str(v) for k, v in model.config.id2label.items()}
        person_id = check.entry.person_label_id
        if id2label.get(person_id) != "person":
            # config 가 digest 로 고정돼 있어 정상 경로에서는 도달 불가 — 도달했다면
            # registry 와 config 가 서로 다른 모델을 가리키는 구성 오류다.
            return DFineLoadResult(
                status=DFineLoadStatus.REGISTRY_REJECTED,
                detail=(
                    f"id2label[{person_id}]={id2label.get(person_id)!r} ≠ 'person' — "
                    "registry person_label_id 와 모델 config 불일치"
                ),
            )

        adapter = DetectionAdapter(
            box_format=BoxFormat.XYXY,  # post_process_object_detection 출력 규약
            normalized=False,  # target_sizes 로 이미 원본 픽셀 좌표 복원됨
            ontology=ontology,
            min_confidence=min_confidence,
        )
    # "예외를 던지지 않는다" 계약의 잔여 경로(반증 리뷰 F11): from_pretrained 의
    # OSError/artifact 오류, DetectionAdapter 인자 검증 ValueError 등을 typed 로 변환.
    # fail-closed 를 전제한 호출자(Manifold 런타임)가 크래시 대신 사유를 받는다.
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return DFineLoadResult(
            status=DFineLoadStatus.LOAD_FAILED,
            detail=f"{type(exc).__name__}: {exc}",
        )
    return DFineLoadResult(
        status=DFineLoadStatus.OK,
        detector=DFineDetector(
            model=model,
            processor=processor,
            id2label=id2label,
            adapter=adapter,
            score_floor=score_floor,
            model_id=model_id,
            source_digests=check.entry.file_digests,
        ),
    )


class RecordedFrameDetector(Detector):
    """frame_id → 녹화 이미지 매핑 + :class:`DFineDetector` 를 :class:`Detector` 로 조립.

    파이프라인의 Detector 자리에 그대로 꽂히는 recorded-input 구현(B1-7 골격).
    진단(탈락·클리핑)은 :class:`FrameDetectionResult` 반환값에 실린다 — mutable
    ``last_dropped``/``last_clipped`` side-channel 은 제거됐다
    (slice-inference-exception-channel 폐쇄).
    """

    def __init__(
        self,
        *,
        frames: dict[int, np.ndarray],
        dfine: DFineDetector,
    ) -> None:
        self._frames = frames
        self._dfine = dfine

    def detect_frame(self, frame_id: int, width: int, height: int) -> FrameDetectionResult:
        if not (isinstance(width, int) and isinstance(height, int)) or width <= 0 or height <= 0:
            # 호출 인자 계약 위반(프로그래머 오류) — typed 로 삼키지 않는다.
            raise ValueError(f"프레임 크기는 양의 int 여야 한다 ({width!r}x{height!r})")
        image = self._frames.get(frame_id)
        if image is None:
            # 없는 프레임은 빈 장면이 아니다 — 소스 결손이 "무사고 프레임"으로
            # 위장하는 경로를 typed 로 끊는다.
            return FrameDetectionResult(
                frame_id=frame_id,
                status=FrameDetectionStatus.FRAME_NOT_FOUND,
                detail=f"frame {frame_id}: 녹화 시퀀스에 없는 frame_id",
            )
        if (int(image.shape[1]), int(image.shape[0])) != (width, height):
            # 호출자가 선언한 프레임 크기와 실제 녹화 이미지가 다르면 bbox 좌표계가
            # 통째로 어긋난다 — 프레임 데이터 문제로 typed 기록하고 이 프레임만
            # 실패시킨다(조용한 진행 금지).
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
            # 프레임 1장의 예상 가능한 추론 실패 — 배치 전체를 죽이지 않는다.
            # (모델/Registry 로드 실패는 여기 오지 않는다 — load_dfine_detector 가
            # 실행 시작 전 typed 로 중단한다.)
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
