"""Protected filesystem byte store for mask-child uploads (P2, additive).

Actual server-side behavior, not a delegation stub.  The client never
supplies a filesystem path: Core mints a server object key from the
organization/site/child/artifact identity, stages the upload under an
unlinked grant id, verifies declared SHA-256/size, then atomically promotes
the bytes to the sealed object key with fsync.  All reads resolve the server
key internally through descriptor-relative ``O_NOFOLLOW`` traversal and
re-hash SHA/size under the trusted coordinator guard.  Raw client paths,
``..``, absolute paths, URLs, and capabilities are rejected by shape.

Immutability discipline: one object key binds exactly one subject plus one
declared byte identity at grant issuance.  Completing the same bytes again
is idempotent and appends nothing; completing different bytes under a sealed
key fails closed without touching the sealed object.  Promotion and the
final journal bind happen under the shared coordinator mutation so a
concurrent ingress seal can never observe half-sealed bytes.

Journal: grant issuance and byte sealing are appended to the store's own
durable journal with canonical event digests, exact closed shapes, strict
types, and resource caps.  Restart replays the exact sealed set; tamper,
unknown-grant seals, conflicting bindings, and version spoofing fail closed.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

from ksi_core.domains.external.ingress.external_mask_input_bytes_io import (
    check_safe_component,
    hash_fd,
    mkdirs_below,
    open_dirs_below,
    open_for_create,
    open_for_read,
    pin_owner_private_root,
    write_all,
)
from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_GRANTED = "external-mask-input-grant-issued.v1"
_EVENT_SEALED = "external-mask-input-bytes-sealed.v1"
_GRANTED_FIELDS = frozenset(
    {
        "kind",
        "version",
        "eventDigest",
        "grantId",
        "organizationId",
        "siteId",
        "workAreaId",
        "maskChildId",
        "maskArtifactId",
        "subjectDigest",
        "objectKey",
        "declaredSha256",
        "declaredSizeBytes",
        "issuedAt",
        "expiresAt",
    }
)
_SEALED_FIELDS = frozenset(
    {
        "kind",
        "version",
        "eventDigest",
        "grantId",
        "organizationId",
        "siteId",
        "maskChildId",
        "maskArtifactId",
        "objectKey",
        "observedSha256",
        "observedSizeBytes",
        "sealedAt",
    }
)


class MaskByteStoreRecoveryError(RuntimeError):
    """The mask byte-store journal cannot be replayed safely."""


@dataclass(frozen=True, slots=True)
class MaskInputUploadGrant:
    grant_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    mask_child_id: str
    mask_artifact_id: str
    subject_digest: str
    object_key: str
    declared_sha256: str
    declared_size_bytes: int
    expires_at: datetime


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


def _object_key(
    *, organization_id: str, site_id: str, mask_child_id: str, mask_artifact_id: str
) -> str:
    for label, value in (
        ("organization", organization_id),
        ("site", site_id),
        ("mask child", mask_child_id),
        ("mask artifact", mask_artifact_id),
    ):
        check_safe_component(value, label)
    return f"mask/{organization_id}/{site_id}/{mask_child_id}/{mask_artifact_id}.tif"


def _key_parts(object_key: str) -> tuple[tuple[str, ...], str]:
    parts = object_key.split("/")
    if len(parts) != 5 or parts[0] != "mask" or not parts[4].endswith(".tif"):
        raise ValueError("object key is outside the mask namespace")
    return tuple(parts[1:4]), parts[4]


def _parse_utc(value: object, description: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{description} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{description} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{description} must be UTC")
    return parsed


def _journal_text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise MaskByteStoreRecoveryError(f"mask byte journal {description} is malformed")
    return value


def _journal_id(value: object, description: str) -> str:
    text = _journal_text(value, description + " id")
    if len(text) > 128:
        raise MaskByteStoreRecoveryError(f"mask byte journal {description} id is malformed")
    lowered = text.lower()
    if (
        "://" in text
        or text.startswith(("/", "\\"))
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise MaskByteStoreRecoveryError(f"mask byte journal {description} id is not opaque")
    return text


def _journal_digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise MaskByteStoreRecoveryError(f"mask byte journal {description} digest is invalid")
    return value


def _journal_size(value: object, cap: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise MaskByteStoreRecoveryError("mask byte journal size is malformed")
    if value <= 0 or value > cap:
        raise MaskByteStoreRecoveryError("mask byte journal size exceeds the finite cap")
    return value


class ExternalMaskInputByteStore:
    """Server-keyed protected bytes for mask-child uploads."""

    def __init__(
        self,
        journal: DurableJournal,
        root: Path,
        *,
        resource_envelope: ResourceEnvelopeV1,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("mask byte store requires a sealed resource envelope")
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("mask byte store requires an absolute root path")
        try:
            os.mkdir(root, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            journal.close()
            raise ValueError("mask byte store root is unavailable") from exc
        self._journal = journal
        self._root = root
        self._envelope = resource_envelope.model_copy(deep=True)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._lock = threading.RLock()
        self._grants: dict[str, MaskInputUploadGrant] = {}
        self._sealed: dict[str, tuple[str, int]] = {}
        try:
            self._root_fd = pin_owner_private_root(root)
        except BaseException as exc:
            journal.close()
            raise exc
        self._closed = False
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            self._close_root_fd()
            journal.close()
            if isinstance(exc, MaskByteStoreRecoveryError):
                raise
            raise MaskByteStoreRecoveryError(str(exc)) from exc

    def close(self) -> None:
        """Release the pinned root descriptor; idempotent for graph lifecycle.

        After close, every byte operation fails closed.  The journal keeps its
        own lifecycle with its owner.
        """
        with self._lock:
            self._closed = True
            self._close_root_fd()

    def _close_root_fd(self) -> None:
        descriptor, self._root_fd = getattr(self, "_root_fd", -1), -1
        if isinstance(descriptor, int) and descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def root(self) -> Path:
        return self._root

    def _byte_cap(self) -> int:
        return min(self._envelope.max_input_bytes, self._envelope.max_streamed_bytes)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("mask byte clock must be UTC-aware")
        return now

    def _require_open(self) -> int:
        descriptor = getattr(self, "_root_fd", -1)
        if self._closed or not isinstance(descriptor, int) or descriptor < 0:
            raise ValueError("mask byte store is closed")
        return descriptor

    def issue_grant(
        self,
        *,
        principal: Principal,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
        subject_digest: str,
        declared_sha256: str,
        declared_size_bytes: int,
        now: datetime,
        ttl_seconds: int = 3600,
    ) -> MaskInputUploadGrant:
        self._require_site_write(principal)
        self._require_utc(now)
        self._require_scope(principal, organization_id, site_id, work_area_id)
        self._require_open()
        self._require_digest(subject_digest, "subject")
        self._require_digest(declared_sha256, "declared bytes")
        if (
            not isinstance(declared_size_bytes, int)
            or isinstance(declared_size_bytes, bool)
            or declared_size_bytes <= 0
            or declared_size_bytes > self._byte_cap()
        ):
            raise ValueError("declared bytes exceed the finite byte cap")
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds <= 0
            or ttl_seconds > 24 * 3600
        ):
            raise ValueError("grant TTL is out of bounds")
        object_key = _object_key(
            organization_id=organization_id,
            site_id=site_id,
            mask_child_id=mask_child_id,
            mask_artifact_id=mask_artifact_id,
        )
        with self._coordinator.mutation(), self._lock:
            for existing in self._grants.values():
                if existing.object_key != object_key:
                    continue
                if (
                    existing.subject_digest != subject_digest
                    or existing.declared_sha256 != declared_sha256
                    or existing.declared_size_bytes != declared_size_bytes
                ):
                    raise ValueError("object key is already bound to other bytes")
            sealed = self._sealed.get(object_key)
            if sealed is not None and sealed != (declared_sha256, declared_size_bytes):
                raise ValueError("object key is already sealed to other bytes")
            grant = MaskInputUploadGrant(
                grant_id=str(uuid.uuid4()),
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                mask_child_id=mask_child_id,
                mask_artifact_id=mask_artifact_id,
                subject_digest=subject_digest,
                object_key=object_key,
                declared_sha256=declared_sha256,
                declared_size_bytes=declared_size_bytes,
                expires_at=self._now() + timedelta(seconds=ttl_seconds),
            )
            raw: dict[str, object] = {
                "kind": _EVENT_GRANTED,
                "version": _VERSION,
                "grantId": grant.grant_id,
                "organizationId": organization_id,
                "siteId": site_id,
                "workAreaId": work_area_id,
                "maskChildId": mask_child_id,
                "maskArtifactId": mask_artifact_id,
                "subjectDigest": subject_digest,
                "objectKey": object_key,
                "declaredSha256": declared_sha256,
                "declaredSizeBytes": declared_size_bytes,
                "issuedAt": iso_utc(now),
                "expiresAt": iso_utc(grant.expires_at),
            }
            self._append_locked(raw)
            return self._grants[grant.grant_id]

    def complete_upload(
        self, *, grant_id: str, data: bytes, principal: Principal, now: datetime
    ) -> tuple[str, int]:
        """Seal one granted upload; idempotent for identical bytes, never replacing."""
        self._require_site_write(principal)
        self._require_utc(now)
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise ValueError("uploaded bytes must be a non-empty byte string")
        payload = bytes(data)
        if len(payload) > self._byte_cap():
            raise ValueError("uploaded bytes exceed the finite byte cap")
        with self._coordinator.mutation(), self._lock:
            root_fd = self._require_open()
            grant = self._grants.get(grant_id)
            if grant is None:
                raise ValueError("upload grant is unknown")
            self._require_scope(principal, grant.organization_id, grant.site_id, grant.work_area_id)
            if self._now() >= grant.expires_at:
                raise ValueError("upload grant has expired")
            if len(payload) != grant.declared_size_bytes:
                raise ValueError("uploaded bytes do not match the declared size")
            actual_sha = "sha256:" + hashlib.sha256(payload).hexdigest()
            if actual_sha != grant.declared_sha256:
                raise ValueError("uploaded bytes do not match the declared SHA-256")
            sealed = self._sealed.get(grant.object_key)
            if sealed is not None:
                if sealed != (actual_sha, len(payload)):
                    raise ValueError("object key is already sealed to other bytes")
                return sealed
            directory_parts, file_name = _key_parts(grant.object_key)
            try:
                leaf_fd = mkdirs_below(root_fd, directory_parts)
                try:
                    staging_name = file_name + f".staging-{grant.grant_id}"
                    try:
                        staging_fd = open_for_create(leaf_fd, staging_name)
                    except FileExistsError:
                        # A crashed attempt left its own staging file behind:
                        # unlink this grant's namespace only, then recreate.
                        try:
                            os.unlink(staging_name, dir_fd=leaf_fd)
                        except OSError as exc:
                            raise ValueError("mask staging object is unavailable") from exc
                        staging_fd = open_for_create(leaf_fd, staging_name)
                    try:
                        write_all(
                            staging_fd,
                            payload,
                            maximum=self._envelope.max_streamed_bytes,
                        )
                    finally:
                        os.close(staging_fd)
                    try:
                        os.rename(staging_name, file_name, src_dir_fd=leaf_fd, dst_dir_fd=leaf_fd)
                    except OSError as exc:
                        raise ValueError("mask byte promotion failed") from exc
                    try:
                        os.fsync(leaf_fd)
                    except OSError as exc:
                        raise ValueError("mask byte directory fsync failed") from exc
                finally:
                    os.close(leaf_fd)
            except ValueError:
                raise
            except FileExistsError as exc:
                raise ValueError("mask staging object already exists") from exc
            raw: dict[str, object] = {
                "kind": _EVENT_SEALED,
                "version": _VERSION,
                "grantId": grant_id,
                "organizationId": grant.organization_id,
                "siteId": grant.site_id,
                "maskChildId": grant.mask_child_id,
                "maskArtifactId": grant.mask_artifact_id,
                "objectKey": grant.object_key,
                "observedSha256": actual_sha,
                "observedSizeBytes": len(payload),
                "sealedAt": iso_utc(self._now()),
            }
            self._append_locked(raw)
            return self._sealed[grant.object_key]

    def fetch_proof(
        self,
        *,
        organization_id: str,
        site_id: str,
        subject_digest: str,
        mask_child_id: str,
        mask_artifact_id: str,
    ) -> tuple[str, int]:
        """Scoped sealed-byte proof; resolves the server key internally, never a client path."""
        if _DIGEST_RE.fullmatch(subject_digest) is None:
            raise ValueError("subject digest is invalid")
        object_key = _object_key(
            organization_id=organization_id,
            site_id=site_id,
            mask_child_id=mask_child_id,
            mask_artifact_id=mask_artifact_id,
        )
        with self._coordinator.guarded_read(), self._lock:
            root_fd = self._require_open()
            sealed = self._sealed.get(object_key)
            if sealed is None:
                raise ValueError("mask bytes are not sealed")
            for grant in self._grants.values():
                if grant.object_key == object_key and grant.subject_digest != subject_digest:
                    raise ValueError("mask bytes do not bind the subject")
            directory_parts, file_name = _key_parts(object_key)
            leaf_fd = open_dirs_below(root_fd, directory_parts)
            try:
                descriptor = open_for_read(leaf_fd, file_name)
                try:
                    actual = hash_fd(descriptor, maximum=self._envelope.max_streamed_bytes)
                finally:
                    os.close(descriptor)
            finally:
                os.close(leaf_fd)
            if actual != sealed:
                raise ValueError("mask object bytes do not match the sealed proof")
            return actual

    def read_slice(
        self,
        *,
        organization_id: str,
        site_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
        subject_digest: str,
        offset: int,
        length: int,
    ) -> bytes:
        """Trusted bounded window read from the sealed object, same-fd verified.

        Resolves the server key internally (never a caller path), re-verifies
        the full sealed byte identity from the SAME open descriptor inside the
        trusted coordinator guard (pre-read fstat size plus full post-open
        hash against the journaled seal), then returns only the requested
        window read from that same descriptor.  HTTP layers must use this,
        never a separately re-opened path.
        """
        if _DIGEST_RE.fullmatch(subject_digest) is None:
            raise ValueError("subject digest is invalid")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not isinstance(length, int)
            or isinstance(length, bool)
        ):
            raise ValueError("mask byte window bounds must be integers")
        if offset < 0 or length <= 0 or length > self._byte_cap():
            raise ValueError("mask byte window is out of range")
        object_key = _object_key(
            organization_id=organization_id,
            site_id=site_id,
            mask_child_id=mask_child_id,
            mask_artifact_id=mask_artifact_id,
        )
        with self._coordinator.guarded_read(), self._lock:
            root_fd = self._require_open()
            sealed = self._sealed.get(object_key)
            if sealed is None:
                raise ValueError("mask bytes are not sealed")
            for grant in self._grants.values():
                if grant.object_key == object_key and grant.subject_digest != subject_digest:
                    raise ValueError("mask bytes do not bind the subject")
            if offset + length > sealed[1]:
                raise ValueError("mask byte window exceeds the sealed size")
            directory_parts, file_name = _key_parts(object_key)
            leaf_fd = open_dirs_below(root_fd, directory_parts)
            try:
                descriptor = open_for_read(leaf_fd, file_name)
                try:
                    try:
                        file_stat = os.fstat(descriptor)
                    except OSError as exc:
                        raise ValueError("mask sealed object is unavailable") from exc
                    if file_stat.st_size != sealed[1]:
                        raise ValueError("mask object size does not match the sealed proof")
                    actual_sha, actual_size = hash_fd(
                        descriptor, maximum=self._envelope.max_streamed_bytes
                    )
                    if (actual_sha, actual_size) != sealed:
                        raise ValueError("mask object bytes do not match the sealed proof")
                    window = bytearray()
                    position = offset
                    remaining = length
                    while remaining > 0:
                        try:
                            chunk = os.pread(descriptor, min(262144, remaining), position)
                        except OSError as exc:
                            raise ValueError("mask byte window read failed") from exc
                        if not chunk:
                            raise ValueError("mask sealed object ended before its proof")
                        window.extend(chunk)
                        position += len(chunk)
                        remaining -= len(chunk)
                finally:
                    os.close(descriptor)
            finally:
                os.close(leaf_fd)
            return bytes(window)

    def sealed_object_path(
        self,
        *,
        organization_id: str,
        site_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
    ) -> Path:
        """Internal/test helper: resolve the sealed server object to a local path.

        This grants NO read guarantee: a separately opened path is not the
        verified descriptor, so HTTP layers must use :meth:`read_slice`
        instead.  Kept for contained test dispatch only.
        """
        self._require_open()
        object_key = _object_key(
            organization_id=organization_id,
            site_id=site_id,
            mask_child_id=mask_child_id,
            mask_artifact_id=mask_artifact_id,
        )
        with self._lock:
            if object_key not in self._sealed:
                raise ValueError("mask bytes are not sealed")
        directory_parts, file_name = _key_parts(object_key)
        return self._root.joinpath(*directory_parts, file_name)

    def _append_locked(self, raw: dict[str, object]) -> None:
        record = dict(raw)
        record["eventDigest"] = _event_digest(record)
        try:
            self._journal.append(record)
        except JournalSealedError:
            raise
        except BaseException as exc:
            raise MaskByteStoreRecoveryError(str(exc)) from exc
        self._apply(record)

    def _apply(self, raw: Mapping[str, object]) -> None:
        kind = raw.get("kind")
        if not isinstance(kind, str):
            raise MaskByteStoreRecoveryError("mask byte journal kind is malformed")
        if type(raw.get("version")) is not int or raw.get("version") != _VERSION:
            raise MaskByteStoreRecoveryError("mask byte journal version is unsupported")
        expected_fields = (
            _GRANTED_FIELDS
            if kind == _EVENT_GRANTED
            else _SEALED_FIELDS
            if kind == _EVENT_SEALED
            else set()
        )
        if not expected_fields or set(raw.keys()) != expected_fields:
            raise MaskByteStoreRecoveryError("mask byte journal fields are not exact")
        digest = raw.get("eventDigest")
        if not isinstance(digest, str) or digest != _event_digest(raw):
            raise MaskByteStoreRecoveryError("mask byte journal digest is invalid")
        cap = self._byte_cap()
        if kind == _EVENT_GRANTED:
            grant = MaskInputUploadGrant(
                grant_id=_journal_id(raw["grantId"], "grant"),
                organization_id=_journal_text(raw["organizationId"], "organization"),
                site_id=_journal_text(raw["siteId"], "site"),
                work_area_id=_journal_text(raw["workAreaId"], "work area"),
                mask_child_id=_journal_text(raw["maskChildId"], "mask child"),
                mask_artifact_id=_journal_text(raw["maskArtifactId"], "mask artifact"),
                subject_digest=_journal_digest(raw["subjectDigest"], "subject"),
                object_key=self._journal_key(raw),
                declared_sha256=_journal_digest(raw["declaredSha256"], "declared bytes"),
                declared_size_bytes=_journal_size(raw["declaredSizeBytes"], cap),
                expires_at=_parse_utc(raw["expiresAt"], "grant expiry"),
            )
            _parse_utc(raw["issuedAt"], "grant issuance")
            bound = self._grants.get(grant.grant_id)
            if bound is not None:
                if bound != grant:
                    raise MaskByteStoreRecoveryError("mask grant journal conflicts")
                return
            for other in self._grants.values():
                if other.object_key == grant.object_key and (
                    other.subject_digest != grant.subject_digest
                    or other.declared_sha256 != grant.declared_sha256
                    or other.declared_size_bytes != grant.declared_size_bytes
                ):
                    raise MaskByteStoreRecoveryError("mask grant journal binds another key")
            sealed = self._sealed.get(grant.object_key)
            if sealed is not None and sealed != (
                grant.declared_sha256,
                grant.declared_size_bytes,
            ):
                raise MaskByteStoreRecoveryError("mask grant journal conflicts with sealed bytes")
            self._grants[grant.grant_id] = grant
        elif kind == _EVENT_SEALED:
            grant_id = _journal_id(raw["grantId"], "grant")
            seal_grant = self._grants.get(grant_id)
            if seal_grant is None:
                raise MaskByteStoreRecoveryError("mask seal journal references an unknown grant")
            object_key = self._journal_key(raw)
            observed = (
                _journal_digest(raw["observedSha256"], "observed bytes"),
                _journal_size(raw["observedSizeBytes"], cap),
            )
            sealed_at = _parse_utc(raw["sealedAt"], "seal time")
            if (
                object_key != seal_grant.object_key
                or str(raw["organizationId"]) != seal_grant.organization_id
                or str(raw["siteId"]) != seal_grant.site_id
                or str(raw["maskChildId"]) != seal_grant.mask_child_id
                or str(raw["maskArtifactId"]) != seal_grant.mask_artifact_id
            ):
                raise MaskByteStoreRecoveryError("mask seal journal escapes its grant")
            if observed != (seal_grant.declared_sha256, seal_grant.declared_size_bytes):
                raise MaskByteStoreRecoveryError("mask seal journal diverges from its grant")
            if sealed_at >= seal_grant.expires_at:
                raise MaskByteStoreRecoveryError("mask seal journal postdates its grant")
            sealed_before = self._sealed.get(object_key)
            if sealed_before is not None:
                if sealed_before != observed:
                    raise MaskByteStoreRecoveryError("mask byte journal conflicts")
                return
            self._sealed[object_key] = observed
        else:
            raise MaskByteStoreRecoveryError(f"unknown mask byte journal kind: {kind!r}")

    def _journal_key(self, raw: Mapping[str, object]) -> str:
        value = raw.get("objectKey")
        if not isinstance(value, str):
            raise MaskByteStoreRecoveryError("mask byte journal object key is malformed")
        expected = _object_key(
            organization_id=str(raw["organizationId"]),
            site_id=str(raw["siteId"]),
            mask_child_id=str(raw["maskChildId"]),
            mask_artifact_id=str(raw["maskArtifactId"]),
        )
        if value != expected:
            raise MaskByteStoreRecoveryError("mask byte journal object key escapes its scope")
        return value

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("mask byte time must be UTC")

    @staticmethod
    def _require_digest(value: str, description: str) -> None:
        if _DIGEST_RE.fullmatch(value) is None:
            raise ValueError(f"{description} digest is invalid")

    @staticmethod
    def _require_site_write(principal: Principal) -> None:
        granted = principal_permissions(principal)
        allowed = (
            Permission.ANALYSIS_API_CREATE in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_WRITE in granted
        )
        if not allowed:
            raise PermissionError("mask byte grant requires SITES_WRITE")

    @classmethod
    def _require_scope(
        cls, principal: Principal, organization_id: str, site_id: str, work_area_id: str
    ) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            if principal.organization_id != organization_id:
                raise PermissionError("mask bytes are outside caller scope")
            if principal.allowed_site_ids is not None and site_id not in (
                principal.allowed_site_ids
            ):
                raise PermissionError("mask bytes are outside caller scope")
            if principal.allowed_work_area_ids is not None and work_area_id not in (
                principal.allowed_work_area_ids
            ):
                raise PermissionError("mask bytes are outside caller scope")
            return
        if (
            principal.organization_id != organization_id
            or principal.allowed_site_ids is None
            or site_id not in principal.allowed_site_ids
            or principal.allowed_work_area_ids is None
            or work_area_id not in principal.allowed_work_area_ids
        ):
            raise PermissionError("mask bytes are outside client scope")


__all__ = [
    "ExternalMaskInputByteStore",
    "MaskByteStoreRecoveryError",
    "MaskInputUploadGrant",
]
