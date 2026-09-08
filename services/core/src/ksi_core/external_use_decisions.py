"""Durable private journal for already evaluated external-use decisions.

This kernel deliberately records immutable evaluator output only.  It contains no
policy lookup, raster/measurement handling, HTTP route, or eligibility evaluator.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalPairUseDecisionV1,
    ExternalUseDecisionV1,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
    external_pair_use_decision_wire_dict,
    external_use_decision_wire_dict,
)

from ksi_core.auth import Principal, PrincipalKind
from ksi_core.durable_journal import DurableJournal

_EVENT_VERSION = 1
_REQUESTED_KIND = "external-use-decision-requested"
_RECORDED_KIND = "external-use-decision-recorded"
_FINGERPRINT_DOMAIN = "ksi.external-use-decision-idempotency.v1"
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

type DecisionCandidate = ExternalUseDecisionV1 | ExternalPairUseDecisionV1


class ExternalUseDecisionConflictError(ValueError):
    """An idempotency key or decision identity was reused for another input."""


class ExternalUseDecisionRecoveryError(RuntimeError):
    """The append-only decision journal cannot be replayed safely."""


class WriteStatus(StrEnum):
    PENDING = "PENDING"
    RECORDED = "RECORDED"


@dataclass(frozen=True, slots=True)
class ExternalDecisionIntent:
    """Closed server intent: requested use plus its exact sealed subject scope."""

    requested_use: str
    subject: SealedExternalSubjectV1 | None = None
    baseline_subject: SealedExternalSubjectV1 | None = None
    current_subject: SealedExternalSubjectV1 | None = None
    zone: SealedZoneReferenceV1 | None = None

    @classmethod
    def from_candidate(cls, candidate: DecisionCandidate) -> ExternalDecisionIntent:
        if isinstance(candidate, ExternalUseDecisionV1):
            return cls(requested_use=candidate.use, subject=candidate.subject)
        return cls(
            requested_use=candidate.use,
            baseline_subject=candidate.baseline_subject,
            current_subject=candidate.current_subject,
            zone=candidate.zone,
        )

    def payload(self) -> dict[str, object]:
        if self.subject is not None:
            if (
                self.requested_use not in {"DISPLAY", "HEIGHT"}
                or self.baseline_subject is not None
                or self.current_subject is not None
                or self.zone is not None
            ):
                raise ValueError("single decision intent is invalid")
            return {
                "requestedUse": self.requested_use,
                "subject": self.subject.canonical_payload(),
            }
        if self.baseline_subject is None or self.current_subject is None:
            raise ValueError("pair decision intent requires ordered subjects")
        if self.requested_use not in {"VISUAL_COMPARISON", "RELATIVE_VOLUME"}:
            raise ValueError("pair decision intent is invalid")
        return {
            "requestedUse": self.requested_use,
            "baselineSubject": self.baseline_subject.canonical_payload(),
            "currentSubject": self.current_subject.canonical_payload(),
            "zone": self.zone.model_dump(by_alias=True, mode="json") if self.zone else None,
        }


def _intent_from_payload(raw: object) -> ExternalDecisionIntent:
    if not isinstance(raw, dict) or not isinstance(raw.get("requestedUse"), str):
        raise ValueError("intent is malformed")
    if set(raw) == {"requestedUse", "subject"}:
        return ExternalDecisionIntent(
            requested_use=raw["requestedUse"],
            subject=SealedExternalSubjectV1.model_validate(raw["subject"]),
        )
    if set(raw) == {"requestedUse", "baselineSubject", "currentSubject", "zone"}:
        zone_raw = raw["zone"]
        return ExternalDecisionIntent(
            requested_use=raw["requestedUse"],
            baseline_subject=SealedExternalSubjectV1.model_validate(raw["baselineSubject"]),
            current_subject=SealedExternalSubjectV1.model_validate(raw["currentSubject"]),
            zone=SealedZoneReferenceV1.model_validate(zone_raw) if zone_raw is not None else None,
        )
    raise ValueError("intent fields are not exact")


@dataclass(frozen=True, slots=True)
class ExternalUseDecisionWrite:
    status: WriteStatus
    candidate: DecisionCandidate


@dataclass(frozen=True, slots=True)
class _Scope:
    organization_id: str
    site_id: str

    def payload(self) -> dict[str, str]:
        return {"organizationId": self.organization_id, "siteId": self.site_id}


@dataclass(frozen=True, slots=True)
class _PrincipalBinding:
    principal_id: str
    kind: str
    organization_id: str

    def payload(self) -> dict[str, str]:
        return {
            "principalId": self.principal_id,
            "kind": self.kind,
            "organizationId": self.organization_id,
        }


@dataclass(frozen=True, slots=True)
class _Pending:
    candidate: DecisionCandidate
    candidate_digest: str
    scope: _Scope
    operation: str
    intent: ExternalDecisionIntent
    principal: _PrincipalBinding
    idempotency_namespace: str
    fingerprint: str
    requested_at: datetime


def _digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _event_digest(event: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _wire_time(value: datetime) -> str:
    _require_utc(value, "event time")
    return value.isoformat()


def _parse_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_utc(parsed, field)
    return parsed


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field} must be UTC-aware")


def _require_text(value: object, *, field: str, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or normalized != value or len(normalized) > maximum:
        raise ValueError(f"{field} is invalid")
    return normalized


def _candidate_wire(candidate: DecisionCandidate) -> dict[str, Any]:
    if isinstance(candidate, ExternalUseDecisionV1):
        return external_use_decision_wire_dict(candidate)
    return external_pair_use_decision_wire_dict(candidate)


def _sealed_candidate(candidate: DecisionCandidate) -> DecisionCandidate:
    if (
        candidate.decision_digest is None
        or candidate.decision_digest != candidate.canonical_digest()
    ):
        raise ValueError("decision candidate must be fully sealed")
    return candidate


def _candidate_from_wire(raw: object) -> DecisionCandidate:
    if not isinstance(raw, dict):
        raise ValueError("decision candidate must be an object")
    contract_version = raw.get("contractVersion")
    if contract_version == "external-use-decision.v1":
        candidate: DecisionCandidate = ExternalUseDecisionV1.model_validate(raw)
    elif contract_version == "external-pair-use-decision.v1":
        candidate = ExternalPairUseDecisionV1.model_validate(raw)
    else:
        raise ValueError("decision candidate contract version is unknown")
    return _sealed_candidate(candidate)


def _scope_and_operation(candidate: DecisionCandidate) -> tuple[_Scope, str]:
    if isinstance(candidate, ExternalUseDecisionV1):
        subject = candidate.subject
        return _Scope(subject.organization_id, subject.site_id), "SINGLE"
    baseline, current = candidate.baseline_subject, candidate.current_subject
    if baseline.organization_id != current.organization_id or baseline.site_id != current.site_id:
        raise ValueError("pair candidate subjects must share organization and site")
    return _Scope(baseline.organization_id, baseline.site_id), "PAIR"


def _principal_binding(principal: Principal, scope: _Scope) -> _PrincipalBinding:
    principal_id = _require_text(principal.principal_id, field="principal id")
    organization_id = _require_text(principal.organization_id, field="principal organization")
    if organization_id != scope.organization_id:
        raise ValueError("principal organization does not match decision scope")
    return _PrincipalBinding(principal_id, principal.kind.value, organization_id)


def _namespace(*, idempotency_key: str, principal: _PrincipalBinding) -> str:
    return _digest(
        {
            "domain": "ksi.external-use-decision-idempotency-namespace.v1",
            "principalId": principal.principal_id,
            "organizationId": principal.organization_id,
            "idempotencyKey": idempotency_key,
        }
    )


def _fingerprint(
    *,
    namespace: str,
    candidate_digest: str,
    scope: _Scope,
    operation: str,
    intent: ExternalDecisionIntent,
    principal: _PrincipalBinding,
) -> str:
    return _digest(
        {
            "domain": _FINGERPRINT_DOMAIN,
            "namespace": namespace,
            "candidateDigest": candidate_digest,
            "scope": scope.payload(),
            "operation": operation,
            "intent": intent.payload(),
            "principal": principal.payload(),
        }
    )


def _validate_intent(candidate: DecisionCandidate, intent: ExternalDecisionIntent) -> None:
    expected = ExternalDecisionIntent.from_candidate(candidate)
    if intent.payload() != expected.payload():
        raise ValueError("decision intent does not match evaluator candidate")


class ExternalUseDecisionStore:
    """Append-only persistence and replay for a future internal evaluator seam."""

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._pending: dict[str, _Pending] = {}
        self._recorded: dict[str, DecisionCandidate] = {}
        self._scopes: dict[str, _Scope] = {}
        self._idempotency: dict[str, _Pending] = {}
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, ExternalUseDecisionRecoveryError):
                raise
            raise ExternalUseDecisionRecoveryError(
                f"external use decision journal replay failed: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def stage_evaluated(
        self,
        candidate: DecisionCandidate,
        *,
        intent: ExternalDecisionIntent,
        principal: Principal,
        idempotency_key: str,
    ) -> ExternalUseDecisionWrite:
        """Durably stage a sealed evaluator candidate without reevaluating it."""
        candidate = _sealed_candidate(candidate)
        scope, operation = _scope_and_operation(candidate)
        _validate_intent(candidate, intent)
        key = _require_text(idempotency_key, field="idempotency key")
        binding = _principal_binding(principal, scope)
        namespace = _namespace(idempotency_key=key, principal=binding)
        digest = candidate.decision_digest
        assert digest is not None
        fingerprint = _fingerprint(
            namespace=namespace,
            candidate_digest=digest,
            scope=scope,
            operation=operation,
            intent=intent,
            principal=binding,
        )
        pending = _Pending(
            candidate,
            digest,
            scope,
            operation,
            intent,
            binding,
            namespace,
            fingerprint,
            candidate.decided_at,
        )
        with self._lock:
            existing = self._idempotency.get(namespace)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ExternalUseDecisionConflictError("idempotency key conflicts")
                status = (
                    WriteStatus.RECORDED
                    if candidate.decision_id in self._recorded
                    else WriteStatus.PENDING
                )
                return ExternalUseDecisionWrite(status, existing.candidate)
            existing_candidate = self._pending.get(candidate.decision_id) or self._recorded.get(
                candidate.decision_id
            )
            if existing_candidate is not None:
                raise ExternalUseDecisionConflictError("decision id conflicts")
            event = self._requested_event(pending)
            self._journal.append(event)
            self._apply(event)
            return ExternalUseDecisionWrite(WriteStatus.PENDING, candidate)

    def reconcile_pending(self) -> tuple[ExternalUseDecisionWrite, ...]:
        """Append records for staged candidates exactly as staged, with no evaluation."""
        with self._lock:
            receipts: list[ExternalUseDecisionWrite] = []
            for decision_id, pending in tuple(self._pending.items()):
                event = self._recorded_event(decision_id, pending)
                self._journal.append(event)
                self._apply(event)
                receipts.append(ExternalUseDecisionWrite(WriteStatus.RECORDED, pending.candidate))
            return tuple(receipts)

    def get_scoped(
        self, decision_id: str, *, principal: Principal, site_id: str
    ) -> DecisionCandidate | None:
        with self._lock:
            candidate = self._recorded.get(decision_id)
            scope = self._scopes.get(decision_id)
            if candidate is None or scope is None:
                return None
            if principal.organization_id != scope.organization_id or site_id != scope.site_id:
                return None
            return candidate

    def list_scoped(self, *, principal: Principal, site_id: str) -> tuple[DecisionCandidate, ...]:
        with self._lock:
            return tuple(
                candidate
                for decision_id, candidate in self._recorded.items()
                if self._scopes[decision_id].organization_id == principal.organization_id
                and self._scopes[decision_id].site_id == site_id
            )

    def _requested_event(self, pending: _Pending) -> dict[str, object]:
        event: dict[str, object] = {
            "kind": _REQUESTED_KIND,
            "version": _EVENT_VERSION,
            "decisionId": pending.candidate.decision_id,
            "candidate": _candidate_wire(pending.candidate),
            "candidateDigest": pending.candidate_digest,
            "scope": pending.scope.payload(),
            "operation": pending.operation,
            "intent": pending.intent.payload(),
            "principal": pending.principal.payload(),
            "idempotency": {
                "namespace": pending.idempotency_namespace,
                "fingerprint": pending.fingerprint,
            },
            "requestedAt": _wire_time(pending.requested_at),
        }
        event["eventDigest"] = _event_digest(event)
        return event

    def _recorded_event(self, decision_id: str, pending: _Pending) -> dict[str, object]:
        event: dict[str, object] = {
            "kind": _RECORDED_KIND,
            "version": _EVENT_VERSION,
            "decisionId": decision_id,
            "candidateDigest": pending.candidate_digest,
            "recordedAt": _wire_time(pending.requested_at),
        }
        event["eventDigest"] = _event_digest(event)
        return event

    def _apply(self, raw: object) -> None:
        try:
            if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
                raise ValueError("unknown event")
            if raw["kind"] == _REQUESTED_KIND:
                self._apply_requested(raw)
            elif raw["kind"] == _RECORDED_KIND:
                self._apply_recorded(raw)
            else:
                raise ValueError("unknown event kind")
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalUseDecisionRecoveryError(str(exc)) from exc

    def _verify_event(self, raw: dict[str, Any], expected: set[str]) -> None:
        if set(raw) != expected:
            raise ValueError("event fields are not exact")
        if type(raw.get("version")) is not int or raw["version"] != _EVENT_VERSION:
            raise ValueError("event version is invalid")
        digest = raw.get("eventDigest")
        if not isinstance(digest, str) or digest != _event_digest(raw):
            raise ValueError("event digest is invalid")

    def _apply_requested(self, raw: dict[str, Any]) -> None:
        self._verify_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "decisionId",
                "candidate",
                "candidateDigest",
                "scope",
                "operation",
                "intent",
                "principal",
                "idempotency",
                "requestedAt",
            },
        )
        decision_id = _require_text(raw["decisionId"], field="decision id")
        candidate = _candidate_from_wire(raw["candidate"])
        if (
            candidate.decision_id != decision_id
            or candidate.decision_digest != raw["candidateDigest"]
        ):
            raise ValueError("candidate identity binding is invalid")
        scope_raw = _exact_mapping(raw["scope"], {"organizationId", "siteId"}, "scope")
        scope = _Scope(
            _require_text(scope_raw["organizationId"], field="scope organization"),
            _require_text(scope_raw["siteId"], field="scope site"),
        )
        derived_scope, operation = _scope_and_operation(candidate)
        if scope != derived_scope:
            raise ValueError("candidate scope binding is invalid")
        if raw["operation"] != operation:
            raise ValueError("candidate operation binding is invalid")
        intent = _intent_from_payload(raw["intent"])
        _validate_intent(candidate, intent)
        if intent.payload() != raw["intent"]:
            raise ValueError("intent binding is invalid")
        principal_raw = _exact_mapping(
            raw["principal"], {"principalId", "kind", "organizationId"}, "principal"
        )
        principal_kind = _require_text(principal_raw["kind"], field="principal kind")
        PrincipalKind(principal_kind)
        principal = _PrincipalBinding(
            _require_text(principal_raw["principalId"], field="principal id"),
            principal_kind,
            _require_text(principal_raw["organizationId"], field="principal organization"),
        )
        if principal.organization_id != scope.organization_id:
            raise ValueError("principal scope binding is invalid")
        idem_raw = _exact_mapping(raw["idempotency"], {"namespace", "fingerprint"}, "idempotency")
        namespace = idem_raw["namespace"]
        if not isinstance(namespace, str) or _SHA256_DIGEST.fullmatch(namespace) is None:
            raise ValueError("idempotency namespace is invalid")
        fingerprint = idem_raw["fingerprint"]
        if not isinstance(fingerprint, str) or fingerprint != _fingerprint(
            namespace=namespace,
            candidate_digest=candidate.decision_digest or "",
            scope=scope,
            operation=operation,
            intent=intent,
            principal=principal,
        ):
            raise ValueError("idempotency fingerprint is invalid")
        requested_at = _parse_time(raw["requestedAt"], field="requestedAt")
        if requested_at != candidate.decided_at:
            raise ValueError("requested time must retain candidate time")
        pending = _Pending(
            candidate,
            candidate.decision_digest or "",
            scope,
            operation,
            intent,
            principal,
            namespace,
            fingerprint,
            requested_at,
        )
        if (
            decision_id in self._pending
            or decision_id in self._recorded
            or namespace in self._idempotency
        ):
            raise ValueError("duplicate requested event")
        self._pending[decision_id] = pending
        self._scopes[decision_id] = scope
        self._idempotency[namespace] = pending

    def _apply_recorded(self, raw: dict[str, Any]) -> None:
        self._verify_event(
            raw,
            {"kind", "version", "eventDigest", "decisionId", "candidateDigest", "recordedAt"},
        )
        decision_id = _require_text(raw["decisionId"], field="decision id")
        pending = self._pending.get(decision_id)
        if pending is None:
            raise ValueError("recorded event has no pending candidate")
        if raw["candidateDigest"] != pending.candidate_digest:
            raise ValueError("recorded candidate digest is invalid")
        if _parse_time(raw["recordedAt"], field="recordedAt") != pending.requested_at:
            raise ValueError("recorded event changed candidate time")
        self._recorded[decision_id] = pending.candidate
        del self._pending[decision_id]


def _exact_mapping(raw: object, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError(f"{context} fields are not exact")
    return raw


__all__ = [
    "ExternalDecisionIntent",
    "ExternalUseDecisionConflictError",
    "ExternalUseDecisionRecoveryError",
    "ExternalUseDecisionStore",
    "ExternalUseDecisionWrite",
    "WriteStatus",
]
