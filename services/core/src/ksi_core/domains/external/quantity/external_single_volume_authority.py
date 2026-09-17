"""Pre-decision compatibility authorization for one DSM epoch and one zone."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
    external_volume_zone_snapshot_wire_dict,
)

from ksi_core.domains.external.quantity.external_quantitative_common import (
    _PROFILE,
    _digest,
    _parse_time,
    _required_digest,
    _strict_mapping,
    _utc,
    _wire_time,
)


@dataclass(frozen=True, slots=True)
class SingleVolumeCompatibilityRuleDescriptorV1:
    """Stable predicates a policy may pre-approve for single-epoch volume."""

    external_profile: str = _PROFILE
    requires_same_grammar_digest: bool = True
    requires_same_inspector_build_digest: bool = True
    requires_independent_measured_checkpoint: bool = True
    requires_exact_work_area_match: bool = True
    base_surface_method: str = "BOUNDARY_LINEAR_INTERPOLATION_V1"

    def __post_init__(self) -> None:
        if self.external_profile != _PROFILE:
            raise ValueError("single-volume descriptor accepts only external-geotiff-profile.v1")
        if not all(
            type(value) is bool and value
            for value in (
                self.requires_same_grammar_digest,
                self.requires_same_inspector_build_digest,
                self.requires_independent_measured_checkpoint,
                self.requires_exact_work_area_match,
            )
        ):
            raise ValueError("single-volume compatibility predicates must remain required")
        if self.base_surface_method != "BOUNDARY_LINEAR_INTERPOLATION_V1":
            raise ValueError("single-volume base surface method is fixed in V1")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "externalProfile": self.external_profile,
            "requiresSameGrammarDigest": self.requires_same_grammar_digest,
            "requiresSameInspectorBuildDigest": self.requires_same_inspector_build_digest,
            "requiresIndependentMeasuredCheckpoint": self.requires_independent_measured_checkpoint,
            "requiresExactWorkAreaMatch": self.requires_exact_work_area_match,
            "baseSurfaceMethod": self.base_surface_method,
        }

    def canonical_digest(self) -> str:
        return _digest(
            {
                "domain": "ksi.external-single-volume-compatibility-rule.v1",
                "rule": self.canonical_payload(),
            }
        )


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeCompatibilityRecord:
    """Immutable single-epoch compatibility authorization; its digest is the mapping ID."""

    organization_id: str
    site_id: str
    target: ExternalVolumeInputBindingV1
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    validation_policy_digest: str
    external_profile: str
    grammar_digest: str
    inspector_build_digest: str
    evidence_record_digests: tuple[str, ...]
    execution_policy_ref: str
    valid_from: datetime
    valid_until: datetime
    compatibility_rule_descriptor: SingleVolumeCompatibilityRuleDescriptorV1 = field(
        default_factory=SingleVolumeCompatibilityRuleDescriptorV1
    )
    compatibility_rule_digest: str | None = None
    mapping_record_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id or not self.site_id:
            raise ValueError("single-volume record requires organization and site")
        if self.external_profile != _PROFILE:
            raise ValueError("single-volume authority accepts only external-geotiff-profile.v1")
        for name, value in (
            ("validation policy", self.validation_policy_digest),
            ("grammar", self.grammar_digest),
            ("inspector build", self.inspector_build_digest),
            ("execution policy reference", self.execution_policy_ref),
        ):
            _required_digest(value, name=name)
        if len(self.evidence_record_digests) != 1:
            raise ValueError("single-volume record requires exactly one evidence record")
        _required_digest(self.evidence_record_digests[0], name="evidence record")
        _utc(self.valid_from, name="single-volume valid_from")
        _utc(self.valid_until, name="single-volume valid_until")
        if self.valid_from >= self.valid_until:
            raise ValueError("single-volume validity interval must be ordered")
        if (
            self.target.subject.organization_id != self.organization_id
            or self.zone_snapshot.organization_id != self.organization_id
            or self.target.subject.site_id != self.site_id
            or self.zone_snapshot.site_id != self.site_id
        ):
            raise ValueError("single-volume participants must share organization and site")
        if (
            self.target.observed_crs_digest != self.zone_snapshot.observed_crs_digest
            or self.target.observed_vertical_reference_digest
            != self.zone_snapshot.analysis_vertical_reference_digest
        ):
            raise ValueError("single-volume DSM and WorkArea references must match")
        if (
            self.compatibility_rule_digest is not None
            and self.compatibility_rule_digest
            != self.compatibility_rule_descriptor.canonical_digest()
        ):
            raise ValueError("single-volume rule digest does not match rule facts")
        if (
            self.mapping_record_digest is not None
            and self.mapping_record_digest != self.canonical_digest()
        ):
            raise ValueError("single-volume mapping record digest does not match canonical record")

    @property
    def mapping_digest(self) -> str | None:
        return self.mapping_record_digest

    def compatibility_rule_canonical_digest(self) -> str:
        return self.compatibility_rule_descriptor.canonical_digest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "target": self.target.model_dump(by_alias=True, mode="json"),
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
                "domain": "ksi.external-single-volume-compatibility.v1",
                "record": self.canonical_payload(),
            }
        )

    def sealed(self) -> ExternalSingleVolumeCompatibilityRecord:
        with_rule = replace(
            self,
            compatibility_rule_digest=self.compatibility_rule_canonical_digest(),
            mapping_record_digest=None,
        )
        return replace(with_rule, mapping_record_digest=with_rule.canonical_digest())

    def is_active_at(self, now: datetime) -> bool:
        _utc(now, name="single-volume lookup time")
        return self.valid_from <= now < self.valid_until

    @classmethod
    def from_event_payload(cls, raw: object) -> ExternalSingleVolumeCompatibilityRecord:
        payload = _strict_mapping(
            raw,
            frozenset(
                {
                    "mappingRecordDigest",
                    "organizationId",
                    "siteId",
                    "target",
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
            name="single-volume compatibility record",
        )
        evidence = payload["evidenceRecordDigests"]
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError("single-volume evidence records must be a string list")
        return cls(
            organization_id=str(payload["organizationId"]),
            site_id=str(payload["siteId"]),
            target=ExternalVolumeInputBindingV1.model_validate(payload["target"]),
            zone_snapshot=ExternalVolumeZoneSnapshotV1.model_validate(payload["zoneSnapshot"]),
            validation_policy_digest=str(payload["validationPolicyDigest"]),
            external_profile=str(payload["externalProfile"]),
            grammar_digest=str(payload["grammarDigest"]),
            inspector_build_digest=str(payload["inspectorBuildDigest"]),
            evidence_record_digests=tuple(evidence),
            compatibility_rule_digest=str(payload["compatibilityRuleDigest"]),
            execution_policy_ref=str(payload["executionPolicyRef"]),
            valid_from=_parse_time(payload["validFrom"], name="single-volume validFrom"),
            valid_until=_parse_time(payload["validUntil"], name="single-volume validUntil"),
            mapping_record_digest=str(payload["mappingRecordDigest"]),
        )


__all__ = ["ExternalSingleVolumeCompatibilityRecord", "SingleVolumeCompatibilityRuleDescriptorV1"]
