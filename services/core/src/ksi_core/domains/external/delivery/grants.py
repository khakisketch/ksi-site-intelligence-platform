"""Trusted append-only grant history. History inspection never authorizes bytes.

The history store cannot authorize. The separate current authorizer requires
the real coordinator-bound SiteStore and an explicit worker execution location.
It checks a Core-resolved source binding, but does not replace source inspection
resolution or the caller's atomic guarded check-and-commit.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Literal, Self

from ksi_event_contracts._spatial_data import SpatialDataModel, require_utc
from ksi_event_contracts.processing_job import ExecutionLocus
from ksi_event_contracts.spatial_data import SpatialDataPurposeV1, SpatialDataSourceV1
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataGrantV1,
    SpatialDataPolicyV1,
    SpatialDataRevocationV1,
)
from ksi_geo_spatial.external_native_window_geometry import (
    Bounds,
    NativeWindowError,
    NativeWindowGeometryV1,
    plan_external_native_window,
)
from pydantic import ValidationError, model_validator

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

type GrantKey = tuple[str, str, int]
type BeneficiaryAssetKey = tuple[str, str, str, str, str]


class SpatialDataGrantRecoveryError(RuntimeError):
    """A corrupt grant history must not create a partial usable projection."""


def _sealed(record: SpatialDataGrantV1 | SpatialDataRevocationV1) -> None:
    if getattr(record, record._digest_field) != record.canonical_digest():
        raise ValueError("grant history requires an explicitly sealed snapshot")


class _GrantProvisioned(SpatialDataModel):
    record_type: Literal["spatial-data-grant.provisioned.v1"] = "spatial-data-grant.provisioned.v1"
    grant: SpatialDataGrantV1

    @model_validator(mode="after")
    def _sealed_snapshot(self) -> Self:
        _sealed(self.grant)
        return self


class _GrantRevoked(SpatialDataModel):
    record_type: Literal["spatial-data-grant.revoked.v1"] = "spatial-data-grant.revoked.v1"
    revocation: SpatialDataRevocationV1

    @model_validator(mode="after")
    def _sealed_snapshot(self) -> Self:
        _sealed(self.revocation)
        return self


class SpatialDataGrantStore:
    """Owner-controlled provisioning/revocation only, with durable exact history."""

    def __init__(
        self, journal: DurableJournal, *, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> None:
        self._journal = journal
        self._coordinator = coordinator
        self._lock = RLock()
        self._grants: dict[GrantKey, SpatialDataGrantV1] = {}
        self._revocations: dict[GrantKey, SpatialDataRevocationV1] = {}
        self._latest: dict[tuple[str, str], int] = {}
        self._by_beneficiary_asset: dict[BeneficiaryAssetKey, list[GrantKey]] = {}
        try:
            for entry in journal.replay():
                kind = entry.get("recordType")
                if kind == "spatial-data-grant.provisioned.v1":
                    provisioned = _GrantProvisioned.model_validate(entry)
                    if self._check_provision(provisioned.grant):
                        self._project_grant(provisioned.grant)
                elif kind == "spatial-data-grant.revoked.v1":
                    revoked = _GrantRevoked.model_validate(entry)
                    if self._check_revocation(revoked.revocation):
                        self._project_revocation(revoked.revocation)
                elif isinstance(kind, str) and kind.startswith("spatial-data-grant."):
                    raise ValueError("unknown grant event")
        except Exception as exc:
            raise SpatialDataGrantRecoveryError("invalid spatial data grant history") from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @staticmethod
    def _key(record: SpatialDataGrantV1 | SpatialDataRevocationV1) -> GrantKey:
        return record.organization_id, record.grant_id, record.revision

    def _check_provision(self, grant: SpatialDataGrantV1) -> bool:
        existing = self._grants.get(self._key(grant))
        if existing is not None:
            if existing.grant_digest != grant.grant_digest:
                raise SpatialDataDomainError("REPORT_CONFLICT", 409)
            return False
        latest = self._latest.get((grant.organization_id, grant.grant_id), 0)
        if grant.revision != latest + 1:
            raise SpatialDataDomainError("REPORT_CONFLICT", 409)
        return True

    def _check_revocation(self, revocation: SpatialDataRevocationV1) -> bool:
        key = self._key(revocation)
        grant = self._grants.get(key)
        if grant is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if grant.grant_digest != revocation.grant_digest:
            raise SpatialDataDomainError("REPORT_CONFLICT", 409)
        existing = self._revocations.get(key)
        if existing is not None:
            if existing.revocation_digest != revocation.revocation_digest:
                raise SpatialDataDomainError("REPORT_CONFLICT", 409)
            return False
        return True

    def _project_grant(self, grant: SpatialDataGrantV1) -> None:
        self._grants[self._key(grant)] = grant
        self._latest[(grant.organization_id, grant.grant_id)] = grant.revision
        asset_key = (
            grant.organization_id,
            grant.beneficiary_principal_id,
            grant.site_id,
            grant.work_area_id,
            grant.asset_ref,
        )
        self._by_beneficiary_asset.setdefault(asset_key, []).append(self._key(grant))

    def _project_revocation(self, revocation: SpatialDataRevocationV1) -> None:
        self._revocations[self._key(revocation)] = revocation

    def provision(self, grant: SpatialDataGrantV1) -> None:
        event = _GrantProvisioned(grant=grant)
        with self._coordinator.mutation(), self._lock:
            if self._check_provision(event.grant):
                self._journal.append(event.model_dump(by_alias=True, mode="json"))
                self._project_grant(event.grant)

    def revoke(self, revocation: SpatialDataRevocationV1) -> None:
        event = _GrantRevoked(revocation=revocation)
        with self._coordinator.mutation(), self._lock:
            if self._check_revocation(event.revocation):
                self._journal.append(event.model_dump(by_alias=True, mode="json"))
                self._project_revocation(event.revocation)

    def historical_grant(
        self, *, organization_id: str, grant_id: str, revision: int
    ) -> SpatialDataGrantV1 | None:
        """Trusted history inspection; never a current-access or principal-scope decision."""
        with self._lock:
            return self._grants.get((organization_id, grant_id, revision))

    def is_revoked(self, *, organization_id: str, grant_id: str, revision: int) -> bool:
        """Inspect the durable revocation bit; False is not evidence of access rights."""
        with self._lock:
            return (organization_id, grant_id, revision) in self._revocations


class SpatialDataGrantAuthorizer:
    """Current exact rights, never inferred from role, history or public metadata.

    Sources passed here must already be resolved through genuine sealed inspection
    authority. A synthetic/model-valid source alone is not admission evidence.
    Callers keep coordinator.guarded_read open through their local durable commit.
    No remote I/O or credential resolution runs inside these locks.
    """

    def __init__(
        self,
        *,
        grants: SpatialDataGrantStore,
        sites: SiteStore,
        processing_location: ExecutionLocus,
    ) -> None:
        if not isinstance(sites, SiteStore) or sites.coordinator is not grants.coordinator:
            raise ValueError("data authorization requires the same Core Site coordinator")
        if not isinstance(processing_location, ExecutionLocus):
            raise ValueError("explicit data worker execution location required")
        self._grants = grants
        self._sites = sites
        self._processing_location = processing_location

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._grants.coordinator

    def uses_exact_participants(self, *, grants: SpatialDataGrantStore, sites: SiteStore) -> bool:
        return grants is self._grants and sites is self._sites

    @staticmethod
    def _asset_key(source: SpatialDataSourceV1, principal: Principal) -> BeneficiaryAssetKey:
        return (
            principal.organization_id,
            principal.principal_id,
            source.site_id,
            source.work_area_id,
            source.asset_ref,
        )

    def _check_context(
        self,
        *,
        source: SpatialDataSourceV1,
        principal: Principal,
        purpose: SpatialDataPurposeV1 | str,
        requested_bounds: Bounds,
        geometry: NativeWindowGeometryV1,
        operation: str,
        policy: SpatialDataPolicyV1,
        now: datetime,
    ) -> None:
        require_utc(now)
        if principal.organization_id != source.sealed_subject.organization_id:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        for scopes, identity in (
            (principal.allowed_site_ids, source.site_id),
            (principal.allowed_work_area_ids, source.work_area_id),
        ):
            if (
                principal.kind
                in (PrincipalKind.SPATIAL_DATA_CLIENT, PrincipalKind.SPATIAL_DATA_MCP_CLIENT)
                and scopes is None
            ) or (scopes is not None and (type(scopes) is not frozenset or identity not in scopes)):
                raise SpatialDataDomainError("NOT_FOUND", 404)
        if principal.kind not in (
            PrincipalKind.OPERATOR,
            PrincipalKind.SPATIAL_DATA_CLIENT,
            PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if principal.device_id is not None or (
            principal.kind
            in (PrincipalKind.SPATIAL_DATA_CLIENT, PrincipalKind.SPATIAL_DATA_MCP_CLIENT)
            and principal.role is not None
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        permission = {
            "PREPARE": Permission.SPATIAL_DATA_REQUEST,
            "READ": Permission.SPATIAL_DATA_READ,
        }.get(operation)
        if permission is None or permission not in principal_permissions(principal):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if purpose not in (SpatialDataPurposeV1.GENERAL_DATA_USE, SpatialDataPurposeV1.EXTERNAL_AI):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        try:
            validated_source = SpatialDataSourceV1.model_validate(source)
            if validated_source.source_digest != validated_source.canonical_digest():
                raise ValueError("unsealed source")
        except (ValidationError, ValueError) as exc:
            raise SpatialDataDomainError("SOURCE_UNAVAILABLE", 503) from exc
        try:
            validated_policy = SpatialDataPolicyV1.model_validate(policy)
            if validated_policy.policy_digest != validated_policy.canonical_digest():
                raise ValueError("unsealed policy")
        except (ValidationError, ValueError) as exc:
            raise SpatialDataDomainError("POLICY_UNAVAILABLE", 503) from exc
        if self._sites.sealed_reason is not None or self._grants._journal.sealed_reason is not None:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        site = self._sites.get_scoped(source.site_id, principal.organization_id)
        if site is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if purpose == SpatialDataPurposeV1.EXTERNAL_AI and site.ai_egress_allowed is not True:
            raise SpatialDataDomainError("AI_EGRESS_DENIED", 403)
        if self._processing_location in (
            ExecutionLocus.KSI_SERVER_GPU,
            ExecutionLocus.VENDOR_CLOUD,
        ) and (site.data_residency is None or site.data_residency.get("egressAllowed") is not True):
            raise SpatialDataDomainError("PROCESSING_LOCATION_DENIED", 403)
        measurements = validated_source.inspection.measurements
        if measurements is None:
            raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
        try:
            expected = plan_external_native_window(
                requested_bounds=requested_bounds,
                measurements=measurements,
                requested_crs_digest=measurements.observed_crs_digest,
            )
        except NativeWindowError as exc:
            raise SpatialDataDomainError(exc.reason, 422) from exc
        if geometry != expected:
            raise SpatialDataDomainError("SOURCE_MEASUREMENTS_MISMATCH", 409)

    def _check_grant(
        self,
        grant: SpatialDataGrantV1,
        *,
        purpose: SpatialDataPurposeV1 | str,
        source: SpatialDataSourceV1,
        requested_bounds: Bounds,
        geometry: NativeWindowGeometryV1,
        operation: str,
        policy: SpatialDataPolicyV1,
        now: datetime,
    ) -> SpatialDataGrantV1:
        if self._grants._key(grant) in self._grants._revocations:
            raise SpatialDataDomainError("ACCESS_REVOKED", 403)
        if not grant.is_current_at(now):
            raise SpatialDataDomainError("ACCESS_EXPIRED", 403)
        if grant.policy_digest != policy.policy_digest:
            raise SpatialDataDomainError("POLICY_UNAVAILABLE", 503)
        if purpose not in grant.purposes or operation not in grant.operations:
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if grant.processing_location is not self._processing_location:
            raise SpatialDataDomainError("PROCESSING_LOCATION_DENIED", 403)
        measurements = source.inspection.measurements
        if measurements is None:
            raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
        if grant.observed_crs_digest != measurements.observed_crs_digest:
            raise SpatialDataDomainError("CRS_MISMATCH", 403)
        left, bottom, right, top = grant.allowed_bounds
        for xmin, ymin, xmax, ymax in (requested_bounds, geometry.actual_bounds):
            if xmin < left or ymin < bottom or xmax > right or ymax > top:
                raise SpatialDataDomainError("OUTPUT_OUTSIDE_GRANT", 403)
        return grant

    def require_current(
        self,
        *,
        grant_id: str,
        revision: int,
        source: SpatialDataSourceV1,
        principal: Principal,
        purpose: SpatialDataPurposeV1 | str,
        requested_bounds: Bounds,
        geometry: NativeWindowGeometryV1,
        operation: str,
        policy: SpatialDataPolicyV1,
        now: datetime,
    ) -> SpatialDataGrantV1:
        with self.coordinator.guarded_read(), self._grants._lock:
            self._check_context(
                source=source,
                principal=principal,
                purpose=purpose,
                requested_bounds=requested_bounds,
                geometry=geometry,
                operation=operation,
                policy=policy,
                now=now,
            )
            if type(revision) is not int or revision <= 0 or type(grant_id) is not str:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            grant = self._grants._grants.get((principal.organization_id, grant_id, revision))
            if grant is None or (
                grant.organization_id,
                grant.beneficiary_principal_id,
                grant.site_id,
                grant.work_area_id,
                grant.asset_ref,
            ) != self._asset_key(source, principal):
                raise SpatialDataDomainError("NOT_FOUND", 404)
            return self._check_grant(
                grant,
                purpose=purpose,
                source=source,
                requested_bounds=requested_bounds,
                geometry=geometry,
                operation=operation,
                policy=policy,
                now=now,
            )

    def select_current(
        self,
        *,
        source: SpatialDataSourceV1,
        principal: Principal,
        purpose: SpatialDataPurposeV1 | str,
        requested_bounds: Bounds,
        geometry: NativeWindowGeometryV1,
        operation: str,
        policy: SpatialDataPolicyV1,
        now: datetime,
    ) -> SpatialDataGrantV1:
        with self.coordinator.guarded_read(), self._grants._lock:
            self._check_context(
                source=source,
                principal=principal,
                purpose=purpose,
                requested_bounds=requested_bounds,
                geometry=geometry,
                operation=operation,
                policy=policy,
                now=now,
            )
            keys = self._grants._by_beneficiary_asset.get(self._asset_key(source, principal), ())
            if len(keys) > policy.max_list_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            applicable = []
            for key in keys:
                try:
                    grant = self._check_grant(
                        self._grants._grants[key],
                        purpose=purpose,
                        source=source,
                        requested_bounds=requested_bounds,
                        geometry=geometry,
                        operation=operation,
                        policy=policy,
                        now=now,
                    )
                except SpatialDataDomainError:
                    continue
                applicable.append(grant)
                if len(applicable) > 1:
                    raise SpatialDataDomainError("AMBIGUOUS_GRANT", 403)
            if not applicable:
                raise SpatialDataDomainError("GRANT_REQUIRED", 403)
            return applicable[0]

    def select_metadata_current(
        self,
        *,
        source: SpatialDataSourceV1,
        principal: Principal,
        policy: SpatialDataPolicyV1,
        now: datetime,
    ) -> SpatialDataGrantV1:
        """One current EXTERNAL_AI+READ grant for AI metadata; no crop planning.

        Metadata authorization never expands pixels: this selector performs no
        native-window planning and no bounds check. It binds exactly one current
        beneficiary/source grant by policy, processing location and observed
        CRS digest; the sealed grant's license-provenance digest is bound by
        exact frozen-grant equality at the job boundary. Ambiguous or absent
        rights fail closed; dependency and representation failures are never
        empty success.
        """
        require_utc(now)
        if (
            principal.kind is not PrincipalKind.SPATIAL_DATA_MCP_CLIENT
            or principal.device_id is not None
            or principal.role is not None
            or Permission.SPATIAL_DATA_READ not in principal_permissions(principal)
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        try:
            validated_source = SpatialDataSourceV1.model_validate(source)
            if validated_source.source_digest != validated_source.canonical_digest():
                raise ValueError("unsealed source")
        except (ValidationError, ValueError) as exc:
            raise SpatialDataDomainError("SOURCE_UNAVAILABLE", 503) from exc
        try:
            validated_policy = SpatialDataPolicyV1.model_validate(policy)
            if validated_policy.policy_digest != validated_policy.canonical_digest():
                raise ValueError("unsealed policy")
        except (ValidationError, ValueError) as exc:
            raise SpatialDataDomainError("POLICY_UNAVAILABLE", 503) from exc
        with self.coordinator.guarded_read(), self._grants._lock:
            if principal.organization_id != validated_source.sealed_subject.organization_id:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            for scopes, identity in (
                (principal.allowed_site_ids, validated_source.site_id),
                (principal.allowed_work_area_ids, validated_source.work_area_id),
            ):
                if scopes is None or type(scopes) is not frozenset or identity not in scopes:
                    raise SpatialDataDomainError("NOT_FOUND", 404)
            if (
                self._sites.sealed_reason is not None
                or self._grants._journal.sealed_reason is not None
            ):
                raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
            site = self._sites.get_scoped(validated_source.site_id, principal.organization_id)
            if site is None:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            if site.ai_egress_allowed is not True:
                raise SpatialDataDomainError("AI_EGRESS_DENIED", 403)
            measurements = validated_source.inspection.measurements
            if measurements is None:
                raise SpatialDataDomainError("SOURCE_NOT_MEASURED", 403)
            keys = self._grants._by_beneficiary_asset.get(
                self._asset_key(validated_source, principal), ()
            )
            if len(keys) > validated_policy.max_list_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            applicable = []
            for key in keys:
                grant = self._grants._grants[key]
                if self._grants._key(grant) in self._grants._revocations:
                    continue
                if not grant.is_current_at(now):
                    continue
                if grant.policy_digest != validated_policy.policy_digest:
                    continue
                if "EXTERNAL_AI" not in grant.purposes or "READ" not in grant.operations:
                    continue
                if grant.processing_location is not self._processing_location:
                    continue
                if grant.observed_crs_digest != measurements.observed_crs_digest:
                    continue
                # The sealed grant model already requires an explicit
                # license-provenance digest; selection binds that recorded
                # digest by exact grant equality at the job boundary rather
                # than inventing a second license comparison here.
                applicable.append(grant)
                if len(applicable) > 1:
                    raise SpatialDataDomainError("AMBIGUOUS_GRANT", 403)
            if not applicable:
                raise SpatialDataDomainError("GRANT_REQUIRED", 403)
            return applicable[0]

    def has_beneficiary_grants(
        self, *, site_id: str, work_area_id: str, asset_ref: str, principal: Principal
    ) -> bool:
        """Local index probe: any grant ever indexed for this beneficiary asset.

        Read-only classification helper for send-time gates: a candidate with
        grant history stays tracked across readiness changes (fail closed on
        drift), while a never-granted candidate stays invisible without
        admission or payload. It authorizes nothing; currentness, uniqueness
        and operations are still decided by the selectors per projection.
        """
        if (
            type(site_id) is not str
            or type(work_area_id) is not str
            or type(asset_ref) is not str
            or not site_id
            or not work_area_id
            or not asset_ref
        ):
            raise ValueError("grant index probe requires explicit scope identifiers")
        if not isinstance(principal, Principal):
            raise ValueError("grant index probe requires a genuine principal")
        with self.coordinator.guarded_read(), self._grants._lock:
            return bool(
                self._grants._by_beneficiary_asset.get(
                    (
                        principal.organization_id,
                        principal.principal_id,
                        site_id,
                        work_area_id,
                        asset_ref,
                    ),
                    (),
                )
            )

    def frozen_grant_state(
        self, *, grant: SpatialDataGrantV1, now: datetime
    ) -> Literal["CURRENT", "REVOKED", "EXPIRED", "ABSENT"]:
        """Durable state of one sealed grant revision; inspection only, never access.

        Reports the exact frozen-grant denial (revoked vs expired vs absent)
        when no current unique READ grant covers a job. Unknown keys and
        tampered copies are both ABSENT: neither can authorize anything.
        """
        require_utc(now)
        key = (grant.organization_id, grant.grant_id, grant.revision)
        with self._grants._lock:
            if key in self._grants._revocations:
                return "REVOKED"
            stored = self._grants._grants.get(key)
            if stored is None or stored != grant:
                return "ABSENT"
            if not stored.is_current_at(now):
                return "EXPIRED"
            return "CURRENT"
