"""Core-owned durable publication lane for protected FLOAT64 delta outputs.

A delta raster publication is a separately versioned, digest-bound derived
artifact referencing one exact immutable calculation plus its numeric result
and coverage witness.  Sign is always ``CURRENT_MINUS_BASELINE``; grid, frame,
selected/common-valid coverage, holes and NoData handling stay those of the
bound calculation.  The frozen V1/V2 contracts, journals and numeric results
are never modified or reinterpreted here.

Authority model, read carefully:

- The sealed :class:`DeltaRasterPublicationV1` descriptor is immutable
  *evidence*, never permission.  It cannot assert that the publication is
  current, unrevoked, or readable by any caller.
- Publication intent and worker upload fences are issued by this Core store,
  never by callers.  The intent binds the exact source numeric, coverage and
  calculation digests plus organization/site/work-area scope and grid; the
  source binding is resolved through the REQUIRED trusted Core
  :class:`DeltaSourceWitnessPort`, not through caller claims and never through
  a caller-supplied ``is_current`` callback.
- Policy caps, lifetime ceiling and signed-authority currency come from the
  REQUIRED :class:`DeltaPublicationAuthorityPort` plus the explicit
  :class:`DeltaPublicationPolicy` config.  No approval is inferred from a
  digest, and a revoked/expired/unknown policy never authorizes.
- AI/data-egress consent is rechecked on every read through the REQUIRED
  :class:`DeltaEgressPort`.  There is no default egress approval.
- Output bytes live in the bounded immutable :class:`FilesystemDeltaByteStore`
  under an owner-controlled root.  Callers never supply paths or URLs, blob
  bytes are never journaled, and the descriptor carries no URL, path or
  capability.  Content hash and size are verified by streaming (never a
  single in-memory giant buffer) before durable publication, and every byte
  read is bounded and revalidated against current source, authority, runtime,
  expiry, revocation and fence state.  TOCTOU, read-time revocation, cancel
  and failure all fail closed.
- Revocation is a separate durable event; the historical descriptor is
  immutable.  Every terminal state carries an explicit reason string.

Journal semantics mirror the sibling Core stores: ``eventDigest`` over the
exact event body, strict closed shapes, malformed / cross-scope / digest
tamper replay fails with :class:`DeltaPublicationRecoveryError` (never
repaired), and the journal is closed on recovery failure.

This module is deliberately UNMOUNTED: no composition wiring is added here,
and the FastAPI factory in
:mod:`ksi_core.domains.external.quantity.external_delta_publication_api`
is provided only as an explicit, separately reviewable seam.  Signed
production activation, profile integration beyond the fenced worker lane, and
MCP/OIDC allowlist changes remain parent-owned future work.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import stat
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_masked_volume import DeltaRasterPublicationV1

from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STREAM_CHUNK_BYTES = 65536

_KIND_INTENT_CREATED = "delta-publication-intent-created"
_KIND_LEASED = "delta-publication-upload-leased"
_KIND_PUBLISHED = "delta-publication-published"
_KIND_REVOKED = "delta-publication-revoked"
_KIND_CANCELED = "delta-publication-canceled"
_KIND_FAILED = "delta-publication-failed"

_SOURCE_CONTRACT_VERSIONS = (
    "external-relative-volume-calculation-report.v2",
    "external-masked-volume-calculation-identity.v3",
)
_SourceContractVersion = Literal[
    "external-relative-volume-calculation-report.v2",
    "external-masked-volume-calculation-identity.v3",
]


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


def _require_digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{description} digest is invalid")
    return value


def _require_opaque_id(value: object, description: str) -> str:
    """Opaque Core identifiers name protected records, never paths or URLs."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{description} identifier is invalid")
    lowered = value.lower()
    if (
        _OPAQUE_ID_RE.fullmatch(value) is None
        or "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(f"{description} identifier must be opaque, never a path or URL")
    return value


def _require_scope_text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError(f"{description} scope is invalid")
    return value


class DeltaPublicationRecoveryError(RuntimeError):
    """A delta-publication journal cannot be replayed as exact, safe history."""


class DeltaPublicationStatusV1(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    REVOKED = "REVOKED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class DeltaPublicationDispositionV1(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    SOURCE_NOT_CURRENT = "SOURCE_NOT_CURRENT"
    POLICY_NOT_CURRENT = "POLICY_NOT_CURRENT"
    RUNTIME_NOT_CURRENT = "RUNTIME_NOT_CURRENT"
    EGRESS_DENIED = "EGRESS_DENIED"
    BYTES_UNAVAILABLE = "BYTES_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DeltaPublicationPolicy:
    """Explicit Core-owned caps for this lane; config, never caller input.

    The canonical digest of these exact bounds is journaled on every intent
    and descriptor.  Currency (is this policy digest still signed-authorized
    right now?) is decided by the authority port at use time; the digest
    itself grants nothing.
    """

    policy_id: str
    version: int
    max_output_bytes: int
    max_grid_cells: int
    max_lifetime_seconds: int
    max_active_publications: int
    upload_lease_duration_seconds: int
    max_upload_attempts: int

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or len(self.policy_id) > 255:
            raise ValueError("publication policy requires a non-empty policy id")
        for name in (
            "version",
            "max_output_bytes",
            "max_grid_cells",
            "max_lifetime_seconds",
            "max_active_publications",
            "upload_lease_duration_seconds",
            "max_upload_attempts",
        ):
            value = getattr(self, name)
            if type(value) is not int or isinstance(value, bool) or value <= 0:
                raise ValueError(f"publication policy {name} must be a positive integer")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "version": self.version,
            "maxOutputBytes": self.max_output_bytes,
            "maxGridCells": self.max_grid_cells,
            "maxLifetimeSeconds": self.max_lifetime_seconds,
            "maxActivePublications": self.max_active_publications,
            "uploadLeaseDurationSeconds": self.upload_lease_duration_seconds,
            "maxUploadAttempts": self.max_upload_attempts,
        }

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class DeltaSourceWitness:
    """Trusted Core resolution of the exact bound calculation sources.

    Instances are produced ONLY by the injected
    :class:`DeltaSourceWitnessPort` from genuine Core calculation state.
    Caller-supplied digests or grids never become a witness; the store
    compares them against the witness and blocks on any mismatch.
    """

    organization_id: str
    site_id: str
    work_area_id: str
    source_contract_version: _SourceContractVersion
    source_calculation_identity_digest: str
    source_numeric_result_identity_digest: str
    source_coverage_witness_digest: str
    grid_rows: int
    grid_columns: int
    transform: tuple[float, float, float, float, float, float]
    transform_digest: str
    grid_crs_identifier: str
    grid_crs_digest: str
    bounds: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        for name in ("organization_id", "site_id", "work_area_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"source witness {name} is invalid")
        if self.source_contract_version not in _SOURCE_CONTRACT_VERSIONS:
            raise ValueError("source witness contract version is not a supported delta source")
        for name in (
            "source_calculation_identity_digest",
            "source_numeric_result_identity_digest",
            "source_coverage_witness_digest",
            "transform_digest",
            "grid_crs_digest",
        ):
            _require_digest(getattr(self, name), f"source witness {name}")
        if (
            type(self.grid_rows) is not int
            or type(self.grid_columns) is not int
            or self.grid_rows <= 0
            or self.grid_columns <= 0
        ):
            raise ValueError("source witness grid dimensions must be positive integers")
        if len(self.transform) != 6 or not all(type(item) is float for item in self.transform):
            raise ValueError("source witness transform must be six floats")
        if len(self.bounds) != 4 or not all(type(item) is float for item in self.bounds):
            raise ValueError("source witness bounds must be four floats")
        if not self.grid_crs_identifier.strip():
            raise ValueError("source witness CRS identifier is invalid")


class DeltaSourceWitnessPort(Protocol):
    """REQUIRED trusted Core seam: resolve the exact bound sources, or None.

    Returning a witness means the three source digests are currently bound to
    one live calculation in the given scope with the witnessed grid.  Any
    source change, revocation, expiry or scope drift must surface as ``None``.
    A witness is Core truth, never caller input.
    """

    def resolve_current_source(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> DeltaSourceWitness | None: ...


@dataclass(frozen=True, slots=True)
class DeltaOutputObservation:
    """Trusted Core acceptance of one worker's observed delta output.

    Instances are produced ONLY by separately authenticated, pinned,
    contained worker result acceptance (parent-owned adapter): the worker's
    parsed output is observed there — including its actual FLOAT64 grid,
    CURRENT_MINUS_BASELINE sign and NaN nodata convention — and bound here
    to the exact source digests, publication, worker identity, lease
    generation and output hash/size.  Core performs no native TIFF parsing
    and never trusts an upload-caller boolean; the observation IS the
    positive authorization for the bytes it names.  A descriptor may only
    assert the format and grid this observation already established.
    """

    organization_id: str
    site_id: str
    work_area_id: str
    source_contract_version: _SourceContractVersion
    source_calculation_identity_digest: str
    source_numeric_result_identity_digest: str
    source_coverage_witness_digest: str
    publication_id: str
    worker_principal_id: str
    worker_instance_id: str
    lease_generation: int
    output_sha256: str
    output_size_bytes: int
    grid_rows: int
    grid_columns: int
    transform: tuple[float, float, float, float, float, float]
    transform_digest: str
    grid_crs_identifier: str
    grid_crs_digest: str
    bounds: tuple[float, float, float, float]
    dtype: Literal["FLOAT64"]
    delta_sign: Literal["CURRENT_MINUS_BASELINE"]
    nodata_value: Literal["NAN"]
    observation_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("organization_id", "site_id", "work_area_id", "publication_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                raise ValueError(f"output observation {name} is invalid")
        if self.source_contract_version not in _SOURCE_CONTRACT_VERSIONS:
            raise ValueError("output observation contract version is not a supported delta source")
        for name in (
            "source_calculation_identity_digest",
            "source_numeric_result_identity_digest",
            "source_coverage_witness_digest",
            "output_sha256",
            "transform_digest",
            "grid_crs_digest",
        ):
            _require_digest(getattr(self, name), f"output observation {name}")
        for name in ("worker_principal_id", "worker_instance_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                raise ValueError(f"output observation {name} is invalid")
        if type(self.lease_generation) is not int or self.lease_generation <= 0:
            raise ValueError("output observation lease generation is invalid")
        if type(self.output_size_bytes) is not int or self.output_size_bytes <= 0:
            raise ValueError("output observation size is invalid")
        if (
            type(self.grid_rows) is not int
            or type(self.grid_columns) is not int
            or self.grid_rows <= 0
            or self.grid_columns <= 0
        ):
            raise ValueError("output observation grid dimensions must be positive integers")
        if len(self.transform) != 6 or not all(type(item) is float for item in self.transform):
            raise ValueError("output observation transform must be six floats")
        if len(self.bounds) != 4 or not all(type(item) is float for item in self.bounds):
            raise ValueError("output observation bounds must be four floats")
        if not self.grid_crs_identifier.strip():
            raise ValueError("output observation CRS identifier is invalid")
        if self.dtype != "FLOAT64":
            raise ValueError("output observation dtype is fixed to FLOAT64")
        if self.delta_sign != "CURRENT_MINUS_BASELINE":
            raise ValueError("output observation sign is fixed to CURRENT_MINUS_BASELINE")
        if self.nodata_value != "NAN":
            raise ValueError("output observation nodata is fixed to NaN")
        if self.observation_digest is not None and (
            self.observation_digest != self.canonical_digest()
        ):
            raise ValueError("output observation digest differs from its exact content")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "workAreaId": self.work_area_id,
            "sourceContractVersion": self.source_contract_version,
            "sourceCalculationIdentityDigest": self.source_calculation_identity_digest,
            "sourceNumericResultIdentityDigest": self.source_numeric_result_identity_digest,
            "sourceCoverageWitnessDigest": self.source_coverage_witness_digest,
            "publicationId": self.publication_id,
            "workerPrincipalId": self.worker_principal_id,
            "workerInstanceId": self.worker_instance_id,
            "leaseGeneration": self.lease_generation,
            "outputSha256": self.output_sha256,
            "outputSizeBytes": self.output_size_bytes,
            "gridRows": self.grid_rows,
            "gridColumns": self.grid_columns,
            "transform": list(self.transform),
            "transformDigest": self.transform_digest,
            "gridCrsIdentifier": self.grid_crs_identifier,
            "gridCrsDigest": self.grid_crs_digest,
            "bounds": list(self.bounds),
            "dtype": self.dtype,
            "deltaSign": self.delta_sign,
            "nodataValue": self.nodata_value,
        }

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> DeltaOutputObservation:
        """Bind the exact content digest; unsealed observations never publish."""
        validated = replace(
            self,
            organization_id=self.organization_id,
            site_id=self.site_id,
            work_area_id=self.work_area_id,
            source_contract_version=self.source_contract_version,
            source_calculation_identity_digest=self.source_calculation_identity_digest,
            source_numeric_result_identity_digest=self.source_numeric_result_identity_digest,
            source_coverage_witness_digest=self.source_coverage_witness_digest,
            publication_id=self.publication_id,
            worker_principal_id=self.worker_principal_id,
            worker_instance_id=self.worker_instance_id,
            lease_generation=self.lease_generation,
            output_sha256=self.output_sha256,
            output_size_bytes=self.output_size_bytes,
            grid_rows=self.grid_rows,
            grid_columns=self.grid_columns,
            transform=self.transform,
            transform_digest=self.transform_digest,
            grid_crs_identifier=self.grid_crs_identifier,
            grid_crs_digest=self.grid_crs_digest,
            bounds=self.bounds,
            dtype=self.dtype,
            delta_sign=self.delta_sign,
            nodata_value=self.nodata_value,
            observation_digest=None,
        )
        return replace(validated, observation_digest=validated.canonical_digest())


class DeltaOutputObservationPort(Protocol):
    """REQUIRED trusted seam: the pinned, authenticated worker result acceptance.

    Returning an observation means a separately authenticated, contained
    worker result for this exact (publication, worker principal, instance,
    lease generation) was accepted with the observed output hash, size and
    grid.  Missing or mismatched observations fail the publish closed, even
    for a lease-holding worker.  The observation is Core truth about the
    worker's actual output; it is never derived from upload-caller claims.
    """

    def resolve_output_observation(
        self,
        *,
        organization_id: str,
        publication_id: str,
        worker_principal_id: str,
        worker_instance_id: str,
        lease_generation: int,
        now: datetime,
    ) -> DeltaOutputObservation | None: ...


class DeltaPublicationAuthorityPort(Protocol):
    """REQUIRED signed-authority seam: policy and runtime currency, or False.

    There is intentionally no ``is_current`` callback with caller-chosen
    semantics.  Both methods consult genuine Core authority state at ``now``.
    The worker lane passes its server-bound identity so runtime currency is
    tied to that exact worker attempt, never a global boolean alone.
    """

    def is_policy_current(self, *, policy_digest: str, now: datetime) -> bool: ...

    def is_runtime_current(
        self,
        *,
        now: datetime,
        worker_principal_id: str | None = None,
        publication_id: str | None = None,
        lease_generation: int | None = None,
    ) -> bool: ...


class DeltaEgressPort(Protocol):
    """REQUIRED egress seam: is output access allowed for this caller now?"""

    def is_egress_allowed(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        now: datetime,
    ) -> bool: ...


class DeltaByteStorePort(Protocol):
    """REQUIRED bounded immutable byte seam under owner-controlled storage."""

    def stage_stream(
        self,
        *,
        stream: BinaryIO,
        expected_sha256: str,
        expected_size_bytes: int,
        max_bytes: int,
    ) -> Path: ...

    def commit(self, *, output_id: str, staged: Path) -> None: ...

    def discard(self, *, staged: Path) -> None: ...

    def exists(self, *, output_id: str) -> bool: ...

    def open_read(self, *, output_id: str) -> BinaryIO: ...


class FilesystemDeltaByteStore:
    """Owner-controlled immutable file bytes for one publication lane.

    The root directory is supplied by Core wiring (tests supply their own
    ``tmp_path``) and is pinned by an open directory descriptor for the
    store's lifetime: every file operation runs relative to that descriptor
    with ``O_NOFOLLOW``, so a swapped symlink can never redirect staging or
    reads.  The root is enforced owner-private ``0700`` (ancestors must be
    root/owner-owned without group/other-writable gaps, mirroring the
    delivery-layer private-dir gate); staged files are created ``0600`` via
    ``O_CREAT|O_EXCL|O_NOFOLLOW``; committed files are re-validated as
    single-link regular files owned by the caller at ``0600`` before and
    after the atomic rename.  Files are keyed by the validated opaque output
    id with a fixed suffix, written to a staging file first, hash/size
    verified while streaming, then atomically renamed.  A committed output
    id is immutable: committing different bytes under it fails closed.
    """

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise ValueError("byte store root must be a Path")
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("byte store root must be an absolute path")
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"byte store root is not usable: {exc}") from exc
        try:
            os.chmod(root, 0o700)
        except OSError as exc:
            raise ValueError(f"byte store root is not owner-controllable: {exc}") from exc
        self._root = root
        self._root_fd = _pin_owner_private_dir(root)
        try:
            self._staging_fd = _ensure_owner_private_subdir(self._root_fd, ".staging")
        except Exception:
            os.close(self._root_fd)
            raise
        self._staging = root / ".staging"
        self._counter = 0
        self._open_staged: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._reap_staging_leftovers()

    @property
    def root(self) -> Path:
        return self._root

    def _final_name(self, output_id: str) -> str:
        _require_opaque_id(output_id, "output")
        return output_id + ".tiff"

    def stage_stream(
        self,
        *,
        stream: BinaryIO,
        expected_sha256: str,
        expected_size_bytes: int,
        max_bytes: int,
    ) -> Path:
        _require_digest(expected_sha256, "output")
        if type(expected_size_bytes) is not int or type(max_bytes) is not int:
            raise ValueError("byte sizes must be integers")
        if expected_size_bytes <= 0 or max_bytes <= 0:
            raise ValueError("byte sizes must be positive")
        if expected_size_bytes > max_bytes:
            raise ValueError("output size exceeds the publication byte cap")
        with self._lock:
            self._counter += 1
            name = f"upload-{os.getpid()}-{self._counter}.part"
        try:
            fd = os.open(
                name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self._staging_fd,
            )
        except OSError as exc:
            raise ValueError(f"staged bytes cannot be created: {exc}") from exc
        hasher = hashlib.sha256()
        written = 0
        try:
            while True:
                chunk = stream.read(_STREAM_CHUNK_BYTES)
                if chunk is None:
                    raise ValueError("byte stream returned no data")
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise ValueError("byte stream must yield bytes")
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("output size exceeds the publication byte cap")
                hasher.update(chunk)
                view = memoryview(chunk)
                while view:
                    sent = os.write(fd, view)
                    view = view[sent:]
        except ValueError:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise
        except OSError as exc:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise ValueError(f"staged bytes cannot be written: {exc}") from exc
        if written != expected_size_bytes:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise ValueError("output byte size differs from the declared size")
        if "sha256:" + hasher.hexdigest() != expected_sha256:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise ValueError("output byte hash differs from the declared hash")
        with self._lock:
            self._open_staged[name] = (fd, written)
        return self._staging / name

    def commit(self, *, output_id: str, staged: Path) -> None:
        final_name = self._final_name(output_id)
        name = self._staged_name(staged)
        with self._lock:
            record = self._open_staged.pop(name, None)
        if record is None:
            raise ValueError("staged bytes are not this store's staged upload")
        fd, staged_size = record
        try:
            entry = os.fstat(fd)
            if (
                not stat.S_ISREG(entry.st_mode)
                or entry.st_nlink != 1
                or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) != 0o600
                or entry.st_size != staged_size
            ):
                raise ValueError("staged bytes fail owner hardening")
            try:
                probe = os.open(
                    final_name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=self._root_fd,
                )
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise ValueError(f"published output cannot be inspected: {exc}") from exc
            else:
                os.close(probe)
                raise ValueError("output id is already published and immutable")
            os.rename(name, final_name, src_dir_fd=self._staging_fd, dst_dir_fd=self._root_fd)
        except ValueError:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise
        except OSError as exc:
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=self._staging_fd)
            raise ValueError(f"staged bytes cannot be committed: {exc}") from exc
        os.close(fd)
        try:
            final_fd = os.open(
                final_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._root_fd,
            )
        except OSError as exc:
            raise ValueError(f"published output is unavailable: {exc}") from exc
        try:
            final_entry = os.fstat(final_fd)
            if (
                not stat.S_ISREG(final_entry.st_mode)
                or final_entry.st_nlink != 1
                or final_entry.st_uid != os.geteuid()
                or stat.S_IMODE(final_entry.st_mode) != 0o600
                or final_entry.st_size != staged_size
            ):
                raise ValueError("published output fails owner hardening")
        finally:
            os.close(final_fd)

    def discard(self, *, staged: Path) -> None:
        if not isinstance(staged, Path):
            raise ValueError("staged path must be a Path")
        name = staged.name
        with self._lock:
            record = self._open_staged.pop(name, None)
        if record is None:
            return
        fd, _ = record
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=self._staging_fd)

    def exists(self, *, output_id: str) -> bool:
        try:
            name = self._final_name(output_id)
        except ValueError:
            return False
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._root_fd,
            )
        except OSError:
            return False
        try:
            return stat.S_ISREG(os.fstat(fd).st_mode)
        except OSError:
            return False
        finally:
            os.close(fd)

    def open_read(self, *, output_id: str) -> BinaryIO:
        name = self._final_name(output_id)
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._root_fd,
            )
        except OSError as exc:
            raise FileNotFoundError("published output bytes are unavailable") from exc
        try:
            entry = os.fstat(fd)
            if (
                not stat.S_ISREG(entry.st_mode)
                or entry.st_nlink != 1
                or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) != 0o600
            ):
                raise ValueError("published output fails owner hardening")
        except ValueError:
            os.close(fd)
            raise
        except OSError as exc:
            os.close(fd)
            raise FileNotFoundError("published output bytes are unavailable") from exc
        return os.fdopen(fd, "rb")

    def _staged_name(self, staged: Path) -> str:
        if not isinstance(staged, Path) or staged.parent != self._staging:
            raise ValueError("staged bytes are not this store's staged upload")
        return staged.name

    def _reap_staging_leftovers(self) -> None:
        """Remove crashed-upload leftovers owned by this staging dir only."""
        try:
            names = os.listdir(self._staging)
        except OSError:
            return
        for name in names:
            if name.startswith("upload-") and name.endswith(".part"):
                with contextlib.suppress(OSError):
                    os.unlink(name, dir_fd=self._staging_fd)

    def close(self) -> None:
        """Release pinned directory descriptors and staged file descriptors."""
        with self._lock:
            records = list(self._open_staged.values())
            self._open_staged.clear()
        for fd, _ in records:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            os.close(self._staging_fd)
        with contextlib.suppress(OSError):
            os.close(self._root_fd)


