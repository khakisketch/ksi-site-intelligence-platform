"""Typed AI authorization closures; the response owns the final send-time gate.

``SpatialDataAiEgress`` binds the exact mounted Core participants and builds
guarded pre-header metadata responses for AI job views and pages. It never
accepts caller-produced Principal authority: every send refreshes genuine
request credentials and rechecks current source/grant/consent rights.
Discovery and snapshot-cursor page preparation are added by Task3.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from time import monotonic

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.spatial_data import SpatialDataJobViewV1, SpatialDataPageV1
from ksi_event_contracts.spatial_data_ai import (
    SpatialDataAssetPageV1,
    SpatialDataAssetViewV1,
)
from pydantic import BaseModel

from ksi_core.domains.external.delivery.asset_discovery import SpatialDataAssetDiscovery
from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.errors import (
    SpatialDataAiDomainError,
    SpatialDataDomainError,
)
from ksi_core.domains.external.delivery.grants import SpatialDataGrantAuthorizer
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.metadata_audit import (
    MetadataAuditOperationV1,
    SpatialDataMetadataAuditStore,
)
from ksi_core.domains.external.delivery.metadata_response import SpatialDataAiMetadataResponse
from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal


class SpatialDataAiEgress:
    """Guarded AI job-response publication over exact Core participants."""

    def __init__(
        self,
        jobs: SpatialDataJobStore,
        sources: SpatialDataSourceResolver,
        grants: SpatialDataGrantAuthorizer,
        audit: SpatialDataMetadataAuditStore,
        clock: Callable[[], datetime],
        discovery: SpatialDataAssetDiscovery | None = None,
    ) -> None:
        if (
            not isinstance(jobs, SpatialDataJobStore)
            or not isinstance(sources, SpatialDataSourceResolver)
            or not isinstance(grants, SpatialDataGrantAuthorizer)
            or not isinstance(audit, SpatialDataMetadataAuditStore)
        ):
            raise ValueError("AI egress requires genuine Core delivery participants")
        if not (jobs.coordinator is sources.coordinator and jobs.coordinator is grants.coordinator):
            raise ValueError("AI egress participants must share one coordinator")
        if not jobs.uses_exact_participants(grants=grants, sources=sources):
            raise ValueError("AI egress requires the same mounted Core participants")
        if audit.policy != jobs.policy:
            raise ValueError("AI egress audit must bind the exact data policy")
        if discovery is not None and (
            not isinstance(discovery, SpatialDataAssetDiscovery)
            or not discovery.uses_exact_participants(sources=sources, grants=grants, jobs=jobs)
        ):
            raise ValueError("AI egress discovery must bind the same mounted Core participants")
        if not callable(clock):
            raise ValueError("AI egress requires a clock")
        self._jobs = jobs
        self._sources = sources
        self._grants = grants
        self._audit = audit
        self._clock = clock
        self._discovery = discovery

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._jobs.coordinator

    @property
    def audit(self) -> SpatialDataMetadataAuditStore:
        return self._audit

    @property
    def discovery(self) -> SpatialDataAssetDiscovery | None:
        return self._discovery

    def uses_exact_participants(
        self,
        *,
        jobs: SpatialDataJobStore,
        sources: SpatialDataSourceResolver,
        grants: SpatialDataGrantAuthorizer,
        audit: SpatialDataMetadataAuditStore,
    ) -> bool:
        return (
            jobs is self._jobs
            and sources is self._sources
            and grants is self._grants
            and audit is self._audit
        )

    def _canonical(self, model: BaseModel) -> bytes:
        body = canonical_json_bytes(model.model_dump(by_alias=True, mode="json"))
        if len(body) > self._jobs.policy.max_json_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return body

    def _check_scope(
        self, *, credentials: SpatialDataCredentialCurrentness, site_id: str, work_area_id: str
    ) -> None:
        if not isinstance(credentials, SpatialDataCredentialCurrentness):
            raise ValueError("AI responses require genuine request credentials")
        if (
            type(site_id) is not str
            or type(work_area_id) is not str
            or not site_id
            or not work_area_id
        ):
            raise ValueError("AI responses require explicit scope identifiers")

    def prepare_job_response(
        self,
        *,
        credentials: SpatialDataCredentialCurrentness,
        site_id: str,
        work_area_id: str,
        view: SpatialDataJobViewV1,
        status: int,
        operation: MetadataAuditOperationV1,
    ) -> SpatialDataAiMetadataResponse:
        """Guarded single-view response; rechecks before headers, never stale.

        The caller view routes job identity and scope only. The published
        bytes are reselected here from the genuine owner store through the
        locally current owner actor (expected ids only — no remote credential
        refresh in prepare) and frozen as a private snapshot bound to the
        immutable issued-job identity plus this store's ephemeral seal, so a
        forged caller view publishes the real owner projection or refuses —
        never fake fields. The bounded metadata-response stages keep sole
        ownership of the genuine request-credential refresh. Every
        header/body refresh re-proves current rights plus that binding and
        returns the SELECTED bytes to the unchanged guarded-send machinery;
        legitimate worker progress after capture therefore publishes the
        truthful point-in-time instead of a false whole-view conflict, and the
        audit hashes exactly the bytes attempted for emission.
        """
        self._check_scope(credentials=credentials, site_id=site_id, work_area_id=work_area_id)
        if not isinstance(view, SpatialDataJobViewV1):
            raise ValueError("AI job responses publish typed job views only")
        if (view.site_id, view.work_area_id) != (site_id, work_area_id):
            raise ValueError("AI job scope must match the authorized view")
        if operation not in ("CREATE_JOB", "GET_JOB", "CANCEL_JOB"):
            raise ValueError(f"single-view AI operation not permitted: {operation!r}")
        expected_principal_id, expected_organization_id = credentials.expected_identity()
        snapshot = self._jobs.seal_ai_job_snapshot(
            job_id=view.job_id,
            expected_principal_id=expected_principal_id,
            expected_organization_id=expected_organization_id,
            now=self._clock(),
        )
        return self._prepare(
            credentials=credentials,
            site_id=site_id,
            work_area_id=work_area_id,
            model=snapshot.view,
            status=status,
            operation=operation,
            recheck=lambda principal: self._jobs.verify_ai_job_snapshot(
                snapshot=snapshot, principal=principal, now=self._clock()
            ),
        )

    def prepare_job_page_response(
        self,
        *,
        credentials: SpatialDataCredentialCurrentness,
        site_id: str,
        work_area_id: str,
        page: SpatialDataPageV1,
        cursor: str | None,
        limit: int,
        operation: MetadataAuditOperationV1 = "LIST_JOBS",
    ) -> SpatialDataAiMetadataResponse:
        """Guarded page response under current V1 cursor semantics.

        Task3 replaces the AI-only cursor with a strict filtered snapshot
        variant; the generic current V1 cursor is unchanged.
        """
        self._check_scope(credentials=credentials, site_id=site_id, work_area_id=work_area_id)
        if not isinstance(page, SpatialDataPageV1):
            raise ValueError("AI page responses publish typed job pages only")
        if operation != "LIST_JOBS":
            raise ValueError(f"page AI operation not permitted: {operation!r}")
        if cursor is not None and type(cursor) is not str:
            raise ValueError("AI page cursor must be an opaque string or null")
        if type(limit) is not int:
            raise ValueError("AI page limit must be an integer")
        return self._prepare(
            credentials=credentials,
            site_id=site_id,
            work_area_id=work_area_id,
            model=page,
            status=200,
            operation=operation,
            recheck=lambda principal: self._canonical(
                self._jobs.list(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    principal=principal,
                    cursor=cursor,
                    limit=limit,
                    now=self._clock(),
                )
            ),
        )

    def prepare_asset_response(
        self,
        *,
        credentials: SpatialDataCredentialCurrentness,
        site_id: str,
        work_area_id: str,
        view: SpatialDataAssetViewV1,
        operation: MetadataAuditOperationV1 = "GET_ASSET",
    ) -> SpatialDataAiMetadataResponse:
        """Guarded single-asset response; rechecks current grant-filtered projection at send."""
        self._check_scope(credentials=credentials, site_id=site_id, work_area_id=work_area_id)
        if not isinstance(view, SpatialDataAssetViewV1):
            raise ValueError("AI asset responses publish typed asset views only")
        if (view.site_id, view.work_area_id) != (site_id, work_area_id):
            raise ValueError("AI asset scope must match the authorized view")
        if operation != "GET_ASSET":
            raise ValueError(f"single-asset AI operation not permitted: {operation!r}")
        discovery = self._discovery
        if discovery is None:
            raise ValueError("AI asset responses require bound discovery participants")
        return self._prepare(
            credentials=credentials,
            site_id=site_id,
            work_area_id=work_area_id,
            model=view,
            status=200,
            operation=operation,
            preflight=lambda principal: self._canonical(
                discovery.get(
                    site_id=site_id,
                    work_area_id=work_area_id,
                    asset_ref=view.asset_ref,
                    principal=principal,
                    now=self._clock(),
                )
            ),
            recheck=lambda principal: discovery.recheck_view(
                view=view, principal=principal, now=self._clock()
            ),
        )

    def prepare_asset_page_response(
        self,
        *,
        credentials: SpatialDataCredentialCurrentness,
        site_id: str,
        work_area_id: str,
        page: SpatialDataAssetPageV1,
        cursor: str | None,
        limit: int,
        operation: MetadataAuditOperationV1 = "LIST_ASSETS",
    ) -> SpatialDataAiMetadataResponse:
        """Guarded asset-page response under the strict snapshot cursor."""
        self._check_scope(credentials=credentials, site_id=site_id, work_area_id=work_area_id)
        if not isinstance(page, SpatialDataAssetPageV1):
            raise ValueError("AI asset page responses publish typed asset pages only")
        if operation != "LIST_ASSETS":
            raise ValueError(f"page AI operation not permitted: {operation!r}")
        if cursor is not None and type(cursor) is not str:
            raise ValueError("AI page cursor must be an opaque string or null")
        if type(limit) is not int:
            raise ValueError("AI page limit must be an integer")
        discovery = self._discovery
        if discovery is None:
            raise ValueError("AI asset responses require bound discovery participants")
        # The send-time preflight publishes the gate context for its own
        # projection; the later header/body gates re-project locally from
        # that context and never resolve the remote authority again. The cell
        # is filled by the ordered preflight stage before any gate runs; an
        # empty cell fails closed, never stale.
        gate: dict[str, dict[str, object] | None] = {"context": None}

        def preflight(principal: Principal) -> bytes:
            page, gate_context = discovery.list_projection(
                site_id=site_id,
                work_area_id=work_area_id,
                principal=principal,
                limit=limit,
                cursor=cursor,
                now=self._clock(),
            )
            gate["context"] = gate_context
            return self._canonical(page)

        def gate_recheck(principal: Principal) -> bytes:
            context = gate["context"]
            if context is None:
                raise SpatialDataAiDomainError("REPORT_CONFLICT", 409)
            return discovery.recheck_page(
                site_id=site_id,
                work_area_id=work_area_id,
                principal=principal,
                limit=limit,
                cursor=cursor,
                gate=context,
                now=self._clock(),
            )

        return self._prepare(
            credentials=credentials,
            site_id=site_id,
            work_area_id=work_area_id,
            model=page,
            status=200,
            operation=operation,
            preflight=preflight,
            recheck=gate_recheck,
        )

    def _prepare(
        self,
        *,
        credentials: SpatialDataCredentialCurrentness,
        site_id: str,
        work_area_id: str,
        model: BaseModel,
        status: int,
        operation: MetadataAuditOperationV1,
        recheck: Callable[[Principal], bytes],
        preflight: Callable[[Principal], bytes] | None = None,
    ) -> SpatialDataAiMetadataResponse:
        body = self._canonical(model)
        policy = self._jobs.policy
        started = self._clock()
        mono_started = monotonic()

        def audit(principal: Principal, fresh: bytes) -> None:
            self._audit.append(
                principal=principal,
                site_id=site_id,
                work_area_id=work_area_id,
                operation=operation,
                payload_digest="sha256:" + hashlib.sha256(fresh).hexdigest(),
                reason=None,
                now=self._clock(),
            )

        return SpatialDataAiMetadataResponse(
            body=body,
            status_code=status,
            credentials=credentials,
            clock=self._clock,
            max_json_bytes=policy.max_json_bytes,
            started=started,
            deadline_seconds=policy.stream_deadline_seconds,
            mono_started=mono_started,
            recheck=recheck,
            audit=audit,
            preflight=preflight,
        )
