"""Real AP/NX journals and actual DSM measurement back delta source resolution.

Local synthetic fixtures, not deployment or signed output-worker authorization.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_core.domains.external.quantity.external_delta_source_adapters import (
    CoreDeltaEgressAdapter,
    CoreV2DeltaSourceAdapter,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_analysis_delta_measurement import (
    measure_external_relative_volume_with_delta_v2,
)


def _adapter(fixture: Any) -> CoreV2DeltaSourceAdapter:
    wiring = fixture.app.state.external_analysis_wiring
    return CoreV2DeltaSourceAdapter(
        intents=wiring.intents,
        assessments=wiring.assessments,
        calculations=wiring.calculations,
        coordinator=wiring.assessments.coordinator,
    )


def test_v2_source_resolves_actual_measured_report_and_revokes_on_source_authority_change(
    tmp_path: Path,
) -> None:
    (tmp_path / "core").mkdir(mode=0o700)
    fixture = build_local_analysis_api_fixture(tmp_path / "core")
    try:
        client = TestClient(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "delta-real-source"},
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
            json={
                "workerInstanceId": "delta-source-worker",
                "leaseAcquisitionId": "delta-source-lease",
            },
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
            source = tmp_path / (capability["role"] + ".tif")
            source.write_bytes(fixture.storage.object_bytes(key))
            paths.append(source)
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
            report_id="delta-real-source-report",
            computed_at=now,
            reported_at=now,
            maximum_delta_output_bytes=1_000_000,
            check_current=lambda: None,
        ) as measured:
            assert isinstance(measured.report, RelativeVolumeCalculationReportV2)
            assert measured.delta is not None
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
            args = {
                "organization_id": fixture.organization_id,
                "site_id": fixture.site_id,
                "work_area_id": fixture.work_area_id,
                "source_calculation_identity_digest": identity.canonical_digest(),
                "source_numeric_result_identity_digest": (
                    measured.delta.numeric_result_identity_digest
                ),
                "source_coverage_witness_digest": measured.delta.coverage_witness_digest,
                "now": now,
            }
            source = _adapter(fixture)
            witness = source.resolve_current_source(**args)
            assert witness is not None
            assert (
                witness.source_contract_version == "external-relative-volume-calculation-report.v2"
            )
            assert (witness.grid_rows, witness.grid_columns) == (
                measured.delta.rows,
                measured.delta.columns,
            )
            assert witness.transform == measured.delta.transform
            publication = _prove_guarded_publication(
                tmp_path,
                fixture,
                source,
                witness,
                measured,
                attempt,
                now,
            )
            for field in (
                "organization_id",
                "site_id",
                "work_area_id",
                "source_numeric_result_identity_digest",
                "source_coverage_witness_digest",
            ):
                wrong = "sha256:" + "0" * 64 if field.endswith("digest") else "foreign"
                assert source.resolve_current_source(**{**args, field: wrong}) is None
            for context in fixture._retained_contexts:
                assert context.context_digest is not None
                fixture.revoke_evidence_context(context.context_digest)
            assert source.resolve_current_source(**args) is None
            assert (
                publication.read_bytes(
                    "actual-v2-delta",
                    principal=Principal(
                        "human",
                        PrincipalKind.OPERATOR,
                        Role.VIEWER,
                        None,
                        fixture.organization_id,
                    ),
                    offset=0,
                    length=100,
                )
                is None
            )
    finally:
        fixture.close()


def _prove_guarded_publication(
    tmp_path: Path,
    fixture: Any,
    source: Any,
    witness: Any,
    measured: Any,
    attempt: Any,
    now: datetime,
) -> Any:
    """Generated DSMs -> Core numeric acceptance -> observed actual TIFF -> guarded bytes.

    The new signing key is temporary synthetic authority, NOT release issuance.
    """
    from dataclasses import asdict

    import rasterio
    from ksi_core.domains.external.quantity.external_delta_output_observations import (
        CoreDeltaOutputObservationStore,
    )
    from ksi_core.domains.external.quantity.external_delta_publications import (
        DeltaOutputObservation,
        DeltaPublicationPolicy,
        ExternalDeltaPublicationStore,
        FilesystemDeltaByteStore,
    )
    from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
        QuantitativeExtensionDeltaPublicationAuthority,
    )
    from test_external_quantitative_extension_activation import _unsigned, _write_files

    policy = DeltaPublicationPolicy(
        policy_id="generated-delta-publication",
        version=1,
        max_output_bytes=1_000_000,
        max_grid_cells=1000,
        max_lifetime_seconds=600,
        max_active_publications=4,
        upload_lease_duration_seconds=60,
        max_upload_attempts=8,
    )
    worker = Principal(
        "analysis-local-worker", PrincipalKind.ANALYSIS_WORKER, None, None, fixture.organization_id
    )
    coor = source.coordinator
    runtime = "sha256:" + hashlib.sha256(b"synthetic-extension-runtime-not-release").hexdigest()
    envelope = attempt.authorization.resource_envelope_digest
    activation, keys, _, _ = _write_files(
        tmp_path / "extension-authority",
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
        coordinator=coor,
    )
    observation_journal = DurableJournal(tmp_path / "delta-output-observations.jsonl")
    publication_journal = DurableJournal(tmp_path / "delta-publications.jsonl")
    fixture.opened.extend([observation_journal, publication_journal])
    observations = CoreDeltaOutputObservationStore(
        observation_journal, coordinator=coor, clock=lambda: now
    )
    store = ExternalDeltaPublicationStore(
        publication_journal,
        source_witness=source,
        authority=authority,
        egress=CoreDeltaEgressAdapter(sites=fixture.app.state.site_store),
        byte_store=FilesystemDeltaByteStore(tmp_path / "delta-output-bytes"),
        observations=observations,
        policy=policy,
        clock=lambda: now,
        coordinator=coor,
    )
    store.create_intent(
        principal=Principal(
            "operator", PrincipalKind.OPERATOR, Role.ADMIN, None, fixture.organization_id
        ),
        publication_id="actual-v2-delta",
        **{
            key: value
            for key, value in asdict(witness).items()
            if key
            not in {
                "organization_id",
                "source_contract_version",
            }
        },
        lifetime_seconds=300,
        now=now,
    )
    lease = store.acquire_upload_lease(
        worker_principal=worker,
        publication_id="actual-v2-delta",
        worker_instance_id="output-instance-1",
        lease_acquisition_id="output-acquisition-1",
        now=now,
    )
    assert lease is not None
    # The authenticated output result is measured in the worker boundary, not
    # inferred by Core from the byte upload's hash or an HTTP caller's dtype.
    with rasterio.open(f"/proc/self/fd/{measured.delta.fd}") as dataset:
        assert dataset.dtypes == ("float64",)
        assert dataset.tags()["DELTA_RULE"] == "CURRENT_MINUS_BASELINE"
        observation = DeltaOutputObservation(
            **asdict(witness),
            publication_id=lease.publication_id,
            worker_principal_id=worker.principal_id,
            worker_instance_id="output-instance-1",
            lease_generation=lease.lease_generation,
            output_sha256=measured.delta.sha256,
            output_size_bytes=measured.delta.size_bytes,
            dtype="FLOAT64",
            delta_sign="CURRENT_MINUS_BASELINE",
            nodata_value="NAN",
        ).sealed()
        assert (dataset.height, dataset.width) == (observation.grid_rows, observation.grid_columns)
        assert tuple(dataset.transform)[:6] == observation.transform
    with os.fdopen(os.dup(measured.delta.fd), "rb") as stream:
        assert (
            store.publish_output(
                worker_principal=worker,
                publication_id=lease.publication_id,
                worker_instance_id="output-instance-1",
                lease_generation=lease.lease_generation,
                byte_stream=stream,
            )
            is None
        )  # Even the legitimate lease cannot skip observed-result acceptance.
    assert (
        observations.record_worker_result(
            publication_store=store,
            worker_principal=worker,
            observation=observation,
        )
        == observation
    )
    with os.fdopen(os.dup(measured.delta.fd), "rb") as stream:
        stream.seek(0)
        published = store.publish_output(
            worker_principal=worker,
            publication_id=lease.publication_id,
            worker_instance_id="output-instance-1",
            lease_generation=lease.lease_generation,
            byte_stream=stream,
        )
    assert published is not None
    assert published.descriptor.source_contract_version == witness.source_contract_version
    assert published.descriptor.output_sha256 == measured.delta.sha256
    view = Principal("human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id)
    content = store.read_bytes(
        lease.publication_id, principal=view, offset=0, length=measured.delta.size_bytes
    )
    assert content is not None
    assert "sha256:" + hashlib.sha256(content).hexdigest() == measured.delta.sha256
    # The receipt journal replays independently without promoting a caller hash
    # into a native format or current permission claim.
    observation_journal.close()
    replay_journal = DurableJournal(tmp_path / "delta-output-observations.jsonl")
    fixture.opened.append(replay_journal)
    replay = CoreDeltaOutputObservationStore(replay_journal, coordinator=coor, clock=lambda: now)
    assert (
        replay.resolve_output_observation(
            organization_id=fixture.organization_id,
            publication_id=lease.publication_id,
            worker_principal_id=worker.principal_id,
            worker_instance_id="output-instance-1",
            lease_generation=lease.lease_generation,
            now=now,
        )
        == observation
    )
    return store


def test_source_adapter_rejects_unrelated_coordinator_and_non_core_participants(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        wiring = fixture.app.state.external_analysis_wiring
        with pytest.raises(ValueError, match="exact common"):
            CoreV2DeltaSourceAdapter(
                intents=wiring.intents,
                assessments=wiring.assessments,
                calculations=wiring.calculations,
                coordinator=ExternalAuthorityCurrentnessCoordinator(),
            )
    finally:
        fixture.close()


@pytest.mark.parametrize("consent", [False, True])
def test_egress_uses_real_site_consent_and_scope_without_restricting_human_reads(
    tmp_path: Path, consent: bool
) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=consent)
    try:
        adapter = CoreDeltaEgressAdapter(sites=fixture.app.state.site_store)
        operator = Principal(
            "human", PrincipalKind.OPERATOR, Role.VIEWER, None, fixture.organization_id
        )
        args: dict[str, Any] = {
            "organization_id": fixture.organization_id,
            "site_id": fixture.site_id,
            "work_area_id": fixture.work_area_id,
            "now": datetime.now(UTC),
        }
        assert adapter.is_egress_allowed(**args, principal=operator)
        mcp = Principal(
            "mcp",
            PrincipalKind.ANALYSIS_MCP_CLIENT,
            None,
            None,
            fixture.organization_id,
            allowed_site_ids=frozenset({fixture.site_id}),
            allowed_work_area_ids=frozenset({fixture.work_area_id}),
        )
        assert adapter.is_egress_allowed(**args, principal=mcp) is consent
        assert not adapter.is_egress_allowed(
            **args, principal=replace(operator, organization_id="other")
        )
        assert not adapter.is_egress_allowed(
            **args, principal=replace(operator, allowed_work_area_ids=frozenset({"other"}))
        )
    finally:
        fixture.close()
