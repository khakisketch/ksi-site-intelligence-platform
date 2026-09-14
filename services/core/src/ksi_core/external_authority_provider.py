"""File-backed, externally signed authority material for quantitative workflow wiring.

The provider verifies an operator-owned authority bundle with a public Ed25519
key.  It never creates authority records, has no private signing material, and
is deliberately inert until a caller binds its durable receipt journal and
then attaches the already assembled Core application.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock, local
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence_validations import EvidenceMeasurementContextAuthorityPort
from ksi_core.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityCurrentnessPort,
    ExternalQuantitativeCatalogAuthorityPort,
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.external_relative_volumes import ExternalRelativeVolumeQueuePolicy
from ksi_core.external_result_workflow_config import ExternalQuantitativeWorkflowParticipants
from ksi_core.external_validation_policy import (
    PolicyAuthorityCurrentnessPort,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
)

_CONFIG_VERSION = "external-authority-provider-config.v1"
_REGISTRY_VERSION = "external-authority-key-registry.v1"
_SNAPSHOT_VERSION = "external-authority-provider-snapshot.v1"
_SNAPSHOT_DOMAIN = "ksi.external-authority-provider-snapshot.v1"
_RECEIPT_NAME = "external-authority-provider-receipts.jsonl"
_MAX_FILE_BYTES = 1024 * 1024
_MAX_REGISTRY_KEYS = 128
_MAX_COLLECTION_RECORDS = 4_096
_MAX_ADMINISTRATION_ACTIONS = 4_096
_RECEIPT_KIND = "external-authority-provider-receipt"
_RECEIPT_VERSION = 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UTC_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")
_SNAPSHOT_UNSIGNED_FIELDS = frozenset(
    {
        "version",
        "organizationId",
        "sequence",
        "previousSnapshotDigest",
        "issuedAt",
        "validUntil",
        "keyId",
        "catalogAuthorities",
        "policyAuthorities",
        "evidenceContexts",
        "quantitativeAdministration",
    }
)


class ExternalAuthorityProviderError(RuntimeError):
    """External authority input cannot be used safely."""


def _utc(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_RFC3339.fullmatch(value) is None:
        raise ValueError(f"{name} must be a UTC RFC3339 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{name} must be UTC-aware")
    return parsed


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty trimmed text")
    return value


def _exact_mapping(raw: object, fields: frozenset[str], *, name: str) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != fields or any(type(key) is not str for key in raw):
        raise ValueError(f"{name} has an invalid object shape")
    return cast(dict[str, object], raw)


def _no_constant(value: str) -> object:
    raise ValueError(f"JSON constant {value!r} is not permitted")


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _protected_bytes(
    path: Path, *, name: str, maximum: int, private: bool,
) -> bytes:
    """Read only the bounded regular descriptor whose metadata was checked."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} path must be absolute and normalized")
    directory = -1
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open("/", flags | os.O_DIRECTORY)
        for part in path.parent.parts[1:]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            parent = os.fstat(directory)
            if parent.st_uid not in {0, os.geteuid()} or (
                parent.st_mode & 0o022 and not parent.st_mode & stat.S_ISVTX
            ):
                raise ValueError(f"{name} has an unprotected parent")
        descriptor = os.open(path.name, flags | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or not before.st_mode & stat.S_IRUSR
            or before.st_mode & (0o077 if private else 0o022)
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError(f"{name} is not bounded protected regular material")
        content = bytearray()
        while len(content) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if len(content) != before.st_size or (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
            after.st_mode, after.st_uid, after.st_gid, after.st_nlink,
        ) != (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns,
            before.st_mode, before.st_uid, before.st_gid, before.st_nlink,
        ):
            raise ValueError(f"{name} changed during its bounded read")
        return bytes(content)
    except OSError as exc:
        raise ValueError(f"{name} is unavailable or unsafe") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)


def _private_json(path: Path, *, name: str) -> object:
    try:
        raw = _protected_bytes(path, name=name, maximum=_MAX_FILE_BYTES, private=True)
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_no_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} is not strict JSON") from exc


def _safe_child(parent: Path, value: object, *, name: str) -> Path:
    child = _text(value, name=name)
    if Path(child).name != child or child in {".", ".."} or not child.endswith(".pem"):
        raise ValueError(f"{name} must name one PEM child")
    candidate = parent / child
    if candidate.parent != parent:
        raise ValueError(f"{name} escapes its registry directory")
    return candidate


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class _VerifiedSnapshot:
    organization_id: str
    sequence: int
    digest: str
    issued_at: datetime
    valid_until: datetime
    key_id: str
    public_key_digest: str
    key_not_before: datetime
    key_not_after: datetime
    raw: dict[str, object]
    catalog_records: dict[str, ExternalQuantitativeCatalogAuthorityRecord]
    current_catalog_digests: frozenset[str]
    policy_records: dict[str, PolicyAuthorityRecord]
    current_policy_digests: frozenset[str]
    context_records: dict[str, ExternalEvidenceMeasurementContextV1]
    current_context_digests: frozenset[str]
    actions: tuple[_AdministrationAction, ...]


@dataclass(frozen=True, slots=True)
class _ActiveKey:
    """The key material and validity interval verified during the file read."""

    public_key: Ed25519PublicKey
    public_key_digest: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True, slots=True)
class _AuthorityGeneration:
    """One immutable, receipt-backed authority publication generation."""

    snapshot: _VerifiedSnapshot
    counter: int
    receipt_sequence: int
    receipt_history_digest: str


def _copy_snapshot(snapshot: _VerifiedSnapshot) -> _VerifiedSnapshot:
    """Copy every mutable container before handing a candidate to live ports."""
    raw = cast(dict[str, object], json.loads(canonical_json_bytes(snapshot.raw)))
    actions = tuple(
        _AdministrationAction(
            action_id=action.action_id,
            kind=action.kind,
            effective_at=action.effective_at,
            actor_id=action.actor_id,
            payload=cast(dict[str, object], json.loads(canonical_json_bytes(action.payload))),
        )
        for action in snapshot.actions
    )
    return _VerifiedSnapshot(
        organization_id=snapshot.organization_id,
        sequence=snapshot.sequence,
        digest=snapshot.digest,
        issued_at=snapshot.issued_at,
        valid_until=snapshot.valid_until,
        key_id=snapshot.key_id,
        public_key_digest=snapshot.public_key_digest,
        key_not_before=snapshot.key_not_before,
        key_not_after=snapshot.key_not_after,
        raw=raw,
        catalog_records=dict(snapshot.catalog_records),
        current_catalog_digests=frozenset(snapshot.current_catalog_digests),
        policy_records=dict(snapshot.policy_records),
        current_policy_digests=frozenset(snapshot.current_policy_digests),
        context_records=dict(snapshot.context_records),
        current_context_digests=frozenset(snapshot.current_context_digests),
        actions=actions,
    )


@dataclass(frozen=True, slots=True)
class _ProviderConfig:
    organization_id: str
    key_registry_path: Path
    snapshot_path: Path
    catalog_administration_actor_id: str
    queue_policy: ExternalRelativeVolumeQueuePolicy


@dataclass(frozen=True, slots=True)
class _AdministrationAction:
    action_id: str
    kind: str
    effective_at: datetime
    actor_id: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Receipt:
    sequence: int
    snapshot_digest: str
    previous_snapshot_digest: str | None
    key_id: str
    public_key_digest: str
    history_digest: str
    snapshot: dict[str, object]


