"""Native Edge candidate-durability timing evidence validator (REQ-EVT-101).

The Manifold shadow slice can truthfully time exactly one event stage:
``FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE``.  It starts at the PSDK RGB
callback's ``CLOCK_MONOTONIC`` receipt timestamp and ends only after the SQLite
candidate/evidence transaction returns accepted.  It does *not* measure a
user-visible local alert or a Core-to-user notification, so it must never be
serialized into those optional ``EventBundle.timing`` fields.

The DPK writes one immutable ``event-timing-<sha256>.json`` artifact for each
new durable candidate.  This utility validates copied raw artifacts before it
calculates a report.  It fails closed on malformed JSON, changed latency,
unknown schema/stage/clock domain, duplicate candidate IDs, and NOT_MEASURED
records.  A within-budget result is replay/HIL measurement evidence only; it
does not by itself make the product hardware-verified or production-supported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

PROFILE_ID = "ksi-edge-candidate-durability-v1"
SCHEMA_VERSION = "1.0"
STAGE = "FRAME_RECEIVED_TO_SQLITE_CANDIDATE_DURABLE"
CLOCK_DOMAIN = "CLOCK_MONOTONIC"
TARGET_MAX_MS = 1000.0


class EvidenceStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class MeasurementStatus(StrEnum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    NOT_MEASURED = "NOT_MEASURED"


class CandidateDurabilityBudgetStatus(StrEnum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    EXCEEDED = "EXCEEDED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


@dataclass(frozen=True, slots=True)
class CandidateTimingSample:
    artifact_name: str
    artifact_sha256: str
    candidate_idempotency_key: str
    measurement_status: str
    frame_received_monotonic_ns: int | None
    candidate_durable_monotonic_ns: int | None
    candidate_latency_ns: int | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class RejectedArtifact:
    artifact_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateTimingLoadResult:
    samples: tuple[CandidateTimingSample, ...]
    rejected: tuple[RejectedArtifact, ...]


def _strict_json_constant(value: str) -> None:
    raise ValueError(f"JSON non-finite constant is forbidden: {value}")


def _nonblank_str(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _read_optional_positive_int(payload: dict[str, Any], *, name: str) -> int | None:
    if name not in payload:
        return None
    return _positive_int(payload[name], name=name)


def _parse_artifact(artifact_name: str, raw: bytes) -> CandidateTimingSample:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"invalid UTF-8: {error}") from error
    try:
        payload = json.loads(text, parse_constant=_strict_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")

    common = {
        "schemaVersion",
        "stage",
        "clockDomain",
        "candidateIdempotencyKey",
        "measurementStatus",
    }
    measurement_status = _nonblank_str(payload.get("measurementStatus"), name="measurementStatus")
    if measurement_status == "MEASURED":
        expected = common | {
            "frameReceivedMonotonicNs",
            "candidateDurableMonotonicNs",
            "candidateLatencyNs",
        }
        if set(payload) != expected:
            raise ValueError("MEASURED artifact fields do not match schema v1.0")
    elif measurement_status == "NOT_MEASURED":
        allowed = common | {
            "frameReceivedMonotonicNs",
            "candidateDurableMonotonicNs",
            "reason",
        }
        if not (common | {"reason"}) <= set(payload) or not set(payload) <= allowed:
            raise ValueError("NOT_MEASURED artifact fields do not match schema v1.0")
    else:
        raise ValueError("measurementStatus must be MEASURED or NOT_MEASURED")

    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schemaVersion: {payload.get('schemaVersion')!r}")
    if payload.get("stage") != STAGE:
        raise ValueError(f"unsupported stage: {payload.get('stage')!r}")
    if payload.get("clockDomain") != CLOCK_DOMAIN:
        raise ValueError(f"unsupported clockDomain: {payload.get('clockDomain')!r}")
    candidate_idempotency_key = _nonblank_str(
        payload.get("candidateIdempotencyKey"), name="candidateIdempotencyKey"
    )
    frame_received = _read_optional_positive_int(payload, name="frameReceivedMonotonicNs")
    candidate_durable = _read_optional_positive_int(payload, name="candidateDurableMonotonicNs")
    if measurement_status == "MEASURED":
        assert frame_received is not None
        assert candidate_durable is not None
        candidate_latency = _nonnegative_int(
            payload.get("candidateLatencyNs"), name="candidateLatencyNs"
        )
        if candidate_durable < frame_received:
            raise ValueError("candidate durable timestamp precedes frame receipt")
        if candidate_latency != candidate_durable - frame_received:
            raise ValueError("candidateLatencyNs does not equal durable minus frame timestamp")
        return CandidateTimingSample(
            artifact_name,
            f"sha256:{hashlib.sha256(raw).hexdigest()}",
            candidate_idempotency_key,
            measurement_status,
            frame_received,
            candidate_durable,
            candidate_latency,
            None,
        )

    reason = _nonblank_str(payload.get("reason"), name="reason")
    if reason not in {"MISSING_FRAME_TIMESTAMP", "CLOCK_UNAVAILABLE", "CLOCK_ROLLBACK"}:
        raise ValueError(f"unsupported NOT_MEASURED reason: {reason!r}")
    return CandidateTimingSample(
        artifact_name,
        f"sha256:{hashlib.sha256(raw).hexdigest()}",
        candidate_idempotency_key,
        measurement_status,
        frame_received,
        candidate_durable,
        None,
        reason,
    )


def load_candidate_timing_artifacts(directory: Path) -> CandidateTimingLoadResult:
    """Read one copied DPK artifact directory without silently dropping defects."""

    if not directory.is_dir():
        return CandidateTimingLoadResult(
            (), (RejectedArtifact(str(directory), "input directory is unavailable"),)
        )
    samples: list[CandidateTimingSample] = []
    rejected: list[RejectedArtifact] = []
    candidate_ids: set[str] = set()
    entries = sorted(directory.glob("event-timing-*.json"), key=lambda item: item.name)
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            rejected.append(
                RejectedArtifact(entry.name, "artifact is not a regular non-symlink file")
            )
            continue
        try:
            sample = _parse_artifact(entry.name, entry.read_bytes())
        except (OSError, ValueError) as error:
            rejected.append(RejectedArtifact(entry.name, str(error)))
            continue
        if sample.candidate_idempotency_key in candidate_ids:
            rejected.append(RejectedArtifact(entry.name, "duplicate candidateIdempotencyKey"))
            continue
        candidate_ids.add(sample.candidate_idempotency_key)
        samples.append(sample)
    return CandidateTimingLoadResult(tuple(samples), tuple(rejected))


def percentile(values: Sequence[int], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= fraction <= 1.0 or not math.isfinite(fraction):
        raise ValueError("percentile fraction must be finite and in [0, 1]")
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def build_summary(
    loaded: CandidateTimingLoadResult, *, session_id: str, build_commit: str
) -> dict[str, Any]:
    """Build a deterministic report without turning missing stages into PASS."""

    session = _nonblank_str(session_id, name="session_id")
    commit = _nonblank_str(build_commit, name="build_commit")
    measured = [sample for sample in loaded.samples if sample.measurement_status == "MEASURED"]
    valid_latencies_ns: list[int] = []
    for sample in measured:
        if sample.candidate_latency_ns is None:
            raise ValueError("MEASURED sample lacks candidate latency")
        valid_latencies_ns.append(sample.candidate_latency_ns)
    evidence_status = EvidenceStatus.INVALID if loaded.rejected else EvidenceStatus.VALID
    if not loaded.samples:
        measurement_status = MeasurementStatus.NOT_MEASURED
    elif len(measured) == len(loaded.samples) and not loaded.rejected:
        measurement_status = MeasurementStatus.MEASURED
    elif measured:
        measurement_status = MeasurementStatus.PARTIAL
    else:
        measurement_status = MeasurementStatus.NOT_MEASURED

    budget: dict[str, Any] = {
        "targetMaxMs": TARGET_MAX_MS,
        "status": CandidateDurabilityBudgetStatus.NOT_EVALUABLE,
        "maxMs": None,
        "p50Ms": None,
        "p95Ms": None,
    }
    if measurement_status == MeasurementStatus.MEASURED and evidence_status == EvidenceStatus.VALID:
        max_ms = max(valid_latencies_ns) / 1_000_000.0
        budget.update(
            {
                "status": CandidateDurabilityBudgetStatus.WITHIN_BUDGET
                if max_ms <= TARGET_MAX_MS
                else CandidateDurabilityBudgetStatus.EXCEEDED,
                "maxMs": max_ms,
                "p50Ms": percentile(valid_latencies_ns, 0.50) / 1_000_000.0,
                "p95Ms": percentile(valid_latencies_ns, 0.95) / 1_000_000.0,
            }
        )
    elif valid_latencies_ns:
        # Retain measured facts for diagnosis, but never calculate a budget
        # verdict from partial/invalid evidence.
        budget.update(
            {
                "maxMs": max(valid_latencies_ns) / 1_000_000.0,
                "p50Ms": percentile(valid_latencies_ns, 0.50) / 1_000_000.0,
                "p95Ms": percentile(valid_latencies_ns, 0.95) / 1_000_000.0,
            }
        )

    return {
        "schemaVersion": "1.0",
        "profileId": PROFILE_ID,
        "scope": STAGE,
        "sessionId": session,
        "buildCommit": commit,
        "evidenceStatus": evidence_status,
        "measurementStatus": measurement_status,
        "artifactCount": len(loaded.samples),
        "measuredSampleCount": len(measured),
        "notMeasuredSampleCount": len(loaded.samples) - len(measured),
        "rejectedArtifacts": [
            {"artifactName": item.artifact_name, "reason": item.reason} for item in loaded.rejected
        ],
        "inputArtifactDigests": [
            {"artifactName": item.artifact_name, "sha256": item.artifact_sha256}
            for item in loaded.samples
        ],
        "candidateDurabilityBudget": budget,
        "limitations": [
            "Measures frame callback receipt to SQLite candidate/evidence durability only.",
            "Does not measure a user-visible local alert or server user notification.",
            "Within-budget replay/HIL evidence is not hardware or production verification "
            "by itself.",
        ],
    }


def _command_summarize(arguments: argparse.Namespace) -> int:
    result = build_summary(
        load_candidate_timing_artifacts(arguments.input_directory),
        session_id=arguments.session_id,
        build_commit=arguments.build_commit,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    summarize = subcommands.add_parser(
        "summarize", help="validate native candidate timing artifacts"
    )
    summarize.add_argument("--in-dir", dest="input_directory", type=Path, required=True)
    summarize.add_argument("--out", dest="output", type=Path, required=True)
    summarize.add_argument("--session-id", required=True)
    summarize.add_argument("--build-commit", required=True)
    summarize.set_defaults(handler=_command_summarize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    sys.exit(main())