def _pin_owner_private_dir(root: Path) -> int:
    """Pin an owner-private 0700 root against symlink substitution.

    Mirrors the delivery-layer private-dir gate: every ancestor from ``/``
    must be root/owner-owned without group/other-writable gaps (unless
    sticky with an owner-owned child), and the leaf must be ``0700`` owned
    by the caller in its own group.  Returns the pinned open directory
    descriptor; the caller owns its lifetime.
    """
    descriptors: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(current)
        for part in root.parts[1:]:
            previous = os.fstat(current)
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            descriptors.append(child)
            entry = os.fstat(child)
            if entry.st_uid not in (0, os.geteuid()) or (
                previous.st_mode & 0o022
                and not (previous.st_mode & stat.S_ISVTX and entry.st_uid == os.geteuid())
            ):
                raise ValueError("substitutable byte store ancestor")
            current = child
        leaf = os.fstat(current)
        if (
            leaf.st_uid != os.geteuid()
            or leaf.st_gid != os.getegid()
            or stat.S_IMODE(leaf.st_mode) != 0o700
        ):
            raise ValueError("byte store root must be an owner-private 0700 directory")
        descriptors.remove(current)
        return current
    except OSError as exc:
        raise ValueError(f"cannot pin byte store root: {exc}") from exc
    finally:
        for descriptor in descriptors:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _ensure_owner_private_subdir(root_fd: int, name: str) -> int:
    """Create and pin an owner-private 0700 staging subdir under a pinned root."""
    try:
        os.mkdir(name, 0o700, dir_fd=root_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ValueError(f"cannot create byte store staging: {exc}") from exc
    try:
        staging_fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd
        )
    except OSError as exc:
        raise ValueError(f"cannot pin byte store staging: {exc}") from exc
    try:
        os.fchmod(staging_fd, 0o700)
    except OSError as exc:
        os.close(staging_fd)
        raise ValueError(f"cannot own byte store staging: {exc}") from exc
    return staging_fd


