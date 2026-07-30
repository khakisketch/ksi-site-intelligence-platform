"""Recorded production entry point 계약 (PRODUCTION EDGE RUNTIME PROMOTION).

고정하는 것:

1. **entry point 가 production pipeline 을 실제로 호출한다** — CLI ``main`` 이
   :func:`ksi_perception.pipeline.run_vertical_slice` 를 경유해 산출물을 만든다.
   파이프라인 호출을 제거하면 이 파일의 통합 테스트가 실패한다(공허 방지 앵커).
2. **구성 실패는 fail-closed exit 1** — Registry 거부·파일 불량·텔레메트리 계약
   위반은 프레임 단위 실패로 축소되지 않고 실행 전에 전체를 중단한다.
3. **텔레메트리 JSONL 은 lax 수용이 없다** — 미지 필드·NaN·필드 누락은 거부.

실모델 성공 경로는 모델 보유 환경의 test_recorded_slice(실 D-FINE E2E)가 담당
하고, 여기서는 stub detector 주입으로 entry 배선 자체를 CI 에서 상시 고정한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from ksi_geo_core.timestamps import TimestampSet
from ksi_perception import recorded_pipeline
from ksi_perception.recorded_pipeline import (
    TelemetryRecord,
    load_telemetry_jsonl,
    main,
    serialize_result,
)

# 픽스처는 replay 트리 소유(HIL 테스트의 tools/hil 경로 주입과 같은 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "replay"))
from vertical_slice import (  # noqa: E402
    ScriptedDetector,
    make_run_context,
    person_detection,
    run_vertical_slice,
    synthetic_telemetry,
)

# CLI 계보 필수 인자(감사 #23 — 기본값 없는 RunContext 의 CLI 대응부).
_LINEAGE_ARGS = [
    "--mission-id", "test-mission-001",
    "--site-id", "test-site-001",
    "--site-frame", "EPSG:4326+WGS84@slice-1.0.0",
    "--sensor-id", "test-wide-camera",
    "--policy-version", "test-policy-0",
    "--calibration-profile-id", "test-cal-0",
]

# 절대 UTC epoch 초 기준(2023-11-14 근방) — 텔레메트리 ts_utc 는 상대 초를
# 거부하므로(자율 재검토 A) 픽스처 기본값도 절대 epoch 이어야 한다.
_ABS_TS_BASE = 1_700_000_000.0


def _main(argv: list[str]) -> int:
    """모든 CLI 테스트가 같은 계보 인자를 지참한다 — 개별 테스트는 차이만 기술."""
    return main(argv + _LINEAGE_ARGS)


def _telemetry_line(ts: float = _ABS_TS_BASE, overrides: dict[str, object] | None = None) -> str:
    payload: dict[str, object] = {
        "ts_utc": ts,
        "drone_lat": 37.5,
        "drone_lon": 127.0,
        "altitude_rel_m": 60.0,
        "heading_deg": 0.0,
        "gimbal_pitch_deg": -60.0,
        "camera_fov_deg": 84.0,
        "zoom_factor": 1.0,
        "rtk_fixed": True,
        "source_quality": "full",
    }
    payload.update(overrides or {})
    return json.dumps(payload)


# ── 텔레메트리 JSONL 계약 ────────────────────────────────────────────────────


def test_telemetry_jsonl_loads_valid_lines(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text(
        _telemetry_line(_ABS_TS_BASE) + "\n" + _telemetry_line(_ABS_TS_BASE + 0.2) + "\n",
        encoding="utf-8",
    )
    samples = load_telemetry_jsonl(path)
    assert len(samples) == 2
    assert samples[0].drone_lat == 37.5
    assert samples[0].rtk_fixed is True


@pytest.mark.parametrize(
    ("mutation", "expect"),
    [
        ({"unknown_field": 1}, "미지 필드"),
        ({"drone_lat": "37.5"}, "문자열 위장(strict)"),
        ({"rtk_fixed": 1}, "bool 위장(strict)"),
        ({"source_quality": "excellent"}, "미지 quality"),
    ],
)
def test_telemetry_contract_violations_rejected(
    tmp_path: Path, mutation: dict[str, object], expect: str
) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text(_telemetry_line(overrides=mutation) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="계약 위반"):
        load_telemetry_jsonl(path)


def test_telemetry_missing_required_field_rejected(tmp_path: Path) -> None:
    payload = json.loads(_telemetry_line())
    del payload["gimbal_pitch_deg"]
    path = tmp_path / "telemetry.jsonl"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="계약 위반"):
        load_telemetry_jsonl(path)


def test_telemetry_nan_constant_rejected(tmp_path: Path) -> None:
    """NaN 텔레메트리는 보간을 타고 조용한 좌표 오염이 된다 — 파싱 단계 거부."""
    path = tmp_path / "telemetry.jsonl"
    path.write_text(_telemetry_line().replace("60.0", "NaN", 1) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 파싱 실패"):
        load_telemetry_jsonl(path)


def test_telemetry_empty_file_rejected(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="샘플 0건"):
        load_telemetry_jsonl(path)


def test_telemetry_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="파일이 없다"):
        load_telemetry_jsonl(tmp_path / "no-such.jsonl")


def test_telemetry_record_roundtrip_to_sample() -> None:
    record = TelemetryRecord.model_validate(json.loads(_telemetry_line(_ABS_TS_BASE + 1.5)))
    sample = record.to_sample()
    assert isinstance(sample.ts, TimestampSet)
    assert sample.ts.capture_ts_utc == _ABS_TS_BASE + 1.5
    assert sample.gimbal_pitch_deg == -60.0


@pytest.mark.parametrize("relative_ts", [0.0, 0.2, 0.4, 999.0])
def test_telemetry_relative_ts_rejected(tmp_path: Path, relative_ts: float) -> None:
    """[자율 재검토 A] 상대 초(자체 앵커 픽스처 관행)는 unix epoch 기준과 결합해
    occurred_at 1970년 근방의 허구 Evidence 를 만든다 — 절대 UTC epoch 초만
    허용한다(파싱 단계 typed 거부)."""
    path = tmp_path / "telemetry.jsonl"
    path.write_text(_telemetry_line(relative_ts) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="절대 UTC epoch"):
        load_telemetry_jsonl(path)


def test_telemetry_future_overflow_ts_rejected(tmp_path: Path) -> None:
    """[A] 상한(2100-01-01) 이상의 ts_utc 도 절대 epoch 구간 밖이라 거부된다."""
    path = tmp_path / "telemetry.jsonl"
    path.write_text(_telemetry_line(4_102_444_800.0) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="절대 UTC epoch"):
        load_telemetry_jsonl(path)


def test_telemetry_overflow_literal_rejected(tmp_path: Path) -> None:
    """[자율 재검토 D-1] 오버플로 리터럴(1e400)은 json.loads 파싱을 통과해 inf 로
    유입된다 — NaN 과 같은 typed 채널(isfinite)로 별도 거부해야 한다."""
    path = tmp_path / "telemetry.jsonl"
    path.write_text(_telemetry_line().replace("60.0", "1e400", 1) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="비유한"):
        load_telemetry_jsonl(path)


def test_telemetry_duplicate_json_key_rejected(tmp_path: Path) -> None:
    """[자율 재검토 D-2] JSON 객체 중복 키는 표준 json 모듈이 마지막 값을 조용히
    채택한다 — typed 거부로 막는다."""
    line = _telemetry_line()
    assert line.endswith("}")
    dup_line = f'{line[:-1]}, "heading_deg": 999.0}}'
    path = tmp_path / "telemetry.jsonl"
    path.write_text(dup_line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="중복 키"):
        load_telemetry_jsonl(path)


# ── CLI 구성 실패 fail-closed ────────────────────────────────────────────────


def test_cli_missing_telemetry_is_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry",
            str(tmp_path / "no-such.jsonl"),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0.2",
        ]
    )
    assert code == 1
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_cli_model_load_failure_is_config_error_not_frame_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """모델 Registry/artifact 실패는 파이프라인 시작 전 전체 중단(exit 1)이다."""
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(_telemetry_line() + "\n", encoding="utf-8")
    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry",
            str(telemetry),
            "--model-dir",
            str(tmp_path / "empty-model-dir"),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0.2",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "CONFIG_ERROR" in err and "모델 로드 실패" in err


def test_cli_nonpositive_interval_is_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry",
            str(tmp_path / "t.jsonl"),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0",
        ]
    )
    assert code == 1
    assert "frame-interval-s" in capsys.readouterr().err


def test_cli_nan_start_ts_is_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[재검증 V3 P2] ``--start-ts nan`` 은 시간축 겹침 게이트의 부등식
    (``frame_last_ts < min(...)`` / ``frame_base_ts > max(...)``)을 전부 False
    로 만들어 겹침 검사를 조용히 통과시킨다 — isfinite 검증으로 파싱 직후 거부."""
    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry",
            str(tmp_path / "t.jsonl"),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0.2",
            "--start-ts",
            "nan",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "CONFIG_ERROR" in err
    assert "start-ts" in err


