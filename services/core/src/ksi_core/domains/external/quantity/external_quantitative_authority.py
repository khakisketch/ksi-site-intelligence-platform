"""Durable two-stage authority for the external relative-volume path.

Compatibility is the only fact that can exist before an evaluator has created
its idempotent pair decision.  A separate execution snapshot binds that later
decision to explicit Core-owned numeric limits.  Neither record promotes
external evidence to a managed ProcessingJob or a managed processing profile.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    DecisionVerdict,
    ExternalPairUseDecisionV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
    external_volume_zone_snapshot_wire_dict,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.work_area import WorkAreaStatus

from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_evidence_validations import (
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)
from ksi_core.domains.external.quantity.external_relative_volume_authorities import (
    ExternalRelativeVolumeAuthority,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
)
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Principal

_VERSION = 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROFILE = "external-geotiff-profile.v1"
_MAPPING_ACTIVATED = "external-quantitative-mapping-activated"
_MAPPING_REVOKED = "external-quantitative-mapping-revoked"
_EXECUTION_ACTIVATED = "external-quantitative-execution-activated"
_EXECUTION_REVOKED = "external-quantitative-execution-revoked"


class ExternalQuantitativeAuthorityRecoveryError(RuntimeError):
    """The authority journal cannot be replayed as exact, safe history."""


def _digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _event_digest(event: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _utc(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be UTC-aware")


def _wire_time(value: datetime) -> str:
    _utc(value, name="authority time")
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(parsed, name=name)
    return parsed


def _required_digest(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a sha256 digest")
    return value


def _strict_mapping(raw: object, keys: frozenset[str], *, name: str) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != keys or any(type(key) is not str for key in raw):
        raise ValueError(f"{name} has an invalid object shape")
    return raw


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeCatalogAuthorityRecord:
    """Independent approval for one exact quantitative catalog body.

    This is intentionally unrelated to validation-policy approval: it binds
    execution thresholds and actors to the catalog's canonical bytes without
    widening ``PolicyAuthorityRecord`` beyond policy-body authority.
    """

    organization_id: str
    catalog_body_digest: str
    authorized_administration_actor_ids: tuple[str, ...]
    active_from: datetime
    active_until: datetime
    synthetic_test_only: bool
    digest: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id or self.organization_id != self.organization_id.strip():
            raise ValueError("catalog authority requires a trimmed organization")
        _required_digest(self.catalog_body_digest, name="catalog body")
        if (
            not self.authorized_administration_actor_ids
            or len(set(self.authorized_administration_actor_ids))
            != len(self.authorized_administration_actor_ids)
            or any(
                not actor or actor != actor.strip()
                for actor in self.authorized_administration_actor_ids
            )
        ):
            raise ValueError("catalog authority requires unique administration actors")
        _utc(self.active_from, name="catalog authority active_from")
        _utc(self.active_until, name="catalog authority active_until")
        if self.active_from >= self.active_until:
            raise ValueError("catalog authority validity interval must be ordered")
        if type(self.synthetic_test_only) is not bool or self.synthetic_test_only:
            raise ValueError("production catalog authority rejects synthetic records")
        if self.digest is not None and self.digest != self.canonical_digest():
            raise ValueError("catalog authority digest does not match canonical record")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "organizationId": self.organization_id,
            "catalogBodyDigest": self.catalog_body_digest,
            "authorizedAdministrationActorIds": list(self.authorized_administration_actor_ids),
            "activeFrom": _wire_time(self.active_from),
            "activeUntil": _wire_time(self.active_until),
            "syntheticTestOnly": self.synthetic_test_only,
        }

    def canonical_digest(self) -> str:
        return _digest(
            {
                "domain": "ksi.external-quantitative-catalog-authority.v1",
                "authority": self.canonical_payload(),
            }
        )

    def sealed(self) -> ExternalQuantitativeCatalogAuthorityRecord:
        return replace(self, digest=self.canonical_digest())

    def is_sealed(self) -> bool:
        return self.digest is not None and self.digest == self.canonical_digest()

    def is_active_at(self, now: datetime) -> bool:
        _utc(now, name="catalog authority lookup time")
        return self.active_from <= now < self.active_until

    def event_payload(self) -> dict[str, object]:
        """Exact sealed authority snapshot safe to retain in provider receipts."""
        if not self.is_sealed() or self.digest is None:
            raise ValueError("catalog authority record must be sealed before persistence")
        return {"digest": self.digest, **self.canonical_payload()}

    @classmethod
    def from_event_payload(cls, raw: object) -> ExternalQuantitativeCatalogAuthorityRecord:
        payload = _strict_mapping(
            raw,
            frozenset(
                {
                    "digest",
                    "organizationId",
                    "catalogBodyDigest",
                    "authorizedAdministrationActorIds",
                    "activeFrom",
                    "activeUntil",
                    "syntheticTestOnly",
                }
            ),
            name="catalog authority record",
        )
        actors = payload["authorizedAdministrationActorIds"]
        if not isinstance(actors, list) or not all(type(actor) is str for actor in actors):
            raise ValueError("catalog authority administration actors must be a string list")
        if (
            not all(
                type(payload[field]) is str
                for field in (
                    "digest",
                    "organizationId",
                    "catalogBodyDigest",
                    "activeFrom",
                    "activeUntil",
                )
            )
            or type(payload["syntheticTestOnly"]) is not bool
        ):
            raise ValueError("catalog authority record fields are malformed")
        return cls(
            organization_id=cast(str, payload["organizationId"]),
            catalog_body_digest=cast(str, payload["catalogBodyDigest"]),
            authorized_administration_actor_ids=tuple(cast(list[str], actors)),
            active_from=_parse_time(payload["activeFrom"], name="catalog authority activeFrom"),
            active_until=_parse_time(payload["activeUntil"], name="catalog authority activeUntil"),
            synthetic_test_only=payload["syntheticTestOnly"],
            digest=cast(str, payload["digest"]),
        )

    def permits_catalog(
        self,
        *,
        catalog_body_digest: str,
        organization_id: str,
        administration_actor_id: str,
        now: datetime,
    ) -> bool:
        return (
            self.is_sealed()
            and self.is_active_at(now)
            and self.catalog_body_digest == catalog_body_digest
            and self.organization_id == organization_id
            and administration_actor_id in self.authorized_administration_actor_ids
        )


class ExternalQuantitativeCatalogAuthorityPort(Protocol):
    """Resolve an exact current catalog-approval record, or fail closed."""

    def resolve(
        self, authority_record_digest: str, now: datetime
    ) -> ExternalQuantitativeCatalogAuthorityRecord | None: ...


class ExternalQuantitativeCatalogAuthorityCurrentnessPort(Protocol):
    """Retained catalog-authority projection safe to read under Core's guard."""

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator: ...

    def is_current(
        self, authority: ExternalQuantitativeCatalogAuthorityRecord, now: datetime
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeCatalogAuthorityBinding:
    """The current injected catalog approval required for every mapping admission."""

    authority_port: ExternalQuantitativeCatalogAuthorityPort
    catalog_body_digest: str
    organization_id: str
    administration_actor_id: str
    currentness_port: ExternalQuantitativeCatalogAuthorityCurrentnessPort | None = None

    def __post_init__(self) -> None:
        if not callable(getattr(self.authority_port, "resolve", None)):
            raise ValueError("catalog authority binding requires a resolver")
        _required_digest(self.catalog_body_digest, name="catalog body")
        if not self.organization_id or self.organization_id != self.organization_id.strip():
            raise ValueError("catalog authority binding requires a trimmed organization")
        if (
            not self.administration_actor_id
            or self.administration_actor_id != self.administration_actor_id.strip()
        ):
            raise ValueError("catalog authority binding requires an administration actor")
        if self.currentness_port is not None and not callable(
            getattr(self.currentness_port, "is_current", None)
        ):
            raise ValueError("catalog authority currentness binding requires a local checker")

    def resolve_current(
        self, record: ExternalQuantitativeCompatibilityRecord, now: datetime
    ) -> ExternalQuantitativeCatalogAuthorityRecord | None:
        try:
            authority = self.authority_port.resolve(record.execution_policy_ref, now)
            return (
                authority
                if (
                    isinstance(authority, ExternalQuantitativeCatalogAuthorityRecord)
                    and authority.digest == record.execution_policy_ref
                    and authority.permits_catalog(
                        catalog_body_digest=self.catalog_body_digest,
                        organization_id=self.organization_id,
                        administration_actor_id=self.administration_actor_id,
                        now=now,
                    )
                    and record.organization_id == authority.organization_id
                )
                else None
            )
        except Exception:
            return None

    def locally_permits(
        self,
        record: ExternalQuantitativeCompatibilityRecord,
        authority: ExternalQuantitativeCatalogAuthorityRecord,
        now: datetime,
    ) -> bool:
        """Use the coordinator-bound retained projection without authority I/O."""
        currentness = self.currentness_port
        return bool(
            currentness is not None
            and currentness.coordinator is not None
            and currentness.is_current(authority, now)
            and authority.digest == record.execution_policy_ref
            and authority.permits_catalog(
                catalog_body_digest=self.catalog_body_digest,
                organization_id=self.organization_id,
                administration_actor_id=self.administration_actor_id,
                now=now,
            )
            and record.organization_id == authority.organization_id
        )

    def permits(self, record: ExternalQuantitativeCompatibilityRecord, now: datetime) -> bool:
        """Compatibility helper for preflight callers outside a coordinator guard."""
        return self.resolve_current(record, now) is not None


@dataclass(frozen=True, slots=True)
class CompatibilityRuleDescriptorV1:
    """Stable predicates which policy may approve before result facts exist."""

    external_profile: str = _PROFILE
    requires_same_grammar_digest: bool = True
    requires_same_inspector_build_digest: bool = True
    requires_same_observed_crs_digest: bool = True
    requires_same_observed_vertical_reference_digest: bool = True
    requires_independent_measured_checkpoint_per_epoch: bool = True
    requires_ordered_non_overlapping_capture_intervals: bool = True
    requires_exact_work_area_match: bool = True

    def __post_init__(self) -> None:
        if self.external_profile != _PROFILE:
            raise ValueError("compatibility descriptor accepts only external-geotiff-profile.v1")
        if not all(
            type(value) is bool and value
            for value in (
                self.requires_same_grammar_digest,
                self.requires_same_inspector_build_digest,
                self.requires_same_observed_crs_digest,
                self.requires_same_observed_vertical_reference_digest,
                self.requires_independent_measured_checkpoint_per_epoch,
                self.requires_ordered_non_overlapping_capture_intervals,
                self.requires_exact_work_area_match,
            )
        ):
            raise ValueError("external quantitative compatibility predicates must remain required")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "externalProfile": self.external_profile,
            "requiresSameGrammarDigest": self.requires_same_grammar_digest,
            "requiresSameInspectorBuildDigest": self.requires_same_inspector_build_digest,
            "requiresSameObservedCrsDigest": self.requires_same_observed_crs_digest,
            "requiresSameObservedVerticalReferenceDigest": (
                self.requires_same_observed_vertical_reference_digest
            ),
            "requiresIndependentMeasuredCheckpointPerEpoch": (
                self.requires_independent_measured_checkpoint_per_epoch
            ),
            "requiresOrderedNonOverlappingCaptureIntervals": (
                self.requires_ordered_non_overlapping_capture_intervals
            ),
            "requiresExactWorkAreaMatch": self.requires_exact_work_area_match,
        }

    def canonical_digest(self) -> str:
        return _digest(
            {
                "domain": "ksi.external-quantitative-compatibility-rule.v1",
                "rule": self.canonical_payload(),
            }
        )


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeCompatibilityRecord:
    """Pre-decision, immutable evidence compatibility authorization.

    This deliberately excludes decision, actor permission, execution thresholds,
    and resource limits.  Its digest is the only V1 compatibility mapping ID.
    """

    organization_id: str
    site_id: str
    baseline: ExternalVolumeInputBindingV1
    current: ExternalVolumeInputBindingV1
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    validation_policy_digest: str
    external_profile: str
    grammar_digest: str
    inspector_build_digest: str
    evidence_record_digests: tuple[str, ...]
    execution_policy_ref: str
    valid_from: datetime
    valid_until: datetime
    compatibility_rule_descriptor: CompatibilityRuleDescriptorV1 = field(
        default_factory=CompatibilityRuleDescriptorV1
    )
    compatibility_rule_digest: str | None = None
    mapping_record_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id or not self.site_id:
            raise ValueError("compatibility record requires organization and site")
        if self.external_profile != _PROFILE:
            raise ValueError(
                "external quantitative authority accepts only external-geotiff-profile.v1"
            )
        if not isinstance(self.compatibility_rule_descriptor, CompatibilityRuleDescriptorV1):
            raise ValueError("compatibility record requires a stable rule descriptor")
        for name, value in (
            ("validation policy", self.validation_policy_digest),
            ("grammar", self.grammar_digest),
            ("inspector build", self.inspector_build_digest),
            ("execution policy reference", self.execution_policy_ref),
        ):
            _required_digest(value, name=name)
        if not self.evidence_record_digests or len(set(self.evidence_record_digests)) != len(
            self.evidence_record_digests
        ):
            raise ValueError("compatibility record requires unique evidence records")
        for digest in self.evidence_record_digests:
            _required_digest(digest, name="evidence record")
        _utc(self.valid_from, name="compatibility valid_from")
        _utc(self.valid_until, name="compatibility valid_until")
        if self.valid_from >= self.valid_until:
            raise ValueError("compatibility validity interval must be ordered")
        if self.baseline.subject == self.current.subject:
            raise ValueError("compatibility subjects must be distinct")
        if self.baseline.captured_to > self.current.captured_from:
            raise ValueError("compatibility capture intervals must not overlap")
        if (
            self.baseline.subject.organization_id != self.organization_id
            or self.current.subject.organization_id != self.organization_id
            or self.zone_snapshot.organization_id != self.organization_id
            or self.baseline.subject.site_id != self.site_id
            or self.current.subject.site_id != self.site_id
            or self.zone_snapshot.site_id != self.site_id
        ):
            raise ValueError("compatibility participants must share organization and site")
        if self.current.observed_crs_digest != self.baseline.observed_crs_digest:
            raise ValueError("compatibility DSM CRS digests must match")
        if (
            self.baseline.observed_vertical_reference_digest
            != self.current.observed_vertical_reference_digest
            or self.current.observed_vertical_reference_digest
            != self.zone_snapshot.analysis_vertical_reference_digest
            or self.baseline.observed_crs_digest != self.zone_snapshot.observed_crs_digest
        ):
            raise ValueError("compatibility DSM and WorkArea references must match")
        if (
            self.compatibility_rule_digest is not None
            and self.compatibility_rule_digest != self.compatibility_rule_canonical_digest()
        ):
            raise ValueError("compatibility rule digest does not match rule facts")
        if (
            self.mapping_record_digest is not None
            and self.mapping_record_digest != self.canonical_digest()
        ):
            raise ValueError("compatibility mapping record digest does not match canonical record")

    @property
    def mapping_digest(self) -> str | None:
        """Compatibility alias used by existing decision and volume contracts.

        Contract field ``compatibilityMappingDigest`` always names the full
        record digest.  The policy-preauthorized rule digest never leaves this
        authority record as a decision or execution identity.
        """
        return self.mapping_record_digest

    def compatibility_rule_payload(self) -> dict[str, object]:
        """Stable predicates, deliberately excluding every mapping fact."""
        return self.compatibility_rule_descriptor.canonical_payload()

    def compatibility_rule_canonical_digest(self) -> str:
        return self.compatibility_rule_descriptor.canonical_digest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "baseline": self.baseline.model_dump(by_alias=True, mode="json"),
            "current": self.current.model_dump(by_alias=True, mode="json"),
            "zoneSnapshot": external_volume_zone_snapshot_wire_dict(self.zone_snapshot),
            "validationPolicyDigest": self.validation_policy_digest,
            "externalProfile": self.external_profile,
            "grammarDigest": self.grammar_digest,
            "inspectorBuildDigest": self.inspector_build_digest,
            "evidenceRecordDigests": list(self.evidence_record_digests),
            "compatibilityRuleDigest": self.compatibility_rule_digest
            or self.compatibility_rule_canonical_digest(),
            "executionPolicyRef": self.execution_policy_ref,
            "validFrom": _wire_time(self.valid_from),
            "validUntil": _wire_time(self.valid_until),
        }

    def canonical_digest(self) -> str:
        return _digest(
            {
                "domain": "ksi.external-quantitative-compatibility.v1",
                "record": self.canonical_payload(),
            }
        )

    def sealed(self) -> ExternalQuantitativeCompatibilityRecord:
        with_rule = replace(
            self,
            compatibility_rule_digest=self.compatibility_rule_canonical_digest(),
            mapping_record_digest=None,
        )
        return replace(with_rule, mapping_record_digest=with_rule.canonical_digest())

    def is_active_at(self, now: datetime) -> bool:
        _utc(now, name="compatibility lookup time")
        return self.valid_from <= now < self.valid_until

    @classmethod
    def from_event_payload(cls, raw: object) -> ExternalQuantitativeCompatibilityRecord:
        payload = _strict_mapping(
            raw,
            frozenset(
                {
                    "mappingRecordDigest",
                    "organizationId",
                    "siteId",
                    "baseline",
                    "current",
                    "zoneSnapshot",
                    "validationPolicyDigest",
                    "externalProfile",
                    "grammarDigest",
                    "inspectorBuildDigest",
                    "evidenceRecordDigests",
                    "compatibilityRuleDigest",
                    "executionPolicyRef",
                    "validFrom",
                    "validUntil",
                }
            ),
            name="compatibility record",
        )
        evidence = payload["evidenceRecordDigests"]
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError("compatibility evidence records must be a string list")
        record = cls(
            organization_id=str(payload["organizationId"]),
            site_id=str(payload["siteId"]),
            baseline=ExternalVolumeInputBindingV1.model_validate(payload["baseline"]),
            current=ExternalVolumeInputBindingV1.model_validate(payload["current"]),
            zone_snapshot=ExternalVolumeZoneSnapshotV1.model_validate(payload["zoneSnapshot"]),
            validation_policy_digest=str(payload["validationPolicyDigest"]),
            external_profile=str(payload["externalProfile"]),
            grammar_digest=str(payload["grammarDigest"]),
            inspector_build_digest=str(payload["inspectorBuildDigest"]),
            evidence_record_digests=tuple(evidence),
            compatibility_rule_digest=str(payload["compatibilityRuleDigest"]),
            execution_policy_ref=str(payload["executionPolicyRef"]),
            valid_from=_parse_time(payload["validFrom"], name="compatibility validFrom"),
            valid_until=_parse_time(payload["validUntil"], name="compatibility validUntil"),
            mapping_record_digest=str(payload["mappingRecordDigest"]),
        )
        return record


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeExecutionTemplate:
    """Approved stage-two limits supplied by a non-client authority source."""

    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    authorized_actor_ids: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    maximum_zone_cell_count: int
    maximum_zone_area_m2: float

    def __post_init__(self) -> None:
        if self.execution_policy.synthetic_test_only:
            raise ValueError("production quantitative execution template rejects synthetic policy")
        if self.execution_policy.policy_digest is None:
            raise ValueError("execution template requires a sealed policy")
        if not self.authorized_actor_ids:
            raise ValueError("execution template requires authorized actors")
        _utc(self.valid_from, name="execution valid_from")
        _utc(self.valid_until, name="execution valid_until")
        if self.valid_from >= self.valid_until:
            raise ValueError("execution validity interval must be ordered")
        if type(self.maximum_zone_cell_count) is not int or self.maximum_zone_cell_count < 1:
            raise ValueError("execution maximum zone cells must be positive")
        if (
            type(self.maximum_zone_area_m2) is not float
            or self.maximum_zone_area_m2 <= 0
            or self.maximum_zone_area_m2 == float("inf")
            or self.maximum_zone_area_m2 != self.maximum_zone_area_m2
        ):
            raise ValueError("execution maximum zone area must be finite and positive")


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeAuthorityParticipants:
    """The already assembled Core facts required for mapping admission.

    This is deliberately a read-only join.  It does not register evidence,
    issue inspection or checkpoint work, select an arbitrary policy, or repair
    a stale participant.  Missing or substituted participants simply leave a
    mapping unadmitted.
    """

    reconstruction: ExternalReconstructionStore
    inspections: ExternalArtifactInspectionStore
    policy_registry: ExternalValidationPolicyRegistry
    evidence_validations: ExternalEvidenceValidationStore
    work_areas: WorkAreaStore
    catalog_authority: ExternalQuantitativeCatalogAuthorityBinding

    def current_snapshot(
        self, record: ExternalQuantitativeCompatibilityRecord, now: datetime
    ) -> _QuantitativeParticipantSnapshot | None:
        """Resolve source-backed currentness before the coordinator guard.

        Authority-port resolution belongs here.  The returned immutable snapshots
        are compared again from Core-owned projections by ``locally_current``.
        """
        catalog_authority = self.catalog_authority.resolve_current(record, now)
        if catalog_authority is None:
            return None
        selected = self.policy_registry.select_for_use(
            "RELATIVE_VOLUME", (record.baseline.subject, record.current.subject)
        )
        policy = selected.policy
        if (
            selected.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy.policy_digest != record.validation_policy_digest
            or policy.synthetic_test_only
            or policy.grammar_digest != record.grammar_digest
            or policy.parser_build_digest != record.inspector_build_digest
            or policy.resource_envelope is None
            or policy.resource_envelope_digest is None
            or record.compatibility_rule_digest not in policy.compatibility_mapping_digests
        ):
            return None
        if not self._record_facts_match(record, policy):
            return None
        evidence_records: list[tuple[object, object]] = []
        for binding, evidence_digest in zip(
            (record.baseline, record.current), record.evidence_record_digests, strict=True
        ):
            evidence = self.evidence_validations.record_for_current_use(
                evidence_digest,
                subject=binding.subject,
                policy_digest=record.validation_policy_digest,
            )
            if evidence is None or not self._evidence_matches_binding(binding, evidence):
                return None
            evidence_records.append(evidence)
        return _QuantitativeParticipantSnapshot(
            catalog_authority=catalog_authority,
            policy=policy,
            evidence_records=(evidence_records[0], evidence_records[1]),
        )

    def locally_current(
        self,
        record: ExternalQuantitativeCompatibilityRecord,
        snapshot: _QuantitativeParticipantSnapshot,
        now: datetime,
    ) -> bool:
        """Recheck retained currentness while the shared coordinator excludes mutation."""
        if not self.catalog_authority.locally_permits(record, snapshot.catalog_authority, now):
            return False
        if not self.policy_registry.locally_current_use_permitted(
            record.validation_policy_digest,
            use="RELATIVE_VOLUME",
            subjects=(record.baseline.subject, record.current.subject),
            at=now,
        ):
            return False
        selected = self.policy_registry.resolve(record.validation_policy_digest)
        policy = selected.policy
        if (
            selected.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy != snapshot.policy
            or not self._record_facts_match(record, policy)
        ):
            return False
        for binding, evidence_digest, expected in zip(
            (record.baseline, record.current),
            record.evidence_record_digests,
            snapshot.evidence_records,
            strict=True,
        ):
            evidence = self.evidence_validations.record_for_locally_current_use(
                evidence_digest,
                subject=binding.subject,
                policy_digest=record.validation_policy_digest,
            )
            if evidence != expected or not self._evidence_matches_binding(binding, evidence):
                return False
        return True

    def validates(self, record: ExternalQuantitativeCompatibilityRecord, now: datetime) -> bool:
        """Compatibility helper for callers that need the complete two-phase check."""
        snapshot = self.current_snapshot(record, now)
        return snapshot is not None and self.locally_current(record, snapshot, now)

    def _record_facts_match(
        self, record: ExternalQuantitativeCompatibilityRecord, policy: ExternalValidationPolicyV1
    ) -> bool:
        area = self.work_areas.get(record.zone_snapshot.work_area_id)
        if (
            area is None
            or area.status is not WorkAreaStatus.ACTIVE
            or area.site_id != record.site_id
            or area.polygon != record.zone_snapshot.polygon
            or area.crs != record.zone_snapshot.crs
            or record.zone_snapshot.definition_digest
            != record.zone_snapshot.definition_canonical_digest()
        ):
            return False
        if len(record.evidence_record_digests) != 2:
            return False
        for binding in (record.baseline, record.current):
            revision = self.reconstruction.resolve_sealed_subject(binding.subject)
            if revision is None or revision.manifest is None:
                return False
            capture_from = revision.submission.input_declaration.capture_started_at
            capture_to = revision.submission.input_declaration.capture_ended_at
            if capture_from is None or capture_to is None:
                return False
            try:
                _utc(capture_from, name="sealed capture start")
                _utc(capture_to, name="sealed capture end")
            except ValueError:
                return False
            if (
                capture_from > capture_to
                or capture_from != binding.captured_from
                or capture_to != binding.captured_to
            ):
                return False
            entry = next(
                (
                    candidate
                    for candidate in revision.manifest.entries
                    if candidate.artifact_id == binding.dsm_artifact_id
                    and candidate.kind is ProcessingArtifactKind.DSM
                    and "sha256:" + candidate.observed_sha256 == binding.observed_sha256
                    and candidate.observed_size_bytes == binding.observed_size_bytes
                ),
                None,
            )
            if entry is None:
                return False
            report = self.inspections.historical_report(
                binding.subject,
                report_digest=binding.inspection_report_digest,
                policy_digest=record.validation_policy_digest,
            )
            if (
                report is None
                or report.inspector_build_digest != record.inspector_build_digest
                or report.inspection_policy_digest != record.validation_policy_digest
                or any(
                    outcome.outcome is not ArtifactOutcome.MEASURED
                    for outcome in report.measurement_payload.outcomes
                )
            ):
                return False
            measured = next(
                (
                    outcome
                    for outcome in report.measurement_payload.outcomes
                    if outcome.artifact_id == binding.dsm_artifact_id
                    and outcome.observed_sha256 == binding.observed_sha256
                    and outcome.measurements is not None
                ),
                None,
            )
            if (
                measured is None
                or measured.measurements is None
                or measured.measurements.observed_crs_digest != binding.observed_crs_digest
                or measured.measurements.observed_vertical_reference is None
                or measured.measurements.observed_vertical_reference.canonical_digest()
                != binding.observed_vertical_reference_digest
            ):
                return False
        return True

    @staticmethod
    def _evidence_matches_binding(
        binding: ExternalVolumeInputBindingV1, evidence: tuple[object, object] | None
    ) -> bool:
        if evidence is None:
            return False
        evidence_record, context = evidence
        return bool(
            getattr(evidence_record, "measurement_payload", None) is not None
            and getattr(evidence_record, "target_dsm_observed_sha256", None)
            == binding.observed_sha256
            and getattr(context, "target_dsm_artifact_id", None) == binding.dsm_artifact_id
            and getattr(context, "target_dsm_observed_sha256", None) == binding.observed_sha256
            and getattr(context, "synthetic_test_only", None) is False
        )


