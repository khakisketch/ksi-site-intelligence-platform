"""Purpose-signed optional common composition; no default mount or V2 fallback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from analysis_api_local_fixture import (
    _digest,
    _LocalObjectStorage,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _workflow,
)
from ksi_core.composition.platform_assembly import assemble_platform_app
from ksi_core.composition.quantitative_extension_graph import DeltaPublicationLocalConfig
from ksi_core.domains.external.quantity.analysis_activation_authority import _runtime_digest
from ksi_core.domains.external.quantity.external_delta_publications import DeltaPublicationPolicy
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import AuthRegistry, Principal, PrincipalKind
from test_external_analysis_http_integration import _local_graph_config
from test_external_quantitative_extension_activation import _unsigned, _write_files


def _assemble(root, *, enabled, invalid_signature=False, with_masked=False):
    root.mkdir(mode=0o700, parents=True)
    now = datetime(2026, 10, 26, 12, tzinfo=UTC)
    workflow, _, envelope, _ = _workflow(
        root,
        now=now,
        policy_authority=_RetainedPolicyAuthority(),
        context_authority=_RetainedEvidenceContextAuthority(now),
    )
    policy = DeltaPublicationPolicy(
        policy_id="optional-delta-test",
        version=1,
        max_output_bytes=1_000_000,
        max_grid_cells=1_000_000,
        max_lifetime_seconds=600,
        max_active_publications=4,
        upload_lease_duration_seconds=60,
        max_upload_attempts=envelope.max_retry_attempts,
    )
    runtime = AnalysisRuntimeIdentityV2(
        worker_executable_digest=_digest("delta-reproduction-executable"),
        worker_build_digest=_digest("delta-reproduction-build"),
        runtime_image_version="synthetic-delta-1",
        runtime_image_oci_digest=_digest("delta-reproduction-image"),
        dependency_lock_digest=_digest("delta-reproduction-lock"),
    )
    worker = Principal("delta-worker", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")
    activation, keys, _, _ = _write_files(
        root / "extension-authority",
        unsigned=_unsigned(
            purpose="DELTA_PUBLICATION_V1",
            policy_digest=policy.canonical_digest(),
            runtime_digest=_runtime_digest(runtime),
            envelope_digest=envelope.canonical_digest(),
            worker_principal_id=worker.principal_id,
            issued_at=now - timedelta(seconds=1),
            valid_until=now + timedelta(hours=1),
        ),
    )
    config = DeltaPublicationLocalConfig(
        policy,
        runtime,
        envelope,
        worker,
        activation,
        keys,
        root / "private-delta-bytes",
        lambda: now,
    )
    if invalid_signature:
        config = replace(
            config, runtime=replace(runtime, worker_build_digest=_digest("wrong-build"))
        )
    masked_config = _masked_config(root, envelope, worker, now) if with_masked else None
    if with_masked:
        config = replace(config, mask_core_origin="http://127.0.0.1:8047")
    opened = []

    def journal(name):
        item = DurableJournal(root / name)
        opened.append(item)
        return item

    try:
        app = assemble_platform_app(
            root,
            journal=journal,
            opened=opened,
            auth_registry=AuthRegistry([]),
            evidence_storage=_LocalObjectStorage(),
            external_result_workflow=workflow,
            external_analysis_local_graph=_local_graph_config(envelope),
            delta_publications=config if enabled else None,
            masked_quantitative=masked_config,
        )
        return app, opened, config
    except BaseException:
        for item in reversed(opened):
            item.close()
        raise


def _masked_config(root, envelope, worker, now):
    from ksi_core.composition.masked_quantitative_graph import MaskedQuantitativeLocalConfig
    from ksi_core.domains.external.quantity.external_masked_calculation_core_adapters import (
        masked_execution_runtime_digest,
    )
    from test_external_masked_http_integration import (
        _execution_runtime,
        _mask_inspection_profile,
        _masked_profile,
    )

    masked_profile = _masked_profile()
    mask_profile = _mask_inspection_profile(envelope)
    masked_runtime = _execution_runtime()
    activation, keys, _, _ = _write_files(
        root / "masked-authority",
        unsigned=_unsigned(
            purpose="MASKED_ANALYSIS_V3",
            policy_digest=masked_profile.canonical_digest(),
            runtime_digest=masked_execution_runtime_digest(
                masked_runtime,
                masked_profile.canonical_digest(),
                envelope.canonical_digest(),
                mask_profile.canonical_digest(),
            ),
            envelope_digest=envelope.canonical_digest(),
            worker_principal_id=worker.principal_id,
            issued_at=now - timedelta(seconds=1),
            valid_until=now + timedelta(hours=1),
        ),
    )
    return MaskedQuantitativeLocalConfig(
        masked_profile,
        mask_profile,
        masked_runtime,
        envelope,
        worker,
        activation,
        keys,
        root / "private-mask-bytes",
        lambda: now,
    )


def test_new_routes_are_absent_without_explicit_delta_graph_even_when_keys_exist(tmp_path):
    app, opened, config = _assemble(tmp_path / "default", enabled=False)
    try:
        assert not any("delta-publication" in path for path in app.openapi()["paths"])
        assert not config.byte_root.exists()
        assert not hasattr(app.state, "external_delta_wiring")
        assert not hasattr(app.state, "external_masked_wiring")
        assert not any(
            "mask-children" in path or "masked-calculations" in path
            for path in app.openapi()["paths"]
        )
    finally:
        for item in reversed(opened):
            item.close()


def test_explicit_new_purpose_signature_mounts_only_exact_common_participants(tmp_path):
    from fastapi.testclient import TestClient

    app, opened, config = _assemble(tmp_path / "enabled", enabled=True)
    try:
        with TestClient(app):
            wiring = app.state.external_delta_wiring
            assert wiring.analysis is app.state.external_analysis_wiring
            assert wiring.source._calculations is app.state.external_analysis_wiring.calculations
            assert wiring.source._assessments.coordinator is wiring.store.coordinator
            paths = app.openapi()["paths"]
            assert "/v1/sites/{site_id}/work-areas/{work_area_id}/delta-publications" in paths
            assert "/v1/internal/delta-publication-uploads/{publication_id}/observation" in paths
            assert config.byte_root.stat().st_mode & 0o777 == 0o700
        with pytest.raises((ValueError, OSError)):
            wiring.bytes.open_read(output_id="already-closed")
    finally:
        for item in reversed(opened):
            item.close()


def test_wrong_runtime_pin_cannot_mount_by_reusing_old_analysis_configuration(tmp_path):
    with pytest.raises(ValueError, match="purpose-bound"):
        _assemble(tmp_path / "wrong-runtime", enabled=True, invalid_signature=True)


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8047/not-an-origin",
        "http://example.invalid:8047",
        "http://192.0.2.1:8047",
        "https://user:secret@127.0.0.1:8047",
        "http://127.0.0.1:8047?alternate=1",
        "file:///tmp/mask",
    ],
)
def test_mask_byte_origin_is_explicit_and_cannot_contain_paths_credentials_or_remote_plaintext(
    tmp_path, origin
):
    app, opened, config = _assemble(tmp_path / "origin-validation", enabled=False)
    try:
        with pytest.raises(ValueError, match="pinned Core origin"):
            replace(config, mask_core_origin=origin)
    finally:
        for handle in reversed(opened):
            handle.close()


def test_failed_optional_boot_closes_only_its_new_journal_handles(tmp_path, monkeypatch):
    import ksi_core.composition.quantitative_extension_graph as graph

    app, opened, config = _assemble(tmp_path / "existing", enabled=True)
    failed_root = tmp_path / "failed"
    failed_root.mkdir(mode=0o700)
    new_handles = []

    def journal(name):
        handle = DurableJournal(failed_root / name)
        new_handles.append(handle)
        return handle

    def reject_store(*args, **kwargs):
        raise ValueError("synthetic construction rejection")

    monkeypatch.setattr(graph, "ExternalDeltaPublicationStore", reject_store)
    try:
        with pytest.raises(ValueError, match="construction rejection"):
            graph.build_delta_publication_wiring(
                journal=journal,
                config=replace(config, byte_root=failed_root / "bytes"),
                analysis=app.state.external_analysis_wiring,
                sites=app.state.site_store,
                coordinator=app.state.external_delta_wiring.store.coordinator,
            )
        assert len(new_handles) == 2
        for handle in new_handles:
            with pytest.raises(JournalSealedError):
                handle.append({"shouldNeverBeWritten": True})
        # Previously mounted participants were not closed by the failed build.
        assert (
            app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a",
            )
            == ()
        )
    finally:
        app.state.external_delta_wiring.close()
        for handle in reversed(opened):
            handle.close()


def test_both_optional_lanes_use_exact_common_sources_but_separate_signed_purposes(tmp_path):
    from fastapi.testclient import TestClient
    from ksi_core.domains.external.quantity.external_masked_delta_source_adapter import (
        CoreVersionedDeltaSourceAdapter,
    )

    app, opened, _ = _assemble(tmp_path / "both", enabled=True, with_masked=True)
    try:
        with TestClient(app):
            masked, delta = app.state.external_masked_wiring, app.state.external_delta_wiring
            assert masked.assessments is delta.analysis.assessments
            assert masked.coordinator is delta.store.coordinator
            assert isinstance(delta.store._source, CoreVersionedDeltaSourceAdapter)
            assert delta.store._source.v3.calculations is masked.calculations
            assert delta.store._source.v2 is delta.source
            paths = app.openapi()["paths"]
            assert "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children" in paths
            assert "/v3/sites/{site_id}/work-areas/{work_area_id}/masked-calculations" in paths
            assert "/v1/internal/mask-children/{mask_child_id}:report" in paths
            assert delta.config.activation_path != masked.config.activation_path
    finally:
        for handle in reversed(opened):
            handle.close()


def test_later_delta_boot_failure_closes_already_built_mask_byte_descriptors(tmp_path, monkeypatch):
    import ksi_core.composition.platform_graph as graph

    captured = []
    build_masked = graph.build_masked_quantitative_wiring

    def capture_masked(**kwargs):
        wiring = build_masked(**kwargs)
        captured.append(wiring)
        return wiring

    def fail_delta(**kwargs):
        raise ValueError("synthetic later delta boot failure")

    monkeypatch.setattr(graph, "build_masked_quantitative_wiring", capture_masked)
    monkeypatch.setattr(graph, "build_delta_publication_wiring", fail_delta)
    with pytest.raises(ValueError, match="later delta boot failure"):
        _assemble(tmp_path / "later-boot-failure", enabled=True, with_masked=True)
    assert len(captured) == 1
    assert captured[0].byte_store._root_fd == -1
    assert captured[0].byte_store._closed


def test_seeded_dsm_fixture_does_not_end_the_optional_lane_lifespan_before_serving(tmp_path):
    from analysis_api_local_fixture import _envelope, build_local_analysis_api_fixture
    from fastapi.testclient import TestClient

    worker = Principal("analysis-local-worker", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")
    config = _masked_config(tmp_path, _envelope(), worker, datetime.now(UTC))
    (tmp_path / "core").mkdir(mode=0o700)
    fixture = build_local_analysis_api_fixture(
        tmp_path / "core",
        v2_dsm_only=True,
        organization_id="org-a",
        masked_quantitative=config,
    )
    try:
        byte_store = fixture.app.state.external_masked_wiring.byte_store
        assert not byte_store._closed
        assert byte_store._root_fd >= 0
        with TestClient(fixture.app) as client:
            assert client.get("/ready").json() == {"ready": True}
            assert not byte_store._closed
        assert byte_store._closed
        assert byte_store._root_fd == -1
    finally:
        fixture.close()
