"""Durable human ingress for separately stored customer evidence.

This deliberately has no validation queue, measurement, or managed-artifact path.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    EvidenceIndependence,
    ExternalEvidenceDeclarationV1,
    ExternalEvidenceManifestV1,
    ExternalEvidenceRecordV1,
    external_evidence_declaration_wire_dict,
    external_evidence_manifest_wire_dict,
)
from pydantic import Field, field_validator

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_UPLOAD_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorageError,
    ObjectStorageObservationPort,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.domains.sites.observation_work_orders import ObservationWorkOrderStore
from ksi_core.foundation.api_base import CamelModel, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

_VERSION = 1
_NOT_FOUND = "EXTERNAL_EVIDENCE_NOT_FOUND"
_OBJECT_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, Any]) -> str:
    value = dict(raw)
    value.pop("eventDigest", None)
    return _digest(value)


def _external_digest(observed_sha256: str) -> str:
    """Bridge a sealed reconstruction's hex SHA-256 into contract Digest form."""
    return f"sha256:{observed_sha256}"


def _require_safe_object_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1_024
        or value.startswith("/")
        or "//" in value
        or any(segment in {".", ".."} for segment in value.split("/"))
        or not all(_OBJECT_KEY_SEGMENT.fullmatch(segment) for segment in value.split("/"))
    ):
        raise ValueError("invalid server object key")
    return value


class ExternalEvidenceRecoveryError(RuntimeError):
    """Raised when an evidence journal cannot be safely projected."""


class EvidenceState(StrEnum):
    DECLARED = "DECLARED"
    SEALED_BYTE_OBSERVED = "SEALED_BYTE_OBSERVED"


class EvidenceVerdict(StrEnum):
    DECLARED = "DECLARED"
    SEALED = "SEALED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
    EXPIRED = "IDEMPOTENT_GRANT_EXPIRED"
    NOT_SEALED = "NOT_SEALED"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class _Grant:
    expires_at: datetime


