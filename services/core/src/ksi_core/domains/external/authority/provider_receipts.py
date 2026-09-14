"""Authority-provider receipt construction, replay, and history reconstruction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.domains.external.authority.provider_loading import (
    _authority_collection,
    _context_from_snapshot_payload,
    _sha256_bytes,
)
from ksi_core.domains.external.authority.provider_types import (
    _RECEIPT_KIND,
    _RECEIPT_VERSION,
    _SNAPSHOT_DOMAIN,
    _SNAPSHOT_UNSIGNED_FIELDS,
    _SNAPSHOT_VERSION,
    _exact_mapping,
    _Receipt,
    _text,
    _VerifiedSnapshot,
)
from ksi_core.domains.external.ingress.external_validation_policy import PolicyAuthorityRecord
from ksi_core.foundation.durable_journal import DurableJournal


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
