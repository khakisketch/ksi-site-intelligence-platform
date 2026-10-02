"""Opt-in pinned Floreat HTTP/byte/grid experiment, not an isolation installer.

Requires an existing pre-inspected source snapshot and signed activated worker
configuration. Never GDAL-decodes an untrusted original in this process. Generated
CI exercises independent pixel/mask comparisons separately; public pixel/peak
resource/host acceptance is not established by this client-only verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from time import monotonic
from types import ModuleType
from typing import Any

from ksi_event_contracts.spatial_data import SpatialDataSourceV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from ksi_processing_controller.spatial_data_sandbox import SpatialDataContainmentProofV1
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    SpatialDataWorkerConfigV1,
    load_spatial_data_worker_config,
    parse_strict_json,
    read_owner_private_file,
)

PINS = {
    "dsm": (181498053, "28eb3bea0e0ef58db7fa9f00b383bf7b50e6348103d80767a5ad362c0c37a7e2"),
    "ortho": (346715111, "b25bbfa56cd8cf90eca43bcb5539de4cbccfaa2744421c5f949ca1038b27cb66"),
}
ATTRIBUTION = "Cambridge Coastcare, Floreat-f4, 24 August 2022, via DataWA; CC BY 4.0."


class Blocked(RuntimeError):
    pass


def original_identity(path: Path, *, kind: str) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise Blocked("PUBLIC_ORIGINAL_UNAVAILABLE") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise Blocked("PUBLIC_ORIGINAL_UNAVAILABLE")
        size, expected = PINS[kind]
        if before.st_size != size:
            raise Blocked("PUBLIC_ORIGINAL_IDENTITY_MISMATCH")
        hashed = hashlib.sha256()
        count = 0
        while chunk := os.read(fd, 65536):
            count += len(chunk)
            if count > size:
                raise Blocked("PUBLIC_ORIGINAL_IDENTITY_MISMATCH")
            hashed.update(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise Blocked("PUBLIC_ORIGINAL_IDENTITY_MISMATCH")
        if count != size or hashed.hexdigest() != expected:
            raise Blocked("PUBLIC_ORIGINAL_IDENTITY_MISMATCH")
        return "sha256:" + expected
    finally:
        os.close(fd)


def _client_module() -> ModuleType:
    spec = spec_from_file_location(
        "native_window_client",
        Path(__file__).resolve().parents[1] / "examples/spatial-data/native_window_client.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bounded_json(path: Path) -> Any:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 262144
        ):
            raise ValueError("metadata limit/type")
        raw = os.read(descriptor, 262145)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(raw) != before.st_size:
            raise ValueError("metadata changed")
        return parse_strict_json(raw)
    finally:
        os.close(descriptor)


def preflight(
    manifest: Any, *, policy_file: Path, core_url: str, now: datetime
) -> tuple[SpatialDataSourceV1, SpatialDataPolicyV1, SpatialDataWorkerConfigV1]:
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != "spatial-data-public-sample.v1"
        or manifest.get("kind") not in PINS
    ):
        raise Blocked("INVALID_SAMPLE_MANIFEST")
    if not isinstance(manifest.get("sourceFile"), str):
        raise Blocked("INVALID_SAMPLE_MANIFEST")
    actual = original_identity(Path(manifest["sourceFile"]), kind=manifest["kind"])
    if not isinstance(manifest.get("sourceSnapshotFile"), str):
        raise Blocked("INSPECTION_UNAVAILABLE")
    try:
        source = SpatialDataSourceV1.model_validate(
            _bounded_json(Path(manifest["sourceSnapshotFile"]))
        )
        if (
            source.source_digest != source.canonical_digest()
            or source.observed_sha256 != actual
            or source.artifact_kind != manifest["kind"]
        ):
            raise ValueError("source identity")
        policy = SpatialDataPolicyV1.model_validate(_bounded_json(policy_file))
        if policy.policy_digest != policy.canonical_digest():
            raise ValueError("sealed data policy")
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise Blocked("INSPECTION_OR_POLICY_UNAVAILABLE") from exc
    if not isinstance(manifest.get("workerConfigFile"), str):
        raise Blocked("ISOLATION_UNVERIFIED")
    try:
        config = load_spatial_data_worker_config(Path(manifest["workerConfigFile"]), now=now)
        if config.policy != policy or config.core_origin.rstrip("/") != core_url.rstrip("/"):
            raise ValueError("worker/core/policy mismatch")
        raw = read_owner_private_file(
            Path(config.sandbox.containment_proof_path), maximum_bytes=262144
        )
        proof = SpatialDataContainmentProofV1.model_validate(parse_strict_json(raw))
        if (
            "sha256:" + hashlib.sha256(raw).hexdigest() != config.sandbox.containment_proof_sha256
            or proof.runtime_digest != config.runtime.runtime_digest
            or proof.launcher_sha256 != config.sandbox.launcher_sha256
            or proof.policy_digest != policy.policy_digest
            or proof.resource_envelope != policy.resource_envelope
            or proof.max_output_bytes != policy.max_output_bytes
            or proof.valid_until <= now
        ):
            raise ValueError("proof identity/expiry")
        launcher = Path(config.sandbox.launcher_path)
        if (
            "sha256:"
            + hashlib.sha256(
                read_owner_private_file(
                    launcher, maximum_bytes=16777216, allowed_modes=(0o500, 0o700)
                )
            ).hexdigest()
            != config.sandbox.launcher_sha256
        ):
            raise ValueError("launcher differs")
    except (OSError, ValueError, TypeError, SpatialDataWorkerConfigError) as exc:
        raise Blocked("ISOLATION_UNVERIFIED") from exc
    bounds = manifest.get("requestedBounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
        or not bounds[0] < bounds[2]
        or not bounds[1] < bounds[3]
        or not isinstance(manifest.get("idempotencyKey"), str)
    ):
        raise Blocked("INVALID_SAMPLE_MANIFEST")
    return source, policy, config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "token-file", "policy-file", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--core-url", required=True)
    args = parser.parse_args(argv)
    client = None
    try:
        try:
            manifest = _bounded_json(args.manifest)
        except (OSError, ValueError, RecursionError) as exc:
            raise Blocked("INVALID_SAMPLE_MANIFEST") from exc
        source, policy, config = preflight(
            manifest, policy_file=args.policy_file, core_url=args.core_url, now=datetime.now(UTC)
        )
        module = _client_module()
        client = module.NativeWindowClient(
            base_url=args.core_url,
            site_id=source.site_id,
            work_area_id=source.work_area_id,
            token=module.private_token(args.token_file),
            max_json_bytes=policy.max_json_bytes,
            max_file_bytes=policy.max_stream_bytes,
            timeout_seconds=policy.stream_deadline_seconds,
        )
        started = monotonic()
        measured = source.inspection.measurements
        if measured is None:
            raise Blocked("INSPECTION_UNAVAILABLE")
        request = dict(
            assetRef=source.asset_ref,
            requestedBounds=manifest["requestedBounds"],
            observedCrsDigest=measured.observed_crs_digest,
            resolutionMode="NATIVE",
            purpose="GENERAL_DATA_USE",
        )
        issued = client.issue(request=request, idempotency_key=manifest["idempotencyKey"])
        status = client.wait(
            issued["jobId"], timeout_seconds=policy.resource_envelope.max_deadline_seconds
        )
        receipt = status["receipt"]
        if (
            receipt["sourceDigest"] != source.source_digest
            or receipt["sourceSha256"] != source.observed_sha256
            or receipt["sourceSizeBytes"] != source.observed_size_bytes
            or receipt["policyDigest"] != policy.policy_digest
            or receipt["runtimeDigest"] != config.runtime.runtime_digest
            or receipt["requestedBounds"] != request["requestedBounds"]
            or receipt["observedCrsDigest"] != measured.observed_crs_digest
            or receipt["sourceTransform"] != list(measured.transform)
            or receipt["observedVerticalReference"]
            != (
                measured.observed_vertical_reference.model_dump(by_alias=True, mode="json")
                if measured.observed_vertical_reference
                else None
            )
            or receipt["accuracyAssessed"] is not False
            or ATTRIBUTION.split(";")[0] not in receipt["attribution"]
        ):
            raise Blocked("RECEIPT_BINDING_MISMATCH")
        output = client.download(status=status, output_dir=args.output_dir)
        record = {
            "status": "byte_receipt_verified",
            "jobId": status["jobId"],
            "receipt": receipt,
            "outputFile": output.name,
            "sourceBytes": source.observed_size_bytes,
            "elapsedSeconds": monotonic() - started,
            "attribution": ATTRIBUTION,
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "orthoPublisherResolutionMeters": 0.02 if source.artifact_kind == "ortho" else None,
            "observedResolutionMeters": receipt["sourceResolution"],
            "hostContainmentVerified": False,
            "publicPixelMaskComparison": "NOT_RUN_REQUIRES_ISOLATED_INDEPENDENT_CONSUMER",
            "workerPeakRssCpuWorkspace": "NOT_MEASURED_BY_HTTP_CLIENT",
            "customerAcceptance": False,
        }
        evidence = args.output_dir / (status["jobId"] + ".verification.json")
        with evidence.open("x", encoding="utf-8") as sink:
            json.dump(record, sink, allow_nan=False, indent=2)
            sink.write("\n")
        print(json.dumps(record, allow_nan=False))
        return 0
    except Exception as exc:
        reason = (
            str(exc)
            if isinstance(exc, Blocked)
            else getattr(exc, "reason", "PREREQUISITE_UNAVAILABLE")
        )
        if not isinstance(reason, str) or not reason.replace("_", "").isupper() or len(reason) > 80:
            reason = "PREREQUISITE_UNAVAILABLE"
        print(json.dumps({"status": "blocked", "reason": reason, "customerAcceptance": False}))
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
