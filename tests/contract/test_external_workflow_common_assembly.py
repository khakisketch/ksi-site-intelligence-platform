"""Real shared app assembly uses explicit authority factories in replay order."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import NoReturn, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.app_assembly import assemble_app
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorage
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_relative_volume_authorities import (
    DefaultClosedExternalRelativeVolumeAuthorityPort,
    ExternalRelativeVolumeAuthorityPort,
)
from ksi_core.external_relative_volume_s3_capabilities import (
    ExternalRelativeVolumeS3InputCapabilityIssuer,
)
from ksi_core.external_relative_volume_use_history import ClosedExternalRelativeVolumeUseHistory
from ksi_core.external_relative_volumes import ExternalRelativeVolumeQueuePolicy
from ksi_core.external_result_workflow_assembly import (
    ExternalRelativeVolumeInputCapabilityFactory,
    ExternalRelativeVolumeRuntimeAuthorities,
    ExternalResultWorkflowAssemblyConfig,
)
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_validation_policy import PolicyAuthorityRecord
from ksi_core.work_areas import WorkAreaStore
from test_api_contract_sync import _auth_registry, _NullEvidenceStorage


class _UnavailablePolicyAuthority:
    def __init__(self) -> None:
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> "_UnavailablePolicyAuthority":
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        if self._coordinator is None:
            raise RuntimeError("policy authority fixture was not bound")
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: object) -> PolicyAuthorityRecord | None:
        del authority_record_digest, now
        return None

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        del authority_record_digest, at
        return None

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        del authority, now
        return False


class _UnavailableEvidenceContextAuthority:
    def __init__(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def resolve_for_validation(self, **_kwargs: object) -> None:
        return None

    def resolve_historical_for_validation(self, **_kwargs: object) -> None:
        return None

    def is_current(self, context: object) -> bool:
        del context
        return False


def _assemble(
    path: Path,
    opened: list[DurableJournal],
    trace: list[str],
    *,
    config: ExternalResultWorkflowAssemblyConfig | None = None,
    storage: bool = True,
) -> FastAPI:
    def journal(name: str) -> DurableJournal:
        trace.append(name)
        item = DurableJournal(path / name)
        opened.append(item)
        return item

    return assemble_app(
        path,
        journal=journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=_auth_registry(),
        evidence_storage=_NullEvidenceStorage() if storage else None,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="fixture",
        external_result_workflow=config,
    )


def _config(
    trace: list[str], *, wrong_stage: str | None = None
) -> ExternalResultWorkflowAssemblyConfig:
    retained: dict[str, ExternalRelativeVolumeAuthorityPort] = {}

    def mapping(**context: object) -> ExternalRelativeVolumeAuthorityPort:
        trace.append("mapping")
        coordinator = cast(ExternalAuthorityCurrentnessCoordinator, context["coordinator"])
        assert cast(WorkAreaStore, context["work_areas"]).coordinator is coordinator
        assert callable(context["open_authority_journal"])
        if wrong_stage == "mapping":
            coordinator = ExternalAuthorityCurrentnessCoordinator()
        retained["mapping"] = DefaultClosedExternalRelativeVolumeAuthorityPort(
            currentness_coordinator=coordinator
        )
        return retained["mapping"]

    def runtime(**context: object) -> ExternalRelativeVolumeRuntimeAuthorities:
        trace.append("runtime")
        assert context["mapping"] is retained["mapping"]
        coordinator = cast(ExternalAuthorityCurrentnessCoordinator, context["coordinator"])
        decisions = cast(ExternalUseDecisionStore, context["decisions"])
        assert decisions.coordinator is coordinator
        if wrong_stage == "runtime":
            coordinator = ExternalAuthorityCurrentnessCoordinator()
        return ExternalRelativeVolumeRuntimeAuthorities(
            execution=DefaultClosedExternalRelativeVolumeAuthorityPort(
                currentness_coordinator=coordinator
            ),
            historical_use=ClosedExternalRelativeVolumeUseHistory(),
        )

    def issuer(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("explicit denial fixture cannot issue byte capabilities")

    return ExternalResultWorkflowAssemblyConfig(
        build_mapping=mapping,
        build_runtime=runtime,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=5),
            deadline_after_issue=timedelta(seconds=30),
            max_attempts=1,
            max_active_requests_per_organization=2,
        ),
        input_capability_issuer=issuer,
    )


def test_common_assembly_constructs_and_protects_complete_graph_in_order(tmp_path: Path) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        app = _assemble(tmp_path, opened, trace, config=_config(trace))
        stages = [
            "mapping",
            "external-use-decisions.jsonl",
            "runtime",
            "external-relative-volumes.jsonl",
            "external-result-reviews.jsonl",
            "external-reobservation-proposals.jsonl",
            "observation-work-orders.jsonl",
        ]
        assert [trace.index(stage) for stage in stages] == sorted(
            trace.index(stage) for stage in stages
        )
        service = app.state.external_result_workflow_service
        assert service.work_orders is app.state.observation_work_order_store
        assert (
            app.state.organization_work_roster_store.coordinator
            is app.state.external_authority_currentness
        )
        assert app.state.work_inbox_store.uses_exact_dependencies(
            work_orders=app.state.observation_work_order_store,
            roster=app.state.organization_work_roster_store,
            report_resolver=app.state.external_relative_volume_store,
        )
        assert app.state.external_relative_volume_mapping_authority is not None
        projector = app.state.external_result_read_projector
        assert projector is not None
        with TestClient(app) as client:
            assert client.get("/v1/external-relative-volume-reports/missing").status_code == 401
            assert (
                client.get(
                    "/v1/external-relative-volume-reports/missing",
                    headers={"Authorization": "Bearer contract-sync-test-token"},
                ).status_code
                == 404
            )
    finally:
        for item in opened:
            item.close()


def test_byte_issuer_factory_receives_final_stores(tmp_path: Path) -> None:
    """A shadow reconstruction store would not see the app's sealed DSM records."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    retained: list[ExternalRelativeVolumeS3InputCapabilityIssuer] = []

    def build_issuer(
        *, reconstruction: ExternalReconstructionStore, storage: EvidenceStorage
    ) -> ExternalRelativeVolumeS3InputCapabilityIssuer:
        issuer = ExternalRelativeVolumeS3InputCapabilityIssuer(
            reconstruction=reconstruction, storage=storage
        )
        retained.append(issuer)
        return issuer

    config = replace(
        _config(trace), input_capability_issuer=None, build_input_capability_issuer=build_issuer
    )
    try:
        app = _assemble(tmp_path, opened, trace, config=config)
        assert len(retained) == 1
        assert retained[0]._reconstruction is app.state.external_reconstruction_store
        assert retained[0]._storage is app.state.evidence_storage
        assert app.state.external_relative_volume_store is not None
    finally:
        for item in opened:
            item.close()


