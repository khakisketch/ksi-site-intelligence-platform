"""Signed-provider routing for profile comparison mapping authority."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from ksi_core.domains.external.authority.external_authority_provider import (
    ExternalAuthorityProvider,
)
from ksi_core.domains.external.authority.provider_loading import _administration_actions
from ksi_core.domains.external.authority.provider_types import (
    _AdministrationAction,
    _ProviderConfig,
    _VerifiedSnapshot,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _subject(work_order_id: str, label: str, site_id: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id=site_id,
        work_order_id=work_order_id,
        submission_id=f"submission-{label}",
        revision=1,
        submission_digest=_digest(f"submission-{label}"),
        manifest_digest=_digest(f"manifest-{label}"),
    )


def _binding(
    work_order_id: str, label: str, hour: int, site_id: str
) -> ExternalVolumeInputBindingV1:
    return ExternalVolumeInputBindingV1(
        subject=_subject(work_order_id, label, site_id),
        inspection_report_digest=_digest(f"inspection-{label}"),
        dsm_artifact_id=f"dsm-{label}",
        observed_sha256=_digest(f"dsm-bytes-{label}"),
        observed_size_bytes=16,
        observed_crs_digest=_digest("crs"),
        observed_vertical_reference_digest=_digest("vertical"),
        captured_from=NOW + timedelta(hours=hour),
        captured_to=NOW + timedelta(hours=hour + 1),
    )


def _mapping(site_id: str = "site-a") -> ExternalQuantitativeCompatibilityRecord:
    return ExternalQuantitativeCompatibilityRecord(
        organization_id="org-a",
        site_id=site_id,
        baseline=_binding("work-baseline", "baseline", 0, site_id),
        current=_binding("work-current", "current", 2, site_id),
        zone_snapshot=ExternalVolumeZoneSnapshotV1(
            organization_id="org-a",
            site_id=site_id,
            work_area_id="work-area-a",
            polygon={
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
            },
            crs="EPSG:5186",
            observed_crs_digest=_digest("crs"),
            analysis_vertical_reference_digest=_digest("vertical"),
        ).sealed(),
        validation_policy_digest=_digest("validation-policy"),
        external_profile="external-geotiff-profile.v1",
        grammar_digest=_digest("grammar"),
        inspector_build_digest=_digest("inspector-build"),
        evidence_record_digests=(_digest("evidence-baseline"), _digest("evidence-current")),
        execution_policy_ref=_digest("execution-policy-authority"),
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=10),
    ).sealed()


def _signed_actions(
    kind: str, mapping: ExternalQuantitativeCompatibilityRecord
) -> tuple[_AdministrationAction, ...]:
    action: dict[str, object] = {
        "actionId": "profile-mapping-action-1",
        "kind": kind,
        "effectiveAt": NOW.isoformat().replace("+00:00", "Z"),
        "actorId": "catalog-admin",
    }
    if kind.startswith("ADMIT_"):
        action["mapping"] = {
            **mapping.canonical_payload(),
            "mappingRecordDigest": mapping.mapping_digest,
        }
    else:
        action["mappingDigest"] = mapping.mapping_digest
    return _administration_actions(
        {"actions": [action]},
        issued_at=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize("kind", ("ADMIT_PROFILE_MAPPING", "REVOKE_PROFILE_MAPPING"))
def test_signed_profile_mapping_actions_are_validated_as_exact_catalog_records(
    kind: str,
) -> None:
    mapping = _mapping()
    action = _signed_actions(kind, mapping)[0]

    assert action.kind == kind
    if kind == "ADMIT_PROFILE_MAPPING":
        assert ExternalQuantitativeCompatibilityRecord.from_event_payload(
            action.payload["mapping"]
        ) == mapping
    else:
        assert action.payload["mappingDigest"] == mapping.mapping_digest


def test_profile_mapping_action_payload_rejects_unrecognized_mapping_fields() -> None:
    sealed = _mapping()
    mapping = {
        **sealed.canonical_payload(),
        "mappingRecordDigest": sealed.mapping_digest,
    }
    mapping["workAreaApprovalText"] = "approved"
    action = {
        "actionId": "profile-mapping-action-1",
        "kind": "ADMIT_PROFILE_MAPPING",
        "effectiveAt": NOW.isoformat().replace("+00:00", "Z"),
        "actorId": "catalog-admin",
        "mapping": mapping,
    }

    with pytest.raises(ValueError):
        _administration_actions(
            {"actions": [action]},
            issued_at=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(hours=1),
        )


def test_profile_mapping_action_rejects_values_normalized_by_the_record_parser() -> None:
    sealed = _mapping(site_id="17")
    mapping: dict[str, object] = {
        **sealed.canonical_payload(),
        "mappingRecordDigest": sealed.mapping_digest,
    }
    mapping["siteId"] = 17
    action = {
        "actionId": "profile-mapping-action-1",
        "kind": "ADMIT_PROFILE_MAPPING",
        "effectiveAt": NOW.isoformat().replace("+00:00", "Z"),
        "actorId": "catalog-admin",
        "mapping": mapping,
    }

    with pytest.raises(ValueError, match="canonical record payload"):
        _administration_actions(
            {"actions": [action]},
            issued_at=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(hours=1),
        )


class _Catalog:
    def __init__(self) -> None:
        self.profile_calls: list[tuple[str, object]] = []
        self.volume_calls: list[str] = []

    def admit_profile_mapping(
        self, mapping: ExternalQuantitativeCompatibilityRecord, *, actor: str, now: datetime
    ) -> ExternalQuantitativeCompatibilityRecord:
        self.profile_calls.append(("admit", mapping.mapping_digest))
        assert actor == "catalog-admin"
        assert now == NOW
        return mapping

    def revoke_profile_mapping(
        self, mapping_digest: str, *, actor: str, now: datetime
    ) -> bool:
        self.profile_calls.append(("revoke", mapping_digest))
        assert actor == "catalog-admin"
        assert now == NOW
        return True

    def admit_mapping(self, *_args: object, **_kwargs: object) -> None:
        self.volume_calls.append("admit")
        raise AssertionError("profile mapping reached volume authority")

    def revoke_mapping(self, *_args: object, **_kwargs: object) -> None:
        self.volume_calls.append("revoke")
        raise AssertionError("profile mapping reached volume authority")


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("ADMIT_PROFILE_MAPPING", "admit"),
        ("REVOKE_PROFILE_MAPPING", "revoke"),
    ),
)
def test_profile_mapping_actions_route_only_to_the_profile_mapping_port(
    kind: str, expected: str
) -> None:
    mapping = _mapping()
    action = _signed_actions(kind, mapping)[0]
    provider = object.__new__(ExternalAuthorityProvider)
    provider._config = cast(
        _ProviderConfig,
        SimpleNamespace(
            catalog_administration_actor_id="catalog-admin", organization_id="org-a"
        ),
    )
    catalog = _Catalog()

    ExternalAuthorityProvider._apply_mapping_actions(
        provider, catalog, cast(_VerifiedSnapshot, SimpleNamespace(actions=(action,)))
    )

    assert catalog.profile_calls == [(expected, mapping.mapping_digest)]
    assert catalog.volume_calls == []


def test_profile_mapping_actions_reject_an_unconfigured_administrator() -> None:
    mapping = _mapping()
    action = _signed_actions("ADMIT_PROFILE_MAPPING", mapping)[0]
    action = _AdministrationAction(
        action_id=action.action_id,
        kind=action.kind,
        effective_at=action.effective_at,
        actor_id="other-admin",
        payload=action.payload,
    )
    provider = object.__new__(ExternalAuthorityProvider)
    provider._config = cast(
        _ProviderConfig,
        SimpleNamespace(
            catalog_administration_actor_id="catalog-admin", organization_id="org-a"
        ),
    )

    with pytest.raises(ValueError, match="configured catalog administrator"):
        ExternalAuthorityProvider._apply_mapping_actions(
            provider, _Catalog(), cast(_VerifiedSnapshot, SimpleNamespace(actions=(action,)))
        )
