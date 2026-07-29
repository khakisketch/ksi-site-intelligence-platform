"""Recorded 입력 production entry point — ``python -m ksi_perception.recorded_pipeline``.

녹화 이미지 시퀀스 + 텔레메트리 JSONL 을 받아 :mod:`ksi_perception.pipeline` 의
제품 orchestration 을 실행하고 Event/Evidence JSON 을 출력한다. 배포 가능한
Runtime entry point 이며 테스트 하네스가 아니다 — replay 테스트가 검증한 그
파이프라인 코드를 **동일 객체로** 호출한다(별도 orchestration 없음).

## 경계 정책 (fail-closed)

- **구성 실패는 exit 1 이다**: 모델 Registry/digest 거부·[dfine] 런타임 부재·
  이미지/텔레메트리 파일 불량은 프레임 단위 실패로 축소하지 않고 파이프라인
  시작 전에 전체를 중단한다. stderr 에 typed 사유(``CONFIG_ERROR: ...``)를 남긴다.
  CLI float 인자(``--min-confidence``·``--frame-interval-s``·``--start-ts``)는
  파싱 직후 isfinite 검증을 거친다 — ``nan``/``inf`` 는 아래의 부등식 기반 게이트
  (시간축 겹침·양수 검사)를 조용히 우회하므로 별도로 거부한다(재검증 V3 P2).
- **자동 다운로드 금지**: 모델은 Registry digest 검증을 통과한 로컬 디렉토리만
  (:func:`ksi_perception.dfine.load_dfine_detector` 의 ``local_files_only`` 강제).
- exit code: ``0`` 성공 · ``1`` 구성 실패 · ``2`` 사용법 오류(argparse) ·
  ``3`` 부분/전량 실패 — 파이프라인은 완주했으나 프레임 단위 typed failure
  (FRAME_NOT_FOUND/INVALID_FRAME/INFERENCE_FAILED)가 1건 이상 기록되거나, 분류
  계보가 형식상 존재하나 실질적으로 공허해(``EventBuildStatus.
  MISSING_CLASSIFICATION_LINEAGE``) Event 미발행이 1건 이상 기록된 실행(모든
  프레임이 실패해도 exit 3 다 — "PARTIAL"로 축소 서술하지 않고 전량이면
  stderr 에 그대로 표기한다). 산출물은 나오지만 성공으로 위장하지 않는다. 계보
  결함은 같은 배치에 유효 track 이 있어 bundles 가 비지 않아도 exit 3 다(재검증
  V3 P3) — 정책에 없는 class 등 다른 정당한 미발행 사유는 이 게이트 대상이 아니다.
  입력 자체가 공허한 경우(프레임 0장)는 프레임 단위 실패가 아니라 구성 실패
  (exit 1)다 — 처리할 게 없는 실행이 조용히 exit 0 으로 끝나지 않는다.

## 텔레메트리 JSONL 계약

한 줄에 샘플 1건. 필수: ``ts_utc``·``drone_lat``·``drone_lon``·``altitude_rel_m``·
``heading_deg``·``gimbal_pitch_deg``·``camera_fov_deg``·``zoom_factor``·
``rtk_fixed``·``source_quality`` ("full"/"partial"/"degraded"). 선택:
``altitude_msl_m``·``gimbal_yaw_deg``·``gimbal_roll_deg``·``gnss_accuracy_m``.
미지 필드·비표준 상수(NaN/Infinity, 및 오버플로 리터럴이 파싱 후 만드는
inf/-inf)·중복 키·필드 누락은 구성 실패다(lax 수용 금지 — HIL 증거 로더와
같은 정신). ``ts_utc`` 는 **절대 UTC epoch 초만** 허용한다(``[1_000_000_000,
4_102_444_800)`` — 2001-09-09~2100-01-01) — 상대 초(0.0/0.2 등)를 주면 아래
"프레임 시각" 절의 unix epoch 기준과 결합해 occurred_at 이 1970년 근방인 허구
Evidence 가 만들어지므로 파싱 단계에서 typed 거부한다.

## Registry 경로 해석

``--registry`` 우선 → 없으면 env ``KSI_MODEL_REGISTRY`` → 그마저 없으면
:data:`ksi_perception.registry.DEFAULT_REGISTRY_PATH`(저장소 루트 기준 상대
경로 — 프로세스 CWD 종속, 하위호환 기본값). CWD 가 저장소 루트가 아닌 셸에서
호출되면 기본값이 조용히 다른(또는 없는) 파일을 가리킬 수 있으므로, CI/자동화
호출은 ``--registry`` 절대경로 지정을 권장한다.

## 프레임 순서는 호출자 계약이다 (P0-6)

``frames`` 인자의 나열 순서가 곧 ``frame_id`` 다. 셸 glob 은 사전순이라
``frame_10 < frame_2`` 오정렬을 조용히 만든다 — 숫자 패딩된 파일명을 쓰거나
순서를 명시적으로 나열하라(:func:`ksi_perception.recorded.load_frame_sequence`
docstring 과 동일 경고).

## viewpoint 좌표계 — 알려진 구조적 한계 (자율 재검토 E, 부분 수정)

이 모듈은 ``drone_position`` 을 WGS84 도(度) 그대로가 아니라 ENU **미터**로
변환해 ``run_vertical_slice`` 에 넘긴다(원점=텔레메트리 첫 샘플, 대표점=프레임
시퀀스 시간 중앙점에 최근접한 샘플) — 도 단위 좌표를 그대로 미터 단위 bin
(:func:`ksi_event_contracts.observation.viewpoint_bin_id`, 기본 2m)에 넣으면
실제 수십~수백 m 이동이 전부 같은 bin 으로 뭉개진다.

**다 고치지 못한 부분**: ``run_vertical_slice`` 의 ``drone_position`` 인자는
호출 1회(=이 배치 전체)당 단일 튜플이며, ``ksi_perception.pipeline`` 내부에서
매 프레임 동일하게 재사용된다 — 그 모듈은 프레임마다 이미
``interpolator.at(frame.capture_ts_utc)`` 로 시간-최근접 샘플을 계산해 두지만,
viewpoint 계산은 그 결과 대신 이 상수 인자를 쓴다. "관측(프레임)별 시간-최근접
샘플로 viewpoint 를 bin"하려면 ``ksi_perception.pipeline`` 내부(이 파일 소유
범위 밖)를 바꿔야 한다 — 대표점 선택은 :func:`_select_representative_telemetry_sample`
docstring 참조.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ksi_event_contracts.event_bundle import event_bundle_wire_dict
from ksi_geo_core.frames import wgs84_to_enu
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ksi_perception.pipeline import (
    EventBuildStatus,
    RunContext,
    SliceFrame,
    SliceResult,
    run_vertical_slice,
)

if TYPE_CHECKING:
    from ksi_domain.detection import Detector

RESULT_SCHEMA_V1 = "ksi-recorded-pipeline-result/1"

# 절대 UTC epoch 초 허용 구간 — 상대 초(0.0/0.2/0.4 등, 자체 테스트 픽스처 관행)를
# 거부한다. 하한 2001-09-09(9자리 epoch 진입), 상한 2100-01-01(오설정 상한). 상대
# 초가 통과하면 아래 ``_UNIX_EPOCH_UTC`` 기준과 결합해 occurred_at 이 1970년
# 근방인 허구 Evidence 가 exit 0 으로 발행된다(감사 #23 이 닫은 클래스의 CLI
# 경계 재발 — 자율 재검토 A).
MIN_ABSOLUTE_TS_UTC: Final[float] = 1_000_000_000.0
MAX_ABSOLUTE_TS_UTC: Final[float] = 4_102_444_800.0

# 오버플로 리터럴(1e400 등)이 json.loads 파싱 후 inf 로 유입되는 경로를 막는
# isfinite 검증 대상 필드(자율 재검토 D-1) — 텔레메트리 계약의 모든 float.
_FINITE_FLOAT_FIELDS: Final[tuple[str, ...]] = (
    "ts_utc",
    "drone_lat",
    "drone_lon",
    "altitude_rel_m",
    "heading_deg",
    "gimbal_pitch_deg",
    "camera_fov_deg",
    "zoom_factor",
    "altitude_msl_m",
    "gimbal_yaw_deg",
    "gimbal_roll_deg",
    "gnss_accuracy_m",
)

# unix epoch 자체 — capture_ts_utc(프레임 시각)가 이미 절대 UTC epoch 초이므로
# (텔레메트리 ts_utc 는 TelemetryRecord 가 절대 epoch 만 허용하도록 강제한다,
# 자율 재검토 A) 이 기준에 더하면 정확한 절대 시각이 나온다. "1970" 은 임의의
# placeholder 가 아니라 unix epoch 그 자체이며, 상대 초 입력이 파싱 단계에서
# 이미 거부되므로 허구 occurred_at 로 이어지는 결합 경로가 없다.
_UNIX_EPOCH_UTC: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)


class TelemetryRecord(BaseModel):
    """텔레메트리 JSONL 한 줄의 typed 계약 — lax coercion 없이 검증한다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ts_utc: float
    drone_lat: float
    drone_lon: float
    altitude_rel_m: float
    heading_deg: float
    gimbal_pitch_deg: float
    camera_fov_deg: float
    zoom_factor: float
    rtk_fixed: bool
    # 값 기반 수용(strict=False) — JSON 문자열 "full" 을 enum 으로 받되 미지 값은
    # 거부한다(onnx_manifest 의 dtype 필드와 동일 패턴).
    source_quality: SourceQuality = Field(default=SourceQuality.FULL, strict=False)

    altitude_msl_m: float | None = None
    gimbal_yaw_deg: float | None = None
    gimbal_roll_deg: float | None = None
    gnss_accuracy_m: float | None = None

    @field_validator(*_FINITE_FLOAT_FIELDS)
    @classmethod
    def _reject_nonfinite(cls, value: float | None) -> float | None:
        """오버플로 리터럴(``1e400`` 등)은 json.loads 파싱을 통과해 inf 로
        유입된다 — ``NaN``/``Infinity`` JSON 상수 거부(``_reject_nonstandard_
        json_constant``)와는 별개 채널이라 파싱 후 여기서 따로 막는다(자율
        재검토 D-1)."""
        if value is not None and not math.isfinite(value):
            raise ValueError(f"비유한(non-finite) float 값 불허 — {value!r}")
        return value

    @field_validator("ts_utc")
    @classmethod
    def _reject_relative_ts(cls, value: float) -> float:
        """상대 초(0.0/0.2 등) 거부 — 절대 UTC epoch 초만 허용한다.

        상대 초가 ``_UNIX_EPOCH_UTC`` 기준과 결합하면 occurred_at 1970년 근방의
        허구 Evidence 가 exit 0 으로 발행된다(감사 #23 이 닫은 클래스의 CLI
        경계 재발 — 자율 재검토 A, P1)."""
        if not (MIN_ABSOLUTE_TS_UTC <= value < MAX_ABSOLUTE_TS_UTC):
            raise ValueError(
                f"ts_utc={value!r} 는 절대 UTC epoch 초가 아니다 — 상대 시각"
                "(0.0/0.2 등) 금지, 절대 epoch 초 필요"
                f"(허용 구간 [{MIN_ABSOLUTE_TS_UTC}, {MAX_ABSOLUTE_TS_UTC}))"
            )
        return value

    def to_sample(self) -> TelemetrySample:
        return TelemetrySample(
            ts=TimestampSet(
                source_ts_utc=self.ts_utc,
                receive_ts_utc=self.ts_utc,
                capture_ts_utc=self.ts_utc,
            ),
            drone_lat=self.drone_lat,
            drone_lon=self.drone_lon,
            altitude_msl_m=self.altitude_msl_m,
            altitude_rel_m=self.altitude_rel_m,
            heading_deg=self.heading_deg,
            gimbal_pitch_deg=self.gimbal_pitch_deg,
            gimbal_yaw_deg=self.gimbal_yaw_deg,
            gimbal_roll_deg=self.gimbal_roll_deg,
            camera_fov_deg=self.camera_fov_deg,
            zoom_factor=self.zoom_factor,
            rtk_fixed=self.rtk_fixed,
            gnss_accuracy_m=self.gnss_accuracy_m,
            source_quality=self.source_quality,
        )


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"비표준 JSON 상수 {value!r} 불허 (NaN/Infinity)")


