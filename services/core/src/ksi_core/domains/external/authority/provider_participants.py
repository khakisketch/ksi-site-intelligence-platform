"""Authority-provider participant adapters; lifecycle remains in the provider."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.domains.external.ingress.external_evidence_validations import (
    EvidenceMeasurementContextAuthorityPort,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    PolicyAuthorityCurrentnessPort,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityCurrentnessPort,
    ExternalQuantitativeCatalogAuthorityPort,
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator

if TYPE_CHECKING:
    from ksi_core.domains.external.authority.external_authority_provider import (
        ExternalAuthorityProvider,
    )

class _CatalogPort(ExternalQuantitativeCatalogAuthorityPort):
    def __init__(self, provider: ExternalAuthorityProvider) -> None:
        self._provider = provider

    def resolve(
        self, authority_record_digest: str, now: datetime
    ) -> ExternalQuantitativeCatalogAuthorityRecord | None:
        # During startup/reload, mapping reconciliation runs before the new
        # receipt is published.  Its thread-local candidate is the same exact
        # signed snapshot that policy/context participants consume; falling
        # back to configuration-only material keeps the pre-attach catalog
        # loader default-closed without exposing that candidate to other
        # threads.
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None:
            snapshot = self._provider._configuration_snapshot(now)
        if snapshot is None or authority_record_digest not in snapshot.current_catalog_digests:
            return None
        record = snapshot.catalog_records.get(authority_record_digest)
        if (
            record is None
            or record.organization_id != self._provider.organization_id
            or not record.is_active_at(now)
        ):
            return None
        return record

    def resolve_historical_configuration(
        self,
        authority_record_digest: str,
        *,
        catalog_body_digest: str,
        organization_id: str,
        administration_actor_id: str,
    ) -> bool:
        return self._provider.catalog_configuration_was_authorized(
            authority_record_digest=authority_record_digest,
            catalog_body_digest=catalog_body_digest,
            organization_id=organization_id,
            administration_actor_id=administration_actor_id,
        )


class _PolicyPort(PolicyAuthorityPort):
    def __init__(self, provider: ExternalAuthorityProvider) -> None:
        self._provider = provider

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None or authority_record_digest not in snapshot.current_policy_digests:
            return None
        record = snapshot.policy_records.get(authority_record_digest)
        if record is None or not record.is_active_at(now):
            return None
        if any(
            subject.organization_id != self._provider.organization_id
            for subject in record.permitted_subjects
        ):
            return None
        return record

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        return self._provider._historical_policy(authority_record_digest, at)


class _PolicyCurrentness(PolicyAuthorityCurrentnessPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and authority.digest is not None
            and authority.digest in snapshot.current_policy_digests
            and snapshot.policy_records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


class _CatalogCurrentness(ExternalQuantitativeCatalogAuthorityCurrentnessPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def is_current(
        self, authority: ExternalQuantitativeCatalogAuthorityRecord, now: datetime
    ) -> bool:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and authority.digest is not None
            and authority.digest in snapshot.current_catalog_digests
            and snapshot.catalog_records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


class _EvidenceContextPort(EvidenceMeasurementContextAuthorityPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

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
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None:
            return None
        matches = tuple(
            context
            for digest, context in snapshot.context_records.items()
            if (
                digest in snapshot.current_context_digests
                and context.is_active_at(now)
                and context.subject == subject
                and context.evidence_manifest_digest == evidence_manifest_digest
                and context.target_dsm_artifact_id == target_dsm_artifact_id
                and context.target_dsm_observed_sha256 == target_dsm_observed_sha256
                and context.policy_digest == policy_digest
            )
        )
        return matches[0] if len(matches) == 1 else None

    def resolve_historical_for_validation(
        self,
        *,
        context_digest: str,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        issued_at: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        context = self._provider._historical_context(context_digest)
        if context is None:
            return None
        return (
            context
            if (
                context.is_active_at(issued_at)
                and context.subject == subject
                and context.evidence_manifest_digest == evidence_manifest_digest
                and context.target_dsm_artifact_id == target_dsm_artifact_id
                and context.target_dsm_observed_sha256 == target_dsm_observed_sha256
                and context.policy_digest == policy_digest
            )
            else None
        )

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        try:
            now = self._provider._clock()
        except Exception:
            return False
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and context.context_digest is not None
            and context.context_digest in snapshot.current_context_digests
            and snapshot.context_records.get(context.context_digest) == context
            and context.is_active_at(now)
        )
