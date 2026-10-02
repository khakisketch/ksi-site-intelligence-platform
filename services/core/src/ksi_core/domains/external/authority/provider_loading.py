"""Protected authority-provider file and signed snapshot loading."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

from ksi_core.domains.external.authority.provider_types import (
    _CONFIG_VERSION,
    _DIGEST,
    _MAX_ADMINISTRATION_ACTIONS,
    _MAX_COLLECTION_RECORDS,
    _MAX_FILE_BYTES,
    _MAX_REGISTRY_KEYS,
    _REGISTRY_VERSION,
    _SNAPSHOT_DOMAIN,
    _SNAPSHOT_UNSIGNED_FIELDS,
    _SNAPSHOT_VERSION,
    _ActiveKey,
    _AdministrationAction,
    _exact_mapping,
    _no_constant,
    _no_duplicate_object,
    _ProviderConfig,
    _text,
    _utc,
    _VerifiedSnapshot,
)
from ksi_core.domains.external.ingress.external_validation_policy import PolicyAuthorityRecord
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
)
from ksi_core.domains.external.quantity.external_single_volume_authority import (
    ExternalSingleVolumeCompatibilityRecord,
)


def _protected_bytes(
    path: Path,
    *,
    name: str,
    maximum: int,
    private: bool,
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
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
        ) != (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
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


def _active_key(registry_path: Path, snapshot_key_id: str, now: datetime) -> _ActiveKey:
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
            key_path,
            name="authority public key",
            maximum=16_384,
            private=False,
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
    config: _ProviderConfig,
    *,
    clock: Callable[[], datetime],
    allow_expired: bool = False,
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
    expired = now >= valid_until and issued_at <= now
    if issued_at >= valid_until or not issued_at <= now or (expired and not allow_expired):
        raise ValueError("authority snapshot is outside its validity interval")
    key_id = _text(raw["keyId"], name="snapshot keyId")
    # An expired snapshot may be retained for history only after its signing
    # key is confirmed to have been valid when the snapshot was issued. It is
    # never thereby made current; provider live ports apply the current-time
    # validity gate independently.
    active_key = _active_key(
        config.key_registry_path, key_id, issued_at if expired else now
    )
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
                policy,
                actor=action.actor_id,
                now=action.effective_at,
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
        "ADMIT_SINGLE_MAPPING": 1,
        "REVOKE_SINGLE_MAPPING": 1,
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
        elif kind in {"ADMIT_MAPPING", "ADMIT_SINGLE_MAPPING"}:
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
        elif kind in {"REVOKE_MAPPING", "REVOKE_SINGLE_MAPPING"} and (
            not isinstance(action["mappingDigest"], str)
            or _DIGEST.fullmatch(action["mappingDigest"]) is None
        ):
            raise ValueError("mappingDigest must be a sha256 digest")
        elif kind == "ADMIT_MAPPING":
            ExternalQuantitativeCompatibilityRecord.from_event_payload(action["mapping"])
        elif kind == "ADMIT_SINGLE_MAPPING":
            ExternalSingleVolumeCompatibilityRecord.from_event_payload(action["mapping"])
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
