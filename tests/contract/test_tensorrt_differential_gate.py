"""Contract tests for the offline TensorRT-to-ONNX semantic gate.

No TensorRT device or model artifact is needed here: these tests exercise the
fail-closed report/evidence boundary that the real C++ runner and ONNX oracle
meet at.  Hardware evidence remains a separate Manifold 3 gate.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ksi_mission_contracts.runtime_profile import EdgeRuntimeProfileV1

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "edge"))

from verify_tensorrt_differential import (  # noqa: E402
    DifferentialFailure,
    OracleSample,
    RawRgbCorpusV1,
    TensorRtRunnerReportV1,
    _preprocess_rgb_bilinear_1over255,
    build_differential_evidence,
    compare_semantic_reports,
    corpus_digest,
)


def test_native_preprocessing_fixture_is_pinned_before_model_comparison() -> None:
    rgb = bytes((0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110))
    output = _preprocess_rgb_bilinear_1over255(rgb, 2, 2, 3, 3)

    assert output.shape == (1, 3, 3, 3)
    assert float(output[0, 0, 1, 1]) == pytest.approx(45.0 / 255.0, abs=1e-7)
    assert float(output[0, 2, 2, 2]) == pytest.approx(110.0 / 255.0, abs=1e-7)
    assert (
        "sha256:" + hashlib.sha256(output.tobytes(order="C")).hexdigest()
        == "sha256:89404ce71651f46204dd0e348107d07979ba204c0610313539582653566aeb18"
    )


def _profile() -> EdgeRuntimeProfileV1:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    return EdgeRuntimeProfileV1.model_validate(
        {
            "schemaVersion": "1.0",
            "edgeRuntimeProfileId": "runtime-profile-differential-v1",
            "validity": {
                "notBefore": now.isoformat(),
                "notAfter": now.replace(hour=13).isoformat(),
            },
            "siteId": "site-001",
            "model": {
                "modelPackId": "model-pack-001",
                "modelId": "dfine-test-v1",
                "onnxArtifactId": "dfine.onnx",
                "registeredOnnxDigest": "sha256:" + "a" * 64,
                "engineArtifactId": "dfine.engine",
                "maxOnnxBytes": 104857600,
                "maxEngineBytes": 209715200,
                "workspaceBytes": 104857600,
                "tensorContract": {
                    "inputWidth": 640,
                    "inputHeight": 640,
                    "queryCount": 2,
                    "classCount": 2,
                },
                "classBindings": [
                    {
                        "sourceClassId": 0,
                        "sourceClassName": "excavator",
                        "equipmentClass": "Excavator",
                        "measuredDimensions": {"lengthM": 9.0, "widthM": 3.0, "heightM": 4.0},
                    }
                ],
                "scoreThreshold": 0.5,
                "topK": 2,
                "ontologyVersion": "ksi-ontology-v1",
                "sourceTaxonomy": "COCO-2017",
                "tensorRtDifferential": {
                    "verificationProfileId": "ksi-dfine-tensorrt-onnx-semantic-v1",
                    "evidenceDigest": "sha256:" + "b" * 64,
                    "registeredOnnxDigest": "sha256:" + "a" * 64,
                    "preprocessingContractId": "rtdetr-rgb-bilinear-1over255-v1",
                    "preprocessingConfigDigest": "sha256:" + "c" * 64,
                    "corpusId": "dfine-corpus-v1",
                    "corpusDigest": "sha256:" + "d" * 64,
                    "sampleCount": 10,
                    "status": "PASS",
                    "confidenceAtol": 0.001,
                    "bboxAtolPx": 0.5,
                },
            },
            "calibration": {
                "calibrationProfileId": "cal-001",
                "siteFrame": {
                    "crs": "EPSG:5186",
                    "verticalDatum": "KNGeoid2018",
                    "unit": "meter",
                    "transformVersion": "1.0.0",
                },
                "wgs84Origin": {"latitudeRad": 0.5, "longitudeRad": 1.0, "altitudeM": 20.0},
                "enuToSite": {
                    "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "translationM": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "groundPlaneUpM": 0.0,
                "intrinsics": {
                    "referenceWidth": 1920,
                    "referenceHeight": 1080,
                    "focalXPx": 1000.0,
                    "focalYPx": 1000.0,
                    "principalXPx": 960.0,
                    "principalYPx": 540.0,
                },
                "cameraToGimbal": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                "cameraOffsetInGimbalM": {"x": 0.0, "y": 0.0, "z": 0.0},
                "positionSigmaM": 1.0,
                "angularSigmaRad": 0.01,
                "pixelSigmaPx": 1.0,
                "maxPoseAgeMs": 500,
            },
            "timing": {"requireSensorAlignment": True, "maxAlignmentMs": 50},
        }
    )


def _corpus() -> RawRgbCorpusV1:
    return RawRgbCorpusV1.model_validate(
        {
            "schemaVersion": "1.0",
            "corpusId": "dfine-corpus-v1",
            "samples": [
                {
                    "sampleId": f"scene-{index}",
                    "width": 2,
                    "height": 2,
                    "rgbFile": f"scene-{index}.rgb",
                    "rgbDigest": "sha256:" + f"{index:x}" * 64,
                }
                for index in range(10)
            ],
        }
    )


def _report(corpus: RawRgbCorpusV1) -> TensorRtRunnerReportV1:
    return TensorRtRunnerReportV1.model_validate(
        {
            "schemaVersion": "1.0",
            "runnerVersion": "ksi-tensorrt-dfine-runner-v1",
            "registeredOnnxDigest": "sha256:" + "a" * 64,
            "preprocessingContractId": "rtdetr-rgb-bilinear-1over255-v1",
            "tensorContract": {
                "inputWidth": 640,
                "inputHeight": 640,
                "queryCount": 2,
                "classCount": 2,
            },
            "scoreThreshold": 0.5,
            "topK": 2,
            "samples": [
                {
                    "sampleId": sample.sample_id,
                    "width": sample.width,
                    "height": sample.height,
                    "rgbDigest": sample.rgb_digest,
                    "preprocessedInputDigest": "sha256:" + "e" * 64,
                    "detections": [],
                    "drops": {
                        "SCORE_BELOW_THRESHOLD": 2,
                        "UNKNOWN_CLASS": 0,
                        "NON_FINITE_TENSOR": 0,
                        "MALFORMED_TENSOR": 0,
                    },
                }
                for sample in corpus.samples
            ],
        }
    )


def _oracle(corpus: RawRgbCorpusV1) -> dict[str, OracleSample]:
    return {
        sample.sample_id: OracleSample(
            sample_id=sample.sample_id,
            width=sample.width,
            height=sample.height,
            rgb_digest=sample.rgb_digest,
            preprocessed_input_digest="sha256:" + "e" * 64,
            detections=(),
            drops={
                "SCORE_BELOW_THRESHOLD": 2,
                "UNKNOWN_CLASS": 0,
                "NON_FINITE_TENSOR": 0,
                "MALFORMED_TENSOR": 0,
            },
        )
        for sample in corpus.samples
    }


def test_semantic_gate_accepts_exact_typed_results_and_evidence_is_deterministic() -> None:
    profile = _profile()
    corpus = _corpus()
    # This unit fixture does not exercise file I/O; wire the canonical corpus
    # digest into the otherwise profile-shaped draft before comparison.
    raw = profile.model_dump(by_alias=True, mode="json")
    raw["model"]["tensorRtDifferential"]["corpusDigest"] = corpus_digest(corpus)
    profile = EdgeRuntimeProfileV1.model_validate(raw)
    report = _report(corpus)
    oracle = _oracle(corpus)

    compare_semantic_reports(profile, corpus, report, oracle)
    evidence_a, digest_a = build_differential_evidence(profile, corpus, report, {"samples": []})
    evidence_b, digest_b = build_differential_evidence(profile, corpus, report, {"samples": []})

    assert evidence_a == evidence_b
    assert digest_a == digest_b
    assert evidence_a["status"] == "PASS"
    assert evidence_a["sampleCount"] == 10


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda raw: raw["samples"][0]["drops"].__setitem__("UNKNOWN_CLASS", 1),
            "typed D-FINE drops differ",
        ),
        (
            lambda raw: raw["samples"][0].__setitem__(
                "preprocessedInputDigest", "sha256:" + "f" * 64
            ),
            "RGB/preprocessing lineage mismatch",
        ),
        (
            lambda raw: raw.__setitem__("registeredOnnxDigest", "sha256:" + "f" * 64),
            "ONNX digest",
        ),
    ],
)
def test_semantic_gate_fails_closed_for_report_drift(mutate: object, message: str) -> None:
    corpus = _corpus()
    raw_profile = _profile().model_dump(by_alias=True, mode="json")
    raw_profile["model"]["tensorRtDifferential"]["corpusDigest"] = corpus_digest(corpus)
    profile = EdgeRuntimeProfileV1.model_validate(raw_profile)
    raw_report = _report(corpus).model_dump(by_alias=True, mode="json")
    assert callable(mutate)
    mutate(raw_report)
    report = TensorRtRunnerReportV1.model_validate(raw_report)

    with pytest.raises(DifferentialFailure, match=message):
        compare_semantic_reports(profile, corpus, report, _oracle(corpus))