def test_cli_infinite_frame_interval_is_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[재검증 V3 P2] ``--frame-interval-s inf`` 는 기존 ``> 0`` 양수 검사를
    조용히 통과한다 — isfinite 검증으로 별도 거부."""
    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry",
            str(tmp_path / "t.jsonl"),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "inf",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "CONFIG_ERROR" in err
    assert "frame-interval-s" in err


def test_cli_relative_telemetry_ts_is_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 A, 회귀] 상대 초(0.0/0.2/0.4) 텔레메트리는 1970 unix epoch
    기준과 결합해 허구 occurred_at Evidence 를 만드는 경로였다 — 파싱 단계에서
    exit 1 로 거부되고 산출물을 남기지 않는다(파이프라인 시작 전 전체 중단)."""
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(ts) for ts in (0.0, 0.2, 0.4)) + "\n", encoding="utf-8"
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 1
    assert "CONFIG_ERROR" in capsys.readouterr().err
    assert not out.exists(), "구성 실패인데 산출물이 생겼다"


def test_cli_frame_count_zero_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 F] 로더가 빈 시퀀스(frame_count=0)를 반환하면 프레임 단위
    typed failure(exit 3)가 아니라 구성 실패(exit 1)다 — 입력 자체가 공허한
    실행이 조용히 exit 0 으로 끝나지 않는다."""

    def _empty_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
        return ScriptedDetector({}), "scripted-stub-0", 0, 1920, 1080

    monkeypatch.setattr(recorded_pipeline, "_load_recorded_detector", _empty_loader)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(_telemetry_line() + "\n", encoding="utf-8")
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "CONFIG_ERROR" in err
    assert "프레임 0장" in err
    assert not out.exists()


def test_load_recorded_detector_decompression_bomb_is_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[자율 재검토 B] PIL DecompressionBombError 는 Exception 직속이라
    (ValueError, OSError) 튜플 밖이다 — 별도 포착 없인 typed 실패 문자열 대신
    미포착 예외로 CLI 가 죽는다(구성 실패 typed 계약 누수)."""
    from typing import cast

    import ksi_perception.dfine as dfine_mod
    import ksi_perception.recorded as recorded_mod
    import ksi_perception.registry as registry_mod
    from PIL import Image

    monkeypatch.setattr(
        registry_mod,
        "load_model_entry",
        lambda model_id, *, registry_path=None: registry_mod.RegistryCheck(
            status=registry_mod.RegistryStatus.OK,
            entry=registry_mod.ModelEntry(
                model_id=model_id,
                weights_source="local-test",
                revision="deadbeefcafefeed",
                file_digests={"model.onnx": "a" * 64},
                person_label_id=0,
                production_status="staging",
            ),
        ),
    )
    monkeypatch.setattr(
        dfine_mod,
        "load_dfine_detector",
        lambda **_kw: dfine_mod.DFineLoadResult(
            status=dfine_mod.DFineLoadStatus.OK,
            detector=cast("dfine_mod.DFineDetector", object()),
        ),
    )

    def _raise_bomb(*_a: object, **_kw: object) -> None:
        raise Image.DecompressionBombError("합성 폭탄 이미지 주입(테스트)")

    monkeypatch.setattr(recorded_mod, "load_frame_sequence", _raise_bomb)

    result = recorded_pipeline._load_recorded_detector(
        model_dir=tmp_path,
        model_id="test-model",
        min_confidence=0.5,
        frame_paths=[tmp_path / "f0.jpg"],
        registry_path=tmp_path / "unused-registry.yaml",
    )
    assert isinstance(result, str), "typed 실패 문자열이 아니라 예외가 새어나갔다"
    assert "DecompressionBombError" in result


