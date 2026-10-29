"""Real ingress projection faults must fence retained downstream snapshots."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
import test_external_evidence_validations as validation_fixture
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence import (
    EvidenceItem,
    ExternalEvidenceDeclarationIntent,
    ExternalEvidenceRecoveryError,
    ExternalEvidenceStore,
)
from ksi_core.external_evidence_validations import (
    EvidenceValidationVerdict,
    ExternalEvidenceValidationInputBinding,
    ExternalEvidenceValidationStore,
    SealedEvidenceValidationPort,
)
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_evidence import ExternalEvidenceValidationRequestV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from test_external_evidence_api import _NOW, _direct_evidence_context, _intent


@pytest.mark.parametrize("default_coordinator", [False, True])
def test_inflight_validation_issuance_rechecks_actual_ingress_projection_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, default_coordinator: bool
) -> None:
    evidence, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    declared = evidence._items[ref]
    storage.objects[declared.object_key] = ObjectStorageObservation(
        declared.object_key,
        True,
        5,
        declared.declaration.declared_content_digest,
        declared.declaration.declared_content_type,
    )
    evidence.seal(
        ref, revision=revision, principal=principal, key="initial-seal", storage=storage, now=_NOW
    )
    item = evidence.resolve_for_validation(ref)
    assert item is not None and item.manifest is not None
    monkeypatch.setattr(validation_fixture, "_subject", lambda: item.manifest.subject)
    coordinator = evidence.coordinator
    registry, policy = validation_fixture._policy_registry(tmp_path, coordinator=coordinator)
    entered, release = Event(), Event()

    class PausedContext(validation_fixture._ContextAuthority):
        def resolve_for_validation(
            self,
            *,
            subject: SealedExternalSubjectV1,
            evidence_manifest_digest: str,
            target_dsm_artifact_id: str,
            target_dsm_observed_sha256: str,
            policy_digest: str,
            now: datetime,
        ) -> ExternalEvidenceMeasurementContextV1 | None:
            entered.set()
            assert release.wait(3)
            return super().resolve_for_validation(
                subject=subject,
                evidence_manifest_digest=evidence_manifest_digest,
                target_dsm_artifact_id=target_dsm_artifact_id,
                target_dsm_observed_sha256=target_dsm_observed_sha256,
                policy_digest=policy_digest,
                now=now,
            )

    context = PausedContext(validation_fixture._context(item, policy), coordinator=coordinator)
    validations = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=evidence,
        policy_registry=registry,
        context_authority=context,
        clock=lambda: validation_fixture.NOW,
        coordinator=None if default_coordinator else coordinator,
    )
    before = list(validations._journal.replay())
    original_apply = evidence._apply

    def fault(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-declared":
            raise RuntimeError("live projection fault")
        original_apply(raw)

    evidence._apply = fault
    with ThreadPoolExecutor(max_workers=1) as executor:
        issuing = executor.submit(validations.issue_after_seal, ref, now=validation_fixture.NOW)
        try:
            assert entered.wait(3)
            with pytest.raises(RuntimeError, match="live projection fault"):
                evidence.declare(
                    ExternalEvidenceDeclarationIntent.model_validate(_intent(b"new")),
                    revision=revision,
                    principal=principal,
                    key="poison",
                    now=_NOW,
                )
            release.set()
            with pytest.raises(ExternalEvidenceRecoveryError):
                issuing.result(timeout=3)
        finally:
            release.set()
    assert list(validations._journal.replay()) == before
    with pytest.raises(ExternalEvidenceRecoveryError):
        validations.analysis_validation_lifecycles_are_locally_current(
            (), now=validation_fixture.NOW
        )
    with pytest.raises(ExternalEvidenceRecoveryError):
        validations.analysis_fact_currentness((), now=validation_fixture.NOW)
    validations._journal.close()
    evidence._journal.close()
    replayed = ExternalEvidenceStore(
        DurableJournal(tmp_path / "external-evidence.jsonl"), coordinator=coordinator
    )
    recovered = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=replayed,
        policy_registry=registry,
        context_authority=context,
        clock=lambda: validation_fixture.NOW,
        coordinator=coordinator,
    )
    assert recovered.issue_after_seal(ref, now=validation_fixture.NOW).verdict is (
        EvidenceValidationVerdict.ISSUED
    )
    assert recovered.issue_after_seal(ref, now=validation_fixture.NOW).verdict is (
        EvidenceValidationVerdict.IDEMPOTENT
    )
    recovered._journal.close()
    replayed._journal.close()


def test_inflight_capability_is_not_returned_after_actual_ingress_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from ksi_core.leasing import LeaseFence

    evidence, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    declared = evidence._items[ref]
    storage.objects[declared.object_key] = ObjectStorageObservation(
        declared.object_key,
        True,
        5,
        declared.declaration.declared_content_digest,
        declared.declaration.declared_content_type,
    )
    evidence.seal(
        ref, revision=revision, principal=principal, key="initial-seal", storage=storage, now=_NOW
    )
    item = evidence.resolve_for_validation(ref)
    assert item is not None and item.manifest is not None
    monkeypatch.setattr(validation_fixture, "_subject", lambda: item.manifest.subject)
    coordinator = evidence.coordinator
    registry, policy = validation_fixture._policy_registry(tmp_path, coordinator=coordinator)
    context = validation_fixture._ContextAuthority(
        validation_fixture._context(item, policy), coordinator=coordinator
    )
    entered, release = Event(), Event()

    class PausedCapability(validation_fixture._InputCapabilities):
        def issue_input(
            self,
            *,
            item: EvidenceItem,
            request: ExternalEvidenceValidationRequestV1,
            context: ExternalEvidenceMeasurementContextV1,
        ) -> tuple[ExternalEvidenceValidationInputBinding, ...]:
            entered.set()
            assert release.wait(3)
            return super().issue_input(item=item, request=request, context=context)

    validations = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=evidence,
        policy_registry=registry,
        context_authority=context,
        input_capabilities=PausedCapability(),
        clock=lambda: validation_fixture.NOW,
        coordinator=coordinator,
    )
    issued = validations.issue_after_seal(ref, now=validation_fixture.NOW)
    assert issued.request is not None
    acquired = validations.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=validation_fixture.NOW,
    )
    assert acquired.fence is not None
    before = list(validations._journal.replay())
    original_apply = evidence._apply

    def fault(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-declared":
            raise RuntimeError("live projection fault")
        original_apply(raw)

    evidence._apply = fault
    with ThreadPoolExecutor(max_workers=1) as executor:
        issuing = executor.submit(
            validations.input_for,
            issued.request.validation_id,
            acquired.fence,
            organization_id="org-a",
        )
        try:
            assert entered.wait(3)
            with pytest.raises(RuntimeError, match="live projection fault"):
                evidence.declare(
                    ExternalEvidenceDeclarationIntent.model_validate(_intent(b"new")),
                    revision=revision,
                    principal=principal,
                    key="poison",
                    now=_NOW,
                )
            release.set()
            with pytest.raises(ExternalEvidenceRecoveryError):
                issuing.result(timeout=3)
        finally:
            release.set()
    assert list(validations._journal.replay()) == before


def test_default_construction_shares_real_ingress_coordinator(tmp_path: Path) -> None:
    evidence, _, _, _, _ = _direct_evidence_context(tmp_path)
    registry, _ = validation_fixture._policy_registry(tmp_path, coordinator=evidence.coordinator)
    validation = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "default-validation.jsonl"),
        evidence=evidence,
        policy_registry=registry,
    )
    assert validation.coordinator is evidence.coordinator
    validation._journal.close()
    evidence._journal.close()


@pytest.mark.parametrize("explicit", [False, True])
def test_adapter_without_coordinator_is_rejected_before_journal_replay(
    tmp_path: Path, explicit: bool
) -> None:
    evidence, _, _, _, _ = _direct_evidence_context(tmp_path)
    registry, _ = validation_fixture._policy_registry(tmp_path, coordinator=evidence.coordinator)

    class UnsafeAdapter:
        def resolve_for_validation(self, evidence_ref: str) -> EvidenceItem | None:
            return evidence.resolve_for_validation(evidence_ref)

        def locally_matches(self, evidence_ref: str, item: EvidenceItem) -> bool:
            return evidence.locally_matches(evidence_ref, item)

        def assert_locally_available(self) -> None:
            evidence.assert_locally_available()

    journal = DurableJournal(tmp_path / "unsafe-validation.jsonl")
    try:
        with pytest.raises(ValueError, match="evidence store must provide"):
            ExternalEvidenceValidationStore(
                journal,
                evidence=cast(SealedEvidenceValidationPort, UnsafeAdapter()),
                policy_registry=registry,
                coordinator=evidence.coordinator if explicit else None,
            )
        assert list(journal.replay()) == []
    finally:
        journal.close()
        evidence._journal.close()


def test_real_ingress_adapter_shares_its_actual_coordinator(tmp_path: Path) -> None:
    evidence, _, _, _, _ = _direct_evidence_context(tmp_path)
    registry, _ = validation_fixture._policy_registry(tmp_path, coordinator=evidence.coordinator)

    class SharedAdapter:
        @property
        def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
            return evidence.coordinator

        def resolve_for_validation(self, evidence_ref: str) -> EvidenceItem | None:
            return evidence.resolve_for_validation(evidence_ref)

        def locally_matches(self, evidence_ref: str, item: EvidenceItem) -> bool:
            return evidence.locally_matches(evidence_ref, item)

        def assert_locally_available(self) -> None:
            evidence.assert_locally_available()

    journal = DurableJournal(tmp_path / "adapter-validation.jsonl")
    try:
        validation = ExternalEvidenceValidationStore(
            journal, evidence=SharedAdapter(), policy_registry=registry
        )
        assert validation.coordinator is evidence.coordinator
    finally:
        journal.close()
        evidence._journal.close()


@pytest.mark.parametrize("mismatch", ["policy", "context"])
def test_default_construction_rejects_mismatched_currentness_graph(
    tmp_path: Path, mismatch: str
) -> None:
    evidence, _, _, _, _ = _direct_evidence_context(tmp_path)
    if mismatch == "policy":
        registry, _ = validation_fixture._policy_registry(tmp_path)
        context = None
    else:
        registry, _ = validation_fixture._policy_registry(
            tmp_path, coordinator=evidence.coordinator
        )
        context = validation_fixture._ContextAuthority(None)
    journal = DurableJournal(tmp_path / "mismatch-validation.jsonl")
    before = list(journal.replay())
    try:
        with pytest.raises(ValueError, match="must share currentness coordinator"):
            ExternalEvidenceValidationStore(
                journal, evidence=evidence, policy_registry=registry, context_authority=context
            )
        assert list(journal.replay()) == before
    finally:
        journal.close()
        evidence._journal.close()


def test_default_coordinator_serializes_final_check_with_real_ingress_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, storage, revision, principal, ref = _direct_evidence_context(tmp_path)
    declared = evidence._items[ref]
    storage.objects[declared.object_key] = ObjectStorageObservation(
        declared.object_key,
        True,
        5,
        declared.declaration.declared_content_digest,
        declared.declaration.declared_content_type,
    )
    evidence.seal(
        ref, revision=revision, principal=principal, key="seal", storage=storage, now=_NOW
    )
    item = evidence.resolve_for_validation(ref)
    assert item is not None and item.manifest is not None
    monkeypatch.setattr(validation_fixture, "_subject", lambda: item.manifest.subject)
    registry, policy = validation_fixture._policy_registry(
        tmp_path, coordinator=evidence.coordinator
    )
    context = validation_fixture._ContextAuthority(
        validation_fixture._context(item, policy), coordinator=evidence.coordinator
    )
    validation = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "default-validation.jsonl"),
        evidence=evidence,
        policy_registry=registry,
        context_authority=context,
        clock=lambda: validation_fixture.NOW,
    )
    assert validation.coordinator is evidence.coordinator
    checked, release, fault_started = Event(), Event(), Event()
    original_match = evidence.locally_matches
    original_apply = evidence._apply
    order: list[str] = []

    def paused_match(evidence_ref: str, expected: EvidenceItem) -> bool:
        result = original_match(evidence_ref, expected)
        checked.set()
        assert release.wait(3)
        return result

    def fail_live(raw: dict[str, Any]) -> None:
        if raw["kind"] == "external-evidence-declared":
            assert len(validation._journal.replay()) == len(before) + 1
            order.append("fault")
            raise RuntimeError("projection fault")
        original_apply(raw)

    def issue() -> EvidenceValidationVerdict:
        result = validation.issue_after_seal(ref, now=validation_fixture.NOW)
        order.append("issued")
        return result.verdict

    def poison() -> None:
        fault_started.set()
        evidence.declare(
            ExternalEvidenceDeclarationIntent.model_validate(_intent(b"new")),
            revision=revision,
            principal=principal,
            key="fault",
            now=_NOW,
        )

    evidence.locally_matches = paused_match
    evidence._apply = fail_live
    before = list(validation._journal.replay())
    with ThreadPoolExecutor(max_workers=2) as executor:
        issuance = executor.submit(issue)
        try:
            assert checked.wait(3)
            failure = executor.submit(poison)
            assert fault_started.wait(3)
        finally:
            release.set()
        assert issuance.result(timeout=3) is EvidenceValidationVerdict.ISSUED
        with pytest.raises(RuntimeError, match="projection fault"):
            failure.result(timeout=3)
    # The guarded append precedes the competing poison, irrespective of return scheduling.
    assert len(validation._journal.replay()) == len(before) + 1
    assert order.count("fault") == 1
    with pytest.raises(ExternalEvidenceRecoveryError):
        validation.issue_after_seal(ref, now=validation_fixture.NOW)
    validation._journal.close()
    evidence._journal.close()
