"""File-backed external-authority provider lifecycle and public loader."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, local
from typing import Any, cast

from fastapi import FastAPI
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.domains.external.authority.external_result_workflow_config import (
    ExternalQuantitativeWorkflowParticipants,
)
from ksi_core.domains.external.authority.provider_loading import (
    _config_from_path,
    _snapshot_from_path,
)
from ksi_core.domains.external.authority.provider_participants import (
    _CatalogCurrentness,
    _CatalogPort,
    _EvidenceContextPort,
    _PolicyCurrentness,
    _PolicyPort,
)
from ksi_core.domains.external.authority.provider_receipts import (
    _historical_contexts_from_receipts,
    _historical_policies_from_receipts,
    _receipt_event,
    _receipt_for,
    _replay_receipts,
)
from ksi_core.domains.external.authority.provider_types import (
    _RECEIPT_NAME,
    ExternalAuthorityProviderError,
    _AdministrationAction,
    _AuthorityGeneration,
    _copy_snapshot,
    _ProviderConfig,
    _Receipt,
    _VerifiedSnapshot,
)
from ksi_core.domains.external.ingress.external_evidence_validations import (
    EvidenceMeasurementContextAuthorityPort,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    PolicyAuthorityCurrentnessPort,
    PolicyAuthorityRecord,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityCurrentnessPort,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.domains.external.quantity.external_single_volume_authority import (
    ExternalSingleVolumeCompatibilityRecord,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal


class ExternalAuthorityProvider:
    """One verified authority bundle and its Core participant ports."""

    def __init__(
        self,
        config: _ProviderConfig,
        snapshot: _VerifiedSnapshot,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._candidate_snapshot: _VerifiedSnapshot | None = snapshot
        self._published_generation: _AuthorityGeneration | None = None
        self._clock = clock
        self._blocked_reason: str | None = None
        self._configured = False
        self._state_lock = RLock()
        # Reload is a transaction over one mutable signed source and several
        # durable participant journals.  A newer caller must not reserve a
        # ticket or begin its protected read while an older reconciliation can
        # still append participant/receipt records and publish its generation.
        self._reload_lock = RLock()
        self._staged = local()
        self._latest_reload_ticket = 0
        self._next_generation = 0
        self._receipt_journal: DurableJournal | None = None
        self._receipts: tuple[_Receipt, ...] = ()
        self._historical_contexts: dict[str, ExternalEvidenceMeasurementContextV1] = {}
        self._historical_policies: dict[str, PolicyAuthorityRecord] = {}
        self._app: FastAPI | None = None
        self._participant_coordinator: ExternalAuthorityCurrentnessCoordinator | None = None
        self._catalog_port = _CatalogPort(self)
        self._policy_port = _PolicyPort(self)
        self._catalog_currentness_port: _CatalogCurrentness | None = None
        self._policy_currentness_port: _PolicyCurrentness | None = None
        self._evidence_context_port: _EvidenceContextPort | None = None
        self.participants = ExternalQuantitativeWorkflowParticipants(
            catalog_authority_port=self._catalog_port,
            catalog_administration_actor_id=config.catalog_administration_actor_id,
            queue_policy=config.queue_policy,
            clock=clock,
            build_catalog_authority_currentness=self._build_catalog_currentness,
            policy_authority_port=self._policy_port,
            build_policy_authority_currentness=self._build_policy_currentness,
            build_evidence_context_authority=self._build_evidence_context,
        )

    @property
    def organization_id(self) -> str:
        return self._config.organization_id

    def status(self) -> dict[str, object]:
        try:
            now = self._clock()
        except Exception:
            now = None
        with self._state_lock:
            generation = self._published_generation
            snapshot = generation.snapshot if generation is not None else self._candidate_snapshot
            configured = self._configured and generation is not None
            receipt_sealed = bool(
                self._receipt_journal is not None
                and self._receipt_journal.sealed_reason is not None
            )
            blocked = self._blocked_reason is not None
        if (
            snapshot is None
            or now is None
            or not self._snapshot_valid_at(snapshot, now)
            or receipt_sealed
            or blocked
        ):
            return {
                "status": "BLOCKED",
                "organizationId": self.organization_id,
                "snapshotSequence": None,
                "snapshotDigest": None,
                "businessEligible": False,
            }
        return {
            "status": "PROVIDER_CONFIGURED" if configured else "CONFIG_VALIDATED",
            "organizationId": self.organization_id,
            "snapshotSequence": snapshot.sequence,
            "snapshotDigest": snapshot.digest,
            "businessEligible": False,
        }

    def bind_receipt_journal(self, journal: DurableJournal) -> None:
        if self._receipt_journal is not None and self._receipt_journal is not journal:
            raise ExternalAuthorityProviderError("authority receipt journal is already bound")
        if not isinstance(journal, DurableJournal):
            raise ValueError("authority receipt journal must be durable")
        journal_path = getattr(journal, "_path", None)
        if (
            not isinstance(journal_path, Path)
            or not journal_path.is_absolute()
            or journal_path.name != _RECEIPT_NAME
        ):
            raise ValueError(
                "authority receipt journal must use the fixed absolute receipt path name"
            )
        try:
            with self._state_lock:
                snapshot = self._candidate_snapshot
            if snapshot is None:
                raise ValueError("authority provider has no verified candidate snapshot")
            receipts = _replay_receipts(journal)
            self._validate_history(receipts, snapshot)
            historical_contexts = _historical_contexts_from_receipts(
                receipts, organization_id=self.organization_id
            )
            historical_policies = _historical_policies_from_receipts(
                receipts, organization_id=self.organization_id
            )
        except Exception as exc:
            self._block(type(exc).__name__)
            raise ExternalAuthorityProviderError("authority receipt history is blocked") from exc
        with self._state_lock:
            self._receipt_journal = journal
            self._receipts = receipts
            self._historical_contexts = historical_contexts
            self._historical_policies = historical_policies

    def attach_app(self, app: FastAPI) -> None:
        if self._receipt_journal is None:
            raise ExternalAuthorityProviderError(
                "authority receipt journal must bind before app attach"
            )
        state = getattr(app, "state", None)
        if state is None:
            raise ValueError("authority provider requires an assembled FastAPI application")
        with self._reload_lock:
            with self._state_lock:
                if self._app is not None and self._app is not app:
                    raise ExternalAuthorityProviderError(
                        "authority provider cannot cross application graphs"
                    )
            # Validate every application participant before committing our
            # identity to the graph.  A malformed first graph must leave this
            # verified provider attachable to the actual assembled app.
            self._graph_from_state(state)
            coordinator = state.external_authority_currentness
            self._bind_participant_coordinator(coordinator)
            with self._state_lock:
                self._app = app
            try:
                with coordinator.mutation():
                    try:
                        now = self._clock()
                        with self._state_lock:
                            candidate = self._candidate_snapshot
                        if candidate is None:
                            raise ExternalAuthorityProviderError("authority provider is blocked")
                        if now < candidate.issued_at:
                            raise ExternalAuthorityProviderError(
                                "authority snapshot is not yet issued at attach time"
                            )
                        if (
                            now >= candidate.valid_until
                            or now >= candidate.key_not_after
                        ):
                            # Keep the signed snapshot and complete workflow
                            # graph available for replay, but never reconcile,
                            # publish, or append a receipt for stale authority.
                            with self._state_lock:
                                self._blocked_reason = "EXPIRED"
                                self._configured = False
                                state.external_authority_provider = self
                            return
                        if not self._snapshot_valid_at(candidate, now):
                            raise ExternalAuthorityProviderError(
                                "authority snapshot is not current at attach time"
                            )
                        receipt = self._reconcile_candidate(candidate, now=now)
                        self._publish_generation(candidate, receipt)
                        state.external_authority_provider = self
                    except Exception as exc:
                        # Currentness users share this mutation boundary.  Do
                        # not release it after participant reconciliation has
                        # failed while an old published generation is live.
                        with self._state_lock:
                            if self._app is app:
                                self._app = None
                            self._block_locked(type(exc).__name__, ticket=None)
                        raise
            except Exception as exc:
                if isinstance(exc, ExternalAuthorityProviderError):
                    raise
                raise ExternalAuthorityProviderError(
                    "authority provider reconciliation failed"
                ) from exc

    def reload_and_reconcile(self, *, now: datetime) -> dict[str, object]:
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("authority reload time must be UTC-aware")
        with self._reload_lock:
            with self._state_lock:
                self._latest_reload_ticket += 1
                ticket = self._latest_reload_ticket
            try:
                replacement = _load(self._config, clock=self._clock, validation_now=now)
            except Exception as exc:
                self._block(type(exc).__name__, ticket=ticket)
                return self._reload_result()
            candidate = replacement._candidate_snapshot
            assert candidate is not None
            with self._state_lock:
                app = self._app
                coordinator = self._participant_coordinator
                if app is None or coordinator is None:
                    self._candidate_snapshot = candidate
                    self._blocked_reason = None
                    self._configured = False
                    return self._reload_result_locked()
            with coordinator.mutation():
                try:
                    receipt = self._reconcile_candidate(candidate, now=now)
                    self._publish_generation(candidate, receipt)
                except Exception:
                    # Publish the failure while this same participant mutation
                    # remains held, so guarded use cannot retain the preceding
                    # receipt-backed generation in between.
                    with self._state_lock:
                        self._block_locked("RECONCILIATION", ticket=ticket)
            return self._reload_result()

    def _graph_from_state(self, state: object) -> tuple[Any, Any, Any, Any, Any]:
        coordinator = getattr(state, "external_authority_currentness", None)
        registry = getattr(state, "external_validation_policy_registry", None)
        inspections = getattr(state, "external_artifact_inspection_store", None)
        evidence_store = getattr(state, "external_evidence_store", None)
        evidence = getattr(state, "external_evidence_validation_store", None)
        catalog = getattr(state, "external_relative_volume_mapping_authority", None)
        if not isinstance(coordinator, ExternalAuthorityCurrentnessCoordinator):
            raise ValueError("authority provider requires the assembled coordinator")
        if (
            registry is None
            or inspections is None
            or evidence_store is None
            or evidence is None
            or catalog is None
            or getattr(registry, "coordinator", None) is not coordinator
            or getattr(registry, "authority_currentness_port", None)
            is not self._policy_currentness_port
            or getattr(inspections, "coordinator", None) is not coordinator
            or getattr(evidence_store, "coordinator", None) is not coordinator
            or getattr(evidence, "coordinator", None) is not coordinator
            or getattr(catalog, "currentness_coordinator", None) is not coordinator
        ):
            raise ValueError("authority provider participants must share the Core coordinator")
        return registry, inspections, evidence_store, evidence, catalog

    def _bind_participant_coordinator(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> None:
        if (
            self._participant_coordinator is not None
            and self._participant_coordinator is not coordinator
        ):
            raise ValueError("authority provider participants cannot cross Core coordinators")
        self._participant_coordinator = coordinator

    def _build_catalog_currentness(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> ExternalQuantitativeCatalogAuthorityCurrentnessPort:
        self._bind_participant_coordinator(coordinator)
        if self._catalog_currentness_port is None:
            self._catalog_currentness_port = _CatalogCurrentness(self, coordinator)
        return self._catalog_currentness_port

    def _build_policy_currentness(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> PolicyAuthorityCurrentnessPort:
        self._bind_participant_coordinator(coordinator)
        if self._policy_currentness_port is None:
            self._policy_currentness_port = _PolicyCurrentness(self, coordinator)
        return self._policy_currentness_port

    def _build_evidence_context(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> EvidenceMeasurementContextAuthorityPort:
        self._bind_participant_coordinator(coordinator)
        if self._evidence_context_port is None:
            self._evidence_context_port = _EvidenceContextPort(self, coordinator)
        return self._evidence_context_port

    def _reconcile_candidate(self, candidate: _VerifiedSnapshot, *, now: datetime) -> _Receipt:
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("authority reconciliation time must be UTC-aware")
        if self._app is None or self._receipt_journal is None:
            raise ExternalAuthorityProviderError("authority provider is not ready to reconcile")
        if any(action.effective_at > now for action in candidate.actions):
            raise ExternalAuthorityProviderError(
                "signed administration action is not yet effective"
            )
        state = getattr(self._app, "state", None)
        if state is None:
            raise ExternalAuthorityProviderError("authority provider lost its application state")
        registry, inspections, evidence_store, evidence, catalog = self._graph_from_state(state)
        self._stage_candidate(candidate)
        try:
            self._validate_history(self._receipts, candidate)
            self._apply_policy_actions(registry, candidate)
            # Policy/context changes become visible to pending sealed records before a
            # later mapping action can admit an eligible pair.
            if (
                not callable(getattr(inspections, "reconcile_sealed", None))
                or not callable(getattr(evidence_store, "sealed_items_snapshot", None))
                or not callable(getattr(evidence, "issue_after_seal", None))
            ):
                raise ExternalAuthorityProviderError(
                    "authority provider graph cannot reconcile sealed work"
                )
            inspections.reconcile_sealed(now)
            for item in evidence_store.sealed_items_snapshot():
                evidence.issue_after_seal(item.evidence_ref, now=now)
            self._apply_mapping_actions(catalog, candidate)
            receipt = next(
                (item for item in self._receipts if item.snapshot_digest == candidate.digest), None
            )
            if receipt is None:
                receipt = _receipt_for(
                    candidate, previous=self._receipts[-1] if self._receipts else None
                )
                try:
                    self._receipt_journal.append(_receipt_event(receipt))
                except Exception as exc:
                    raise ExternalAuthorityProviderError("authority receipt append failed") from exc
                self._receipts = (*self._receipts, receipt)
            self._retain_historical_contexts(candidate.context_records)
            self._retain_historical_policies(candidate.policy_records)
            return receipt
        finally:
            self._clear_staged_candidate()

    def _retain_historical_contexts(
        self, contexts: Mapping[str, ExternalEvidenceMeasurementContextV1]
    ) -> None:
        for digest, context in contexts.items():
            retained = self._historical_contexts.setdefault(digest, context)
            if retained != context:
                raise ExternalAuthorityProviderError("historical evidence context is substituted")

    def _retain_historical_policies(self, policies: Mapping[str, PolicyAuthorityRecord]) -> None:
        for digest, policy in policies.items():
            retained = self._historical_policies.setdefault(digest, policy)
            if retained != policy:
                raise ExternalAuthorityProviderError("historical policy authority is substituted")

    def _apply_policy_actions(self, registry: Any, snapshot: _VerifiedSnapshot) -> None:
        for action in snapshot.actions:
            if action.kind == "ADMIT_POLICY":
                policy = ExternalValidationPolicyV1.model_validate(action.payload["policy"])
                if (
                    policy.synthetic_test_only
                    or policy.policy_digest is None
                    or policy.policy_digest != policy.canonical_digest()
                ):
                    raise ValueError(
                        "signed policy action must carry a sealed non-synthetic policy"
                    )
                receipt = registry.admit(policy, action.actor_id, action.effective_at)
                allowed = {"ADMITTED", "IDEMPOTENT"}
            elif action.kind == "REVOKE_POLICY":
                receipt = registry.revoke(
                    cast(str, action.payload["policyId"]),
                    cast(int, action.payload["policyVersion"]),
                    action.actor_id,
                    action.effective_at,
                )
                allowed = {"REVOKED"}
            elif action.kind == "SUPERSEDE_POLICY":
                receipt = registry.supersede(
                    cast(str, action.payload["policyId"]),
                    cast(int, action.payload["policyVersion"]),
                    cast(str, action.payload["successorPolicyId"]),
                    cast(int, action.payload["successorPolicyVersion"]),
                    action.actor_id,
                    action.effective_at,
                )
                allowed = {"SUPERSEDED"}
            else:
                continue
            status = getattr(getattr(receipt, "status", None), "value", None)
            if status not in allowed and not self._policy_action_effect_retained(registry, action):
                raise ExternalAuthorityProviderError("signed policy action was not applied")

    def _apply_mapping_actions(self, catalog: Any, snapshot: _VerifiedSnapshot) -> None:
        for action in snapshot.actions:
            if action.kind == "ADMIT_MAPPING":
                if action.actor_id != self._config.catalog_administration_actor_id:
                    raise ValueError(
                        "mapping action actor is not the configured catalog administrator"
                    )
                mapping = ExternalQuantitativeCompatibilityRecord.from_event_payload(
                    action.payload["mapping"]
                )
                if (
                    mapping.organization_id != self.organization_id
                    or catalog.admit_mapping(
                        mapping, actor=action.actor_id, now=action.effective_at
                    )
                    is None
                ):
                    raise ExternalAuthorityProviderError("signed mapping admission was not applied")
            elif action.kind == "ADMIT_SINGLE_MAPPING":
                if action.actor_id != self._config.catalog_administration_actor_id:
                    raise ValueError(
                        "mapping action actor is not the configured catalog administrator"
                    )
                single = ExternalSingleVolumeCompatibilityRecord.from_event_payload(
                    action.payload["mapping"]
                )
                if (
                    single.organization_id != self.organization_id
                    or catalog.admit_single_mapping(
                        single, actor=action.actor_id, now=action.effective_at
                    )
                    is None
                ):
                    raise ExternalAuthorityProviderError(
                        "signed single-volume mapping admission was not applied"
                    )
            elif action.kind == "REVOKE_SINGLE_MAPPING":
                if (
                    action.actor_id != self._config.catalog_administration_actor_id
                    or not catalog.revoke_single_mapping(
                        cast(str, action.payload["mappingDigest"]),
                        actor=action.actor_id,
                        now=action.effective_at,
                    )
                ):
                    raise ExternalAuthorityProviderError(
                        "signed single-volume mapping revocation was not applied"
                    )
            elif action.kind == "REVOKE_MAPPING":
                if (
                    action.actor_id != self._config.catalog_administration_actor_id
                    or not catalog.revoke_mapping(
                        cast(str, action.payload["mappingDigest"]),
                        actor=action.actor_id,
                        now=action.effective_at,
                    )
                ):
                    raise ExternalAuthorityProviderError(
                        "signed mapping revocation was not applied"
                    )

    @staticmethod
    def _policy_action_effect_retained(registry: Any, action: _AdministrationAction) -> bool:
        journal = getattr(registry, "_journal", None)
        if not isinstance(journal, DurableJournal):
            return False
        expected_kind = {
            "REVOKE_POLICY": "external-validation-policy-revoked",
            "SUPERSEDE_POLICY": "external-validation-policy-superseded",
        }.get(action.kind)
        if expected_kind is None:
            return False
        occurred_at = action.effective_at.isoformat().replace("+00:00", "Z")
        for event in journal.replay():
            if (
                event.get("kind") == expected_kind
                and event.get("actor") == action.actor_id
                and event.get("occurredAt") == occurred_at
                and event.get("policyId") == action.payload.get("policyId")
                and event.get("policyVersion") == action.payload.get("policyVersion")
                and (
                    action.kind != "SUPERSEDE_POLICY"
                    or (
                        event.get("successorPolicyId") == action.payload.get("successorPolicyId")
                        and event.get("successorPolicyVersion")
                        == action.payload.get("successorPolicyVersion")
                    )
                )
            ):
                return True
        return False

    def _validate_history(
        self, receipts: tuple[_Receipt, ...], snapshot: _VerifiedSnapshot
    ) -> None:
        if not receipts:
            if snapshot.sequence != 1 or snapshot.raw["previousSnapshotDigest"] is not None:
                raise ValueError("initial authority snapshot does not start a new history")
            return
        prior = receipts[-1]
        for receipt in receipts:
            if (
                receipt.key_id == snapshot.key_id
                and receipt.public_key_digest != snapshot.public_key_digest
            ):
                raise ValueError("authority snapshot substitutes pinned key material")
        if snapshot.sequence == prior.sequence:
            if snapshot.digest != prior.snapshot_digest:
                raise ValueError("authority snapshot substitutes retained history")
            return
        if (
            snapshot.sequence != prior.sequence + 1
            or snapshot.raw["previousSnapshotDigest"] != prior.snapshot_digest
        ):
            raise ValueError("authority snapshot does not extend the retained history")

    @staticmethod
    def _snapshot_valid_at(snapshot: _VerifiedSnapshot, now: datetime) -> bool:
        return (
            now.tzinfo is not None
            and now.utcoffset() == UTC.utcoffset(now)
            and snapshot.issued_at <= now < snapshot.valid_until
            and snapshot.key_not_before <= now < snapshot.key_not_after
        )

    def _live_generation(self, now: datetime) -> _AuthorityGeneration | None:
        """Return only the receipt-published generation usable by live ports.

        This method intentionally never reads a pathname.  Explicit reload is
        the sole disk publication boundary; an already-loaded generation stays
        intact until then, while its embedded snapshot/key interval and receipt
        seal are checked on every live use.
        """
        with self._state_lock:
            generation = self._published_generation
            journal = self._receipt_journal
            if (
                generation is None
                or self._blocked_reason is not None
                or not self._configured
                or self._app is None
                or self._participant_coordinator is None
                or journal is None
                or journal.sealed_reason is not None
                or not self._snapshot_valid_at(generation.snapshot, now)
            ):
                return None
            return generation

    def _live_snapshot(self, now: datetime, *, permit_staged: bool) -> _VerifiedSnapshot | None:
        """Return the one current live snapshot, or this thread's reconciliation candidate."""
        if permit_staged:
            staged = getattr(self._staged, "candidate", None)
            if isinstance(staged, _VerifiedSnapshot) and self._snapshot_valid_at(staged, now):
                # _reconcile_candidate stages only its own thread while the
                # caller holds the participant coordinator mutation.  A
                # blocked provider must still let that thread resolve a signed
                # corrective candidate; all other threads lack this local
                # value and fall through to the blocked live generation.
                with self._state_lock:
                    journal = self._receipt_journal
                    if (
                        self._participant_coordinator is not None
                        and journal is not None
                        and journal.sealed_reason is None
                    ):
                        return staged
        generation = self._live_generation(now)
        return generation.snapshot if generation is not None else None

    def _configuration_snapshot(self, now: datetime) -> _VerifiedSnapshot | None:
        """Expose a verified candidate only while Core is still closed.

        Catalog construction/replay needs exact signed records before a receipt
        exists.  Its coordinator-bound currentness port still rejects every
        live mutation until this candidate is receipt-published.
        """
        generation = self._live_generation(now)
        if generation is not None:
            return generation.snapshot
        with self._state_lock:
            candidate = self._candidate_snapshot
            if (
                self._app is None
                and self._blocked_reason is None
                and candidate is not None
                and self._snapshot_valid_at(candidate, now)
            ):
                return candidate
            return None

    def catalog_configuration_was_authorized(
        self,
        *,
        authority_record_digest: str,
        catalog_body_digest: str,
        organization_id: str,
        administration_actor_id: str,
    ) -> bool:
        """Check a catalog binding from its exact signed record and valid history."""
        try:
            now = self._clock()
        except Exception:
            return False
        with self._state_lock:
            snapshot = self._candidate_snapshot
        if (
            snapshot is None
            or now.tzinfo is None
            or now.utcoffset() != UTC.utcoffset(now)
            or snapshot.issued_at > now
            or organization_id != self.organization_id
            or authority_record_digest not in snapshot.current_catalog_digests
        ):
            return False
        record = snapshot.catalog_records.get(authority_record_digest)
        if record is None:
            return False
        if now < snapshot.valid_until and now < record.active_until:
            return False
        historical_at = max(snapshot.issued_at, snapshot.key_not_before, record.active_from)
        historical_until = min(snapshot.valid_until, snapshot.key_not_after, record.active_until)
        return bool(
            historical_at < historical_until
            and historical_at <= now
            and record.permits_catalog(
                catalog_body_digest=catalog_body_digest,
                organization_id=organization_id,
                administration_actor_id=administration_actor_id,
                now=historical_at,
            )
        )

    def _historical_policy(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        if at.tzinfo is None or at.utcoffset() != UTC.utcoffset(at):
            return None
        with self._state_lock:
            record = self._historical_policies.get(authority_record_digest)
            snapshots = (
                self._candidate_snapshot,
                self._published_generation.snapshot
                if self._published_generation is not None
                else None,
            )
        if record is None:
            for snapshot in snapshots:
                if snapshot is not None:
                    candidate = snapshot.policy_records.get(authority_record_digest)
                    if candidate is not None:
                        record = candidate
                        break
        if (
            record is None
            or record.digest != authority_record_digest
            or not record.is_active_at(at)
            or any(
                subject.organization_id != self.organization_id
                for subject in record.permitted_subjects
            )
        ):
            return None
        return record

    def _historical_context(
        self, context_digest: str
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        with self._state_lock:
            context = self._historical_contexts.get(context_digest)
            snapshots = (
                self._candidate_snapshot,
                self._published_generation.snapshot
                if self._published_generation is not None
                else None,
            )
        if context is None:
            for snapshot in snapshots:
                if snapshot is not None:
                    candidate = snapshot.context_records.get(context_digest)
                    if candidate is not None:
                        context = candidate
                        break
        if (
            context is None
            or context.context_digest != context_digest
            or context.subject.organization_id != self.organization_id
        ):
            return None
        return context

    def _stage_candidate(self, candidate: _VerifiedSnapshot) -> None:
        if getattr(self._staged, "candidate", None) is not None:
            raise ExternalAuthorityProviderError("authority reconciliation is already staged")
        self._staged.candidate = candidate

    def _clear_staged_candidate(self) -> None:
        if hasattr(self._staged, "candidate"):
            del self._staged.candidate

    def _publish_generation(self, candidate: _VerifiedSnapshot, receipt: _Receipt) -> None:
        if receipt.snapshot_digest != candidate.digest or receipt.sequence != candidate.sequence:
            raise ExternalAuthorityProviderError("authority receipt does not bind the candidate")
        with self._state_lock:
            self._next_generation += 1
            self._candidate_snapshot = candidate
            self._published_generation = _AuthorityGeneration(
                snapshot=_copy_snapshot(candidate),
                counter=self._next_generation,
                receipt_sequence=receipt.sequence,
                receipt_history_digest=receipt.history_digest,
            )
            self._blocked_reason = None
            self._configured = True

    def _block(self, reason: str, *, ticket: int | None = None) -> None:
        coordinator = self._participant_coordinator
        if coordinator is None:
            with self._state_lock:
                self._block_locked(reason, ticket=ticket)
            return
        with coordinator.mutation(), self._state_lock:
            self._block_locked(reason, ticket=ticket)

    def _block_locked(self, reason: str, *, ticket: int | None) -> None:
        if ticket is not None and ticket != self._latest_reload_ticket:
            return
        self._candidate_snapshot = None
        self._published_generation = None
        self._configured = False
        self._blocked_reason = reason

    def _reload_result(self) -> dict[str, object]:
        with self._state_lock:
            return self._reload_result_locked()

    def _reload_result_locked(self) -> dict[str, object]:
        generation = self._published_generation
        candidate = self._candidate_snapshot
        snapshot = generation.snapshot if generation is not None else candidate
        if self._blocked_reason is not None or snapshot is None:
            return {"status": "BLOCKED", "sequence": None, "snapshotDigest": None}
        return {
            "status": (
                "PROVIDER_CONFIGURED"
                if generation is not None and self._configured
                else "CONFIG_VALIDATED"
            ),
            "sequence": snapshot.sequence,
            "snapshotDigest": snapshot.digest,
        }


def _load(
    config: _ProviderConfig,
    *,
    clock: Callable[[], datetime],
    validation_now: datetime | None = None,
    allow_expired: bool = False,
) -> ExternalAuthorityProvider:
    validation_clock = clock if validation_now is None else lambda: validation_now
    return ExternalAuthorityProvider(
        config,
        _snapshot_from_path(config, clock=validation_clock, allow_expired=allow_expired),
        clock=clock,
    )


def load_external_authority_provider(
    path: Path, *, clock: Callable[[], datetime], allow_expired: bool = False
) -> ExternalAuthorityProvider:
    """Verify file-backed authority inputs without opening a receipt journal."""
    if not callable(clock):
        raise ValueError("authority provider requires a clock")
    try:
        return _load(_config_from_path(path), clock=clock, allow_expired=allow_expired)
    except (OSError, ValueError, TypeError) as exc:
        raise ExternalAuthorityProviderError("external authority provider is blocked") from exc


__all__ = [
    "ExternalAuthorityProvider",
    "ExternalAuthorityProviderError",
    "load_external_authority_provider",
]
