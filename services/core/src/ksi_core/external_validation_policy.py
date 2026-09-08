"""Append-only Core registry for externally validated artifact policies.

The registry deliberately does not supply a policy.  An active contract snapshot
becomes selectable only after an injected authority port resolves its exact,
currently active authority record.  The port is the trust boundary: a digest is
an identifier, never proof by itself.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    SealedExternalSubjectV1,
)
from pydantic import ValidationError

from ksi_core.durable_journal import DurableJournal

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_WIRE_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)
_EVENT_VERSION = 1
_ADMITTED_KIND = "external-validation-policy-admitted"
_REVOKED_KIND = "external-validation-policy-revoked"
_SUPERSEDED_KIND = "external-validation-policy-superseded"
_POLICY_BODY_DOMAIN = "ksi.external-validation-policy-authority-body.v1"
_AUTHORITY_RECORD_DOMAIN = "ksi.external-validation-policy-authority-record.v1"
_PERMITTED_USES = frozenset(
    {"INSPECTION", "DISPLAY", "HEIGHT", "VISUAL_COMPARISON", "RELATIVE_VOLUME"}
)


class ExternalValidationPolicyConflictError(ValueError):
    """An admitted policy identity/version was submitted with another body."""


class ExternalValidationPolicyRecoveryError(RuntimeError):
    """A policy lifecycle journal event cannot be trusted during replay."""


class PolicySelectionStatus(StrEnum):
    """Current lifecycle state or a typed fail-closed selection result."""

    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    INSPECTION_PENDING_POLICY = "INSPECTION_PENDING_POLICY"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    POLICY_AMBIGUOUS = "POLICY_AMBIGUOUS"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"


class PolicyReceiptStatus(StrEnum):
    """Outcome of a registry lifecycle mutation; no client policy activation exists."""

    ADMITTED = "ADMITTED"
    IDEMPOTENT = "IDEMPOTENT"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    POLICY_AUTHORITY_UNRESOLVED = "POLICY_AUTHORITY_UNRESOLVED"


@dataclass(frozen=True)
class PolicySelection:
    status: PolicySelectionStatus
    policy: ExternalValidationPolicyV1 | None
    reason: str | None


@dataclass(frozen=True)
class PolicyReceipt:
    policy_id: str
    version: int
    policy_digest: str | None
    status: PolicyReceiptStatus


@dataclass(frozen=True)
class PolicyAuthorityRecord:
    """Trusted authority data returned only by :class:`PolicyAuthorityPort`.

    ``permitted_subjects`` is intentionally an exact sealed-subject allowlist.
    It prevents a policy approval for one revision from becoming a site-wide or
    tenant-wide approval by label, hash, or an inferred latest revision.
    """

    policy_id: str
    policy_version: int
    authorized_policy_body_digest: str
    permitted_subjects: tuple[SealedExternalSubjectV1, ...]
    permitted_uses: tuple[str, ...]
    authorized_actor_ids: tuple[str, ...]
    active_from: datetime
    active_until: datetime
    synthetic_test_only: bool
    digest: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id or self.policy_id != self.policy_id.strip():
            raise ValueError("authority record policy_id must be non-empty and trimmed")
        if (
            not isinstance(self.policy_version, int)
            or isinstance(self.policy_version, bool)
            or self.policy_version < 1
        ):
            raise ValueError("authority record policy_version must be positive")
        if _DIGEST_RE.fullmatch(self.authorized_policy_body_digest) is None:
            raise ValueError("authority record authorized policy body digest is malformed")
        _require_utc(self.active_from, "authority active_from")
        _require_utc(self.active_until, "authority active_until")
        if self.active_from >= self.active_until:
            raise ValueError("authority record active interval must be non-empty")
        if not self.permitted_subjects:
            raise ValueError("authority record requires an exact permitted subject")
        subject_digests = tuple(subject.canonical_digest() for subject in self.permitted_subjects)
        if len(subject_digests) != len(set(subject_digests)):
            raise ValueError("authority record permitted subjects must be unique")
        _require_nonempty_unique(self.permitted_uses, "authority record permitted uses")
        for use in self.permitted_uses:
            _require_use(use)
        _require_nonempty_unique(self.authorized_actor_ids, "authority record actor ids")
        if self.digest is not None and (
            _DIGEST_RE.fullmatch(self.digest) is None
            or self.digest != self.canonical_digest()
        ):
            raise ValueError("authority record digest does not match canonical authority content")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "authorizedPolicyBodyDigest": self.authorized_policy_body_digest,
            "permittedSubjects": [
                subject.canonical_payload() for subject in self.permitted_subjects
            ],
            "permittedUses": list(self.permitted_uses),
            "authorizedActorIds": list(self.authorized_actor_ids),
            "activeFrom": _wire_time(self.active_from),
            "activeUntil": _wire_time(self.active_until),
            "syntheticTestOnly": self.synthetic_test_only,
        }

    def canonical_digest(self) -> str:
        return _canonical_digest(
            {"domain": _AUTHORITY_RECORD_DOMAIN, "authority": self.canonical_payload()}
        )

    def sealed(self) -> PolicyAuthorityRecord:
        if self.digest is not None and self.digest != self.canonical_digest():
            raise ValueError("authority record digest does not match canonical authority content")
        return replace(self, digest=self.canonical_digest())

    def is_sealed(self) -> bool:
        return self.digest is not None and self.digest == self.canonical_digest()

    def is_active_at(self, now: datetime) -> bool:
        _require_utc(now, "authority lookup time")
        return self.active_from <= now < self.active_until

    def authorizes_admission(
        self, policy: ExternalValidationPolicyV1, *, actor: str, now: datetime
    ) -> bool:
        return (
            self.is_sealed()
            and self.is_active_at(now)
            and actor in self.authorized_actor_ids
            and self.policy_id == policy.policy_id
            and self.policy_version == policy.version
            and self.authorized_policy_body_digest == authorized_policy_body_digest(policy)
            and self.synthetic_test_only == policy.synthetic_test_only
        )

    def permits_selection(
        self,
        policy: ExternalValidationPolicyV1,
        *,
        use: str,
        subjects: Sequence[SealedExternalSubjectV1],
        now: datetime,
    ) -> bool:
        requested_subjects = tuple(subject.canonical_digest() for subject in subjects)
        permitted_subjects = tuple(
            subject.canonical_digest() for subject in self.permitted_subjects
        )
        if use in {"INSPECTION", "DISPLAY", "HEIGHT"}:
            subject_scope_matches = (
                len(requested_subjects) == 1 and requested_subjects[0] in permitted_subjects
            )
        else:
            subject_scope_matches = requested_subjects == permitted_subjects
        return (
            self.is_sealed()
            and self.is_active_at(now)
            and self.policy_id == policy.policy_id
            and self.policy_version == policy.version
            and self.authorized_policy_body_digest == authorized_policy_body_digest(policy)
            and self.synthetic_test_only == policy.synthetic_test_only
            and use in self.permitted_uses
            and subject_scope_matches
        )

    def event_payload(self) -> dict[str, object]:
        """Exact authority snapshot persisted with an admission event for replay."""
        if not self.is_sealed() or self.digest is None:
            raise ValueError("authority record must be sealed before event persistence")
        return {"digest": self.digest, **self.canonical_payload()}

    @classmethod
    def from_event_payload(cls, raw: object) -> PolicyAuthorityRecord:
        payload = _exact_mapping(
            raw,
            {
                "digest",
                "policyId",
                "policyVersion",
                "authorizedPolicyBodyDigest",
                "permittedSubjects",
                "permittedUses",
                "authorizedActorIds",
                "activeFrom",
                "activeUntil",
                "syntheticTestOnly",
            },
            context="authority record",
        )
        subjects_raw = payload["permittedSubjects"]
        if not isinstance(subjects_raw, list):
            raise ValueError("authority record permittedSubjects must be a list")
        uses_raw = payload["permittedUses"]
        actors_raw = payload["authorizedActorIds"]
        if not isinstance(uses_raw, list) or not all(isinstance(item, str) for item in uses_raw):
            raise ValueError("authority record permittedUses must be a string list")
        if not isinstance(actors_raw, list) or not all(
            isinstance(item, str) for item in actors_raw
        ):
            raise ValueError("authority record authorizedActorIds must be a string list")
        if not isinstance(payload["digest"], str):
            raise ValueError("authority record digest must be a string")
        if (
            not isinstance(payload["policyId"], str)
            or not isinstance(payload["policyVersion"], int)
            or isinstance(payload["policyVersion"], bool)
        ):
            raise ValueError("authority record policy identity is malformed")
        if not isinstance(payload["authorizedPolicyBodyDigest"], str):
            raise ValueError("authority record authorizedPolicyBodyDigest must be a string")
        if not isinstance(payload["activeFrom"], str) or not isinstance(
            payload["activeUntil"], str
        ):
            raise ValueError("authority record active interval is malformed")
        if not isinstance(payload["syntheticTestOnly"], bool):
            raise ValueError("authority record syntheticTestOnly must be a bool")
        return cls(
            policy_id=payload["policyId"],
            policy_version=payload["policyVersion"],
            authorized_policy_body_digest=payload["authorizedPolicyBodyDigest"],
            permitted_subjects=tuple(
                SealedExternalSubjectV1.model_validate(subject) for subject in subjects_raw
            ),
            permitted_uses=tuple(uses_raw),
            authorized_actor_ids=tuple(actors_raw),
            active_from=_parse_wire_time(payload["activeFrom"], "authority activeFrom"),
            active_until=_parse_wire_time(payload["activeUntil"], "authority activeUntil"),
            synthetic_test_only=payload["syntheticTestOnly"],
            digest=payload["digest"],
        )


class PolicyAuthorityPort(Protocol):
    """The only source of authority records; no digest-only fallback is valid."""

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        """Return a currently readable authority record, or ``None`` fail-closed."""


class _NoPolicyAuthorityPort:
    """Production-safe default until an authorized authority path is assembled."""

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del authority_record_digest, now
        return None


@dataclass
class _PolicyEntry:
    policy: ExternalValidationPolicyV1
    authority: PolicyAuthorityRecord
    status: PolicyStatus


class ExternalValidationPolicyRegistry:
    """Durable policy lifecycle with immutable snapshots and current selection.

    The registry owns no administration route.  Its ``actor`` parameters are
    authenticated Core actor identities supplied by a future controlled policy
    authority path; the injected authority port validates their authorization.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        authority_port: PolicyAuthorityPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal = journal
        self._authority_port = authority_port or _NoPolicyAuthorityPort()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._entries_by_identity: dict[tuple[str, int], _PolicyEntry] = {}
        self._entries_by_digest: dict[str, _PolicyEntry] = {}
        try:
            self._replay(journal)
        except BaseException:
            journal.close()
            raise

    def select_for_inspection(self, subject: SealedExternalSubjectV1) -> PolicySelection:
        """Select exactly one currently authorized inspection policy, or show pending."""
        selection = self._select("INSPECTION", (subject,))
        if selection.status is PolicySelectionStatus.POLICY_UNAVAILABLE:
            return PolicySelection(
                status=PolicySelectionStatus.INSPECTION_PENDING_POLICY,
                policy=None,
                reason="NO_ACTIVE_POLICY",
            )
        return selection

    def select_for_use(
        self, use: str, subjects: Sequence[SealedExternalSubjectV1]
    ) -> PolicySelection:
        """Select exactly one currently-authorized policy for the exact requested subjects."""
        _require_use(use)
        if _selection_arity_reason(use, subjects) is not None:
            return PolicySelection(
                status=PolicySelectionStatus.POLICY_UNAVAILABLE,
                policy=None,
                reason="SUBJECT_ARITY_INVALID",
            )
        return self._select(use, tuple(subjects))

    def resolve(self, policy_digest: str) -> PolicySelection:
        """Resolve retained history without treating it as selectable current policy."""
        with self._lock:
            entry = self._entries_by_digest.get(policy_digest)
            if entry is None:
                return PolicySelection(
                    status=PolicySelectionStatus.POLICY_NOT_FOUND,
                    policy=None,
                    reason="POLICY_NOT_FOUND",
                )
            return PolicySelection(
                status=PolicySelectionStatus(entry.status.value),
                policy=entry.policy.model_copy(deep=True),
                reason=None,
            )

    def historical_use_permitted(
        self,
        policy_digest: str,
        *,
        use: str,
        subjects: Sequence[SealedExternalSubjectV1],
        at: datetime,
    ) -> bool:
        """Read one immutable policy/authority capability at an event's Core time.

        This is evidence derivation only.  It deliberately ignores mutable
        registry lifecycle state, current authority-port availability, and all
        other policies; callers must continue to use ``select_for_use`` for
        every current execution authorization.
        """
        _require_use(use)
        _require_utc(at, "historical use time")
        if _selection_arity_reason(use, subjects) is not None:
            return False
        with self._lock:
            entry = self._entries_by_digest.get(policy_digest)
            if entry is None:
                return False
            policy, authority = entry.policy, entry.authority
            authority_digest = policy.authority_record_digest
            return (
                _policy_digest(policy) == policy_digest
                and authority_digest is not None
                and authority.digest == authority_digest
                and authority.permits_selection(policy, use=use, subjects=subjects, now=at)
            )

    def admit(
        self, policy: ExternalValidationPolicyV1, actor: str, now: datetime
    ) -> PolicyReceipt:
        """Append a new authority-validated immutable policy snapshot before publishing it."""
        _require_actor(actor)
        _require_utc(now, "admission time")
        sealed = _seal_policy(policy)
        with self._lock:
            authority = self._resolve_administration_authority(sealed, actor=actor, now=now)
            if authority is None:
                return _receipt(sealed, PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED)
            key = (sealed.policy_id, sealed.version)
            existing = self._entries_by_identity.get(key)
            if existing is not None:
                if existing.policy.policy_digest == sealed.policy_digest:
                    return _receipt(sealed, PolicyReceiptStatus.IDEMPOTENT)
                raise ExternalValidationPolicyConflictError(
                    f"external validation policy conflict: {sealed.policy_id}@{sealed.version}"
                )
            self._journal.append(self._admitted_event(sealed, authority, actor=actor, now=now))
            self._publish(sealed, authority)
            return _receipt(sealed, PolicyReceiptStatus.ADMITTED)

    def revoke(self, policy_id: str, version: int, actor: str, now: datetime) -> PolicyReceipt:
        """Append revocation before removing a policy from future selection."""
        _require_policy_identity(policy_id, version)
        _require_actor(actor)
        _require_utc(now, "revocation time")
        with self._lock:
            entry = self._active_entry(policy_id, version)
            if entry is None:
                return _unresolved_receipt(policy_id, version)
            if self._resolve_administration_authority(entry.policy, actor=actor, now=now) is None:
                return _receipt(entry.policy, PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED)
            self._journal.append(self._revoked_event(entry.policy, actor=actor, now=now))
            entry.status = PolicyStatus.REVOKED
            return _receipt(entry.policy, PolicyReceiptStatus.REVOKED)

    def supersede(
        self,
        policy_id: str,
        version: int,
        successor_policy_id: str,
        successor_version: int,
        actor: str,
        now: datetime,
    ) -> PolicyReceipt:
        """Retire one active entry in favor of an already admitted active successor."""
        _require_policy_identity(policy_id, version)
        _require_policy_identity(successor_policy_id, successor_version)
        _require_actor(actor)
        _require_utc(now, "supersession time")
        with self._lock:
            entry = self._active_entry(policy_id, version)
            successor = self._active_entry(successor_policy_id, successor_version)
            if entry is None or successor is None or entry is successor:
                return _unresolved_receipt(policy_id, version)
            if self._resolve_administration_authority(entry.policy, actor=actor, now=now) is None:
                return _receipt(entry.policy, PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED)
            self._journal.append(
                self._superseded_event(entry.policy, successor.policy, actor=actor, now=now)
            )
            entry.status = PolicyStatus.SUPERSEDED
            return _receipt(entry.policy, PolicyReceiptStatus.SUPERSEDED)

    def _select(
        self, use: str, subjects: Sequence[SealedExternalSubjectV1]
    ) -> PolicySelection:
        now = self._clock()
        _require_utc(now, "selection time")
        with self._lock:
            matches: list[_PolicyEntry] = []
            for entry in self._entries_by_identity.values():
                if entry.status is not PolicyStatus.ACTIVE:
                    continue
                authority_digest = entry.policy.authority_record_digest
                if authority_digest is None:
                    continue
                authority = self._authority_port.resolve(authority_digest, now)
                if authority is None:
                    continue
                if authority.digest != authority_digest or authority != entry.authority:
                    continue
                if authority.permits_selection(entry.policy, use=use, subjects=subjects, now=now):
                    matches.append(entry)
            if not matches:
                return PolicySelection(
                    status=PolicySelectionStatus.POLICY_UNAVAILABLE,
                    policy=None,
                    reason="NO_ACTIVE_POLICY",
                )
            if len(matches) != 1:
                return PolicySelection(
                    status=PolicySelectionStatus.POLICY_AMBIGUOUS,
                    policy=None,
                    reason="AMBIGUOUS_POLICY_SELECTION",
                )
            entry = matches[0]
            return PolicySelection(
                status=PolicySelectionStatus.ACTIVE,
                policy=entry.policy.model_copy(deep=True),
                reason=None,
            )

    def _resolve_administration_authority(
        self, policy: ExternalValidationPolicyV1, *, actor: str, now: datetime
    ) -> PolicyAuthorityRecord | None:
        authority_digest = policy.authority_record_digest
        if policy.status is not PolicyStatus.ACTIVE or authority_digest is None:
            return None
        authority = self._authority_port.resolve(authority_digest, now)
        if authority is None or authority.digest != authority_digest:
            return None
        if not authority.authorizes_admission(policy, actor=actor, now=now):
            return None
        return authority

    def _active_entry(self, policy_id: str, version: int) -> _PolicyEntry | None:
        entry = self._entries_by_identity.get((policy_id, version))
        if entry is None or entry.status is not PolicyStatus.ACTIVE:
            return None
        return entry

    def _publish(
        self, policy: ExternalValidationPolicyV1, authority: PolicyAuthorityRecord
    ) -> None:
        digest = _policy_digest(policy)
        entry = _PolicyEntry(policy=policy, authority=authority, status=PolicyStatus.ACTIVE)
        self._entries_by_identity[(policy.policy_id, policy.version)] = entry
        self._entries_by_digest[digest] = entry

    def _admitted_event(
        self,
        policy: ExternalValidationPolicyV1,
        authority: PolicyAuthorityRecord,
        *,
        actor: str,
        now: datetime,
    ) -> dict[str, object]:
        return _seal_event(
            {
                "kind": _ADMITTED_KIND,
                "eventVersion": _EVENT_VERSION,
                "policy": policy.model_dump(by_alias=True, mode="json"),
                "policyDigest": _policy_digest(policy),
                "policyId": policy.policy_id,
                "policyVersion": policy.version,
                "authorityRecordDigest": policy.authority_record_digest,
                "authority": authority.event_payload(),
                "actor": actor,
                "occurredAt": _wire_time(now),
            }
        )

    def _revoked_event(
        self, policy: ExternalValidationPolicyV1, *, actor: str, now: datetime
    ) -> dict[str, object]:
        return _seal_event(
            {
                "kind": _REVOKED_KIND,
                "eventVersion": _EVENT_VERSION,
                "policyId": policy.policy_id,
                "policyVersion": policy.version,
                "policyDigest": _policy_digest(policy),
                "actor": actor,
                "occurredAt": _wire_time(now),
            }
        )

    def _superseded_event(
        self,
        policy: ExternalValidationPolicyV1,
        successor: ExternalValidationPolicyV1,
        *,
        actor: str,
        now: datetime,
    ) -> dict[str, object]:
        return _seal_event(
            {
                "kind": _SUPERSEDED_KIND,
                "eventVersion": _EVENT_VERSION,
                "policyId": policy.policy_id,
                "policyVersion": policy.version,
                "policyDigest": _policy_digest(policy),
                "successorPolicyId": successor.policy_id,
                "successorPolicyVersion": successor.version,
                "successorPolicyDigest": _policy_digest(successor),
                "actor": actor,
                "occurredAt": _wire_time(now),
            }
        )

    def _replay(self, journal: DurableJournal) -> None:
        for index, raw in enumerate(journal.replay(), start=1):
            kind = raw.get("kind")
            try:
                if kind == _ADMITTED_KIND:
                    self._replay_admitted(raw)
                elif kind == _REVOKED_KIND:
                    self._replay_revoked(raw)
                elif kind == _SUPERSEDED_KIND:
                    self._replay_superseded(raw)
                else:
                    raise ValueError("unrecognized external validation policy journal event kind")
            except (TypeError, ValueError, ValidationError) as exc:
                raise ExternalValidationPolicyRecoveryError(
                    f"external validation policy journal event {index} is invalid: {exc}"
                ) from exc

    def _replay_admitted(self, raw: Mapping[str, Any]) -> None:
        event = _exact_mapping(
            raw,
            {
                "kind",
                "eventVersion",
                "policy",
                "policyDigest",
                "policyId",
                "policyVersion",
                "authorityRecordDigest",
                "authority",
                "actor",
                "occurredAt",
                "eventDigest",
            },
            context="admission event",
        )
        _require_event_header(event, _ADMITTED_KIND)
        if not isinstance(event["policy"], Mapping):
            raise ValueError("admission event policy must be an object")
        policy = _seal_policy(ExternalValidationPolicyV1.model_validate(event["policy"]))
        authority = PolicyAuthorityRecord.from_event_payload(event["authority"])
        policy_id, version, digest = _event_identity(event)
        actor = _event_actor(event)
        occurred_at = _event_time(event)
        authority_digest = policy.authority_record_digest
        if authority_digest is None:
            raise ValueError("admission event policy authority digest is absent")
        trusted = self._authority_port.resolve(authority_digest, occurred_at)
        if (
            digest != _policy_digest(policy)
            or policy_id != policy.policy_id
            or version != policy.version
            or event["authorityRecordDigest"] != authority_digest
            or authority.digest != authority_digest
            or trusted is None
            or trusted != authority
            or not authority.authorizes_admission(policy, actor=actor, now=occurred_at)
        ):
            raise ValueError("admission event policy/authority binding is invalid")
        key = (policy.policy_id, policy.version)
        if key in self._entries_by_identity or _policy_digest(policy) in self._entries_by_digest:
            raise ValueError("admission event duplicates an existing immutable policy")
        self._publish(policy, authority)

    def _replay_revoked(self, raw: Mapping[str, Any]) -> None:
        event = _exact_mapping(
            raw,
            {
                "kind",
                "eventVersion",
                "policyId",
                "policyVersion",
                "policyDigest",
                "actor",
                "occurredAt",
                "eventDigest",
            },
            context="revocation event",
        )
        _require_event_header(event, _REVOKED_KIND)
        policy_id, version, digest = _event_identity(event)
        entry = self._active_entry(policy_id, version)
        if entry is None or digest != _policy_digest(entry.policy):
            raise ValueError("revocation event is out of order or does not bind its policy")
        if not self._replay_authority_authorizes(
            entry, actor=_event_actor(event), now=_event_time(event)
        ):
            raise ValueError("revocation event actor/authority binding is invalid")
        entry.status = PolicyStatus.REVOKED

    def _replay_superseded(self, raw: Mapping[str, Any]) -> None:
        event = _exact_mapping(
            raw,
            {
                "kind",
                "eventVersion",
                "policyId",
                "policyVersion",
                "policyDigest",
                "successorPolicyId",
                "successorPolicyVersion",
                "successorPolicyDigest",
                "actor",
                "occurredAt",
                "eventDigest",
            },
            context="supersession event",
        )
        _require_event_header(event, _SUPERSEDED_KIND)
        policy_id, version, digest = _event_identity(event)
        entry = self._active_entry(policy_id, version)
        successor_id = event["successorPolicyId"]
        successor_version = event["successorPolicyVersion"]
        successor_digest = event["successorPolicyDigest"]
        if (
            not isinstance(successor_id, str)
            or not isinstance(successor_version, int)
            or isinstance(successor_version, bool)
        ):
            raise ValueError("supersession event successor identity is malformed")
        successor = self._active_entry(successor_id, successor_version)
        if (
            entry is None
            or successor is None
            or entry is successor
            or digest != _policy_digest(entry.policy)
            or successor_digest != _policy_digest(successor.policy)
        ):
            raise ValueError("supersession event is out of order or does not bind both policies")
        if not self._replay_authority_authorizes(
            entry, actor=_event_actor(event), now=_event_time(event)
        ):
            raise ValueError("supersession event actor/authority binding is invalid")
        entry.status = PolicyStatus.SUPERSEDED

    def _replay_authority_authorizes(
        self, entry: _PolicyEntry, *, actor: str, now: datetime
    ) -> bool:
        authority_digest = entry.policy.authority_record_digest
        if authority_digest is None:
            return False
        trusted = self._authority_port.resolve(authority_digest, now)
        return (
            trusted is not None
            and trusted == entry.authority
            and trusted.authorizes_admission(entry.policy, actor=actor, now=now)
        )


