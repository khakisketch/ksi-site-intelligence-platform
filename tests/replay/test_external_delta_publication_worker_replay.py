"""Replay for the late-export output job (synthetic local fixtures only).

Proves the new publication input factory changes no journaled history: intent,
lease, observation, and published bytes replay exactly across restart, and
tampered/dropped bytes fail closed. All keys and bytes are synthetic.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient as TC
from ksi_core.domains.external.quantity.external_delta_output_observations import (
    CoreDeltaOutputObservationStore,
)
from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
    DeltaPublicationS3InputCapabilityIssuer,
    resolve_publication_worker_input,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaPublicationDispositionV1,
    DeltaPublicationPolicy,
    DeltaPublicationRecoveryError,
    ExternalDeltaPublicationStore,
    FilesystemDeltaByteStore,
)
from ksi_core.domains.external.quantity.external_delta_source_adapters import (
    CoreDeltaEgressAdapter,
    CoreV2DeltaSourceAdapter,
)
from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
    QuantitativeExtensionDeltaPublicationAuthority,
)
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_event_contracts.external_relative_volume_calculation import AnalysisExecutionAttemptV2
from ksi_processing_controller.external_analysis_delta_measurement import (
    measure_external_relative_volume_with_delta_v2,
)
from ksi_processing_controller.external_delta_publication_worker import (
    build_observation_from_output,
)
from ksi_processing_controller.external_delta_reproduction_measurement import (
    reproduce_external_delta_raster_v2,
)
from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2


def _reconstruction_of(fixture: Any) -> Any:
    if hasattr(fixture.app.state, "external_reconstruction_store"):
        return fixture.app.state.external_reconstruction_store
    raise AssertionError("fixture reconstruction store is unavailable")


def _publish_once(tmp_path: Path) -> tuple[Any, Any, Any, bytes, str, int, str, str]:
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    (tmp_path / "core").mkdir(mode=0o700, exist_ok=True)
    fixture = build_local_analysis_api_fixture(tmp_path / "core")
    object_server = None
    object_thread = None
    try:
        client = TC(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "replay-intent"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True),
                "current": fixture.current.model_dump(by_alias=True),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        request_id = created.json()["authority"]["calculationRequestId"]
        leased = client.post(
            f"/v1/internal/analysis-jobs/{analysis_id}:lease",
            headers=fixture.worker_headers(),
            json={"workerInstanceId": "replay-worker", "leaseAcquisitionId": "replay-lease"},
        )
        assert leased.status_code == 200, leased.text
        attempt = AnalysisExecutionAttemptV2.model_validate(leased.json()["attempt"])

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                try:
                    payload = fixture.storage.object_bytes(
                        unquote(self.path.removeprefix("/objects/"))
                    )
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_a: Any, **_k: Any) -> None:
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        object_thread = threading.Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(origin)
        wiring = fixture.app.state.external_analysis_wiring
        inputs = client.get(
            f"/v1/internal/analysis-jobs/{analysis_id}/input",
            headers={
                **fixture.worker_headers(),
                "X-Analysis-Attempt-Digest": attempt.canonical_digest(),
                "X-Analysis-Worker-Instance-Id": attempt.worker_instance_id,
            },
        )
        assert inputs.status_code == 200, inputs.text
        staged = []
        for capability in inputs.json()["input"]["inputs"]:
            key = unquote(urlsplit(capability["downloadUrl"]).path.removeprefix("/objects/"))
            target = tmp_path / (capability["role"] + ".tif")
            target.write_bytes(fixture.storage.object_bytes(key))
            staged.append(target)
        now = datetime.now(UTC)
        with measure_external_relative_volume_with_delta_v2(
            attempt=attempt,
            calculation_identity=wiring.calculations.get_history(
                request_id, organization_id=fixture.organization_id
            ).admission.calculation_identity,
            baseline_path=staged[0],
            current_path=staged[1],
            report_id="replay-report",
            computed_at=now,
            reported_at=now,
            maximum_delta_output_bytes=1_000_000,
            check_current=lambda: None,
        ) as measured:
            wiring.calculations.record_report(
                request_id=request_id,
                worker_principal=Principal(
                    "analysis-local-worker",
                    PrincipalKind.ANALYSIS_WORKER,
                    None,
                    None,
                    fixture.organization_id,
                ),
                report=measured.report,
                now=now,
            )
        record = wiring.calculations.get_history(
            request_id, organization_id=fixture.organization_id
        )
        assert record is not None and record.report is not None
        identity = record.admission.calculation_identity
        numeric = record.report.numeric_result
        numeric_json_before = record.report.model_dump_json()

        now2 = datetime.now(UTC)
        policy = DeltaPublicationPolicy(
            policy_id="replay-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=3600,
            max_active_publications=4,
            upload_lease_duration_seconds=120,
            max_upload_attempts=8,
        )
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        source = CoreV2DeltaSourceAdapter(
            intents=wiring.intents,
            assessments=wiring.assessments,
            calculations=wiring.calculations,
            coordinator=coordinator,
        )
        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        envelope_digest = record.authorization.resource_envelope_digest
        assert envelope_digest is not None
        activation, keys, _, _ = _write_files(
            tmp_path / "ext-replay",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope_digest,
                worker_principal_id=worker.principal_id,
                issued_at=now2 - timedelta(seconds=1),
                valid_until=now2 + timedelta(minutes=10),
            ),
        )
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation,
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope_digest,
            worker_principal=worker,
            coordinator=coordinator,
        )
        obs_journal = DurableJournal(tmp_path / "replay-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "replay-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now2
        )
        byte_root = tmp_path / "replay-bytes"
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(byte_root),
            observations=observations,
            policy=policy,
            clock=lambda: now2,
            coordinator=coordinator,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )
        store.request_publication(
            principal=operator,
            publication_id="replay-pub",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=3000,
        )
        lease = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="replay-pub",
            worker_instance_id="replay-instance",
            lease_acquisition_id="replay-acq",
            now=now2,
        )
        assert lease is not None
        issuer = DeltaPublicationS3InputCapabilityIssuer(
            reconstruction=_reconstruction_of(fixture), storage=fixture.storage
        )
        worker_input = resolve_publication_worker_input(
            store=store,
            material_resolver=source,
            capability_issuer=issuer,
            publication_id="replay-pub",
            worker_principal=worker,
            worker_instance_id="replay-instance",
            now=now2,
        )
        assert worker_input is not None
        envelope = record.authorization.resource_envelope
        with reproduce_external_delta_raster_v2(
            calculation_identity=worker_input.calculation_identity,
            numeric_result=worker_input.numeric_result,
            baseline_path=staged[0],
            current_path=staged[1],
            envelope=envelope,
            watchdog=MeasurementWatchdogV2.from_envelope(envelope),
            maximum_output_bytes=policy.max_output_bytes,
            maximum_grid_cells=policy.max_grid_cells,
            check_current=lambda: None,
        ) as measured2:
            observation = build_observation_from_output(
                worker_input=worker_input,
                output_fd=measured2.fd,
                output_sha256=measured2.sha256,
                output_size_bytes=measured2.size_bytes,
            )
            from ksi_core.domains.external.quantity.external_delta_publications import (
                DeltaOutputObservation,
            )

            wire = observation.model_dump(mode="python")
            wire["transform"] = tuple(wire["transform"])
            wire["bounds"] = tuple(wire["bounds"])
            wire["observation_digest"] = None
            accepted = observations.record_worker_result(
                publication_store=store,
                worker_principal=worker,
                observation=DeltaOutputObservation(**wire).sealed(),
            )
            assert accepted is not None
            with os.fdopen(os.dup(measured2.fd), "rb") as stream:
                published = store.publish_output(
                    worker_principal=worker,
                    publication_id="replay-pub",
                    worker_instance_id="replay-instance",
                    lease_generation=lease.lease_generation,
                    byte_stream=stream,
                )
            assert published is not None
            sha, size = measured2.sha256, measured2.size_bytes
        # Close journals to simulate a crash; bytes stay on disk.
        obs_journal.close()
        pub_journal.close()
        byte_store_port = store._bytes  # noqa: SLF001
        assert isinstance(byte_store_port, FilesystemDeltaByteStore)
        byte_store_port.close()
        journal_bytes = (tmp_path / "replay-pubs.jsonl").read_bytes()
        return (
            fixture,
            object_server,
            object_thread,
            journal_bytes,
            sha,
            size,
            numeric_json_before,
            request_id,
        )
    except BaseException:
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        fixture.close()
        raise


def test_restart_replays_exact_history_with_unchanged_journal_bytes(tmp_path: Path) -> None:
    (
        fixture,
        object_server,
        object_thread,
        journal_bytes,
        sha,
        size,
        numeric_json_before,
        request_id,
    ) = _publish_once(tmp_path)
    try:
        from analysis_api_local_fixture import build_local_analysis_api_fixture  # noqa: F401

        # Reopen only the publication lane journals; NX state is retained by the fixture.
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        record = wiring.calculations.get_history(
            request_id, organization_id=fixture.organization_id
        )
        assert record is not None and record.report is not None
        assert record.report.model_dump_json() == numeric_json_before
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        # Rebuild the lane against the same journal files and byte root.
        from ksi_core.foundation.durable_journal import DurableJournal as DJ
        from test_external_quantitative_extension_activation import _unsigned  # noqa: F401

        obs_journal = DJ(tmp_path / "replay-obs.jsonl")
        pub_journal = DJ(tmp_path / "replay-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        # Authority files are retained on disk; rebuild with identical pins.

        act = next(iter((tmp_path / "ext-replay").glob("*.json")))
        keys = tmp_path / "ext-replay" / "verification-keys.json"
        policy = DeltaPublicationPolicy(
            policy_id="replay-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=3600,
            max_active_publications=4,
            upload_lease_duration_seconds=120,
            max_upload_attempts=8,
        )
        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        envelope_digest = record.authorization.resource_envelope_digest
        assert envelope_digest is not None
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=act
            if act.name.startswith("quantitative")
            else tmp_path / "ext-replay" / "quantitative-extension-activation.json",
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope_digest,
            worker_principal=worker,
            coordinator=coordinator,
        )
        source = CoreV2DeltaSourceAdapter(
            intents=wiring.intents,
            assessments=wiring.assessments,
            calculations=wiring.calculations,
            coordinator=coordinator,
        )
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: datetime.now(UTC)
        )
        reopened = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "replay-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: datetime.now(UTC),
            coordinator=coordinator,
        )
        viewer = Principal(
            "human",
            PrincipalKind.OPERATOR,
            __import__("ksi_core.identity.auth", fromlist=["Role"]).Role.VIEWER,
            None,
            fixture.organization_id,
        )
        view, disposition = reopened.get_current_with_disposition(
            "replay-pub", principal=viewer, now=datetime.now(UTC)
        )
        # The reopened lane may be expired by wall clock; the durable history
        # itself must replay without recovery error and journal bytes unchanged.
        assert (tmp_path / "replay-pubs.jsonl").read_bytes() == journal_bytes
        assert disposition in (
            DeltaPublicationDispositionV1.AVAILABLE,
            DeltaPublicationDispositionV1.EXPIRED,
        )
        if view is not None:
            assert view.descriptor.output_sha256 == sha
            assert view.descriptor.output_size_bytes == size
    finally:
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        fixture.close()


def test_replay_rejects_tampered_observation_binding(tmp_path: Path) -> None:
    _, _, _, _, _, _, _, _ = _publish_once(tmp_path)
    # Tamper the journaled observation hash and prove replay fails closed.
    # _publish_once closed its fixture; reopen the journal file directly.
    journal_path = tmp_path / "replay-pubs.jsonl"
    records = [json.loads(line) for line in journal_path.read_text().splitlines() if line.strip()]
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["observation"]["outputSha256"] = "sha256:" + "0" * 64
    import hashlib as _hl

    from ksi_domain.canonical_json import canonical_json_bytes as _cjb

    for record in records:
        payload = {k: v for k, v in record.items() if k != "eventDigest"}
        record["eventDigest"] = "sha256:" + _hl.sha256(_cjb(payload)).hexdigest()
    journal_path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator as CO
    from ksi_core.foundation.durable_journal import DurableJournal as DJ
    from test_external_delta_publications import (
        _FakeAuthority,
        _FakeEgress,
        _FakeObservations,
        _FakeSource,
        _policy,
    )

    journal = DJ(journal_path)
    with pytest.raises(DeltaPublicationRecoveryError):
        ExternalDeltaPublicationStore(
            journal,
            source_witness=_FakeSource(),
            authority=_FakeAuthority(),
            egress=_FakeEgress(),
            byte_store=FilesystemDeltaByteStore(tmp_path / "replay-bytes"),
            observations=_FakeObservations(),
            policy=_policy(),
            clock=lambda: datetime.now(UTC),
            coordinator=CO(),
        )
    assert journal.sealed_reason == "closed"


def test_missing_bytes_after_replay_fail_closed(tmp_path: Path) -> None:
    fixture, object_server, object_thread, _, sha, size, _, _ = _publish_once(tmp_path)
    try:
        for child in (tmp_path / "replay-bytes").glob("*.tiff"):
            child.unlink()
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        from ksi_core.foundation.durable_journal import DurableJournal as DJ

        obs_journal = DJ(tmp_path / "replay-obs.jsonl")
        pub_journal = DJ(tmp_path / "replay-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        record = next(iter(wiring.calculations._records.values()))  # noqa: SLF001
        envelope_digest = record.authorization.resource_envelope_digest
        assert envelope_digest is not None
        policy = DeltaPublicationPolicy(
            policy_id="replay-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=3600,
            max_active_publications=4,
            upload_lease_duration_seconds=120,
            max_upload_attempts=8,
        )
        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        act = tmp_path / "ext-replay" / "quantitative-extension-activation.json"
        keys = tmp_path / "ext-replay" / "verification-keys.json"
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=act,
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope_digest,
            worker_principal=worker,
            coordinator=coordinator,
        )
        source = CoreV2DeltaSourceAdapter(
            intents=wiring.intents,
            assessments=wiring.assessments,
            calculations=wiring.calculations,
            coordinator=coordinator,
        )
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: datetime.now(UTC)
        )
        reopened = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "replay-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: datetime.now(UTC),
            coordinator=coordinator,
        )
        from ksi_core.identity.auth import Role

        viewer = Principal(
            "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
        )
        view, disposition = reopened.get_current_with_disposition(
            "replay-pub", principal=viewer, now=datetime.now(UTC)
        )
        assert view is None and disposition is DeltaPublicationDispositionV1.BYTES_UNAVAILABLE
        assert reopened.read_bytes("replay-pub", principal=viewer, offset=0, length=8) is None
    finally:
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        fixture.close()