@dataclass(frozen=True, slots=True)
class _QuantitativeParticipantSnapshot:
    catalog_authority: ExternalQuantitativeCatalogAuthorityRecord
    policy: ExternalValidationPolicyV1
    evidence_records: tuple[tuple[object, object], tuple[object, object]]


class _DecisionResolver(Protocol):
    def __call__(
        self,
        decision_id: str,
        principal: Principal,
        current_work_order_id: str,
    ) -> Mapping[str, object] | ExternalPairUseDecisionV1 | None: ...


class _ExecutionTemplateResolver(Protocol):
    def __call__(
        self, record: ExternalQuantitativeCompatibilityRecord, now: datetime
    ) -> ExternalQuantitativeExecutionTemplate | None: ...


@dataclass(frozen=True, slots=True)
class _MappingState:
    record: ExternalQuantitativeCompatibilityRecord
    activated_at: datetime
    revoked_at: datetime | None = None

    def active_at(self, at: datetime) -> bool:
        return (
            self.activated_at <= at
            and self.record.is_active_at(at)
            and (self.revoked_at is None or at < self.revoked_at)
        )


@dataclass(frozen=True, slots=True)
class _ExecutionState:
    authority: ExternalRelativeVolumeExecutionAuthority
    mapping_digest: str
    activated_at: datetime
    revoked_at: datetime | None = None

    def active_at(self, at: datetime) -> bool:
        return (
            self.activated_at <= at
            and self.authority.is_current_at(at)
            and (self.revoked_at is None or at < self.revoked_at)
        )