def _reject_duplicate_json_key(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """object_pairs_hook — JSON 객체 중복 키의 '마지막 값 채택'을 typed 거부로
    막는다(자율 재검토 D-2).

    표준 ``json`` 모듈은 ``{"a": 1, "a": 2}`` 를 조용히 ``{"a": 2}`` 로 만든다 —
    손으로 합치거나 편집한 텔레메트리 JSONL 에서 흔한 오염 형태이며, 어느 값이
    채택됐는지 호출자가 알 길이 없다.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"중복 키 {key!r} — JSON 객체는 키가 유일해야 한다")
        seen[key] = value
    return seen


def load_telemetry_jsonl(path: Path) -> list[TelemetrySample]:
    """텔레메트리 JSONL → TelemetrySample 목록. 불량 라인은 구성 실패(ValueError)다.

    부분 성공을 허용하지 않는다 — 텔레메트리가 의심스러우면 그 실행 전체가
    의심스럽다(보간이 불량 샘플 사이를 그럴듯하게 메꿔 조용한 좌표 오염이 된다).
    """
    if not path.is_file():
        raise ValueError(f"텔레메트리 파일이 없다: {path}")
    samples: list[TelemetrySample] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(
                line,
                parse_constant=_reject_nonstandard_json_constant,
                object_pairs_hook=_reject_duplicate_json_key,
            )
        except ValueError as exc:
            raise ValueError(f"{path}:{line_no}: JSON 파싱 실패 — {exc}") from exc
        try:
            record = TelemetryRecord.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_no}: 텔레메트리 계약 위반 — {exc}") from exc
        samples.append(record.to_sample())
    if not samples:
        raise ValueError(f"{path}: 텔레메트리 샘플 0건 — 빈 파일로는 보간할 수 없다")
    return samples


def serialize_result(
    result: SliceResult,
    *,
    model_id: str,
    model_version: str,
    frame_count: int,
    width: int,
    height: int,
) -> dict:
    """SliceResult → 결정적 JSON-safe dict (typed diagnostics 포함)."""
    return {
        "schema": RESULT_SCHEMA_V1,
        "model": {"model_id": model_id, "model_version": model_version},
        "frames": {"count": frame_count, "width": width, "height": height},
        # observations/entities 도 wire 규약(exclude_none)이다 — bundles 만 적용하면
        # entities 의 null 방출이 world-entity.v1.json 을 위반한다(자율 재검토 P1-C1,
        # 감사 #28 과 동일 클래스가 형제 계약에서 재발한 것).
        "observations": [
            o.model_dump(mode="json", by_alias=True, exclude_none=True)
            for o in result.observations
        ],
        "entities": [
            e.model_dump(mode="json", by_alias=True, exclude_none=True)
            for e in result.entities
        ],
        # wire 규약 SSOT(event_bundle_wire_dict) — null 방출은 스키마 위반이다(감사 #28).
        "event_bundles": [event_bundle_wire_dict(b) for b in result.bundles],
        # 재현성 지문의 정본은 SliceResult.entity_fingerprints() 하나다(감사 #2 —
        # 정렬 기준이 다른 재구현은 내부 테스트와 산출물 순서를 갈라놓는다).
        "entity_fingerprints": result.entity_fingerprints(),
        "diagnostics": {
            "frame_failures": [
                {
                    "frame_id": f.frame_id,
                    "capture_ts_utc": f.capture_ts_utc,
                    "status": f.status.value,
                    "detail": f.detail,
                    "model_version": f.model_version,
                }
                for f in result.frame_failures
            ],
            "dropped": [
                {
                    "frame_id": d.frame_id,
                    "track_id": d.track_id,
                    "stage": d.stage.value,
                    "reason": d.reason,
                }
                for d in result.dropped
            ],
            "clipped": [
                {"frame_id": f, "area_kept": a, "detail": detail}
                for f, a, detail in result.clipped_detections
            ],
            "assembly_failures": [
                {"track_id": t, "status": s.value, "detail": detail}
                for t, s, detail in result.assembly_failures
            ],
            "unpublished_events": [
                {"entity_id": e, "entity_class": c, "reason": r}
                for e, c, r in result.unpublished_events
            ],
        },
    }


def _edge_version() -> str:
    """실행 중인 perception 패키지의 실버전 — 하드코딩 placeholder 가 아니다."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"ksi-perception/{version('ksi-perception')}"
    except PackageNotFoundError:  # 소스 트리 직접 실행 등
        return "ksi-perception/unpackaged"


def _config_error(message: str) -> int:
    print(f"CONFIG_ERROR: {message}", file=sys.stderr)
    return 1


def _load_recorded_detector(
    *,
    model_dir: Path,
    model_id: str,
    min_confidence: float,
    frame_paths: list[Path],
    registry_path: Path,
) -> tuple[Detector, str, int, int, int] | str:
    """모델·프레임 로드 — 성공 시 (detector, model_version, count, w, h), 실패 시 사유.

    구성 로드 실패는 프레임 failure 로 축소하지 않는다 — 호출자(main)가 exit 1 로
    전체를 중단한다(fail-closed).
    """
    from PIL import Image as PILImage

    from ksi_perception.dfine import RecordedFrameDetector, load_dfine_detector
    from ksi_perception.recorded import load_frame_sequence, sequence_dimensions
    from ksi_perception.registry import load_model_entry

    entry_check = load_model_entry(model_id, registry_path=registry_path)
    if not entry_check.ok or entry_check.entry is None:
        return f"Registry 조회 실패 — {entry_check.status}: {entry_check.detail}"
    loaded = load_dfine_detector(
        local_dir=model_dir,
        model_id=model_id,
        min_confidence=min_confidence,
        # load_dfine_detector 는 verify_local_model 을 위해 **자체** registry_path
        # 를 또 읽는다(기본값은 여기와 별개로 CWD 상대) — 위에서 넘긴 registry_path
        # 를 여기도 전달하지 않으면 두 번째 검증이 --registry/env 를 무시하고
        # 조용히 기본 경로로 새는 결함이 된다(자율 재검토 C 완결).
        registry_path=registry_path,
    )
    if not loaded.ok or loaded.detector is None:
        return f"모델 로드 실패 — {loaded.status}: {loaded.detail}"

    try:
        frames = load_frame_sequence(frame_paths)
        width, height = sequence_dimensions(frames)
    except (ValueError, OSError, PILImage.DecompressionBombError) as exc:
        # PIL UnidentifiedImageError 는 OSError 계열이지만 DecompressionBombError
        # 는 Exception 직속(OSError/ValueError 서브클래스가 아니다) — 튜플 밖에
        # 두면 미포착 traceback 으로 CLI 가 죽어 typed CONFIG_ERROR 계약이 샌다
        # (자율 재검토 B, P2).
        return f"프레임 로드 실패 — {type(exc).__name__}: {exc}"

    detector = RecordedFrameDetector(frames=frames, dfine=loaded.detector)
    model_version = f"{model_id}@{entry_check.entry.revision[:8]}"
    return detector, model_version, len(frames), width, height


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ksi_perception.recorded_pipeline",
        description=(
            "녹화 이미지 시퀀스 + 텔레메트리 JSONL → Perception 파이프라인 실행 "
            "→ Event/Evidence JSON. 모델은 Registry digest 검증 로컬 디렉토리만"
            "(자동 다운로드 금지)."
        ),
    )
    parser.add_argument(
        "frames",
        nargs="+",
        type=Path,
        help="녹화 프레임 이미지(나열 순서 = frame_id — 셸 glob 사전순 오정렬 주의)",
    )
    parser.add_argument("--telemetry", type=Path, required=True, help="텔레메트리 JSONL 경로")
    parser.add_argument(
        "--model-dir", type=Path, required=True, help="Registry 검증 대상 모델 디렉토리"
    )
    parser.add_argument(
        "--model-id",
        default="ksi-person-detector-dfine-s-coco",
        help="Model Registry 항목 id (기본: %(default)s)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        required=True,
        help=(
            "detection 채택 문턱 — 명시적 운용 선택이라 기본값이 없다"
            "(0.0 은 300-query 노이즈 폭주 실측, 실기 배포값은 HIL 측정으로 확정)"
        ),
    )
    parser.add_argument(
        "--frame-interval-s",
        type=float,
        required=True,
        help="프레임 간 간격(초) — capture_ts = frame_id × interval",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="결과 JSON 경로(생략 시 stdout)"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help=(
            "Model Registry YAML 경로. 해석 순서: --registry 우선 → 없으면 env "
            "KSI_MODEL_REGISTRY → 그마저 없으면 "
            "ksi_perception.registry.DEFAULT_REGISTRY_PATH(저장소 루트 기준 "
            "상대경로, 프로세스 CWD 종속 — 하위호환 기본값)"
        ),
    )
    # 계보 신원 — 기본값이 없다(INV-040/042, 감사 #23). placeholder 로 채워진
    # Evidence 가 Core durable 원장에 영구 기록되는 것을 CLI 경계에서 막는다.
    parser.add_argument("--mission-id", required=True, help="이 재생이 귀속되는 임무 id")
    parser.add_argument("--site-id", required=True, help="현장 id")
    parser.add_argument(
        "--site-frame", required=True,
        help='현장 좌표계 참조(예: "EPSG:4326+WGS84@site-1.0.0")',
    )
    parser.add_argument("--sensor-id", required=True, help="녹화 카메라/센서 식별자")
    parser.add_argument("--policy-version", required=True, help="적용 정책 버전")
    parser.add_argument(
        "--calibration-profile-id", required=True, help="캘리브레이션 프로파일 id"
    )
    parser.add_argument(
        "--start-ts",
        type=float,
        default=None,
        help=(
            "프레임 0 의 절대 시각(UTC epoch 초) — 생략 시 텔레메트리 첫 샘플 시각. "
            "프레임 시각 구간이 텔레메트리 구간과 겹치지 않으면 구성 실패다(감사 #24)"
        ),
    )
    return parser


