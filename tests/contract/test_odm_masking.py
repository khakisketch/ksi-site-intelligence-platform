"""동적 객체 마스크 → NodeODM 업로드 파일 계약 (PRD §15.2 ④).

여기서 고정하는 것은 실물(무수정 ``opendronemap/nodeodm:latest``, NodeODM
2.2.4 / ODM 3.5.6, 2026-08-12)로 검증된 세 사실이다(``odm_masking.py`` 모듈
docstring 1~3번) — 이 파일이 없으면 그 세 사실이 문서에만 있는 주장으로
남는다.

1. 파일명 규약은 ``{stem}_mask.png`` 다 — ``{전체파일명}_mask.png`` 가 **아니다**.
2. 폴라리티는 흰색(255)=유지, 검정(0)=제외다.
3. 탐지가 없는 사진은 마스크를 만들지 않는다(전부 흰색 마스크는 무의미).

실 컨테이너 대상 종단 확인(제출이 실제로 받아들여지는지)은
``tests/contract/test_odm_live.py`` 가 별도로 한다(HIL 성격, 환경변수 없으면
skip).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from ksi_domain.detection import BoundingBox, Detection
from ksi_domain.detection_adapter import AdapterResult
from ksi_processing_controller.odm import MaskImage
from ksi_processing_controller.odm_masking import (
    build_mask_for_photo,
    build_mask_image,
    odm_mask_filename,
    render_mask_png,
)
from PIL import Image

# ── 파일명 규약 — 실물이 확인한 사실 그대로 고정한다 ─────────────────────────


@pytest.mark.parametrize(
    ("image_filename", "expected"),
    [
        ("probe-0.jpg", "probe-0_mask.png"),
        ("DJI_0001.JPG", "DJI_0001_mask.png"),
        ("site.photo.jpg", "site.photo_mask.png"),  # 마지막 확장자만 벗긴다
    ],
)
def test_mask_filename_strips_only_the_last_extension(
    image_filename: str, expected: str
) -> None:
    """[핵심·실물이 고쳐준 것] ``{stem}_mask.png`` 다 — ``{전체파일명}_mask.png``
    가 아니다.

    실측(2026-08-12): 두 후보(``probe-0.jpg_mask.png`` vs ``probe-0_mask.png``)
    를 실제 컨테이너에 나란히 올려보니 후자만 엔진 로그(``Found N image
    masks``)에 잡혔다. 엔진 소스(``dataset.py::find_mask``)의 마스크 키가
    ``os.path.splitext(사진파일명)[0] + "_mask"`` 이기 때문이다.
    """
    assert odm_mask_filename(image_filename) == expected


def test_mask_filename_is_not_the_full_filename_plus_suffix() -> None:
    """[음성·실물이 고쳐준 것] 조용히 무시되는 규약을 회귀로 재도입하지 않는다."""
    wrong = "probe-0.jpg_mask.png"  # 실측에서 조용히 무시된 규약
    assert odm_mask_filename("probe-0.jpg") != wrong


def test_empty_filename_is_rejected() -> None:
    with pytest.raises(ValueError):
        odm_mask_filename("")


# ── 폴라리티 — 흰색=유지, 검정=제외 ─────────────────────────────────────────


def test_masked_region_renders_black_background_renders_white() -> None:
    """[핵심·실물이 고쳐준 것] 흰색(255)=유지, 검정(0)=제외.

    OpenSfM 소스(``features.py::_in_mask`` 의 ``mask != 0`` = 포함,
    ``dense.py::load_combined_mask``)로 대조한 폴라리티다 — 반대로 칠하면
    "동적 객체만 남기고 나머지를 전부 제외"가 되는 정반대 결과다.
    """
    regions = np.zeros((10, 10), dtype=bool)
    regions[2:5, 2:5] = True  # "동적 객체" 영역

    png_bytes = render_mask_png(regions)
    with Image.open(io.BytesIO(png_bytes)) as im:
        assert im.mode == "L"
        pixels = np.array(im)

    assert (pixels[2:5, 2:5] == 0).all(), "동적 객체 영역은 검정(제외)이어야 한다"
    assert (pixels[0:2, :] == 255).all(), "배경은 흰색(유지)이어야 한다"


def test_render_mask_png_rejects_non_2d_input() -> None:
    with pytest.raises(ValueError):
        render_mask_png(np.zeros((10, 10, 3), dtype=bool))


def test_build_mask_image_combines_filename_and_polarity() -> None:
    regions = np.zeros((4, 4), dtype=bool)
    regions[0, 0] = True

    mask = build_mask_image("photo-1.jpg", regions)

    assert isinstance(mask, MaskImage)
    assert mask.filename == "photo-1_mask.png"
    assert mask.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


# ── 사진 1장 → 탐지 → 마스크 파이프라인 ─────────────────────────────────────


class _FakeDetector:
    """:class:`~ksi_processing_controller.odm_masking.ImageDetector` 구조를
    만족하는 가짜 — 실제 이미지를 열지만 탐지는 미리 정한 값으로 대체한다."""

    def __init__(self, adapter_result: AdapterResult) -> None:
        self._result = adapter_result
        self.seen_shapes: list[tuple[int, ...]] = []

    def detect_image(self, image: np.ndarray) -> AdapterResult:
        self.seen_shapes.append(tuple(image.shape))
        return self._result


def _write_tiny_jpeg(path: Path, *, width: int = 20, height: int = 16) -> None:
    rng = np.random.default_rng(seed=1)
    array = (rng.random((height, width, 3)) * 255).astype("uint8")
    Image.fromarray(array).save(path)


def test_build_mask_for_photo_returns_none_when_nothing_detected(tmp_path: Path) -> None:
    """[핵심] 탐지가 0건이면 마스크 파일 자체를 만들지 않는다."""
    photo = tmp_path / "img-1.jpg"
    _write_tiny_jpeg(photo)
    detector = _FakeDetector(AdapterResult(detections=[], dropped=[], clipped=[]))

    result = build_mask_for_photo(detector, photo, filename="img-1.jpg")

    assert result is None
    assert detector.seen_shapes == [(16, 20, 3)], "HWC RGB 로 열려야 한다"


def test_build_mask_for_photo_returns_a_mask_when_something_detected(
    tmp_path: Path,
) -> None:
    photo = tmp_path / "img-1.jpg"
    _write_tiny_jpeg(photo, width=20, height=16)
    detection = Detection(
        detection_class="Person",
        confidence=0.9,
        bbox=BoundingBox(x_min=2.0, y_min=2.0, x_max=8.0, y_max=10.0),
        source_class_id=0,
        source_class_name="person",
    )
    detector = _FakeDetector(AdapterResult(detections=[detection], dropped=[], clipped=[]))

    result = build_mask_for_photo(detector, photo, filename="img-1.jpg")

    assert result is not None
    assert result.filename == "img-1_mask.png"
    with Image.open(__import__("io").BytesIO(result.png_bytes)) as im:
        assert im.size == (20, 16), "마스크 크기는 사진 픽셀 크기와 같아야 한다"
