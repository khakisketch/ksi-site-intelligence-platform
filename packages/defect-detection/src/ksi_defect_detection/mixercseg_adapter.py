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

import importlib.machinery
import importlib.util
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_defect_detection.registry import DEFAULT_REGISTRY_PATH, verify_local_model

if TYPE_CHECKING:
    import numpy as np

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor" / "mixercseg"

# upstream 코드가 절대 import 로 쓰는 최상위 이름("from models...", "from
# VMamba...") — 둘 다 흔한 이름이라 프로세스의 다른 'models'/'VMamba' 와 충돌할
# 수 있다(risk defect-detection-vendor-syspath-pollution). 로드 도중에만
# sys.modules 에 이 bare 이름으로 잠깐 등록했다가, 끝나면 아래 접두사 밑으로
# 옮겨 담고 bare 이름은 지운다.
_VENDOR_TOP_NAMES = ("models", "VMamba")
_VENDOR_NS_PREFIX = "_ksi_defect_detection_vendor_mixercseg"

# _import_vendored_build_fn 은 프로세스당 최대 1회만 실제 import 를 실행하고
# 그 뒤로는 이 캐시를 반환한다(락으로 동시 호출 직렬화). 이유는 함수
# docstring 의 "재호출 안전성" 항목 참고 — 캐시가 없으면 두 번째 로드부터
# PyTorch TORCH_LIBRARY 네이티브 등록 충돌로 깨진다.
_vendor_build_fn_lock = threading.Lock()
_vendor_build_fn_cache: Any | None = None


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


def _is_vendor_sys_modules_key(key: str) -> bool:
    """``key`` 가 이번 벤더 로드로 생겼을 수 있는 'models'/'VMamba' 계열인가.

    정확히 그 이름이거나(top package) 그 이름으로 시작하는 dotted 하위
    모듈만 해당한다(``"models.decoder"`` 는 해당, ``"other.models.x"`` 는
    비해당) — 그 외 torch/triton/mmcv 등은 이 필터로 절대 걸리지 않는다.
    """
    return key in _VENDOR_TOP_NAMES or any(
        key.startswith(f"{top}.") for top in _VENDOR_TOP_NAMES
    )


def _relocate_vendor_sys_modules(*, keep: bool) -> None:
    """이번 호출로 ``sys.modules`` 에 생긴 'models'/'VMamba' 계열 항목을 정리한다.

    ``keep=True`` (로드 성공): 고유 접두사(``_VENDOR_NS_PREFIX``) 밑으로 옮겨
    담아 재호출 캐시로 삼는다 — bare 이름은 남기지 않는다.
    ``keep=False`` (로드 실패): 통째로 버린다. 실패 도중 부분적으로 생긴
    하위 모듈을 캐시로 남기면 다음 재시도가 일관성 없는 상태를 이어받는다.

    ``models``/``VMamba`` 가 아닌 다른 이름(``torch``, ``triton``, ``mmcv`` 등)은
    이 함수가 절대 건드리지 않는다 — "새로 생긴 걸 전부 정리"하는 넓은 청소는
    2026-08-08 조사에서 PyTorch ``TORCH_LIBRARY`` 네이티브 등록 재실행 크래시를
    낸 원인이었다(아래 ``load_mixercseg_detector`` 재호출 관련 docstring 참고).
    """
    for key in [k for k in sys.modules if _is_vendor_sys_modules_key(k)]:
        module = sys.modules.pop(key)
        if keep:
            sys.modules[f"{_VENDOR_NS_PREFIX}.{key}"] = module


def _spec_for_vendor_package(name: str, package_dir: Path) -> importlib.machinery.ModuleSpec:
    """``package_dir`` 을 ``name`` 으로 로드할 spec 을 파일 경로로 직접 만든다.

    ``__init__.py`` 가 있으면 일반 패키지로 spec 을 만든다(``models`` 가
    이 경우). 없으면(``VMamba`` 가 이 경우 — upstream 자체가 top-level
    ``__init__.py`` 없이 ``VMamba.models...`` 로 import 한다) PEP 420 네임스페이스
    패키지와 동등한 spec(``loader=None``)을 직접 구성한다 — 어느 쪽이든
    ``sys.path``/``sys.modules`` 에 이미 뭐가 있는지와 무관하게 항상 이
    디렉토리에서 로드됨을 보장한다(``importlib.import_module`` 이었다면
    같은 이름의 기존 캐시를 잘못 돌려줄 수 있었다).
    """
    init_file = package_dir / "__init__.py"
    if init_file.is_file():
        spec = importlib.util.spec_from_file_location(
            name, init_file, submodule_search_locations=[str(package_dir)]
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"벤더 패키지 진입점을 찾을 수 없음: {init_file}")
        return spec
    namespace_spec = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    namespace_spec.submodule_search_locations = [str(package_dir)]
    return namespace_spec