def _require_utc(value: datetime, field: str) -> None:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field} must be a UTC timezone-aware datetime")


def _wire_time(value: datetime) -> str:
    _require_utc(value, "event time")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_wire_time(value: str, field: str) -> datetime:
    if _UTC_WIRE_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a strict UTC RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UTC RFC3339 timestamp") from exc
    _require_utc(parsed, field)
    return parsed


def _require_nonempty_unique(values: tuple[str, ...], field: str) -> None:
    if not values or any(not value or value != value.strip() for value in values):
        raise ValueError(f"{field} must be non-empty trimmed strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must be unique")


def _require_actor(actor: str) -> None:
    if not actor or actor != actor.strip():
        raise ValueError("actor must be a non-empty authenticated identity")


def _require_policy_identity(policy_id: str, version: int) -> None:
    if not isinstance(policy_id, str) or not policy_id or policy_id != policy_id.strip():
        raise ValueError("policy_id must be a non-empty trimmed identifier")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("policy version must be a positive integer")


def _require_use(use: str) -> None:
    if not use or use != use.strip() or use not in _PERMITTED_USES:
        raise ValueError("policy use must be an allowed closed-catalogue value")


def _selection_arity_reason(
    use: str, subjects: Sequence[SealedExternalSubjectV1]
) -> str | None:
    """Reject malformed use scope before a policy can become selectable."""
    if use in {"INSPECTION", "DISPLAY", "HEIGHT"}:
        return None if len(subjects) == 1 else "SINGLE_SUBJECT_REQUIRED"
    if len(subjects) != 2:
        return "DISTINCT_ORDERED_PAIR_REQUIRED"
    first, second = subjects
    if first.canonical_digest() == second.canonical_digest():
        return "DISTINCT_ORDERED_PAIR_REQUIRED"
    return None


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def authorized_policy_body_digest(policy: ExternalValidationPolicyV1) -> str:
    """Digest the authority-approved policy body before authority digest finalization.

    The two omitted fields are deliberately the only omitted fields: the final
    policy digest binds the completed authority-record digest, while this body
    digest gives that authority record an acyclic approval target.
    """
    payload = policy.model_dump(
        by_alias=True,
        mode="json",
        exclude={"policy_digest", "authority_record_digest"},
    )
    return _canonical_digest({"domain": _POLICY_BODY_DOMAIN, "policy": payload})