def test_cli_registry_flag_resolves_absolute_path_from_any_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 C] --registry 절대경로는 프로세스 CWD 와 무관하게 해석된다 —
    기본값(저장소 루트 기준 상대경로, CWD 종속)이 아닌 다른 registry 를 명시적으로
    가리킬 수 있어야 한다. ``load_dfine_detector`` 가 내부에서 registry 를 다시
    읽는 2차 경로까지 같은 registry_path 를 받는지도 함께 고정한다."""
    registry_yaml = tmp_path / "custom_registry.yaml"
    registry_yaml.write_text(
        "\n".join(
            [
                "models:",
                "  - model_id: custom-registry-test",
                "    weights:",
                "      source: local-test",
                "      revision: deadbeefcafefeed",
                "      files:",
                "        - name: model.onnx",
                f'          sha256: "{"a" * 64}"',
                "    pretraining:",
                "      objects365_used: false",
                "      visdrone_used: false",
                "    model_facts:",
                "      person_label_id: 0",
                "    deployment_status:",
                "      production: staging",
                "",
            ]
        ),
        encoding="utf-8",
    )
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(_telemetry_line() + "\n", encoding="utf-8")

    cwd_dir = tmp_path / "cwd-without-default-registry"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    code = _main(
        [
            str(tmp_path / "frame.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path / "model-dir"),
            "--model-id", "custom-registry-test",
            "--registry", str(registry_yaml),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "CONFIG_ERROR" in err
    assert "Registry 조회 실패" not in err, (
        "커스텀 --registry 가 무시되고 기본(CWD 상대) 경로로 폴백했다"
    )
    # 실패 사유가 커스텀 registry 의 파일명(model.onnx)을 참조한다 — load_dfine_
    # detector 내부의 2차 registry 재검증(verify_local_model)까지 --registry 를
    # 실제로 받았다는 증거(그렇지 않으면 기본 경로 조회 실패로 다른 메시지가 난다).
    assert "model.onnx" in err


# ── entry point 가 production pipeline 을 실제로 호출한다 ─────────────────────


def _stub_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
    detector = ScriptedDetector(
        {
            i: [
                person_detection(
                    x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                )
            ]
            for i in range(3)
        }
    )
    return detector, "scripted-stub-0", 3, 1920, 1080


def test_cli_runs_production_pipeline_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[공허 방지 앵커] main → run_vertical_slice → Event JSON 이 실제로 이어진다.

    stub 은 **detector 로드 단계만** 대체한다 — orchestration(tracking·보간·투영·
    조립·event 정책)은 production 코드가 그대로 돈다. main 에서 파이프라인 호출을
    제거하면 entities/event_bundles 가 비어 이 테스트가 실패한다.
    """
    monkeypatch.setattr(
        recorded_pipeline, "_load_recorded_detector", lambda **kw: _stub_loader(**kw)
    )
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"),
            str(tmp_path / "f1.jpg"),
            str(tmp_path / "f2.jpg"),
            "--telemetry",
            str(telemetry),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0.2",
            "--out",
            str(out),
        ]
    )
    assert code == 0, capsys.readouterr().err
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "ksi-recorded-pipeline-result/1"
    assert len(payload["observations"]) == 3, "프레임 3장 → 관측 3건 (파이프라인 실호출)"
    assert len(payload["entities"]) == 1
    assert len(payload["event_bundles"]) == 1
    assert payload["event_bundles"][0]["eventType"] == "PERSON_PRESENT"
    assert payload["entity_fingerprints"], "지문 없는 산출물은 재현성 비교 불가"


