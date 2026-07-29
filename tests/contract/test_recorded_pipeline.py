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


def _main(argv: list[str]) -> int:
    """모든 CLI 테스트가 같은 계보 인자를 지참한다 — 개별 테스트는 차이만 기술."""
    return main(argv + _LINEAGE_ARGS)


def _telemetry_line(ts: float = 0.0, overrides: dict[str, object] | None = None) -> str:
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
        _telemetry_line(0.0) + "\n" + _telemetry_line(0.2) + "\n", encoding="utf-8"
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
    record = TelemetryRecord.model_validate(json.loads(_telemetry_line(1.5)))
    sample = record.to_sample()
    assert isinstance(sample.ts, TimestampSet)
    assert sample.ts.capture_ts_utc == 1.5
    assert sample.gimbal_pitch_deg == -60.0


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
        "\n".join(_telemetry_line(ts) for ts in (0.0, 0.2, 0.4)) + "\n", encoding="utf-8"
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
        "\n".join(_telemetry_line(ts) for ts in (0.0, 0.2, 0.4)) + "\n", encoding="utf-8"
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
    from fastapi.testclient import TestClient
    from ksi_core.app import create_app
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_event_contracts.offline_sync import JournalEntry, payload_digest

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
        edge_device_id="e2e-edge-001",
        payload_digest=payload_digest(payload),
        payload=payload,
    )
    store = EdgeSyncStore(tmp_path / "journal.jsonl")
    client = TestClient(create_app(edge_sync_store=store))
    created = client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers={"Content-Type": "application/json"},
    )
    assert created.status_code == 201, created.text
    retransmit = client.post(
        "/v1/edge-sync/event-bundles",
        content=entry.model_dump_json(by_alias=True),
        headers={"Content-Type": "application/json"},
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
        "\n".join(_telemetry_line(1_700_000_000.0 + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
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
        "\n".join(_telemetry_line(1_700_000_000.0 + ts) for ts in (0.0, 0.2, 0.4)) + "\n",
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
        "\n".join(_telemetry_line(i * 0.2) for i in range(7)) + "\n", encoding="utf-8"
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