@dataclass(frozen=True, slots=True)
class DeltaPublicationIntentView:
    """Server-issued intent plus the live upload lease, when held.

    The lease fields are populated only while the recorded lease is live for
    the requesting holder; otherwise they are ``None``/``0``.  The
    ``upload_fence_id`` is a stable server-derived routing id, never an
    upload authorization by itself: an upload additionally requires the live
    lease tuple (holder principal, holder instance, generation, expiry).
    """

    publication_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    source_contract_version: str
    output_id: str
    upload_fence_id: str
    source_calculation_identity_digest: str
    source_numeric_result_identity_digest: str
    source_coverage_witness_digest: str
    grid_rows: int
    grid_columns: int
    issued_at: datetime
    expires_at: datetime
    policy_digest: str
    status: DeltaPublicationStatusV1
    lease_generation: int = 0
    lease_holder_principal_id: str | None = None
    lease_holder_instance_id: str | None = None
    lease_issued_at: datetime | None = None
    lease_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeltaPublicationView:
    """Currently readable publication: immutable descriptor plus status."""

    publication_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    output_id: str
    issued_at: datetime
    expires_at: datetime
    policy_digest: str
    status: DeltaPublicationStatusV1
    descriptor: DeltaRasterPublicationV1
    reason: str


@dataclass(frozen=True, slots=True)
class _PublicationEntry:
    publication_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    source_contract_version: _SourceContractVersion
    source_calculation_identity_digest: str
    source_numeric_result_identity_digest: str
    source_coverage_witness_digest: str
    grid_rows: int
    grid_columns: int
    transform: tuple[float, float, float, float, float, float]
    transform_digest: str
    grid_crs_identifier: str
    grid_crs_digest: str
    bounds: tuple[float, float, float, float]
    output_id: str
    upload_fence_id: str
    issued_at: datetime
    expires_at: datetime
    policy_digest: str
    status: DeltaPublicationStatusV1
    descriptor: DeltaRasterPublicationV1 | None
    reason: str
    lease_generation: int = 0
    lease_holder_principal_id: str | None = None
    lease_holder_instance_id: str | None = None
    lease_acquisition_id: str | None = None
    lease_issued_at: datetime | None = None
    lease_expires_at: datetime | None = None
    seen_acquisition_ids: tuple[str, ...] = ()