def test_cli_partial_failure_exits_3_with_typed_frame_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """프레임 단위 실패가 있으면 산출물은 내되 exit 3 — 성공으로 위장하지 않는다."""

    def _failing_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
        detector = ScriptedDetector(
            {
                i: [
                    person_detection(
                        x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                    )
                ]
                for i in range(3)
            },
            fail_frames={1: "synthetic inference failure"},
        )
        return detector, "scripted-stub-0", 3, 1920, 1080

    monkeypatch.setattr(recorded_pipeline, "_load_recorded_detector", _failing_loader)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"),
            str(tmp_path / "f1.jpg"),
            str(tmp_path / "f2.jpg"),
            "--telemetry",
            str(telemetry),
            "--model-dir",
            str(tmp_path),
            "--min-confidence",
            "0.5",
            "--frame-interval-s",
            "0.2",
            "--out",
            str(out),
        ]
    )
    assert code == 3, "부분 실패가 exit 0 으로 위장했다"
    assert "PARTIAL" in capsys.readouterr().err
    payload = json.loads(out.read_text(encoding="utf-8"))
    [failure] = payload["diagnostics"]["frame_failures"]
    assert failure["frame_id"] == 1
    assert failure["status"] == "inference_failed"
    assert failure["model_version"] == "scripted-stub-0"
    # 살아남은 프레임의 산출물은 그대로 나온다(부분 실패 ≠ 전체 실패).
    assert len(payload["observations"]) == 2


