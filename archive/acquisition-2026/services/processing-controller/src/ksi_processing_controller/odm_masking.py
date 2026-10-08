"""동적 객체 마스크 → NodeODM 업로드 파일 (PRD §15.2 ④, phase2-dynamic-object-masking).

## 실물이 확인해준 것 — 문서를 믿지 않고 컨테이너를 직접 두드렸다

무수정 ``opendronemap/nodeodm:latest``(NodeODM 2.2.4 / ODM 3.5.6)를 띄워
``/task/new`` 에 합성 이미지 + 마스크 후보 파일명 여러 개를 실제로 올려보고,
``/task/{uuid}/output`` 콘솔 로그와 컨테이너 내부 엔진 소스(``/code/stages/
dataset.py``·``/code/SuperBuild/install/bin/opensfm/opensfm/masking.py`` —
**읽기만 했다, import 하지 않았다.** ADR-KSI-012 D2 는 프로세스·저작물 경계이지
디버깅 중 컨테이너 안을 들여다보는 것을 금지하지 않는다)로 대조해 확인했다
(2026-08-12). odm.py 모듈 docstring 이 이미 세운 선례(버전 필드 오판·all.zip
단일산출물·HTTP 200 에러·code 30)와 같은 지위다 — 아래 넷은 실측이지 ODM
공식 문서 요약이 아니다.

1. **마스크는 별도 REST 필드가 아니다.** ``/swagger.json`` 의 ``/task/new``
   ``images`` 필드 설명은 GEO 파일(geo.txt)·이미지그룹(image_groups.txt)·
   GCP 파일(*.txt)·seed.zip·align 파일은 이름으로 언급하지만 마스크는 전혀
   언급하지 않는다 — NodeODM 자신은 마스크 개념을 모른다. 그런데도 동작하는
   건 ODM 엔진이 업로드된 이미지 디렉터리를 파일명 패턴으로 스캔하기
   때문이다. 그래서 마스크는 사진과 **같은 multipart ``images`` 필드에,
   같은 ``/task/new`` 호출로** 얹는다 — :class:`~ksi_processing_controller.
   odm.NodeOdmClient` 의 5개 REST 호출 경계가 늘지 않는다.

2. **[핵심] 파일명 규약은 ``{stem}_mask.<ext>`` 다 — ``{원본파일명 전체}_mask.
   png`` 가 아니다.** 처음 시도(사진 ``probe-0.jpg`` 에 ``probe-0.jpg_mask.png``
   식으로 확장자를 포함한 전체 파일명 뒤에 접미사를 붙이는 규약)는 REST 로는
   200 을 받았지만 엔진 로그에 ``Found N image masks`` 가 찍히지 않아 **조용히
   무시됐다** — 실패로도 드러나지 않는다는 점에서 odm.py 의 "HTTP 200 에러"
   교훈과 같은 함정이다. 엔진 소스(``dataset.py::find_mask``)를 읽고 나서야
   원인이 드러났다: 사진의 마스크 키는
   ``os.path.splitext(사진파일명)[0] + "_mask"`` 인데(확장자를 뗀 stem),
   ``{전체파일명}_mask.png`` 로 올리면 ``os.path.splitext`` 가 마지막
   확장자(``.png``)만 떼서 키가 ``"probe-0.jpg_mask"`` 가 되어 사진이 찾는 키
   ``"probe-0_mask"`` 와 어긋난다. ``{stem}_mask.png`` 규약으로 정정해
   재업로드하자 ``Found 3 image masks``(사진 3장 모두)로 정확히 매칭됐다.

3. **폴라리티는 흰색(255)=유지, 검정(0)=제외다.** OpenSfM 소스
   (``opensfm/features.py::_in_mask`` 의 ``mask[...] != 0`` 이 "포함")와 dense
   단계(``opensfm/dense.py::load_combined_mask``)를 대조해 확인했다 — 사람
   bbox 를 흰색으로 칠하면 정반대(그 영역만 남기고 나머지를 전부 제외)가
   된다.

4. **알려진 한계 — sparse 특징점 매칭 단계는 이 이미지에서 마스크를 무시한다.**
   번들된 OpenSfM 포크의 ``opensfm/masking.py::load_features_mask`` 에
   ``# ODM fork hack: we never mask features (they can add good keypoints)``
   주석과 조기 ``return`` 이 있어(그 아래 실제 마스킹 코드는 도달 불가능한
   죽은 코드), 카메라 포즈 추정에 쓰이는 특징점은 마스크와 무관하게 전부
   살아남는다. 마스크가 실제로 끊는 곳은 **dense 단계**
   (``opensfm/dense.py``·``opensfm/undistort.py``·
   ``opensfm/actions/export_openmvs.py`` — depthmap·점군 밀도·텍스처링)뿐이다.
   즉 최종 정사영상·메시 텍스처에서 동적 객체가 빠지는 효과는 실물로
   확인되지만, 카메라 포즈 자체는 동적 객체 특징점의 영향을 그대로 받는다.
   완료기준의 "저가중치" 대안으로도 이 한계는 없어지지 않는다 — 그 대안도
   결국 같은 엔진의 같은 sparse 경로를 타기 때문이다. 이 한계는 정직하게
   남겨둔다(2차 검증·향후 세션이 참고할 사실).

## 왜 여기이고 :mod:`ksi_perception.dynamic_object_mask` 가 아닌가

탐지 bbox → bool 영역 배열까지는 엔진과 무관한 순수 기하 연산이라 perception
패키지가 갖는다(그 모듈 docstring 참고). 그 배열을 **어떤 파일명·어떤 흑백
폴라리티로 인코딩해야 NodeODM 이 알아보는가**는 위 1~3번처럼 엔진 실물이 정한
사실이고, 엔진이 바뀌면(Pix4D 등) 이 규약도 바뀐다 — 그래서 엔진 어댑터
계층(``odm.py`` 옆)에 둔다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

import numpy as np
from ksi_domain.detection_adapter import AdapterResult
from ksi_perception.dynamic_object_mask import dynamic_object_regions
from PIL import Image

from ksi_processing_controller.odm import MaskImage


class ImageDetector(Protocol):
    """:class:`~ksi_perception.dfine.DFineDetector` 와 구조적으로 호환되는
    최소 인터페이스.

    이 프로토콜만 참조하므로 이 모듈·``worker.py`` 는 torch/transformers 를
    끌어오지 않는다 — 실제 ``DFineDetector`` 인스턴스는 이 시그니처를 이미
    만족하므로(구조적 타이핑) 어댑터 글루 코드 없이 그대로 넘길 수 있다.
    """

    def detect_image(self, image: np.ndarray) -> AdapterResult: ...


def odm_mask_filename(image_filename: str) -> str:
    """사진 파일명 → ODM 이 인식하는 마스크 파일명(``{stem}_mask.png``).

    ``os.path.splitext`` 와 동일하게 **마지막 확장자만** 벗긴다 — 실물 확인:
    모듈 docstring 2번. ``PurePosixPath.stem`` 도 같은 규칙(마지막 점 기준)
    이라 등가다.
    """
    stem = PurePosixPath(image_filename).stem
    if not stem:
        raise ValueError(f"파일명에서 stem 을 얻을 수 없다: {image_filename!r}")
    return f"{stem}_mask.png"


def render_mask_png(regions: np.ndarray) -> bytes:
    """bool ``(H, W)`` 배열 → ODM 폴라리티(흰색=유지, 검정=제외) PNG 바이트.

    실물 확인: 모듈 docstring 3번.
    """
    if regions.ndim != 2:
        raise ValueError(f"regions 는 2D(H,W) 여야 한다 (shape={regions.shape})")
    # True(동적 객체 → 제외) → 0(검정). False(배경 → 유지) → 255(흰색).
    pixels = np.where(regions, np.uint8(0), np.uint8(255))
    buf = io.BytesIO()
    Image.fromarray(pixels, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def build_mask_image(image_filename: str, regions: np.ndarray) -> MaskImage:
    """사진 1장의 동적 객체 영역 → 업로드용 :class:`~odm.MaskImage`."""
    return MaskImage(
        filename=odm_mask_filename(image_filename),
        png_bytes=render_mask_png(regions),
    )


@dataclass(frozen=True, slots=True)
class MaskGenerationFailure:
    """사진 1장의 탐지·마스크 생성이 실패한 기록 — 조용히 삼키지 않는다."""

    media_id: str
    detail: str


def build_mask_for_photo(
    detector: ImageDetector,
    image_path: Path,
    *,
    filename: str,
) -> MaskImage | None:
    """사진 1장을 열어 탐지 → 마스크까지 만든다.

    동적 객체가 하나도 없으면 ``None`` 이다 — 전부 흰색인 마스크는 ODM 입장에서
    "아무것도 제외하지 않는다"와 동치라, 업로드할 이유가 없다(대역폭 낭비이자
    엔진 로그의 ``Found N image masks`` 카운트를 실제 개입 건수와 다르게
    부풀린다).

    구조가 어긋난 이미지(손상 파일 등)는 :class:`OSError`/:class:`ValueError`
    로 전파한다 — 호출자(``worker.py``)가 사진 1장의 탐지 실패를 배치 전체
    중단 없이 다루는 typed 정책을 이미 갖고 있으므로(그 정책을 여기서 복제하지
    않는다), 이 함수는 예외를 그대로 던지는 편이 판단을 한 곳에 모은다.
    """
    with Image.open(image_path) as im:
        image = np.array(im.convert("RGB"))
    height, width = int(image.shape[0]), int(image.shape[1])
    result = detector.detect_image(image)
    regions = dynamic_object_regions(result.detections, width=width, height=height)
    if not regions.any():
        return None
    return build_mask_image(filename, regions)


__all__ = [
    "ImageDetector",
    "MaskGenerationFailure",
    "build_mask_for_photo",
    "build_mask_image",
    "odm_mask_filename",
    "render_mask_png",
]