class _CatalogPort(ExternalQuantitativeCatalogAuthorityPort):
    def __init__(self, provider: ExternalAuthorityProvider) -> None:
        self._provider = provider

    def resolve(
        self, authority_record_digest: str, now: datetime
    ) -> ExternalQuantitativeCatalogAuthorityRecord | None:
        # During startup/reload, mapping reconciliation runs before the new
        # receipt is published.  Its thread-local candidate is the same exact
        # signed snapshot that policy/context participants consume; falling
        # back to configuration-only material keeps the pre-attach catalog
        # loader default-closed without exposing that candidate to other
        # threads.
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None:
            snapshot = self._provider._configuration_snapshot(now)
        if snapshot is None or authority_record_digest not in snapshot.current_catalog_digests:
            return None
        record = snapshot.catalog_records.get(authority_record_digest)
        if (
            record is None
            or record.organization_id != self._provider.organization_id
            or not record.is_active_at(now)
        ):
            return None
        return record


class _PolicyPort(PolicyAuthorityPort):
    def __init__(self, provider: ExternalAuthorityProvider) -> None:
        self._provider = provider

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None or authority_record_digest not in snapshot.current_policy_digests:
            return None
        record = snapshot.policy_records.get(authority_record_digest)
        if record is None or not record.is_active_at(now):
            return None
        if any(
            subject.organization_id != self._provider.organization_id
            for subject in record.permitted_subjects
        ):
            return None
        return record

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        return self._provider._historical_policy(authority_record_digest, at)