@pytest.mark.parametrize("mode", ["missing", "both", "not_callable"])
def test_byte_issuer_configuration_requires_one_explicit_source(mode: str) -> None:
    config = _config([])
    with pytest.raises(ValueError, match="issuer"):
        if mode == "missing":
            replace(config, input_capability_issuer=None)
        elif mode == "both":
            issuer = config.input_capability_issuer
            assert issuer is not None
            replace(
                config,
                build_input_capability_issuer=lambda **_kwargs: issuer,
            )
        else:
            # Deliberately malformed runtime input exercises the constructor guard.
            replace(
                config, input_capability_issuer=None,
                build_input_capability_issuer=cast(
                    ExternalRelativeVolumeInputCapabilityFactory, 42
                ),
            )


@pytest.mark.parametrize("failure", ["none", "raises"])
def test_byte_issuer_factory_failure_prevents_workflow_replay(tmp_path: Path, failure: str) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []

    def failed_factory(**_kwargs: object) -> None:
        if failure == "raises":
            raise ValueError("issuer unavailable")
        return None

    config = replace(
        _config(trace), input_capability_issuer=None,
        # The invalid return value is intentional: assembly must reject it before replay.
        build_input_capability_issuer=cast(
            ExternalRelativeVolumeInputCapabilityFactory, failed_factory
        ),
    )
    try:
        with pytest.raises(ValueError, match="issuer"):
            _assemble(tmp_path, opened, trace, config=config)
        assert "external-relative-volumes.jsonl" not in trace
    finally:
        for item in opened:
            item.close()


@pytest.mark.parametrize("stage", ["mapping", "runtime"])
def test_common_assembly_rejects_wrong_coordinator_before_volume_replay(
    tmp_path: Path, stage: str
) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        with pytest.raises(ValueError, match="coordinator"):
            _assemble(tmp_path, opened, trace, config=_config(trace, wrong_stage=stage))
        assert "external-relative-volumes.jsonl" not in trace
        if stage == "mapping":
            assert "runtime" not in trace
    finally:
        for item in opened:
            item.close()