def test_cli_total_frame_failure_labeled_total_not_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 F] 처리된 프레임 전량이 실패해도 exit 3 은 동일하지만
    (성공으로 위장하지 않는다), stderr label 이 "PARTIAL" 로 실제 상태를 축소
    서술하지 않고 "TOTAL" 로 정직하게 표기한다."""

    def _all_fail_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
        detector = ScriptedDetector(
            {},
            fail_frames={i: "synthetic inference failure" for i in range(3)},
        )
        return detector, "scripted-stub-0", 3, 1920, 1080

    monkeypatch.setattr(recorded_pipeline, "_load_recorded_detector", _all_fail_loader)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 3, "전량 실패가 성공으로 위장됐다"
    err = capsys.readouterr().err
    assert "TOTAL" in err
    assert "PARTIAL" not in err
    assert "3/3" in err
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["diagnostics"]["frame_failures"]) == 3
    assert payload["observations"] == []


def test_cli_lineage_defect_exits_3_even_with_a_valid_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[재검증 V3 P3] 실질 공허 계보(entity 1) + 유효 계보(entity 1)를 같은 배치에
    섞으면, 유효 track 이 있어 ``result.bundles`` 가 비지 않으므로 기존 "관측은
    있는데 Event 0건" 게이트(bundles 전량 빌 때만 발동)를 피해가 exit 0 으로
    위장됐다 — 계보 결함은 bundles 잔존 여부와 무관하게 exit 3 이어야 한다."""
    from ksi_domain.detection import BoundingBox, Detection

    def _bare_person(*, x_min: float, y_min: float, x_max: float, y_max: float) -> Detection:
        # source_class_id/source_class_name 을 주지 않는다 — 계보의 원시 id/이름이
        # 비어 ClassificationLineage 의 model_validator(``_source_nonempty``)를
        # 위반하는 "형식상 존재하나 실질적으로 공허"한 계보 재현(vertical_slice
        # 픽스처의 person_detection 과 달리 source_class_id/name 을 채우지 않는다).
        return Detection(
            detection_class="Person",
            confidence=0.9,
            bbox=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
        )

    def _mixed_lineage_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
        script = {
            i: [
                _bare_person(
                    x_min=100.0 + i * 4, y_min=100.0, x_max=180.0 + i * 4, y_max=300.0
                ),
                person_detection(
                    x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                ),
            ]
            for i in range(3)
        }
        return ScriptedDetector(script), "scripted-stub-0", 3, 1920, 1080

    monkeypatch.setattr(recorded_pipeline, "_load_recorded_detector", _mixed_lineage_loader)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 3, "부분 계보 결함이 유효 track 뒤에 숨어 exit 0 으로 위장됐다"
    err = capsys.readouterr().err
    assert "missing_classification_lineage" in err
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["entities"]) == 2, "유효 entity + 공허 계보 entity 둘 다 산출된다"
    assert len(payload["event_bundles"]) == 1, "유효 track 의 Event 는 그대로 발행된다"
    assert payload["diagnostics"]["unpublished_events"], "계보 결함 사유가 diagnostics 에 남는다"


def test_serialized_result_is_deterministic() -> None:
    """같은 입력 2회 → 문자 단위 동일 JSON (P0-6 이 entry 출력까지 이어진다)."""

    def run() -> str:
        result = run_vertical_slice(
            frames=[
                # SliceFrame 은 pipeline 모듈 소유 — re-export 로도 같은 객체다.
                __import__("ksi_perception.pipeline", fromlist=["SliceFrame"]).SliceFrame(
                    frame_id=i, capture_ts_utc=i * 0.2, width=1920, height=1080
                )
                for i in range(2)
            ],
            detector=ScriptedDetector(
                {
                    i: [
                        person_detection(
                            x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                        )
                    ]
                    for i in range(2)
                }
            ),
            telemetry=synthetic_telemetry([0.0, 0.2]),
            drone_position=(100.0, 200.0, 60.0),
            context=make_run_context(),
        )
        return json.dumps(
            serialize_result(
                result,
                model_id="stub",
                model_version="scripted-stub-0",
                frame_count=2,
                width=1920,
                height=1080,
            ),
            sort_keys=True,
        )

    assert run() == run()


# ── Edge→Core 이음매 E2E (감사 #27) — 양쪽 픽스처가 아니라 실산출물이 흐른다 ──


