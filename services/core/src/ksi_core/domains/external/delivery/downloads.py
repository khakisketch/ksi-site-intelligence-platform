"""Full-hash private spool and live exact-owner byte authorization, never a redirect."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException
from ksi_event_contracts.spatial_data import SpatialDataReasonV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from starlette.responses import Response

from ksi_core.domains.external.delivery.audit import SpatialDataAuditEventV1, SpatialDataAuditStore
from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.job_projection import DownloadOutput
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.storage import SpatialDataStoragePort
from ksi_core.identity.auth import Principal


def _private_root(path: Path) -> int:
    """Pin existing protected directory chain; never follow symlinked ancestors."""
    descriptors: list[int] = []
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("explicit absolute private spool root required")
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for part in path.parts[1:]:
            p = os.fstat(parent)
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            descriptors.append(child)
            c = os.fstat(child)
            if (
                c.st_uid not in (0, os.geteuid())
                or p.st_mode & 0o022
                and not (p.st_mode & stat.S_ISVTX and c.st_uid == os.geteuid())
            ):
                raise ValueError("substitutable spool ancestor")
            parent = child
        root = os.fstat(parent)
        if (
            root.st_uid != os.geteuid()
            or root.st_gid != os.getegid()
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise ValueError("spool root not owner private")
        descriptors.remove(parent)
        return parent
    except (OSError, ValueError) as exc:
        raise SpatialDataDomainError("PRIVATE_WORKSPACE_UNAVAILABLE", 503) from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


class SpatialDataPreparedDownload:
    def __init__(
        self,
        *,
        service: SpatialDataDownloadService,
        output: DownloadOutput,
        credentials: SpatialDataCredentialCurrentness,
        spool: BinaryIO,
        session_id: str,
        started: float,
        resources: ExitStack,
    ):
        self.service, self.output, self.credentials, self.spool = (
            service,
            output,
            credentials,
            spool,
        )
        self.session_id, self.started = session_id, started
        self.size_bytes, self.sha256 = output.observation.size_bytes, output.observation.sha256
        self.policy = output.job.policy
        self.closed = False
        self.resources = resources

    def authorize(self, now: datetime) -> Principal:
        if self.closed:
            raise SpatialDataDomainError("CURRENTNESS_UNAVAILABLE", 503)
        self.check_deadline()
        principal = self.credentials.resolve(now=now)  # Remote auth stays outside coordinator lock.
        job = self.output.job
        if (principal.principal_id, principal.organization_id) != (
            job.requester_principal_id,
            job.organization_id,
        ):
            raise SpatialDataDomainError("NOT_FOUND", 404)
        current = self.service.jobs.require_download(
            job_id=job.job_id, principal=principal, now=now
        )
        if current != self.output:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        return principal

    def check_deadline(self) -> None:
        if monotonic() - self.started >= self.policy.stream_deadline_seconds:
            raise SpatialDataDomainError("DEADLINE_EXCEEDED", 503)

    def audit(
        self, action: str, *, sent_bytes: int = 0, reason: SpatialDataReasonV1 | None = None
    ) -> None:
        self.service._audit(
            self.output, self.session_id, action, sent_bytes=sent_bytes, reason=reason
        )

    def iter_chunks(self) -> Iterator[bytes]:
        self.spool.seek(0)
        while self.spool.tell() < self.size_bytes:
            self.authorize(self.service.clock())
            yield self.read_spool_chunk()

    def read_spool_chunk(self) -> bytes:
        """Local bounded read only; ASGI caller separately reauthenticates off its loop."""
        self.check_deadline()
        remaining = self.size_bytes - self.spool.tell()
        if remaining <= 0:
            return b""
        chunk = self.spool.read(min(self.policy.stream_chunk_bytes, remaining))
        if type(chunk) is not bytes or not chunk:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        return chunk

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.resources.close()
            finally:
                self.service._release(self.output.job.organization_id, self.size_bytes)


class SpatialDataDownloadService:
    def __init__(
        self,
        *,
        jobs: SpatialDataJobStore,
        storage: SpatialDataStoragePort,
        audit: SpatialDataAuditStore,
        policy: SpatialDataPolicyV1,
        spool_root: Path,
        clock: Callable[[], datetime],
    ):
        policy = SpatialDataPolicyV1.model_validate(policy.__dict__)
        if (
            policy.policy_digest != policy.canonical_digest()
            or jobs.policy != policy
            or audit.policy != policy
        ):
            raise ValueError("exact connected sealed download policy required")
        root = _private_root(spool_root)
        os.close(root)
        self.jobs, self.storage, self.audit_store, self.policy, self.spool_root, self.clock = (
            jobs,
            storage,
            audit,
            policy,
            spool_root,
            clock,
        )
        self._lock = RLock()
        self._counts: dict[str, int] = {}
        self._reserved = 0

    @property
    def active_downloads(self) -> int:
        with self._lock:
            return sum(self._counts.values())

    @property
    def reserved_bytes(self) -> int:
        with self._lock:
            return self._reserved

    def _reserve(self, org: str, size: int) -> None:
        with self._lock:
            if (
                self._counts.get(org, 0) >= self.policy.max_active_downloads_per_organization
                or sum(self._counts.values()) >= self.policy.max_pending_records
            ):
                raise SpatialDataDomainError("CONCURRENCY_LIMIT_EXCEEDED", 429)
            if (
                self._reserved
                + size
                + self.audit_store.disk_reserved_bytes()
                > self.policy.resource_envelope.max_workspace_bytes
            ):
                raise SpatialDataDomainError("WORKSPACE_LIMIT_EXCEEDED", 429)
            self._counts[org] = self._counts.get(org, 0) + 1
            self._reserved += size

    def _release(self, org: str, size: int) -> None:
        with self._lock:
            self._counts[org] -= 1
            if not self._counts[org]:
                del self._counts[org]
            self._reserved -= size

    def _audit(
        self,
        output: DownloadOutput,
        session: str,
        action: str,
        *,
        sent_bytes: int = 0,
        reason: SpatialDataReasonV1 | None = None,
    ) -> None:
        job = output.job
        self.audit_store.append(
            SpatialDataAuditEventV1.model_validate(
                dict(
                    event_id=str(uuid4()),
                    session_id=session,
                    organization_id=job.organization_id,
                    principal_id=job.requester_principal_id,
                    site_id=job.site_id,
                    work_area_id=job.work_area_id,
                    job_id=job.job_id,
                    at=self.clock(),
                    action=action,
                    expected_size_bytes=output.observation.size_bytes,
                    output_sha256=output.observation.sha256,
                    sent_bytes=sent_bytes,
                    reason=reason,
                )
            ).sealed()
        )

    def prepare(
        self,
        *,
        job_id: str,
        principal: Principal,
        credentials: SpatialDataCredentialCurrentness,
        now: datetime,
    ) -> SpatialDataPreparedDownload:
        fresh = credentials.resolve(now=now)
        if (fresh.principal_id, fresh.organization_id) != (
            principal.principal_id,
            principal.organization_id,
        ):
            raise SpatialDataDomainError("NOT_FOUND", 404)
        output = self.jobs.require_download(job_id=job_id, principal=fresh, now=now)
        size = output.observation.size_bytes
        if output.job.policy != self.policy or size > min(
            self.policy.max_output_bytes, self.policy.max_stream_bytes
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        if getattr(self.audit_store, "operation_scope", "full") == "history-only":
            # Recovery mode: retain and serve history, deny every new byte
            # admission before reservation, spool, storage or journal writes.
            # Authorization and scope checks above keep their exact precedence.
            raise SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
        org, session, started = output.job.organization_id, str(uuid4()), monotonic()
        self._reserve(org, size)
        spool: BinaryIO | None = None
        admitted = False
        prepared: SpatialDataPreparedDownload | None = None
        resources = ExitStack()
        try:
            self._audit(output, session, "DOWNLOAD_ADMITTED")
            admitted = True
            root = _private_root(self.spool_root)
            try:
                spool = resources.enter_context(
                    tempfile.TemporaryFile(mode="w+b", dir=f"/proc/self/fd/{root}")  # noqa: SIM115 -- ASGI lifetime owns ExitStack
                )
            finally:
                os.close(root)
            prepared = SpatialDataPreparedDownload(
                service=self,
                output=output,
                credentials=credentials,
                spool=spool,
                session_id=session,
                started=started,
                resources=resources,
            )
            hashed, received = hashlib.sha256(), 0
            with self.storage.open_version(
                output.observation,
                chunk_bytes=self.policy.stream_chunk_bytes,
                deadline=now + timedelta(seconds=self.policy.stream_deadline_seconds),
            ) as chunks:
                for chunk in chunks:
                    prepared.authorize(self.clock())
                    if (
                        type(chunk) is not bytes
                        or not 0 < len(chunk) <= self.policy.stream_chunk_bytes
                        or received + len(chunk) > size
                    ):
                        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                    if spool.write(chunk) != len(chunk):
                        raise SpatialDataDomainError("PRIVATE_WORKSPACE_UNAVAILABLE", 503)
                    hashed.update(chunk)
                    received += len(chunk)
            if received != size or "sha256:" + hashed.hexdigest() != output.observation.sha256:
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            spool.flush()
            spool.seek(0)
            prepared.authorize(self.clock())
            return prepared
        except BaseException as exc:
            try:
                if admitted:
                    reason = (
                        exc.reason
                        if isinstance(exc, SpatialDataDomainError)
                        else "PERMISSION_DENIED"
                        if isinstance(exc, HTTPException)
                        else "CANCELED"
                        if not isinstance(exc, Exception)
                        else "STORAGE_UNAVAILABLE"
                    )
                    self._audit(output, session, "DENIED", reason=reason)
            finally:
                if prepared is not None:
                    prepared.close()
                else:
                    resources.close()
                    self._release(org, size)
            raise

    def response(
        self,
        *,
        job_id: str,
        principal: Principal,
        credentials: SpatialDataCredentialCurrentness,
        head_only: bool,
        now: datetime,
    ) -> Response:
        from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

        return SpatialDataDownloadResponse(
            self.prepare(job_id=job_id, principal=principal, credentials=credentials, now=now),
            head_only=head_only,
        )
