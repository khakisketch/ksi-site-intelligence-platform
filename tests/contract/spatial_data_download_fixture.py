"""Actual Core job authorities, synthetic version storage and explicit fresh credential port."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal
from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1
from spatial_data_job_fixture import NOW, issue, job_graph, job_store, lease, receipt_for


class FreshCredentials:
    def __init__(self, principal: Principal) -> None:
        self.principal: Principal | None = principal
        self.enabled = True
        self.calls = 0

    def resolve(self, *, now: datetime) -> Principal | None:
        from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

        self.calls += 1
        if not self.enabled:
            raise SpatialDataDomainError("PERMISSION_DENIED", 401)
        return self.principal


class VersionBytes:
    def __init__(self, payload: bytes, observation: SpatialDataObjectObservation) -> None:
        self.payload, self.observation = payload, observation
        self.opened = self.closed = 0
        self.after_read: Callable[[], None] | None = None

    @contextmanager
    def open_version(
        self, observation: SpatialDataObjectObservation, *, chunk_bytes: int, deadline: datetime
    ) -> Iterator[Iterator[bytes]]:
        from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

        assert chunk_bytes > 0 and deadline > NOW
        if observation != self.observation:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        self.opened += 1

        def chunks() -> Iterator[bytes]:
            for index in range(0, len(self.payload), chunk_bytes):
                yield self.payload[index : index + chunk_bytes]
            if self.after_read:
                self.after_read()

        try:
            yield chunks()
        finally:
            self.closed += 1

    def issue_source_get(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise NotImplementedError(
            "Read-only generated version fixture cannot sign source capabilities"
        )

    def issue_output_put(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise NotImplementedError(
            "Read-only generated version fixture cannot sign upload capabilities"
        )

    def observe_owned_output(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise NotImplementedError(
            "Read-only generated version fixture cannot observe provider output"
        )

    def list_owned_versions(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("Read-only generated version fixture cannot inventory versions")

    def delete_owned_version(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("Read-only generated version fixture cannot delete versions")


def delivery_graph(tmp_path: Path) -> SimpleNamespace:
    from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore
    from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService

    graph = job_graph(tmp_path)
    jobs = job_store(graph)
    issued = issue(jobs, graph)
    attempt = lease(jobs, graph, issued)
    payload = b"0123456789abcdef" * 64
    assert len(payload) == 1024
    receipt = receipt_for(
        jobs, graph, issued, attempt, output_hash="sha256:" + sha256(payload).hexdigest()
    )
    receipt = receipt.model_copy(
        update={"output_size_bytes": len(payload), "receipt_digest": None}
    ).sealed()
    target = jobs.reserve_output(
        job_id=issued.job_id,
        worker=graph.worker,
        attempt=attempt,
        receipt=receipt,
        expires_at=attempt.lease_until,
        now=NOW,
    )
    observation = SpatialDataObjectObservation(
        target.object_key, "pinned-v1", len(payload), receipt.output_sha256, "image/tiff"
    )
    declaration = SpatialDataUploadDeclarationV1(
        attempt=attempt,
        receipt=receipt,
        sha256=receipt.output_sha256,
        size_bytes=len(payload),
        content_type="image/tiff",
    ).sealed()
    assert declaration.upload_digest is not None
    jobs.complete(
        job_id=issued.job_id,
        worker=graph.worker,
        attempt=attempt,
        upload_digest=declaration.upload_digest,
        observation=observation,
        now=NOW,
    )
    storage = VersionBytes(payload, observation)
    credentials = FreshCredentials(graph.principal)
    audit = SpatialDataAuditStore(
        DurableJournal(tmp_path / "audit.jsonl"), policy=graph.data_policy
    )
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    service = SpatialDataDownloadService(
        jobs=jobs,
        storage=storage,
        audit=audit,
        policy=graph.data_policy,
        spool_root=spool,
        clock=lambda: NOW,
    )
    return SimpleNamespace(
        graph=graph,
        jobs=jobs,
        issued=issued,
        observation=observation,
        storage=storage,
        payload=payload,
        credentials=credentials,
        audit=audit,
        spool=spool,
        service=service,
    )


def prepare(graph: SimpleNamespace) -> Any:
    return graph.service.prepare(
        job_id=graph.issued.job_id,
        principal=graph.graph.principal,
        credentials=graph.credentials,
        now=NOW,
    )