def test_configured_workflow_requires_complete_external_storage_graph(tmp_path: Path) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        with pytest.raises(ValueError, match="external result workflow"):
            _assemble(tmp_path, opened, trace, config=_config(trace), storage=False)
        assert "mapping" not in trace
    finally:
        for item in opened:
            item.close()


def test_manual_workflow_without_upstream_authorities_remains_closed(tmp_path: Path) -> None:
    """Manual/dev configs do not acquire an authority merely by enabling routes."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        app = _assemble(tmp_path, opened, trace, config=_config(trace))
        assert app.state.external_relative_volume_mapping_authority is not None
        assert type(app.state.external_validation_policy_registry._authority_port).__name__ == (
            "_NoPolicyAuthorityPort"
        )
        assert type(app.state.external_evidence_validation_store._context_authority).__name__ == (
            "_NoContextAuthority"
        )
    finally:
        for item in opened:
            item.close()


def test_storage_only_assembly_exposes_no_mapping_authority(tmp_path: Path) -> None:
    """No result-workflow config means no mapping participant exists to administer."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        app = _assemble(tmp_path, opened, trace, config=None)
        assert app.state.external_relative_volume_mapping_authority is None
    finally:
        for item in opened:
            item.close()


def test_context_authority_factory_must_bind_the_exact_assembly_coordinator(tmp_path: Path) -> None:
    """A context authority for another graph must be rejected before any journal opens."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    policy_authority = _UnavailablePolicyAuthority()
    config = replace(
        _config(trace),
        policy_authority_port=policy_authority,
        build_policy_authority_currentness=policy_authority.bind,
        build_evidence_context_authority=lambda _coordinator: _UnavailableEvidenceContextAuthority(
            ExternalAuthorityCurrentnessCoordinator()
        ),
    )
    try:
        with pytest.raises(ValueError, match="context authority must share"):
            _assemble(tmp_path, opened, trace, config=config)
        assert trace == []
    finally:
        for item in opened:
            item.close()


def test_common_assembly_forwards_exact_upstream_authority_ports(tmp_path: Path) -> None:
    """Configured workflow ports reach only their existing Core authority consumers."""
    opened: list[DurableJournal] = []
    trace: list[str] = []
    policy_authority = _UnavailablePolicyAuthority()
    retained: dict[str, _UnavailableEvidenceContextAuthority] = {}

    def build_context_authority(
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> _UnavailableEvidenceContextAuthority:
        authority = _UnavailableEvidenceContextAuthority(coordinator)
        retained["context"] = authority
        return authority

    config = replace(
        _config(trace),
        policy_authority_port=policy_authority,
        build_policy_authority_currentness=policy_authority.bind,
        build_evidence_context_authority=build_context_authority,
    )
    try:
        app = _assemble(tmp_path, opened, trace, config=config)
        assert app.state.external_validation_policy_registry._authority_port is policy_authority
        assert (
            app.state.external_evidence_validation_store._context_authority is retained["context"]
        )
    finally:
        for item in opened:
            item.close()


def test_loader_configured_authority_journal_is_owned_by_common_assembly(tmp_path: Path) -> None:
    """The absolute authority journal is tracked, closed, and never opened by the loader."""
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config
    from test_external_result_workflow_config import _approved_files

    config_path, participants = _approved_files(tmp_path)
    workflow = load_external_result_workflow_config(
        config_path,
        participants=participants,
        input_capability_issuer=lambda *_args, **_kwargs: None,
    )
    opened: list[DurableJournal] = []
    trace: list[str] = []
    app = _assemble(tmp_path, opened, trace, config=workflow)
    authority_path = tmp_path / "authority.jsonl"
    try:
        assert str(authority_path) in trace
        assert any(item._path == authority_path for item in opened)
        assert app.state.external_relative_volume_store is not None
    finally:
        for item in opened:
            item.close()

    reopened = DurableJournal(authority_path)
    reopened.close()


def test_absent_config_leaves_workflow_journals_and_routes_absent(tmp_path: Path) -> None:
    opened: list[DurableJournal] = []
    trace: list[str] = []
    try:
        app = _assemble(tmp_path, opened, trace)
        assert "external-relative-volumes.jsonl" not in trace
        assert "external-result-reviews.jsonl" not in trace
        assert "/v1/external-relative-volume-reports/{report_ref}" not in app.openapi()["paths"]
        assert "/v1/copilot/query" not in app.openapi()["paths"]
        assert not hasattr(app.state, "copilot_service")
    finally:
        for item in opened:
            item.close()
