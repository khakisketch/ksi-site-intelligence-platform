"""Late-export output job: real V2 source to verified bytes (synthetic only).

Covers the new workstream only: worker input contract, Core input factory,
native reproduction primitive, and the full lease → input → download →
reproduce → observe → publish handshake. All keys, bytes, and authority are
synthetic local fixtures, never production or release issuance.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def _complete_v2_report(tmp_path, label="delta-worker-e2e"):
    """Run the real local Analysis lane to a COMPLETED V2 report.

    Returns (fixture, record, identity, numeric, baseline_path, current_path).
    Uses actual generated DSM bytes and actual Core AP/NX stores.
    """
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from fastapi.testclient import TestClient as TC
    from ksi_core.identity.auth import Principal, PrincipalKind
    from ksi_event_contracts.external_relative_volume_calculation import (
        AnalysisExecutionAttemptV2,
    )
    from ksi_processing_controller.external_analysis_delta_measurement import (
        measure_external_relative_volume_with_delta_v2,
    )

    (tmp_path / "core").mkdir(mode=0o700, exist_ok=True)
    fixture = build_local_analysis_api_fixture(tmp_path / "core")
    try:
        client = TC(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": f"{label}-intent"},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True),
                "current": fixture.current.model_dump(by_alias=True),
            },
        )
        assert created.status_code == 202, created.text
        body = created.json()
        analysis_id = body["analysisId"]
        request_id = body["authority"]["calculationRequestId"]
        leased = client.post(
            f"/v1/internal/analysis-jobs/{analysis_id}:lease",
            headers=fixture.worker_headers(),
            json={"workerInstanceId": f"{label}-worker", "leaseAcquisitionId": f"{label}-lease"},
        )
        assert leased.status_code == 200, leased.text
        attempt = AnalysisExecutionAttemptV2.model_validate(leased.json()["attempt"])
        fixture.set_loopback_object_origin("http://127.0.0.1:8123")
        inputs = client.get(
            f"/v1/internal/analysis-jobs/{analysis_id}/input",
            headers={
                **fixture.worker_headers(),
                "X-Analysis-Attempt-Digest": attempt.canonical_digest(),
                "X-Analysis-Worker-Instance-Id": attempt.worker_instance_id,
            },
        )
        assert inputs.status_code == 200, inputs.text
        paths = []
        for capability in inputs.json()["input"]["inputs"]:
            key = unquote(urlsplit(capability["downloadUrl"]).path.removeprefix("/objects/"))
            role = capability["role"]
            target = tmp_path / (role + ".tif")
            target.write_bytes(fixture.storage.object_bytes(key))
            paths.append(target)
        wiring = fixture.app.state.external_analysis_wiring
        record = wiring.calculations.get_history(
            request_id, organization_id=fixture.organization_id
        )
        identity = record.admission.calculation_identity
        now = datetime.now(UTC)
        with measure_external_relative_volume_with_delta_v2(
            attempt=attempt,
            calculation_identity=identity,
            baseline_path=paths[0],
            current_path=paths[1],
            report_id=f"{label}-report",
            computed_at=now,
            reported_at=now,
            maximum_delta_output_bytes=1_000_000,
            check_current=lambda: None,
        ) as measured:
            assert measured.report is not None and measured.delta is not None
            accepted = wiring.calculations.record_report(
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
            assert accepted is not None
            final = wiring.calculations.get_history(
                request_id, organization_id=fixture.organization_id
            )
            assert final is not None and final.report is not None
            return fixture, final, identity, final.report.numeric_result, paths[0], paths[1]
    except BaseException:
        fixture.close()
        raise


def test_worker_input_contract_binds_exact_lease_and_rejects_drift(tmp_path):
    fixture, record, identity, numeric, _, _ = _complete_v2_report(tmp_path, "worker-contract")
    try:
        from ksi_core.domains.external.quantity.external_delta_output_observations import (
            CoreDeltaOutputObservationStore,
        )
        from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
            DeltaPublicationS3InputCapabilityIssuer,
            resolve_publication_worker_input,
        )
        from ksi_core.domains.external.quantity.external_delta_publications import (
            DeltaPublicationPolicy,
            ExternalDeltaPublicationStore,
            FilesystemDeltaByteStore,
        )
        from ksi_core.domains.external.quantity.external_delta_source_adapters import (
            CoreV2DeltaSourceAdapter,
            DeltaSourceMaterialV1,
        )
        from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
            QuantitativeExtensionDeltaPublicationAuthority,
        )
        from ksi_core.foundation.durable_journal import DurableJournal
        from ksi_core.identity.auth import Principal, PrincipalKind, Role
        from test_external_quantitative_extension_activation import _unsigned, _write_files

        now = datetime.now(UTC)
        policy = DeltaPublicationPolicy(
            policy_id="worker-contract-policy",
            version=1,
            max_output_bytes=1_000_000,
            max_grid_cells=100_000,
            max_lifetime_seconds=600,
            max_active_publications=4,
            upload_lease_duration_seconds=60,
            max_upload_attempts=8,
        )
        wiring = fixture.app.state.external_analysis_wiring
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
        # Narrow material resolves the exact sealed identity plus sealed report.
        material = source.resolve_current_material(
            organization_id=fixture.organization_id,
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            now=now,
        )
        assert isinstance(material, DeltaSourceMaterialV1)
        assert material.calculation_identity == identity
        assert material.report.numeric_result == numeric
        # Unknown digest, wrong scope, and revoked source all fail closed.
        assert (
            source.resolve_current_material(
                organization_id=fixture.organization_id,
                site_id=fixture.site_id,
                work_area_id=fixture.work_area_id,
                source_calculation_identity_digest="sha256:" + "0" * 64,
                source_numeric_result_identity_digest=numeric.canonical_digest(),
                source_coverage_witness_digest=numeric.coverage.canonical_digest(),
                now=now,
            )
            is None
        )
        assert (
            source.resolve_current_material(
                organization_id=fixture.organization_id,
                site_id="foreign",
                work_area_id=fixture.work_area_id,
                source_calculation_identity_digest=identity.canonical_digest(),
                source_numeric_result_identity_digest=numeric.canonical_digest(),
                source_coverage_witness_digest=numeric.coverage.canonical_digest(),
                now=now,
            )
            is None
        )

        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        envelope = record.authorization.resource_envelope_digest
        assert envelope is not None
        activation, keys, _, _ = _write_files(
            tmp_path / "ext-auth",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope,
                worker_principal_id=worker.principal_id,
                issued_at=now - timedelta(seconds=1),
                valid_until=now + timedelta(minutes=10),
            ),
        )
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation,
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope,
            worker_principal=worker,
            coordinator=coordinator,
        )
        from ksi_core.domains.external.quantity.external_delta_source_adapters import (
            CoreDeltaEgressAdapter,
        )

        obs_journal = DurableJournal(tmp_path / "delta-out-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "delta-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now
        )
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "delta-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: now,
            coordinator=coordinator,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )
        store.request_publication(
            principal=operator,
            publication_id="worker-input-e2e",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=300,
        )
        lease = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="worker-input-e2e",
            worker_instance_id="output-instance-1",
            lease_acquisition_id="output-acq-1",
            now=now,
        )
        assert lease is not None
        issuer = DeltaPublicationS3InputCapabilityIssuer(
            reconstruction=fixture.app.state.external_reconstruction_store
            if hasattr(fixture.app.state, "external_reconstruction_store")
            else _reconstruction_of(fixture),
            storage=fixture.storage,
        )
        worker_input = resolve_publication_worker_input(
            store=store,
            material_resolver=source,
            capability_issuer=issuer,
            publication_id="worker-input-e2e",
            worker_principal=worker,
            worker_instance_id="output-instance-1",
            now=now,
        )
        assert worker_input is not None
        assert worker_input.calculation_identity == identity
        assert worker_input.numeric_result == numeric
        assert worker_input.lease_generation == lease.lease_generation
        assert [c.role for c in worker_input.inputs] == ["BASELINE_DSM", "CURRENT_DSM"]
        assert all(c.expires_at <= lease.lease_expires_at for c in worker_input.inputs)
        # Foreign instance, unknown publication, and wrong generation-adjacent
        # principal all fail closed with no input.
        assert (
            resolve_publication_worker_input(
                store=store,
                material_resolver=source,
                capability_issuer=issuer,
                publication_id="worker-input-e2e",
                worker_principal=worker,
                worker_instance_id="other-instance",
                now=now,
            )
            is None
        )
        assert (
            resolve_publication_worker_input(
                store=store,
                material_resolver=source,
                capability_issuer=issuer,
                publication_id="missing",
                worker_principal=worker,
                worker_instance_id="output-instance-1",
                now=now,
            )
            is None
        )
        other = Principal(
            "analysis-worker-2", PrincipalKind.ANALYSIS_WORKER, None, None, fixture.organization_id
        )
        assert (
            resolve_publication_worker_input(
                store=store,
                material_resolver=source,
                capability_issuer=issuer,
                publication_id="worker-input-e2e",
                worker_principal=other,
                worker_instance_id="output-instance-1",
                now=now,
            )
            is None
        )
        # Mutated wire (capability order, sha, expiry, grid) is rejected by the
        # event contract, never repaired.
        from ksi_event_contracts.external_delta_publication_worker import (
            DeltaPublicationWorkerInputV1,
        )

        raw = worker_input.model_dump(by_alias=True, mode="json")
        swapped = dict(raw)
        swapped["inputs"] = [raw["inputs"][1], raw["inputs"][0]]
        with pytest.raises(ValidationError):
            DeltaPublicationWorkerInputV1.model_validate(swapped)
        bad_sha = dict(raw)
        bad_sha["inputs"] = [dict(raw["inputs"][0]), dict(raw["inputs"][1])]
        bad_sha["inputs"][0]["observedSha256"] = "sha256:" + "0" * 64
        with pytest.raises(ValidationError):
            DeltaPublicationWorkerInputV1.model_validate(bad_sha)
    finally:
        fixture.close()


def test_input_issuance_drops_urls_after_mid_presign_invalidation(tmp_path):
    """Presigning I/O runs outside the guard; the final recheck must drop URLs.

    A signer callback mutates Core state between the two presigned GETs
    (source revocation, lease cancel, trusted-clock advance). Issuance must
    return None in every case: no input URL may be handed out after the bound
    source/lease/policy it names has been invalidated. Already-signed URLs
    cannot be un-issued, but the later worker accept guards deny their use.
    """
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
        DeltaPublicationS3InputCapabilityIssuer,
        resolve_publication_worker_input,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
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
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    fixture, record, identity, numeric, _, _ = _complete_v2_report(tmp_path, "mid-presign")
    try:
        now_box = [datetime.now(UTC)]
        policy = DeltaPublicationPolicy(
            policy_id="mid-presign-policy",
            version=1,
            max_output_bytes=1_000_000,
            max_grid_cells=100_000,
            max_lifetime_seconds=600,
            max_active_publications=8,
            upload_lease_duration_seconds=60,
            max_upload_attempts=8,
        )
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )
        source = CoreV2DeltaSourceAdapter(
            intents=wiring.intents,
            assessments=wiring.assessments,
            calculations=wiring.calculations,
            coordinator=coordinator,
        )
        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        envelope = record.authorization.resource_envelope_digest
        assert envelope is not None
        activation, keys, _, _ = _write_files(
            tmp_path / "ext-mid",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope,
                worker_principal_id=worker.principal_id,
                issued_at=now_box[0] - timedelta(seconds=1),
                valid_until=now_box[0] + timedelta(minutes=10),
            ),
        )
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation,
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope,
            worker_principal=worker,
            coordinator=coordinator,
        )
        obs_journal = DurableJournal(tmp_path / "mid-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "mid-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now_box[0]
        )
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "mid-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: now_box[0],
            coordinator=coordinator,
        )

        class _MutatingStorage:
            """Delegate presigned_get, mutating Core state before the 2nd call."""

            def __init__(self, inner, mutate):
                self._inner = inner
                self._mutate = mutate
                self.calls = 0

            def presigned_get(self, object_key, *, ttl):
                self.calls += 1
                if self.calls == 2:
                    self._mutate()
                return self._inner.presigned_get(object_key, ttl=ttl)

        def _lane(suffix):
            publication_id = f"mid-presign-{suffix}"
            store.request_publication(
                principal=operator,
                publication_id=publication_id,
                site_id=fixture.site_id,
                work_area_id=fixture.work_area_id,
                source_calculation_identity_digest=identity.canonical_digest(),
                source_numeric_result_identity_digest=numeric.canonical_digest(),
                source_coverage_witness_digest=numeric.coverage.canonical_digest(),
                lifetime_seconds=300,
            )
            lease = store.acquire_upload_lease(
                worker_principal=worker,
                publication_id=publication_id,
                worker_instance_id="mid-instance",
                lease_acquisition_id=f"mid-acq-{suffix}",
                now=now_box[0],
            )
            assert lease is not None
            return publication_id

        def _resolve(publication_id, storage):
            issuer = DeltaPublicationS3InputCapabilityIssuer(
                reconstruction=_reconstruction_of(fixture),
                storage=storage,
                signing_clock=lambda: now_box[0],
            )
            return resolve_publication_worker_input(
                store=store,
                material_resolver=source,
                capability_issuer=issuer,
                publication_id=publication_id,
                worker_principal=worker,
                worker_instance_id="mid-instance",
                now=now_box[0],
            )

        # Sanity: plain issuance succeeds before any mutation.
        assert _resolve(_lane("plain"), fixture.storage) is not None, (
            "unmutated issuance must succeed"
        )

        # Case 1: lease canceled between the two presigns.
        canceled_pub = _lane("canceled")

        def _cancel():
            store.cancel_intent(
                principal=operator,
                publication_id=canceled_pub,
                reason="NO_LONGER_NEEDED",
                now=now_box[0],
            )

        assert _resolve(canceled_pub, _MutatingStorage(fixture.storage, _cancel)) is None

        # Case 2: trusted clock advances past the lease expiry mid-presign.
        clock_pub = _lane("clock")
        clock_journal_before = (tmp_path / "mid-pubs.jsonl").read_text()

        def _advance():
            now_box[0] = now_box[0] + timedelta(seconds=61)

        assert _resolve(clock_pub, _MutatingStorage(fixture.storage, _advance)) is None
        # A dropped issuance appends no journal event of its own.
        assert (tmp_path / "mid-pubs.jsonl").read_text() == clock_journal_before
        now_box[0] = now_box[0] - timedelta(seconds=61)
        # Case 3: source revoked between the two presigns (last: irreversible).
        revoked_pub = _lane("revoked")

        def _revoke():
            for context in fixture._retained_contexts:
                fixture.revoke_evidence_context(context.context_digest)

        assert _resolve(revoked_pub, _MutatingStorage(fixture.storage, _revoke)) is None
    finally:
        fixture.close()


def test_discovery_page_rejects_malformed_pages_and_bad_limits(tmp_path):
    """Closed discovery page: unknown fields, oversize, duplicates, bad ids fail."""
    import httpx
    from ksi_event_contracts.external_delta_publication_worker import DeltaPublicationPendingPageV1
    from ksi_processing_controller.external_delta_publication_worker import (
        DeltaPublicationCoreClient,
        DeltaPublicationWorkerError,
    )
    from pydantic import ValidationError

    assert (
        DeltaPublicationPendingPageV1.model_validate({"publicationIds": []}).publication_ids == ()
    )
    assert DeltaPublicationPendingPageV1.model_validate(
        {"publicationIds": ["pub-1", "pub_2", "a.b"]}
    ).publication_ids == ("pub-1", "pub_2", "a.b")
    with pytest.raises(ValidationError):
        DeltaPublicationPendingPageV1.model_validate(
            {"publicationIds": ["pub-1"], "unknownField": ["pub-1"]}
        )
    with pytest.raises(ValidationError):
        DeltaPublicationPendingPageV1.model_validate(
            {"publicationIds": [f"pub-{index}" for index in range(51)]}
        )
    with pytest.raises(ValidationError):
        DeltaPublicationPendingPageV1.model_validate({"publicationIds": ["pub-1", "pub-1"]})
    for bad in ("", "a/b", "..", "has space", "x" * 129):
        with pytest.raises(ValidationError):
            DeltaPublicationPendingPageV1.model_validate({"publicationIds": [bad]})

    client = DeltaPublicationCoreClient(
        base_url="http://127.0.0.1:9", bearer_token="discovery-token"
    )
    try:
        for bad_limit in (0, 51, -1, True, "50"):
            with pytest.raises(DeltaPublicationWorkerError):
                client.discover_pending(bad_limit)  # type: ignore[arg-type]

        def _over_limit(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/internal/delta-publication-uploads"
            assert request.url.params["limit"] == "2"
            return httpx.Response(200, json={"publicationIds": ["a", "b", "c"]})

        over_client = DeltaPublicationCoreClient(
            base_url="http://127.0.0.1:9",
            bearer_token="discovery-token",
            transport=httpx.MockTransport(_over_limit),
        )
        try:
            with pytest.raises(DeltaPublicationWorkerError):
                over_client.discover_pending(2)
        finally:
            over_client.close()

        def _duplicates(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"publicationIds": ["a", "a"]})

        dup_client = DeltaPublicationCoreClient(
            base_url="http://127.0.0.1:9",
            bearer_token="discovery-token",
            transport=httpx.MockTransport(_duplicates),
        )
        try:
            with pytest.raises(DeltaPublicationWorkerError):
                dup_client.discover_pending(50)
        finally:
            dup_client.close()
    finally:
        client.close()


def test_discovery_lists_only_takeable_pending_intents(tmp_path):
    """Store discovery: pending, in-scope, no-live-lease, unexhausted, current only.

    A lapsed lease does NOT hide the intent: a crashed or restarted worker
    that lost its publication id rediscovers the job and re-acquires it with
    a fresh acquisition id and the next generation, until the attempt cap is
    met.
    """
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
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
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    fixture, record, identity, numeric, _, _ = _complete_v2_report(tmp_path, "discovery-store")
    try:
        now_box = [datetime.now(UTC)]
        policy = DeltaPublicationPolicy(
            policy_id="discovery-policy",
            version=1,
            max_output_bytes=1_000_000,
            max_grid_cells=100_000,
            max_lifetime_seconds=300,
            max_active_publications=8,
            upload_lease_duration_seconds=60,
            max_upload_attempts=2,
        )
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )
        source = CoreV2DeltaSourceAdapter(
            intents=wiring.intents,
            assessments=wiring.assessments,
            calculations=wiring.calculations,
            coordinator=coordinator,
        )
        runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
        envelope = record.authorization.resource_envelope_digest
        assert envelope is not None
        activation, keys, _, _ = _write_files(
            tmp_path / "ext-discovery",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope,
                worker_principal_id=worker.principal_id,
                issued_at=now_box[0] - timedelta(seconds=1),
                valid_until=now_box[0] + timedelta(minutes=10),
            ),
        )
        authority = QuantitativeExtensionDeltaPublicationAuthority(
            activation_path=activation,
            verification_keys_path=keys,
            organization_id=fixture.organization_id,
            policy_digest=policy.canonical_digest(),
            runtime_digest=runtime,
            resource_envelope_digest=envelope,
            worker_principal=worker,
            coordinator=coordinator,
        )
        obs_journal = DurableJournal(tmp_path / "disc-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "disc-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now_box[0]
        )
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "disc-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: now_box[0],
            coordinator=coordinator,
        )
        digests = {
            "source_calculation_identity_digest": identity.canonical_digest(),
            "source_numeric_result_identity_digest": numeric.canonical_digest(),
            "source_coverage_witness_digest": numeric.coverage.canonical_digest(),
        }

        def _create(publication_id, lifetime_seconds=300):
            store.request_publication(
                principal=operator,
                publication_id=publication_id,
                site_id=fixture.site_id,
                work_area_id=fixture.work_area_id,
                lifetime_seconds=lifetime_seconds,
                **digests,
            )

        for bad_limit in (0, 51, -1, True, "50"):
            with pytest.raises(ValueError, match="discovery limit"):
                store.list_pending_for_worker(worker_principal=worker, limit=bad_limit)
        _create("disc-a")
        _create("disc-b")
        assert set(store.list_pending_for_worker(worker_principal=worker, limit=50)) == {
            "disc-a",
            "disc-b",
        }
        assert len(store.list_pending_for_worker(worker_principal=worker, limit=1)) == 1
        # Foreign organization and out-of-scope callers see nothing.
        foreign = Principal(
            "analysis-local-worker", PrincipalKind.ANALYSIS_WORKER, None, None, "org-foreign"
        )
        assert store.list_pending_for_worker(worker_principal=foreign, limit=50) == ()
        scoped_out = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
            allowed_site_ids=frozenset({"other-site"}),
            allowed_work_area_ids=frozenset({fixture.work_area_id}),
        )
        assert store.list_pending_for_worker(worker_principal=scoped_out, limit=50) == ()
        # A live lease hides the intent from every worker, holder included.
        lease_a = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="disc-a",
            worker_instance_id="disc-instance",
            lease_acquisition_id="disc-acq-a",
            now=now_box[0],
        )
        assert lease_a is not None and lease_a.lease_generation == 1
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ("disc-b",)
        # Recovery: a lapsed lease does not hide the intent. The crashed
        # worker rediscovers its job and re-acquires it with a fresh
        # acquisition id and the next generation, within the attempt cap.
        now_box[0] = now_box[0] + timedelta(seconds=61)
        assert set(store.list_pending_for_worker(worker_principal=worker, limit=50)) == {
            "disc-a",
            "disc-b",
        }
        reacquired = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="disc-a",
            worker_instance_id="disc-instance",
            lease_acquisition_id="disc-acq-a2",
            now=now_box[0],
        )
        assert reacquired is not None and reacquired.lease_generation == 2
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ("disc-b",)
        # Once the attempt cap is met the intent stays hidden even lapsed.
        now_box[0] = now_box[0] + timedelta(seconds=61)
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ("disc-b",)
        # Terminal states never list: canceled and failed.
        canceled = store.cancel_intent(
            principal=operator, publication_id="disc-b", reason="NO_LONGER_NEEDED", now=now_box[0]
        )
        assert canceled is not None
        _create("disc-c")
        lease_c = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="disc-c",
            worker_instance_id="disc-instance",
            lease_acquisition_id="disc-acq-c",
            now=now_box[0],
        )
        assert lease_c is not None
        failed = store.record_upload_failure(
            worker_principal=worker,
            publication_id="disc-c",
            worker_instance_id="disc-instance",
            lease_generation=lease_c.lease_generation,
            reason="WORKER_OOM",
            now=now_box[0],
        )
        assert failed is not None
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ()
        # Attempt-cap exhaustion hides an unleashed intent: two spent
        # generations meet max_upload_attempts=2 even after both leases lapse.
        # Before the cap is met, a lapsed first generation is rediscoverable.
        _create("disc-exhausted")
        first = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="disc-exhausted",
            worker_instance_id="disc-instance",
            lease_acquisition_id="disc-acq-1",
            now=now_box[0],
        )
        assert first is not None and first.lease_generation == 1
        now_box[0] = now_box[0] + timedelta(seconds=61)
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == (
            "disc-exhausted",
        )
        second = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="disc-exhausted",
            worker_instance_id="disc-instance",
            lease_acquisition_id="disc-acq-2",
            now=now_box[0],
        )
        assert second is not None and second.lease_generation == 2
        now_box[0] = now_box[0] + timedelta(seconds=61)
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ()
        # Expired intents never list.
        now_box[0] = datetime.now(UTC)
        _create("disc-short", lifetime_seconds=30)
        now_box[0] = now_box[0] + timedelta(seconds=31)
        assert store.list_pending_for_worker(worker_principal=worker, limit=50) == ()
    finally:
        fixture.close()


def _reconstruction_of(fixture):
    for candidate in (
        getattr(getattr(fixture.app.state, "external_analysis_wiring", None), "facade", None),
    ):
        if candidate is not None and hasattr(candidate, "_reconstruction"):
            return candidate._reconstruction
    if hasattr(fixture.app.state, "external_reconstruction_store"):
        return fixture.app.state.external_reconstruction_store
    wiring = fixture.app.state.external_analysis_wiring
    for name in ("reconstruction", "_reconstruction"):
        if hasattr(wiring, name):
            return getattr(wiring, name)
    raise AssertionError("fixture reconstruction store is unavailable")


def test_reproduction_primitive_reproduces_actual_bytes_and_rejects_drift(tmp_path):
    fixture, record, identity, numeric, baseline_path, current_path = _complete_v2_report(
        tmp_path, "repro-primitive"
    )
    try:
        from ksi_processing_controller.external_delta_reproduction_measurement import (
            ReproductionMeasurementError,
            reproduce_external_delta_raster_v2,
        )
        from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2

        envelope = record.authorization.resource_envelope
        watchdog = lambda: MeasurementWatchdogV2.from_envelope(envelope)  # noqa: E731
        # Happy path reproduces the sealed numeric bytes exactly.
        with reproduce_external_delta_raster_v2(
            calculation_identity=identity,
            numeric_result=numeric,
            baseline_path=baseline_path,
            current_path=current_path,
            envelope=envelope,
            watchdog=watchdog(),
            maximum_output_bytes=1_000_000,
            maximum_grid_cells=100_000,
            check_current=lambda: None,
        ) as measured:
            assert measured.numeric_result_identity_digest == numeric.canonical_digest()
            assert (measured.rows, measured.columns) == (
                numeric.coverage.rows,
                numeric.coverage.columns,
            )
            with rasterio.open(f"/proc/self/fd/{measured.fd}") as dataset:
                assert dataset.dtypes == ("float64",)
                assert dataset.tags()["DELTA_RULE"] == "CURRENT_MINUS_BASELINE"
            first_sha, first_size = measured.sha256, measured.size_bytes
        # Second run is deterministic.
        with reproduce_external_delta_raster_v2(
            calculation_identity=identity,
            numeric_result=numeric,
            baseline_path=baseline_path,
            current_path=current_path,
            envelope=envelope,
            watchdog=watchdog(),
            maximum_output_bytes=1_000_000,
            maximum_grid_cells=100_000,
            check_current=lambda: None,
        ) as second:
            assert (second.sha256, second.size_bytes) == (first_sha, first_size)
        # Bad sha file fails closed.
        tampered = tmp_path / "tampered-current.tif"
        tampered.write_bytes(current_path.read_bytes() + b"\x00")
        with (
            pytest.raises(ReproductionMeasurementError),
            reproduce_external_delta_raster_v2(
                calculation_identity=identity,
                numeric_result=numeric,
                baseline_path=baseline_path,
                current_path=tampered,
                envelope=envelope,
                watchdog=watchdog(),
                maximum_output_bytes=1_000_000,
                maximum_grid_cells=100_000,
                check_current=lambda: None,
            ),
        ):
            pytest.fail("tampered bytes were measured")
        # Byte cap fails before any native write.
        with (
            pytest.raises(ReproductionMeasurementError),
            reproduce_external_delta_raster_v2(
                calculation_identity=identity,
                numeric_result=numeric,
                baseline_path=baseline_path,
                current_path=current_path,
                envelope=envelope,
                watchdog=watchdog(),
                maximum_output_bytes=10,
                maximum_grid_cells=100_000,
                check_current=lambda: None,
            ),
        ):
            pytest.fail("oversized output was exposed")

        # Stale guard never exposes bytes.
        def _revoked():
            raise RuntimeError("REVOKED")

        with (
            pytest.raises(RuntimeError),
            reproduce_external_delta_raster_v2(
                calculation_identity=identity,
                numeric_result=numeric,
                baseline_path=baseline_path,
                current_path=current_path,
                envelope=envelope,
                watchdog=watchdog(),
                maximum_output_bytes=1_000_000,
                maximum_grid_cells=100_000,
                check_current=_revoked,
            ),
        ):
            pytest.fail("revoked operation was exposed")
        # Numeric drift (plausible but wrong metrics) fails closed.
        from ksi_event_contracts.external_relative_volume_calculation import (
            RelativeVolumeMetricsV2,
            RelativeVolumeNumericResultV2,
        )

        drifted = RelativeVolumeNumericResultV2(
            calculation_identity_digest=numeric.calculation_identity_digest,
            profile_digest=numeric.profile_digest,
            metrics=RelativeVolumeMetricsV2(
                cut_m3=numeric.metrics.cut_m3 + 1.0,
                fill_m3=numeric.metrics.fill_m3,
                net_m3=numeric.metrics.net_m3 - 1.0,
                threshold_m=0.0,
            ),
            coverage=numeric.coverage,
        ).sealed()
        with (
            pytest.raises(ReproductionMeasurementError),
            reproduce_external_delta_raster_v2(
                calculation_identity=identity,
                numeric_result=drifted,
                baseline_path=baseline_path,
                current_path=current_path,
                envelope=envelope,
                watchdog=watchdog(),
                maximum_output_bytes=1_000_000,
                maximum_grid_cells=100_000,
                check_current=lambda: None,
            ),
        ):
            pytest.fail("drifted numeric was exported")
    finally:
        fixture.close()


def test_full_handshake_lease_input_download_reproduce_observe_publish(tmp_path):
    """End-to-end late-export job over real stores, loopback objects, and routers."""
    import hashlib as _hashlib
    import time

    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from fastapi.testclient import TestClient as TC
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_api import (
        build_external_delta_publication_router,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
        DeltaPublicationS3InputCapabilityIssuer,
        build_external_delta_publication_input_router,
        resolve_publication_worker_input,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
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
    from ksi_core.identity.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
        mount_auth,
    )
    from ksi_event_contracts.external_relative_volume_calculation import AnalysisExecutionAttemptV2
    from ksi_processing_controller.external_analysis_delta_measurement import (
        measure_external_relative_volume_with_delta_v2,
    )
    from ksi_processing_controller.external_delta_publication_worker import (
        build_observation_from_output,
        download_inputs,
    )
    from ksi_processing_controller.external_delta_reproduction_measurement import (
        reproduce_external_delta_raster_v2,
    )
    from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline
    from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2
    from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectCapabilityV1,
        ExternalObjectHttpByteSource,
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    (tmp_path / "core").mkdir(mode=0o700, exist_ok=True)
    fixture = build_local_analysis_api_fixture(tmp_path / "core")
    object_server = None
    object_thread = None
    try:
        client = TC(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "handshake-intent"},
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
            json={"workerInstanceId": "handshake-worker", "leaseAcquisitionId": "handshake-lease"},
        )
        assert leased.status_code == 200, leased.text
        attempt = AnalysisExecutionAttemptV2.model_validate(leased.json()["attempt"])

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
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

            def log_message(self, *_a, **_k):
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
            from urllib.parse import unquote as _unquote
            from urllib.parse import urlsplit as _split

            key = _unquote(_split(capability["downloadUrl"]).path.removeprefix("/objects/"))
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
            report_id="handshake-report",
            computed_at=now,
            reported_at=now,
            maximum_delta_output_bytes=1_000_000,
            check_current=lambda: None,
        ) as measured:
            accepted = wiring.calculations.record_report(
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
            assert accepted is not None
        record = wiring.calculations.get_history(
            request_id, organization_id=fixture.organization_id
        )
        assert record is not None and record.report is not None
        identity = record.admission.calculation_identity
        numeric = record.report.numeric_result

        # Publication lane over the SAME actual stores.
        now2 = datetime.now(UTC)
        policy = DeltaPublicationPolicy(
            policy_id="handshake-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=600,
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
            tmp_path / "ext-handshake",
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
        obs_journal = DurableJournal(tmp_path / "hs-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "hs-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now2
        )
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "hs-bytes"),
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
            publication_id="handshake-pub",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=300,
        )
        lease = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="handshake-pub",
            worker_instance_id="output-instance-9",
            lease_acquisition_id="output-acq-9",
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
            publication_id="handshake-pub",
            worker_principal=worker,
            worker_instance_id="output-instance-9",
            now=now2,
        )
        assert worker_input is not None

        # Download via the pinned object transport (real loopback HTTP).
        envelope = record.authorization.resource_envelope
        transport = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16_384,
            max_object_bytes=envelope.max_input_bytes,
            max_chunk_bytes=min(65_536, envelope.max_input_bytes),
        )
        byte_source = ExternalObjectHttpByteSource(
            (
                ExternalObjectCapabilityV1(
                    artifact=MeasurementInputV2(
                        role=c.role,
                        artifact_id=c.artifact_id,  # type: ignore[arg-type]
                        observed_sha256=c.observed_sha256,
                        observed_size_bytes=c.observed_size_bytes,
                    ),
                    url=c.download_url,
                    required_headers=dict(c.required_headers),
                )
                for c in worker_input.inputs
            ),
            policy=transport,
        )
        work_dir = tmp_path / "worker-stage"
        work_dir.mkdir(mode=0o700)
        deadline = ProtocolDeadline.at_expires_at(time.monotonic() + 30)
        baseline_local, current_local = download_inputs(
            worker_input=worker_input,
            source=byte_source,
            work_dir=work_dir,
            deadline=deadline,
            is_current=lambda: True,
            heartbeat_interval_millis=25,
            max_chunk_bytes=65_536,
        )
        assert baseline_local.exists() and current_local.exists()

        # Reproduce the exact delta bytes; old numeric report is unchanged.
        before_json = record.report.model_dump_json()
        with reproduce_external_delta_raster_v2(
            calculation_identity=worker_input.calculation_identity,
            numeric_result=worker_input.numeric_result,
            baseline_path=baseline_local,
            current_path=current_local,
            envelope=envelope,
            watchdog=MeasurementWatchdogV2.from_envelope(envelope),
            maximum_output_bytes=policy.max_output_bytes,
            maximum_grid_cells=policy.max_grid_cells,
            check_current=lambda: None,
        ) as measured2:
            assert measured2.numeric_result_identity_digest == numeric.canonical_digest()
            observation = build_observation_from_output(
                worker_input=worker_input,
                output_fd=measured2.fd,
                output_sha256=measured2.sha256,
                output_size_bytes=measured2.size_bytes,
            )
            assert observation.grid_rows == numeric.coverage.rows
            from ksi_core.domains.external.quantity.external_delta_publications import (
                DeltaOutputObservation,
            )

            _wire_python = observation.model_dump(mode="python")
            _wire_python["transform"] = tuple(_wire_python["transform"])
            _wire_python["bounds"] = tuple(_wire_python["bounds"])
            _wire_python["observation_digest"] = None
            accepted_obs = observations.record_worker_result(
                publication_store=store,
                worker_principal=worker,
                observation=DeltaOutputObservation(**_wire_python).sealed(),
            )
            assert accepted_obs is not None
            with os.fdopen(os.dup(measured2.fd), "rb") as stream:
                published = store.publish_output(
                    worker_principal=worker,
                    publication_id="handshake-pub",
                    worker_instance_id="output-instance-9",
                    lease_generation=lease.lease_generation,
                    byte_stream=stream,
                )
            assert published is not None
            assert published.descriptor.output_sha256 == measured2.sha256
            content = store.read_bytes(
                "handshake-pub",
                principal=Principal(
                    "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
                ),
                offset=0,
                length=measured2.size_bytes,
            )
            assert content is not None
            assert "sha256:" + hashlib.sha256(content).hexdigest() == measured2.sha256
        after = wiring.calculations.get_history(request_id, organization_id=fixture.organization_id)
        assert after is not None and after.report is not None
        assert after.report.model_dump_json() == before_json

        # Closed HTTP protocol: lease/input/observation/bytes/failure routers.
        app = FastAPI()
        app.include_router(build_external_delta_publication_router(store=store, clock=lambda: now2))
        app.include_router(
            build_external_delta_publication_input_router(
                store=store, material_resolver=source, capability_issuer=issuer, clock=lambda: now2
            )
        )
        operator_token, worker_token = "op-token", "wk-token"
        mount_auth(
            app,
            AuthRegistry(
                records=(
                    PrincipalTokenRecord(
                        token_sha256=_hashlib.sha256(operator_token.encode()).hexdigest(),
                        principal=operator,
                    ),
                    PrincipalTokenRecord(
                        token_sha256=_hashlib.sha256(worker_token.encode()).hexdigest(),
                        principal=worker,
                    ),
                )
            ),
        )
        http = TestClient(app, raise_server_exceptions=False)
        wk_h = {"Authorization": "Bearer " + worker_token}
        # The published fence no longer exposes a worker intent (pending only).
        got = http.get(
            "/v1/internal/delta-publication-uploads/handshake-pub",
            params={"worker_instance_id": "output-instance-9"},
            headers=wk_h,
        )
        assert got.status_code == 404, got.text
        # A fresh pending intent exposes its lease-bound input over HTTP.
        store.request_publication(
            principal=operator,
            publication_id="handshake-http",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=300,
        )
        http_lease = http.post(
            "/v1/internal/delta-publication-uploads/handshake-http/lease",
            headers={**wk_h, "Content-Type": "application/json"},
            json={"workerInstanceId": "output-instance-9", "leaseAcquisitionId": "http-acq-1"},
        )
        assert http_lease.status_code == 200, http_lease.text
        got = http.get(
            "/v1/internal/delta-publication-uploads/handshake-http",
            params={"worker_instance_id": "output-instance-9"},
            headers=wk_h,
        )
        assert got.status_code == 200, got.text
        inp = http.get(
            "/v1/internal/delta-publication-uploads/handshake-http/input",
            params={"worker_instance_id": "output-instance-9"},
            headers=wk_h,
        )
        assert inp.status_code == 200, inp.text
        assert inp.json()["input"]["publicationId"] == "handshake-http"
        # Foreign instance sees no job.
        missing = http.get(
            "/v1/internal/delta-publication-uploads/handshake-http/input",
            params={"worker_instance_id": "intruder"},
            headers=wk_h,
        )
        assert missing.status_code == 404
        # Observation source-version drift is rejected by the wire model.
        bad_obs = dict(observation.model_dump(by_alias=True, mode="json"))
        bad_obs["sourceContractVersion"] = "external-masked-volume-calculation-identity.v3"
        bad = http.post(
            "/v1/internal/delta-publication-uploads/handshake-http/observation",
            headers={**wk_h, "Content-Type": "application/json"},
            json=bad_obs,
        )
        assert bad.status_code in (404, 422)
        # Publication FAILED on a fresh intent does not rewrite numeric state.
        store.request_publication(
            principal=operator,
            publication_id="handshake-fail",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=300,
        )
        fail_lease = store.acquire_upload_lease(
            worker_principal=worker,
            publication_id="handshake-fail",
            worker_instance_id="output-instance-9",
            lease_acquisition_id="fail-acq-9",
            now=now2,
        )
        assert fail_lease is not None
        failed = store.record_upload_failure(
            worker_principal=worker,
            publication_id="handshake-fail",
            worker_instance_id="output-instance-9",
            lease_generation=fail_lease.lease_generation,
            reason="WORKER_OOM",
            now=now2,
        )
        assert failed is not None
        still = wiring.calculations.get_history(request_id, organization_id=fixture.organization_id)
        assert still is not None and still.report is not None
        assert still.report.model_dump_json() == before_json
    finally:
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        fixture.close()


def test_live_run_delta_publication_job_over_loopback_core_and_objects(tmp_path):
    """Full run_delta_publication_job against live loopback Core + objects.

    Real software only: a fresh FastAPI app mounting the new publication and
    input routers plus the real source/observation stores is served by uvicorn
    on an ephemeral loopback port with a fresh scoped test bearer and a
    temporary synthetic signed activation; DSM bytes come from a loopback
    object server on an ephemeral port. run_delta_publication_job must return
    PUBLISHED, the published bytes must hash to the descriptor, and the
    original NX numeric report must be byte-identical. No production service,
    no host provisioning, no OS-containment claim.
    """
    import secrets
    import socket as _socket
    import time as _time

    import uvicorn
    from fastapi import FastAPI
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_api import (
        build_external_delta_publication_router,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
        DeltaPublicationS3InputCapabilityIssuer,
        build_external_delta_publication_input_router,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
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
    from ksi_core.identity.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
        mount_auth,
    )
    from ksi_processing_controller.external_delta_publication_worker import (
        DeltaPublicationWorkerConfig,
        run_delta_publication_job,
    )
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    (tmp_path / "core").mkdir(mode=0o700, exist_ok=True)
    object_server = None
    object_thread = None
    core_server = None
    core_thread = None
    core_socket = None
    fixture = None
    try:
        fixture, record, identity, numeric, _, _ = _complete_v2_report(tmp_path, "live-run")
        before_json = record.report.model_dump_json()
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
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

            def log_message(self, *_a, **_k):
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        object_thread = threading.Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        now = datetime.now(UTC)
        policy = DeltaPublicationPolicy(
            policy_id="live-run-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=600,
            max_active_publications=4,
            upload_lease_duration_seconds=120,
            max_upload_attempts=8,
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
            tmp_path / "ext-live",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope_digest,
                worker_principal_id=worker.principal_id,
                issued_at=now - timedelta(seconds=1),
                valid_until=now + timedelta(minutes=10),
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
        obs_journal = DurableJournal(tmp_path / "live-obs.jsonl")
        pub_journal = DurableJournal(tmp_path / "live-pubs.jsonl")
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: datetime.now(UTC)
        )
        byte_root = tmp_path / "live-bytes"
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(byte_root),
            observations=observations,
            policy=policy,
            clock=lambda: datetime.now(UTC),
            coordinator=coordinator,
        )
        store.request_publication(
            principal=operator,
            publication_id="live-run-pub",
            site_id=fixture.site_id,
            work_area_id=fixture.work_area_id,
            source_calculation_identity_digest=identity.canonical_digest(),
            source_numeric_result_identity_digest=numeric.canonical_digest(),
            source_coverage_witness_digest=numeric.coverage.canonical_digest(),
            lifetime_seconds=300,
        )

        app = FastAPI()
        app.include_router(
            build_external_delta_publication_router(store=store, clock=lambda: datetime.now(UTC))
        )
        app.include_router(
            build_external_delta_publication_input_router(
                store=store,
                material_resolver=source,
                capability_issuer=DeltaPublicationS3InputCapabilityIssuer(
                    reconstruction=_reconstruction_of(fixture), storage=fixture.storage
                ),
                clock=lambda: datetime.now(UTC),
            )
        )
        operator_token, worker_token = secrets.token_hex(16), secrets.token_hex(16)
        mount_auth(
            app,
            AuthRegistry(
                records=(
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(operator_token.encode()).hexdigest(),
                        principal=operator,
                    ),
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                        principal=worker,
                    ),
                )
            ),
        )
        core_socket = _socket.socket()
        core_socket.bind(("127.0.0.1", 0))
        core_socket.listen(128)
        core_origin = f"http://127.0.0.1:{core_socket.getsockname()[1]}"
        core_server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        core_thread = threading.Thread(
            target=lambda: core_server.run(sockets=[core_socket]), daemon=True
        )
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive(), "local Core server stopped during startup"
            _time.sleep(0.02)
        assert core_server.started

        envelope = record.authorization.resource_envelope
        work_dir = tmp_path / "live-work"
        work_dir.mkdir(mode=0o700)
        config = DeltaPublicationWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token=worker_token,
            worker_instance_id="live-run-instance",
            publication_id="live-run-pub",
            lease_acquisition_id="live-run-acq",
            transport_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            ),
            work_dir=work_dir,
            envelope=envelope,
            maximum_output_bytes=policy.max_output_bytes,
            maximum_grid_cells=policy.max_grid_cells,
        )
        assert (
            run_delta_publication_job(config=config, worker_principal_id=worker.principal_id)
            == "PUBLISHED"
        )
        view = store.get_current(
            "live-run-pub",
            principal=Principal(
                "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
            ),
            now=datetime.now(UTC),
        )
        assert view is not None and view.descriptor.dtype == "FLOAT64"
        content = store.read_bytes(
            "live-run-pub",
            principal=Principal(
                "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
            ),
            offset=0,
            length=view.descriptor.output_size_bytes,
        )
        assert content is not None
        assert "sha256:" + hashlib.sha256(content).hexdigest() == view.descriptor.output_sha256
        recalculated = wiring.calculations.get_history(
            record.request_id, organization_id=fixture.organization_id
        )
        assert recalculated is not None and recalculated.report is not None
        assert recalculated.report.model_dump_json() == before_json
    finally:
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=10)
        if core_socket is not None:
            core_socket.close()
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        if fixture is not None:
            fixture.close()


def test_drain_recovers_lapsed_lease_with_fresh_generation(tmp_path):
    """Live drain: restart after a crash re-acquires the lapsed lease at gen2.

    Human operator creates three publications over HTTP without the driver
    ever learning an id out of band. A crashed worker's gen-1 lease on
    ``drain-a`` lapses; a third publication exhausts the attempt cap. The
    driver discovers only the takeable ids, drains them to PUBLISHED with a
    fresh acquisition id (``drain-a`` completes at lease generation 2), and
    leaves the exhausted intent hidden. Published hashes match descriptors
    and the original NX numeric report is byte-identical.
    """
    import json as _json
    import secrets
    import socket as _socket
    import time as _time

    import httpx
    import uvicorn
    from fastapi import FastAPI
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_api import (
        build_external_delta_publication_router,
    )
    from ksi_core.domains.external.quantity.external_delta_publication_inputs import (
        DeltaPublicationS3InputCapabilityIssuer,
        build_external_delta_publication_input_router,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaPublicationPolicy,
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
    from ksi_core.identity.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
        mount_auth,
    )
    from ksi_processing_controller.external_delta_publication_driver import (
        run_pending_delta_publications,
    )
    from ksi_processing_controller.external_delta_publication_worker import (
        DeltaPublicationWorkerConfig,
    )
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    (tmp_path / "core").mkdir(mode=0o700, exist_ok=True)
    object_server = None
    object_thread = None
    core_server = None
    core_thread = None
    core_socket = None
    fixture = None
    try:
        fixture, record, identity, numeric, _, _ = _complete_v2_report(tmp_path, "drain-run")
        before_json = record.report.model_dump_json()
        wiring = fixture.app.state.external_analysis_wiring
        coordinator = wiring.assessments.coordinator
        worker = Principal(
            "analysis-local-worker",
            PrincipalKind.ANALYSIS_WORKER,
            None,
            None,
            fixture.organization_id,
        )
        operator = Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        )

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
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

            def log_message(self, *_a, **_k):
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        object_thread = threading.Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        now_box = [datetime.now(UTC)]
        policy = DeltaPublicationPolicy(
            policy_id="drain-policy",
            version=1,
            max_output_bytes=2_000_000,
            max_grid_cells=1_000_000,
            max_lifetime_seconds=600,
            max_active_publications=8,
            upload_lease_duration_seconds=60,
            max_upload_attempts=2,
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
            tmp_path / "ext-drain",
            unsigned=_unsigned(
                purpose="DELTA_PUBLICATION_V1",
                organization_id=fixture.organization_id,
                policy_digest=policy.canonical_digest(),
                runtime_digest=runtime,
                envelope_digest=envelope_digest,
                worker_principal_id=worker.principal_id,
                issued_at=now_box[0] - timedelta(seconds=1),
                valid_until=now_box[0] + timedelta(minutes=10),
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
        obs_journal = DurableJournal(tmp_path / "drain-obs.jsonl")
        pub_journal_path = tmp_path / "drain-pubs.jsonl"
        pub_journal = DurableJournal(pub_journal_path)
        fixture.opened.extend([obs_journal, pub_journal])
        observations = CoreDeltaOutputObservationStore(
            obs_journal, coordinator=coordinator, clock=lambda: now_box[0]
        )
        store = ExternalDeltaPublicationStore(
            pub_journal,
            source_witness=source,
            authority=authority,
            egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
            byte_store=FilesystemDeltaByteStore(tmp_path / "drain-bytes"),
            observations=observations,
            policy=policy,
            clock=lambda: now_box[0],
            coordinator=coordinator,
        )
        app = FastAPI()
        app.include_router(
            build_external_delta_publication_router(store=store, clock=lambda: now_box[0])
        )
        app.include_router(
            build_external_delta_publication_input_router(
                store=store,
                material_resolver=source,
                capability_issuer=DeltaPublicationS3InputCapabilityIssuer(
                    reconstruction=_reconstruction_of(fixture),
                    storage=fixture.storage,
                    signing_clock=lambda: now_box[0],
                ),
                clock=lambda: now_box[0],
            )
        )
        operator_token, worker_token = secrets.token_hex(16), secrets.token_hex(16)
        mount_auth(
            app,
            AuthRegistry(
                records=(
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(operator_token.encode()).hexdigest(),
                        principal=operator,
                    ),
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                        principal=worker,
                    ),
                )
            ),
        )
        core_socket = _socket.socket()
        core_socket.bind(("127.0.0.1", 0))
        core_socket.listen(128)
        core_origin = f"http://127.0.0.1:{core_socket.getsockname()[1]}"
        core_server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        core_thread = threading.Thread(
            target=lambda: core_server.run(sockets=[core_socket]), daemon=True
        )
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive(), "local Core server stopped during startup"
            _time.sleep(0.02)
        assert core_server.started

        site_path = f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}"
        create_body = {
            "publicationId": "placeholder",
            "sourceCalculationIdentityDigest": identity.canonical_digest(),
            "sourceNumericResultIdentityDigest": numeric.canonical_digest(),
            "sourceCoverageWitnessDigest": numeric.coverage.canonical_digest(),
            "lifetimeSeconds": 300,
        }
        with httpx.Client(
            base_url=core_origin,
            trust_env=False,
            headers={"Authorization": "Bearer " + operator_token},
        ) as human:
            for publication_id in ("drain-a", "drain-b", "drain-c"):
                created = human.post(
                    site_path + "/delta-publications",
                    json={**create_body, "publicationId": publication_id},
                )
                assert created.status_code == 200, created.text
        worker_headers = {"Authorization": "Bearer " + worker_token}
        with httpx.Client(base_url=core_origin, trust_env=False) as crashed:
            # Crashed worker: gen-1 lease on drain-a, then the process dies
            # and the lease lapses. The publication id is lost with it.
            leased = crashed.post(
                "/v1/internal/delta-publication-uploads/drain-a/lease",
                headers=worker_headers,
                json={"workerInstanceId": "crashed-instance", "leaseAcquisitionId": "crashed-acq"},
            )
            assert leased.status_code == 200, leased.text
            assert leased.json()["leaseGeneration"] == 1
            now_box[0] = now_box[0] + timedelta(seconds=61)
            # Exhaust drain-c: two spent generations meet the cap, then lapse.
            for acquisition_id, generation in (("drain-c-acq-1", 1), ("drain-c-acq-2", 2)):
                leased_c = crashed.post(
                    "/v1/internal/delta-publication-uploads/drain-c/lease",
                    headers=worker_headers,
                    json={
                        "workerInstanceId": "drain-instance",
                        "leaseAcquisitionId": acquisition_id,
                    },
                )
                assert leased_c.status_code == 200, leased_c.text
                assert leased_c.json()["leaseGeneration"] == generation
                now_box[0] = now_box[0] + timedelta(seconds=61)

        envelope = record.authorization.resource_envelope
        work_dir = tmp_path / "drain-work"
        work_dir.mkdir(mode=0o700)
        config = DeltaPublicationWorkerConfig(
            core_base_url=core_origin,
            core_bearer_token=worker_token,
            worker_instance_id="drain-instance",
            publication_id="drain-placeholder",
            lease_acquisition_id="restart-acq",
            transport_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            ),
            work_dir=work_dir,
            envelope=envelope,
            maximum_output_bytes=policy.max_output_bytes,
            maximum_grid_cells=policy.max_grid_cells,
        )
        summary = run_pending_delta_publications(
            config=config,
            worker_principal_id=worker.principal_id,
            limit=50,
            flavor="v2",
        )
        # The driver never learned an id out of band: discovery supplied both
        # takeable ids, the exhausted intent stayed hidden, and drain-a
        # completed at lease generation 2 with the fresh acquisition id.
        assert set(summary.discovered) == {"drain-a", "drain-b"}
        assert set(summary.published) == {"drain-a", "drain-b"}
        assert summary.failed == ()
        assert summary.skipped == ()
        published_generations = {
            event["publicationId"]: event["leaseGeneration"]
            for event in (_json.loads(line) for line in pub_journal_path.read_text().splitlines())
            if event.get("kind") == "delta-publication-published"
        }
        assert published_generations == {"drain-a": 2, "drain-b": 1}
        viewer = Principal(
            "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
        )
        for publication_id in ("drain-a", "drain-b"):
            view = store.get_current(publication_id, principal=viewer, now=now_box[0])
            assert view is not None and view.descriptor.dtype == "FLOAT64"
            content = store.read_bytes(
                publication_id,
                principal=viewer,
                offset=0,
                length=view.descriptor.output_size_bytes,
            )
            assert content is not None
            assert "sha256:" + hashlib.sha256(content).hexdigest() == view.descriptor.output_sha256
        recalculated = wiring.calculations.get_history(
            record.request_id, organization_id=fixture.organization_id
        )
        assert recalculated is not None and recalculated.report is not None
        assert recalculated.report.model_dump_json() == before_json
    finally:
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=10)
        if core_socket is not None:
            core_socket.close()
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
        if fixture is not None:
            fixture.close()


def test_synthetic_4x4_and_2x2_encoder_known_answers():
    """Actual emitted TIFF bytes match sealed numeric known answers.

    Proves the owned encoder (reused by the late-export primitive) on the two
    required synthetic grid sizes without any production state.
    """
    from ksi_change_detection.dsm_diff import DiffResult
    from ksi_event_contracts.external_relative_volume_calculation import (
        RelativeVolumeCoverageWitnessV2,
        RelativeVolumeMetricsV2,
        RelativeVolumeNumericResultV2,
    )
    from ksi_processing_controller.external_delta_raster import prepare_external_delta_raster_v2
    from rasterio.transform import from_origin

    def _case(rows, columns, values, valid_mask, metrics):
        diff = DiffResult(
            diff_m=np.array(values, dtype=np.float64).reshape(rows, columns),
            valid=np.array(valid_mask, dtype=bool).reshape(rows, columns),
            transform=from_origin(100, 200, 1, 1),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        )
        packed_common = base64.b64encode(
            np.packbits(np.array(valid_mask, dtype=bool), bitorder="big").tobytes()
        ).decode()
        zero = base64.b64encode(
            np.packbits(np.zeros(len(valid_mask), dtype=bool), bitorder="big").tobytes()
        ).decode()
        coverage = RelativeVolumeCoverageWitnessV2(
            rows=rows,
            columns=columns,
            row_offset=0,
            column_offset=0,
            selected_mask_b64=packed_common,
            common_valid_mask_b64=packed_common,
            unavailable_mask_b64=zero,
            threshold_excluded_mask_b64=zero,
            selected_cell_count=int(np.sum(valid_mask)),
            common_valid_cell_count=int(np.sum(valid_mask)),
            unavailable_cell_count=0,
            threshold_excluded_cell_count=0,
            cell_area_m2=1.0,
            selected_area_m2=float(np.sum(valid_mask)),
            common_valid_area_m2=float(np.sum(valid_mask)),
            bounds=(100.0, 200.0 - rows, 100.0 + columns, 200.0),
        ).sealed()
        numeric = RelativeVolumeNumericResultV2(
            calculation_identity_digest="sha256:" + "a" * 64,
            profile_digest="sha256:" + "b" * 64,
            metrics=RelativeVolumeMetricsV2(
                cut_m3=metrics[0],
                fill_m3=metrics[1],
                net_m3=metrics[1] - metrics[0],
                threshold_m=0.0,
            ),
            coverage=coverage,
        ).sealed()
        return diff, numeric

    diff4, numeric4 = _case(4, 4, [2.0, 0.0, -1.0, 0.5] * 4, [True] * 16, (4.0, 10.0))
    with prepare_external_delta_raster_v2(
        diff=diff4,
        numeric_result=numeric4,
        maximum_output_bytes=1_000_000,
        maximum_grid_cells=16,
        check_current=lambda: None,
    ) as out4:
        with rasterio.open(f"/proc/self/fd/{out4.fd}") as ds:
            assert ds.dtypes == ("float64",)
            assert (ds.height, ds.width) == (4, 4)
            np.testing.assert_allclose(ds.read(1)[0], [2.0, 0.0, -1.0, 0.5])
        sha4 = out4.sha256
    with prepare_external_delta_raster_v2(
        diff=diff4,
        numeric_result=numeric4,
        maximum_output_bytes=1_000_000,
        maximum_grid_cells=16,
        check_current=lambda: None,
    ) as out4b:
        assert out4b.sha256 == sha4  # deterministic replay

    diff2, numeric2 = _case(2, 2, [2.0, 0.0, -1.0, 0.0], [True, False, True, True], (1.0, 2.0))
    with prepare_external_delta_raster_v2(
        diff=diff2,
        numeric_result=numeric2,
        maximum_output_bytes=1_000_000,
        maximum_grid_cells=4,
        check_current=lambda: None,
    ) as out2:
        with rasterio.open(f"/proc/self/fd/{out2.fd}") as ds:
            assert (ds.height, ds.width) == (2, 2)
            assert np.isnan(ds.read(1)[0, 1])
        assert out2.sha256 != sha4