def _seal_policy(policy: ExternalValidationPolicyV1) -> ExternalValidationPolicyV1:
    _require_policy_identity(policy.policy_id, policy.version)
    sealed = policy.sealed()
    if sealed.status is not PolicyStatus.ACTIVE:
        raise ValueError("only ACTIVE external validation policies can be admitted")
    if sealed.policy_digest is None:
        raise ValueError("sealed external validation policy digest is required")
    return sealed


def _policy_digest(policy: ExternalValidationPolicyV1) -> str:
    if policy.policy_digest is None:
        raise ValueError("sealed external validation policy digest is required")
    return policy.policy_digest


def _receipt(policy: ExternalValidationPolicyV1, status: PolicyReceiptStatus) -> PolicyReceipt:
    return PolicyReceipt(
        policy_id=policy.policy_id,
        version=policy.version,
        policy_digest=_policy_digest(policy),
        status=status,
    )


def _unresolved_receipt(policy_id: str, version: int) -> PolicyReceipt:
    _require_policy_identity(policy_id, version)
    return PolicyReceipt(
        policy_id=policy_id,
        version=version,
        policy_digest=None,
        status=PolicyReceiptStatus.POLICY_AUTHORITY_UNRESOLVED,
    )


def _exact_mapping(
    raw: object, expected_keys: set[str], *, context: str
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{context} must be an object")
    keys = set(raw)
    if keys != expected_keys:
        raise ValueError(f"{context} fields do not match the exact event shape")
    if not all(isinstance(key, str) for key in keys):
        raise ValueError(f"{context} keys must be strings")
    return raw


def _require_event_header(event: Mapping[str, Any], expected_kind: str) -> None:
    version = event["eventVersion"]
    if (
        event["kind"] != expected_kind
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version != _EVENT_VERSION
    ):
        raise ValueError("policy lifecycle event kind/version is invalid")
    _verify_event_digest(event)


def _event_actor(event: Mapping[str, Any]) -> str:
    actor = event["actor"]
    if not isinstance(actor, str):
        raise ValueError("policy lifecycle actor is malformed")
    _require_actor(actor)
    return actor


def _event_time(event: Mapping[str, Any]) -> datetime:
    occurred_at = event["occurredAt"]
    if not isinstance(occurred_at, str):
        raise ValueError("policy lifecycle occurredAt is malformed")
    return _parse_wire_time(occurred_at, "policy lifecycle occurredAt")


def _event_identity(event: Mapping[str, Any]) -> tuple[str, int, str]:
    policy_id = event["policyId"]
    version = event["policyVersion"]
    digest = event["policyDigest"]
    if not isinstance(policy_id, str) or not policy_id or policy_id != policy_id.strip():
        raise ValueError("policy lifecycle policyId is malformed")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("policy lifecycle policyVersion is malformed")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("policy lifecycle policyDigest is malformed")
    return policy_id, version, digest


def _event_digest(event: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    return _canonical_digest(payload)


def _seal_event(event: dict[str, object]) -> dict[str, object]:
    event["eventDigest"] = _event_digest(event)
    return event


def _verify_event_digest(event: Mapping[str, Any]) -> None:
    digest = event["eventDigest"]
    if (
        not isinstance(digest, str)
        or _DIGEST_RE.fullmatch(digest) is None
        or digest != _event_digest(event)
    ):
        raise ValueError("policy lifecycle eventDigest does not match canonical event content")


__all__ = [
    "ExternalValidationPolicyConflictError",
    "ExternalValidationPolicyRecoveryError",
    "ExternalValidationPolicyRegistry",
    "PolicyAuthorityPort",
    "PolicyAuthorityRecord",
    "PolicyReceipt",
    "PolicyReceiptStatus",
    "PolicySelection",
    "PolicySelectionStatus",
    "authorized_policy_body_digest",
]