def _select_representative_telemetry_sample(
    telemetry: list[TelemetrySample], midpoint_ts: float
) -> TelemetrySample:
    """시간 중앙점에 가장 가까운 텔레메트리 샘플 하나를 고른다.

    ## 알려진 구조적 한계 (자율 재검토 E — 이 파일 소유 범위의 최선)

    ``run_vertical_slice`` 의 ``drone_position`` 인자는 호출 1회(=배치 전체)당
    단일 튜플이며, ``ksi_perception.pipeline`` 내부(이 파일 소유 밖)가 매 프레임
    동일한 값을 재사용한다 — 그 모듈은 프레임마다 이미
    ``interpolator.at(frame.capture_ts_utc)`` 로 시간-최근접 샘플을 계산해 두지만
    viewpoint 계산은 그 결과 대신 이 함수가 고른 단일 대표값을 쓴다. "관측
    (프레임)별 시간-최근접 샘플로 viewpoint 를 bin"하는 완전한 수정은
    ``ksi_perception.pipeline`` 을 바꿔야 하므로 이 함수만으로는 닫히지 않는다.
    여기서는 배치 전체가 공유하는 단일 대표점을 "항상 첫 샘플"보다 낫게(시간
    중앙점 최근접) 고르는 것까지만 한다.
    """
    dated = [
        (sample, sample.ts.capture_ts_utc)
        for sample in telemetry
        if isinstance(sample.ts, TimestampSet) and sample.ts.capture_ts_utc is not None
    ]
    if not dated:
        return telemetry[0]  # 방어적 폴백 — 호출 시점엔 이미 telemetry_ts 비공허 확인됨
    return min(dated, key=lambda pair: abs(pair[1] - midpoint_ts))[0]


