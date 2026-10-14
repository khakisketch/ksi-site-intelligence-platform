"""Protected, operator-controlled production wiring for the spatial-data lane.

Absent configuration keeps the lane unmounted (the existing closed surface).
A present configuration is validated before any journal or S3 side effect:
owner-private files, a detached Ed25519 activation signature, exact
policy/runtime/activation bindings, a registered ``SPATIAL_DATA_WORKER``
identity, and an operator-provisioned grant/revocation file. The lane still
performs its own currentness check on every use — this module never becomes a
second authority and never provisions credentials, keys or grants by itself.

Boot with an authentic but expired activation is allowed so retained history
still replays; every new work/use path then fails closed through the store's
existing ``ACTIVATION_UNAVAILABLE``/``CURRENTNESS_UNAVAILABLE`` checks.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import stat
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts._spatial_data import (
    Digest,
    PositiveSeconds,
    SpatialDataModel,
)
from ksi_event_contracts.processing_job import ExecutionLocus
from ksi_event_contracts.spatial_data import SpatialDataSourceV1
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataGrantV1,
    SpatialDataPolicyV1,
    SpatialDataRevocationV1,
    SpatialDataRuntimeV1,
)
from pydantic import Field, model_validator

from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord
from ksi_core.composition.spatial_data_graph import (
    SpatialDataLocalAssemblyConfig,
    SpatialDataLocalGraphConfig,
    SpatialDataWiring,
)
from ksi_core.domains.external.delivery.cleanup import run_spatial_data_cleanup_once
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.grants import SpatialDataGrantStore
from ksi_core.domains.external.delivery.jobs import SpatialDataJobCurrentnessPort
from ksi_core.domains.external.delivery.storage_s3 import SpatialDataS3Storage
from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry

_LOGGER = logging.getLogger(__name__)

_MAX_CONFIG_BYTES = 256 * 1024
_MAX_RIGHTS_BYTES = 1024 * 1024
_MAX_RIGHTS_RECORDS = 512


class SpatialDataCoreConfigError(RuntimeError):
    """The protected spatial-data configuration is absent, unsafe or invalid."""

    def __init__(self, reason: str = "CONFIG_UNAVAILABLE") -> None:
        self.reason = reason
        super().__init__(reason)


def _path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("explicit absolute path required")
    return path


def _open_protected_directory(path: Path) -> int:
    """Pin an existing owner-controlled directory chain without following links."""
    descriptors: list[int] = []
    try:
        path = _path(str(path))
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(directory)
        for component in path.parts[1:]:
            parent = os.fstat(directory)
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            descriptors.append(child)
            observed = os.fstat(child)
            if observed.st_uid not in (0, os.geteuid()):
                raise ValueError("untrusted ancestor")
            if parent.st_mode & 0o022 and not (
                parent.st_mode & stat.S_ISVTX and observed.st_uid == os.geteuid()
            ):
                raise ValueError("substitutable ancestor")
            directory = child
        parent = os.fstat(directory)
        if parent.st_mode & 0o022:
            raise ValueError("substitutable file parent")
        descriptors.remove(directory)
        return directory
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _require_owner_private_directory(path: Path) -> None:
    descriptor = -1
    try:
        descriptor = _open_protected_directory(path)
        node = os.fstat(descriptor)
        if (
            node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or stat.S_IMODE(node.st_mode) != 0o700
        ):
            raise ValueError("existing owner-private directory required")
    except (OSError, ValueError) as exc:
        raise SpatialDataCoreConfigError() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_protected_file(path: Path, *, maximum_bytes: int) -> bytes:
    """Bounded descriptor read through a no-symlink, non-substitutable chain."""
    descriptors: list[int] = []
    try:
        path = _path(str(path))
        directory = _open_protected_directory(path.parent)
        descriptors.append(directory)
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
        )
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
        ):
            raise ValueError("private file identity unavailable")
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, min(8192, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > maximum_bytes:
                raise ValueError("private file over budget")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(payload) != before.st_size:
            raise ValueError("private file changed")
        return bytes(payload)
    except (ValueError, OSError) as exc:
        raise SpatialDataCoreConfigError() from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(_: str) -> Any:
    raise ValueError("nonfinite JSON")


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_nonfinite
    )


def _sealed(snapshot: Any) -> None:
    if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
        raise ValueError("sealed authority snapshot required")


def _bounded_positive_seconds(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
        raise ValueError("explicit positive finite seconds required")
    return float(value)


class SpatialDataCoreConfigV1(SpatialDataModel):
    """One protected generation of the Core-side data-lane authority."""

    version: Literal["spatial-data-core-config.v1"]
    processing_location: Literal["site_onprem"]
    policy: SpatialDataPolicyV1
    runtime: SpatialDataRuntimeV1
    activation: SpatialDataActivationV1
    activation_signature: str = Field(strict=True, min_length=1, max_length=128, repr=False)
    trusted_public_key: str = Field(strict=True, min_length=1, max_length=64, repr=False)
    revoked_activation_digests: tuple[Digest, ...] = Field(max_length=4096)
    spool_root: str = Field(strict=True, min_length=1, max_length=4096)
    operation_timeout_seconds: PositiveSeconds
    grants_file: str = Field(strict=True, min_length=1, max_length=4096)
    cleanup_interval_seconds: PositiveSeconds

    @property
    def spool_root_path(self) -> Path:
        return _path(self.spool_root)

    @property
    def grants_file_path(self) -> Path:
        return _path(self.grants_file)

    @model_validator(mode="after")
    def _exact_signed_authority(self) -> Self:
        for snapshot in (self.policy, self.runtime, self.activation):
            _sealed(snapshot)
        if (
            self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
            or self.activation.preparation_profile != self.runtime.preparation_profile
        ):
            raise ValueError("activation must bind the exact policy/runtime")
        if tuple(sorted(set(self.revoked_activation_digests))) != self.revoked_activation_digests:
            raise ValueError("revoked activation digests must be sorted and unique")
        if self.activation.activation_digest in self.revoked_activation_digests:
            raise ValueError("configured activation is revoked")
        timeout = _bounded_positive_seconds(self.operation_timeout_seconds)
        _bounded_positive_seconds(self.cleanup_interval_seconds)
        envelope = self.policy.resource_envelope
        if timeout > min(
            self.policy.stream_deadline_seconds,
            self.policy.cleanup_deadline_seconds,
            envelope.max_deadline_seconds,
        ):
            raise ValueError("operation timeout exceeds the data policy deadlines")
        _path(self.spool_root)
        _path(self.grants_file)
        key = base64.b64decode(self.trusted_public_key, validate=True)
        signature = base64.b64decode(self.activation_signature, validate=True)
        if (
            len(key) != 32
            or len(signature) != 64
            or base64.b64encode(key).decode("ascii") != self.trusted_public_key
            or base64.b64encode(signature).decode("ascii") != self.activation_signature
        ):
            raise ValueError("canonical detached signature required")
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(
                signature, self.activation.signing_bytes()
            )
        except InvalidSignature as exc:
            raise ValueError("activation signature is invalid") from exc
        return self


class SpatialDataRightsFileV1(SpatialDataModel):
    """Operator-provisioned grant/revocation records for one boot generation."""

    version: Literal["spatial-data-rights.v1"]
    grants: tuple[SpatialDataGrantV1, ...] = Field(max_length=_MAX_RIGHTS_RECORDS)
    revocations: tuple[SpatialDataRevocationV1, ...] = Field(max_length=_MAX_RIGHTS_RECORDS)

    @model_validator(mode="after")
    def _sealed_unique_pairs(self) -> Self:
        grants: dict[tuple[str, str, int], SpatialDataGrantV1] = {}
        for grant in self.grants:
            _sealed(grant)
            key = (grant.organization_id, grant.grant_id, grant.revision)
            if key in grants:
                raise ValueError("duplicate grant record")
            grants[key] = grant
        revocations: set[tuple[str, str, int]] = set()
        for revocation in self.revocations:
            _sealed(revocation)
            key = (revocation.organization_id, revocation.grant_id, revocation.revision)
            if key in revocations or key not in grants:
                raise ValueError("revocation must pair with its grant record in this file")
            if grants[key].grant_digest != revocation.grant_digest:
                raise ValueError("revocation digest does not match its grant record")
            revocations.add(key)
        return self


def _worker_records(
    config: SpatialDataCoreConfigV1, principal_records: Iterable[PrincipalTokenRecord]
) -> Principal:
    matches = {
        record.principal
        for record in principal_records
        if record.principal.principal_id == config.activation.worker_principal_id
    }
    if len(matches) != 1:
        raise ValueError("activation requires exactly one registered worker identity")
    worker = next(iter(matches))
    if (
        worker.kind is not PrincipalKind.SPATIAL_DATA_WORKER
        or worker.organization_id != config.activation.organization_id
        or worker.role is not None
        or worker.device_id is not None
    ):
        raise ValueError("activation worker identity is not an exact data worker")
    return worker


def load_spatial_data_core_config(
    path: Path, *, principal_records: Iterable[PrincipalTokenRecord]
) -> SpatialDataCoreConfigV1:
    """Load and fully verify the protected generation; no side effects."""
    try:
        raw = _read_protected_file(path, maximum_bytes=_MAX_CONFIG_BYTES)
        config = SpatialDataCoreConfigV1.model_validate(_strict_json(raw))
        _worker_records(config, principal_records)
        _require_owner_private_directory(config.spool_root_path)
        return config
    except (ValueError, TypeError, RecursionError) as exc:
        raise SpatialDataCoreConfigError() from exc


def _resolvable_beneficiary(
    grant: SpatialDataGrantV1,
    *,
    opaque: dict[str, Principal],
    oidc_subject_registry: OidcSubjectRegistry | None,
) -> Principal | None:
    principal = opaque.get(grant.beneficiary_principal_id)
    if principal is None and oidc_subject_registry is not None:
        principal = oidc_subject_registry.principal_by_id(grant.beneficiary_principal_id)
    if principal is None or principal.organization_id != grant.organization_id:
        return None
    return principal


def load_spatial_data_rights_file(
    config: SpatialDataCoreConfigV1,
    *,
    principal_records: Iterable[PrincipalTokenRecord],
    oidc_subject_registry: OidcSubjectRegistry | None,
) -> SpatialDataRightsFileV1:
    """Load the grant/revocation generation bound to this config; no side effects.

    Every grant must reference the exact current policy digest, the configured
    on-prem location and a currently resolvable beneficiary principal of the
    same organization; a grant that could never authorize fails boot instead of
    lingering as dead configuration.
    """
    try:
        raw = _read_protected_file(config.grants_file_path, maximum_bytes=_MAX_RIGHTS_BYTES)
        rights = SpatialDataRightsFileV1.model_validate(_strict_json(raw))
        opaque: dict[str, Principal] = {}
        for record in principal_records:
            opaque.setdefault(record.principal.principal_id, record.principal)
        location = ExecutionLocus(config.processing_location)
        for grant in rights.grants:
            if (
                grant.policy_digest != config.policy.policy_digest
                or grant.processing_location is not location
                or grant.observed_crs_digest == ""
            ):
                raise ValueError("grant does not bind the configured data authority")
            if _resolvable_beneficiary(
                grant, opaque=opaque, oidc_subject_registry=oidc_subject_registry
            ) is None:
                raise ValueError("grant beneficiary is not a resolvable current principal")
        return rights
    except (ValueError, TypeError, RecursionError) as exc:
        raise SpatialDataCoreConfigError() from exc


class SpatialDataProductionCurrentness(SpatialDataJobCurrentnessPort):
    """Trusted local identity/authority lookup for background job checks.

    Identity resolution is boot-loaded (opaque registry records and the
    protected OIDC subject registry). Retiring a token or revoking a subject
    therefore takes effect on the next Core restart, exactly like the other
    boot-loaded Core authorities; no request credential is stored or replayed.
    """

    def __init__(
        self,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        policy: SpatialDataPolicyV1,
        runtime: SpatialDataRuntimeV1,
        activation: SpatialDataActivationV1,
        revoked_activation_digests: tuple[str, ...],
        auth_registry: AuthRegistry,
        oidc_subject_registry: OidcSubjectRegistry | None,
    ) -> None:
        self._coordinator = coordinator
        self._policy = policy.model_copy(deep=True)
        self._runtime = runtime.model_copy(deep=True)
        self._activation = activation.model_copy(deep=True)
        self._revoked = frozenset(revoked_activation_digests)
        self._auth_registry = auth_registry
        self._oidc_subject_registry = oidc_subject_registry

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def resolve_requester(
        self, *, principal_id: str, organization_id: str, now: datetime
    ) -> Principal | None:
        if type(principal_id) is not str or type(organization_id) is not str:
            return None
        principal = self._auth_registry.principal_by_id(principal_id)
        if principal is None and self._oidc_subject_registry is not None:
            principal = self._oidc_subject_registry.principal_by_id(principal_id)
        if principal is None or principal.organization_id != organization_id:
            return None
        return principal

    def is_current(
        self,
        *,
        policy: SpatialDataPolicyV1,
        runtime: SpatialDataRuntimeV1,
        activation: SpatialDataActivationV1,
        now: datetime,
    ) -> bool:
        return (
            policy == self._policy
            and runtime == self._runtime
            and activation == self._activation
            and activation.activation_digest is not None
            and activation.activation_digest not in self._revoked
            and activation.is_current_at(now)
        )


def spatial_data_source_key_resolver(
    reconstruction: ExternalReconstructionStore,
) -> Callable[[SpatialDataSourceV1], str]:
    """Exact sealed-subject manifest resolution; never a caller-supplied key."""

    def resolve(source: SpatialDataSourceV1) -> str:
        revision = reconstruction.resolve_sealed_subject(source.sealed_subject)
        if revision is None or revision.manifest is None:
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        entries = {entry.artifact_id: entry for entry in revision.manifest.entries}
        entry = entries.get(source.artifact_id)
        if (
            entry is None
            or "sha256:" + entry.observed_sha256 != source.observed_sha256
            or entry.observed_size_bytes != source.observed_size_bytes
        ):
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        return entry.object_key

    return resolve


def _fresh_s3_client_factory(
    endpoint_url: str, operation_timeout_seconds: float
) -> Callable[[], Any]:
    """A fresh, bounded SDK client construction per supervised child session."""

    def factory() -> Any:
        import boto3  # noqa: PLC0415 -- lazy import keeps boto3 optional for Core
        from botocore.config import Config  # noqa: PLC0415 -- same lazy boundary

        connect_timeout = min(5.0, operation_timeout_seconds)
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=connect_timeout,
                read_timeout=operation_timeout_seconds,
                retries={"total_max_attempts": 1},
            ),
        )

    return factory


def build_spatial_data_production(
    config: SpatialDataCoreConfigV1,
    rights: SpatialDataRightsFileV1,
    *,
    auth_registry: AuthRegistry,
    oidc_subject_registry: OidcSubjectRegistry | None,
    bucket: str,
    endpoint_url: str,
) -> SpatialDataLocalAssemblyConfig:
    """Assemble the explicit local wiring factories for the platform factory."""
    if not isinstance(config, SpatialDataCoreConfigV1) or not isinstance(
        rights, SpatialDataRightsFileV1
    ):
        raise ValueError("validated protected configuration and rights required")
    if not bucket:
        raise ValueError("explicit S3 bucket required")
    location = ExecutionLocus(config.processing_location)
    clock = lambda: datetime.now(UTC)  # noqa: E731 -- single explicit Core clock

    def build_storage(reconstruction: ExternalReconstructionStore) -> SpatialDataS3Storage:
        return SpatialDataS3Storage(
            client_factory=_fresh_s3_client_factory(
                endpoint_url, float(config.operation_timeout_seconds)
            ),
            bucket=bucket,
            source_key_resolver=spatial_data_source_key_resolver(reconstruction),
            clock=clock,
            policy=config.policy,
            supervisor=SpatialDataStorageSupervisor(max_concurrency=2),
            operation_timeout_seconds=float(config.operation_timeout_seconds),
        )

    def build_currentness(
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> SpatialDataJobCurrentnessPort:
        return SpatialDataProductionCurrentness(
            coordinator=coordinator,
            policy=config.policy,
            runtime=config.runtime,
            activation=config.activation,
            revoked_activation_digests=tuple(config.revoked_activation_digests),
            auth_registry=auth_registry,
            oidc_subject_registry=oidc_subject_registry,
        )

    def import_rights(grants: SpatialDataGrantStore) -> None:
        for grant in rights.grants:
            grants.provision(grant)
        for revocation in rights.revocations:
            grants.revoke(revocation)

    return SpatialDataLocalAssemblyConfig(
        config=SpatialDataLocalGraphConfig(
            config.policy, config.runtime, config.activation, location, clock
        ),
        build_storage=build_storage,
        build_currentness=build_currentness,
        spool_root=config.spool_root_path,
        import_rights=import_rights,
    )


class SpatialDataCleanupLoop:
    """Bounded same-process retention pass; never enumerates or deletes sources.

    ``run_spatial_data_cleanup_once`` keeps its own per-candidate lease and
    audit discipline; this class only schedules it and surfaces failures to the
    log instead of hiding them.
    """

    def __init__(
        self,
        *,
        jobs: Any,
        storage: Any,
        audit: Any,
        interval_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._interval = _bounded_positive_seconds(interval_seconds)
        if jobs is None or storage is None or audit is None:
            raise ValueError("cleanup requires the mounted jobs/storage/audit participants")
        self._jobs = jobs
        self._storage = storage
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def run_once(self) -> int:
        return run_spatial_data_cleanup_once(
            jobs=self._jobs,
            storage=self._storage,
            audit=self._audit,
            now=self._clock(),
        )

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="spatial-data-cleanup", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 -- a failed pass is logged, never silent
                _LOGGER.exception("spatial data cleanup pass failed")
            if self._stop.wait(self._interval):
                return

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        _bounded_positive_seconds(timeout_seconds)
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread is not None:
            thread.join(timeout_seconds)


def start_spatial_data_cleanup(
    wiring: SpatialDataWiring,
    *,
    interval_seconds: float,
    clock: Callable[[], datetime] | None = None,
) -> SpatialDataCleanupLoop:
    """Start the bounded cleanup loop for an assembled wiring; explicit stop."""
    downloads = wiring.downloads
    if not isinstance(wiring, SpatialDataWiring) or downloads is None:
        raise ValueError("cleanup requires the mounted download/audit wiring")
    loop = SpatialDataCleanupLoop(
        jobs=wiring.jobs,
        storage=wiring.storage,
        audit=downloads.audit_store,
        interval_seconds=interval_seconds,
        clock=clock,
    )
    loop.start()
    return loop


__all__ = [
    "SpatialDataCleanupLoop",
    "SpatialDataCoreConfigError",
    "SpatialDataCoreConfigV1",
    "SpatialDataProductionCurrentness",
    "SpatialDataRightsFileV1",
    "build_spatial_data_production",
    "load_spatial_data_core_config",
    "load_spatial_data_rights_file",
    "spatial_data_source_key_resolver",
    "start_spatial_data_cleanup",
]