def _execution_identity(authority: ExternalRelativeVolumeExecutionAuthority) -> str:
    payload = authority.snapshot_payload()
    payload.pop("historicalAuthorityDigest")
    return _digest({"domain": "ksi.external-quantitative-execution.v1", "snapshot": payload})


def _decision_precedes_activation(decided_at: object, activated_at: datetime) -> bool:
    """Reject malformed or non-UTC retained decision chronology fail closed."""
    if not isinstance(decided_at, datetime):
        return False
    try:
        _utc(decided_at, name="decision decided_at")
    except ValueError:
        return False
    return decided_at <= activated_at


class ExternalQuantitativeAuthorityCatalog:
    """Append-only mapping and post-decision execution lifecycle.

    The two callback seams are intentional Core-internal dependencies.  They
    are never HTTP configuration: a missing validator, execution policy, or
    decision resolver makes new authority unavailable.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        currentness_coordinator: ExternalAuthorityCurrentnessCoordinator,
        participants: ExternalQuantitativeAuthorityParticipants | None = None,
        mapping_admission_validator: Callable[
            [ExternalQuantitativeCompatibilityRecord, datetime], bool
        ]
        | None = None,
        execution_template_resolver: _ExecutionTemplateResolver | None = None,
        decision_resolver: _DecisionResolver | None = None,
    ) -> None:
        self.currentness_coordinator = currentness_coordinator
        self._journal = journal
        if participants is not None and mapping_admission_validator is not None:
            raise ValueError(
                "quantitative authority accepts either participants or a test validator"
            )
        if participants is not None and (
            participants.catalog_authority.currentness_port is None
            or (
                participants.catalog_authority.currentness_port.coordinator
                is not currentness_coordinator
            )
        ):
            raise ValueError(
                "quantitative authority catalog currentness must share the Core coordinator"
            )
        self._participants = participants
        self._mapping_admission_validator = (
            participants.validates if participants is not None else mapping_admission_validator
        )
        self._execution_template_resolver = execution_template_resolver
        self._decision_resolver = decision_resolver
        self._lock = threading.RLock()
        self._mappings: dict[str, _MappingState] = {}
        self._current_participant_snapshots: dict[str, _QuantitativeParticipantSnapshot] = {}
        self._executions: dict[str, _ExecutionState] = {}
        try:
            self._replay()
        except BaseException:
            journal.close()
            raise

    def bind_decision_resolver(self, resolver: _DecisionResolver) -> None:
        """Bind the existing durable decision projection after it is assembled."""
        if not callable(resolver):
            raise ValueError("decision resolver must be callable")
        with self._lock:
            self._decision_resolver = resolver

    def bind_decision_store(self, decisions: object) -> None:
        """Bind the assembled decision ledger and verify retained execution proof."""
        current = getattr(decisions, "resolve_current_pair_for_issue", None)
        historical = getattr(decisions, "resolve_historical_pair", None)
        if not callable(current) or not callable(historical):
            raise ValueError("decision store lacks quantitative authority joins")
        with self._lock:
            for state in self._executions.values():
                authority = state.authority
                decision = historical(
                    organization_id=authority.organization_id,
                    site_id=authority.site_id,
                    decision_id=authority.decision_id,
                    decision_digest=authority.decision_digest,
                )
                if not self._execution_decision_matches(state, decision):
                    raise ExternalQuantitativeAuthorityRecoveryError(
                        "execution snapshot has no exact durable decision"
                    )
            self._decision_resolver = lambda decision_id, principal, work_order_id: current(
                decision_id,
                principal=principal,
                current_work_order_id=work_order_id,
            )

    def _append_apply(self, event: dict[str, object]) -> None:
        event["eventDigest"] = _event_digest(event)
        self._journal.append(event)
        self._apply(event)

    def _current_participants(
        self, record: ExternalQuantitativeCompatibilityRecord, now: datetime
    ) -> _QuantitativeParticipantSnapshot | bool | None:
        participants = self._participants
        if participants is not None:
            return participants.current_snapshot(record, now)
        validator = self._mapping_admission_validator
        return True if validator is not None and validator(record, now) else None

    def _participants_remain_current(
        self,
        record: ExternalQuantitativeCompatibilityRecord,
        snapshot: _QuantitativeParticipantSnapshot | bool,
        now: datetime,
    ) -> bool:
        participants = self._participants
        return (
            bool(snapshot)
            if participants is None
            else (
                isinstance(snapshot, _QuantitativeParticipantSnapshot)
                and participants.locally_current(record, snapshot, now)
            )
        )

    def admit_mapping(
        self, record: ExternalQuantitativeCompatibilityRecord, *, actor: str, now: datetime
    ) -> ExternalQuantitativeCompatibilityRecord | None:
        """Append a verified compatibility record before any pair decision exists."""
        _utc(now, name="mapping activation time")
        if not actor or actor != actor.strip():
            raise ValueError("mapping activation actor is invalid")
        sealed = record.sealed()
        if not sealed.is_active_at(now):
            return None
        snapshot = self._current_participants(sealed, now)
        if snapshot is None:
            return None
        assert sealed.mapping_digest is not None
        with self.currentness_coordinator.mutation(), self._lock:
            prior_mapping = self._mappings.get(sealed.mapping_digest)
            if prior_mapping is not None:
                return sealed if prior_mapping.record == sealed else None
            if not self._participants_remain_current(sealed, snapshot, now):
                return None
            event: dict[str, object] = {
                "kind": _MAPPING_ACTIVATED,
                "version": _VERSION,
                "mapping": {
                    "mappingRecordDigest": sealed.mapping_digest,
                    **sealed.canonical_payload(),
                },
                "activatedBy": actor,
                "activatedAt": _wire_time(now),
            }
            try:
                self._append_apply(event)
            except JournalSealedError:
                return None
        return sealed

    def revoke_mapping(self, mapping_digest: str, *, actor: str, now: datetime) -> bool:
        _required_digest(mapping_digest, name="mapping")
        _utc(now, name="mapping revocation time")
        if not actor or actor != actor.strip():
            raise ValueError("mapping revocation actor is invalid")
        with self.currentness_coordinator.mutation(), self._lock:
            state = self._mappings.get(mapping_digest)
            if state is None or now < state.activated_at:
                return False
            if state.revoked_at is not None:
                return state.revoked_at == now
            event: dict[str, object] = {
                "kind": _MAPPING_REVOKED,
                "version": _VERSION,
                "mappingDigest": mapping_digest,
                "revokedBy": actor,
                "revokedAt": _wire_time(now),
            }
            try:
                self._append_apply(event)
            except JournalSealedError:
                return False
        return True

    def resolve_for_use(
        self,
        *,
        baseline: SealedExternalSubjectV1,
        current: SealedExternalSubjectV1,
        zone_id: str,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> ExternalRelativeVolumeAuthority | None:
        _utc(now, name="mapping use time")
        policy_digest = getattr(policy, "policy_digest", None)
        if not isinstance(policy_digest, str):
            return None
        with self._lock:
            matches = tuple(
                state
                for state in self._mappings.values()
                if state.active_at(now)
                and state.record.baseline.subject == baseline
                and state.record.current.subject == current
                and state.record.zone_snapshot.work_area_id == zone_id
                and state.record.validation_policy_digest == policy_digest
            )
        if len(matches) != 1:
            return None
        record = matches[0].record
        snapshot = self._current_participants(record, now)
        if snapshot is None:
            return None
        with self.currentness_coordinator.guarded_read(), self._lock:
            state = self._mappings.get(record.mapping_digest or "")
            if (
                state is None
                or state.record != record
                or not state.active_at(now)
                or not self._participants_remain_current(record, snapshot, now)
            ):
                return None
            if isinstance(snapshot, _QuantitativeParticipantSnapshot):
                assert record.mapping_digest is not None
                self._current_participant_snapshots[record.mapping_digest] = snapshot
        assert record.mapping_digest is not None
        return ExternalRelativeVolumeAuthority(
            zone=record.zone_snapshot.to_zone_reference(),
            compatibility_mapping_digest=record.mapping_digest,
            historical_authority_digest=record.mapping_digest,
            synthetic_test_only=False,
        )

    def is_current_for_use(
        self, authority: ExternalRelativeVolumeAuthority, *, now: datetime
    ) -> bool:
        _utc(now, name="mapping currentness time")
        with self._lock:
            state = self._mappings.get(authority.compatibility_mapping_digest)
            record = state.record if state is not None else None
            snapshot = self._current_participant_snapshots.get(
                authority.compatibility_mapping_digest
            )
        if record is None:
            return False
        # ``resolve_for_use`` completed the source-backed preflight before the
        # caller entered its coordinator guard.  This final check touches only
        # retained Core projections and the bound local catalog projection.
        with self.currentness_coordinator.guarded_read(), self._lock:
            state = self._mappings.get(authority.compatibility_mapping_digest)
            return bool(
                state
                and state.record == record
                and state.active_at(now)
                and authority.historical_authority_digest == authority.compatibility_mapping_digest
                and authority.synthetic_test_only is False
                and authority.zone == record.zone_snapshot.to_zone_reference()
                and (
                    self._participants is None
                    or (
                        isinstance(snapshot, _QuantitativeParticipantSnapshot)
                        and self._participants.locally_current(record, snapshot, now)
                    )
                )
            )

    def resolve_historical_for_decision(
        self, decision: ExternalPairUseDecisionV1
    ) -> ExternalRelativeVolumeAuthority | None:
        if (
            decision.use != "RELATIVE_VOLUME"
            or decision.compatibility_mapping_digest is None
            or decision.zone is None
            or decision.policy_digest is None
        ):
            return None
        with self._lock:
            state = self._mappings.get(decision.compatibility_mapping_digest)
            if state is None or not state.active_at(decision.decided_at):
                return None
            record = state.record
            if (
                record.baseline.subject != decision.baseline_subject
                or record.current.subject != decision.current_subject
                or record.validation_policy_digest != decision.policy_digest
                or record.zone_snapshot.to_zone_reference() != decision.zone
            ):
                return None
        return ExternalRelativeVolumeAuthority(
            zone=record.zone_snapshot.to_zone_reference(),
            compatibility_mapping_digest=decision.compatibility_mapping_digest,
            historical_authority_digest=decision.compatibility_mapping_digest,
            synthetic_test_only=False,
        )

    def _decision_binding(
        self,
        decision_ref: str,
        *,
        principal: Principal,
        current_work_order_id: str,
    ) -> Mapping[str, object] | None:
        resolver = self._decision_resolver
        if resolver is None:
            return None
        resolved = resolver(decision_ref, principal, current_work_order_id)
        if isinstance(resolved, ExternalPairUseDecisionV1):
            try:
                _utc(resolved.decided_at, name="decision decided_at")
            except ValueError:
                return None
            if (
                resolved.decision_digest is None
                or resolved.zone is None
                or resolved.verdict is not DecisionVerdict.ELIGIBLE
                or resolved.use != "RELATIVE_VOLUME"
            ):
                return None
            return {
                "decisionId": resolved.decision_id,
                "decisionDigest": resolved.decision_digest,
                "organizationId": resolved.current_subject.organization_id,
                "siteId": resolved.current_subject.site_id,
                "baseline": resolved.baseline_subject,
                "current": resolved.current_subject,
                "zoneDigest": resolved.zone.definition_digest,
                "policyDigest": resolved.policy_digest,
                "compatibilityMappingDigest": resolved.compatibility_mapping_digest,
                "decisionUse": resolved.use,
                "decisionVerdict": resolved.verdict.value,
                "decidedAt": resolved.decided_at,
            }
        return resolved

    @staticmethod
    def _execution_decision_matches(
        state: _ExecutionState, decision: ExternalPairUseDecisionV1 | None
    ) -> bool:
        authority = state.authority
        return bool(
            decision
            and decision.decision_id == authority.decision_id
            and decision.decision_digest == authority.decision_digest
            and decision.canonical_digest() == authority.decision_digest
            and decision.verdict is DecisionVerdict.ELIGIBLE
            and decision.use == "RELATIVE_VOLUME"
            and decision.baseline_subject == authority.baseline.subject
            and decision.current_subject == authority.current.subject
            and decision.zone == authority.zone_snapshot.to_zone_reference()
            and decision.policy_digest == authority.validation_policy_digest
            and decision.compatibility_mapping_digest == state.mapping_digest
            and _decision_precedes_activation(decision.decided_at, state.activated_at)
        )

    def activate_execution(
        self,
        *,
        decision_ref: str,
        principal: Principal,
        current_work_order_id: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        """Snapshot approved limits only after the durable pair decision exists."""
        _utc(now, name="execution activation time")
        if not decision_ref or not current_work_order_id:
            raise ValueError("execution activation identifiers are required")
        binding = self._decision_binding(
            decision_ref,
            principal=principal,
            current_work_order_id=current_work_order_id,
        )
        if binding is None:
            return None
        required = {
            "decisionId",
            "decisionDigest",
            "organizationId",
            "siteId",
            "baseline",
            "current",
            "zoneDigest",
            "policyDigest",
            "compatibilityMappingDigest",
            "decisionUse",
            "decisionVerdict",
            "decidedAt",
        }
        if set(binding) != required:
            return None
        if (
            binding["decisionUse"] != "RELATIVE_VOLUME"
            or binding["decisionVerdict"] != DecisionVerdict.ELIGIBLE.value
        ):
            return None
        try:
            decision_digest = _required_digest(binding["decisionDigest"], name="decision")
            mapping_digest = _required_digest(
                binding["compatibilityMappingDigest"], name="compatibility mapping"
            )
            decided_at = binding["decidedAt"]
            if not isinstance(decided_at, datetime):
                return None
            _utc(decided_at, name="decision decidedAt")
        except ValueError:
            return None
        if decided_at > now:
            return None
        with self._lock:
            mapping_state = self._mappings.get(mapping_digest)
            record = mapping_state.record if mapping_state is not None else None
        if record is None:
            return None
        snapshot = self._current_participants(record, now)
        if snapshot is None:
            return None
        resolver = self._execution_template_resolver
        template = resolver(record, now) if resolver is not None else None
        if template is None or not (template.valid_from <= now < template.valid_until):
            return None
        with self.currentness_coordinator.mutation(), self._lock:
            state = self._mappings.get(mapping_digest)
            if (
                state is None
                or state.record != record
                or not state.active_at(now)
                or not self._participants_remain_current(record, snapshot, now)
            ):
                return None
            if (
                binding["decisionId"] != decision_ref
                or binding["organizationId"] != record.organization_id
                or binding["siteId"] != record.site_id
                or binding["baseline"] != record.baseline.subject
                or binding["current"] != record.current.subject
                or binding["zoneDigest"] != record.zone_snapshot.definition_digest
                or binding["policyDigest"] != record.validation_policy_digest
                or current_work_order_id != record.current.subject.work_order_id
            ):
                return None
            if principal.principal_id not in template.authorized_actor_ids:
                return None
            policy = template.execution_policy
            if (
                policy.authority_record_digest != record.execution_policy_ref
                or policy.synthetic_test_only
            ):
                return None
            provisional = ExternalRelativeVolumeExecutionAuthority(
                organization_id=record.organization_id,
                site_id=record.site_id,
                current_work_order_id=current_work_order_id,
                decision_id=decision_ref,
                decision_digest=decision_digest,
                compatibility_mapping_digest=mapping_digest,
                baseline=record.baseline,
                current=record.current,
                evidence_record_digests=record.evidence_record_digests,
                validation_policy_digest=record.validation_policy_digest,
                zone_snapshot=record.zone_snapshot,
                execution_policy=policy,
                authorized_actor_ids=template.authorized_actor_ids,
                valid_from=template.valid_from,
                valid_until=template.valid_until,
                historical_authority_digest=_digest({"provisional": "external-quantitative"}),
                baseline_rmse_m=None,
                current_rmse_m=None,
                maximum_zone_cell_count=template.maximum_zone_cell_count,
                maximum_zone_area_m2=template.maximum_zone_area_m2,
                synthetic_test_only=False,
            )
            authority = replace(
                provisional, historical_authority_digest=_execution_identity(provisional)
            )
            prior = self._executions.get(authority.historical_authority_digest)
            if prior is not None:
                return authority if prior.authority == authority else None
            event: dict[str, object] = {
                "kind": _EXECUTION_ACTIVATED,
                "version": _VERSION,
                "mappingDigest": mapping_digest,
                "authority": authority.snapshot_payload(),
                "activatedBy": principal.principal_id,
                "activatedAt": _wire_time(now),
            }
            try:
                self._append_apply(event)
            except JournalSealedError:
                return None
        return authority

    def revoke_execution(self, authority_digest: str, *, actor: str, now: datetime) -> bool:
        _required_digest(authority_digest, name="execution authority")
        _utc(now, name="execution revocation time")
        if not actor or actor != actor.strip():
            raise ValueError("execution revocation actor is invalid")
        with self.currentness_coordinator.mutation(), self._lock:
            state = self._executions.get(authority_digest)
            if state is None or now < state.activated_at:
                return False
            if state.revoked_at is not None:
                return state.revoked_at == now
            event: dict[str, object] = {
                "kind": _EXECUTION_REVOKED,
                "version": _VERSION,
                "historicalAuthorityDigest": authority_digest,
                "revokedBy": actor,
                "revokedAt": _wire_time(now),
            }
            try:
                self._append_apply(event)
            except JournalSealedError:
                return False
        return True

    def resolve_for_issue(
        self,
        *,
        principal: Principal,
        current_work_order_id: str,
        decision_ref: str,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        _utc(now, name="execution issue time")
        binding = self._decision_binding(
            decision_ref,
            principal=principal,
            current_work_order_id=current_work_order_id,
        )
        required = {
            "decisionId",
            "decisionDigest",
            "organizationId",
            "siteId",
            "baseline",
            "current",
            "zoneDigest",
            "policyDigest",
            "compatibilityMappingDigest",
            "decisionUse",
            "decisionVerdict",
            "decidedAt",
        }
        if binding is None or set(binding) != required:
            return None
        if (
            binding["decisionUse"] != "RELATIVE_VOLUME"
            or binding["decisionVerdict"] != DecisionVerdict.ELIGIBLE.value
        ):
            return None
        try:
            decision_digest = _required_digest(binding["decisionDigest"], name="decision")
            mapping_digest = _required_digest(
                binding["compatibilityMappingDigest"], name="compatibility mapping"
            )
            zone_digest = _required_digest(binding["zoneDigest"], name="zone")
            policy_digest = _required_digest(binding["policyDigest"], name="validation policy")
            decided_at = binding["decidedAt"]
            if not isinstance(decided_at, datetime):
                return None
            _utc(decided_at, name="decision decidedAt")
        except ValueError:
            return None
        if decided_at > now:
            return None
        with self._lock:
            matches = tuple(
                state
                for state in self._executions.values()
                if state.active_at(now)
                and state.mapping_digest == mapping_digest
                and self._mapping_active(mapping_digest, now)
                and state.authority.organization_id == principal.organization_id
                and state.authority.current_work_order_id == current_work_order_id
                and state.authority.decision_id == decision_ref
                and state.authority.decision_digest == decision_digest
                and binding["decisionId"] == decision_ref
                and binding["organizationId"] == state.authority.organization_id
                and binding["siteId"] == state.authority.site_id
                and binding["baseline"] == state.authority.baseline.subject
                and binding["current"] == state.authority.current.subject
                and zone_digest == state.authority.zone_snapshot.definition_digest
                and policy_digest == state.authority.validation_policy_digest
                and principal.principal_id in state.authority.authorized_actor_ids
            )
            if len(matches) != 1:
                return None
            state = matches[0]
            mapping_state = self._mappings.get(state.mapping_digest)
            record = mapping_state.record if mapping_state is not None else None
        if record is None:
            return None
        snapshot = self._current_participants(record, now)
        if snapshot is None:
            return None
        with self.currentness_coordinator.guarded_read(), self._lock:
            current_mapping = self._mappings.get(state.mapping_digest)
            current_execution = self._executions.get(state.authority.historical_authority_digest)
            if (
                current_mapping is None
                or current_mapping.record != record
                or not current_mapping.active_at(now)
                or current_execution != state
                or not current_execution.active_at(now)
                or not self._participants_remain_current(record, snapshot, now)
            ):
                return None
            if isinstance(snapshot, _QuantitativeParticipantSnapshot):
                assert record.mapping_digest is not None
                self._current_participant_snapshots[record.mapping_digest] = snapshot
            return state.authority

    @contextmanager
    def guard_current(
        self,
        *,
        authority: ExternalRelativeVolumeExecutionAuthority,
        principal: Principal,
        now: datetime,
    ) -> Iterator[ExternalRelativeVolumeExecutionAuthority | None]:
        with self._lock:
            current = self._executions.get(authority.historical_authority_digest)
            mapping = self._mappings.get(current.mapping_digest) if current is not None else None
            snapshot = self._current_participant_snapshots.get(
                current.mapping_digest if current is not None else ""
            )
            if (
                current is None
                or current.authority != authority
                or not current.active_at(now)
                or not self._mapping_active(current.mapping_digest, now)
                or principal.organization_id != authority.organization_id
                or principal.principal_id not in authority.authorized_actor_ids
                or (
                    self._participants is not None
                    and (
                        mapping is None
                        or not isinstance(snapshot, _QuantitativeParticipantSnapshot)
                        or not self._participants.locally_current(mapping.record, snapshot, now)
                    )
                )
            ):
                yield None
                return
            yield authority

    def resolve_historical(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        issued_at: datetime,
        now: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        del now
        _utc(issued_at, name="historical issue time")
        with self._lock:
            state = self._executions.get(historical_authority_digest)
            if (
                state is None
                or not state.active_at(issued_at)
                or not self._mapping_active(state.mapping_digest, issued_at)
                or state.authority.decision_id != decision_id
                or state.authority.decision_digest != decision_digest
            ):
                return None
            return state.authority

    def resolve_historical_for_use(
        self,
        *,
        historical_authority_digest: str,
        decision_id: str,
        decision_digest: str,
        evaluated_at: datetime,
    ) -> ExternalRelativeVolumeExecutionAuthority | None:
        return self.resolve_historical(
            historical_authority_digest=historical_authority_digest,
            decision_id=decision_id,
            decision_digest=decision_digest,
            issued_at=evaluated_at,
            now=evaluated_at,
        )

    def _mapping_active(self, mapping_digest: str, at: datetime) -> bool:
        state = self._mappings.get(mapping_digest)
        return state is not None and state.active_at(at)

    def _replay(self) -> None:
        for event in self._journal.replay():
            self._apply(event, recovery=True)

    def _apply(self, event: Mapping[str, object], *, recovery: bool = False) -> None:
        try:
            if event.get("eventDigest") != _event_digest(event):
                raise ValueError("event digest mismatch")
            if event.get("version") != _VERSION:
                raise ValueError("event version mismatch")
            kind = event.get("kind")
            if kind == _MAPPING_ACTIVATED:
                expected = {
                    "kind",
                    "version",
                    "mapping",
                    "activatedBy",
                    "activatedAt",
                    "eventDigest",
                }
                if set(event) != expected or not isinstance(event["activatedBy"], str):
                    raise ValueError("mapping activation shape is invalid")
                record = ExternalQuantitativeCompatibilityRecord.from_event_payload(
                    event["mapping"]
                )
                assert record.mapping_digest is not None
                activated_at = _parse_time(event["activatedAt"], name="mapping activatedAt")
                if not record.is_active_at(activated_at):
                    raise ValueError("mapping activation lies outside validity")
                prior = self._mappings.get(record.mapping_digest)
                if prior is not None and prior.record != record:
                    raise ValueError("mapping identity conflicts")
                if prior is None:
                    self._mappings[record.mapping_digest] = _MappingState(record, activated_at)
            elif kind == _MAPPING_REVOKED:
                expected = {
                    "kind",
                    "version",
                    "mappingDigest",
                    "revokedBy",
                    "revokedAt",
                    "eventDigest",
                }
                if set(event) != expected or not isinstance(event["revokedBy"], str):
                    raise ValueError("mapping revocation shape is invalid")
                mapping_digest = _required_digest(event["mappingDigest"], name="mapping")
                revoked_at = _parse_time(event["revokedAt"], name="mapping revokedAt")
                state = self._mappings.get(mapping_digest)
                if state is None or revoked_at < state.activated_at:
                    raise ValueError("mapping revoked before activation")
                if state.revoked_at is not None and state.revoked_at != revoked_at:
                    raise ValueError("mapping has conflicting revocation")
                self._mappings[mapping_digest] = replace(state, revoked_at=revoked_at)
            elif kind == _EXECUTION_ACTIVATED:
                expected = {
                    "kind",
                    "version",
                    "mappingDigest",
                    "authority",
                    "activatedBy",
                    "activatedAt",
                    "eventDigest",
                }
                if set(event) != expected or not isinstance(event["activatedBy"], str):
                    raise ValueError("execution activation shape is invalid")
                mapping_digest = _required_digest(event["mappingDigest"], name="mapping")
                activated_at = _parse_time(event["activatedAt"], name="execution activatedAt")
                mapping_state = self._mappings.get(mapping_digest)
                if mapping_state is None or not mapping_state.active_at(activated_at):
                    raise ValueError("execution activated without active mapping")
                authority_raw = event["authority"]
                if type(authority_raw) is not dict:
                    raise ValueError("execution authority shape is invalid")
                authority = ExternalRelativeVolumeExecutionAuthority.from_snapshot(
                    cast(dict[str, Any], authority_raw)
                )
                if (
                    authority.compatibility_mapping_digest != mapping_digest
                    or authority.historical_authority_digest != _execution_identity(authority)
                    or authority.organization_id != mapping_state.record.organization_id
                    or authority.site_id != mapping_state.record.site_id
                    or authority.baseline != mapping_state.record.baseline
                    or authority.current != mapping_state.record.current
                    or authority.validation_policy_digest
                    != mapping_state.record.validation_policy_digest
                    or authority.zone_snapshot != mapping_state.record.zone_snapshot
                    or authority.evidence_record_digests
                    != mapping_state.record.evidence_record_digests
                    or authority.execution_policy.authority_record_digest
                    != mapping_state.record.execution_policy_ref
                    or authority.synthetic_test_only
                    or not authority.is_current_at(activated_at)
                ):
                    raise ValueError("execution snapshot does not bind mapping")
                prior_execution = self._executions.get(authority.historical_authority_digest)
                if prior_execution is not None and prior_execution.authority != authority:
                    raise ValueError("execution authority identity conflicts")
                if prior_execution is None:
                    self._executions[authority.historical_authority_digest] = _ExecutionState(
                        authority, mapping_digest, activated_at
                    )
            elif kind == _EXECUTION_REVOKED:
                expected = {
                    "kind",
                    "version",
                    "historicalAuthorityDigest",
                    "revokedBy",
                    "revokedAt",
                    "eventDigest",
                }
                if set(event) != expected or not isinstance(event["revokedBy"], str):
                    raise ValueError("execution revocation shape is invalid")
                digest = _required_digest(
                    event["historicalAuthorityDigest"], name="execution authority"
                )
                revoked_at = _parse_time(event["revokedAt"], name="execution revokedAt")
                execution_state = self._executions.get(digest)
                if execution_state is None or revoked_at < execution_state.activated_at:
                    raise ValueError("execution revoked before activation")
                if (
                    execution_state.revoked_at is not None
                    and execution_state.revoked_at != revoked_at
                ):
                    raise ValueError("execution has conflicting revocation")
                self._executions[digest] = replace(execution_state, revoked_at=revoked_at)
            else:
                raise ValueError("unknown quantitative authority event")
        except (KeyError, TypeError, ValueError) as exc:
            if recovery:
                raise ExternalQuantitativeAuthorityRecoveryError(
                    "external quantitative authority journal is malformed"
                ) from exc
            raise


__all__ = [
    "ExternalQuantitativeAuthorityCatalog",
    "ExternalQuantitativeAuthorityParticipants",
    "ExternalQuantitativeAuthorityRecoveryError",
    "ExternalQuantitativeCatalogAuthorityBinding",
    "ExternalQuantitativeCatalogAuthorityPort",
    "ExternalQuantitativeCatalogAuthorityRecord",
    "CompatibilityRuleDescriptorV1",
    "ExternalQuantitativeCompatibilityRecord",
    "ExternalQuantitativeExecutionTemplate",
]