def test_pipeline_output_flows_into_core_ingest_end_to_end(tmp_path: Path) -> None:
    """run_vertical_slice 가 만든 EventBundle 이 Core edge-sync 에 실제로 수락된다.

    파이프라인이 필드를 바꾸거나 v1.3 으로 올라가면 여기서 깨진다 — 각자 손으로
    만든 픽스처만 쓰면 양쪽이 각자 green 인 채 통합 시점에야 어긋난다.
    """
    import hashlib

    from fastapi.testclient import TestClient
    from ksi_core.app import create_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_core.events import EventStore
    from ksi_event_contracts.offline_sync import JournalEntry, payload_digest

    edge_device_id = "e2e-edge-001"
    edge_token = "e2e-recorded-pipeline-edge-token"  # noqa: S105 — 테스트 고정 토큰
    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(edge_token.encode("utf-8")).hexdigest(),
                principal=Principal(
                    principal_id="edge-principal-e2e-recorded-pipeline",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=edge_device_id,
                ),
            )
        ]
    )

    result = run_vertical_slice(
        frames=[
            recorded_pipeline.SliceFrame(
                frame_id=i, capture_ts_utc=i * 0.2, width=1920, height=1080
            )
            for i in range(2)
        ],
        detector=ScriptedDetector(
            {
                i: [
                    person_detection(
                        x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                    )
                ]
                for i in range(2)
            }
        ),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=(100.0, 200.0, 60.0),
        context=make_run_context(),
    )
    [bundle] = result.bundles

    from ksi_event_contracts.event_bundle import event_bundle_wire_dict

    payload = event_bundle_wire_dict(bundle)
    entry = JournalEntry(
        idempotency_key=f"e2e:{bundle.event_id}",
        device_sequence=0,
        edge_device_id=edge_device_id,
        payload_digest=payload_digest(payload),
        payload=payload,
    )
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    event_store = EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))
    client = TestClient(
        create_app(edge_sync_store=store, event_store=event_store, auth_registry=auth_registry)
    )
    request_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {edge_token}",
    }
    created = client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers=request_headers,
    )
    assert created.status_code == 201, created.text
    retransmit = client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers=request_headers,
    )
    assert retransmit.status_code == 200
    assert retransmit.json()["verdict"] == "DUPLICATE_IGNORED"
    assert store.accepted_count() == 1


def test_cli_disjoint_time_axis_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[감사 #24] 프레임/텔레메트리 시간축 미겹침은 무산출 성공이 아니라 exit 1 이다."""
    monkeypatch.setattr(
        recorded_pipeline, "_load_recorded_detector", lambda **kw: _stub_loader(**kw)
    )
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--start-ts", "0.0",  # 실제 epoch 텔레메트리와 겹치지 않는 강제 시작점
        ]
    )
    assert code == 1
    assert "겹치지 않는다" in capsys.readouterr().err


