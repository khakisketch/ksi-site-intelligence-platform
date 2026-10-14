#!/usr/bin/env python3
"""Renew a signed external-validation authority chain with current windows.

Maintenance tool for F-03-generation provider material whose authority records
have expired: an expired policy/context window cannot be extended in place
(the policy body binds its authority record digest, and the record digest binds
its window), so the whole chain must be regenerated from the policy body:

    policy authority record R' (fresh window)
      -> policy body version+1 (authorityRecordDigest = R')
        -> policy digest Y
          -> evidence contexts (policyDigest = Y, fresh windows)
            -> catalog authority (fresh windows, same execution digests)
              -> snapshot sequence+1 with ADMIT_POLICY(Y)

Only authority *windows* and their dependent digests are regenerated; execution
policy digests (algorithm build, config, resource envelope) and context rule
fields are carried over unchanged, so the operator can keep whatever the
deployment corrected. Dependent mappings must be re-admitted separately against
the renewed catalog authority (the Core binds the catalog body at boot).

A new subject is admitted only through the explicit ``--add-subject-file``
option: a JSON array of ``SealedExternalSubjectV1`` payloads (same field
names as the ``permittedSubjects`` records). The renewed policy record's
``permittedSubjects`` is the prior subjects plus the added subjects, deduped
by ``canonical_digest()`` with prior order preserved. This is the KSI signing
step for adding a subject; there is no automatic subject discovery.

The regenerated snapshot is validated with the real provider loader before any
file is replaced. Files are written owner-private (0600); the provider
directory must be protected (0700 ancestors) because the loader enforces it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.domains.external.authority.external_result_workflow_config import (
    catalog_admission_body_digest,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.domains.external.quantity.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

DOMAIN = "ksi.external-authority-provider-snapshot.v1"
_PLACEHOLDER = "sha256:" + "0" * 64


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _snapshot_digest(snapshot: dict[str, object]) -> str:
    unsigned = {key: value for key, value in snapshot.items() if key != "signature"}
    signed = canonical_json_bytes({"domain": DOMAIN, "snapshot": unsigned})
    return "sha256:" + hashlib.sha256(signed).hexdigest()


def _read_private_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path} is not a JSON object")
    return value


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SystemExit(f"{name} must be a JSON object")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise SystemExit(f"{name} must be a list")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{name} must be a non-empty string")
    return value


def _text_list(value: object, name: str) -> tuple[str, ...]:
    items = _list(value, name)
    if not items or any(not isinstance(item, str) or not item for item in items):
        raise SystemExit(f"{name} must be a non-empty string list")
    return tuple(item for item in items if isinstance(item, str))


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SystemExit(f"{name} must be an integer")
    return value


def _load_added_subjects(path: Path) -> list[SealedExternalSubjectV1]:
    """Load an explicit JSON array of SealedExternalSubjectV1 payloads.

    This is the KSI signing step for admitting a new subject: only subjects
    listed in this file are appended. There is no automatic discovery.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--add-subject-file cannot be read as JSON: {exc}") from exc
    items = _list(raw, "--add-subject-file subjects")
    subjects = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SystemExit(f"--add-subject-file subject #{index} must be a JSON object")
        try:
            subjects.append(SealedExternalSubjectV1.model_validate(item))
        except ValueError as exc:
            raise SystemExit(f"--add-subject-file subject #{index} is invalid: {exc}") from exc
    return subjects


def _merge_subjects(
    prior: list[SealedExternalSubjectV1], added: list[SealedExternalSubjectV1]
) -> tuple[SealedExternalSubjectV1, ...]:
    """Prior subjects first, then added subjects, deduped by canonical_digest()."""
    merged = list(prior)
    seen = {subject.canonical_digest() for subject in merged}
    for subject in added:
        digest = subject.canonical_digest()
        if digest in seen:
            continue
        seen.add(digest)
        merged.append(subject)
    return tuple(merged)


def _write_private_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.chmod(path, 0o600)


def _receipt_head(core_data_dir: Path) -> tuple[int, str] | None:
    receipts = core_data_dir / "external-authority-provider-receipts.jsonl"
    if not receipts.exists():
        return None
    head: tuple[int, str] | None = None
    for line in receipts.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            isinstance(row.get("sequence"), int)
            and isinstance(row.get("snapshotDigest"), str)
            and (head is None or row["sequence"] > head[0])
        ):
            head = (row["sequence"], row["snapshotDigest"])
    return head


