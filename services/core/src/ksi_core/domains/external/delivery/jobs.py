"""Durable data jobs: exact rights, bounded fences and ownership, without storage/network I/O."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol
from uuid import uuid4

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._spatial_data import require_utc
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataAvailabilityV1,
    SpatialDataExecutionStateV1,
    SpatialDataFrozenJobV1,
    SpatialDataJobViewV1,
    SpatialDataPageV1,
    SpatialDataPurposeV1,
    SpatialDataReasonV1,
    SpatialDataReceiptV1,
    SpatialDataRequestV1,
)
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)
from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1
from ksi_geo_spatial.external_native_window_geometry import (
    NativeWindowError,
    plan_external_native_window,
)
from pydantic import ValidationError

from ksi_core.domains.external.delivery.asset_discovery import (
    decode_snapshot_cursor,
    encode_snapshot_cursor,
    scope_hash,
    snapshot_digest,
)
from ksi_core.domains.external.delivery.errors import (
    SpatialDataAiDomainError,
    SpatialDataDomainError,
)
from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer
from ksi_core.domains.external.delivery.job_events import (
    JOB_EVENT,
    JobCleanupChanged,
    JobCompleted,
    JobEvent,
    JobIssued,
    JobLeased,
    JobOutputReserved,
    JobRenewed,
    JobStateChanged,
)
from ksi_core.domains.external.delivery.job_projection import (
    ACTIVE,
    TRANSIENT,
    CleanupCandidate,
    CleanupHandle,
    CleanupStatus,
    DownloadOutput,
    JobRecord,
    cleanup_ready_at,
    owned_key,
    transition,
)
from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, Role, principal_permissions


class SpatialDataJobCurrentnessPort(Protocol):
    """Trusted local lookup only. Caller owns this coordinator through durable append."""

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator: ...

    def resolve_requester(
        self, *, principal_id: str, organization_id: str, now: datetime
    ) -> Principal | None: ...

    def is_current(
        self,
        *,
        policy: SpatialDataPolicyV1,
        runtime: SpatialDataRuntimeV1,
        activation: SpatialDataActivationV1,
        now: datetime,
    ) -> bool: ...


class SpatialDataJobRecoveryError(RuntimeError):
    """Corrupt history cannot yield a partial usable job projection."""


@dataclass(frozen=True, slots=True)
class SpatialDataAiJobSnapshot:
    """Private owner-selected single-job publication snapshot.

    Captured by :meth:`SpatialDataJobStore.seal_ai_job_snapshot` from the
    genuine owner store under the locally current owner actor resolved from
    the credential's expected identity — never from caller-supplied bytes — and re-proved by
    :meth:`SpatialDataJobStore.verify_ai_job_snapshot` at every header/body
    refresh. It binds the exact canonical body emitted for this response to
    the immutable issued-job identity (job, source, frozen grant, requester,
    scope, purpose, policy). Only legal mutable drift (execution state,
    availability, receipt, reason, remediation) is tolerated between capture
    and emission; the snapshot stays a truthful point-in-time, never a claim
    of the latest atomic state. Ephemeral per-response provenance only: job
    and grant digests plus identifiers, finite JSON bytes, no tokens,
    capabilities, caches or public wire exposure.
    """

    job_id: str
    view: SpatialDataJobViewV1
    body: bytes
    body_digest: str
    job_digest: str | None
    asset_ref: str
    organization_id: str
    requester_principal_id: str
    site_id: str
    work_area_id: str
    purpose: SpatialDataPurposeV1
    source_digest: str | None
    grant_id: str
    grant_revision: int
    grant_digest: str | None
    policy_digest: str | None
    request_fingerprint: str | None
    seal: str
    """Per-store ephemeral integrity tag over the binding below.

    Computed with the store's private per-process key (never logged, wired
    or provisioned) so a self-consistent caller forgery or the same frozen
    job bytes sealed by another store cannot verify here. Supplements — never
    replaces — the fresh current-rights check on every use.
    """


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


class SpatialDataJobStore:
    def __init__(
        self,
        journal: DurableJournal,
        *,
        grants: SpatialDataGrantAuthorizer,
        sources: SpatialDataSourceResolver,
        policy: SpatialDataPolicyV1,
        runtime: SpatialDataRuntimeV1,
        activation: SpatialDataActivationV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        currentness: SpatialDataJobCurrentnessPort,
    ) -> None:
        if (
            not isinstance(grants, SpatialDataGrantAuthorizer)
            or not isinstance(sources, SpatialDataSourceResolver)
            or grants.coordinator is not coordinator
            or sources.coordinator is not coordinator
            or currentness.coordinator is not coordinator
        ):
            raise ValueError("job authority requires genuine participants with one coordinator")
        for snapshot in (policy, runtime, activation):
            validated = type(snapshot).model_validate(snapshot.model_dump())
            if getattr(validated, validated._digest_field) != validated.canonical_digest():
                raise ValueError("job authority requires sealed explicit snapshots")
        if (
            activation.policy_digest != policy.policy_digest
            or activation.runtime_digest != runtime.runtime_digest
        ):
            raise ValueError("job activation must bind explicit policy/runtime")
        self._journal = journal
        self._grants = grants
        self._sources = sources
        self._policy = policy.model_copy(deep=True)
        self._runtime = runtime.model_copy(deep=True)
        self._activation = activation.model_copy(deep=True)
        self._coordinator = coordinator
        self._currentness = currentness
        self._snapshot_key = secrets.token_bytes(32)
        self._lock = RLock()
        self._records: dict[str, JobRecord] = {}
        self._idempotency: dict[tuple[str, str, str, str, str], str] = {}
        self._by_scope: dict[tuple[str, str, str], dict[str, None]] = {}
        self._active: dict[str, dict[str, None]] = {}
        self._outputs: dict[tuple[str, str], None] = {}
        try:
            for raw in journal.replay():
                event = JOB_EVENT.validate_python(raw)
                record = transition(self._records.get(event.job_id), event)
                if isinstance(event, JobIssued):
                    self._check_new(record)
                self._project(record)
        except Exception as exc:
            raise SpatialDataJobRecoveryError("invalid spatial data job history") from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def policy(self) -> SpatialDataPolicyV1:
        return self._policy.model_copy(deep=True)

    @property
    def activation(self) -> SpatialDataActivationV1:
        return self._activation.model_copy(deep=True)

    def uses_exact_participants(
        self,
        *,
        grants: SpatialDataGrantAuthorizer,
        sources: SpatialDataSourceResolver,
        currentness: SpatialDataJobCurrentnessPort | None = None,
    ) -> bool:
        return (
            grants is self._grants
            and sources is self._sources
            and (currentness is None or currentness is self._currentness)
        )

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @contextmanager
    def _guard(self, now: datetime) -> Iterator[None]:
        require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            yield

    def _ensure_open(self) -> None:
        if self.sealed_reason is not None:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)

    @staticmethod
    def _key(job: SpatialDataFrozenJobV1) -> tuple[str, str, str, str, str]:
        return (
            job.organization_id,
            job.requester_principal_id,
            job.site_id,
            job.work_area_id,
            job.idempotency_key_hash,
        )

    def _check_new(self, record: JobRecord) -> None:
        job = record.job
        if job.job_id in self._records or self._key(job) in self._idempotency:
            raise ValueError("duplicate durable identity/idempotency scope")
        if (
            len(self._active.get(job.organization_id, {}))
            >= job.policy.max_active_jobs_per_organization
        ):
            raise ValueError("issuance exceeded frozen atomic organization quota")
        if (
            len(canonical_json_bytes(job.model_dump(by_alias=True, mode="json")))
            > job.policy.max_snapshot_bytes
        ):
            raise ValueError("frozen job exceeds representation budget")

    def _project(self, record: JobRecord) -> None:
        job = record.job
        self._records[job.job_id] = record
        for fence in record.outputs:
            output = record.outputs[fence]
            if output.cleanup is not None and output.cleanup.state == "COMPLETED":
                self._outputs.pop((job.job_id, fence), None)
            else:
                self._outputs[(job.job_id, fence)] = None
        self._idempotency[self._key(job)] = job.job_id
        self._by_scope.setdefault((job.organization_id, job.site_id, job.work_area_id), {})[
            job.job_id
        ] = None
        active = self._active.setdefault(job.organization_id, {})
        if record.state in ACTIVE:
            active[job.job_id] = None
        else:
            active.pop(job.job_id, None)

    def _append(self, event: JobEvent) -> JobRecord:
        self._ensure_open()
        event = JOB_EVENT.validate_python(event.model_dump())
        record = transition(self._records.get(event.job_id), event)
        if isinstance(event, JobIssued):
            self._check_new(record)
        try:
            self._journal.append(event.model_dump(by_alias=True, mode="json"))
        except JournalSealedError as exc:
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503) from exc
        self._project(record)
        return record

    @staticmethod
    def _scope(
        principal: Principal, site_id: str, work_area_id: str, *, permission: Permission
    ) -> None:
        for scopes, identity in (
            (principal.allowed_site_ids, site_id),
            (principal.allowed_work_area_ids, work_area_id),
        ):
            if (
                principal.kind
                in (PrincipalKind.SPATIAL_DATA_CLIENT, PrincipalKind.SPATIAL_DATA_MCP_CLIENT)
                and scopes is None
            ) or (scopes is not None and (type(scopes) is not frozenset or identity not in scopes)):
                raise SpatialDataDomainError("NOT_FOUND", 404)
        if (
            principal.kind
            not in (
                PrincipalKind.OPERATOR,
                PrincipalKind.SPATIAL_DATA_CLIENT,
                PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
            )
            or principal.device_id is not None
            or permission not in principal_permissions(principal)
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)

    def _history(
        self,
        job_id: str,
        principal: Principal,
        *,
        permission: Permission = Permission.SPATIAL_DATA_READ,
    ) -> JobRecord:
        record = self._records.get(job_id)
        if record is None or record.job.organization_id != principal.organization_id:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        job = record.job
        self._scope(principal, job.site_id, job.work_area_id, permission=permission)
        if job.requester_principal_id != principal.principal_id and not (
            principal.kind is PrincipalKind.OPERATOR and principal.role is Role.ADMIN
        ):
            raise SpatialDataDomainError("NOT_FOUND", 404)
        # Current Site/area visibility is checked by the genuine source participant without
        # requiring a grant/report (otherwise revoked jobs would disappear from history).
        self._sources.require_history_scope(job.site_id, job.work_area_id, principal)
        return record

    @staticmethod
    def _assert_ai_reader(principal: Principal, job: SpatialDataFrozenJobV1) -> None:
        """AI metadata readers: exact identity, owner scope and AI purpose only.

        Generic jobs are non-disclosing 404s for the AI identity; metadata can
        never be moved into AI use by a request header or a supplied job ID.
        """
        if (
            principal.kind is not PrincipalKind.SPATIAL_DATA_MCP_CLIENT
            or principal.device_id is not None
            or principal.role is not None
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        permissions = principal_permissions(principal)
        if (
            Permission.SPATIAL_DATA_READ not in permissions
            or Permission.SPATIAL_DATA_REQUEST not in permissions
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        for scopes, identity in (
            (principal.allowed_site_ids, job.site_id),
            (principal.allowed_work_area_ids, job.work_area_id),
        ):
            if scopes is None or type(scopes) is not frozenset or identity not in scopes:
                raise SpatialDataDomainError("NOT_FOUND", 404)
        if job.request.purpose != SpatialDataPurposeV1.EXTERNAL_AI:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if (job.requester_principal_id, job.organization_id) != (
            principal.principal_id,
            principal.organization_id,
        ):
            raise SpatialDataDomainError("NOT_FOUND", 404)

    def _require_ai_metadata_locked(
        self, *, job_id: str, principal: Principal, now: datetime
    ) -> SpatialDataJobViewV1:
        """Current AI metadata; caller holds the shared coordinator guard.

        Single-observation core shared by the public read, the snapshot seal
        and the snapshot verify, so authorization and the binding record read
        never separate across a guard release where a grant/source mutation
        could slip between them. Read-only: appends no journal events.
        """
        record = self._records.get(job_id)
        if record is None or record.job.organization_id != principal.organization_id:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        job = record.job
        self._assert_ai_reader(principal, job)
        self._lane(now, job=job)
        try:
            requester = self._currentness.resolve_requester(
                principal_id=job.requester_principal_id,
                organization_id=job.organization_id,
                now=now,
            )
        except Exception as exc:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if not isinstance(requester, Principal) or (
            requester.principal_id,
            requester.organization_id,
        ) != (job.requester_principal_id, job.organization_id):
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        # Re-evaluate the fresh authority's scopes rather than trusting the
        # caller-supplied principal object alone.
        self._scope(
            requester, job.site_id, job.work_area_id, permission=Permission.SPATIAL_DATA_READ
        )
        self._assert_ai_reader(requester, job)
        source = self._sources.require_current(source=job.source, principal=requester, now=now)
        # Metadata authorization binds the exact current unique READ
        # grant with no native-window planning: pixel rights stay on
        # preparation and download, never on metadata reads.
        try:
            selected = self._grants.select_metadata_current(
                source=source, principal=requester, policy=job.policy, now=now
            )
        except SpatialDataDomainError as exc:
            if exc.reason != "GRANT_REQUIRED":
                raise
            state = self._grants.frozen_grant_state(grant=job.grant, now=now)
            if state == "REVOKED":
                raise SpatialDataDomainError("ACCESS_REVOKED", 403) from exc
            if state == "EXPIRED":
                raise SpatialDataDomainError("ACCESS_EXPIRED", 403) from exc
            raise
        if selected != job.grant:
            # A replacement, tampered or forged grant — including one that
            # differs only in license_provenance_digest — can never
            # resurrect the exact frozen job grant.
            raise SpatialDataDomainError("ACCESS_REVOKED", 403)
        return self._view(record, now)

    def require_ai_metadata(
        self, *, job_id: str, principal: Principal, now: datetime
    ) -> SpatialDataJobViewV1:
        """Current AI metadata for one job; denial appends nothing.

        The caller must be the scoped owner AI principal and the job must carry
        EXTERNAL_AI purpose. Fresh requester authority, scopes, locally current
        source and the exact frozen READ grant are re-evaluated here — never by
        ID equality alone — and the frozen grant cannot be resurrected by a
        replacement. Retention and byte availability never deny AI metadata.
        """
        require_utc(now)
        with self._guard(now):
            return self._require_ai_metadata_locked(job_id=job_id, principal=principal, now=now)

    @staticmethod
    def _snapshot_binding_bytes(
        *,
        job_id: str,
        job_digest: str | None,
        source_digest: str | None,
        grant_id: str,
        grant_revision: int,
        grant_digest: str | None,
        organization_id: str,
        requester_principal_id: str,
        site_id: str,
        work_area_id: str,
        asset_ref: str,
        purpose: SpatialDataPurposeV1,
        policy_digest: str | None,
        request_fingerprint: str | None,
        body_digest: str,
    ) -> bytes:
        return canonical_json_bytes(
            {
                "job_id": job_id,
                "job_digest": job_digest,
                "source_digest": source_digest,
                "grant_id": grant_id,
                "grant_revision": grant_revision,
                "grant_digest": grant_digest,
                "organization_id": organization_id,
                "requester_principal_id": requester_principal_id,
                "site_id": site_id,
                "work_area_id": work_area_id,
                "asset_ref": asset_ref,
                "purpose": purpose.value,
                "policy_digest": policy_digest,
                "request_fingerprint": request_fingerprint,
                "body_digest": body_digest,
            }
        )

    def _snapshot_seal(self, binding: bytes) -> str:
        return "hmac-sha256:" + hmac.new(self._snapshot_key, binding, hashlib.sha256).hexdigest()

    def seal_ai_job_snapshot(
        self,
        *,
        job_id: str,
        now: datetime,
        principal: Principal | None = None,
        expected_principal_id: str | None = None,
        expected_organization_id: str | None = None,
    ) -> SpatialDataAiJobSnapshot:
        """Capture the owner-selected canonical publication snapshot for one AI job.

        The expected identity contributes ids only (a routing hint); the
        locally current owner actor is resolved through the trusted local
        currentness port inside the same shared coordinator guard that spans
        authorization and the binding record read, so no grant/source
        mutation slips between them and no remote credential refresh runs
        here. The caller view that routed this call contributes no bytes.
        Read-only: appends no journal events. A GENERAL-purpose, revoked,
        expired, replaced-grant, new-source, out-of-scope or
        identity-mismatched job refuses here, before any protected bytes,
        with the same closed reason the read itself carries.
        """
        require_utc(now)
        if expected_principal_id is None or expected_organization_id is None:
            if principal is None:
                raise ValueError("owner snapshot capture requires an expected identity")
            expected_principal_id = principal.principal_id
            expected_organization_id = principal.organization_id
        if (
            type(expected_principal_id) is not str
            or type(expected_organization_id) is not str
            or not expected_principal_id
            or not expected_organization_id
        ):
            raise ValueError("owner snapshot capture requires an expected identity")
        with self._guard(now):
            try:
                local_actor = self._currentness.resolve_requester(
                    principal_id=expected_principal_id,
                    organization_id=expected_organization_id,
                    now=now,
                )
            except Exception as exc:
                raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
            if not isinstance(local_actor, Principal) or (
                local_actor.principal_id,
                local_actor.organization_id,
            ) != (expected_principal_id, expected_organization_id):
                raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
            view = self._require_ai_metadata_locked(job_id=job_id, principal=local_actor, now=now)
            record = self._records.get(job_id)
            if record is None:  # Cannot follow a successful read; fail closed.
                raise SpatialDataDomainError("NOT_FOUND", 404)
            job = record.job
            if (expected_principal_id, expected_organization_id) != (
                job.requester_principal_id,
                job.organization_id,
            ):
                raise SpatialDataDomainError("NOT_FOUND", 404)
            body = canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
            if len(body) > self._policy.max_json_bytes:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            body_digest = _hash(body)
            binding = self._snapshot_binding_bytes(
                job_id=job.job_id,
                job_digest=job.job_digest,
                source_digest=job.source.source_digest,
                grant_id=job.grant.grant_id,
                grant_revision=job.grant.revision,
                grant_digest=job.grant.grant_digest,
                organization_id=job.organization_id,
                requester_principal_id=job.requester_principal_id,
                site_id=job.site_id,
                work_area_id=job.work_area_id,
                asset_ref=job.source.asset_ref,
                purpose=job.request.purpose,
                policy_digest=job.policy.policy_digest,
                request_fingerprint=job.request_fingerprint,
                body_digest=body_digest,
            )
            if len(binding) > self._policy.max_json_bytes:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            return SpatialDataAiJobSnapshot(
                job_id=job.job_id,
                view=view,
                body=body,
                body_digest=body_digest,
                job_digest=job.job_digest,
                asset_ref=job.source.asset_ref,
                organization_id=job.organization_id,
                requester_principal_id=job.requester_principal_id,
                site_id=job.site_id,
                work_area_id=job.work_area_id,
                purpose=job.request.purpose,
                source_digest=job.source.source_digest,
                grant_id=job.grant.grant_id,
                grant_revision=job.grant.revision,
                grant_digest=job.grant.grant_digest,
                policy_digest=job.policy.policy_digest,
                request_fingerprint=job.request_fingerprint,
                seal=self._snapshot_seal(binding),
            )

    def verify_ai_job_snapshot(
        self, *, snapshot: SpatialDataAiJobSnapshot, principal: Principal, now: datetime
    ) -> bytes:
        """Re-prove a sealed snapshot and return its SELECTED bytes for emission.

        Every header/body refresh repeats the genuine current authorization
        first (locked current-rights check over the freshly resolved
        principal, under the same shared guard as the binding record read),
        then compares the snapshot's per-store seal and immutable issued-job
        binding against the current frozen job. The seal proves the bytes
        were captured by this store's owner — a self-consistent caller
        forgery, a tampered seal, or the same frozen job sealed by another
        store refuses even when body, view and digest agree. Only legal
        mutable drift — execution state, availability, receipt, reason,
        remediation — is ignored for body equality, so legitimate worker
        progress after capture publishes the truthful point-in-time instead
        of a false conflict. A changed immutable binding or lapsed rights
        refuses with a closed denial before protected bytes. Read-only:
        appends no journal events.
        """
        require_utc(now)
        if type(snapshot) is not SpatialDataAiJobSnapshot:
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if (
            type(snapshot.body) is not bytes
            or not snapshot.body
            or len(snapshot.body) > self._policy.max_json_bytes
            or _hash(snapshot.body) != snapshot.body_digest
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if (
            not isinstance(snapshot.view, SpatialDataJobViewV1)
            or canonical_json_bytes(snapshot.view.model_dump(by_alias=True, mode="json"))
            != snapshot.body
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if (
            type(snapshot.seal) is not str
            or len(snapshot.seal) != len("hmac-sha256:") + 64
            or not snapshot.seal.startswith("hmac-sha256:")
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        expected_seal = self._snapshot_seal(
            self._snapshot_binding_bytes(
                job_id=snapshot.job_id,
                job_digest=snapshot.job_digest,
                source_digest=snapshot.source_digest,
                grant_id=snapshot.grant_id,
                grant_revision=snapshot.grant_revision,
                grant_digest=snapshot.grant_digest,
                organization_id=snapshot.organization_id,
                requester_principal_id=snapshot.requester_principal_id,
                site_id=snapshot.site_id,
                work_area_id=snapshot.work_area_id,
                asset_ref=snapshot.asset_ref,
                purpose=snapshot.purpose,
                policy_digest=snapshot.policy_digest,
                request_fingerprint=snapshot.request_fingerprint,
                body_digest=snapshot.body_digest,
            )
        )
        if not hmac.compare_digest(snapshot.seal, expected_seal):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        # Fresh rights before binding, under one guard with the record read:
        # revoked/expired/replaced grants, new sources, GENERAL purpose and
        # unknown scopes refuse here.
        with self._guard(now):
            self._require_ai_metadata_locked(job_id=snapshot.job_id, principal=principal, now=now)
            record = self._records.get(snapshot.job_id)
            if record is None:  # Cannot follow a successful read; fail closed.
                raise SpatialDataDomainError("NOT_FOUND", 404)
            job = record.job
            if (
                (snapshot.job_digest or "") != (job.job_digest or "")
                or snapshot.asset_ref != job.source.asset_ref
                or snapshot.organization_id != job.organization_id
                or snapshot.requester_principal_id != job.requester_principal_id
                or snapshot.site_id != job.site_id
                or snapshot.work_area_id != job.work_area_id
                or snapshot.purpose != job.request.purpose
                or (snapshot.source_digest or "") != (job.source.source_digest or "")
                or snapshot.grant_id != job.grant.grant_id
                or snapshot.grant_revision != job.grant.revision
                or (snapshot.grant_digest or "") != (job.grant.grant_digest or "")
                or (snapshot.policy_digest or "") != (job.policy.policy_digest or "")
                or (snapshot.request_fingerprint or "") != (job.request_fingerprint or "")
            ):
                raise SpatialDataDomainError("PERMISSION_DENIED", 403)
            return snapshot.body

    #: Candidate denials suppressed from AI listing; dependency, authority and
    #: representation failures propagate instead of becoming empty success.
    _AI_LIST_SUPPRESSED = frozenset(
        {
            "NOT_FOUND",
            "PERMISSION_DENIED",
            "AI_EGRESS_DENIED",
            "GRANT_REQUIRED",
            "AMBIGUOUS_GRANT",
            "ACCESS_REVOKED",
            "ACCESS_EXPIRED",
            "OUTPUT_OUTSIDE_GRANT",
            "PROCESSING_LOCATION_DENIED",
            "SOURCE_NOT_MEASURED",
            "SOURCE_UNSEALED",
            "CRS_MISMATCH",
        }
    )

    def _ai_visible_entries(
        self, ids: Sequence[str], principal: Principal, now: datetime
    ) -> list[tuple[str, SpatialDataJobViewV1, SpatialDataFrozenJobV1]]:
        """Filter AI-exportable jobs before pagination; never hide hard failures.

        Returns the visible sorted entries with their current views and frozen
        jobs so the snapshot cursor binds the exact projection without a
        second authorization pass. Read-only: never mutates journals.
        """
        entries = []
        for job_id in ids:
            record = self._records[job_id]
            if record.job.request.purpose != SpatialDataPurposeV1.EXTERNAL_AI:
                continue
            try:
                view = self.require_ai_metadata(job_id=job_id, principal=principal, now=now)
            except SpatialDataDomainError as exc:
                if exc.reason in self._AI_LIST_SUPPRESSED:
                    continue
                raise
            entries.append((job_id, view, record.job))
        return entries

    def _ai_job_snapshot(
        self, entries: list[tuple[str, SpatialDataJobViewV1, SpatialDataFrozenJobV1]]
    ) -> str:
        """Bind the current AI job projection plus relevant grant/consent bindings.

        Even an empty authorized page binds policy/activation digests, so a
        newly visible job stales outstanding cursors. No denied-job counts.
        """
        views: list[list[str]] = []
        size = 0
        for job_id, view, job in entries:
            body = canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
            if len(body) > self._policy.max_json_bytes:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            size += len(body)
            views.append(
                [
                    job_id,
                    "sha256:" + hashlib.sha256(body).hexdigest(),
                    job.job_digest or "",
                    job.source.source_digest or "",
                    job.grant.grant_digest or "",
                ]
            )
        if size > self._policy.max_snapshot_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return snapshot_digest(
            {
                "jobs": sorted(views),
                "policy": self._policy.policy_digest,
                "activation": self._activation.activation_digest,
            }
        )

    def check_ai_prepare_lane(self, *, now: datetime) -> None:
        """Fresh lane/policy/runtime for AI PREPARE advertisement; stale lane raises.

        Read-only: no journal append. A stale lane surfaces here instead of a
        fake preparable crop.
        """
        with self._guard(now):
            self._lane(now)

    def _lane(self, now: datetime, *, job: SpatialDataFrozenJobV1 | None = None) -> None:
        self._ensure_open()
        policy = job.policy if job else self._policy
        runtime = job.runtime if job else self._runtime
        if (
            not self._activation.is_current_at(now)
            or self._activation.policy_digest != policy.policy_digest
            or self._activation.runtime_digest != runtime.runtime_digest
        ):
            raise SpatialDataDomainError("ACTIVATION_UNAVAILABLE", 503)
        try:
            valid = self._currentness.is_current(
                policy=policy.model_copy(deep=True),
                runtime=runtime.model_copy(deep=True),
                activation=self._activation.model_copy(deep=True),
                now=now,
            )
        except Exception as exc:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if valid is not True:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)

    def _current(self, record: JobRecord, now: datetime, *, operation: str = "PREPARE") -> None:
        job = record.job
        self._lane(now, job=job)
        try:
            requester = self._currentness.resolve_requester(
                principal_id=job.requester_principal_id,
                organization_id=job.organization_id,
                now=now,
            )
        except Exception as exc:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        if not isinstance(requester, Principal) or (
            requester.principal_id,
            requester.organization_id,
        ) != (job.requester_principal_id, job.organization_id):
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        source = self._sources.require_current(source=job.source, principal=requester, now=now)
        measured = source.inspection.measurements
        assert measured is not None
        geometry = plan_external_native_window(
            requested_bounds=job.request.requested_bounds,
            measurements=measured,
            requested_crs_digest=job.request.observed_crs_digest,
        )
        grant = self._grants.require_current(
            grant_id=job.grant.grant_id,
            revision=job.grant.revision,
            source=source,
            principal=requester,
            purpose=job.request.purpose,
            requested_bounds=job.request.requested_bounds,
            geometry=geometry,
            operation=operation,
            policy=job.policy,
            now=now,
        )
        if grant != job.grant:
            raise SpatialDataDomainError("ACCESS_REVOKED", 403)

    def _expire(self, record: JobRecord, now: datetime) -> JobRecord:
        if record.state in ACTIVE and now >= record.job.deadline:
            return self._append(
                JobStateChanged(
                    job_id=record.job.job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    state="EXPIRED",
                    reason="DEADLINE_EXCEEDED",
                )
            )
        return record

    def _sweep(self, organization_id: str, now: datetime) -> None:
        ids = self._active.get(organization_id, {})
        if len(ids) > self._policy.max_pending_records:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        for job_id in tuple(ids):
            self._expire(self._records[job_id], now)

    def _view(self, record: JobRecord, now: datetime) -> SpatialDataJobViewV1:
        job = record.job
        receipt = record.outputs[record.accepted_fence].receipt if record.accepted_fence else None
        availability = "NOT_READY"
        reason = record.reason
        if record.completed_at is not None and now >= record.completed_at + timedelta(
            seconds=job.policy.retention_seconds
        ):
            availability, reason = "RETENTION_EXPIRED", "RETENTION_EXPIRED"
        else:
            try:
                self._current(record, now, operation="READ" if receipt else "PREPARE")
                if receipt:
                    availability = "AVAILABLE"
            except SpatialDataDomainError as exc:
                availability = (
                    exc.reason
                    if exc.reason in ("ACCESS_REVOKED", "ACCESS_EXPIRED")
                    else "UNAVAILABLE"
                )
                reason = exc.reason
        return SpatialDataJobViewV1(
            job_id=job.job_id,
            asset_ref=job.source.asset_ref,
            site_id=job.site_id,
            work_area_id=job.work_area_id,
            created_at=job.created_at,
            execution_state=SpatialDataExecutionStateV1(record.state),
            availability=SpatialDataAvailabilityV1(availability),
            reason=reason,
            receipt=receipt.model_copy(deep=True) if receipt else None,
        )

    def issue(
        self,
        *,
        site_id: str,
        work_area_id: str,
        request: SpatialDataRequestV1,
        principal: Principal,
        idempotency_key: str,
        now: datetime,
    ) -> SpatialDataJobViewV1:
        view, _ = self.issue_with_outcome(
            site_id=site_id,
            work_area_id=work_area_id,
            request=request,
            principal=principal,
            idempotency_key=idempotency_key,
            now=now,
        )
        return view

    def issue_with_outcome(
        self,
        *,
        site_id: str,
        work_area_id: str,
        request: SpatialDataRequestV1,
        principal: Principal,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[SpatialDataJobViewV1, bool]:
        require_utc(now)
        self._scope(principal, site_id, work_area_id, permission=Permission.SPATIAL_DATA_REQUEST)
        request = SpatialDataRequestV1.model_validate(request.model_dump())
        if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
            # The AI identity infers EXTERNAL_AI; a GENERAL purpose is refused
            # rather than rewritten, and issuance needs READ plus PREPARE.
            permissions = principal_permissions(principal)
            if (
                Permission.SPATIAL_DATA_READ not in permissions
                or Permission.SPATIAL_DATA_REQUEST not in permissions
            ):
                raise SpatialDataDomainError("PERMISSION_DENIED", 403)
            if request.purpose != SpatialDataPurposeV1.EXTERNAL_AI:
                raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key.encode()) > self._policy.max_idempotency_key_bytes
            or any(ord(c) < 32 or ord(c) == 127 for c in idempotency_key)
        ):
            raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
        key_hash = _hash(idempotency_key.encode())
        key = principal.organization_id, principal.principal_id, site_id, work_area_id, key_hash
        fingerprint = request.canonical_digest()
        with self._guard(now):
            existing = self._idempotency.get(key)
            if existing is not None:
                record = self._history(
                    existing, principal, permission=Permission.SPATIAL_DATA_REQUEST
                )
                self._current(record, now)
                if record.job.request_fingerprint != fingerprint:
                    raise SpatialDataDomainError("IDEMPOTENCY_CONFLICT", 409)
                if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                    # Same-key AI retry re-proves current unique AI metadata
                    # rights at the store; the outer send-time gate is never
                    # the only enforcement.
                    return (
                        self.require_ai_metadata(job_id=existing, principal=principal, now=now),
                        False,
                    )
                return self._view(self._expire(record, now), now), False
            self._lane(now)
        # Remote policy authority is only consulted outside the guarded commit.
        source = self._sources.resolve(
            site_id=site_id,
            work_area_id=work_area_id,
            asset_ref=request.asset_ref,
            principal=principal,
        )
        measured = source.inspection.measurements
        assert measured is not None
        try:
            geometry = plan_external_native_window(
                requested_bounds=request.requested_bounds,
                measurements=measured,
                requested_crs_digest=request.observed_crs_digest,
            )
        except NativeWindowError as exc:
            raise SpatialDataDomainError(exc.reason, 422) from exc
        c0, c1, r0, r1 = geometry.pixel_window
        if (c1 - c0) * (r1 - r0) > self._policy.max_output_pixels:
            raise SpatialDataDomainError("OUTPUT_PIXEL_LIMIT_EXCEEDED", 422)
        with self._guard(now):
            existing = self._idempotency.get(key)
            if existing is not None:
                record = self._history(
                    existing, principal, permission=Permission.SPATIAL_DATA_REQUEST
                )
                self._current(record, now)
                if record.job.request_fingerprint != fingerprint:
                    raise SpatialDataDomainError("IDEMPOTENCY_CONFLICT", 409)
                if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                    # Same-key AI retry re-proves current unique AI metadata
                    # rights at the store; the outer send-time gate is never
                    # the only enforcement.
                    return (
                        self.require_ai_metadata(job_id=existing, principal=principal, now=now),
                        False,
                    )
                return self._view(self._expire(record, now), now), False
            self._lane(now)
            if self._activation.organization_id != principal.organization_id:
                raise SpatialDataDomainError("ACTIVATION_UNAVAILABLE", 503)
            self._sources.require_current(source=source, principal=principal, now=now)
            grant = self._grants.select_current(
                source=source,
                principal=principal,
                purpose=request.purpose,
                requested_bounds=request.requested_bounds,
                geometry=geometry,
                operation="PREPARE",
                policy=self._policy,
                now=now,
            )
            if (
                principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT
                and "READ" not in grant.operations
            ):
                # AI jobs must stay readable under the same grant that
                # prepares them; PREPARE-only rights cannot append an AI job.
                raise SpatialDataDomainError("PERMISSION_DENIED", 403)
            if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                # New AI jobs must already satisfy current unique metadata
                # readability: the unique READ grant must equal the exact
                # PREPARE grant, before any sweep or append. A conflicting
                # READ-only grant refuses creation instead of an unreadable
                # job. The selector plans no native windows here.
                selected = self._grants.select_metadata_current(
                    source=source, principal=principal, policy=self._policy, now=now
                )
                if selected != grant:
                    raise SpatialDataDomainError("PERMISSION_DENIED", 403)
            self._sweep(principal.organization_id, now)
            if (
                len(self._active.get(principal.organization_id, {}))
                >= self._policy.max_active_jobs_per_organization
            ):
                raise SpatialDataDomainError("CONCURRENCY_LIMIT_EXCEEDED", 429, True)
            job = SpatialDataFrozenJobV1(
                job_id="sdj-v1-" + str(uuid4()),
                organization_id=principal.organization_id,
                requester_principal_id=principal.principal_id,
                site_id=site_id,
                work_area_id=work_area_id,
                request=request,
                source=source,
                grant=grant,
                policy=self._policy,
                runtime=self._runtime,
                idempotency_key_hash=key_hash,
                request_fingerprint=fingerprint,
                created_at=now,
                deadline=now
                + timedelta(seconds=self._policy.resource_envelope.max_deadline_seconds),
            ).sealed()
            if (
                len(canonical_json_bytes(job.model_dump(by_alias=True, mode="json")))
                > self._policy.max_snapshot_bytes
            ):
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            self._current(JobRecord(job, 1, now), now)
            record = self._append(JobIssued(job_id=job.job_id, sequence=1, at=now, job=job))
            return self._view(record, now), True

    def get(self, *, job_id: str, principal: Principal, now: datetime) -> SpatialDataJobViewV1:
        if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
            return self.require_ai_metadata(job_id=job_id, principal=principal, now=now)
        with self._guard(now):
            return self._view(self._expire(self._history(job_id, principal), now), now)

    def list(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        cursor: str | None,
        limit: int,
        now: datetime,
    ) -> SpatialDataPageV1:
        with self._guard(now):
            self._scope(principal, site_id, work_area_id, permission=Permission.SPATIAL_DATA_READ)
            self._sources.require_history_scope(site_id, work_area_id, principal)
            if type(limit) is not int or not 1 <= limit <= min(200, self._policy.max_list_records):
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)
            indexed = self._by_scope.get((principal.organization_id, site_id, work_area_id), {})
            if len(indexed) > self._policy.max_list_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            ids = sorted(
                job_id
                for job_id in indexed
                if self._records[job_id].job.requester_principal_id == principal.principal_id
                or principal.kind is PrincipalKind.OPERATOR
                and principal.role is Role.ADMIN
            )
            if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                # AI filtering precedes pagination: denied candidates are
                # suppressed, while dependency/authority failures propagate.
                # The AI page additionally binds a strict projection snapshot;
                # generic V1 cursor semantics below are unchanged.
                return self._list_ai(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    principal=principal,
                    cursor=cursor,
                    limit=limit,
                    now=now,
                    ids=ids,
                )
            scope = _hash(
                canonical_json_bytes(
                    {
                        "organization": principal.organization_id,
                        "principal": principal.principal_id,
                        "site": site_id,
                        "area": work_area_id,
                    }
                )
            )
            start = 0
            if cursor is not None:
                try:
                    if type(cursor) is not str or len(cursor) > 2048:
                        raise ValueError("invalid cursor")
                    body = json.loads(
                        base64.b64decode(cursor.encode(), altchars=b"-_", validate=True)
                    )
                    if (
                        type(body) is not dict
                        or set(body) != {"scope", "last"}
                        or body["scope"] != scope
                    ):
                        raise ValueError("foreign cursor")
                    start = ids.index(body["last"]) + 1
                except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                    raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc
            selected = ids[start : start + limit]
            more = start + len(selected) < len(ids)
            next_cursor = (
                base64.urlsafe_b64encode(
                    canonical_json_bytes({"scope": scope, "last": selected[-1]})
                ).decode()
                if more
                else None
            )
            return SpatialDataPageV1(
                items=tuple(
                    self._view(self._expire(self._history(job_id, principal), now), now)
                    for job_id in selected
                ),
                next_cursor=next_cursor,
            )

    def _list_ai(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        cursor: str | None,
        limit: int,
        now: datetime,
        ids: Sequence[str],
    ) -> SpatialDataPageV1:
        """AI job page under a strict projection snapshot cursor.

        Caller holds the store guard through this read-only projection; no
        journal is mutated (expiry appends stay on the mutating paths). The
        cursor binds scope plus the current permitted projection and relevant
        grant bindings; a changed snapshot is a typed stale conflict, never a
        bypass. Generic cursor semantics are untouched.
        """
        # Common fresh AI scope/consent precedes enumeration: an empty or
        # fully filtered page never bypasses withdrawn consent into a
        # successful publication, while generic V1 history stays untouched.
        self._sources.require_ai_scope(site_id, work_area_id, principal)
        if cursor is not None and type(cursor) is not str:
            raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
        entries = self._ai_visible_entries(ids, principal, now)
        snapshot = self._ai_job_snapshot(entries)
        scope = scope_hash(
            organization_id=principal.organization_id,
            principal_id=principal.principal_id,
            site_id=site_id,
            work_area_id=work_area_id,
        )
        visible = [job_id for job_id, _, _ in entries]
        views = {job_id: view for job_id, view, _ in entries}
        if cursor is None:
            start = 0
        else:
            presented, last = decode_snapshot_cursor(cursor, scope=scope)
            if presented != snapshot:
                raise SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
            try:
                start = visible.index(last) + 1
            except ValueError as exc:
                raise SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422) from exc
        selected = visible[start : start + limit]
        more = start + len(selected) < len(visible)
        next_cursor = (
            encode_snapshot_cursor(scope=scope, snapshot=snapshot, last=selected[-1])
            if more
            else None
        )
        return SpatialDataPageV1(
            items=tuple(views[job_id] for job_id in selected),
            next_cursor=next_cursor,
        )

    def cancel(self, *, job_id: str, principal: Principal, now: datetime) -> SpatialDataJobViewV1:
        with self._guard(now):
            if principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                # Current AI metadata permission precedes any cancel append.
                self.require_ai_metadata(job_id=job_id, principal=principal, now=now)
            record = self._expire(
                self._history(job_id, principal, permission=Permission.SPATIAL_DATA_REQUEST), now
            )
            if record.state == "CANCELED":
                return self._view(record, now)
            if record.state not in ACTIVE:
                raise SpatialDataDomainError("REPORT_CONFLICT", 409)
            record = self._append(
                JobStateChanged(
                    job_id=job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    state="CANCELED",
                    reason="CANCELED",
                )
            )
            return self._view(record, now)

    def _worker(self, worker: Principal, now: datetime, record: JobRecord | None = None) -> None:
        if record is not None and worker.organization_id != record.job.organization_id:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        if (
            worker.kind is not PrincipalKind.SPATIAL_DATA_WORKER
            or worker.device_id is not None
            or Permission.SPATIAL_DATA_WORK not in principal_permissions(worker)
        ):
            raise SpatialDataDomainError("PERMISSION_DENIED", 403)
        if (
            worker.principal_id != self._activation.worker_principal_id
            or worker.organization_id != self._activation.organization_id
        ):
            raise SpatialDataDomainError("ACTIVATION_UNAVAILABLE", 503)
        self._lane(now, job=record.job if record else None)

    def _worker_record(self, job_id: str, worker: Principal, now: datetime) -> JobRecord:
        record = self._records.get(job_id)
        if record is None:
            raise SpatialDataDomainError("NOT_FOUND", 404)
        self._worker(worker, now, record)
        return self._expire(record, now)

    @staticmethod
    def _attempt(record: JobRecord, attempt: SpatialDataAttemptV1, now: datetime) -> None:
        attempt = SpatialDataAttemptV1.model_validate(attempt.model_dump())
        if (
            record.attempt is None
            or record.attempt != attempt
            or attempt.attempt_digest != attempt.canonical_digest()
        ):
            raise SpatialDataDomainError("FENCE_CONFLICT", 409)
        if record.state != "RUNNING":
            raise SpatialDataDomainError(
                "CANCELED" if record.state == "CANCELED" else "FENCE_CONFLICT", 409
            )
        if now >= attempt.lease_until:
            raise SpatialDataDomainError("LEASE_EXPIRED", 409)

    def pending(
        self, *, worker: Principal, limit: int, now: datetime
    ) -> tuple[SpatialDataFrozenJobV1, ...]:
        with self._guard(now):
            self._worker(worker, now)
            if type(limit) is not int or not 1 <= limit <= self._policy.max_pending_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)
            self._sweep(worker.organization_id, now)
            results = []
            for job_id in tuple(self._active.get(worker.organization_id, {})):
                record = self._records[job_id]
                if record.next_available_at is not None and now < record.next_available_at:
                    continue
                if (
                    record.state == "RUNNING"
                    and record.attempt is not None
                    and now < record.attempt.lease_until
                ):
                    continue
                if (
                    record.attempt is not None
                    and record.attempt.attempt_number >= record.job.policy.max_attempts
                ):
                    self._append(
                        JobStateChanged(
                            job_id=job_id,
                            sequence=record.sequence + 1,
                            at=now,
                            state="FAILED",
                            reason="LEASE_EXPIRED",
                        )
                    )
                    continue
                try:
                    self._current(record, now)
                except SpatialDataDomainError as exc:
                    # Omit only definite record-level ineligibility. The original job/grant
                    # remains historical, and leasing still rechecks its exact currentness.
                    # Missing authority, corrupt binding or an unknown failure closes polling.
                    if (exc.reason, exc.status_code) in {
                        ("ACCESS_REVOKED", 403),
                        ("ACCESS_EXPIRED", 403),
                        ("PERMISSION_DENIED", 403),
                        ("AI_EGRESS_DENIED", 403),
                        ("PROCESSING_LOCATION_DENIED", 403),
                        ("SOURCE_UNSEALED", 403),
                        ("SOURCE_NOT_MEASURED", 403),
                        ("NOT_FOUND", 404),
                    }:
                        continue
                    raise
                results.append(record.job.model_copy(deep=True))
                if len(results) == limit:
                    break
            return tuple(results)

    def lease(
        self,
        *,
        job_id: str,
        worker: Principal,
        instance_id: str,
        acquisition_id: str,
        now: datetime,
    ) -> SpatialDataAttemptV1:
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._current(record, now)
            if instance_id != self._activation.worker_instance_id:
                raise SpatialDataDomainError("ACTIVATION_UNAVAILABLE", 503)
            if (
                type(acquisition_id) is not str
                or not acquisition_id
                or len(acquisition_id.encode()) > self._policy.max_idempotency_key_bytes
                or any(ord(c) < 32 or ord(c) == 127 for c in acquisition_id)
            ):
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            acquisition_hash = _hash(acquisition_id.encode())
            old = record.attempt
            if record.state not in ACTIVE:
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            if old is not None and record.state == "RUNNING" and now < old.lease_until:
                if (old.worker_principal_id, old.worker_instance_id, old.acquisition_key_hash) == (
                    worker.principal_id,
                    instance_id,
                    acquisition_hash,
                ):
                    return old.model_copy(deep=True)
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            if acquisition_hash in record.acquisitions:
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            if old is not None and old.attempt_number >= record.job.policy.max_attempts:
                self._append(
                    JobStateChanged(
                        job_id=job_id,
                        sequence=record.sequence + 1,
                        at=now,
                        state="FAILED",
                        reason="LEASE_EXPIRED",
                    )
                )
                raise SpatialDataDomainError("LEASE_EXPIRED", 409)
            if record.next_available_at is not None and now < record.next_available_at:
                raise SpatialDataDomainError("NOT_READY", 409, True)
            assert record.job.job_digest is not None
            attempt = SpatialDataAttemptV1(
                job_id=job_id,
                frozen_job_digest=record.job.job_digest,
                worker_principal_id=worker.principal_id,
                worker_instance_id=instance_id,
                acquisition_key_hash=acquisition_hash,
                fence=old.fence + 1 if old else 1,
                attempt_number=old.attempt_number + 1 if old else 1,
                acquired_at=now,
                lease_until=min(
                    now + timedelta(seconds=record.job.policy.lease_seconds),
                    record.job.deadline,
                    record.job.grant.valid_until,
                    self._activation.valid_until,
                ),
            ).sealed()
            self._append(
                JobLeased(job_id=job_id, sequence=record.sequence + 1, at=now, attempt=attempt)
            )
            return attempt.model_copy(deep=True)

    def renew(
        self, *, job_id: str, worker: Principal, attempt: SpatialDataAttemptV1, now: datetime
    ) -> SpatialDataAttemptV1:
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._attempt(record, attempt, now)
            self._current(record, now)
            renewed = attempt.model_copy(
                update={
                    "lease_until": min(
                        now + timedelta(seconds=record.job.policy.lease_seconds),
                        record.job.deadline,
                        record.job.grant.valid_until,
                        self._activation.valid_until,
                    ),
                    "attempt_digest": None,
                }
            ).sealed()
            if renewed != attempt:
                self._append(
                    JobRenewed(job_id=job_id, sequence=record.sequence + 1, at=now, attempt=renewed)
                )
            return renewed.model_copy(deep=True)

    def worker_input(
        self, *, job_id: str, worker: Principal, attempt: SpatialDataAttemptV1, now: datetime
    ) -> SpatialDataFrozenJobV1:
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._attempt(record, attempt, now)
            self._current(record, now)
            return record.job.model_copy(deep=True)

    def resolve_worker_attempt(
        self,
        *,
        job_id: str,
        worker: Principal,
        instance_id: str,
        attempt_digest: str,
        now: datetime,
    ) -> SpatialDataAttemptV1:
        """Header-only input lookup can resolve only the current exact live attempt."""
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            attempt = record.attempt
            if (
                attempt is None
                or attempt.worker_instance_id != instance_id
                or attempt.attempt_digest != attempt_digest
            ):
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            self._attempt(record, attempt, now)
            self._current(record, now)
            return attempt.model_copy(deep=True)

    def reserved_output(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        upload_digest: str,
        now: datetime,
    ) -> tuple[SpatialDataOutputTarget, SpatialDataObjectObservation | None] | None:
        """Resolve owned output; completed retries retain the accepted pinned observation."""
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._current(record, now)
            if record.state == "COMPLETED":
                if attempt != record.attempt:
                    raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            else:
                self._attempt(record, attempt, now)
            owned = record.outputs.get(attempt.fence_digest())
            if owned is None:
                return None
            if upload_digest != owned.upload_digest:
                raise SpatialDataDomainError("REPORT_CONFLICT", 409)
            return owned.target, owned.observation

    def reserve_output(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        receipt: SpatialDataReceiptV1,
        expires_at: datetime,
        now: datetime,
    ) -> SpatialDataOutputTarget:
        with self._guard(now):
            require_utc(expires_at)
            record = self._worker_record(job_id, worker, now)
            self._attempt(record, attempt, now)
            self._current(record, now)
            fence = attempt.fence_digest()
            owned = record.outputs.get(fence)
            if now >= expires_at:
                raise SpatialDataDomainError("LEASE_EXPIRED", 409)
            try:
                declaration = SpatialDataUploadDeclarationV1(
                    attempt=attempt,
                    receipt=receipt,
                    sha256=receipt.output_sha256,
                    size_bytes=receipt.output_size_bytes,
                    content_type="image/tiff",
                ).sealed()
                assert declaration.upload_digest is not None
                if owned is not None:
                    if (
                        receipt != owned.receipt
                        or expires_at != owned.target.expires_at
                        or declaration.upload_digest != owned.upload_digest
                    ):
                        raise SpatialDataDomainError("REPORT_CONFLICT", 409)
                    return owned.target
                event = JobOutputReserved(
                    job_id=job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    receipt=receipt,
                    object_key=owned_key(record.job, attempt),
                    expires_at=expires_at,
                    upload_digest=declaration.upload_digest,
                )
                updated = self._append(event)
            except (ValueError, ValidationError) as exc:
                raise SpatialDataDomainError("REPORT_CONFLICT", 409) from exc
            return updated.outputs[fence].target

    def complete(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        upload_digest: str,
        observation: SpatialDataObjectObservation,
        now: datetime,
    ) -> SpatialDataJobViewV1:
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._current(record, now)
            if record.state == "COMPLETED":
                assert record.accepted_fence is not None
                owned = record.outputs[record.accepted_fence]
                if (
                    attempt != record.attempt
                    or upload_digest != owned.upload_digest
                    or observation != owned.observation
                ):
                    raise SpatialDataDomainError("REPORT_CONFLICT", 409)
                return self._view(record, now)
            self._attempt(record, attempt, now)
            if not isinstance(observation, SpatialDataObjectObservation):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 409)
            try:
                record = self._append(
                    JobCompleted(
                        job_id=job_id,
                        sequence=record.sequence + 1,
                        at=now,
                        upload_digest=upload_digest,
                        object_key=observation.object_key,
                        version_id=observation.version_id,
                        size_bytes=observation.size_bytes,
                        sha256=observation.sha256,
                        content_type=observation.content_type,
                    )
                )
            except (ValueError, ValidationError) as exc:
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 409) from exc
            return self._view(record, now)

    def fail(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SpatialDataAttemptV1,
        reason: str,
        now: datetime,
    ) -> SpatialDataJobViewV1:
        with self._guard(now):
            record = self._worker_record(job_id, worker, now)
            self._attempt(record, attempt, now)
            validated_reason = SpatialDataDomainError(reason, 422).reason
            retry_at = now + timedelta(seconds=record.job.policy.min_retry_backoff_seconds)
            retry = (
                reason in TRANSIENT
                and attempt.attempt_number < record.job.policy.max_attempts
                and retry_at < record.job.deadline
            )
            record = self._append(
                JobStateChanged(
                    job_id=job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    state="QUEUED" if retry else "FAILED",
                    reason=validated_reason,
                    next_available_at=retry_at if retry else None,
                    attempt=attempt,
                )
            )
            return self._view(record, now)

    def require_download(
        self, *, job_id: str, principal: Principal, now: datetime
    ) -> DownloadOutput:
        """Fresh byte authority is separate from historic metadata or scoped ADMIN visibility."""
        with self._guard(now):
            record = self._history(job_id, principal)
            job = record.job
            if job.requester_principal_id != principal.principal_id:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            if record.completed_at is not None and now >= record.completed_at + timedelta(
                seconds=job.policy.retention_seconds
            ):
                raise SpatialDataDomainError("RETENTION_EXPIRED", 410)
            if record.state != "COMPLETED" or record.accepted_fence is None:
                raise SpatialDataDomainError("NOT_READY", 409)
            self._current(record, now, operation="READ")
            # Fresh credential claims must pass as well as resolved requester authority.
            source = self._sources.require_current(source=job.source, principal=principal, now=now)
            measurements = source.inspection.measurements
            assert measurements is not None
            geometry = plan_external_native_window(
                requested_bounds=job.request.requested_bounds,
                measurements=measurements,
                requested_crs_digest=job.request.observed_crs_digest,
            )
            grant = self._grants.require_current(
                grant_id=job.grant.grant_id,
                revision=job.grant.revision,
                source=source,
                principal=principal,
                purpose=job.request.purpose,
                requested_bounds=job.request.requested_bounds,
                geometry=geometry,
                operation="READ",
                policy=job.policy,
                now=now,
            )
            if grant != job.grant:
                raise SpatialDataDomainError("ACCESS_REVOKED", 403)
            output = record.outputs[record.accepted_fence]
            if output.observation is None:
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            return DownloadOutput(
                job.model_copy(deep=True),
                output.target,
                output.observation,
                output.receipt.model_copy(deep=True),
            )

    def cleanup_pending(self, *, limit: int, now: datetime) -> tuple[CleanupCandidate, ...]:
        """Trusted owner-only projection, never an HTTP deletion permission or storage listing.

        Complete ownership index is bounded before enumeration. The downstream executor
        must recheck the exact candidate under this coordinator before each deletion.
        """
        with self._guard(now):
            self._ensure_open()
            if type(limit) is not int or not 1 <= limit <= self._policy.max_pending_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 422)
            if len(self._outputs) > self._policy.max_list_records:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            result = []
            for job_id, fence in self._outputs:
                record = self._records[job_id]
                owned = record.outputs[fence]
                ready_at = cleanup_ready_at(record, fence)
                status = owned.cleanup
                if status is not None:
                    if (
                        status.state == "STARTED"
                        and status.attempt_number >= record.job.policy.max_cleanup_attempts
                        and now
                        >= status.started_at
                        + timedelta(seconds=record.job.policy.cleanup_deadline_seconds)
                    ):
                        self._append(
                            JobCleanupChanged(
                                job_id=job_id,
                                sequence=record.sequence + 1,
                                at=now,
                                fence_digest=fence,
                                cleanup_id=status.cleanup_id,
                                attempt_number=status.attempt_number,
                                state="FAILED",
                                reason="DEADLINE_EXCEEDED",
                            )
                        )
                        continue
                    if (
                        status.state == "COMPLETED"
                        or status.attempt_number >= record.job.policy.max_cleanup_attempts
                    ):
                        continue
                    ready_at = max(
                        ready_at,
                        status.started_at
                        + timedelta(seconds=record.job.policy.cleanup_deadline_seconds)
                        if status.state == "STARTED"
                        else status.updated_at
                        + timedelta(seconds=record.job.policy.min_retry_backoff_seconds),
                    )
                if now < ready_at:
                    continue
                result.append(
                    CleanupCandidate(
                        owned.target,
                        owned.observation,
                        ready_at,
                        record.job.policy.model_copy(deep=True),
                    )
                )
                if len(result) == limit:
                    break
            return tuple(result)

    def reserve_cleanup(
        self, *, candidate: CleanupCandidate, now: datetime
    ) -> CleanupHandle | None:
        with self._guard(now):
            self._ensure_open()
            record = self._records.get(candidate.target.job_id)
            fence = candidate.target.attempt_digest
            if (
                record is None
                or fence not in record.outputs
                or record.outputs[fence].target != candidate.target
            ):
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            owned = record.outputs[fence]
            if owned.observation != candidate.observation or record.job.policy != candidate.policy:
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            old = owned.cleanup
            if now < cleanup_ready_at(record, fence):
                return None
            if old is not None and (
                old.state == "COMPLETED"
                or old.attempt_number >= record.job.policy.max_cleanup_attempts
                or old.state == "STARTED"
                and now
                < old.started_at + timedelta(seconds=record.job.policy.cleanup_deadline_seconds)
                or old.state == "FAILED"
                and now
                < old.updated_at + timedelta(seconds=record.job.policy.min_retry_backoff_seconds)
            ):
                return None
            cleanup_id = str(uuid4())
            attempt = old.attempt_number + 1 if old else 1
            record = self._append(
                JobCleanupChanged(
                    job_id=record.job.job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    fence_digest=fence,
                    cleanup_id=cleanup_id,
                    attempt_number=attempt,
                    state="STARTED",
                )
            )
            return CleanupHandle(
                record.job.model_copy(deep=True), record.outputs[fence], cleanup_id, attempt, now
            )

    def require_cleanup(self, *, handle: CleanupHandle, now: datetime) -> None:
        with self._guard(now):
            self._ensure_open()
            record = self._records.get(handle.job.job_id)
            owned = record.outputs.get(handle.output.target.attempt_digest) if record else None
            if (
                record is None
                or owned is None
                or owned.cleanup is None
                or record.job != handle.job
                or owned.target != handle.output.target
                or owned.cleanup.cleanup_id != handle.cleanup_id
                or owned.cleanup.attempt_number != handle.attempt_number
                or owned.cleanup.state != "STARTED"
            ):
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)
            if now >= handle.started_at + timedelta(
                seconds=record.job.policy.cleanup_deadline_seconds
            ):
                raise SpatialDataDomainError("LEASE_EXPIRED", 409)
            if now < cleanup_ready_at(record, owned.target.attempt_digest):
                raise SpatialDataDomainError("FENCE_CONFLICT", 409)

    def finish_cleanup(
        self, *, handle: CleanupHandle, now: datetime, reason: SpatialDataReasonV1 | None = None
    ) -> None:
        with self._guard(now):
            if reason is None:
                self.require_cleanup(handle=handle, now=now)
            record = self._records.get(handle.job.job_id)
            if record is None:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            try:
                self._append(
                    JobCleanupChanged(
                        job_id=record.job.job_id,
                        sequence=record.sequence + 1,
                        at=now,
                        fence_digest=handle.output.target.attempt_digest,
                        cleanup_id=handle.cleanup_id,
                        attempt_number=handle.attempt_number,
                        state="FAILED" if reason else "COMPLETED",
                        reason=reason,
                    )
                )
            except ValueError as exc:
                raise SpatialDataDomainError("FENCE_CONFLICT", 409) from exc

    def cleanup_status(self, *, job_id: str) -> tuple[CleanupStatus, ...]:
        """Trusted local diagnostics only; never a cross-tenant public endpoint."""
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise SpatialDataDomainError("NOT_FOUND", 404)
            return tuple(
                output.cleanup for output in record.outputs.values() if output.cleanup is not None
            )
