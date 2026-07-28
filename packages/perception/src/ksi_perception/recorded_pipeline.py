"""Recorded 입력 production entry point — ``python -m ksi_perception.recorded_pipeline``.

녹화 이미지 시퀀스 + 텔레메트리 JSONL 을 받아 :mod:`ksi_perception.pipeline` 의
제품 orchestration 을 실행하고 Event/Evidence JSON 을 출력한다. 배포 가능한
Runtime entry point 이며 테스트 하네스가 아니다 — replay 테스트가 검증한 그
파이프라인 코드를 **동일 객체로** 호출한다(별도 orchestration 없음).

## 경계 정책 (fail-closed)

- **구성 실패는 exit 1 이다**: 모델 Registry/digest 거부·[dfine] 런타임 부재·
  이미지/텔레메트리 파일 불량은 프레임 단위 실패로 축소하지 않고 파이프라인
  시작 전에 전체를 중단한다. stderr 에 typed 사유(``CONFIG_ERROR: ...``)를 남긴다.
- **자동 다운로드 금지**: 모델은 Registry digest 검증을 통과한 로컬 디렉토리만
  (:func:`ksi_perception.dfine.load_dfine_detector` 의 ``local_files_only`` 강제).
- exit code: ``0`` 성공 · ``1`` 구성 실패 · ``2`` 사용법 오류(argparse) ·
  ``3`` 부분 실패 — 파이프라인은 완주했으나 프레임 단위 typed failure
  (FRAME_NOT_FOUND/INVALID_FRAME/INFERENCE_FAILED)가 1건 이상 기록된 실행.
  산출물은 나오지만 성공으로 위장하지 않는다.

## 텔레메트리 JSONL 계약

한 줄에 샘플 1건. 필수: ``ts_utc``·``drone_lat``·``drone_lon``·``altitude_rel_m``·
``heading_deg``·``gimbal_pitch_deg``·``camera_fov_deg``·``zoom_factor``·
``rtk_fixed``·``source_quality`` ("full"/"partial"/"degraded"). 선택:
``altitude_msl_m``·``gimbal_yaw_deg``·``gimbal_roll_deg``·``gnss_accuracy_m``.
미지 필드·비표준 상수(NaN/Infinity)·필드 누락은 구성 실패다(lax 수용 금지 —
HIL 증거 로더와 같은 정신).

## 프레임 순서는 호출자 계약이다 (P0-6)

``frames`` 인자의 나열 순서가 곧 ``frame_id`` 다. 셸 glob 은 사전순이라
``frame_10 < frame_2`` 오정렬을 조용히 만든다 — 숫자 패딩된 파일명을 쓰거나
순서를 명시적으로 나열하라(:func:`ksi_perception.recorded.load_frame_sequence`
docstring 과 동일 경고).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ksi_event_contracts.assembly import world_entity_fingerprint
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ksi_perception.pipeline import SliceFrame, SliceResult, run_vertical_slice

if TYPE_CHECKING:
    from ksi_domain.detection import Detector

RESULT_SCHEMA_V1 = "ksi-recorded-pipeline-result/1"


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
            payload = json.loads(line, parse_constant=_reject_nonstandard_json_constant)
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
        "observations": [
            o.model_dump(mode="json", by_alias=True) for o in result.observations
        ],
        "entities": [e.model_dump(mode="json", by_alias=True) for e in result.entities],
        "event_bundles": [b.model_dump(mode="json", by_alias=True) for b in result.bundles],
        "entity_fingerprints": [
            world_entity_fingerprint(e) for e in sorted(result.entities, key=lambda e: e.entity_id)
        ],
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


def _config_error(message: str) -> int:
    print(f"CONFIG_ERROR: {message}", file=sys.stderr)
    return 1


def _load_recorded_detector(
    *,
    model_dir: Path,
    model_id: str,
    min_confidence: float,
    frame_paths: list[Path],
) -> tuple[Detector, str, int, int, int] | str:
    """모델·프레임 로드 — 성공 시 (detector, model_version, count, w, h), 실패 시 사유.

    구성 로드 실패는 프레임 failure 로 축소하지 않는다 — 호출자(main)가 exit 1 로
    전체를 중단한다(fail-closed).
    """
    from ksi_perception.dfine import RecordedFrameDetector, load_dfine_detector
    from ksi_perception.recorded import load_frame_sequence, sequence_dimensions
    from ksi_perception.registry import load_model_entry

    entry_check = load_model_entry(model_id)
    if not entry_check.ok or entry_check.entry is None:
        return f"Registry 조회 실패 — {entry_check.status}: {entry_check.detail}"
    loaded = load_dfine_detector(
        local_dir=model_dir, model_id=model_id, min_confidence=min_confidence
    )
    if not loaded.ok or loaded.detector is None:
        return f"모델 로드 실패 — {loaded.status}: {loaded.detail}"

    try:
        frames = load_frame_sequence(frame_paths)
        width, height = sequence_dimensions(frames)
    except (ValueError, OSError) as exc:
        # PIL UnidentifiedImageError/DecompressionBombError 는 OSError/ValueError 계열.
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not (args.frame_interval_s > 0.0):
        return _config_error(f"--frame-interval-s 는 양수여야 한다 ({args.frame_interval_s!r})")

    try:
        telemetry = load_telemetry_jsonl(args.telemetry)
    except ValueError as exc:
        return _config_error(str(exc))

    loaded = _load_recorded_detector(
        model_dir=args.model_dir,
        model_id=args.model_id,
        min_confidence=args.min_confidence,
        frame_paths=list(args.frames),
    )
    if isinstance(loaded, str):
        return _config_error(loaded)
    detector, model_version, frame_count, width, height = loaded

    first = telemetry[0]
    drone_position = (
        float(first.drone_lat or 0.0),
        float(first.drone_lon or 0.0),
        float(first.altitude_rel_m or 0.0),
    )
    result = run_vertical_slice(
        frames=[
            SliceFrame(
                frame_id=i,
                capture_ts_utc=i * args.frame_interval_s,
                width=width,
                height=height,
            )
            for i in range(frame_count)
        ],
        detector=detector,
        telemetry=telemetry,
        drone_position=drone_position,
        model_version=model_version,
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
        # 부분 실패 — 산출물은 냈지만 성공으로 위장하지 않는다(exit 3).
        print(
            f"PARTIAL: 프레임 단위 실패 {len(result.frame_failures)}건 — "
            "diagnostics.frame_failures 참조",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
