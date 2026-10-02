"""Real journal-backed Core source authority with explicitly synthetic measurement reports.

The retained report exercises resolution/currentness, not parser or host containment proof.
T8 must replace only the synthetic measurement production with the genuine inspector.
"""

import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ksi_core.acquisition import observation_epoch_id
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_core.work_areas import WorkAreaStore
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_mission_contracts.models import SiteFrame
from pyproj import CRS
from spatial_data_fixture import make_policy
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    NOW,
    WORKER_A,
    SyntheticStorage,
    policy_template,
    report,
    sealed_submission,
)
from test_external_artifact_inspections import _Authority


def source_stores(
    path: Path,
    *,
    sealed: bool = True,
    measured: bool = True,
    rejected: bool = False,
    artifact_declarations: Any = None,
    inspection_template: Any = None,
    measurement_factory: Any = None,
) -> SimpleNamespace:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(DurableJournal(path / "sites.jsonl"), coordinator=coordinator)
    frame = SiteFrame(
        crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
    )
    sites.register(
        "site-1", "site", frame, organization_id="organization-1", actor="operator-1", now=NOW
    )
    areas = WorkAreaStore(
        DurableJournal(path / "areas.jsonl"),
        site_exists=lambda site: sites.get(site) is not None,
        coordinator=coordinator,
    )
    area = areas.register(
        "site-1",
        name="area",
        crs="EPSG:5186",
        supersedes=None,
        polygon={"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        actor="operator-1",
        now=NOW,
    ).work_area
    assert area is not None
    orders = ObservationWorkOrderStore(
        DurableJournal(path / "orders.jsonl"),
        site_exists=lambda site, organization: sites.get_scoped(site, organization) is not None,
        operations_coordinator=coordinator,
    )
    order = orders.create_work_order(
        organization_id="organization-1",
        site_id="site-1",
        name="export",
        work_area_ids=[area.work_area_id],
        schedule_id=None,
        actor="operator-1",
        now=NOW,
    )
    reconstruction = ExternalReconstructionStore(
        DurableJournal(path / "ingress.jsonl"), coordinator=coordinator
    )
    submission = (
        sealed_submission()
        .model_copy(
            update={
                "observation_epoch_id": observation_epoch_id(order),
                "submission_digest": None,
            }
        )
        .sealed()
    )
    if artifact_declarations is not None:
        submission = submission.model_copy(
            update={"artifacts": tuple(artifact_declarations), "submission_digest": None}
        ).sealed()
    result = reconstruction.register(
        submission, work_order=order, registered_by="operator-1", now=NOW
    )
    assert result.revision is not None, result
    if sealed:
        storage = SyntheticStorage()
        for artifact_id, key in result.revision.bindings:
            declaration = next(a for a in submission.artifacts if a.artifact_id == artifact_id)
            storage.objects[key] = ObjectStorageObservation(
                object_key=key,
                exists=True,
                sha256="sha256:" + declaration.declared_sha256,
                size_bytes=declaration.declared_size_bytes,
                content_type=declaration.content_type,
            )
        result = reconstruction.seal(
            order.work_order_id,
            submission.submission_id,
            1,
            organization_id="organization-1",
            site_id="site-1",
            storage=storage,
            now=NOW,
        )
    record = result.revision
    assert record is not None
    assert submission.submission_digest is not None
    assert record.manifest is None or record.manifest.manifest_digest is not None
    manifest_digest = record.manifest.manifest_digest if record.manifest is not None else None
    subject = (
        SealedExternalSubjectV1(
            organization_id="organization-1",
            site_id="site-1",
            work_order_id=order.work_order_id,
            submission_id=submission.submission_id,
            revision=1,
            submission_digest=submission.submission_digest,
            manifest_digest=manifest_digest,
        )
        if record.manifest is not None and manifest_digest is not None
        else None
    )
    template = inspection_template if inspection_template is not None else policy_template()
    authority_record = (
        PolicyAuthorityRecord(
            policy_id=template.policy_id,
            policy_version=template.version,
            authorized_policy_body_digest=authorized_policy_body_digest(template),
            permitted_subjects=(subject,) if subject else (),
            permitted_uses=("INSPECTION", "DISPLAY"),
            authorized_actor_ids=("authority",),
            active_from=NOW - timedelta(minutes=1),
            active_until=NOW + timedelta(minutes=1),
            synthetic_test_only=True,
        ).sealed()
        if subject
        else None
    )
    authority = _Authority(*((authority_record,) if authority_record else ())).bind(coordinator)
    policies = ExternalValidationPolicyRegistry(
        DurableJournal(path / "policy.jsonl"),
        authority_port=authority,
        authority_currentness_port=authority,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    inspection_policy = (
        template.model_copy(
            update={"authority_record_digest": authority_record.digest, "policy_digest": None}
        ).sealed()
        if authority_record
        else None
    )
    if inspection_policy is not None:
        policies.admit(inspection_policy, actor="authority", now=NOW)
    inspections = ExternalArtifactInspectionStore(
        DurableJournal(path / "inspections.jsonl"),
        policy_registry=policies,
        external_reconstruction=reconstruction,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    accepted = None
    if measured and subject is not None:
        assert inspection_policy is not None
        issued = inspections.issue_after_seal(subject, now=NOW)
        assert issued.request is not None
        claim = inspections.claim(
            issued.request.request_id, LeaseFence(WORKER_A, ACQUISITION, 0), now=NOW
        )
        assert claim.fence is not None
        base = report(request_id=issued.request.request_id, policy=inspection_policy)
        wkt = CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
        original = base.measurement_payload.outcomes[0]
        assert original.measurements is not None
        measurements = original.measurements.model_copy(
            update={
                "observed_crs_wkt": wkt,
                "observed_crs_digest": "sha256:" + hashlib.sha256(wkt.encode()).hexdigest(),
                "layout": "GEOTIFF_STRIPED_V1",
            }
        )
        outcome = original.model_copy(update={"measurements": measurements})
        if rejected:
            outcome = original.model_copy(
                update={"outcome": "REJECTED", "reason": "UNSUPPORTED_RASTER", "measurements": None}
            )
        payload = base.measurement_payload.model_copy(
            update={
                "subject_digest": subject.canonical_digest(),
                "sealed_manifest_digest": subject.manifest_digest,
                "outcomes": (outcome,),
            }
        )
        if measurement_factory is not None:
            from ksi_event_contracts.external_artifact_validation import SealedArtifactBindingV1

            outcomes = tuple(measurement_factory(inspection_policy))
            payload = payload.model_copy(
                update={
                    "outcomes": outcomes,
                    "artifact_bindings": tuple(
                        SealedArtifactBindingV1(
                            artifact_id=outcome.artifact_id, observed_sha256=outcome.observed_sha256
                        )
                        for outcome in outcomes
                    ),
                }
            )
        accepted = base.model_copy(
            update={
                "subject": subject,
                "subject_digest": subject.canonical_digest(),
                "sealed_manifest_digest": subject.manifest_digest,
                "measurement_payload": payload,
                "measurement_payload_digest": None,
                "report_digest": None,
            }
        ).sealed()
        assert (
            inspections.record_report(
                issued.request.request_id, claim.fence, accepted, now=NOW
            ).verdict
            == "REPORTED"
        )
    principal = Principal(
        principal_id="operator-1",
        organization_id="organization-1",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
    )
    return SimpleNamespace(
        coordinator=coordinator,
        sites=sites,
        work_areas=areas,
        work_orders=orders,
        reconstruction=reconstruction,
        inspections=inspections,
        inspection_policies=policies,
        authority=authority,
        data_policy=make_policy(),
        principal=principal,
        area=area,
        order=order,
        subject=subject,
        accepted_report=accepted,
        record=record,
    )


def source_resolver(stores: SimpleNamespace) -> SpatialDataSourceResolver:
    from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver

    return SpatialDataSourceResolver(
        reconstruction=stores.reconstruction,
        inspections=stores.inspections,
        sites=stores.sites,
        work_areas=stores.work_areas,
        work_orders=stores.work_orders,
        policy=stores.data_policy,
        coordinator=stores.coordinator,
        clock=lambda: NOW,
    )


def restart_source_stores(stores: SimpleNamespace, path: Path) -> SimpleNamespace:
    """Reopen real participant journals only; no register/inspect/issue side effects."""
    for participant in (
        stores.sites,
        stores.work_areas,
        stores.work_orders,
        stores.reconstruction,
        stores.inspection_policies,
        stores.inspections,
    ):
        participant._journal.close()  # noqa: SLF001
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    sites = SiteStore(DurableJournal(path / "sites.jsonl"), coordinator=coordinator)
    areas = WorkAreaStore(
        DurableJournal(path / "areas.jsonl"),
        site_exists=lambda site: sites.get(site) is not None,
        coordinator=coordinator,
    )
    orders = ObservationWorkOrderStore(
        DurableJournal(path / "orders.jsonl"),
        site_exists=lambda site, organization: sites.get_scoped(site, organization) is not None,
        operations_coordinator=coordinator,
    )
    reconstruction = ExternalReconstructionStore(
        DurableJournal(path / "ingress.jsonl"), coordinator=coordinator
    )
    authority = _Authority(*stores.authority._records.values()).bind(coordinator)  # noqa: SLF001
    policies = ExternalValidationPolicyRegistry(
        DurableJournal(path / "policy.jsonl"),
        authority_port=authority,
        authority_currentness_port=authority,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    inspections = ExternalArtifactInspectionStore(
        DurableJournal(path / "inspections.jsonl"),
        policy_registry=policies,
        external_reconstruction=reconstruction,
        coordinator=coordinator,
        clock=lambda: NOW,
    )
    return SimpleNamespace(
        **{
            **stores.__dict__,
            "coordinator": coordinator,
            "sites": sites,
            "work_areas": areas,
            "work_orders": orders,
            "reconstruction": reconstruction,
            "authority": authority,
            "inspection_policies": policies,
            "inspections": inspections,
        }
    )


def source_identity(stores: SimpleNamespace, *, artifact_id: str | None = None) -> str:
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

    items = SpatialAssetCatalog(
        reconstruction=stores.reconstruction,
        work_orders=stores.work_orders,
        sites=stores.sites,
        work_areas=stores.work_areas,
        inspections=stores.inspections,
    ).items("site-1", stores.area.work_area_id, stores.principal)
    return next(
        item.asset_ref for item in items if artifact_id is None or item.artifact_id == artifact_id
    )