class _PolicyCurrentness(PolicyAuthorityCurrentnessPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and authority.digest is not None
            and authority.digest in snapshot.current_policy_digests
            and snapshot.policy_records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


class _CatalogCurrentness(ExternalQuantitativeCatalogAuthorityCurrentnessPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def is_current(
        self, authority: ExternalQuantitativeCatalogAuthorityRecord, now: datetime
    ) -> bool:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and authority.digest is not None
            and authority.digest in snapshot.current_catalog_digests
            and snapshot.catalog_records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


class _EvidenceContextPort(EvidenceMeasurementContextAuthorityPort):
    def __init__(
        self,
        provider: ExternalAuthorityProvider,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._provider = provider
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def resolve_for_validation(
        self,
        *,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        now: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        if snapshot is None:
            return None
        matches = tuple(
            context
            for digest, context in snapshot.context_records.items()
            if (
                digest in snapshot.current_context_digests
                and context.is_active_at(now)
                and context.subject == subject
                and context.evidence_manifest_digest == evidence_manifest_digest
                and context.target_dsm_artifact_id == target_dsm_artifact_id
                and context.target_dsm_observed_sha256 == target_dsm_observed_sha256
                and context.policy_digest == policy_digest
            )
        )
        return matches[0] if len(matches) == 1 else None

    def resolve_historical_for_validation(
        self,
        *,
        context_digest: str,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        issued_at: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        context = self._provider._historical_context(context_digest)
        if context is None:
            return None
        return (
            context
            if (
                context.is_active_at(issued_at)
                and context.subject == subject
                and context.evidence_manifest_digest == evidence_manifest_digest
                and context.target_dsm_artifact_id == target_dsm_artifact_id
                and context.target_dsm_observed_sha256 == target_dsm_observed_sha256
                and context.policy_digest == policy_digest
            )
            else None
        )

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        try:
            now = self._provider._clock()
        except Exception:
            return False
        snapshot = self._provider._live_snapshot(now, permit_staged=True)
        return bool(
            snapshot is not None
            and context.context_digest is not None
            and context.context_digest in snapshot.current_context_digests
            and snapshot.context_records.get(context.context_digest) == context
            and context.is_active_at(now)
        )


class ExternalAuthorityProvider:
    """One verified authority bundle and its Core participant ports."""

    def __init__(
        self,
        config: _ProviderConfig,
        snapshot: _VerifiedSnapshot,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._candidate_snapshot: _VerifiedSnapshot | None = snapshot
        self._published_generation: _AuthorityGeneration | None = None
        self._clock = clock
        self._blocked_reason: str | None = None
        self._configured = False
        self._state_lock = RLock()
        # Reload is a transaction over one mutable signed source and several
        # durable participant journals.  A newer caller must not reserve a
        # ticket or begin its protected read while an older reconciliation can
        # still append participant/receipt records and publish its generation.
        self._reload_lock = RLock()
        self._staged = local()
        self._latest_reload_ticket = 0
        self._next_generation = 0
        self._receipt_journal: DurableJournal | None = None
        self._receipts: tuple[_Receipt, ...] = ()
        self._historical_contexts: dict[str, ExternalEvidenceMeasurementContextV1] = {}
        self._historical_policies: dict[str, PolicyAuthorityRecord] = {}
        self._app: FastAPI | None = None
        self._participant_coordinator: ExternalAuthorityCurrentnessCoordinator | None = None
        self._catalog_port = _CatalogPort(self)
        self._policy_port = _PolicyPort(self)
        self._catalog_currentness_port: _CatalogCurrentness | None = None
        self._policy_currentness_port: _PolicyCurrentness | None = None
        self._evidence_context_port: _EvidenceContextPort | None = None
        self.participants = ExternalQuantitativeWorkflowParticipants(
            catalog_authority_port=self._catalog_port,
            catalog_administration_actor_id=config.catalog_administration_actor_id,
            queue_policy=config.queue_policy,
            clock=clock,
            build_catalog_authority_currentness=self._build_catalog_currentness,
            policy_authority_port=self._policy_port,
            build_policy_authority_currentness=self._build_policy_currentness,
            build_evidence_context_authority=self._build_evidence_context,
        )

    @property
    def organization_id(self) -> str:
        return self._config.organization_id

    def status(self) -> dict[str, object]:
        try:
            now = self._clock()
        except Exception:
            now = None
        with self._state_lock:
            generation = self._published_generation
            snapshot = generation.snapshot if generation is not None else self._candidate_snapshot
            configured = self._configured and generation is not None
            receipt_sealed = bool(
                self._receipt_journal is not None
                and self._receipt_journal.sealed_reason is not None
            )
            blocked = self._blocked_reason is not None
        if (
            snapshot is None
            or now is None
            or not self._snapshot_valid_at(snapshot, now)
            or receipt_sealed
            or blocked
        ):
            return {
                "status": "BLOCKED",
                "organizationId": self.organization_id,
                "snapshotSequence": None,
                "snapshotDigest": None,
                "businessEligible": False,
            }
        return {
            "status": "PROVIDER_CONFIGURED" if configured else "CONFIG_VALIDATED",
            "organizationId": self.organization_id,
            "snapshotSequence": snapshot.sequence,
            "snapshotDigest": snapshot.digest,
            "businessEligible": False,
        }

    def bind_receipt_journal(self, journal: DurableJournal) -> None:
        if self._receipt_journal is not None and self._receipt_journal is not journal:
            raise ExternalAuthorityProviderError("authority receipt journal is already bound")
        if not isinstance(journal, DurableJournal):
            raise ValueError("authority receipt journal must be durable")
        journal_path = getattr(journal, "_path", None)
        if (
            not isinstance(journal_path, Path)
            or not journal_path.is_absolute()
            or journal_path.name != _RECEIPT_NAME
        ):
            raise ValueError(
                "authority receipt journal must use the fixed absolute receipt path name"
            )
        try:
            with self._state_lock:
                snapshot = self._candidate_snapshot
            if snapshot is None:
                raise ValueError("authority provider has no verified candidate snapshot")
            receipts = _replay_receipts(journal)
            self._validate_history(receipts, snapshot)
            historical_contexts = _historical_contexts_from_receipts(
                receipts, organization_id=self.organization_id
            )
            historical_policies = _historical_policies_from_receipts(
                receipts, organization_id=self.organization_id
            )
        except Exception as exc:
            self._block(type(exc).__name__)
            raise ExternalAuthorityProviderError("authority receipt history is blocked") from exc
        with self._state_lock:
            self._receipt_journal = journal
            self._receipts = receipts
            self._historical_contexts = historical_contexts
            self._historical_policies = historical_policies

    def attach_app(self, app: FastAPI) -> None:
        if self._receipt_journal is None:
            raise ExternalAuthorityProviderError(
                "authority receipt journal must bind before app attach"
            )
        state = getattr(app, "state", None)
        if state is None:
            raise ValueError("authority provider requires an assembled FastAPI application")
        with self._reload_lock:
            with self._state_lock:
                if self._app is not None and self._app is not app:
                    raise ExternalAuthorityProviderError(
                        "authority provider cannot cross application graphs"
                    )
            # Validate every application participant before committing our
            # identity to the graph.  A malformed first graph must leave this
            # verified provider attachable to the actual assembled app.
            self._graph_from_state(state)
            coordinator = state.external_authority_currentness
            self._bind_participant_coordinator(coordinator)
            with self._state_lock:
                self._app = app
            try:
                with coordinator.mutation():
                    try:
                        now = self._clock()
                        with self._state_lock:
                            candidate = self._candidate_snapshot
                        if candidate is None:
                            raise ExternalAuthorityProviderError("authority provider is blocked")
                        receipt = self._reconcile_candidate(candidate, now=now)
                        self._publish_generation(candidate, receipt)
                        state.external_authority_provider = self
                    except Exception as exc:
                        # Currentness users share this mutation boundary.  Do
                        # not release it after participant reconciliation has
                        # failed while an old published generation is live.
                        with self._state_lock:
                            if self._app is app:
                                self._app = None
                            self._block_locked(type(exc).__name__, ticket=None)
                        raise
            except Exception as exc:
                if isinstance(exc, ExternalAuthorityProviderError):
                    raise
                raise ExternalAuthorityProviderError(
                    "authority provider reconciliation failed"
                ) from exc

    def reload_and_reconcile(self, *, now: datetime) -> dict[str, object]:
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("authority reload time must be UTC-aware")
        with self._reload_lock:
            with self._state_lock:
                self._latest_reload_ticket += 1
                ticket = self._latest_reload_ticket
            try:
                replacement = _load(self._config, clock=self._clock, validation_now=now)
            except Exception as exc:
                self._block(type(exc).__name__, ticket=ticket)
                return self._reload_result()
            candidate = replacement._candidate_snapshot
            assert candidate is not None
            with self._state_lock:
                app = self._app
                coordinator = self._participant_coordinator
                if app is None or coordinator is None:
                    self._candidate_snapshot = candidate
                    self._blocked_reason = None
                    self._configured = False
                    return self._reload_result_locked()
            with coordinator.mutation():
                try:
                    receipt = self._reconcile_candidate(candidate, now=now)
                    self._publish_generation(candidate, receipt)
                except Exception:
                    # Publish the failure while this same participant mutation
                    # remains held, so guarded use cannot retain the preceding
                    # receipt-backed generation in between.
                    with self._state_lock:
                        self._block_locked("RECONCILIATION", ticket=ticket)
            return self._reload_result()

    def _graph_from_state(self, state: object) -> tuple[Any, Any, Any, Any, Any]:
        coordinator = getattr(state, "external_authority_currentness", None)
        registry = getattr(state, "external_validation_policy_registry", None)
        inspections = getattr(state, "external_artifact_inspection_store", None)
        evidence_store = getattr(state, "external_evidence_store", None)
        evidence = getattr(state, "external_evidence_validation_store", None)
        catalog = getattr(state, "external_relative_volume_mapping_authority", None)
        if not isinstance(coordinator, ExternalAuthorityCurrentnessCoordinator):
            raise ValueError("authority provider requires the assembled coordinator")
        if (
            registry is None
            or inspections is None
            or evidence_store is None
            or evidence is None
            or catalog is None
            or getattr(registry, "coordinator", None) is not coordinator
            or getattr(registry, "authority_currentness_port", None)
            is not self._policy_currentness_port
            or getattr(inspections, "coordinator", None) is not coordinator
            or getattr(evidence_store, "coordinator", None) is not coordinator
            or getattr(evidence, "coordinator", None) is not coordinator
            or getattr(catalog, "currentness_coordinator", None) is not coordinator
        ):
            raise ValueError("authority provider participants must share the Core coordinator")
        return registry, inspections, evidence_store, evidence, catalog

    def _bind_participant_coordinator(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> None:
        if (
            self._participant_coordinator is not None
            and self._participant_coordinator is not coordinator
        ):
            raise ValueError("authority provider participants cannot cross Core coordinators")
        self._participant_coordinator = coordinator

    def _build_catalog_currentness(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> ExternalQuantitativeCatalogAuthorityCurrentnessPort:
        self._bind_participant_coordinator(coordinator)
        if self._catalog_currentness_port is None:
            self._catalog_currentness_port = _CatalogCurrentness(self, coordinator)
        return self._catalog_currentness_port

    def _build_policy_currentness(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> PolicyAuthorityCurrentnessPort:
        self._bind_participant_coordinator(coordinator)
        if self._policy_currentness_port is None:
            self._policy_currentness_port = _PolicyCurrentness(self, coordinator)
        return self._policy_currentness_port

    def _build_evidence_context(
        self, coordinator: ExternalAuthorityCurrentnessCoordinator
    ) -> EvidenceMeasurementContextAuthorityPort:
        self._bind_participant_coordinator(coordinator)
        if self._evidence_context_port is None:
            self._evidence_context_port = _EvidenceContextPort(self, coordinator)
        return self._evidence_context_port

    def _reconcile_candidate(self, candidate: _VerifiedSnapshot, *, now: datetime) -> _Receipt:
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("authority reconciliation time must be UTC-aware")
        if self._app is None or self._receipt_journal is None:
            raise ExternalAuthorityProviderError("authority provider is not ready to reconcile")
        if any(action.effective_at > now for action in candidate.actions):
            raise ExternalAuthorityProviderError(
                "signed administration action is not yet effective"
            )
        state = getattr(self._app, "state", None)
        if state is None:
            raise ExternalAuthorityProviderError("authority provider lost its application state")
        registry, inspections, evidence_store, evidence, catalog = self._graph_from_state(state)
        self._stage_candidate(candidate)
        try:
            self._validate_history(self._receipts, candidate)
            self._apply_policy_actions(registry, candidate)
            # Policy/context changes become visible to pending sealed records before a
            # later mapping action can admit an eligible pair.
            if (
                not callable(getattr(inspections, "reconcile_sealed", None))
                or not callable(getattr(evidence_store, "sealed_items_snapshot", None))
                or not callable(getattr(evidence, "issue_after_seal", None))
            ):
                raise ExternalAuthorityProviderError(
                    "authority provider graph cannot reconcile sealed work"
                )
            inspections.reconcile_sealed(now)
            for item in evidence_store.sealed_items_snapshot():
                evidence.issue_after_seal(item.evidence_ref, now=now)
            self._apply_mapping_actions(catalog, candidate)
            receipt = next(
                (item for item in self._receipts if item.snapshot_digest == candidate.digest), None
            )
            if receipt is None:
                receipt = _receipt_for(
                    candidate, previous=self._receipts[-1] if self._receipts else None
                )
                try:
                    self._receipt_journal.append(_receipt_event(receipt))
                except Exception as exc:
                    raise ExternalAuthorityProviderError("authority receipt append failed") from exc
                self._receipts = (*self._receipts, receipt)
            self._retain_historical_contexts(candidate.context_records)
            self._retain_historical_policies(candidate.policy_records)
            return receipt
        finally:
            self._clear_staged_candidate()

    def _retain_historical_contexts(
        self, contexts: Mapping[str, ExternalEvidenceMeasurementContextV1]
    ) -> None:
        for digest, context in contexts.items():
            retained = self._historical_contexts.setdefault(digest, context)
            if retained != context:
                raise ExternalAuthorityProviderError("historical evidence context is substituted")

    def _retain_historical_policies(self, policies: Mapping[str, PolicyAuthorityRecord]) -> None:
        for digest, policy in policies.items():
            retained = self._historical_policies.setdefault(digest, policy)
            if retained != policy:
                raise ExternalAuthorityProviderError("historical policy authority is substituted")

    def _apply_policy_actions(self, registry: Any, snapshot: _VerifiedSnapshot) -> None:
        for action in snapshot.actions:
            if action.kind == "ADMIT_POLICY":
                policy = ExternalValidationPolicyV1.model_validate(action.payload["policy"])
                if (
                    policy.synthetic_test_only
                    or policy.policy_digest is None
                    or policy.policy_digest != policy.canonical_digest()
                ):
                    raise ValueError(
                        "signed policy action must carry a sealed non-synthetic policy"
                    )
                receipt = registry.admit(policy, action.actor_id, action.effective_at)
                allowed = {"ADMITTED", "IDEMPOTENT"}
            elif action.kind == "REVOKE_POLICY":
                receipt = registry.revoke(
                    cast(str, action.payload["policyId"]),
                    cast(int, action.payload["policyVersion"]),
                    action.actor_id,
                    action.effective_at,
                )
                allowed = {"REVOKED"}
            elif action.kind == "SUPERSEDE_POLICY":
                receipt = registry.supersede(
                    cast(str, action.payload["policyId"]),
                    cast(int, action.payload["policyVersion"]),
                    cast(str, action.payload["successorPolicyId"]),
                    cast(int, action.payload["successorPolicyVersion"]),
                    action.actor_id,
                    action.effective_at,
                )
                allowed = {"SUPERSEDED"}
            else:
                continue
            status = getattr(getattr(receipt, "status", None), "value", None)
            if status not in allowed and not self._policy_action_effect_retained(registry, action):
                raise ExternalAuthorityProviderError("signed policy action was not applied")

    def _apply_mapping_actions(self, catalog: Any, snapshot: _VerifiedSnapshot) -> None:
        for action in snapshot.actions:
            if action.kind == "ADMIT_MAPPING":
                if action.actor_id != self._config.catalog_administration_actor_id:
                    raise ValueError(
                        "mapping action actor is not the configured catalog administrator"
                    )
                mapping = ExternalQuantitativeCompatibilityRecord.from_event_payload(
                    action.payload["mapping"]
                )
                if (
                    mapping.organization_id != self.organization_id
                    or catalog.admit_mapping(
                        mapping, actor=action.actor_id, now=action.effective_at
                    )
                    is None
                ):
                    raise ExternalAuthorityProviderError("signed mapping admission was not applied")
            elif action.kind == "REVOKE_MAPPING":
                if (
                    action.actor_id != self._config.catalog_administration_actor_id
                    or not catalog.revoke_mapping(
                        cast(str, action.payload["mappingDigest"]),
                        actor=action.actor_id,
                        now=action.effective_at,
                    )
                ):
                    raise ExternalAuthorityProviderError(
                        "signed mapping revocation was not applied"
                    )

    @staticmethod
    def _policy_action_effect_retained(registry: Any, action: _AdministrationAction) -> bool:
        journal = getattr(registry, "_journal", None)
        if not isinstance(journal, DurableJournal):
            return False
        expected_kind = {
            "REVOKE_POLICY": "external-validation-policy-revoked",
            "SUPERSEDE_POLICY": "external-validation-policy-superseded",
        }.get(action.kind)
        if expected_kind is None:
            return False
        occurred_at = action.effective_at.isoformat().replace("+00:00", "Z")
        for event in journal.replay():
            if (
                event.get("kind") == expected_kind
                and event.get("actor") == action.actor_id
                and event.get("occurredAt") == occurred_at
                and event.get("policyId") == action.payload.get("policyId")
                and event.get("policyVersion") == action.payload.get("policyVersion")
                and (
                    action.kind != "SUPERSEDE_POLICY"
                    or (
                        event.get("successorPolicyId") == action.payload.get("successorPolicyId")
                        and event.get("successorPolicyVersion")
                        == action.payload.get("successorPolicyVersion")
                    )
                )
            ):
                return True
        return False

    def _validate_history(
        self, receipts: tuple[_Receipt, ...], snapshot: _VerifiedSnapshot
    ) -> None:
        if not receipts:
            if snapshot.sequence != 1 or snapshot.raw["previousSnapshotDigest"] is not None:
                raise ValueError("initial authority snapshot does not start a new history")
            return
        prior = receipts[-1]
        for receipt in receipts:
            if (
                receipt.key_id == snapshot.key_id
                and receipt.public_key_digest != snapshot.public_key_digest
            ):
                raise ValueError("authority snapshot substitutes pinned key material")
        if snapshot.sequence == prior.sequence:
            if snapshot.digest != prior.snapshot_digest:
                raise ValueError("authority snapshot substitutes retained history")
            return
        if (
            snapshot.sequence != prior.sequence + 1
            or snapshot.raw["previousSnapshotDigest"] != prior.snapshot_digest
        ):
            raise ValueError("authority snapshot does not extend the retained history")

    @staticmethod
    def _snapshot_valid_at(snapshot: _VerifiedSnapshot, now: datetime) -> bool:
        return (
            now.tzinfo is not None
            and now.utcoffset() == UTC.utcoffset(now)
            and snapshot.issued_at <= now < snapshot.valid_until
            and snapshot.key_not_before <= now < snapshot.key_not_after
        )

    def _live_generation(self, now: datetime) -> _AuthorityGeneration | None:
        """Return only the receipt-published generation usable by live ports.

        This method intentionally never reads a pathname.  Explicit reload is
        the sole disk publication boundary; an already-loaded generation stays
        intact until then, while its embedded snapshot/key interval and receipt
        seal are checked on every live use.
        """
        with self._state_lock:
            generation = self._published_generation
            journal = self._receipt_journal
            if (
                generation is None
                or self._blocked_reason is not None
                or not self._configured
                or self._app is None
                or self._participant_coordinator is None
                or journal is None
                or journal.sealed_reason is not None
                or not self._snapshot_valid_at(generation.snapshot, now)
            ):
                return None
            return generation

    def _live_snapshot(
        self, now: datetime, *, permit_staged: bool
    ) -> _VerifiedSnapshot | None:
        """Return the one current live snapshot, or this thread's reconciliation candidate."""
        if permit_staged:
            staged = getattr(self._staged, "candidate", None)
            if isinstance(staged, _VerifiedSnapshot) and self._snapshot_valid_at(staged, now):
                # _reconcile_candidate stages only its own thread while the
                # caller holds the participant coordinator mutation.  A
                # blocked provider must still let that thread resolve a signed
                # corrective candidate; all other threads lack this local
                # value and fall through to the blocked live generation.
                with self._state_lock:
                    journal = self._receipt_journal
                    if (
                        self._participant_coordinator is not None
                        and journal is not None
                        and journal.sealed_reason is None
                    ):
                        return staged
        generation = self._live_generation(now)
        return generation.snapshot if generation is not None else None

    def _configuration_snapshot(self, now: datetime) -> _VerifiedSnapshot | None:
        """Expose a verified candidate only while Core is still closed.

        Catalog construction/replay needs exact signed records before a receipt
        exists.  Its coordinator-bound currentness port still rejects every
        live mutation until this candidate is receipt-published.
        """
        generation = self._live_generation(now)
        if generation is not None:
            return generation.snapshot
        with self._state_lock:
            candidate = self._candidate_snapshot
            if (
                self._app is None
                and self._blocked_reason is None
                and candidate is not None
                and self._snapshot_valid_at(candidate, now)
            ):
                return candidate
            return None

    def _historical_policy(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        if at.tzinfo is None or at.utcoffset() != UTC.utcoffset(at):
            return None
        with self._state_lock:
            record = self._historical_policies.get(authority_record_digest)
            snapshots = (
                self._candidate_snapshot,
                self._published_generation.snapshot
                if self._published_generation is not None
                else None,
            )
        if record is None:
            for snapshot in snapshots:
                if snapshot is not None:
                    candidate = snapshot.policy_records.get(authority_record_digest)
                    if candidate is not None:
                        record = candidate
                        break
        if (
            record is None
            or record.digest != authority_record_digest
            or not record.is_active_at(at)
            or any(
                subject.organization_id != self.organization_id
                for subject in record.permitted_subjects
            )
        ):
            return None
        return record

    def _historical_context(
        self, context_digest: str
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        with self._state_lock:
            context = self._historical_contexts.get(context_digest)
            snapshots = (
                self._candidate_snapshot,
                self._published_generation.snapshot
                if self._published_generation is not None
                else None,
            )
        if context is None:
            for snapshot in snapshots:
                if snapshot is not None:
                    candidate = snapshot.context_records.get(context_digest)
                    if candidate is not None:
                        context = candidate
                        break
        if (
            context is None
            or context.context_digest != context_digest
            or context.subject.organization_id != self.organization_id
        ):
            return None
        return context

    def _stage_candidate(self, candidate: _VerifiedSnapshot) -> None:
        if getattr(self._staged, "candidate", None) is not None:
            raise ExternalAuthorityProviderError("authority reconciliation is already staged")
        self._staged.candidate = candidate

    def _clear_staged_candidate(self) -> None:
        if hasattr(self._staged, "candidate"):
            del self._staged.candidate

    def _publish_generation(self, candidate: _VerifiedSnapshot, receipt: _Receipt) -> None:
        if receipt.snapshot_digest != candidate.digest or receipt.sequence != candidate.sequence:
            raise ExternalAuthorityProviderError("authority receipt does not bind the candidate")
        with self._state_lock:
            self._next_generation += 1
            self._candidate_snapshot = candidate
            self._published_generation = _AuthorityGeneration(
                snapshot=_copy_snapshot(candidate),
                counter=self._next_generation,
                receipt_sequence=receipt.sequence,
                receipt_history_digest=receipt.history_digest,
            )
            self._blocked_reason = None
            self._configured = True

    def _block(self, reason: str, *, ticket: int | None = None) -> None:
        coordinator = self._participant_coordinator
        if coordinator is None:
            with self._state_lock:
                self._block_locked(reason, ticket=ticket)
            return
        with coordinator.mutation(), self._state_lock:
            self._block_locked(reason, ticket=ticket)

    def _block_locked(self, reason: str, *, ticket: int | None) -> None:
        if ticket is not None and ticket != self._latest_reload_ticket:
            return
        self._candidate_snapshot = None
        self._published_generation = None
        self._configured = False
        self._blocked_reason = reason

    def _reload_result(self) -> dict[str, object]:
        with self._state_lock:
            return self._reload_result_locked()

    def _reload_result_locked(self) -> dict[str, object]:
        generation = self._published_generation
        candidate = self._candidate_snapshot
        snapshot = generation.snapshot if generation is not None else candidate
        if self._blocked_reason is not None or snapshot is None:
            return {"status": "BLOCKED", "sequence": None, "snapshotDigest": None}
        return {
            "status": (
                "PROVIDER_CONFIGURED"
                if generation is not None and self._configured
                else "CONFIG_VALIDATED"
            ),
            "sequence": snapshot.sequence,
            "snapshotDigest": snapshot.digest,
        }


def _config_from_path(path: Path) -> _ProviderConfig:
    raw = _exact_mapping(
        _private_json(path, name="authority provider configuration"),
        frozenset(
            {
                "version",
                "organizationId",
                "keyRegistryPath",
                "snapshotPath",
                "catalogAdministrationActorId",
                "leaseTtlSeconds",
                "deadlineAfterIssueSeconds",
                "maxAttempts",
                "maxActiveRequestsPerOrganization",
            }
        ),
        name="authority provider configuration",
    )
    if raw["version"] != _CONFIG_VERSION:
        raise ValueError("unknown authority provider configuration version")

    def _absolute(value: object, *, name: str) -> Path:
        candidate = Path(_text(value, name=name))
        if not candidate.is_absolute():
            raise ValueError(f"{name} must be absolute")
        return candidate

    numeric_fields = (
        "leaseTtlSeconds",
        "deadlineAfterIssueSeconds",
        "maxAttempts",
        "maxActiveRequestsPerOrganization",
    )
    if any(type(raw[field]) is not int for field in numeric_fields):
        raise ValueError("authority provider queue values must be integers")
    return _ProviderConfig(
        organization_id=_text(raw["organizationId"], name="organizationId"),
        key_registry_path=_absolute(raw["keyRegistryPath"], name="keyRegistryPath"),
        snapshot_path=_absolute(raw["snapshotPath"], name="snapshotPath"),
        catalog_administration_actor_id=_text(
            raw["catalogAdministrationActorId"], name="catalogAdministrationActorId"
        ),
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=cast(int, raw["leaseTtlSeconds"])),
            deadline_after_issue=timedelta(seconds=cast(int, raw["deadlineAfterIssueSeconds"])),
            max_attempts=cast(int, raw["maxAttempts"]),
            max_active_requests_per_organization=cast(int, raw["maxActiveRequestsPerOrganization"]),
        ),
    )


def _active_key(
    registry_path: Path, snapshot_key_id: str, now: datetime
) -> _ActiveKey:
    raw = _exact_mapping(
        _private_json(registry_path, name="authority key registry"),
        frozenset({"version", "keys"}),
        name="authority key registry",
    )
    if (
        raw["version"] != _REGISTRY_VERSION
        or not isinstance(raw["keys"], list)
        or not raw["keys"]
        or len(raw["keys"]) > _MAX_REGISTRY_KEYS
    ):
        raise ValueError("authority key registry is malformed")
    matching: list[dict[str, object]] = []
    for item in raw["keys"]:
        key = _exact_mapping(
            item,
            frozenset(
                {
                    "keyId",
                    "role",
                    "algorithm",
                    "status",
                    "publicKeyFile",
                    "notBefore",
                    "notAfter",
                }
            ),
            name="authority key",
        )
        if _text(key["keyId"], name="keyId") == snapshot_key_id:
            matching.append(key)
    if len(matching) != 1:
        raise ValueError("authority snapshot key is ambiguous or absent")
    key = matching[0]
    if (
        key["role"] != "AUTHORITY_BUNDLE"
        or key["algorithm"] != "Ed25519"
        or key["status"] != "ACTIVE"
    ):
        raise ValueError("authority snapshot key is not active for authority bundles")
    not_before = _utc(key["notBefore"], name="key notBefore")
    not_after = _utc(key["notAfter"], name="key notAfter")
    if not_before >= not_after or not not_before <= now < not_after:
        raise ValueError("authority snapshot key is outside its validity interval")
    key_path = _safe_child(registry_path.parent, key["publicKeyFile"], name="publicKeyFile")
    try:
        material = _protected_bytes(
            key_path, name="authority public key", maximum=16_384, private=False,
        )
        loaded = serialization.load_pem_public_key(material)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("authority public key cannot be loaded") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("authority public key must be Ed25519")
    return _ActiveKey(
        public_key=loaded,
        public_key_digest=_sha256_bytes(material),
        not_before=not_before,
        not_after=not_after,
    )


def _snapshot_from_path(
    config: _ProviderConfig, *, clock: Callable[[], datetime]
) -> _VerifiedSnapshot:
    raw = _exact_mapping(
        _private_json(config.snapshot_path, name="authority snapshot"),
        _SNAPSHOT_UNSIGNED_FIELDS | {"signature"},
        name="authority snapshot",
    )
    if raw["version"] != _SNAPSHOT_VERSION:
        raise ValueError("unknown authority snapshot version")
    organization_id = _text(raw["organizationId"], name="snapshot organizationId")
    if organization_id != config.organization_id:
        raise ValueError("authority snapshot organization does not match configuration")
    if type(raw["sequence"]) is not int or raw["sequence"] < 1:
        raise ValueError("authority snapshot sequence must be positive")
    if raw["previousSnapshotDigest"] is not None and (
        not isinstance(raw["previousSnapshotDigest"], str)
        or _DIGEST.fullmatch(raw["previousSnapshotDigest"]) is None
    ):
        raise ValueError("authority snapshot previous digest is malformed")
    issued_at = _utc(raw["issuedAt"], name="snapshot issuedAt")
    valid_until = _utc(raw["validUntil"], name="snapshot validUntil")
    now = clock()
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError("authority provider clock must return UTC time")
    if issued_at >= valid_until or not issued_at <= now < valid_until:
        raise ValueError("authority snapshot is outside its validity interval")
    key_id = _text(raw["keyId"], name="snapshot keyId")
    active_key = _active_key(config.key_registry_path, key_id, now)
    signature_value = raw["signature"]
    if not isinstance(signature_value, str):
        raise ValueError("authority snapshot signature must be base64 text")
    try:
        signature = base64.b64decode(signature_value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("authority snapshot signature is malformed") from exc
    unsigned = {key: value for key, value in raw.items() if key != "signature"}
    signed = canonical_json_bytes({"domain": _SNAPSHOT_DOMAIN, "snapshot": unsigned})
    try:
        active_key.public_key.verify(signature, signed)
    except InvalidSignature as exc:
        raise ValueError("authority snapshot signature is invalid") from exc
    catalog_records, current_catalog_digests = _authority_collection(
        raw["catalogAuthorities"],
        parser=ExternalQuantitativeCatalogAuthorityRecord.from_event_payload,
        digest=lambda record: record.digest,
        name="catalog authorities",
    )
    for catalog_record in catalog_records.values():
        if catalog_record.organization_id != organization_id or catalog_record.synthetic_test_only:
            raise ValueError(
                "catalog authority record has an invalid organization or synthetic flag"
            )
    policy_records, current_policy_digests = _authority_collection(
        raw["policyAuthorities"],
        parser=PolicyAuthorityRecord.from_event_payload,
        digest=lambda record: record.digest,
        name="policy authorities",
    )
    for policy_record in policy_records.values():
        if policy_record.synthetic_test_only or any(
            subject.organization_id != organization_id
            for subject in policy_record.permitted_subjects
        ):
            raise ValueError(
                "policy authority record has an invalid organization or synthetic flag"
            )
    context_records, current_context_digests = _authority_collection(
        raw["evidenceContexts"],
        parser=_context_from_snapshot_payload,
        digest=lambda record: record.context_digest,
        name="evidence contexts",
    )
    for context in context_records.values():
        if context.synthetic_test_only or context.subject.organization_id != organization_id:
            raise ValueError("evidence context has an invalid organization or synthetic flag")
    actions = _administration_actions(
        raw["quantitativeAdministration"], issued_at=issued_at, valid_until=valid_until
    )
    for action in actions:
        if action.kind != "ADMIT_POLICY":
            continue
        policy = ExternalValidationPolicyV1.model_validate(action.payload["policy"])
        if policy.authority_record_digest is None:
            raise ValueError("signed policy admission omits its authority record")
        authority = policy_records.get(policy.authority_record_digest)
        if (
            policy.model_dump(by_alias=True, mode="json") != action.payload["policy"]
            or policy.synthetic_test_only
            or policy.status.value != "ACTIVE"
            or policy.policy_digest is None
            or policy.policy_digest != policy.canonical_digest()
            or policy.authority_record_digest not in current_policy_digests
            or authority is None
            or not authority.authorizes_admission(
                policy, actor=action.actor_id, now=action.effective_at,
            )
        ):
            raise ValueError("signed policy admission is not exactly sealed and authorized")
    return _VerifiedSnapshot(
        organization_id=organization_id,
        sequence=raw["sequence"],
        digest=_sha256_bytes(signed),
        issued_at=issued_at,
        valid_until=valid_until,
        key_id=key_id,
        public_key_digest=active_key.public_key_digest,
        key_not_before=active_key.not_before,
        key_not_after=active_key.not_after,
        raw=cast(dict[str, object], json.loads(canonical_json_bytes(unsigned))),
        catalog_records=catalog_records,
        current_catalog_digests=current_catalog_digests,
        policy_records=policy_records,
        current_policy_digests=current_policy_digests,
        context_records=context_records,
        current_context_digests=current_context_digests,
        actions=actions,
    )


def _authority_collection[AuthorityRecord](
    raw: object,
    *,
    parser: Callable[[object], AuthorityRecord],
    digest: Callable[[AuthorityRecord], str | None],
    name: str,
) -> tuple[dict[str, AuthorityRecord], frozenset[str]]:
    collection = _exact_mapping(raw, frozenset({"records", "currentDigests"}), name=name)
    records_raw = collection["records"]
    current_raw = collection["currentDigests"]
    if (
        not isinstance(records_raw, list)
        or not isinstance(current_raw, list)
        or len(records_raw) > _MAX_COLLECTION_RECORDS
        or len(current_raw) > _MAX_COLLECTION_RECORDS
        or not all(type(value) is str for value in current_raw)
    ):
        raise ValueError(f"{name} has invalid records or current digests")
    if len(set(current_raw)) != len(current_raw):
        raise ValueError(f"{name} has duplicate current digests")
    records: dict[str, AuthorityRecord] = {}
    for raw_record in records_raw:
        record = parser(raw_record)
        record_digest = digest(record)
        if not isinstance(record_digest, str) or record_digest in records:
            raise ValueError(f"{name} has duplicate or unsealed record identities")
        records[record_digest] = record
    if not set(current_raw).issubset(records):
        raise ValueError(f"{name} current digest is not retained")
    return records, frozenset(cast(list[str], current_raw))


def _context_from_snapshot_payload(raw: object) -> ExternalEvidenceMeasurementContextV1:
    context = ExternalEvidenceMeasurementContextV1.model_validate(raw)
    if (
        context.context_digest is None
        or context.context_digest != context.canonical_digest()
        or context.synthetic_test_only
    ):
        raise ValueError("evidence context must be exact, sealed, and non-synthetic")
    attestation = context.independent_attestation
    if attestation is not None and (
        attestation.attestation_digest is None
        or attestation.attestation_digest != attestation.canonical_digest()
        or attestation.synthetic_test_only
    ):
        raise ValueError("evidence context attestation must be exact, sealed, and non-synthetic")
    return context


def _administration_actions(
    raw: object, *, issued_at: datetime, valid_until: datetime
) -> tuple[_AdministrationAction, ...]:
    administration = _exact_mapping(raw, frozenset({"actions"}), name="quantitative administration")
    raw_actions = administration["actions"]
    if not isinstance(raw_actions, list) or len(raw_actions) > _MAX_ADMINISTRATION_ACTIONS:
        raise ValueError("quantitative administration actions must be a list")
    actions: list[_AdministrationAction] = []
    seen_ids: set[str] = set()
    previous_at: datetime | None = None
    ranks = {
        "ADMIT_POLICY": 0,
        "REVOKE_POLICY": 0,
        "SUPERSEDE_POLICY": 0,
        "ADMIT_MAPPING": 1,
        "REVOKE_MAPPING": 1,
    }
    prior_rank = -1
    for raw_action in raw_actions:
        if type(raw_action) is not dict or raw_action.get("kind") not in ranks:
            raise ValueError("quantitative administration action is unsupported")
        kind = cast(str, raw_action["kind"])
        required = {"actionId", "kind", "effectiveAt", "actorId"}
        if kind == "ADMIT_POLICY":
            required.add("policy")
        elif kind == "REVOKE_POLICY":
            required.update({"policyId", "policyVersion"})
        elif kind == "SUPERSEDE_POLICY":
            required.update(
                {"policyId", "policyVersion", "successorPolicyId", "successorPolicyVersion"}
            )
        elif kind == "ADMIT_MAPPING":
            required.add("mapping")
        else:
            required.add("mappingDigest")
        action = _exact_mapping(
            raw_action, frozenset(required), name="quantitative administration action"
        )
        action_id = _text(action["actionId"], name="actionId")
        if action_id in seen_ids:
            raise ValueError("quantitative administration action has a duplicate id")
        effective_at = _utc(action["effectiveAt"], name="action effectiveAt")
        if (
            effective_at < issued_at
            or effective_at >= valid_until
            or (previous_at is not None and effective_at < previous_at)
            or ranks[kind] < prior_rank
        ):
            raise ValueError("quantitative administration action order is invalid")
        if kind in {"REVOKE_POLICY", "SUPERSEDE_POLICY"}:
            for field in ("policyId",):
                _text(action[field], name=field)
            if type(action["policyVersion"]) is not int or isinstance(
                action["policyVersion"], bool
            ):
                raise ValueError("policyVersion must be an integer")
            if kind == "SUPERSEDE_POLICY":
                _text(action["successorPolicyId"], name="successorPolicyId")
                if type(action["successorPolicyVersion"]) is not int or isinstance(
                    action["successorPolicyVersion"], bool
                ):
                    raise ValueError("successorPolicyVersion must be an integer")
        elif kind == "REVOKE_MAPPING" and (
            not isinstance(action["mappingDigest"], str)
            or _DIGEST.fullmatch(action["mappingDigest"]) is None
        ):
            raise ValueError("mappingDigest must be a sha256 digest")
        elif kind == "ADMIT_MAPPING":
            ExternalQuantitativeCompatibilityRecord.from_event_payload(action["mapping"])
        seen_ids.add(action_id)
        previous_at = effective_at
        prior_rank = ranks[kind]
        actions.append(
            _AdministrationAction(
                action_id=action_id,
                kind=kind,
                effective_at=effective_at,
                actor_id=_text(action["actorId"], name="action actorId"),
                payload={
                    key: value
                    for key, value in action.items()
                    if key not in {"actionId", "kind", "effectiveAt", "actorId"}
                },
            )
        )
    return tuple(actions)


def _event_digest(event: Mapping[str, object]) -> str:
    return _sha256_bytes(
        canonical_json_bytes({key: value for key, value in event.items() if key != "eventDigest"})
    )


def _history_digest(
    *,
    sequence: int,
    snapshot_digest: str,
    previous_snapshot_digest: str | None,
    key_id: str,
    public_key_digest: str,
    previous_history_digest: str | None,
) -> str:
    return _sha256_bytes(
        canonical_json_bytes(
            {
                "domain": "ksi.external-authority-provider-history.v1",
                "sequence": sequence,
                "snapshotDigest": snapshot_digest,
                "previousSnapshotDigest": previous_snapshot_digest,
                "keyId": key_id,
                "publicKeyDigest": public_key_digest,
                "previousHistoryDigest": previous_history_digest,
            }
        )
    )


def _receipt_for(snapshot: _VerifiedSnapshot, *, previous: _Receipt | None) -> _Receipt:
    previous_history_digest = previous.history_digest if previous is not None else None
    return _Receipt(
        sequence=snapshot.sequence,
        snapshot_digest=snapshot.digest,
        previous_snapshot_digest=cast(str | None, snapshot.raw["previousSnapshotDigest"]),
        key_id=snapshot.key_id,
        public_key_digest=snapshot.public_key_digest,
        history_digest=_history_digest(
            sequence=snapshot.sequence,
            snapshot_digest=snapshot.digest,
            previous_snapshot_digest=cast(str | None, snapshot.raw["previousSnapshotDigest"]),
            key_id=snapshot.key_id,
            public_key_digest=snapshot.public_key_digest,
            previous_history_digest=previous_history_digest,
        ),
        snapshot=snapshot.raw,
    )


def _receipt_event(receipt: _Receipt) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": _RECEIPT_KIND,
        "version": _RECEIPT_VERSION,
        "sequence": receipt.sequence,
        "snapshotDigest": receipt.snapshot_digest,
        "previousSnapshotDigest": receipt.previous_snapshot_digest,
        "keyId": receipt.key_id,
        "publicKeyDigest": receipt.public_key_digest,
        "historyDigest": receipt.history_digest,
        "snapshot": receipt.snapshot,
    }
    event["eventDigest"] = _event_digest(event)
    return event


def _replay_receipts(journal: DurableJournal) -> tuple[_Receipt, ...]:
    receipts: list[_Receipt] = []
    pinned_material: dict[str, str] = {}
    for raw in journal.replay():
        event = _exact_mapping(
            raw,
            frozenset(
                {
                    "kind",
                    "version",
                    "sequence",
                    "snapshotDigest",
                    "previousSnapshotDigest",
                    "keyId",
                    "publicKeyDigest",
                    "historyDigest",
                    "snapshot",
                    "eventDigest",
                }
            ),
            name="authority provider receipt",
        )
        if event["kind"] != _RECEIPT_KIND or event["version"] != _RECEIPT_VERSION:
            raise ValueError("unknown authority provider receipt")
        if type(event["sequence"]) is not int or event["sequence"] < 1:
            raise ValueError("authority receipt sequence is malformed")
        if not all(
            type(event[field]) is str
            for field in (
                "snapshotDigest",
                "keyId",
                "publicKeyDigest",
                "historyDigest",
                "eventDigest",
            )
        ) or (
            event["previousSnapshotDigest"] is not None
            and type(event["previousSnapshotDigest"]) is not str
        ):
            raise ValueError("authority receipt strings are malformed")
        if type(event["snapshot"]) is not dict or event["eventDigest"] != _event_digest(event):
            raise ValueError("authority receipt is malformed or tampered")
        snapshot = cast(dict[str, object], event["snapshot"])
        expected_snapshot_digest = _sha256_bytes(
            canonical_json_bytes({"domain": _SNAPSHOT_DOMAIN, "snapshot": snapshot})
        )
        if event["snapshotDigest"] != expected_snapshot_digest:
            raise ValueError("authority receipt snapshot digest is substituted")
        previous = receipts[-1] if receipts else None
        if (
            previous is None
            and (event["sequence"] != 1 or event["previousSnapshotDigest"] is not None)
        ) or (
            previous is not None
            and (
                event["sequence"] != previous.sequence + 1
                or event["previousSnapshotDigest"] != previous.snapshot_digest
            )
        ):
            raise ValueError("authority receipt sequence has a gap or rollback")
        key_id = cast(str, event["keyId"])
        material = cast(str, event["publicKeyDigest"])
        if key_id in pinned_material and pinned_material[key_id] != material:
            raise ValueError("authority receipt key identity is substituted")
        pinned_material[key_id] = material
        expected_history_digest = _history_digest(
            sequence=event["sequence"],
            snapshot_digest=event["snapshotDigest"],
            previous_snapshot_digest=event["previousSnapshotDigest"],
            key_id=key_id,
            public_key_digest=material,
            previous_history_digest=previous.history_digest if previous is not None else None,
        )
        if event["historyDigest"] != expected_history_digest:
            raise ValueError("authority receipt history digest is substituted")
        receipts.append(
            _Receipt(
                sequence=event["sequence"],
                snapshot_digest=event["snapshotDigest"],
                previous_snapshot_digest=event["previousSnapshotDigest"],
                key_id=key_id,
                public_key_digest=material,
                history_digest=event["historyDigest"],
                snapshot=snapshot,
            )
        )
    return tuple(receipts)


def _historical_contexts_from_receipts(
    receipts: tuple[_Receipt, ...], *, organization_id: str
) -> dict[str, ExternalEvidenceMeasurementContextV1]:
    retained: dict[str, ExternalEvidenceMeasurementContextV1] = {}
    for receipt in receipts:
        snapshot = _exact_mapping(
            receipt.snapshot, _SNAPSHOT_UNSIGNED_FIELDS, name="authority receipt snapshot"
        )
        if (
            snapshot["version"] != _SNAPSHOT_VERSION
            or _text(snapshot["organizationId"], name="receipt snapshot organizationId")
            != organization_id
            or snapshot["sequence"] != receipt.sequence
            or snapshot["previousSnapshotDigest"] != receipt.previous_snapshot_digest
            or snapshot["keyId"] != receipt.key_id
        ):
            raise ValueError("authority receipt snapshot identity is substituted")
        contexts, _current = _authority_collection(
            snapshot["evidenceContexts"],
            parser=_context_from_snapshot_payload,
            digest=lambda context: context.context_digest,
            name="receipt evidence contexts",
        )
        for digest, context in contexts.items():
            if context.subject.organization_id != organization_id:
                raise ValueError("receipt evidence context has the wrong organization")
            existing = retained.setdefault(digest, context)
            if existing != context:
                raise ValueError("receipt evidence context is substituted")
    return retained


def _historical_policies_from_receipts(
    receipts: tuple[_Receipt, ...], *, organization_id: str
) -> dict[str, PolicyAuthorityRecord]:
    """Retain exact signed policy records for journal replay only.

    In particular this does not inspect ``currentDigests`` or a candidate
    snapshot's current key/window.  A replay event is verified at its own
    recorded Core time through ``resolve_historical``.
    """
    retained: dict[str, PolicyAuthorityRecord] = {}
    for receipt in receipts:
        snapshot = _exact_mapping(
            receipt.snapshot, _SNAPSHOT_UNSIGNED_FIELDS, name="authority receipt snapshot"
        )
        if (
            snapshot["version"] != _SNAPSHOT_VERSION
            or _text(snapshot["organizationId"], name="receipt snapshot organizationId")
            != organization_id
            or snapshot["sequence"] != receipt.sequence
            or snapshot["previousSnapshotDigest"] != receipt.previous_snapshot_digest
            or snapshot["keyId"] != receipt.key_id
        ):
            raise ValueError("authority receipt snapshot identity is substituted")
        policies, _current = _authority_collection(
            snapshot["policyAuthorities"],
            parser=PolicyAuthorityRecord.from_event_payload,
            digest=lambda policy: policy.digest,
            name="receipt policy authorities",
        )
        for digest, policy in policies.items():
            if policy.synthetic_test_only or any(
                subject.organization_id != organization_id
                for subject in policy.permitted_subjects
            ):
                raise ValueError("receipt policy authority is invalid")
            existing = retained.setdefault(digest, policy)
            if existing != policy:
                raise ValueError("receipt policy authority is substituted")
    return retained


def _load(
    config: _ProviderConfig,
    *,
    clock: Callable[[], datetime],
    validation_now: datetime | None = None,
) -> ExternalAuthorityProvider:
    validation_clock = clock if validation_now is None else lambda: validation_now
    return ExternalAuthorityProvider(
        config,
        _snapshot_from_path(config, clock=validation_clock),
        clock=clock,
    )


def load_external_authority_provider(
    path: Path, *, clock: Callable[[], datetime]
) -> ExternalAuthorityProvider:
    """Verify file-backed authority inputs without opening a receipt journal."""
    if not callable(clock):
        raise ValueError("authority provider requires a clock")
    try:
        return _load(_config_from_path(path), clock=clock)
    except (OSError, ValueError, TypeError) as exc:
        raise ExternalAuthorityProviderError("external authority provider is blocked") from exc


__all__ = [
    "ExternalAuthorityProvider",
    "ExternalAuthorityProviderError",
    "load_external_authority_provider",
]
