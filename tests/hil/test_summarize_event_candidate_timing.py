"""REQ-EVT-101 native candidate-durability artifact validator tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "hil"))

from summarize_event_candidate_timing import (  # noqa: E402
    CandidateDurabilityBudgetStatus,
    EvidenceStatus,
    MeasurementStatus,
    build_summary,
    load_candidate_timing_artifacts,
    main,
)


def _measured(candidate_id: str, start_ns: int, latency_ns: int) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "stage": "FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE",
        "clockDomain": "CLOCK_MONOTONIC",
        "candidateIdempotencyKey": candidate_id,
        "measurementStatus": "MEASURED",
        "frameReceivedMonotonicNs": start_ns,
        "candidateDurableMonotonicNs": start_ns + latency_ns,
        "candidateLatencyNs": latency_ns,
    }


def _not_measured(candidate_id: str, reason: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "stage": "FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE",
        "clockDomain": "CLOCK_MONOTONIC",
        "candidateIdempotencyKey": candidate_id,
        "measurementStatus": "NOT_MEASURED",
        "reason": reason,
    }


def _write(directory: Path, name: str, payload: dict[str, object]) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def _summary(directory: Path) -> dict[str, Any]:
    return build_summary(
        load_candidate_timing_artifacts(directory),
        session_id="SESS-20260814T010203Z-TEST",
        build_commit="deadbeef",
    )


def test_valid_measured_artifacts_need_every_sample_within_fixed_one_second_budget(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "event-timing-a.json", _measured("evt-a", 10, 500_000_000))
    _write(tmp_path, "event-timing-b.json", _measured("evt-b", 20, 1_000_000_000))

    summary = _summary(tmp_path)

    assert summary["evidenceStatus"] == EvidenceStatus.VALID
    assert summary["measurementStatus"] == MeasurementStatus.MEASURED
    assert summary["measuredSampleCount"] == 2
    budget = summary["candidateDurabilityBudget"]
    assert isinstance(budget, dict)
    assert budget["status"] == CandidateDurabilityBudgetStatus.WITHIN_BUDGET
    assert budget["maxMs"] == 1000.0


def test_tampered_duration_is_rejected_instead_of_recomputed_to_a_good_value(
    tmp_path: Path,
) -> None:
    payload = _measured("evt-a", 10, 500_000_000)
    payload["candidateLatencyNs"] = 1
    _write(tmp_path, "event-timing-a.json", payload)

    summary = _summary(tmp_path)

    assert summary["evidenceStatus"] == EvidenceStatus.INVALID
    assert summary["measurementStatus"] == MeasurementStatus.NOT_MEASURED
    assert (
        summary["candidateDurabilityBudget"]["status"]
        == CandidateDurabilityBudgetStatus.NOT_EVALUABLE
    )
    assert "does not equal" in summary["rejectedArtifacts"][0]["reason"]


def test_not_measured_record_prevents_budget_pass_from_the_remaining_samples(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "event-timing-a.json", _measured("evt-a", 10, 1))
    _write(tmp_path, "event-timing-b.json", _not_measured("evt-b", "CLOCK_ROLLBACK"))

    summary = _summary(tmp_path)

    assert summary["evidenceStatus"] == EvidenceStatus.VALID
    assert summary["measurementStatus"] == MeasurementStatus.PARTIAL
    assert (
        summary["candidateDurabilityBudget"]["status"]
        == CandidateDurabilityBudgetStatus.NOT_EVALUABLE
    )
    assert summary["candidateDurabilityBudget"]["maxMs"] == 0.000001


def test_duplicate_candidate_id_and_unknown_fields_invalidate_evidence(tmp_path: Path) -> None:
    _write(tmp_path, "event-timing-a.json", _measured("evt-a", 10, 1))
    _write(tmp_path, "event-timing-b.json", _measured("evt-a", 20, 1))
    payload = _measured("evt-c", 30, 1)
    payload["unexpected"] = "drift"
    _write(tmp_path, "event-timing-c.json", payload)

    summary = _summary(tmp_path)

    assert summary["evidenceStatus"] == EvidenceStatus.INVALID
    assert summary["measurementStatus"] == MeasurementStatus.PARTIAL
    assert len(summary["rejectedArtifacts"]) == 2
    assert (
        summary["candidateDurabilityBudget"]["status"]
        == CandidateDurabilityBudgetStatus.NOT_EVALUABLE
    )


def test_cli_writes_traceable_summary_and_accepts_zero_duration(tmp_path: Path) -> None:
    _write(tmp_path, "event-timing-zero.json", _measured("evt-zero", 10, 0))
    output = tmp_path / "summary.json"

    assert (
        main(
            [
                "summarize",
                "--in-dir",
                str(tmp_path),
                "--out",
                str(output),
                "--session-id",
                "SESS-20260814T010203Z-TEST",
                "--build-commit",
                "deadbeef",
            ]
        )
        == 0
    )
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["profileId"] == "ksi-edge-candidate-durability-v1"
    assert written["inputArtifactDigests"][0]["sha256"].startswith("sha256:")
    assert written["candidateDurabilityBudget"]["status"] == "WITHIN_BUDGET"
