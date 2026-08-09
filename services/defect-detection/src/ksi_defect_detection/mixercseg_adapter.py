"""MixerCSeg 실모델 → 확률맵 통합 (Phase 4, MODEL-P4-001).

파이프라인 위치::

    Image(HWC uint8 RGB)
      → cv2.resize(INTER_CUBIC, registry 의 input_width/height_px)
      → ToTensor 동형 정규화 ((x/255 - 0.5) / 0.5)
      → MixerCSeg.forward → raw logits [1,1,H,W]
      → sigmoid → 확률맵 [H,W] float32 (0~1)

마스크→:class:`~ksi_event_contracts.defect_candidate.DefectCandidate` 변환(윤곽
추출·면적/길이 계측)은 :mod:`ksi_defect_detection.postprocess` 의 몫이다 — 이
모듈은 "이미지 한 장 → 확률맵"까지만 책임진다.

## 로드 게이트 (D-FINE, ``ksi_perception.dfine`` 와 동일 원칙)

- **런타임 자동 다운로드 금지**: 명시적 로컬 디렉토리에서만 로드한다. 파일이
  없으면 typed 실패를 반환한다(``tools/fetch_defect_model.py`` 로 받으라는
  사유 포함).
- **미고정 파일 금지**: 로드 전 :func:`~ksi_defect_detection.registry.verify_local_model`
  이 Model Registry 의 sha256 과 실물을 대조한다.

## 알려진 잔여 리스크 — 체크포인트 역직렬화

이 체크포인트는 ``.pth``(pickle) 형식이라 ``torch.load(..., weights_only=False)``
가 필요하다(state_dict 옆에 ``argparse.Namespace`` 등 pickle 전용 객체가 같이
저장돼 있어 ``weights_only=True`` 로는 그 계층 자체를 역직렬화할 수 없다) —
D-FINE 의 safetensors 로드보다 약한 안전기반이다. digest 검증(레지스트리
sha256 일치)이 유일한 방어선이며, 이는 파일이 변조되지 않았다는 것만 보증하고
pickle 자체의 임의코드실행 가능성을 없애지는 않는다. 등재된 sha256 과 다른
파일은 애초에 이 로더에 도달하지 못한다(``verify_local_model`` 이 fail-closed).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_defect_detection.registry import DEFAULT_REGISTRY_PATH, verify_local_model

if TYPE_CHECKING:
    import numpy as np

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor" / "mixercseg"


class MixerCSegLoadStatus(StrEnum):
    OK = "ok"
    REGISTRY_REJECTED = "registry_rejected"  # digest 검증 실패(사유는 detail)
    RUNTIME_MISSING = "runtime_missing"  # torch/mmcv 등 미설치([mixercseg] extra)
    LOAD_FAILED = "load_failed"  # 로드·구성 단계의 실패(사유는 detail) — typed 계약 유지


@dataclass(frozen=True, slots=True)
class MixerCSegLoadResult:
    status: MixerCSegLoadStatus
    detector: MixerCSegDetector | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is MixerCSegLoadStatus.OK


def _import_vendored_build_fn() -> Any:
    """벤더링된 MixerCSeg 코드를 로드한다.

    upstream 코드가 ``from models.decoder import ...``/``from VMamba.models...``
    처럼 저장소 루트가 ``sys.path`` 에 있다고 가정하는 절대 import 를 쓴다(벤더링
    시 재작성하지 않음 — upstream 대조·업데이트를 쉽게 유지하려는 선택,
    ``_vendor/mixercseg/NOTICE.md`` 참고). ``models``/``VMamba`` 는 흔한 top-level
    이름이라 다른 곳과 충돌할 수 있어, import 하는 동안만 ``sys.path`` 에 넣고
    끝나면 바로 뺀다 — 이미 import 된 서브모듈은 ``sys.modules`` 캐시에 남아
    재호출 비용은 없다.

    ``sys.modules`` 캐시를 로드 완료 후 지우는 "정리"는 **시도했다가 되돌렸다**
    (2026-08-08, risk defect-detection-vendor-syspath-pollution 조사) — 실측
    결과 이 프로세스에서 ``load_mixercseg_detector`` 를 두 번째 호출하면
    ``RuntimeError: Only a single TORCH_LIBRARY can be used to register the
    namespace _inductor_test``(``torch/_inductor/test_operators.py`` 재import
    시 발생)로 즉시 깨진다 — PyTorch 의 ``TORCH_LIBRARY`` 네이티브 등록은
    프로세스 전역이라 Python 쪽 ``sys.modules`` 를 지우고 재import 해도 그
    네이티브 등록은 "처음 한 번만" 규칙을 어기면 예외를 던진다. 즉 이 캐싱은
    단순 비용 절감이 아니라 **재호출 안전성의 전제**다 — 지우면 두 번째 로드부터
    깨진다. 진짜 오염 방지책은 sys.modules 정리가 아니라 이 top-level import
    자체를 프로세스당 최대 1회로 막는 게이트(예: 모듈 전역 캐시)가 될 텐데,
    그건 이 함수의 스코프를 넘는 별도 설계라 남겨둔다.
    """
    import importlib

    vendor_path = str(_VENDOR_DIR)
    inserted = vendor_path not in sys.path
    if inserted:
        sys.path.insert(0, vendor_path)
    try:
        models_module = importlib.import_module("models")
    finally:
        if inserted and vendor_path in sys.path:
            sys.path.remove(vendor_path)
    return models_module.build_MixerCSeg


class MixerCSegDetector:
    """MixerCSeg 추론 wrapper. :func:`load_mixercseg_detector` 로만 만든다.

    직접 생성하지 않는 이유: 생성 경로를 하나로 좁혀야 digest 검증 우회가
    리뷰에서 눈에 띈다(``ksi_perception.dfine.DFineDetector`` 와 동일 원칙).
    """

    def __init__(
        self,
        *,
        model: Any,
        device: str,
        input_width_px: int,
        input_height_px: int,
        model_id: str,
        source_digests: dict[str, str],
    ) -> None:
        self._model = model
        self._device = device
        self._input_width_px = input_width_px
        self._input_height_px = input_height_px
        self.model_id = model_id
        self.source_digests = dict(source_digests)

    def segment_image(self, image: np.ndarray) -> np.ndarray:
        """이미지 1장(HWC uint8 RGB) → **원본 해상도** 확률맵(H,W) float32, 0~1.

        모델은 고정 ``input_width_px``/``input_height_px``(registry, 512x512)
        에서만 추론하지만, 반환값은 원본 이미지 크기로 다시 리사이즈해서 낸다
        (``ksi_perception.dfine.DFineDetector.detect_image`` 가 ``target_sizes``
        로 원본 픽셀 bbox 를 복원하는 것과 동일 원칙). 이걸 하지 않으면
        ``postprocess`` 가 만드는 polygon·면적·길이가 전부 512x512 모델 좌표계
        값이 돼 호출자가 원본 좌표로 되돌릴 방법이 없다(리사이즈가 비등방이면
        단일 배율로도 복원 불가 — reviewer 지적 F3, 2026-08-07).

        결정성: eval 모드 + ``no_grad`` 로 같은 입력·같은 모델 artifact 에 같은
        출력을 낸다(2026-08-07 이 워크스페이스에서 동일 입력 2회 실행 bit-exact
        실측 확인 — 원본 해상도 복원 리사이즈도 결정적 연산이라 이 성질을
        보존한다).

        구조가 어긋난 입력(2D grayscale·RGBA·비 uint8)은 ValueError 다 —
        조용히 돌리면 성능만 무너져 원인 추적이 안 된다(``DFineDetector.
        detect_image`` 와 동일 계약).
        """
        import cv2
        import numpy as np
        import torch

        if image.ndim != 3 or image.shape[2] != 3 or image.dtype.name != "uint8":
            raise ValueError(
                f"이미지는 HWC uint8 RGB 여야 한다 (shape={image.shape}, dtype={image.dtype})"
            )
        original_height, original_width = image.shape[0], image.shape[1]
        # datasets/crack_dataset.py 의 전처리와 동형: INTER_CUBIC 리사이즈 →
        # [0,1] → (x-0.5)/0.5 정규화(transforms.Normalize((.5,.5,.5),(.5,.5,.5))).
        resized = cv2.resize(
            image,
            (self._input_width_px, self._input_height_px),
            interpolation=cv2.INTER_CUBIC,
        )
        normalized = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
        chw = np.transpose(normalized, (2, 0, 1))
        tensor = torch.from_numpy(chw).unsqueeze(0).to(self._device)
        with torch.no_grad():
            logits = self._model(tensor)
        probability = torch.sigmoid(logits)[0, 0, ...].cpu().numpy().astype(np.float32)
        if (original_width, original_height) == (self._input_width_px, self._input_height_px):
            return probability
        # INTER_LINEAR — 확률맵은 연속값이라 CUBIC 의 오버슈트(0 미만/1 초과)를
        # 피한다. 그래도 부동소수 리샘플링 오차로 미세하게 범위를 벗어날 수
        # 있어 clip 으로 계약([0,1])을 명시적으로 강제한다.
        restored = cv2.resize(
            probability, (original_width, original_height), interpolation=cv2.INTER_LINEAR
        )
        return np.clip(restored, 0.0, 1.0).astype(np.float32)


def load_mixercseg_detector(
    *,
    local_dir: Path,
    model_id: str = "ksi-crack-segmenter-mixercseg-deepcrack",
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    device: str | None = None,
) -> MixerCSegLoadResult:
    """Registry digest 검증 → 로컬 전용 로드 → Detector 구성.

    예외를 던지지 않는다 — 실패는 :class:`MixerCSegLoadResult` 로 반환된다
    (사유 포함, ``load_dfine_detector`` 와 동일 계약).
    """
    check = verify_local_model(model_id, local_dir, registry_path=registry_path)
    if not check.ok:
        return MixerCSegLoadResult(
            status=MixerCSegLoadStatus.REGISTRY_REJECTED,
            detail=f"{check.status}: {check.detail}",
        )
    assert check.entry is not None

    try:
        import torch
    except ImportError as exc:
        return MixerCSegLoadResult(
            status=MixerCSegLoadStatus.RUNTIME_MISSING,
            detail=f"[mixercseg] extra 미설치({exc}) — uv sync --extra mixercseg",
        )

    resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    try:
        build_MixerCSeg = _import_vendored_build_fn()
    # 넓은 except — 이 자리는 "우리 코드"가 아니라 남의 벤더 모듈 최상단
    # 실행이라(reviewer 재검토 지적) ImportError/NameError/AttributeError로
    # 열거해도 새는 경로가 계속 나온다: VMamba/models/csm_triton.py 의
    # `@triton.jit` 은 WITH_TRITON=False 가드 밖이라 triton 미설치 시
    # NameError(실측), mmsegmentation 0.x 의 `mmseg/__init__.py` 는 mmcv 버전
    # 범위를 assert 로 강제하는 것으로 알려져 있어(이 환경에 mmseg 미설치라
    # 직접 재현은 못 함) 버전 불일치 시 AssertionError 가능성. 남의 모듈이
    # import 시점에 무엇을 던질지 이 파일에서 전부 예측할 수 없으므로,
    # "예외를 던지지 않는다" 계약을 지키려면 이 경계에서만 넓게 잡는다
    # (KeyboardInterrupt/SystemExit 은 BaseException 이라 여전히 통과한다).
    except Exception as exc:
        return MixerCSegLoadResult(
            status=MixerCSegLoadStatus.RUNTIME_MISSING,
            detail=(
                f"[mixercseg] extra 의존성 일부 미설치·충돌({exc}) — "
                "mmcv/mmsegmentation/mmengine/triton 확인"
            ),
        )

    try:
        # build_MixerCSeg 는 args.device/args.load_width/args.load_height 만
        # 읽는다(models/segmentor/MixerCSeg.py build_MixerCSeg 본문 확인,
        # criterion 은 학습 전용이라 추론 경로에서 버린다) — upstream main.py 의
        # 전체 argparse CLI 를 벤더링하지 않고 이 세 값만 최소 SimpleNamespace 로
        # 준다.
        from types import SimpleNamespace

        args = SimpleNamespace(
            device=resolved_device,
            load_width=check.entry.input_width_px,
            load_height=check.entry.input_height_px,
        )
        model, _criterion = build_MixerCSeg(args)

        # 원장 파일 중 .pth 로 명시적으로 고른다 — dict 순회 순서(YAML 선언
        # 순서)에 기대는 next(iter(...))는 원장에 다른 파일(config 류)이
        # 추가되면 조용히 엉뚱한 파일을 torch.load 할 수 있다(reviewer 지적
        # P5). 정확히 하나가 아니면 typed 실패로 fail-closed.
        pth_files = [name for name in check.entry.file_digests if name.endswith(".pth")]
        if len(pth_files) != 1:
            return MixerCSegLoadResult(
                status=MixerCSegLoadStatus.LOAD_FAILED,
                detail=f"원장에 .pth 체크포인트가 정확히 1개가 아니다: {pth_files!r}",
            )
        weight_file = pth_files[0]
        # weights_only=False 필요 사유는 모듈 docstring "알려진 잔여 리스크" 참고
        # — digest 검증을 통과한 파일만 여기 도달한다(verify_local_model 이 이미
        # 막았다).
        checkpoint = torch.load(
            local_dir / weight_file, map_location=resolved_device, weights_only=False
        )
        state_dict = checkpoint["model"] if isinstance(checkpoint, dict) else checkpoint
        model.load_state_dict(state_dict, strict=True)
        model.eval()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # "예외를 던지지 않는다" 계약의 잔여 경로(ksi_perception.dfine 와 동일 사유):
        # 체크포인트 손상, state_dict 형상 불일치 등을 typed 로 변환.
        return MixerCSegLoadResult(
            status=MixerCSegLoadStatus.LOAD_FAILED,
            detail=f"{type(exc).__name__}: {exc}",
        )

    return MixerCSegLoadResult(
        status=MixerCSegLoadStatus.OK,
        detector=MixerCSegDetector(
            model=model,
            device=resolved_device,
            input_width_px=check.entry.input_width_px,
            input_height_px=check.entry.input_height_px,
            model_id=model_id,
            source_digests=check.entry.file_digests,
        ),
    )


__all__ = [
    "MixerCSegDetector",
    "MixerCSegLoadResult",
    "MixerCSegLoadStatus",
    "load_mixercseg_detector",
]