class ExternalDeltaPublicationStore:
    """Durable registration, revocation and read-currentness for delta outputs."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        source_witness: DeltaSourceWitnessPort,
        authority: DeltaPublicationAuthorityPort,
        egress: DeltaEgressPort,
        byte_store: DeltaByteStorePort,
        observations: DeltaOutputObservationPort,
        policy: DeltaPublicationPolicy,
        clock: Callable[[], datetime],
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        for name, port in (
            ("source_witness", source_witness),
            ("authority", authority),
            ("egress", egress),
            ("byte_store", byte_store),
            ("observations", observations),
        ):
            if port is None:
                raise ValueError(f"delta publications require an explicit {name} port")
        if not callable(getattr(source_witness, "resolve_current_source", None)):
            raise ValueError("source witness port must resolve current sources")
        if not callable(getattr(authority, "is_policy_current", None)) or not callable(
            getattr(authority, "is_runtime_current", None)
        ):
            raise ValueError("authority port must report policy and runtime currency")
        if not callable(getattr(egress, "is_egress_allowed", None)):
            raise ValueError("egress port must decide output access")
        if not callable(getattr(observations, "resolve_output_observation", None)):
            raise ValueError("output observation port must resolve accepted worker outputs")
        for method in ("stage_stream", "commit", "discard", "exists", "open_read"):
            if not callable(getattr(byte_store, method, None)):
                raise ValueError(f"byte store port must implement {method}")
        if not isinstance(policy, DeltaPublicationPolicy):
            raise ValueError("delta publications require an explicit policy")
        if not callable(clock):
            raise ValueError("delta publications require an explicit trusted clock")
        self._journal = journal
        self._source = source_witness
        self._authority = authority
        self._egress = egress
        self._bytes = byte_store
        self._observations = observations
        self._policy = policy
        self._policy_digest = policy.canonical_digest()
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], _PublicationEntry] = {}
        self._pending: dict[tuple[str, str], None] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, DeltaPublicationRecoveryError):
                raise
            raise DeltaPublicationRecoveryError(str(exc)) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def policy(self) -> DeltaPublicationPolicy:
        return self._policy

    @property
    def policy_digest(self) -> str:
        return self._policy_digest

    # -- intent (human owner) -------------------------------------------------

    def create_intent(
        self,
        *,
        principal: Principal,
        publication_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        grid_rows: int,
        grid_columns: int,
        transform: tuple[float, float, float, float, float, float],
        transform_digest: str,
        grid_crs_identifier: str,
        grid_crs_digest: str,
        bounds: tuple[float, float, float, float],
        lifetime_seconds: int,
        now: datetime,
    ) -> DeltaPublicationIntentView:
        """Issue a server-bound upload intent; binds exact sources and scope.

        Caller grids, digests and the publication id are accepted only when
        they match the trusted source witness exactly.  An idempotent retry
        with the full identical binding rechecks scope and currentness before
        returning the existing intent; it never skips them, and a full
        lane never rejects such a retry on capacity grounds.
        """
        self._require_intent_owner(principal)
        self._require_utc(now)
        organization_id = principal.organization_id
        _require_opaque_id(publication_id, "publication")
        _require_scope_text(site_id, "site")
        _require_scope_text(work_area_id, "work area")
        self._require_caller_scope(principal, site_id, work_area_id)
        _require_digest(source_calculation_identity_digest, "source calculation identity")
        _require_digest(source_numeric_result_identity_digest, "source numeric result")
        _require_digest(source_coverage_witness_digest, "source coverage witness")
        _require_digest(transform_digest, "grid transform")
        _require_digest(grid_crs_digest, "grid CRS")
        if type(grid_rows) is not int or type(grid_columns) is not int:
            raise ValueError("grid dimensions must be integers")
        if grid_rows <= 0 or grid_columns <= 0:
            raise ValueError("grid dimensions must be positive")
        if grid_rows * grid_columns > self._policy.max_grid_cells:
            raise ValueError("grid exceeds the publication cell cap")
        if len(transform) != 6 or not all(type(item) is float for item in transform):
            raise ValueError("grid transform must be six floats")
        if len(bounds) != 4 or not all(type(item) is float for item in bounds):
            raise ValueError("grid bounds must be four floats")
        if not grid_crs_identifier.strip():
            raise ValueError("grid CRS identifier is invalid")
        self._require_lifetime(lifetime_seconds)
        output_id = f"delta-out-{publication_id}"
        if len(output_id) > 128:
            raise ValueError("publication identifier is too long for a derived output id")
        upload_fence_id = f"upload-fence-{publication_id}"
        requested = {
            "site_id": site_id,
            "work_area_id": work_area_id,
            "source_calculation_identity_digest": source_calculation_identity_digest,
            "source_numeric_result_identity_digest": source_numeric_result_identity_digest,
            "source_coverage_witness_digest": source_coverage_witness_digest,
            "grid_rows": grid_rows,
            "grid_columns": grid_columns,
            "transform": transform,
            "transform_digest": transform_digest,
            "grid_crs_identifier": grid_crs_identifier,
            "grid_crs_digest": grid_crs_digest,
            "bounds": bounds,
        }
        # One guarded section only: no pre-guard witness snapshot can go stale
        # beneath the decision, and idempotent retries re-prove currentness.
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            existing = self._entries.get((organization_id, publication_id))
            if existing is not None:
                if not self._binding_matches_request(existing, requested):
                    raise ValueError("publication id is already bound to other sources")
                witness = self._resolve_witness_locked(
                    organization_id=organization_id,
                    requested=requested,
                    now=trusted,
                )
                self._require_authority_current(trusted)
                return self._intent_view(existing)
            self._check_capacity_locked(trusted)
            witness = self._resolve_witness_locked(
                organization_id=organization_id,
                requested=requested,
                now=trusted,
            )
            self._require_authority_current(trusted)
            issued_at = trusted
            expires_at = trusted + _lifetime(lifetime_seconds)
            raw = {
                "kind": _KIND_INTENT_CREATED,
                "version": _VERSION,
                "organizationId": organization_id,
                "publicationId": publication_id,
                "siteId": site_id,
                "workAreaId": work_area_id,
                "sourceContractVersion": witness.source_contract_version,
                "sourceCalculationIdentityDigest": source_calculation_identity_digest,
                "sourceNumericResultIdentityDigest": source_numeric_result_identity_digest,
                "sourceCoverageWitnessDigest": source_coverage_witness_digest,
                "gridRows": grid_rows,
                "gridColumns": grid_columns,
                "transform": list(transform),
                "transformDigest": transform_digest,
                "gridCrsIdentifier": grid_crs_identifier,
                "gridCrsDigest": grid_crs_digest,
                "bounds": list(bounds),
                "outputId": output_id,
                "uploadFenceId": upload_fence_id,
                "issuedAt": iso_utc(issued_at),
                "expiresAt": iso_utc(expires_at),
                "policyDigest": self._policy_digest,
            }
            self._append_locked(raw)
            return self._intent_view(self._entries[(organization_id, publication_id)])

    def _require_lifetime(self, lifetime_seconds: int) -> None:
        if type(lifetime_seconds) is not int or isinstance(lifetime_seconds, bool):
            raise ValueError("lifetime must be an integer number of seconds")
        if lifetime_seconds <= 0 or lifetime_seconds > self._policy.max_lifetime_seconds:
            raise ValueError("lifetime exceeds the publication lifetime cap")

    def request_publication(
        self,
        *,
        principal: Principal,
        publication_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        lifetime_seconds: int,
    ) -> DeltaPublicationIntentView:
        """Source-only intent: the grid comes from the trusted witness.

        Unlike :meth:`create_intent` this helper accepts no grid at all —
        rows, columns, affine, CRS and bounds are derived from the real
        Core-resolved source under the shared guard and trusted clock, then
        the existing ``create_intent`` path binds and journals them.  A
        caller can therefore neither borrow another scope's grid nor smuggle
        a wrong one; unknown or out-of-scope sources fail closed.
        """
        self._require_intent_owner(principal)
        organization_id = principal.organization_id
        _require_opaque_id(publication_id, "publication")
        _require_scope_text(site_id, "site")
        _require_scope_text(work_area_id, "work area")
        self._require_caller_scope(principal, site_id, work_area_id)
        _require_digest(source_calculation_identity_digest, "source calculation identity")
        _require_digest(source_numeric_result_identity_digest, "source numeric result")
        _require_digest(source_coverage_witness_digest, "source coverage witness")
        self._require_lifetime(lifetime_seconds)
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            witness = self._source.resolve_current_source(
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                source_calculation_identity_digest=source_calculation_identity_digest,
                source_numeric_result_identity_digest=source_numeric_result_identity_digest,
                source_coverage_witness_digest=source_coverage_witness_digest,
                now=trusted,
            )
            if witness is None:
                raise RuntimeError("bound calculation sources are not currently available")
            if (
                witness.organization_id != organization_id
                or witness.site_id != site_id
                or witness.work_area_id != work_area_id
            ):
                raise RuntimeError("source witness is outside the requested scope")
            grid: dict[str, Any] = {
                "grid_rows": witness.grid_rows,
                "grid_columns": witness.grid_columns,
                "transform": witness.transform,
                "transform_digest": witness.transform_digest,
                "grid_crs_identifier": witness.grid_crs_identifier,
                "grid_crs_digest": witness.grid_crs_digest,
                "bounds": witness.bounds,
            }
        return self.create_intent(
            principal=principal,
            publication_id=publication_id,
            site_id=site_id,
            work_area_id=work_area_id,
            source_calculation_identity_digest=source_calculation_identity_digest,
            source_numeric_result_identity_digest=source_numeric_result_identity_digest,
            source_coverage_witness_digest=source_coverage_witness_digest,
            grid_rows=grid["grid_rows"],
            grid_columns=grid["grid_columns"],
            transform=grid["transform"],
            transform_digest=grid["transform_digest"],
            grid_crs_identifier=grid["grid_crs_identifier"],
            grid_crs_digest=grid["grid_crs_digest"],
            bounds=grid["bounds"],
            lifetime_seconds=lifetime_seconds,
            now=self._clock(),
        )

    @staticmethod
    def _binding_matches_request(entry: _PublicationEntry, requested: dict[str, Any]) -> bool:
        """Full binding equality: affine, CRS, bounds and digests, not just ids."""
        return (
            entry.site_id == requested["site_id"]
            and entry.work_area_id == requested["work_area_id"]
            and entry.source_calculation_identity_digest
            == requested["source_calculation_identity_digest"]
            and entry.source_numeric_result_identity_digest
            == requested["source_numeric_result_identity_digest"]
            and entry.source_coverage_witness_digest == requested["source_coverage_witness_digest"]
            and entry.grid_rows == requested["grid_rows"]
            and entry.grid_columns == requested["grid_columns"]
            and entry.transform == requested["transform"]
            and entry.transform_digest == requested["transform_digest"]
            and entry.grid_crs_identifier == requested["grid_crs_identifier"]
            and entry.grid_crs_digest == requested["grid_crs_digest"]
            and entry.bounds == requested["bounds"]
        )

    def _resolve_witness_locked(
        self,
        *,
        organization_id: str,
        requested: dict[str, Any],
        now: datetime,
    ) -> DeltaSourceWitness:
        """Resolve the trusted witness and require the exact caller binding."""
        witness = self._source.resolve_current_source(
            organization_id=organization_id,
            site_id=requested["site_id"],
            work_area_id=requested["work_area_id"],
            source_calculation_identity_digest=requested["source_calculation_identity_digest"],
            source_numeric_result_identity_digest=requested[
                "source_numeric_result_identity_digest"
            ],
            source_coverage_witness_digest=requested["source_coverage_witness_digest"],
            now=now,
        )
        return self._require_witness_grid(
            witness,
            organization_id=organization_id,
            site_id=requested["site_id"],
            work_area_id=requested["work_area_id"],
            source_calculation_identity_digest=requested["source_calculation_identity_digest"],
            source_numeric_result_identity_digest=requested[
                "source_numeric_result_identity_digest"
            ],
            source_coverage_witness_digest=requested["source_coverage_witness_digest"],
            grid_rows=requested["grid_rows"],
            grid_columns=requested["grid_columns"],
            transform=requested["transform"],
            transform_digest=requested["transform_digest"],
            grid_crs_identifier=requested["grid_crs_identifier"],
            grid_crs_digest=requested["grid_crs_digest"],
            bounds=requested["bounds"],
        )

    def _resolve_bound_observation(
        self,
        *,
        entry: _PublicationEntry,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_generation: int,
        now: datetime,
    ) -> DeltaOutputObservation | None:
        """Resolve the trusted output acceptance and require its exact binding.

        The observation must name this exact intent (scope, pinned source
        version and digests, grid), this exact lease holder and generation,
        and an output hash/size within the publication byte cap.  The staged
        stream is then verified against the observation's hash/size — never
        against caller-declared values, which are not accepted at all.
        Anything else — including a valid lease with merely caller-asserted
        bytes — fails closed.  ``None`` never distinguishes the cause.
        """
        try:
            observation = self._observations.resolve_output_observation(
                organization_id=entry.organization_id,
                publication_id=entry.publication_id,
                worker_principal_id=worker_principal.principal_id,
                worker_instance_id=worker_instance_id,
                lease_generation=lease_generation,
                now=now,
            )
        except Exception:
            return None
        if observation is None:
            return None
        if not isinstance(observation, DeltaOutputObservation):
            return None
        if observation.observation_digest is None or (
            observation.observation_digest != observation.canonical_digest()
        ):
            return None
        if not self._observation_matches_entry(
            observation,
            entry,
            worker_principal_id=worker_principal.principal_id,
            worker_instance_id=worker_instance_id,
            lease_generation=lease_generation,
        ):
            return None
        return observation

    def _observation_matches_entry(
        self,
        observation: DeltaOutputObservation,
        entry: _PublicationEntry,
        *,
        worker_principal_id: str,
        worker_instance_id: str,
        lease_generation: int,
    ) -> bool:
        """The acceptance must bind the intent, the lease and the byte cap."""
        return (
            observation.organization_id == entry.organization_id
            and observation.site_id == entry.site_id
            and observation.work_area_id == entry.work_area_id
            and observation.source_contract_version == entry.source_contract_version
            and observation.source_calculation_identity_digest
            == entry.source_calculation_identity_digest
            and observation.source_numeric_result_identity_digest
            == entry.source_numeric_result_identity_digest
            and observation.source_coverage_witness_digest == entry.source_coverage_witness_digest
            and observation.publication_id == entry.publication_id
            and observation.worker_principal_id == worker_principal_id
            and observation.worker_instance_id == worker_instance_id
            and observation.lease_generation == lease_generation
            and observation.lease_generation == entry.lease_generation
            and observation.worker_principal_id == entry.lease_holder_principal_id
            and observation.worker_instance_id == entry.lease_holder_instance_id
            and observation.output_size_bytes <= self._policy.max_output_bytes
            and observation.grid_rows == entry.grid_rows
            and observation.grid_columns == entry.grid_columns
            and observation.transform == entry.transform
            and observation.transform_digest == entry.transform_digest
            and observation.grid_crs_identifier == entry.grid_crs_identifier
            and observation.grid_crs_digest == entry.grid_crs_digest
            and observation.bounds == entry.bounds
        )

    # -- worker upload lease (server-bound) -------------------------------------

    def acquire_upload_lease(
        self,
        *,
        worker_principal: Principal,
        publication_id: str,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> DeltaPublicationIntentView | None:
        """Issue a worker-bound upload lease for one pending intent.

        The lease binds the exact worker principal, its instance, a fresh
        acquisition id, a server generation and a bounded expiry.  Only the
        recorded holder may upload or fail that generation while it is live;
        any other worker in the same organization observes ``None`` without
        distinguishing the cause.  Issuance requires currently bound sources
        plus current policy and worker-tied runtime authority.
        """
        self._require_worker(worker_principal)
        self._require_utc(now)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(worker_instance_id, str) or not worker_instance_id.strip():
            raise ValueError("worker instance is required")
        if len(worker_instance_id) > 255:
            raise ValueError("worker instance is invalid")
        if not isinstance(lease_acquisition_id, str) or not lease_acquisition_id.strip():
            raise ValueError("lease acquisition is required")
        if len(lease_acquisition_id) > 255:
            raise ValueError("lease acquisition is invalid")
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            entry = self._entries.get((worker_principal.organization_id, publication_id))
            if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
                return None
            if not self._caller_scope_allows(worker_principal, entry.site_id, entry.work_area_id):
                return None
            if trusted >= entry.expires_at:
                return None
            live = self._live_lease(entry, trusted)
            if live is not None:
                if (
                    live["principal_id"] == worker_principal.principal_id
                    and live["instance_id"] == worker_instance_id
                    and live["acquisition_id"] == lease_acquisition_id
                ):
                    # An idempotent retry must re-prove currentness; a source,
                    # policy or runtime change since issuance returns None
                    # without a misleading fence or journal delta.
                    if not self._lease_issue_checks(
                        entry,
                        worker_principal,
                        entry.lease_generation,
                        trusted,
                    ):
                        return None
                    return self._intent_view(entry)
                return None
            if lease_acquisition_id in entry.seen_acquisition_ids:
                return None
            generation = entry.lease_generation + 1
            if generation > self._policy.max_upload_attempts:
                return None
            if not self._lease_issue_checks(entry, worker_principal, generation, trusted):
                return None
            lease_issued_at = trusted
            lease_expires_at = min(
                trusted + _lifetime(self._policy.upload_lease_duration_seconds),
                entry.expires_at,
            )
            if lease_issued_at >= lease_expires_at:
                return None
            raw = {
                "kind": _KIND_LEASED,
                "version": _VERSION,
                "organizationId": entry.organization_id,
                "publicationId": entry.publication_id,
                "leaseGeneration": generation,
                "holderPrincipalId": worker_principal.principal_id,
                "holderInstanceId": worker_instance_id,
                "leaseAcquisitionId": lease_acquisition_id,
                "issuedAt": iso_utc(lease_issued_at),
                "expiresAt": iso_utc(lease_expires_at),
            }
            self._append_locked(raw)
            return self._intent_view(self._entries[(entry.organization_id, entry.publication_id)])

    def _lease_issue_checks(
        self,
        entry: _PublicationEntry,
        worker_principal: Principal,
        generation: int,
        trusted: datetime,
    ) -> bool:
        """Re-prove source, policy and worker-tied runtime for one generation.

        Used both for fresh issuance and for idempotent reclaim of a live
        lease, so a retry can never present a stale fence as current.
        """
        witness = self._source.resolve_current_source(
            organization_id=entry.organization_id,
            site_id=entry.site_id,
            work_area_id=entry.work_area_id,
            source_calculation_identity_digest=entry.source_calculation_identity_digest,
            source_numeric_result_identity_digest=entry.source_numeric_result_identity_digest,
            source_coverage_witness_digest=entry.source_coverage_witness_digest,
            now=trusted,
        )
        if witness is None or not self._witness_matches_entry(witness, entry):
            return False
        if not self._authority.is_policy_current(policy_digest=entry.policy_digest, now=trusted):
            return False
        return bool(
            self._authority.is_runtime_current(
                now=trusted,
                worker_principal_id=worker_principal.principal_id,
                publication_id=entry.publication_id,
                lease_generation=generation,
            )
        )

    @staticmethod
    def _live_lease(entry: _PublicationEntry, trusted: datetime) -> dict[str, str] | None:
        """The recorded lease if it is still live at the trusted timestamp."""
        if (
            entry.lease_generation <= 0
            or entry.lease_holder_principal_id is None
            or entry.lease_holder_instance_id is None
            or entry.lease_acquisition_id is None
            or entry.lease_issued_at is None
            or entry.lease_expires_at is None
            or trusted >= entry.lease_expires_at
        ):
            return None
        return {
            "principal_id": entry.lease_holder_principal_id,
            "instance_id": entry.lease_holder_instance_id,
            "acquisition_id": entry.lease_acquisition_id,
        }

    def _lease_matches_caller(
        self,
        entry: _PublicationEntry,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_generation: int,
        trusted: datetime,
    ) -> bool:
        """Only the recorded holder may act on a live generation."""
        if type(lease_generation) is not int or lease_generation <= 0:
            return False
        live = self._live_lease(entry, trusted)
        if live is None:
            return False
        return (
            entry.lease_generation == lease_generation
            and live["principal_id"] == worker_principal.principal_id
            and live["instance_id"] == worker_instance_id
        )

    def intent_for_worker(
        self,
        publication_id: str,
        *,
        worker_principal: Principal,
        worker_instance_id: str,
    ) -> DeltaPublicationIntentView | None:
        """Reveal the intent only to the live lease holder; all others see None.

        Any pending same-organization fence is hidden from workers that do
        not hold its live lease, so one worker can never observe — let alone
        reuse — another worker's fence.
        """
        self._require_worker(worker_principal)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(worker_instance_id, str) or not worker_instance_id.strip():
            raise ValueError("worker instance is required")
        with self._lock:
            entry = self._entries.get((worker_principal.organization_id, publication_id))
            if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
                return None
            if not self._caller_scope_allows(worker_principal, entry.site_id, entry.work_area_id):
                return None
            trusted = self._clock()
            live = self._live_lease(entry, trusted)
            if (
                live is None
                or live["principal_id"] != worker_principal.principal_id
                or live["instance_id"] != worker_instance_id
            ):
                return None
            return self._intent_view(entry)

    def list_pending_for_worker(
        self,
        *,
        worker_principal: Principal,
        limit: int = 50,
        source_contract_version: str | None = None,
    ) -> tuple[str, ...]:
        """Bounded worker job discovery: pending publication ids this worker may take.

        Returns only organization-scoped, caller-scoped, unexpired
        ``PENDING`` publication ids with no live lease whose sources, policy
        and worker-tied runtime are currently authorizing this exact
        worker — resolved under the shared guard at the trusted clock, the
        same gate a later ``acquire_upload_lease`` must pass.  A lapsed
        lease does not hide the intent: a crashed or restarted worker that
        lost its known id recovers the job through discovery and
        re-acquires it with a fresh acquisition id and the next generation,
        so the signed attempt cap stays meaningful for driver recovery.
        Terminal records, expired or out-of-scope intents, stale sources
        and cap-exhausted intents are skipped.  Only opaque ids are
        returned: no fences, hashes, grids or byte metadata leak to a
        worker that has not acquired the lease.  Read-only: no journal
        event is appended however often it is polled.  The scan walks the
        pending index (maintained on journal apply), not the full journal
        history, and stops at ``limit``.
        """
        self._require_worker(worker_principal)
        if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
            raise ValueError("discovery limit must be an integer between 1 and 50")
        if source_contract_version not in {
            None,
            "external-relative-volume-calculation-report.v2",
            "external-masked-volume-calculation-identity.v3",
        }:
            raise ValueError("discovery source version must name the V2 or V3 source contract")
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            found: list[str] = []
            for key in self._pending:
                if len(found) >= limit:
                    break
                entry = self._entries.get(key)
                if entry is None:
                    continue
                if entry.organization_id != worker_principal.organization_id:
                    continue
                if entry.status is not DeltaPublicationStatusV1.PENDING:
                    continue
                # Filter before limit/lease: a differently configured native
                # worker must never consume another calculation lane's retry.
                if (
                    source_contract_version is not None
                    and entry.source_contract_version != source_contract_version
                ):
                    continue
                if not self._caller_scope_allows(
                    worker_principal, entry.site_id, entry.work_area_id
                ):
                    continue
                if trusted >= entry.expires_at:
                    continue
                if self._live_lease(entry, trusted) is not None:
                    continue
                if entry.lease_generation >= self._policy.max_upload_attempts:
                    continue
                if not self._lease_issue_checks(
                    entry,
                    worker_principal,
                    entry.lease_generation + 1,
                    trusted,
                ):
                    continue
                found.append(entry.publication_id)
            return tuple(found)

    def publish_output(
        self,
        *,
        worker_principal: Principal,
        publication_id: str,
        worker_instance_id: str,
        lease_generation: int,
        byte_stream: BinaryIO,
    ) -> DeltaPublicationView | None:
        """Durably publish worker bytes bound to the live upload lease.

        Timing comes from the injected trusted clock, never a caller-passed
        timestamp: a slow stream cannot outlive the lease or the intent and
        still publish.  Publication additionally requires the trusted output
        observation — the separately authenticated, pinned worker result
        acceptance naming this exact publication, worker, generation, output
        hash/size and grid.  The observation is compared before staging and
        re-resolved after the trusted finish recheck; a missing or mismatched
        observation fails closed even for the lease-holding worker.  No
        caller-declared hash or size is accepted at all: the staged stream is
        verified solely against the observation, and the descriptor asserts
        only the format and grid the observation already established.  The
        guarded finish recheck (lease holder, observation, source, policy,
        worker-tied runtime, expiry) and the journal append precede the
        atomic byte commit.  Returns ``None`` for unknown, foreign, unleased,
        unobserved, stale-lease or non-pending records without distinguishing
        them.
        """
        self._require_worker(worker_principal)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(worker_instance_id, str) or not worker_instance_id.strip():
            raise ValueError("worker instance is required")
        if type(lease_generation) is not int or lease_generation <= 0:
            raise ValueError("lease generation is invalid")
        # Fast pre-stage gate under lock only (no authority I/O): an
        # obviously unleased or non-pending record never reaches staging.
        with self._lock:
            entry = self._entries.get((worker_principal.organization_id, publication_id))
            if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
                return None
            if not self._caller_scope_allows(worker_principal, entry.site_id, entry.work_area_id):
                return None
            pre_trusted = self._clock()
            if not self._lease_matches_caller(
                entry, worker_principal, worker_instance_id, lease_generation, pre_trusted
            ):
                return None
            output_id = entry.output_id
        first_observation = self._resolve_bound_observation(
            entry=entry,
            worker_principal=worker_principal,
            worker_instance_id=worker_instance_id,
            lease_generation=lease_generation,
            now=pre_trusted,
        )
        if first_observation is None:
            return None
        staged: Path | None = None
        try:
            staged = self._bytes.stage_stream(
                stream=byte_stream,
                expected_sha256=first_observation.output_sha256,
                expected_size_bytes=first_observation.output_size_bytes,
                max_bytes=self._policy.max_output_bytes,
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"output bytes cannot be staged: {exc}") from exc
        assert staged is not None
        try:
            with self._coordinator.guarded_read(), self._lock:
                trusted = self._clock()
                self._require_utc(trusted)
                entry = self._entries.get((worker_principal.organization_id, publication_id))
                if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
                    return None
                if not self._caller_scope_allows(
                    worker_principal, entry.site_id, entry.work_area_id
                ):
                    return None
                if not self._lease_matches_caller(
                    entry, worker_principal, worker_instance_id, lease_generation, trusted
                ):
                    return None
                if trusted >= entry.expires_at:
                    return None
                witness = self._source.resolve_current_source(
                    organization_id=entry.organization_id,
                    site_id=entry.site_id,
                    work_area_id=entry.work_area_id,
                    source_calculation_identity_digest=entry.source_calculation_identity_digest,
                    source_numeric_result_identity_digest=entry.source_numeric_result_identity_digest,
                    source_coverage_witness_digest=entry.source_coverage_witness_digest,
                    now=trusted,
                )
                if witness is None or not self._witness_matches_entry(witness, entry):
                    return None
                if not self._authority_is_current(
                    trusted,
                    entry.policy_digest,
                    worker_principal_id=worker_principal.principal_id,
                    publication_id=entry.publication_id,
                    lease_generation=entry.lease_generation,
                ):
                    return None
                observation = self._resolve_bound_observation(
                    entry=entry,
                    worker_principal=worker_principal,
                    worker_instance_id=worker_instance_id,
                    lease_generation=lease_generation,
                    now=trusted,
                )
                if observation is None or observation != first_observation:
                    # The acceptance must still name these exact bytes after
                    # the trusted recheck; a vanished or rotated observation
                    # fails closed even for the lease holder.
                    return None
                descriptor = DeltaRasterPublicationV1(
                    publication_id=entry.publication_id,
                    organization_id=entry.organization_id,
                    site_id=entry.site_id,
                    work_area_id=entry.work_area_id,
                    source_contract_version=observation.source_contract_version,
                    source_calculation_identity_digest=observation.source_calculation_identity_digest,
                    source_numeric_result_identity_digest=observation.source_numeric_result_identity_digest,
                    source_coverage_witness_digest=observation.source_coverage_witness_digest,
                    delta_sign=observation.delta_sign,
                    grid_rows=observation.grid_rows,
                    grid_columns=observation.grid_columns,
                    transform=observation.transform,
                    transform_digest=observation.transform_digest,
                    grid_crs_identifier=observation.grid_crs_identifier,
                    grid_crs_digest=observation.grid_crs_digest,
                    bounds=observation.bounds,
                    vertical_unit="metre",
                    dtype=observation.dtype,
                    output_id=entry.output_id,
                    output_sha256=observation.output_sha256,
                    output_size_bytes=observation.output_size_bytes,
                    issued_at=entry.issued_at,
                    expires_at=entry.expires_at,
                    publication_policy_digest=self._policy_digest,
                ).sealed()
                if not self._observation_matches_entry(
                    observation,
                    entry,
                    worker_principal_id=worker_principal.principal_id,
                    worker_instance_id=worker_instance_id,
                    lease_generation=lease_generation,
                ):
                    return None
                raw = {
                    "kind": _KIND_PUBLISHED,
                    "version": _VERSION,
                    "organizationId": entry.organization_id,
                    "publicationId": entry.publication_id,
                    "leaseGeneration": entry.lease_generation,
                    "holderPrincipalId": worker_principal.principal_id,
                    "holderInstanceId": worker_instance_id,
                    "observationDigest": observation.canonical_digest(),
                    "observation": observation.canonical_payload(),
                    "descriptor": descriptor.model_dump(by_alias=True, mode="json"),
                }
                self._append_locked(raw)
                try:
                    self._bytes.commit(output_id=output_id, staged=staged)
                except Exception:
                    # The journal is the durable truth; missing bytes fail
                    # closed at read time.  Never roll the journal back.
                    return self._public_view(
                        self._entries[(entry.organization_id, entry.publication_id)]
                    )
                return self._public_view(
                    self._entries[(entry.organization_id, entry.publication_id)]
                )
        finally:
            if staged is not None:
                self._bytes.discard(staged=staged)

    def record_upload_failure(
        self,
        *,
        worker_principal: Principal,
        publication_id: str,
        worker_instance_id: str,
        lease_generation: int,
        reason: str,
        now: datetime,
    ) -> DeltaPublicationIntentView | None:
        """Durably mark a leased upload as failed; published bytes never appear."""
        self._require_worker(worker_principal)
        self._require_utc(now)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(worker_instance_id, str) or not worker_instance_id.strip():
            raise ValueError("worker instance is required")
        if type(lease_generation) is not int or lease_generation <= 0:
            raise ValueError("lease generation is invalid")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 255:
            raise ValueError("failure reason is required")
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            entry = self._entries.get((worker_principal.organization_id, publication_id))
            if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
                return None
            if not self._caller_scope_allows(worker_principal, entry.site_id, entry.work_area_id):
                return None
            if not self._lease_matches_caller(
                entry, worker_principal, worker_instance_id, lease_generation, trusted
            ):
                return None
            if trusted >= entry.expires_at:
                return None
            raw = {
                "kind": _KIND_FAILED,
                "version": _VERSION,
                "organizationId": entry.organization_id,
                "publicationId": entry.publication_id,
                "leaseGeneration": entry.lease_generation,
                "holderPrincipalId": worker_principal.principal_id,
                "holderInstanceId": worker_instance_id,
                "reason": reason.strip(),
                "failedAt": iso_utc(trusted),
            }
            self._append_locked(raw)
            return self._intent_view(self._entries[(entry.organization_id, entry.publication_id)])

    # -- human terminal transitions ------------------------------------------

    def intent_matches_scope(
        self,
        *,
        principal: Principal,
        publication_id: str,
        site_id: str,
        work_area_id: str,
    ) -> bool:
        """Path-scope predicate for cancel/revoke routing: never mutates.

        Returns True only when the caller's organization owns the record,
        the record's immutable scope equals the requested path scope, and
        the caller is allowed in that scope.  Anything else — unknown ids,
        foreign organizations, path/entry scope drift, out-of-scope callers
        or malformed identifiers — is False, never an exception, so routing
        layers can refuse before any terminal transition runs.
        """
        if (
            not isinstance(publication_id, str)
            or not isinstance(site_id, str)
            or not isinstance(work_area_id, str)
        ):
            return False
        try:
            _require_opaque_id(publication_id, "publication")
            _require_scope_text(site_id, "site")
            _require_scope_text(work_area_id, "work area")
        except ValueError:
            return False
        with self._lock:
            entry = self._entries.get((principal.organization_id, publication_id))
        if entry is None:
            return False
        if entry.site_id != site_id or entry.work_area_id != work_area_id:
            return False
        return self._caller_scope_allows(principal, entry.site_id, entry.work_area_id)

    def cancel_intent(
        self, *, principal: Principal, publication_id: str, reason: str, now: datetime
    ) -> DeltaPublicationIntentView | None:
        """Cancel a pending intent; a canceled fence can never publish.

        The terminal timestamp comes from the injected trusted clock, never
        the caller stamp, so a backdated or future caller ``now`` cannot
        rewrite history; ``now`` is validated only as a well-formed request
        time.
        """
        self._require_intent_owner(principal)
        self._require_utc(now)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 255:
            raise ValueError("cancel reason is required")
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            entry = self._entries.get((principal.organization_id, publication_id))
            if entry is None:
                return None
            self._require_caller_scope(principal, entry.site_id, entry.work_area_id)
            if entry.status is not DeltaPublicationStatusV1.PENDING:
                return None
            raw = {
                "kind": _KIND_CANCELED,
                "version": _VERSION,
                "organizationId": entry.organization_id,
                "publicationId": entry.publication_id,
                "reason": reason.strip(),
                "canceledAt": iso_utc(trusted),
            }
            self._append_locked(raw)
            return self._intent_view(self._entries[(entry.organization_id, entry.publication_id)])

    def revoke(
        self, *, principal: Principal, publication_id: str, reason: str, now: datetime
    ) -> DeltaPublicationView | None:
        """Revoke a published output; the historical descriptor is immutable.

        The terminal timestamp comes from the injected trusted clock, never
        the caller stamp (see :meth:`cancel_intent`).
        """
        self._require_intent_owner(principal)
        self._require_utc(now)
        _require_opaque_id(publication_id, "publication")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 255:
            raise ValueError("revocation reason is required")
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            entry = self._entries.get((principal.organization_id, publication_id))
            if entry is None:
                return None
            self._require_caller_scope(principal, entry.site_id, entry.work_area_id)
            if entry.status is not DeltaPublicationStatusV1.PUBLISHED:
                return None
            raw = {
                "kind": _KIND_REVOKED,
                "version": _VERSION,
                "organizationId": entry.organization_id,
                "publicationId": entry.publication_id,
                "reason": reason.strip(),
                "revokedAt": iso_utc(trusted),
            }
            self._append_locked(raw)
            return self._public_view(self._entries[(entry.organization_id, entry.publication_id)])

    # -- guarded reads --------------------------------------------------------

    def get_current(
        self, publication_id: str, *, principal: Principal, now: datetime
    ) -> DeltaPublicationView | None:
        """Return the publication only if currently readable; else ``None``."""
        view, _ = self.get_current_with_disposition(publication_id, principal=principal, now=now)
        return view

    def get_current_with_disposition(
        self, publication_id: str, *, principal: Principal, now: datetime
    ) -> tuple[DeltaPublicationView | None, DeltaPublicationDispositionV1]:
        """Read with an explicit disposition; foreign/unknown ids are NOT_FOUND.

        Every currentness input — scope, status, expiry, source witness,
        policy, runtime, egress and byte integrity — is resolved inside one
        shared guarded section against the trusted clock, so no stale
        pre-guard snapshot can bless the result.
        """
        self._require_read(principal)
        self._require_utc(now)
        _require_opaque_id(publication_id, "publication")
        if not self._caller_scope_allows_for_lookup(principal, publication_id):
            return None, DeltaPublicationDispositionV1.NOT_FOUND
        with self._coordinator.guarded_read(), self._lock:
            trusted = self._clock()
            self._require_utc(trusted)
            entry = self._entries.get((principal.organization_id, publication_id))
            disposition = self._check_live(entry, principal, trusted)
            if disposition is not DeltaPublicationDispositionV1.AVAILABLE:
                assert entry is not None or disposition is DeltaPublicationDispositionV1.NOT_FOUND
                return None, disposition
            assert entry is not None and entry.descriptor is not None
            if not self._verify_bytes_integrity(entry):
                return None, DeltaPublicationDispositionV1.BYTES_UNAVAILABLE
            return self._public_view(entry), DeltaPublicationDispositionV1.AVAILABLE

    def _caller_scope_allows_for_lookup(self, principal: Principal, publication_id: str) -> bool:
        """Scope pre-check that maps foreign entries to NOT_FOUND, never raises."""
        with self._lock:
            entry = self._entries.get((principal.organization_id, publication_id))
        if entry is None:
            return True
        return self._caller_scope_allows(principal, entry.site_id, entry.work_area_id)

    def read_bytes(
        self,
        publication_id: str,
        *,
        principal: Principal,
        offset: int,
        length: int,
    ) -> bytes | None:
        """Return one bounded byte slice only if the publication is readable now.

        Timing comes from the injected trusted clock at two points: the
        pre-stream check and a second recheck after the bounded stream
        completes.  A revocation, source/authority/egress change or expiry
        landing mid-stream therefore fails closed instead of leaking bytes
        that were current only when the call started.  The full file content
        is hash-verified while streaming, but only the requested window —
        never more than ``length`` bytes — is retained in memory.  ``None``
        means not currently readable (same indistinguishability as
        :meth:`get_current`); invalid bounds raise.
        """
        self._require_read(principal)
        _require_opaque_id(publication_id, "publication")
        if type(offset) is not int or type(length) is not int:
            raise ValueError("byte range must be integers")
        if offset < 0 or length <= 0 or length > self._policy.max_output_bytes:
            raise ValueError("byte range is invalid")
        with self._coordinator.guarded_read(), self._lock:
            entry = self._entries.get((principal.organization_id, publication_id))
            if entry is None:
                return None
            if not self._caller_scope_allows(principal, entry.site_id, entry.work_area_id):
                return None
            trusted_before = self._clock()
            self._require_utc(trusted_before)
            if (
                self._check_live(entry, principal, trusted_before)
                is not DeltaPublicationDispositionV1.AVAILABLE
            ):
                return None
            assert entry.descriptor is not None
            expected_size = entry.descriptor.output_size_bytes
            if offset + length > expected_size:
                raise ValueError("byte range exceeds the published output size")
            window = self._stream_verified_window(
                entry,
                offset=offset,
                length=length,
                expected_size=expected_size,
                expected_sha256=entry.descriptor.output_sha256,
            )
            if window is None:
                return None
            trusted_after = self._clock()
            self._require_utc(trusted_after)
            entry = self._entries.get((principal.organization_id, publication_id))
            if (
                self._check_live(entry, principal, trusted_after)
                is not DeltaPublicationDispositionV1.AVAILABLE
            ):
                return None
            return window

    def _stream_verified_window(
        self,
        entry: _PublicationEntry,
        *,
        offset: int,
        length: int,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes | None:
        """Hash-verify the whole file while retaining only the requested window.

        Every byte of the committed file passes through the SHA-256 digest,
        but only bytes in ``[offset, offset+length)`` are kept — at most
        ``length`` bytes (itself capped by the publication byte cap), never
        the full output.  Truncation, same-size tampering, oversize content
        and swaps all fail closed with ``None``.
        """
        try:
            handle = self._bytes.open_read(output_id=entry.output_id)
        except (FileNotFoundError, OSError, ValueError):
            return None
        hasher = hashlib.sha256()
        kept = bytearray()
        position = 0
        window_end = offset + length
        try:
            with handle:
                while True:
                    chunk = handle.read(_STREAM_CHUNK_BYTES)
                    if chunk is None:
                        return None
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        return None
                    chunk_len = len(chunk)
                    position += chunk_len
                    if position > self._policy.max_output_bytes:
                        return None
                    hasher.update(chunk)
                    chunk_start = position - chunk_len
                    if chunk_start < window_end and position > offset:
                        keep_from = max(0, offset - chunk_start)
                        keep_to = min(chunk_len, window_end - chunk_start)
                        kept.extend(chunk[keep_from:keep_to])
                        if len(kept) > length:
                            return None
        except (OSError, ValueError):
            return None
        if position != expected_size:
            return None
        if "sha256:" + hasher.hexdigest() != expected_sha256:
            return None
        if len(kept) != length:
            return None
        return bytes(kept)

    def _check_live(
        self,
        entry: _PublicationEntry | None,
        principal: Principal,
        trusted: datetime,
    ) -> DeltaPublicationDispositionV1:
        """Full currentness decision for one entry at a trusted timestamp.

        Must run under the shared guard plus store lock.  Performs no byte
        I/O; byte integrity is verified separately by
        :meth:`_verify_bytes_integrity` (availability) and
        :meth:`_stream_verified_window` (slices) on the read path.
        """
        if entry is None:
            return DeltaPublicationDispositionV1.NOT_FOUND
        if not self._caller_scope_allows(principal, entry.site_id, entry.work_area_id):
            return DeltaPublicationDispositionV1.NOT_FOUND
        if entry.status is DeltaPublicationStatusV1.PENDING:
            return DeltaPublicationDispositionV1.NOT_YET_PUBLISHED
        if entry.status is DeltaPublicationStatusV1.CANCELED:
            return DeltaPublicationDispositionV1.CANCELED
        if entry.status is DeltaPublicationStatusV1.FAILED:
            return DeltaPublicationDispositionV1.FAILED
        if entry.status is DeltaPublicationStatusV1.REVOKED:
            return DeltaPublicationDispositionV1.REVOKED
        if entry.status is not DeltaPublicationStatusV1.PUBLISHED:
            return DeltaPublicationDispositionV1.NOT_FOUND
        if trusted >= entry.expires_at:
            return DeltaPublicationDispositionV1.EXPIRED
        witness = self._source.resolve_current_source(
            organization_id=entry.organization_id,
            site_id=entry.site_id,
            work_area_id=entry.work_area_id,
            source_calculation_identity_digest=entry.source_calculation_identity_digest,
            source_numeric_result_identity_digest=entry.source_numeric_result_identity_digest,
            source_coverage_witness_digest=entry.source_coverage_witness_digest,
            now=trusted,
        )
        if witness is None or not self._witness_matches_entry(witness, entry):
            return DeltaPublicationDispositionV1.SOURCE_NOT_CURRENT
        if not self._authority.is_policy_current(policy_digest=entry.policy_digest, now=trusted):
            return DeltaPublicationDispositionV1.POLICY_NOT_CURRENT
        if not self._authority.is_runtime_current(now=trusted):
            return DeltaPublicationDispositionV1.RUNTIME_NOT_CURRENT
        if not self._egress.is_egress_allowed(
            organization_id=entry.organization_id,
            site_id=entry.site_id,
            work_area_id=entry.work_area_id,
            principal=principal,
            now=trusted,
        ):
            return DeltaPublicationDispositionV1.EGRESS_DENIED
        return DeltaPublicationDispositionV1.AVAILABLE

    def _verify_bytes_integrity(self, entry: _PublicationEntry) -> bool:
        """Prove the committed bytes match the sealed descriptor, retaining zero.

        Streams the whole file in bounded chunks through SHA-256 and
        compares size plus digest, keeping nothing in memory.  Same-size
        content tampering, truncation and swaps all fail closed.
        """
        descriptor = entry.descriptor
        if descriptor is None:
            return False
        try:
            handle = self._bytes.open_read(output_id=entry.output_id)
        except (FileNotFoundError, OSError, ValueError):
            return False
        hasher = hashlib.sha256()
        total = 0
        try:
            with handle:
                while True:
                    chunk = handle.read(_STREAM_CHUNK_BYTES)
                    if chunk is None:
                        return False
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        return False
                    total += len(chunk)
                    if total > self._policy.max_output_bytes:
                        return False
                    hasher.update(chunk)
        except (OSError, ValueError):
            return False
        return (
            total == descriptor.output_size_bytes
            and ("sha256:" + hasher.hexdigest()) == descriptor.output_sha256
        )

    # -- internal guards -------------------------------------------------------

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("publication time must be UTC")

    @staticmethod
    def _require_intent_owner(principal: Principal) -> None:
        """Only a human owner (or scoped MCP creator) may create/cancel/revoke."""
        if principal.kind is PrincipalKind.ANALYSIS_WORKER or principal.kind in (
            PrincipalKind.PROCESSING_WORKER,
            PrincipalKind.SPATIAL_DATA_WORKER,
            PrincipalKind.EDGE_DEVICE,
            PrincipalKind.GATEWAY_DEVICE,
            PrincipalKind.EDGE_ROUTE_OBSERVER,
        ):
            raise PermissionError("publication intent requires a human owner")
        granted = principal_permissions(principal)
        allowed = (
            Permission.ANALYSIS_API_CREATE in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_WRITE in granted
        )
        if not allowed:
            raise PermissionError("publication intent requires SITES_WRITE")

    @staticmethod
    def _require_worker(principal: Principal) -> None:
        if (
            principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or Permission.ANALYSIS_WORK not in principal_permissions(principal)
        ):
            raise PermissionError("publication upload requires analysis worker scope")

    @staticmethod
    def _require_read(principal: Principal) -> None:
        granted = principal_permissions(principal)
        allowed = (
            Permission.ANALYSIS_API_READ in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_READ in granted
        )
        if not allowed:
            raise PermissionError("publication read requires SITES_READ")

    @staticmethod
    def _caller_scope_allows(principal: Principal, site_id: str, work_area_id: str) -> bool:
        """Caller rights over one site/work-area: MCP clients AND OIDC operators.

        A ``None`` allow-set preserves the existing opaque meaning (full
        organization access); an explicit set — MCP or OIDC-mapped operator —
        restricts to its members.  The source witness carries no principal,
        so this check must run on every store entry point; the router alone
        is never the scope boundary.
        """
        if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT:
            return (
                principal.allowed_site_ids is not None
                and site_id in principal.allowed_site_ids
                and principal.allowed_work_area_ids is not None
                and work_area_id in principal.allowed_work_area_ids
            )
        if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
            return False
        return not (
            principal.allowed_work_area_ids is not None
            and work_area_id not in principal.allowed_work_area_ids
        )

    @classmethod
    def _require_caller_scope(cls, principal: Principal, site_id: str, work_area_id: str) -> None:
        if not cls._caller_scope_allows(principal, site_id, work_area_id):
            raise PermissionError("publication is outside caller scope")

    def _require_witness_grid(
        self,
        witness: DeltaSourceWitness | None,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        grid_rows: int,
        grid_columns: int,
        transform: tuple[float, float, float, float, float, float],
        transform_digest: str,
        grid_crs_identifier: str,
        grid_crs_digest: str,
        bounds: tuple[float, float, float, float],
    ) -> DeltaSourceWitness:
        """The witness is Core truth; caller grids must match it exactly."""
        if witness is None:
            raise RuntimeError("bound calculation sources are not currently available")
        if (
            witness.organization_id != organization_id
            or witness.site_id != site_id
            or witness.work_area_id != work_area_id
            or witness.source_calculation_identity_digest != source_calculation_identity_digest
            or witness.source_numeric_result_identity_digest
            != source_numeric_result_identity_digest
            or witness.source_coverage_witness_digest != source_coverage_witness_digest
            or witness.grid_rows != grid_rows
            or witness.grid_columns != grid_columns
            or witness.transform != transform
            or witness.transform_digest != transform_digest
            or witness.grid_crs_identifier != grid_crs_identifier
            or witness.grid_crs_digest != grid_crs_digest
            or witness.bounds != bounds
        ):
            raise RuntimeError("publication grid does not match the bound sources")
        return witness

    @staticmethod
    def _witness_matches_entry(witness: DeltaSourceWitness, entry: _PublicationEntry) -> bool:
        return (
            witness.organization_id == entry.organization_id
            and witness.site_id == entry.site_id
            and witness.work_area_id == entry.work_area_id
            and witness.source_contract_version == entry.source_contract_version
            and witness.source_calculation_identity_digest
            == entry.source_calculation_identity_digest
            and witness.source_numeric_result_identity_digest
            == entry.source_numeric_result_identity_digest
            and witness.source_coverage_witness_digest == entry.source_coverage_witness_digest
            and witness.grid_rows == entry.grid_rows
            and witness.grid_columns == entry.grid_columns
            and witness.transform == entry.transform
            and witness.transform_digest == entry.transform_digest
            and witness.grid_crs_identifier == entry.grid_crs_identifier
            and witness.grid_crs_digest == entry.grid_crs_digest
            and witness.bounds == entry.bounds
        )

    def _require_authority_current(self, now: datetime) -> None:
        if not self._authority.is_policy_current(policy_digest=self._policy_digest, now=now):
            raise RuntimeError("publication policy is not currently authorized")
        if not self._authority.is_runtime_current(now=now):
            raise RuntimeError("publication runtime is not currently authorized")

    def _authority_is_current(
        self,
        now: datetime,
        policy_digest: str,
        *,
        worker_principal_id: str | None = None,
        publication_id: str | None = None,
        lease_generation: int | None = None,
    ) -> bool:
        try:
            return bool(
                self._authority.is_policy_current(policy_digest=policy_digest, now=now)
                and self._authority.is_runtime_current(
                    now=now,
                    worker_principal_id=worker_principal_id,
                    publication_id=publication_id,
                    lease_generation=lease_generation,
                )
            )
        except Exception:
            return False

    def _check_capacity_locked(self, now: datetime) -> None:
        active = sum(
            1
            for entry in self._entries.values()
            if entry.status
            in (DeltaPublicationStatusV1.PENDING, DeltaPublicationStatusV1.PUBLISHED)
            and now < entry.expires_at
        )
        if active >= self._policy.max_active_publications:
            raise RuntimeError("publication capacity is exhausted")

    @staticmethod
    def _intent_view(entry: _PublicationEntry) -> DeltaPublicationIntentView:
        return DeltaPublicationIntentView(
            publication_id=entry.publication_id,
            organization_id=entry.organization_id,
            site_id=entry.site_id,
            work_area_id=entry.work_area_id,
            source_contract_version=entry.source_contract_version,
            output_id=entry.output_id,
            upload_fence_id=entry.upload_fence_id,
            source_calculation_identity_digest=entry.source_calculation_identity_digest,
            source_numeric_result_identity_digest=entry.source_numeric_result_identity_digest,
            source_coverage_witness_digest=entry.source_coverage_witness_digest,
            grid_rows=entry.grid_rows,
            grid_columns=entry.grid_columns,
            issued_at=entry.issued_at,
            expires_at=entry.expires_at,
            policy_digest=entry.policy_digest,
            status=entry.status,
            lease_generation=entry.lease_generation,
            lease_holder_principal_id=entry.lease_holder_principal_id,
            lease_holder_instance_id=entry.lease_holder_instance_id,
            lease_issued_at=entry.lease_issued_at,
            lease_expires_at=entry.lease_expires_at,
        )

    @staticmethod
    def _public_view(entry: _PublicationEntry) -> DeltaPublicationView:
        assert entry.descriptor is not None
        return DeltaPublicationView(
            publication_id=entry.publication_id,
            organization_id=entry.organization_id,
            site_id=entry.site_id,
            work_area_id=entry.work_area_id,
            output_id=entry.output_id,
            issued_at=entry.issued_at,
            expires_at=entry.expires_at,
            policy_digest=entry.policy_digest,
            status=entry.status,
            descriptor=entry.descriptor.model_copy(deep=True),
            reason=entry.reason,
        )

    def _append_locked(self, raw: dict[str, object]) -> None:
        raw["eventDigest"] = _event_digest(raw)
        try:
            self._apply(raw, mutate=False)
        except DeltaPublicationRecoveryError as exc:
            raise ValueError(f"publication event is invalid: {exc}") from exc
        try:
            self._journal.append(raw)
        except JournalSealedError as exc:
            raise RuntimeError("publication journal is unavailable") from exc
        self._apply(raw)

    # -- journal replay ---------------------------------------------------------

    def _apply(self, raw: object, *, mutate: bool = True) -> None:
        try:
            if not isinstance(raw, dict) or raw.get("eventDigest") != _event_digest(raw):
                raise ValueError("publication event digest is invalid")
            if raw.get("version") != _VERSION:
                raise ValueError("publication event version is invalid")
            kind = raw.get("kind")
            if kind == _KIND_INTENT_CREATED:
                self._apply_intent_created(raw, mutate=mutate)
            elif kind == _KIND_LEASED:
                self._apply_leased(raw, mutate=mutate)
            elif kind == _KIND_PUBLISHED:
                self._apply_published(raw, mutate=mutate)
            elif kind == _KIND_REVOKED:
                self._apply_terminal(raw, mutate=mutate, status=DeltaPublicationStatusV1.REVOKED)
            elif kind == _KIND_CANCELED:
                self._apply_terminal(raw, mutate=mutate, status=DeltaPublicationStatusV1.CANCELED)
            elif kind == _KIND_FAILED:
                self._apply_terminal(raw, mutate=mutate, status=DeltaPublicationStatusV1.FAILED)
            else:
                raise ValueError("publication event kind is invalid")
        except (KeyError, TypeError, ValueError) as exc:
            raise DeltaPublicationRecoveryError(str(exc)) from exc

    def _apply_intent_created(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "organizationId",
            "publicationId",
            "siteId",
            "workAreaId",
            "sourceContractVersion",
            "sourceCalculationIdentityDigest",
            "sourceNumericResultIdentityDigest",
            "sourceCoverageWitnessDigest",
            "gridRows",
            "gridColumns",
            "transform",
            "transformDigest",
            "gridCrsIdentifier",
            "gridCrsDigest",
            "bounds",
            "outputId",
            "uploadFenceId",
            "issuedAt",
            "expiresAt",
            "policyDigest",
        }
        if set(raw) != expected:
            raise ValueError("intent event shape is invalid")
        organization_id = raw["organizationId"]
        publication_id = raw["publicationId"]
        site_id = raw["siteId"]
        work_area_id = raw["workAreaId"]
        if not isinstance(organization_id, str) or not isinstance(publication_id, str):
            raise ValueError("intent event identity is invalid")
        _require_opaque_id(publication_id, "publication")
        site_id = _require_scope_text(site_id, "site")
        work_area_id = _require_scope_text(work_area_id, "work area")
        source_contract_version = raw["sourceContractVersion"]
        if source_contract_version not in _SOURCE_CONTRACT_VERSIONS:
            raise ValueError("intent binds an unsupported source contract version")
        assert isinstance(source_contract_version, str)
        output_id = raw["outputId"]
        fence_id = raw["uploadFenceId"]
        if not isinstance(output_id, str) or not isinstance(fence_id, str):
            raise ValueError("intent fence identity is invalid")
        output_id = _require_opaque_id(output_id, "output")
        if (
            output_id != f"delta-out-{publication_id}"
            or fence_id != f"upload-fence-{publication_id}"
        ):
            raise ValueError("intent fence is not server-bound to the publication")
        _require_digest(raw["sourceCalculationIdentityDigest"], "source calculation identity")
        _require_digest(raw["sourceNumericResultIdentityDigest"], "source numeric result")
        _require_digest(raw["sourceCoverageWitnessDigest"], "source coverage witness")
        _require_digest(raw["transformDigest"], "grid transform")
        _require_digest(raw["gridCrsDigest"], "grid CRS")
        _require_digest(raw["policyDigest"], "publication policy")
        if raw["policyDigest"] != self._policy_digest:
            raise ValueError("intent binds an unknown publication policy")
        grid_rows = raw["gridRows"]
        grid_columns = raw["gridColumns"]
        if type(grid_rows) is not int or type(grid_columns) is not int:
            raise ValueError("intent grid dimensions are invalid")
        if grid_rows <= 0 or grid_columns <= 0:
            raise ValueError("intent grid dimensions are invalid")
        if grid_rows * grid_columns > self._policy.max_grid_cells:
            raise ValueError("intent grid exceeds the publication cell cap")
        transform_raw = raw["transform"]
        bounds_raw = raw["bounds"]
        if (
            not isinstance(transform_raw, list)
            or len(transform_raw) != 6
            or not all(type(item) is float for item in transform_raw)
        ):
            raise ValueError("intent transform is invalid")
        if (
            not isinstance(bounds_raw, list)
            or len(bounds_raw) != 4
            or not all(type(item) is float for item in bounds_raw)
        ):
            raise ValueError("intent bounds are invalid")
        if not isinstance(raw["gridCrsIdentifier"], str) or not raw["gridCrsIdentifier"].strip():
            raise ValueError("intent CRS identifier is invalid")
        issued_at = _parse_utc(raw["issuedAt"])
        expires_at = _parse_utc(raw["expiresAt"])
        if expires_at <= issued_at:
            raise ValueError("intent lifetime is invalid")
        lifetime = int((expires_at - issued_at).total_seconds())
        if lifetime <= 0 or lifetime > self._policy.max_lifetime_seconds:
            raise ValueError("intent lifetime exceeds the publication lifetime cap")
        key = (organization_id, publication_id)
        if key in self._entries:
            raise ValueError("duplicate publication intent")
        calc_digest = raw["sourceCalculationIdentityDigest"]
        numeric_digest = raw["sourceNumericResultIdentityDigest"]
        coverage_digest = raw["sourceCoverageWitnessDigest"]
        transform_digest_value = raw["transformDigest"]
        crs_digest_value = raw["gridCrsDigest"]
        crs_identifier = raw["gridCrsIdentifier"]
        policy_digest_value = raw["policyDigest"]
        for value in (
            calc_digest,
            numeric_digest,
            coverage_digest,
            transform_digest_value,
            crs_digest_value,
            policy_digest_value,
        ):
            if not isinstance(value, str):
                raise ValueError("intent digest fields are invalid")
        if not isinstance(crs_identifier, str):
            raise ValueError("intent CRS identifier is invalid")
        assert isinstance(calc_digest, str)
        assert isinstance(numeric_digest, str)
        assert isinstance(coverage_digest, str)
        assert isinstance(transform_digest_value, str)
        assert isinstance(crs_digest_value, str)
        assert isinstance(crs_identifier, str)
        assert isinstance(policy_digest_value, str)
        transform_tuple = (
            transform_raw[0],
            transform_raw[1],
            transform_raw[2],
            transform_raw[3],
            transform_raw[4],
            transform_raw[5],
        )
        bounds_tuple = (bounds_raw[0], bounds_raw[1], bounds_raw[2], bounds_raw[3])
        if mutate:
            self._entries[key] = _PublicationEntry(
                publication_id=publication_id,
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                source_contract_version=source_contract_version,  # type: ignore[arg-type]
                source_calculation_identity_digest=calc_digest,
                source_numeric_result_identity_digest=numeric_digest,
                source_coverage_witness_digest=coverage_digest,
                grid_rows=grid_rows,
                grid_columns=grid_columns,
                transform=transform_tuple,
                transform_digest=transform_digest_value,
                grid_crs_identifier=crs_identifier,
                grid_crs_digest=crs_digest_value,
                bounds=bounds_tuple,
                output_id=output_id,
                upload_fence_id=fence_id,
                issued_at=issued_at,
                expires_at=expires_at,
                policy_digest=policy_digest_value,
                status=DeltaPublicationStatusV1.PENDING,
                descriptor=None,
                reason="AWAITING_WORKER_UPLOAD",
            )
            self._pending[key] = None

    def _apply_leased(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "organizationId",
            "publicationId",
            "leaseGeneration",
            "holderPrincipalId",
            "holderInstanceId",
            "leaseAcquisitionId",
            "issuedAt",
            "expiresAt",
        }
        if set(raw) != expected:
            raise ValueError("leased event shape is invalid")
        organization_id = raw["organizationId"]
        publication_id = raw["publicationId"]
        if not isinstance(organization_id, str) or not isinstance(publication_id, str):
            raise ValueError("leased event identity is invalid")
        _require_opaque_id(publication_id, "publication")
        key = (organization_id, publication_id)
        entry = self._entries.get(key)
        if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
            raise ValueError("leased event has no pending intent")
        generation = raw["leaseGeneration"]
        holder_principal_id = raw["holderPrincipalId"]
        holder_instance_id = raw["holderInstanceId"]
        acquisition_id = raw["leaseAcquisitionId"]
        if type(generation) is not int or generation != entry.lease_generation + 1:
            raise ValueError("leased event generation is not the next lease")
        if generation > self._policy.max_upload_attempts:
            raise ValueError("leased event exceeds the publication attempt cap")
        for value in (holder_principal_id, holder_instance_id, acquisition_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                raise ValueError("leased event holder identity is invalid")
        assert isinstance(holder_principal_id, str)
        assert isinstance(holder_instance_id, str)
        assert isinstance(acquisition_id, str)
        if acquisition_id in entry.seen_acquisition_ids:
            raise ValueError("leased event reuses a spent acquisition id")
        issued_at = _parse_utc(raw["issuedAt"])
        expires_at = _parse_utc(raw["expiresAt"])
        if issued_at >= expires_at:
            raise ValueError("leased event window is invalid")
        expected_expires_at = min(
            issued_at + _lifetime(self._policy.upload_lease_duration_seconds),
            entry.expires_at,
        )
        if expires_at != expected_expires_at:
            raise ValueError("leased event expiry is not the policy bound truncated by the intent")
        if mutate:
            self._entries[key] = replace(
                entry,
                lease_generation=generation,
                lease_holder_principal_id=holder_principal_id,
                lease_holder_instance_id=holder_instance_id,
                lease_acquisition_id=acquisition_id,
                lease_issued_at=issued_at,
                lease_expires_at=expires_at,
                seen_acquisition_ids=entry.seen_acquisition_ids + (acquisition_id,),
                reason="AWAITING_WORKER_UPLOAD",
            )

    def _replay_observation(self, payload: object, digest: object) -> DeltaOutputObservation:
        """Revalidate the journaled acceptance; no live observation is queried.

        The persisted digest and exact binding are recomputed and crosslinked
        against the pending intent and lease.  Replay never repairs: any
        shape, digest or binding violation fails the whole journal closed.
        """
        if not isinstance(payload, dict):
            raise ValueError("published observation is invalid")
        if not isinstance(digest, str):
            raise ValueError("published observation digest is invalid")
        _require_digest(digest, "output observation")
        expected = {
            "organizationId",
            "siteId",
            "workAreaId",
            "sourceContractVersion",
            "sourceCalculationIdentityDigest",
            "sourceNumericResultIdentityDigest",
            "sourceCoverageWitnessDigest",
            "publicationId",
            "workerPrincipalId",
            "workerInstanceId",
            "leaseGeneration",
            "outputSha256",
            "outputSizeBytes",
            "gridRows",
            "gridColumns",
            "transform",
            "transformDigest",
            "gridCrsIdentifier",
            "gridCrsDigest",
            "bounds",
            "dtype",
            "deltaSign",
            "nodataValue",
        }
        if set(payload) != expected:
            raise ValueError("published observation shape is invalid")
        transform = payload["transform"]
        bounds = payload["bounds"]
        if (
            not isinstance(transform, list)
            or len(transform) != 6
            or not all(type(item) is float for item in transform)
        ):
            raise ValueError("published observation transform is invalid")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or not all(type(item) is float for item in bounds)
        ):
            raise ValueError("published observation bounds are invalid")
        for name in ("leaseGeneration", "outputSizeBytes", "gridRows", "gridColumns"):
            value = payload[name]
            if type(value) is not int or value <= 0:
                raise ValueError(f"published observation {name} is invalid")
        try:
            observation = DeltaOutputObservation(
                organization_id=payload["organizationId"],
                site_id=payload["siteId"],
                work_area_id=payload["workAreaId"],
                source_contract_version=payload["sourceContractVersion"],
                source_calculation_identity_digest=payload["sourceCalculationIdentityDigest"],
                source_numeric_result_identity_digest=payload["sourceNumericResultIdentityDigest"],
                source_coverage_witness_digest=payload["sourceCoverageWitnessDigest"],
                publication_id=payload["publicationId"],
                worker_principal_id=payload["workerPrincipalId"],
                worker_instance_id=payload["workerInstanceId"],
                lease_generation=payload["leaseGeneration"],
                output_sha256=payload["outputSha256"],
                output_size_bytes=payload["outputSizeBytes"],
                grid_rows=payload["gridRows"],
                grid_columns=payload["gridColumns"],
                transform=(
                    transform[0],
                    transform[1],
                    transform[2],
                    transform[3],
                    transform[4],
                    transform[5],
                ),
                transform_digest=payload["transformDigest"],
                grid_crs_identifier=payload["gridCrsIdentifier"],
                grid_crs_digest=payload["gridCrsDigest"],
                bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
                dtype=payload["dtype"],
                delta_sign=payload["deltaSign"],
                nodata_value=payload["nodataValue"],
                observation_digest=digest,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"published observation is not sealed: {exc}") from exc
        if observation.canonical_digest() != digest:
            raise ValueError("published observation digest differs from its exact binding")
        return observation

    def _apply_published(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "organizationId",
            "publicationId",
            "leaseGeneration",
            "holderPrincipalId",
            "holderInstanceId",
            "observationDigest",
            "observation",
            "descriptor",
        }
        if set(raw) != expected:
            raise ValueError("published event shape is invalid")
        organization_id = raw["organizationId"]
        publication_id = raw["publicationId"]
        if not isinstance(organization_id, str) or not isinstance(publication_id, str):
            raise ValueError("published event identity is invalid")
        _require_opaque_id(publication_id, "publication")
        key = (organization_id, publication_id)
        entry = self._entries.get(key)
        if entry is None or entry.status is not DeltaPublicationStatusV1.PENDING:
            raise ValueError("published event has no pending intent")
        generation = raw["leaseGeneration"]
        holder_principal_id = raw["holderPrincipalId"]
        holder_instance_id = raw["holderInstanceId"]
        if type(generation) is not int or generation != entry.lease_generation:
            raise ValueError("published event generation does not match the live lease")
        if (
            holder_principal_id != entry.lease_holder_principal_id
            or holder_instance_id != entry.lease_holder_instance_id
        ):
            raise ValueError("published event holder does not match the live lease")
        observation = self._replay_observation(raw["observation"], raw["observationDigest"])
        if not self._observation_matches_entry(
            observation,
            entry,
            worker_principal_id=entry.lease_holder_principal_id or "",
            worker_instance_id=entry.lease_holder_instance_id or "",
            lease_generation=entry.lease_generation,
        ):
            raise ValueError("published observation does not bind the intent and lease")
        if not isinstance(raw["descriptor"], dict):
            raise ValueError("published descriptor is invalid")
        try:
            descriptor = DeltaRasterPublicationV1.model_validate(raw["descriptor"])
        except Exception as exc:
            raise ValueError(f"published descriptor is unsealed: {exc}") from exc
        if descriptor.publication_digest is None or (
            descriptor.publication_digest != descriptor.canonical_digest()
        ):
            raise ValueError("published descriptor is unsealed")
        if (
            descriptor.publication_id != publication_id
            or descriptor.organization_id != organization_id
            or descriptor.site_id != entry.site_id
            or descriptor.work_area_id != entry.work_area_id
            or descriptor.source_contract_version != entry.source_contract_version
            or descriptor.source_calculation_identity_digest
            != entry.source_calculation_identity_digest
            or descriptor.source_numeric_result_identity_digest
            != entry.source_numeric_result_identity_digest
            or descriptor.source_coverage_witness_digest != entry.source_coverage_witness_digest
            or descriptor.delta_sign != "CURRENT_MINUS_BASELINE"
            or descriptor.dtype != "FLOAT64"
            or descriptor.grid_rows != entry.grid_rows
            or descriptor.grid_columns != entry.grid_columns
            or descriptor.transform != entry.transform
            or descriptor.transform_digest != entry.transform_digest
            or descriptor.grid_crs_identifier != entry.grid_crs_identifier
            or descriptor.grid_crs_digest != entry.grid_crs_digest
            or descriptor.bounds != entry.bounds
            or descriptor.output_id != entry.output_id
            or descriptor.issued_at != entry.issued_at
            or descriptor.expires_at != entry.expires_at
            or descriptor.publication_policy_digest != entry.policy_digest
            or descriptor.vertical_unit != "metre"
        ):
            raise ValueError("published descriptor does not bind the intent")
        if (
            descriptor.output_size_bytes <= 0
            or descriptor.output_size_bytes > self._policy.max_output_bytes
        ):
            raise ValueError("published output size exceeds the publication byte cap")
        _require_digest(descriptor.output_sha256, "output")
        if (
            descriptor.output_sha256 != observation.output_sha256
            or descriptor.output_size_bytes != observation.output_size_bytes
            or descriptor.source_contract_version != observation.source_contract_version
            or descriptor.grid_rows != observation.grid_rows
            or descriptor.grid_columns != observation.grid_columns
            or descriptor.transform != observation.transform
        ):
            raise ValueError("published descriptor does not bind the accepted observation")
        if mutate:
            self._entries[key] = replace(
                entry,
                status=DeltaPublicationStatusV1.PUBLISHED,
                descriptor=descriptor,
                reason="PUBLISHED",
            )
            self._pending.pop(key, None)

    def _apply_terminal(
        self, raw: dict[str, object], *, mutate: bool, status: DeltaPublicationStatusV1
    ) -> None:
        if status is DeltaPublicationStatusV1.REVOKED:
            expected = {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "publicationId",
                "reason",
                "revokedAt",
            }
            at_field = "revokedAt"
            required_from = DeltaPublicationStatusV1.PUBLISHED
        elif status is DeltaPublicationStatusV1.CANCELED:
            expected = {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "publicationId",
                "reason",
                "canceledAt",
            }
            at_field = "canceledAt"
            required_from = DeltaPublicationStatusV1.PENDING
        else:
            expected = {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "publicationId",
                "leaseGeneration",
                "holderPrincipalId",
                "holderInstanceId",
                "reason",
                "failedAt",
            }
            at_field = "failedAt"
            required_from = DeltaPublicationStatusV1.PENDING
        if set(raw) != expected:
            raise ValueError("terminal event shape is invalid")
        organization_id = raw["organizationId"]
        publication_id = raw["publicationId"]
        if not isinstance(organization_id, str) or not isinstance(publication_id, str):
            raise ValueError("terminal event identity is invalid")
        _require_opaque_id(publication_id, "publication")
        key = (organization_id, publication_id)
        entry = self._entries.get(key)
        if entry is None or entry.status is not required_from:
            raise ValueError("terminal event has no matching live record")
        if status is DeltaPublicationStatusV1.FAILED and (
            raw["leaseGeneration"] != entry.lease_generation
            or raw["holderPrincipalId"] != entry.lease_holder_principal_id
            or raw["holderInstanceId"] != entry.lease_holder_instance_id
        ):
            raise ValueError("failure event lease does not match the live lease")
        if (
            not isinstance(raw["reason"], str)
            or not raw["reason"].strip()
            or len(raw["reason"]) > 255
        ):
            raise ValueError("terminal event reason is invalid")
        reason_text = raw["reason"]
        assert isinstance(reason_text, str)
        _parse_utc(raw[at_field])
        if mutate:
            if status is DeltaPublicationStatusV1.REVOKED:
                assert entry.descriptor is not None
            updated = replace(entry, status=status, reason=reason_text)
            self._entries[key] = updated
            self._pending.pop(key, None)


def _lifetime(seconds: int) -> timedelta:
    return timedelta(seconds=seconds)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("event time is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("event time must be UTC")
    return parsed


__all__ = [
    "DeltaByteStorePort",
    "DeltaEgressPort",
    "DeltaOutputObservation",
    "DeltaOutputObservationPort",
    "DeltaPublicationAuthorityPort",
    "DeltaPublicationDispositionV1",
    "DeltaPublicationIntentView",
    "DeltaPublicationPolicy",
    "DeltaPublicationRecoveryError",
    "DeltaPublicationStatusV1",
    "DeltaPublicationView",
    "DeltaSourceWitness",
    "DeltaSourceWitnessPort",
    "ExternalDeltaPublicationStore",
    "FilesystemDeltaByteStore",
]