def _continuity(
    snapshot: dict[str, object], head: tuple[int, str] | None
) -> tuple[int, str | None]:
    sequence = snapshot.get("sequence")
    previous = snapshot.get("previousSnapshotDigest")
    if not isinstance(sequence, int) or sequence < 1:
        raise SystemExit("authority snapshot sequence must be a positive integer")
    if head is None:
        # Never-attached material (no Core receipt): the renewed snapshot must
        # still be a valid fresh history — keep the sequence, no predecessor.
        if sequence != 1 or previous is not None:
            raise SystemExit(
                "no retained receipt history: only a fresh sequence-1 history can be renewed"
            )
        return sequence, None
    if head[0] != sequence:
        raise SystemExit(
            f"receipt head (seq {head[0]}) does not match the snapshot (seq {sequence})"
        )
    current = _snapshot_digest(snapshot)
    if current != head[1]:
        raise SystemExit("snapshot digest does not match the retained receipt head")
    return sequence + 1, head[1]


def _current_records(
    snapshot: dict[str, object], collection: str
) -> tuple[list[dict[str, object]], list[str]]:
    section = snapshot[collection]
    assert isinstance(section, dict)
    records = section["records"]
    current = section["currentDigests"]
    assert isinstance(records, list) and isinstance(current, list)
    return records, current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--provider-dir", required=True, type=Path)
    parser.add_argument("--core-data-dir", required=True, type=Path)
    parser.add_argument("--policy-file", type=Path, default=None)
    parser.add_argument("--catalog-file", type=Path, default=None)
    parser.add_argument("--window-hours", type=float, default=6.0)
    parser.add_argument("--reload-url", default=None, help="Core origin for the authority reload")
    parser.add_argument("--admin-token", default=None)
    parser.add_argument(
        "--add-subject-file",
        type=Path,
        default=None,
        help=(
            "JSON array of SealedExternalSubjectV1 payloads (same field names as "
            "permittedSubjects records) to append to the renewed policy record's "
            "permittedSubjects. Prior subjects are preserved first, then added "
            "subjects, deduped by canonical_digest(). This explicit option is "
            "the only way the tool admits a new subject; no automatic discovery."
        ),
    )
    parser.add_argument("--check-only", action="store_true", help="preflight without writing")
    parser.add_argument("--state-file", type=Path, default=None)
    args = parser.parse_args(argv)

    provider = args.provider_dir
    policy_path = args.policy_file or provider / "policy-valid.json"
    catalog_path = args.catalog_file or provider / "catalog.json"
    snapshot_path = provider / "authority-snapshot.json"
    for path in (snapshot_path, policy_path):
        if not path.exists():
            raise SystemExit(f"required file is missing: {path}")

    now = datetime.now(UTC).replace(microsecond=0)
    window_start = now - timedelta(minutes=1)
    window_end = now + timedelta(hours=args.window_hours)

    snapshot = _read_private_json(snapshot_path)
    next_sequence, previous_digest = _continuity(snapshot, _receipt_head(args.core_data_dir))
    print(f"renewing seq {snapshot['sequence']} -> {next_sequence}")

    # ---- policy record R' -> body version+1 -> policy digest Y ------------------
    policy_records, current_policy = _current_records(snapshot, "policyAuthorities")
    if len(current_policy) != 1:
        raise SystemExit("exactly one current policy authority record is required")
    prior_record_payload = next(
        (row for row in policy_records if row.get("digest") == current_policy[0]), None
    )
    if prior_record_payload is None:
        raise SystemExit("current policy authority record is not retained in the snapshot")
    policy_body = _read_private_json(policy_path)
    new_version = _integer(policy_body.get("version"), "policy version") + 1
    actor_ids = _text_list(
        prior_record_payload.get("authorizedActorIds"), "authorizedActorIds"
    )

    policy_placeholder = ExternalValidationPolicyV1.model_validate(
        {
            **policy_body,
            "version": new_version,
            "policyDigest": None,
            "authorityRecordDigest": _PLACEHOLDER,
        }
    )
    body_digest = authorized_policy_body_digest(policy_placeholder)
    prior_subjects = [
        SealedExternalSubjectV1.model_validate(item)
        for item in _list(prior_record_payload.get("permittedSubjects"), "permittedSubjects")
    ]
    added_subjects = (
        _load_added_subjects(args.add_subject_file)
        if args.add_subject_file is not None
        else []
    )
    if added_subjects:
        print(f"adding {len(added_subjects)} explicit subject(s) to permittedSubjects")
    merged_subjects = _merge_subjects(prior_subjects, added_subjects)
    prior_digests = {subject.canonical_digest() for subject in prior_subjects}
    appended_subject_digests = [
        subject.canonical_digest()
        for subject in merged_subjects
        if subject.canonical_digest() not in prior_digests
    ]
    record = PolicyAuthorityRecord(
        policy_id=_text(policy_body.get("policyId"), "policyId"),
        policy_version=new_version,
        authorized_policy_body_digest=body_digest,
        permitted_subjects=merged_subjects,
        permitted_uses=_text_list(prior_record_payload.get("permittedUses"), "permittedUses"),
        authorized_actor_ids=actor_ids,
        active_from=window_start,
        active_until=window_end,
        synthetic_test_only=bool(prior_record_payload["syntheticTestOnly"]),
    ).sealed()
    assert record.digest
    policy = policy_placeholder.model_copy(
        update={"authority_record_digest": record.digest}, deep=True
    ).sealed()
    assert policy.policy_digest
    assert authorized_policy_body_digest(policy) == body_digest
    print(f"policy v{new_version} digest {policy.policy_digest}")

    # ---- evidence contexts -------------------------------------------------------
    context_records, current_contexts = _current_records(snapshot, "evidenceContexts")
    fresh_contexts = []
    for digest in current_contexts:
        payload = next((row for row in context_records if row.get("contextDigest") == digest), None)
        if payload is None:
            raise SystemExit("current evidence context is not retained in the snapshot")
        body = {key: value for key, value in payload.items() if key != "contextDigest"}
        body["policyDigest"] = policy.policy_digest
        body["activeFrom"] = _iso(window_start)
        body["activeUntil"] = _iso(window_end)
        fresh_contexts.append(ExternalEvidenceMeasurementContextV1.model_validate(body).sealed())
    for context in fresh_contexts:
        assert context.context_digest
    print(f"contexts renewed: {len(fresh_contexts)}")

    # ---- catalog authority -------------------------------------------------------
    catalog_payload: dict[str, object] | None = None
    catalog_authority: ExternalQuantitativeCatalogAuthorityRecord | None = None
    catalog_records, current_catalogs = _current_records(snapshot, "catalogAuthorities")
    if catalog_path.exists():
        if len(current_catalogs) != 1:
            raise SystemExit("exactly one current catalog authority record is required")
        prior_catalog_payload = next(
            (row for row in catalog_records if row.get("digest") == current_catalogs[0]), None
        )
        if prior_catalog_payload is None:
            raise SystemExit("current catalog authority record is not retained in the snapshot")
        catalog = _read_private_json(catalog_path)
        prior_top = _text(catalog.get("authorityRecordDigest"), "authorityRecordDigest")
        catalog_body = _mapping(catalog.get("body"), "catalog body")
        for group in ("executionTemplates", "singleExecutionTemplates"):
            for template in _list(catalog_body.get(group, []), group):
                template_row = _mapping(template, group)
                execution_policy = _mapping(
                    template_row.get("executionPolicy"), "executionPolicy"
                )
                template_row["validFrom"] = _iso(window_start)
                template_row["validUntil"] = _iso(
                    now + timedelta(hours=max(args.window_hours - 1.0, 0.5))
                )
                execution_policy["authorityRecordDigest"] = prior_top
        body_digest_catalog = catalog_admission_body_digest(catalog)
        catalog_authority = ExternalQuantitativeCatalogAuthorityRecord(
            organization_id=_text(
                prior_catalog_payload.get("organizationId"), "catalog organizationId"
            ),
            catalog_body_digest=body_digest_catalog,
            authorized_administration_actor_ids=_text_list(
                prior_catalog_payload.get("authorizedAdministrationActorIds"),
                "authorizedAdministrationActorIds",
            ),
            active_from=window_start,
            active_until=window_end,
            synthetic_test_only=False,
        ).sealed()
        assert catalog_authority.digest
        for group in ("executionTemplates", "singleExecutionTemplates"):
            for template in _list(catalog_body.get(group, []), group):
                execution_policy = _mapping(
                    _mapping(template, group).get("executionPolicy"), "executionPolicy"
                )
                execution_policy["authorityRecordDigest"] = catalog_authority.digest
        catalog["authorityRecordDigest"] = catalog_authority.digest
        assert catalog_admission_body_digest(catalog) == body_digest_catalog
        catalog_payload = catalog
        print(f"catalog authority {catalog_authority.digest}")

    # ---- snapshot -----------------------------------------------------------------
    issued = _iso(now)
    unsigned: dict[str, object] = {
        "version": snapshot["version"],
        "organizationId": snapshot["organizationId"],
        "sequence": next_sequence,
        "previousSnapshotDigest": previous_digest,
        "issuedAt": issued,
        "validUntil": _iso(window_end),
        "keyId": snapshot["keyId"],
        "catalogAuthorities": (
            {
                "records": [catalog_authority.event_payload()],
                "currentDigests": [catalog_authority.digest],
            }
            if catalog_authority is not None
            else {"records": [], "currentDigests": []}
        ),
        "policyAuthorities": {
            "records": [record.event_payload()],
            "currentDigests": [record.digest],
        },
        "evidenceContexts": {
            "records": [row.model_dump(by_alias=True, mode="json") for row in fresh_contexts],
            "currentDigests": [row.context_digest for row in fresh_contexts],
        },
        "quantitativeAdministration": {
            "actions": [
                {
                    "actionId": f"renew-policy-v{new_version}-{str(record.digest)[7:19]}",
                    "kind": "ADMIT_POLICY",
                    "effectiveAt": issued,
                    "actorId": actor_ids[0],
                    "policy": policy.model_dump(by_alias=True, mode="json"),
                }
            ]
        },
    }
    signer = serialization.load_pem_private_key(
        (provider / "authority-signer.private.pem").read_bytes(), password=None
    )
    assert isinstance(signer, Ed25519PrivateKey)
    signature = signer.sign(canonical_json_bytes({"domain": DOMAIN, "snapshot": unsigned}))
    new_snapshot = {**unsigned, "signature": base64.b64encode(signature).decode("ascii")}

    # ---- preflight with the real loader ------------------------------------------
    from ksi_core.domains.external.authority.provider_loading import (  # noqa: PLC0415
        _snapshot_from_path,
    )
    from ksi_core.domains.external.authority.provider_types import (  # noqa: PLC0415
        _ProviderConfig,
    )
    from ksi_core.domains.external.quantity.external_relative_volumes import (  # noqa: PLC0415
        ExternalRelativeVolumeQueuePolicy,
    )

    with tempfile.NamedTemporaryFile(
        suffix=".json", dir=provider, delete=False, mode="w", encoding="utf-8"
    ) as handle:
        json.dump(new_snapshot, handle, separators=(",", ":"))
        scratch = Path(handle.name)
    os.chmod(scratch, 0o600)
    try:
        config = _ProviderConfig(
            organization_id=str(snapshot["organizationId"]),
            key_registry_path=provider / "authority-keys.json",
            snapshot_path=scratch,
            catalog_administration_actor_id="catalog-admin",
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(seconds=60),
                deadline_after_issue=timedelta(seconds=3600),
                max_attempts=3,
                max_active_requests_per_organization=2,
            ),
        )
        verified = _snapshot_from_path(config, clock=lambda: datetime.now(UTC))
    finally:
        scratch.unlink(missing_ok=True)
    assert verified.sequence == next_sequence
    print(f"preflight OK (loader digest {verified.digest})")

    state = {
        "renewedAt": issued,
        "sequence": next_sequence,
        "snapshotDigest": _snapshot_digest(new_snapshot),
        "policyVersion": new_version,
        "policyDigest": policy.policy_digest,
        "policyAuthorityRecordDigest": record.digest,
        "addedSubjectDigests": appended_subject_digests,
        "contextDigests": [row.context_digest for row in fresh_contexts],
        "catalogAuthorityDigest": None if catalog_authority is None else catalog_authority.digest,
    }
    if args.check_only:
        print("check-only: no files were written")
        if args.state_file:
            _write_private_json(args.state_file, state)
        return 0

    _write_private_json(policy_path, policy.model_dump(by_alias=True, mode="json"))
    if catalog_payload is not None:
        _write_private_json(catalog_path, catalog_payload)
    _write_private_json(snapshot_path, new_snapshot)
    print("files written (policy/catalog/snapshot)")

    if args.reload_url is not None:
        if not args.admin_token:
            raise SystemExit("--reload-url requires --admin-token")
        import httpx  # noqa: PLC0415

        response = httpx.post(
            f"{args.reload_url.rstrip('/')}/v1/operations/external-authority/reload",
            headers={"Authorization": f"Bearer {args.admin_token}"},
            json={},
            timeout=60.0,
        )
        print(f"reload: {response.status_code} {response.text[:200]}")
        response.raise_for_status()
        state["reloadStatus"] = response.status_code

    if args.state_file:
        _write_private_json(args.state_file, state)
    print(json.dumps(state, indent=1, ensure_ascii=False))
    print(
        "note: dependent mappings must be re-admitted against the renewed catalog "
        "authority (the Core binds the catalog body at boot)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