def _import_vendored_build_fn() -> Any:
    """벤더링된 MixerCSeg 코드를 로드해 ``build_MixerCSeg`` 를 반환한다.

    upstream 코드가 ``from models.decoder import ...``/``from VMamba.models...``
    처럼 저장소 루트가 ``sys.path`` 에 있다고 가정하는 절대 import 를 쓴다(벤더링
    시 재작성하지 않음 — upstream 대조·업데이트를 쉽게 유지하려는 선택,
    ``_vendor/mixercseg/NOTICE.md`` 참고). ``models``/``VMamba`` 는 흔한 top-level
    이름이라 프로세스의 다른 곳에서 이미 그 이름으로 뭔가를 import 했다면(가장
    흔하게는 ``models`` — Django 스타일 앱, 튜토리얼 스크립트 등 어디서든 쓰는
    이름) ``importlib.import_module("models")`` 는 그 기존 캐시를 그대로
    돌려줘 벤더 코드 대신 엉뚱한 모듈을 로드할 수 있었다(risk
    defect-detection-vendor-syspath-pollution, reviewer 지적 P1).

    그래서 ``models``/``VMamba`` 둘 다 :func:`_spec_for_vendor_package` 로
    **파일 경로를 직접 지정**해 spec 을 만든다 — ``sys.modules``/``sys.path``
    에 이미 뭐가 있든 상관없이 항상 ``_VENDOR_DIR`` 밑의 실제 파일에서
    로드됨을 보장한다(``sys.path`` 를 아예 건드리지 않으므로 이전처럼
    "일시적 sys.path 삽입" 구간에서 다른 스레드가 끼어들 여지도 없다). upstream
    내부의 'from models.xxx import ...'/'from VMamba.models... import ...'
    절대 import 가 여전히 ``sys.modules['models']``/``sys.modules['VMamba']``
    를 bare 이름으로 찾으므로, exec 직전에만 그 이름으로 등록해 둔다
    (``importlib`` 공식 문서 "Importing a source file directly" 관용구).

    로드가 끝나면(성공이든 실패든) :func:`_relocate_vendor_sys_modules` 가
    'models'/'VMamba' 계열 bare 이름을 ``sys.modules`` 에서 지운다 — 성공 시엔
    고유 접두사 밑으로 옮겨 재호출 캐시로 삼고, 실패 시엔 버린다. 호출 전에
    'models'/'VMamba' 가 이미 다른 목적으로 caching 돼 있었다면(드묾) 원래 값을
    그대로 복구한다.

    ## 재호출 안전성 — 프로세스당 최대 1회만 실제 import

    ``_vendor_build_fn_cache`` 모듈 전역에 결과를 캐시하고, 이후 호출은 그
    캐시만 반환한다(``_vendor_build_fn_lock`` 으로 동시 호출도 직렬화 —
    ``sys.modules`` 갱신 자체가 여러 스레드가 겹치면 안전하지 않은 공유 상태다).
    이 캐싱은 단순 비용 절감이 아니다 — **재호출 시 두 번째 import 자체를 아예
    실행하지 않는 것**이 안전성의 전제다: ``sys.modules`` 캐시를 로드 완료 후
    지우는 "정리"를 시도했다가 되돌린 적이 있다(2026-08-08, 같은 risk 조사) —
    실측 결과 그 프로세스에서 ``load_mixercseg_detector`` 를 두 번째 호출하면
    ``RuntimeError: Only a single TORCH_LIBRARY can be used to register the
    namespace _inductor_test``(``torch/_inductor/test_operators.py`` 재import
    시 발생)로 즉시 깨졌다 — PyTorch 의 ``TORCH_LIBRARY`` 네이티브 등록은
    프로세스 전역이라 Python 쪽 ``sys.modules`` 를 지우고 재import 해도 그
    네이티브 등록은 "처음 한 번만" 규칙을 어기면 예외를 던진다. 그래서 이
    함수는 'models'/'VMamba' bare 이름만 지우고(위 두 문단), 벤더 코드 자체의
    **재실행**은 프로세스당 정확히 1회로 게이트한다 — 두 방식을 합쳐야 "오염
    없음"과 "재호출 안전"을 동시에 만족한다.
    """
    global _vendor_build_fn_cache

    with _vendor_build_fn_lock:
        if _vendor_build_fn_cache is not None:
            return _vendor_build_fn_cache

        saved_top: dict[str, Any] = {name: sys.modules.get(name) for name in _VENDOR_TOP_NAMES}

        succeeded = False
        try:
            # VMamba 를 먼저 등록한다 — models.encoder.vss_block 이 로드 도중
            # 'from VMamba.models.vmamba import TransMixer' 를 걸어 VMamba 가
            # 먼저 sys.modules 에 있어야 한다.
            vmamba_spec = _spec_for_vendor_package("VMamba", _VENDOR_DIR / "VMamba")
            vmamba_module = importlib.util.module_from_spec(vmamba_spec)
            sys.modules["VMamba"] = vmamba_module
            if vmamba_spec.loader is not None:  # 일반 패키지면 실행할 __init__ 이 있다
                vmamba_spec.loader.exec_module(vmamba_module)

            models_spec = _spec_for_vendor_package("models", _VENDOR_DIR / "models")
            models_module = importlib.util.module_from_spec(models_spec)
            sys.modules["models"] = models_module
            assert models_spec.loader is not None  # models/__init__.py 는 항상 실존
            models_spec.loader.exec_module(models_module)
            succeeded = True
        finally:
            _relocate_vendor_sys_modules(keep=succeeded)
            for name, original in saved_top.items():
                if original is not None:
                    sys.modules[name] = original
                else:
                    sys.modules.pop(name, None)

        _vendor_build_fn_cache = models_module.build_MixerCSeg
        return _vendor_build_fn_cache


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