def _nonfinite_cli_error(flag: str, value: float) -> str | None:
    """CLI float 인자 공통 isfinite 게이트(재검증 V3 P2) — 텔레메트리 필드에는
    이미 있는 ``isfinite`` 방어(``_reject_nonfinite``)가 CLI argparse 인자에는
    없어, ``--start-ts nan`` 은 시간축 겹침 부등식을 전부 False 로 만들어 exit 3
    오진(실제로는 거부돼야 할 구성이 프레임 실패로 오분류)을 낳고, ``--frame-
    interval-s inf`` 는 ``> 0`` 양수 검사를 조용히 통과한다. 두 값 모두 파싱
    직후 여기서 거부한다."""
    if not math.isfinite(value):
        return f"--{flag} 는 유한(finite) 값이어야 한다(nan/inf 불허) — {value!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    for flag, value in (
        ("min-confidence", args.min_confidence),
        ("frame-interval-s", args.frame_interval_s),
    ):
        nonfinite_error = _nonfinite_cli_error(flag, value)
        if nonfinite_error:
            return _config_error(nonfinite_error)
    if args.start_ts is not None:
        nonfinite_error = _nonfinite_cli_error("start-ts", args.start_ts)
        if nonfinite_error:
            return _config_error(nonfinite_error)

    if not (args.frame_interval_s > 0.0):
        return _config_error(f"--frame-interval-s 는 양수여야 한다 ({args.frame_interval_s!r})")

    registry_path = args.registry
    if registry_path is None:
        env_registry = os.environ.get("KSI_MODEL_REGISTRY")
        if env_registry:
            registry_path = Path(env_registry)
        else:
            from ksi_perception.registry import DEFAULT_REGISTRY_PATH

            registry_path = DEFAULT_REGISTRY_PATH

    try:
        telemetry = load_telemetry_jsonl(args.telemetry)
    except ValueError as exc:
        return _config_error(str(exc))

    loaded = _load_recorded_detector(
        model_dir=args.model_dir,
        model_id=args.model_id,
        min_confidence=args.min_confidence,
        frame_paths=list(args.frames),
        registry_path=registry_path,
    )
    if isinstance(loaded, str):
        return _config_error(loaded)
    detector, model_version, frame_count, width, height = loaded

    if frame_count == 0:
        # 입력 자체가 공허하다 — 프레임 단위 typed failure 로 축소되면 exit 3
        # 이지만, 처리할 게 아예 없는 실행은 그와 다른 구성 실패다(exit 1).
        # argparse 의 nargs="+" 가 CLI 경로에서 이를 이미 막지만, 로더 계층이
        # 0장을 반환하는 경로까지 fail-closed 로 방어한다(자율 재검토 F).
        return _config_error("프레임 0장 — 처리할 입력이 없다(빈 시퀀스는 프레임 소스가 아니다)")

    # 프레임 시각을 텔레메트리와 **같은 절대 시간축**으로 만든다(감사 #24) —
    # 초판은 프레임을 0초부터 상대 시각으로 만들었고, 실제 UTC 로그를 주면 전
    # detection 이 보간 gap 으로 전량 탈락하는데 exit 0(성공)으로 끝났다.
    telemetry_ts = [
        sample.ts.capture_ts_utc
        for sample in telemetry
        if isinstance(sample.ts, TimestampSet) and sample.ts.capture_ts_utc is not None
    ]
    if not telemetry_ts:
        return _config_error("텔레메트리에 capture 시각이 없다 — 시간축 기준을 세울 수 없다")
    frame_base_ts = args.start_ts if args.start_ts is not None else min(telemetry_ts)
    frame_last_ts = frame_base_ts + (frame_count - 1) * args.frame_interval_s
    if frame_last_ts < min(telemetry_ts) or frame_base_ts > max(telemetry_ts):
        return _config_error(
            f"프레임 시각 구간 [{frame_base_ts}, {frame_last_ts}] 이 텔레메트리 구간 "
            f"[{min(telemetry_ts)}, {max(telemetry_ts)}] 과 겹치지 않는다 — 시간축 "
            "불일치 상태의 재생은 전량 무산출이 된다(--start-ts 확인)"
        )

    # viewpoint 참조점 — 원점(=텔레메트리 첫 샘플)기준 ENU **미터**로 변환한다
    # (자율 재검토 E, 부분 수정 — 전체 수정은 ksi_perception.pipeline 소유,
    # 위 모듈 docstring "viewpoint 좌표계" 절 참조). 도(度) 그대로 미터 bin 에
    # 넣으면 실제 이동이 전부 같은 bin 으로 뭉개진다.
    first = telemetry[0]
    origin_lat = float(first.drone_lat or 0.0)
    origin_lon = float(first.drone_lon or 0.0)
    origin_alt = float(first.altitude_rel_m or 0.0)
    representative = _select_representative_telemetry_sample(
        telemetry, (frame_base_ts + frame_last_ts) / 2.0
    )
    east_m, north_m = wgs84_to_enu(
        origin_lat,
        origin_lon,
        float(representative.drone_lat or 0.0),
        float(representative.drone_lon or 0.0),
    )
    up_m = float(representative.altitude_rel_m or 0.0) - origin_alt
    drone_position = (east_m, north_m, up_m)

    context = RunContext(
        mission_id=args.mission_id,
        site_id=args.site_id,
        site_frame=args.site_frame,
        epoch_utc=_UNIX_EPOCH_UTC,
        model_version=model_version,
        policy_version=args.policy_version,
        calibration_profile_id=args.calibration_profile_id,
        edge_version=_edge_version(),
        sensor_id=args.sensor_id,
    )
    result = run_vertical_slice(
        frames=[
            SliceFrame(
                frame_id=i,
                capture_ts_utc=frame_base_ts + i * args.frame_interval_s,
                width=width,
                height=height,
            )
            for i in range(frame_count)
        ],
        detector=detector,
        telemetry=telemetry,
        drone_position=drone_position,
        context=context,
    )

    payload = serialize_result(
        result,
        model_id=args.model_id,
        model_version=model_version,
        frame_count=frame_count,
        width=width,
        height=height,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out is None:
        print(rendered)
    else:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    if result.frame_failures:
        # 부분/전량 실패 — 산출물은 냈지만 성공으로 위장하지 않는다(exit 3).
        # 처리된 프레임 전량이 실패해도 같은 exit 3 다(자율 재검토 F) — 다만
        # "PARTIAL" 이라는 label 자체가 전량 실패를 축소 서술하지 않도록
        # 실제 비율을 함께 남긴다.
        label = "TOTAL" if len(result.frame_failures) >= frame_count else "PARTIAL"
        print(
            f"{label}: 프레임 단위 실패 {len(result.frame_failures)}/{frame_count}건 — "
            "diagnostics.frame_failures 참조",
            file=sys.stderr,
        )
        return 3
    lineage_defects = [
        (entity_id, entity_class, reason)
        for entity_id, entity_class, reason in result.unpublished_events
        if reason.startswith(f"{EventBuildStatus.MISSING_CLASSIFICATION_LINEAGE}:")
    ]
    if lineage_defects:
        # 실질 공허 계보(빈 원시 id/이름·공백 class 등)는 typed MISSING_CLASSIFICATION_
        # LINEAGE 미발행으로 흡수되도록 고쳐졌지만(pipeline.py), 같은 배치에 유효
        # track 이 하나라도 있어 bundles 가 비지 않으면 아래 "관측은 있는데 Event
        # 0건" 게이트(bundles 전량 빌 때만 발동)를 피해가 exit 0 으로 위장된다
        # (재검증 V3 P3). 계보 결함은 다른 정당한 미발행 사유(정책에 없는 class 등)
        # 와 달리 그 자체로 Evidence 누락이므로 bundles 잔존 여부와 무관하게 exit
        # 3 이다 — 다른 사유(unsupported_event_policy 등)까지 넓히지는 않는다.
        print(
            f"PARTIAL: 분류 계보 결함으로 Event 미발행 {len(lineage_defects)}건 — "
            f"diagnostics.unpublished_events 참조 (예: {lineage_defects[0][2]})",
            file=sys.stderr,
        )
        return 3
    if result.observations and not result.bundles and (
        result.assembly_failures or result.unpublished_events
    ):
        # 관측은 있는데 Event 가 0건 — 조립(융합 창 초과 등)·발행 단계 전량 탈락이다.
        # "감지했지만 아무 사건도 안 됐다"가 성공(exit 0)으로 위장되면 안 된다
        # (자율 재검토 P1-B1 — track 관측창 1.0s 초과가 대표 재현).
        print(
            "PARTIAL: 관측은 있으나 Event 0건 — "
            f"assembly_failures {len(result.assembly_failures)}건, "
            f"unpublished {len(result.unpublished_events)}건 (diagnostics 참조)",
            file=sys.stderr,
        )
        return 3
    if not result.observations and (result.dropped or result.clipped_detections):
        # detection 은 있었는데 관측 산출이 0 — 시간축/투영 계열의 전량 탈락이다.
        # "드론이 아무것도 못 봤다"와 구분되어야 하므로 성공으로 위장하지 않는다
        # (감사 #24).
        print(
            f"PARTIAL: detection 은 발생했으나 관측 산출 0건(탈락 {len(result.dropped)}건) — "
            "diagnostics.dropped 참조(시간축·투영 점검)",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