@dataclass(slots=True)
class _PendingBinding:
    fingerprint: str
    evidence_ref: str
    completed: threading.Event


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    evidence_ref: str
    work_order_id: str
    submission_id: str
    revision: int
    declaration: ExternalEvidenceDeclarationV1
    object_key: str
    manifest: ExternalEvidenceManifestV1 | None = None
    grants: tuple[tuple[str, _Grant], ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    verdict: EvidenceVerdict
    item: EvidenceItem | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None
    required_headers: dict[str, str] | None = None


class ExternalEvidenceDeclarationIntent(CamelModel):
    target_dsm_artifact_id: str = Field(min_length=1, max_length=255)
    declared_content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    declared_content_type: str = Field(min_length=1, max_length=255)
    independence_basis: str = Field(min_length=1, max_length=1_000)

    @field_validator("declared_content_type", "independence_basis", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ExternalEvidenceView(CamelModel):
    evidence_ref: str
    state: EvidenceState
    target_dsm_artifact_id: str
    target_dsm_observed_sha256: str
    declared_content_digest: str
    declared_content_type: str
    independence_basis: str
    declared_at: datetime
    observed_object_digest: str | None = None
    observed_size_bytes: int | None = None
    observed_content_type: str | None = None
    observed_at: datetime | None = None
    measurement_summaries: list[ExternalEvidenceMeasurementSummaryView] | None = None


class ExternalEvidenceMeasurementSummaryView(CamelModel):
    """Occurred aggregate only; raw checkpoint facts remain worker-private."""

    core_verdict: EvidenceCoreVerdict
    measured_checkpoint_count: int
    mean_error_m: float
    mae_m: float
    rmse_m: float
    recorded_at: datetime


class ExternalEvidenceTerminalRecordProjectionPort(Protocol):
    def terminal_records_for_evidence(
        self, evidence_ref: str
    ) -> tuple[ExternalEvidenceRecordV1, ...]: ...


class ExternalEvidenceListResponse(CamelModel):
    items: list[ExternalEvidenceView]


class ExternalEvidenceUploadGrantResponse(CamelModel):
    evidence_ref: str
    upload_url: str
    expires_at: datetime
    required_headers: dict[str, str]


class ExternalEvidenceStore:
    """Append-only evidence ledger with durable idempotency bindings."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._items: dict[str, EvidenceItem] = {}
        self._natural: dict[str, str] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._pending: dict[str, _PendingBinding] = {}
        self._seal_listeners: list[Callable[[EvidenceItem, datetime], object]] = []
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            raise ExternalEvidenceRecoveryError(f"external evidence replay failed: {exc}") from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def bind_seal_listener(self, listener: Callable[[EvidenceItem, datetime], object]) -> None:
        """Bind additive post-commit validation issuance without ingress authority."""
        with self._lock:
            self._seal_listeners.append(listener)

    def sealed_items_snapshot(self) -> tuple[EvidenceItem, ...]:
        """Return retained seals for restart reconciliation only."""
        with self._lock:
            return tuple(item for item in self._items.values() if item.manifest is not None)

    def _apply(self, raw: dict[str, Any]) -> None:
        if not isinstance(raw, dict) or raw.get("eventDigest") != _event_digest(raw):
            raise ValueError("invalid event digest")
        if type(raw.get("version")) is not int or raw["version"] != _VERSION:
            raise ValueError("unknown event version")
        if not isinstance(raw.get("kind"), str):
            raise ValueError("unknown event")
        kind = raw["kind"]
        if kind == "external-evidence-declared":
            required = {
                "kind",
                "version",
                "eventDigest",
                "evidenceRef",
                "objectKey",
                "natural",
                "idempotency",
                "declaration",
            }
            if set(raw) != required:
                raise ValueError("invalid declaration event")
            declaration = ExternalEvidenceDeclarationV1.model_validate(raw["declaration"])
            if declaration.declaration_digest is None or not isinstance(raw["evidenceRef"], str):
                raise ValueError("unsealed declaration")
            if not isinstance(raw["natural"], str):
                raise ValueError("invalid natural identity")
            expected_natural, expected_id, expected_ref, expected_key = (
                self._derived_declaration_ids(declaration)
            )
            if (
                raw["natural"] != expected_natural
                or declaration.evidence_id != expected_id
                or raw["evidenceRef"] != expected_ref
                or raw["objectKey"] != expected_key
            ):
                raise ValueError("declaration identity mismatch")
            item = EvidenceItem(
                declaration.evidence_id,
                raw["evidenceRef"],
                declaration.subject.work_order_id,
                declaration.subject.submission_id,
                declaration.subject.revision,
                declaration,
                _require_safe_object_key(raw["objectKey"]),
            )
            if item.evidence_ref in self._items or raw["natural"] in self._natural:
                raise ValueError("duplicate declaration")
            self._items[item.evidence_ref] = item
            self._natural[raw["natural"]] = item.evidence_ref
            self._bind(
                raw["idempotency"],
                item.evidence_ref,
                operation="declare",
                scope=self._declaration_scope(declaration),
                body=self._declaration_body(declaration),
            )
        elif kind == "external-evidence-idempotency-bound":
            if set(raw) != {"kind", "version", "eventDigest", "evidenceRef", "idempotency"}:
                raise ValueError("invalid idempotency event")
            if raw["evidenceRef"] not in self._items:
                raise ValueError("unknown evidence")
            bound_item = self._items[raw["evidenceRef"]]
            operation = (
                raw["idempotency"].get("operation")
                if isinstance(raw["idempotency"], dict)
                else None
            )
            if operation == "declare":
                self._bind(
                    raw["idempotency"],
                    bound_item.evidence_ref,
                    operation="declare",
                    scope=self._declaration_scope(bound_item.declaration),
                    body=self._declaration_body(bound_item.declaration),
                )
            elif operation == "seal":
                self._bind(
                    raw["idempotency"],
                    bound_item.evidence_ref,
                    operation="seal",
                    scope=self._evidence_scope(bound_item),
                    body={},
                )
            else:
                raise ValueError("invalid bound operation")
        elif kind == "external-evidence-grant-issued":
            if set(raw) != {
                "kind",
                "version",
                "eventDigest",
                "evidenceRef",
                "idempotency",
                "expiresAt",
            }:
                raise ValueError("invalid grant event")
            grant_item = self._items.get(raw["evidenceRef"])
            if grant_item is None:
                raise ValueError("unknown evidence")
            if grant_item.manifest is not None:
                raise ValueError("grant after seal")
            expires = datetime.fromisoformat(raw["expiresAt"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires.utcoffset() is None:
                raise ValueError("grant expiry must be aware")
            binding_key = (
                raw["idempotency"].get("key") if isinstance(raw["idempotency"], dict) else None
            )
            if not isinstance(binding_key, str):
                raise ValueError("invalid idempotency key")
            if binding_key in dict(grant_item.grants):
                raise ValueError("duplicate grant")
            self._items[grant_item.evidence_ref] = replace(
                grant_item, grants=grant_item.grants + ((binding_key, _Grant(expires)),)
            )
            self._bind(
                raw["idempotency"],
                grant_item.evidence_ref,
                operation="grant",
                scope=self._evidence_scope(grant_item),
                body={},
            )
        elif kind == "external-evidence-sealed":
            if set(raw) != {
                "kind",
                "version",
                "eventDigest",
                "evidenceRef",
                "idempotency",
                "manifest",
            }:
                raise ValueError("invalid seal event")
            sealed_item = self._items.get(raw["evidenceRef"])
            if sealed_item is None:
                raise ValueError("unknown evidence")
            if sealed_item.manifest is not None:
                raise ValueError("duplicate seal")
            manifest = ExternalEvidenceManifestV1.model_validate(raw["manifest"])
            if (
                manifest.evidence_id != sealed_item.evidence_id
                or manifest.declaration_digest != sealed_item.declaration.declaration_digest
                or manifest.subject != sealed_item.declaration.subject
                or manifest.subject_digest != sealed_item.declaration.subject_digest
                or manifest.target_dsm_artifact_id != sealed_item.declaration.target_dsm_artifact_id
                or manifest.target_dsm_observed_sha256
                != sealed_item.declaration.target_dsm_observed_sha256
                or manifest.observed_object_digest
                != sealed_item.declaration.declared_content_digest
                or manifest.observed_content_type != sealed_item.declaration.declared_content_type
                or manifest.server_object_key != sealed_item.object_key
                or manifest.evidence_manifest_digest is None
                or manifest.evidence_manifest_id
                != "external-evidence-manifest-"
                + hashlib.sha256(sealed_item.evidence_ref.encode()).hexdigest()[:32]
            ):
                raise ValueError("manifest mismatch")
            self._items[sealed_item.evidence_ref] = replace(sealed_item, manifest=manifest)
            self._bind(
                raw["idempotency"],
                sealed_item.evidence_ref,
                operation="seal",
                scope=self._evidence_scope(sealed_item),
                body={},
            )
        else:
            raise ValueError("unknown event")

    def _bind(
        self,
        binding: Any,
        evidence_ref: str,
        *,
        operation: str,
        scope: dict[str, Any],
        body: dict[str, Any],
    ) -> None:
        if not isinstance(binding, dict) or set(binding) != {
            "key",
            "fingerprint",
            "operation",
            "scope",
            "body",
        }:
            raise ValueError("invalid idempotency")
        key = binding["key"]
        fingerprint = binding["fingerprint"]
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", key)
            or not isinstance(fingerprint, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
        ):
            raise ValueError("invalid idempotency key")
        if (
            binding["operation"] != operation
            or binding["scope"] != scope
            or binding["body"] != body
            or fingerprint != _digest({"operation": operation, "scope": scope, "body": body})
        ):
            raise ValueError("idempotency fingerprint mismatch")
        existing = self._idempotency.get(key)
        value = (fingerprint, evidence_ref)
        if existing is not None:
            raise ValueError("duplicate idempotency binding")
        self._idempotency[key] = value

    @staticmethod
    def _declaration_body(declaration: ExternalEvidenceDeclarationV1) -> dict[str, Any]:
        return {
            "targetDsmArtifactId": declaration.target_dsm_artifact_id,
            "declaredContentDigest": declaration.declared_content_digest,
            "declaredContentType": declaration.declared_content_type,
            "independenceBasis": declaration.independence_basis,
        }

    @staticmethod
    def _declaration_scope(declaration: ExternalEvidenceDeclarationV1) -> dict[str, Any]:
        return {
            "workOrderId": declaration.subject.work_order_id,
            "submissionId": declaration.subject.submission_id,
            "revision": declaration.subject.revision,
        }

    @staticmethod
    def _evidence_scope(item: EvidenceItem) -> dict[str, Any]:
        return {"evidenceRef": item.evidence_ref, "revision": item.revision}

    @classmethod
    def _derived_declaration_ids(
        cls, declaration: ExternalEvidenceDeclarationV1
    ) -> tuple[str, str, str, str]:
        natural = _digest(
            {
                "subject": declaration.subject.canonical_digest(),
                "dsm": declaration.target_dsm_observed_sha256,
                "body": cls._declaration_body(declaration),
            }
        )
        evidence_id = (
            "external-evidence-" + hashlib.sha256((natural + "\0id").encode()).hexdigest()[:32]
        )
        evidence_ref = (
            "eev-v1-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "version": "eev-v1",
                        "organization": declaration.subject.organization_id,
                        "natural": natural,
                    }
                )
            ).hexdigest()
        )
        return (
            natural,
            evidence_id,
            evidence_ref,
            "external-evidence/v1/" + hashlib.sha256(evidence_ref.encode()).hexdigest(),
        )

    def _prevalidate(self, raw: dict[str, Any]) -> None:
        trial = object.__new__(ExternalEvidenceStore)
        trial._items = self._items.copy()
        trial._natural = self._natural.copy()
        trial._idempotency = self._idempotency.copy()
        trial._apply(raw)

    def _append_projected(self, raw: dict[str, Any]) -> None:
        self._prevalidate(raw)
        self._journal.append(raw)
        self._apply(raw)

    def _fresh_now(self, not_before: datetime) -> datetime:
        fresh_now = self._clock()
        if fresh_now.tzinfo is None or fresh_now.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return max(not_before, fresh_now)

    def _reserve_locked(
        self, binding: dict[str, Any], evidence_ref: str
    ) -> tuple[str, _PendingBinding | None]:
        committed = self._idempotency.get(binding["key"])
        expected = (binding["fingerprint"], evidence_ref)
        if committed is not None:
            return ("committed" if committed == expected else "conflict", None)
        pending = self._pending.get(binding["key"])
        if pending is not None:
            return (
                ("wait", pending)
                if (pending.fingerprint, pending.evidence_ref) == expected
                else ("conflict", None)
            )
        pending = _PendingBinding(binding["fingerprint"], evidence_ref, threading.Event())
        self._pending[binding["key"]] = pending
        return "owner", pending

    def _release_locked(self, binding: dict[str, Any], pending: _PendingBinding) -> None:
        if self._pending.get(binding["key"]) is pending:
            del self._pending[binding["key"]]
            pending.completed.set()

    @staticmethod
    def _binding(
        principal: Principal, operation: str, scope: dict[str, Any], body: dict[str, Any], key: str
    ) -> dict[str, Any]:
        key = key.strip()
        if not key or len(key) > 255:
            raise ValueError("Idempotency-Key required")
        return {
            "key": _digest(
                {
                    "principal": principal.principal_id,
                    "organization": principal.organization_id,
                    "key": key,
                }
            ),
            "fingerprint": _digest({"operation": operation, "scope": scope, "body": body}),
            "operation": operation,
            "scope": scope,
            "body": body,
        }

    @staticmethod
    def _subject(
        revision: ExternalReconstructionRevision,
    ) -> tuple[SealedExternalSubjectV1, Any] | None:
        manifest = revision.manifest
        submission = revision.submission
        if (
            manifest is None
            or manifest.manifest_digest is None
            or submission.submission_digest is None
        ):
            return None
        dsm = next((entry for entry in manifest.entries if entry.kind.value == "dsm"), None)
        if dsm is None:
            return None
        return (
            SealedExternalSubjectV1(
                organization_id=submission.organization_id,
                site_id=submission.site_id,
                work_order_id=revision.work_order_id,
                submission_id=submission.submission_id,
                revision=submission.revision,
                submission_digest=submission.submission_digest,
                manifest_digest=manifest.manifest_digest,
            ),
            dsm,
        )

    def declare(
        self,
        intent: ExternalEvidenceDeclarationIntent,
        *,
        revision: ExternalReconstructionRevision,
        principal: Principal,
        key: str,
        now: datetime,
    ) -> EvidenceResult:
        subject_pair = self._subject(revision)
        if subject_pair is None or intent.target_dsm_artifact_id != subject_pair[1].artifact_id:
            return EvidenceResult(EvidenceVerdict.NOT_FOUND)
        subject, dsm = subject_pair
        scope = {
            "workOrderId": subject.work_order_id,
            "submissionId": subject.submission_id,
            "revision": subject.revision,
        }
        body = intent.model_dump(by_alias=True, mode="json")
        binding = self._binding(principal, "declare", scope, body, key)
        observed_dsm_digest = _external_digest(dsm.observed_sha256)
        declaration = ExternalEvidenceDeclarationV1(
            evidence_id="external-evidence-pending",
            subject=subject,
            subject_digest=subject.canonical_digest(),
            target_dsm_artifact_id=dsm.artifact_id,
            target_dsm_observed_sha256=observed_dsm_digest,
            declared_content_digest=intent.declared_content_digest,
            declared_content_type=intent.declared_content_type,
            independence=EvidenceIndependence.DECLARED,
            independence_basis=intent.independence_basis,
            declared_at=now,
        )
        natural = _digest(
            {"subject": subject.canonical_digest(), "dsm": observed_dsm_digest, "body": body}
        )
        evidence_id = (
            "external-evidence-" + hashlib.sha256((natural + "\0id").encode()).hexdigest()[:32]
        )
        declaration = declaration.model_copy(update={"evidence_id": evidence_id}).sealed()
        _, _, evidence_ref, object_key = self._derived_declaration_ids(declaration)
        while True:
            with self._coordinator.mutation(), self._lock:
                existing_ref = self._natural.get(natural)
                target_ref = existing_ref or evidence_ref
                state, pending = self._reserve_locked(binding, target_ref)
                if state == "committed":
                    return EvidenceResult(EvidenceVerdict.DECLARED, self._items.get(target_ref))
                if state == "conflict":
                    return EvidenceResult(EvidenceVerdict.CONFLICT, self._items.get(target_ref))
                if state == "owner":
                    assert pending is not None
                    raw = (
                        {
                            "kind": "external-evidence-idempotency-bound",
                            "version": _VERSION,
                            "evidenceRef": existing_ref,
                            "idempotency": binding,
                        }
                        if existing_ref is not None
                        else {
                            "kind": "external-evidence-declared",
                            "version": _VERSION,
                            "evidenceRef": evidence_ref,
                            "objectKey": object_key,
                            "natural": natural,
                            "idempotency": binding,
                            "declaration": external_evidence_declaration_wire_dict(declaration),
                        }
                    )
                    raw["eventDigest"] = _event_digest(raw)
                    try:
                        self._append_projected(raw)
                    except JournalSealedError:
                        self._release_locked(binding, pending)
                        return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE)
                    self._release_locked(binding, pending)
                    return EvidenceResult(EvidenceVerdict.DECLARED, self._items[target_ref])
                assert pending is not None
            pending.completed.wait()

    def is_declaration_retry(
        self,
        intent: ExternalEvidenceDeclarationIntent,
        *,
        revision: ExternalReconstructionRevision,
        principal: Principal,
        key: str,
    ) -> bool:
        """Return whether a declaration is already durable for the exact human retry."""

        subject_pair = self._subject(revision)
        if subject_pair is None or intent.target_dsm_artifact_id != subject_pair[1].artifact_id:
            return False
        subject, _dsm = subject_pair
        binding = self._binding(
            principal,
            "declare",
            {
                "workOrderId": subject.work_order_id,
                "submissionId": subject.submission_id,
                "revision": subject.revision,
            },
            intent.model_dump(by_alias=True, mode="json"),
            key,
        )
        with self._lock:
            existing = self._idempotency.get(binding["key"])
        return existing is not None and existing[0] == binding["fingerprint"]

    def list(self, revision: ExternalReconstructionRevision) -> tuple[EvidenceItem, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._items.values()
                if (item.work_order_id, item.submission_id, item.revision)
                == (
                    revision.work_order_id,
                    revision.submission.submission_id,
                    revision.submission.revision,
                )
            )

    def resolve_for_validation(self, evidence_ref: str) -> EvidenceItem | None:
        """Return one sealed record to the Core-only validation lifecycle.

        This is intentionally not a human-scoped read and exposes no object
        capability.  Callers still need an authenticated worker route plus a
        current lease before a byte binding can be issued.
        """
        with self._lock:
            item = self._items.get(evidence_ref)
            return item if item is not None and item.manifest is not None else None

    def _scoped(
        self, evidence_ref: str, revision: ExternalReconstructionRevision
    ) -> EvidenceItem | None:
        item = self._items.get(evidence_ref)
        return (
            item
            if item
            and (item.work_order_id, item.submission_id, item.revision)
            == (
                revision.work_order_id,
                revision.submission.submission_id,
                revision.submission.revision,
            )
            else None
        )

    def grant(
        self,
        evidence_ref: str,
        *,
        revision: ExternalReconstructionRevision,
        principal: Principal,
        key: str,
        storage: DigestBoundEvidenceStorage,
        now: datetime,
    ) -> EvidenceResult:
        scope = {"evidenceRef": evidence_ref, "revision": revision.submission.revision}
        binding = self._binding(principal, "grant", scope, {}, key)
        while True:
            fresh_now = self._fresh_now(now)
            with self._lock:
                item = self._scoped(evidence_ref, revision)
                if item is None:
                    return EvidenceResult(EvidenceVerdict.NOT_FOUND)
                state, pending = self._reserve_locked(binding, evidence_ref)
                if state == "conflict":
                    return EvidenceResult(EvidenceVerdict.CONFLICT, item)
                if state == "wait":
                    assert pending is not None
                else:
                    if item.manifest is not None:
                        if state == "owner":
                            assert pending is not None
                            self._release_locked(binding, pending)
                        return EvidenceResult(EvidenceVerdict.NOT_SEALED, item)
                    old = dict(item.grants).get(binding["key"])
                    if state == "committed" and old is None:
                        return EvidenceResult(EvidenceVerdict.CONFLICT, item)
                    expires = old.expires_at if old else fresh_now + DEFAULT_UPLOAD_TTL
                    if fresh_now >= expires:
                        if state == "owner":
                            assert pending is not None
                            self._release_locked(binding, pending)
                        return EvidenceResult(EvidenceVerdict.EXPIRED, item)
                    snapshot = item
                    break
            pending.completed.wait()
        owner_pending = pending if state == "owner" else None
        if owner_pending is not None:
            assert state == "owner"
        fresh_now = self._fresh_now(now)
        if fresh_now >= expires:
            if owner_pending is not None:
                with self._lock:
                    self._release_locked(binding, owner_pending)
            return EvidenceResult(EvidenceVerdict.EXPIRED, snapshot)
        try:
            capability = storage.presigned_put_bound_digest(
                snapshot.object_key,
                content_type=snapshot.declaration.declared_content_type,
                content_digest=snapshot.declaration.declared_content_digest,
                ttl=expires - fresh_now,
            )
        except EvidenceStorageError:
            if owner_pending is not None:
                with self._lock:
                    self._release_locked(binding, owner_pending)
            return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE, snapshot)
        with self._lock:
            item = self._scoped(evidence_ref, revision)
            if item is None:
                if owner_pending is not None:
                    self._release_locked(binding, owner_pending)
                return EvidenceResult(EvidenceVerdict.NOT_FOUND)
            if self._fresh_now(now) >= expires:
                if owner_pending is not None:
                    self._release_locked(binding, owner_pending)
                return EvidenceResult(EvidenceVerdict.EXPIRED, item)
            if item.manifest is not None:
                if owner_pending is not None:
                    self._release_locked(binding, owner_pending)
                return EvidenceResult(EvidenceVerdict.NOT_SEALED, item)
            if owner_pending is not None:
                raw = {
                    "kind": "external-evidence-grant-issued",
                    "version": _VERSION,
                    "evidenceRef": evidence_ref,
                    "idempotency": binding,
                    "expiresAt": iso_utc(expires),
                }
                raw["eventDigest"] = _event_digest(raw)
                try:
                    self._append_projected(raw)
                except JournalSealedError:
                    self._release_locked(binding, owner_pending)
                    return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE, item)
                self._release_locked(binding, owner_pending)
                item = self._items[evidence_ref]
            return EvidenceResult(
                EvidenceVerdict.DECLARED,
                item,
                capability.upload_url,
                expires,
                capability.required_headers,
            )

    def seal(
        self,
        evidence_ref: str,
        *,
        revision: ExternalReconstructionRevision,
        principal: Principal,
        key: str,
        storage: ObjectStorageObservationPort,
        now: datetime,
    ) -> EvidenceResult:
        scope = {"evidenceRef": evidence_ref, "revision": revision.submission.revision}
        binding = self._binding(principal, "seal", scope, {}, key)
        while True:
            with self._lock:
                item = self._scoped(evidence_ref, revision)
                if item is None:
                    return EvidenceResult(EvidenceVerdict.NOT_FOUND)
                state, pending = self._reserve_locked(binding, evidence_ref)
                if state == "conflict":
                    return EvidenceResult(EvidenceVerdict.CONFLICT, item)
                if state == "wait":
                    assert pending is not None
                elif item.manifest is not None:
                    if state == "owner":
                        assert pending is not None
                        raw = {
                            "kind": "external-evidence-idempotency-bound",
                            "version": _VERSION,
                            "evidenceRef": evidence_ref,
                            "idempotency": binding,
                        }
                        raw["eventDigest"] = _event_digest(raw)
                        try:
                            self._append_projected(raw)
                        except JournalSealedError:
                            self._release_locked(binding, pending)
                            return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE, item)
                        self._release_locked(binding, pending)
                    return EvidenceResult(EvidenceVerdict.SEALED, item)
                elif state == "committed":
                    return EvidenceResult(EvidenceVerdict.CONFLICT, item)
                else:
                    assert pending is not None
                    snapshot = item
                    break
            pending.completed.wait()
        assert pending is not None
        try:
            observed = storage.observe_object(snapshot.object_key)
        except EvidenceStorageError:
            with self._lock:
                self._release_locked(binding, pending)
            return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE, snapshot)
        if not observed.exists:
            with self._lock:
                self._release_locked(binding, pending)
            return EvidenceResult(EvidenceVerdict.OBSERVATION_MISSING, snapshot)
        if (
            observed.object_key != snapshot.object_key
            or observed.sha256 != snapshot.declaration.declared_content_digest
            or observed.content_type != snapshot.declaration.declared_content_type
            or observed.size_bytes is None
            or observed.size_bytes <= 0
        ):
            with self._lock:
                self._release_locked(binding, pending)
            return EvidenceResult(EvidenceVerdict.OBSERVATION_MISMATCH, snapshot)
        assert snapshot.declaration.declaration_digest is not None
        manifest = ExternalEvidenceManifestV1(
            evidence_manifest_id="external-evidence-manifest-"
            + hashlib.sha256(snapshot.evidence_ref.encode()).hexdigest()[:32],
            evidence_id=snapshot.evidence_id,
            declaration_digest=snapshot.declaration.declaration_digest,
            subject=snapshot.declaration.subject,
            subject_digest=snapshot.declaration.subject_digest,
            target_dsm_artifact_id=snapshot.declaration.target_dsm_artifact_id,
            target_dsm_observed_sha256=snapshot.declaration.target_dsm_observed_sha256,
            observed_object_digest=observed.sha256,
            observed_size_bytes=observed.size_bytes,
            observed_content_type=observed.content_type,
            server_object_key=snapshot.object_key,
            observed_at=now,
        ).sealed()
        with self._coordinator.mutation(), self._lock:
            item = self._scoped(evidence_ref, revision)
            if item is None:
                self._release_locked(binding, pending)
                return EvidenceResult(EvidenceVerdict.NOT_FOUND)
            newly_sealed = item.manifest is None
            if item.manifest is not None:
                raw = {
                    "kind": "external-evidence-idempotency-bound",
                    "version": _VERSION,
                    "evidenceRef": evidence_ref,
                    "idempotency": binding,
                }
            else:
                raw = {
                    "kind": "external-evidence-sealed",
                    "version": _VERSION,
                    "evidenceRef": evidence_ref,
                    "idempotency": binding,
                    "manifest": external_evidence_manifest_wire_dict(manifest),
                }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_projected(raw)
            except JournalSealedError:
                self._release_locked(binding, pending)
                return EvidenceResult(EvidenceVerdict.STORAGE_UNAVAILABLE, item)
            self._release_locked(binding, pending)
            sealed = self._items[evidence_ref]
            listeners = tuple(self._seal_listeners) if newly_sealed else ()
        for listener in listeners:
            try:
                listener(sealed, now)
            except Exception:
                # Derived issue work is recovered from the immutable seal on
                # assembly restart; a listener cannot alter ingress history.
                continue
        return EvidenceResult(EvidenceVerdict.SEALED, sealed)


def _view(
    item: EvidenceItem,
    *,
    terminal_records: tuple[ExternalEvidenceRecordV1, ...] = (),
) -> ExternalEvidenceView:
    d, m = item.declaration, item.manifest
    summaries = [
        ExternalEvidenceMeasurementSummaryView(
            core_verdict=record.core_verdict,
            measured_checkpoint_count=record.measurement_payload.measured_checkpoint_count,
            mean_error_m=record.measurement_payload.mean_error_m,
            mae_m=record.measurement_payload.mae_m,
            rmse_m=record.measurement_payload.rmse_m,
            recorded_at=record.core_recorded_at,
        )
        for record in terminal_records
        if record.measurement_payload is not None
    ]
    if m is None:
        return ExternalEvidenceView(
            evidence_ref=item.evidence_ref,
            state=EvidenceState.DECLARED,
            target_dsm_artifact_id=d.target_dsm_artifact_id,
            target_dsm_observed_sha256=d.target_dsm_observed_sha256,
            declared_content_digest=d.declared_content_digest,
            declared_content_type=d.declared_content_type,
            independence_basis=d.independence_basis,
            declared_at=d.declared_at,
            measurement_summaries=summaries or None,
        )
    return ExternalEvidenceView(
        evidence_ref=item.evidence_ref,
        state=EvidenceState.SEALED_BYTE_OBSERVED,
        target_dsm_artifact_id=d.target_dsm_artifact_id,
        target_dsm_observed_sha256=d.target_dsm_observed_sha256,
        declared_content_digest=d.declared_content_digest,
        declared_content_type=d.declared_content_type,
        independence_basis=d.independence_basis,
        declared_at=d.declared_at,
        observed_object_digest=m.observed_object_digest,
        observed_size_bytes=m.observed_size_bytes,
        observed_content_type=m.observed_content_type,
        observed_at=m.observed_at,
        measurement_summaries=summaries or None,
    )


def _require_scoped_work_order(
    work_orders: ObservationWorkOrderStore, work_order_id: str, principal: Principal
) -> Any:
    """INV-060: derive organization/Site/WorkArea scope from the WorkOrder.

    The organization comes from the authenticated principal, never the body.
    The order's Site must be granted and every WorkArea of the order must be
    granted. An order with no WorkArea anchor fails closed for area-restricted
    principals — ``set() <= grants`` would otherwise pass vacuously with no
    resource proving the scope. Mismatches fold into the same non-disclosing
    404 as a missing order.
    """
    order = work_orders.get(work_order_id, organization_id=principal.organization_id)
    if order is None:
        raise HTTPException(404, _NOT_FOUND)
    if principal.allowed_site_ids is not None and order.site_id not in principal.allowed_site_ids:
        raise HTTPException(404, _NOT_FOUND)
    areas = getattr(order, "work_area_ids", None) or ()
    if principal.allowed_work_area_ids is not None and (
        not areas or not set(areas).issubset(principal.allowed_work_area_ids)
    ):
        raise HTTPException(404, _NOT_FOUND)
    return order


def mount_external_evidence(
    app: FastAPI,
    store: ExternalEvidenceStore,
    *,
    reconstruction: ExternalReconstructionStore,
    work_orders: ObservationWorkOrderStore,
    storage: Any,
    terminal_records: ExternalEvidenceTerminalRecordProjectionPort | None = None,
) -> None:
    router = APIRouter(prefix="/v1/observation-work-orders", tags=["external-evidence"])
    read = require_permission(Permission.SITES_READ)
    write = require_permission(Permission.SITES_WRITE)
    base = (
        "/{work_order_id}/external-reconstruction-submissions/{submission_ref}"
        "/revisions/{revision}/evidence"
    )

    def revision_for(
        work_order_id: str, submission_ref: str, revision: int, principal: Principal
    ) -> ExternalReconstructionRevision:
        order = _require_scoped_work_order(work_orders, work_order_id, principal)
        sid = reconstruction.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        record = (
            reconstruction.get(
                work_order_id,
                sid,
                revision,
                organization_id=principal.organization_id,
                site_id=order.site_id,
            )
            if sid
            else None
        )
        if record is None:
            raise HTTPException(404, _NOT_FOUND)
        return record

    def human(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(403, "HUMAN_AUTHORITY_REQUIRED")

    def view(item: EvidenceItem) -> ExternalEvidenceView:
        return _view(
            item,
            terminal_records=(
                terminal_records.terminal_records_for_evidence(item.evidence_ref)
                if terminal_records is not None
                else ()
            ),
        )

    def error(result: EvidenceResult) -> None:
        status = {
            EvidenceVerdict.NOT_FOUND: 404,
            EvidenceVerdict.CONFLICT: 409,
            EvidenceVerdict.EXPIRED: 409,
            EvidenceVerdict.NOT_SEALED: 409,
            EvidenceVerdict.OBSERVATION_MISSING: 422,
            EvidenceVerdict.OBSERVATION_MISMATCH: 422,
            EvidenceVerdict.STORAGE_UNAVAILABLE: 503,
        }.get(result.verdict)
        if status:
            raise HTTPException(status, result.verdict.value)

    def idempotency_header(
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=255, pattern=r".*\S.*"
        ),
    ) -> str:
        return idempotency_key.strip()

    @router.post(
        base,
        response_model=ExternalEvidenceView,
        response_model_exclude_none=True,
        status_code=201,
    )
    def declare(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        intent: ExternalEvidenceDeclarationIntent,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalEvidenceView:  # noqa: B008
        human(principal)
        resolved_revision = revision_for(work_order_id, submission_ref, revision, principal)
        try:
            with work_orders.guard_new_external_intent(
                work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: store.is_declaration_retry(
                    intent,
                    revision=resolved_revision,
                    principal=principal,
                    key=idempotency_key,
                ),
            ):
                result = store.declare(
                    intent,
                    revision=resolved_revision,
                    principal=principal,
                    key=idempotency_key,
                    now=datetime.now(UTC),
                )
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        error(result)
        assert result.item
        return view(result.item)

    @router.get(base, response_model=ExternalEvidenceListResponse, response_model_exclude_none=True)
    def list_evidence(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> ExternalEvidenceListResponse:  # noqa: B008
        return ExternalEvidenceListResponse(
            items=[
                view(item)
                for item in store.list(
                    revision_for(work_order_id, submission_ref, revision, principal)
                )
            ]
        )

    @router.post(
        base + "/{evidence_ref}/upload-grant", response_model=ExternalEvidenceUploadGrantResponse
    )
    def grant(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        evidence_ref: str,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalEvidenceUploadGrantResponse:  # noqa: B008
        human(principal)
        result = store.grant(
            evidence_ref,
            revision=revision_for(work_order_id, submission_ref, revision, principal),
            principal=principal,
            key=idempotency_key,
            storage=storage,
            now=datetime.now(UTC),
        )
        error(result)
        assert result.upload_url and result.expires_at and result.required_headers
        return ExternalEvidenceUploadGrantResponse(
            evidence_ref=evidence_ref,
            upload_url=result.upload_url,
            expires_at=result.expires_at,
            required_headers=result.required_headers,
        )

    @router.post(
        base + "/{evidence_ref}/seal",
        response_model=ExternalEvidenceView,
        response_model_exclude_none=True,
    )
    def seal(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        evidence_ref: str,
        idempotency_key: str = Depends(idempotency_header),  # noqa: B008
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalEvidenceView:  # noqa: B008
        human(principal)
        result = store.seal(
            evidence_ref,
            revision=revision_for(work_order_id, submission_ref, revision, principal),
            principal=principal,
            key=idempotency_key,
            storage=storage,
            now=datetime.now(UTC),
        )
        error(result)
        assert result.item
        return view(result.item)

    app.state.external_evidence_store = store
    app.include_router(router)


__all__ = ["ExternalEvidenceStore", "ExternalEvidenceRecoveryError", "mount_external_evidence"]