def test_cli_absolute_epoch_telemetry_succeeds_without_start_ts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[감사 #24 핵심] 실제 UTC epoch 텔레메트리를 주면 프레임 시각이 그 축으로
    절대화돼 산출이 나온다 — 초판은 전량 gap 탈락인데 exit 0 이었다."""
    monkeypatch.setattr(
        recorded_pipeline, "_load_recorded_detector", lambda **kw: _stub_loader(**kw)
    )
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 0, capsys.readouterr().err
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["observations"]) == 3, "실 epoch 축에서 전량 탈락했다(시간축 회귀)"


def test_cli_viewpoint_uses_enu_meters_not_raw_degrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 E, 부분 수정 — 전체는 ksi_perception.pipeline 소유 밖, 모듈
    docstring "viewpoint 좌표계" 절 참조] WGS84 도(度)를 그대로 미터 bin(기본
    2m)에 넣으면 실제 수십 m 이동이 전부 같은 bin 으로 뭉개진다. ENU 미터 변환
    후에는 그 이동이 실제로 다른 bin 이 된다.

    이 배치의 모든 프레임은 (구조적 제약상) 단일 대표 viewpoint 를 공유한다 —
    "프레임별 서로 다른 bin"이 아니라 "그 대표값이 도가 아니라 미터로 스케일된다"
    를 고정한다(완전한 프레임별 binning 은 별도 상신 대상).
    """
    monkeypatch.setattr(
        recorded_pipeline, "_load_recorded_detector", lambda **kw: _stub_loader(**kw)
    )
    # 위도 0.00045° ≈ 50m(적도 기준 1° ≈ 111km) — 실제 드론 이동 스케일. 도
    # 단위 그대로 bin_meters=2.0 에 투입하면 0.00045 << 2.0 이라 원점과 항상 같은
    # bin(고정)이 된다 — 이게 정확히 이번에 닫는 결함이다.
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(
            _telemetry_line(
                _ABS_TS_BASE + i * 0.2, overrides={"drone_lat": 37.5 + i * 0.00045}
            )
            for i in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            str(tmp_path / "f0.jpg"), str(tmp_path / "f1.jpg"), str(tmp_path / "f2.jpg"),
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 0, capsys.readouterr().err
    payload = json.loads(out.read_text(encoding="utf-8"))
    viewpoint_ids = {o["viewpointId"] for o in payload["observations"]}
    assert len(viewpoint_ids) == 1, (
        "배치 전체가 단일 대표 샘플을 공유하는 구조적 제약(recorded_pipeline 모듈 "
        'docstring "viewpoint 좌표계" 절 참조) 밖의 값이다'
    )
    [viewpoint_id] = viewpoint_ids

    from ksi_event_contracts.observation import viewpoint_bin_id
    from ksi_geo_core.frames import wgs84_to_enu

    # [재검증 V3 P3, 강화] '도 단위 bin 과 다르다'만 단언하면 east/north 뒤바뀜·
    # 원점 오선택도 통과한다 — 실제 CLI 알고리즘(recorded_pipeline.main 의
    # "viewpoint 참조점" 절)과 동일한 계산으로 정확값을 재현해 단언한다.
    #
    # 원점 = 텔레메트리 첫 샘플(i=0, drone_lat=37.5). 대표점 = 프레임 시퀀스
    # 시간 중앙점(offset 0.2s)에 최근접한 샘플 — 이 픽스처는 프레임 간격(0.2s)과
    # 텔레메트리 오프셋(0.0/0.2/0.4s)이 정확히 일치하므로 그 대표점은 i=1
    # (drone_lat=37.5+0.00045)이다.
    origin_lat, origin_lon, origin_alt = 37.5, 127.0, 60.0
    representative_lat = 37.5 + 1 * 0.00045
    representative_lon = 127.0
    representative_alt = 60.0
    expected_east_m, expected_north_m = wgs84_to_enu(
        origin_lat, origin_lon, representative_lat, representative_lon
    )
    expected_up_m = representative_alt - origin_alt
    expected_bin = viewpoint_bin_id((expected_east_m, expected_north_m, expected_up_m))

    assert viewpoint_id == expected_bin, (
        "ENU 변환 결과가 실제 알고리즘과 다르다 — east/north 뒤바뀜·원점 오선택 등의 "
        "회귀를 잡는다"
    )
    assert viewpoint_id.startswith("vpbin:")

    # 옛 결함의 대조군 — 도(度) 그대로 bin 에 넣었다면 이 값이 됐을 것이다.
    degree_scale_bin = viewpoint_bin_id((37.5, 127.0, 60.0))
    assert viewpoint_id != degree_scale_bin, (
        "ENU 미터 변환이 적용되지 않았다 — 여전히 도 단위 bin 과 동일하다"
    )


def test_cli_assembly_stage_wipeout_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """[자율 재검토 P1-B1] 관측은 있는데 Event 0건(융합 창 1.0s 초과 등)이 exit 0
    으로 위장되지 않는다 — 7프레임×0.2s(1.2s span) track 재현."""

    def _long_loader(**_kwargs: object) -> tuple[ScriptedDetector, str, int, int, int]:
        detector = ScriptedDetector(
            {
                i: [
                    person_detection(
                        x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                    )
                ]
                for i in range(7)
            }
        )
        return detector, "scripted-stub-0", 7, 1920, 1080

    monkeypatch.setattr(recorded_pipeline, "_load_recorded_detector", _long_loader)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(_telemetry_line(_ABS_TS_BASE + i * 0.2) for i in range(7)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    code = _main(
        [
            *[str(tmp_path / f"f{i}.jpg") for i in range(7)],
            "--telemetry", str(telemetry),
            "--model-dir", str(tmp_path),
            "--min-confidence", "0.5",
            "--frame-interval-s", "0.2",
            "--out", str(out),
        ]
    )
    assert code == 3, "조립 단계 전량 탈락이 성공으로 위장됐다"
    assert "Event 0건" in capsys.readouterr().err
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["event_bundles"] == []
    assert payload["diagnostics"]["assembly_failures"], "재현 전제(창 초과) 불성립"


def test_serialized_entities_and_bundles_satisfy_their_schemas() -> None:
    """[자율 재검토 P1-C1·P2-C2] 실산출 JSON 이 계약 스키마를 실제로 통과한다."""
    from jsonschema import Draft202012Validator

    result = run_vertical_slice(
        frames=[
            recorded_pipeline.SliceFrame(
                frame_id=i, capture_ts_utc=i * 0.2, width=1920, height=1080
            )
            for i in range(2)
        ],
        detector=ScriptedDetector(
            {
                i: [
                    person_detection(
                        x_min=900.0 + i * 4, y_min=500.0, x_max=980.0 + i * 4, y_max=700.0
                    )
                ]
                for i in range(2)
            }
        ),
        telemetry=synthetic_telemetry([0.0, 0.2]),
        drone_position=(100.0, 200.0, 60.0),
        context=make_run_context(),
    )
    payload = serialize_result(
        result, model_id="stub", model_version="scripted-stub-0",
        frame_count=2, width=1920, height=1080,
    )
    root = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
    entity_schema = json.loads((root / "world-entity.v1.json").read_text(encoding="utf-8"))
    bundle_schema = json.loads((root / "event-bundle.v1.2.json").read_text(encoding="utf-8"))
    assert payload["entities"] and payload["event_bundles"], "검증 대상이 비어 공허하다"
    for entity in payload["entities"]:
        Draft202012Validator(entity_schema).validate(entity)
    for bundle in payload["event_bundles"]:
        Draft202012Validator(bundle_schema).validate(bundle)


# ── 실모델 entry 게이트 (자율 재검토 G) ────────────────────────────────────────
#
# 위 CLI 테스트는 전부 ``_load_recorded_detector`` 를 stub 으로 대체한다 —
# Registry→모델→프레임 실로드 경로(entry point 의 실제 진입 경로) 자체는 이
# 파일 어디에서도 실행된 적이 없다. 여기서만 실 Registry·실모델·실 프레임으로
# subprocess CLI 를 end-to-end 실행해 그 경로를 고정한다.
#
# NOTE(배선 경계, 재검증 V3 P1 폐쇄): tests/conftest.py 의 ``REAL_MODEL_GATE_FILES``
# (skip 감지)·``expected``(파일 부재 감지) 양쪽 모두에 이 파일(test_recorded_
# pipeline.py)이 등록돼 있다 — KSI_REQUIRE_REAL_MODEL=1 세션에서 이 테스트가
# skip 되거나, 이 파일 자체가 rename/삭제돼 수집조차 안 되는 경우 모두 conftest
# 의 강제 실패 훅이 잡는다.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tests/ (conftest 도 동일 삽입)
from _real_model_gate import real_model_runtime_available, registry_model_dir  # noqa: E402

_REAL_MODEL_ID = "ksi-person-detector-dfine-s-coco"
_REAL_PERSON_IMAGE = Path("models/test-assets/person.jpg")


def _real_model_dir() -> Path:
    return registry_model_dir(_REAL_MODEL_ID)


@pytest.mark.skipif(
    not (
        real_model_runtime_available()
        and _real_model_dir().is_dir()
        and _REAL_PERSON_IMAGE.is_file()
    ),
    reason="[dfine] extra·모델·녹화 이미지 없음 — tools/fetch_model.py 후 실행",
)
def test_cli_real_entry_path_end_to_end() -> None:
    """[자율 재검토 G] Registry→모델→프레임 실로드 경로가 자동 게이트에서 실행된
    적이 없었다 — subprocess 로 실 CLI(``python -m ksi_perception.
    recorded_pipeline``)를 실 Registry·실모델·소형 프레임 시퀀스로 end-to-end
    실행해 exit 0 + Event/Evidence 산출을 고정한다."""
    import subprocess
    import sys as _sys
    import tempfile

    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        telemetry = tmp_path / "telemetry.jsonl"
        telemetry.write_text(
            "\n".join(_telemetry_line(_ABS_TS_BASE + i * 0.2) for i in range(3)) + "\n",
            encoding="utf-8",
        )
        out = tmp_path / "result.json"
        proc = subprocess.run(
            [
                _sys.executable, "-m", "ksi_perception.recorded_pipeline",
                str(_REAL_PERSON_IMAGE), str(_REAL_PERSON_IMAGE), str(_REAL_PERSON_IMAGE),
                "--telemetry", str(telemetry),
                "--model-dir", str(_real_model_dir()),
                "--model-id", _REAL_MODEL_ID,
                "--registry", str(repo_root / "docs" / "models" / "MODEL_REGISTRY.yaml"),
                "--min-confidence", "0.5",
                "--frame-interval-s", "0.2",
                "--out", str(out),
                *_LINEAGE_ARGS,
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=180,
        )
        assert proc.returncode == 0, (
            f"실 entry 경로 end-to-end 실패 (exit {proc.returncode})\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["entities"], "실모델 경로에서 Entity 0건 — 배선 죽음"
        assert payload["event_bundles"], "실모델 경로에서 Event Bundle 0건"
