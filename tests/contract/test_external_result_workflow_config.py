"""Production configuration gates for external quantitative authority."""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self, cast

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_quantitative_authority import (
    ExternalQuantitativeCatalogAuthorityRecord,
)
from ksi_core.external_relative_volumes import ExternalRelativeVolumeQueuePolicy
from ksi_core.external_result_workflow_config import ExternalQuantitativeWorkflowParticipants
from ksi_core.external_validation_policy import PolicyAuthorityRecord
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeExecutionPolicyV1


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def test_catalog_authority_record_is_domain_sealed_and_time_bounded() -> None:
    """Catalog bytes cannot self-approve outside the injected authority boundary."""
    now = datetime(2026, 9, 9, tzinfo=UTC)
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_digest("catalog-body"),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=now - timedelta(minutes=1),
        active_until=now + timedelta(minutes=1),
        synthetic_test_only=False,
    ).sealed()

    assert record.digest == record.canonical_digest()
    assert record.is_active_at(now)
    assert not record.is_active_at(now + timedelta(minutes=1))


def _write_private(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)


def _execution_policy(authority_record_digest: str) -> ExternalRelativeVolumeExecutionPolicyV1:
    return ExternalRelativeVolumeExecutionPolicyV1(
        policy_id="execution-policy-a",
        version=1,
        algorithm_build_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        threshold_m=0.1,
        minimum_common_valid_fraction=0.8,
        uncertainty_method="INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
        resource_envelope_digest=_digest("resource-envelope"),
        authority_record_digest=authority_record_digest,
        synthetic_test_only=False,
    ).sealed()


def _catalog_policy_body(authority_record_digest: str | None = None) -> dict[str, object]:
    policy = _execution_policy(authority_record_digest or _digest("placeholder-authority"))
    body = policy.model_dump(by_alias=True, mode="json")
    body.pop("policyDigest")
    if authority_record_digest is None:
        body.pop("authorityRecordDigest")
    return body


def _catalog_body(authority_record_digest: str | None = None) -> dict[str, object]:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    return {
        "organizationId": "org-a",
        "executionTemplates": [
            {
                "executionPolicy": _catalog_policy_body(authority_record_digest),
                "authorizedActorIds": ["operator-a"],
                "validFrom": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "maximumZoneCellCount": 1000,
                "maximumZoneAreaM2": 1000.0,
            }
        ],
    }


def _catalog_digest(body: dict[str, object]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {"domain": "ksi.external-quantitative-catalog.v1", "catalog": body}
            )
        ).hexdigest()
    )


class _CatalogAuthority:
    def __init__(self, record: ExternalQuantitativeCatalogAuthorityRecord) -> None:
        self._record = record
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> Self:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(
        self, authority_record_digest: str, now: datetime
    ) -> ExternalQuantitativeCatalogAuthorityRecord | None:
        del now
        return self._record if authority_record_digest == self._record.digest else None

    def is_current(self, record: ExternalQuantitativeCatalogAuthorityRecord, now: datetime) -> bool:
        return record == self._record and record.is_active_at(now)


class _UnavailablePolicyAuthority:
    def resolve(
        self, authority_record_digest: str, now: datetime
    ) -> PolicyAuthorityRecord | None:
        del authority_record_digest, now
        return None


class _UnavailableEvidenceContextAuthority:
    def __init__(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def resolve_for_validation(self, **_kwargs: object) -> None:
        return None

    def resolve_historical_for_validation(self, **_kwargs: object) -> None:
        return None

    def is_current(self, context: object) -> bool:
        del context
        return False


def _participants(
    record: ExternalQuantitativeCatalogAuthorityRecord,
) -> ExternalQuantitativeWorkflowParticipants:
    catalog_authority = _CatalogAuthority(record)
    return ExternalQuantitativeWorkflowParticipants(
        catalog_authority_port=catalog_authority,
        catalog_administration_actor_id="catalog-admin",
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=5),
            deadline_after_issue=timedelta(seconds=30),
            max_attempts=1,
            max_active_requests_per_organization=2,
        ),
        clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
        build_catalog_authority_currentness=catalog_authority.bind,
        policy_authority_port=_UnavailablePolicyAuthority(),
        build_evidence_context_authority=_UnavailableEvidenceContextAuthority,
    )


def _approved_files(tmp_path: Path) -> tuple[Path, ExternalQuantitativeWorkflowParticipants]:
    admission_body = _catalog_body()
    record = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=_catalog_digest(admission_body),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=datetime(2026, 9, 9, tzinfo=UTC) - timedelta(minutes=1),
        active_until=datetime(2026, 9, 9, tzinfo=UTC) + timedelta(minutes=1),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    body = _catalog_body(record.digest)
    catalog = {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": record.digest,
        "body": body,
    }
    catalog_path = tmp_path / "catalog.json"
    _write_private(catalog_path, catalog)
    config_path = tmp_path / "workflow.json"
    _write_private(
        config_path,
        {
            "version": "external-result-workflow-config.v1",
            "authorityJournalPath": str(tmp_path / "authority.jsonl"),
            "catalogPath": str(catalog_path),
        },
    )
    return config_path, _participants(record)


def test_loader_builds_workflow_only_from_an_exact_approved_catalog(tmp_path: Path) -> None:
    """The protected path selects a preapproved body; it cannot create authority."""
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config

    config_path, participants = _approved_files(tmp_path)
    workflow = load_external_result_workflow_config(
        config_path,
        participants=participants,
        input_capability_issuer=lambda *_args, **_kwargs: None,
    )

    assert callable(workflow.build_mapping)
    assert callable(workflow.build_runtime)


def test_loader_accepts_deferred_real_storage_issuer(tmp_path: Path) -> None:
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.external_result_workflow_config import load_external_result_workflow_config

    config_path, participants = _approved_files(tmp_path)
    workflow = load_external_result_workflow_config(
        config_path,
        participants=participants,
        build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    assert workflow.input_capability_issuer is None
    assert workflow.build_input_capability_issuer is ExternalRelativeVolumeS3InputCapabilityIssuer


def test_loader_rejects_competing_issuer_sources_before_opening_files(tmp_path: Path) -> None:
    from ksi_core.external_relative_volume_s3_capabilities import (
        ExternalRelativeVolumeS3InputCapabilityIssuer,
    )
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    _, participants = _approved_files(tmp_path)
    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable) as error:
        load_external_result_workflow_config(
            tmp_path / "absent.json",
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )
    assert error.value.code.value == "CONFIG_VALUE"


@pytest.mark.parametrize("mode", (0o666, 0o640))
def test_loader_rejects_existing_nonprivate_authority_journal(tmp_path: Path, mode: int) -> None:
    """A private config cannot bless a mutable configured authority journal."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigBlockedCode,
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    journal = tmp_path / "authority.jsonl"
    journal.write_text("{}\n", encoding="utf-8")
    journal.chmod(mode)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable) as raised:
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
    assert raised.value.code is ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE


def test_loader_rejects_authority_journal_under_writable_parent(tmp_path: Path) -> None:
    """The journal's directory remains part of its tamper boundary."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigBlockedCode,
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["authorityJournalPath"] = str(shared / "authority.jsonl")
    _write_private(config_path, config)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable) as raised:
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
    assert raised.value.code is ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE


@pytest.mark.parametrize("kind", ("hardlink", "symlink", "fifo"))
def test_loader_rejects_nonprivate_authority_journal_nodes(tmp_path: Path, kind: str) -> None:
    """Links and non-regular journal nodes cannot become replay authority."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigBlockedCode,
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    journal = tmp_path / "authority.jsonl"
    target = tmp_path / "other.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o600)
    if kind == "hardlink":
        os.link(target, journal)
    elif kind == "symlink":
        journal.symlink_to(target)
    else:
        os.mkfifo(journal, 0o600)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable) as raised:
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
    expected = (
        ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_VALUE
        if kind == "symlink"
        else ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
    )
    assert raised.value.code is expected


def test_protected_opener_rechecks_a_replaced_authority_journal(tmp_path: Path) -> None:
    """The tracked-opener boundary rejects a path replaced after its first check."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigBlockedCode,
        ExternalQuantitativeWorkflowConfigUnavailable,
        _open_protected_authority_journal,
    )

    journal = tmp_path / "authority.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text("{}\n", encoding="utf-8")
    replacement.chmod(0o600)

    class _ReplacedJournal:
        def close(self) -> None:
            return None

    def replace_path(path: Path) -> _ReplacedJournal:
        path.unlink()
        path.symlink_to(replacement)
        return _ReplacedJournal()

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable) as raised:
        _open_protected_authority_journal(
            cast(Callable[[Path], DurableJournal], replace_path), journal
        )
    assert raised.value.code is ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE


def test_protected_journal_rejects_foreign_owned_parent_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-root foreign owner can replace its private-looking descendant tree."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        _validate_authority_journal_bundle,
    )

    parent = tmp_path / "foreign-owner"
    parent.mkdir(mode=0o755)
    journal = parent / "authority.jsonl"
    journal.write_text("", encoding="utf-8")
    journal.chmod(0o600)
    actual_lstat = os.lstat

    def foreign_lstat(value: str | Path) -> os.stat_result:
        node = actual_lstat(value)
        if Path(value) == parent:
            metadata = list(node)
            metadata[4] = os.geteuid() + 10_000
            return os.stat_result(metadata)
        return node

    monkeypatch.setattr(os, "lstat", foreign_lstat)
    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        _validate_authority_journal_bundle(journal, create_missing=False)


def test_protected_opener_rejects_regular_private_journal_replacement(tmp_path: Path) -> None:
    """A replacement must not detach the opened journal from its verified pathname."""
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        _open_protected_authority_journal,
    )

    journal = tmp_path / "authority.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text("", encoding="utf-8")
    replacement.chmod(0o600)
    opened: list[DurableJournal] = []

    def replace_journal(path: Path) -> DurableJournal:
        instance = DurableJournal(path)
        opened.append(instance)
        os.replace(replacement, path)
        return instance

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        _open_protected_authority_journal(replace_journal, journal)
    assert opened[0].sealed_reason == "closed"


def test_protected_opener_rejects_regular_private_lock_replacement(tmp_path: Path) -> None:
    """A replacement lock must not detach the held flock from its verified pathname."""
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        _open_protected_authority_journal,
    )

    journal = tmp_path / "authority.jsonl"
    lock = journal.with_suffix(journal.suffix + ".lock")
    replacement = tmp_path / "replacement.lock"
    replacement.write_text("", encoding="utf-8")
    replacement.chmod(0o600)
    opened: list[DurableJournal] = []

    def replace_lock(path: Path) -> DurableJournal:
        instance = DurableJournal(path)
        opened.append(instance)
        os.replace(replacement, lock)
        return instance

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        _open_protected_authority_journal(replace_lock, journal)
    assert opened[0].sealed_reason == "closed"


def test_protected_opener_rejects_retained_segment_membership_change(tmp_path: Path) -> None:
    """The checked segment set cannot gain an otherwise private retained file."""
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        _open_protected_authority_journal,
    )

    journal = tmp_path / "authority.jsonl"
    segment = tmp_path / "authority.0001.jsonl"
    opened: list[DurableJournal] = []

    def add_segment(path: Path) -> DurableJournal:
        instance = DurableJournal(path)
        opened.append(instance)
        segment.write_text("", encoding="utf-8")
        segment.chmod(0o600)
        return instance

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        _open_protected_authority_journal(add_segment, journal)
    assert opened[0].sealed_reason == "closed"


def test_protected_opener_rejects_verified_directory_replacement(tmp_path: Path) -> None:
    """A same-mode private directory replacement changes the protected pathname."""
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        _open_protected_authority_journal,
    )

    directory = tmp_path / "journal-parent"
    directory.mkdir(mode=0o700)
    journal = directory / "authority.jsonl"
    replacement = tmp_path / "replacement-parent"
    replacement.mkdir(mode=0o700)
    replacement_journal = replacement / journal.name
    replacement_lock = replacement / (journal.name + ".lock")
    for path in (replacement_journal, replacement_lock):
        path.write_text("", encoding="utf-8")
        path.chmod(0o600)
    parked = tmp_path / "parked-parent"
    opened: list[DurableJournal] = []

    def replace_directory(path: Path) -> DurableJournal:
        instance = DurableJournal(path)
        opened.append(instance)
        os.rename(directory, parked)
        os.rename(replacement, directory)
        return instance

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        _open_protected_authority_journal(replace_directory, journal)
    assert opened[0].sealed_reason == "closed"


def test_production_loader_rejects_missing_validation_authority_ports(tmp_path: Path) -> None:
    """A catalog approval alone cannot admit policy or evidence facts."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    participants = replace(
        participants,
        policy_authority_port=None,
        build_evidence_context_authority=None,
    )

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )


def test_catalog_authority_binds_only_the_strict_admission_body(tmp_path: Path) -> None:
    """Top-level and nested catalog-authority references are the only digest omissions."""
    from ksi_core.external_result_workflow_config import catalog_admission_body_digest

    config_path, participants = _approved_files(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["body"]["executionTemplates"][0]["executionPolicy"]["authorityRecordDigest"] = catalog[
        "authorityRecordDigest"
    ]

    authority_record = cast(_CatalogAuthority, participants.catalog_authority_port)._record
    assert catalog_admission_body_digest(catalog) == authority_record.catalog_body_digest
    assert config_path.is_absolute()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda policy: policy.pop("authorityRecordDigest"),
        lambda policy: policy.update(
            authorityRecordDigest=_digest("substituted-catalog-authority")
        ),
    ),
)
def test_loader_rejects_omitted_or_mismatched_nested_catalog_authority_reference(
    tmp_path: Path, mutation: Callable[[dict[str, object]], object]
) -> None:
    """Only the serializer may omit its own reference; final catalog references stay exact."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    mutation(catalog["body"]["executionTemplates"][0]["executionPolicy"])
    _write_private(catalog_path, catalog)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda config: config.update(organizationId="org-a"),
        lambda config: config.update(authorityRecordDigest=_digest("forbidden")),
        lambda config: config.update(maximumZoneCellCount=1),
    ),
)
def test_config_cannot_supply_catalog_facts_or_thresholds(
    tmp_path: Path, mutation: Callable[[dict[str, object]], object]
) -> None:
    """Organization, approval and numeric facts belong to the approved catalog, never config."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    mutation(config)
    _write_private(config_path, config)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    "prepare",
    (
        lambda config_path, _catalog_path: config_path.unlink(),
        lambda config_path, _catalog_path: config_path.chmod(0o640),
        lambda config_path, _catalog_path: config_path.write_text("{", encoding="utf-8"),
        lambda config_path, _catalog_path: config_path.write_bytes(b"x" * (256 * 1024 + 1)),
    ),
)
def test_loader_fails_closed_for_missing_mutable_or_malformed_config(
    tmp_path: Path, prepare: Callable[[Path, Path], object]
) -> None:
    """A private file path is an input boundary, never a permissive fallback."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    prepare(config_path, catalog_path)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize("target", ("config", "catalog"))
def test_loader_rejects_relative_and_symlinked_config_inputs(tmp_path: Path, target: str) -> None:
    """The loader must not follow a caller-controlled relative path or symlink."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    if target == "config":
        path = Path("workflow.json")
    else:
        link = tmp_path / "catalog-link.json"
        link.symlink_to(catalog_path)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["catalogPath"] = str(link)
        _write_private(config_path, config)
        path = config_path

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("status", "ACTIVE"),
        ("clientScope", "customer-selected"),
        ("externalProfile", "ksi-odm-civil-v1"),
    ),
)
def test_catalog_cannot_supply_status_client_scope_or_managed_profile(
    tmp_path: Path, field: str, value: str
) -> None:
    """The approved catalog is also strict: it cannot smuggle product policy facts."""
    from ksi_core.external_result_workflow_config import (
        ExternalQuantitativeWorkflowConfigUnavailable,
        load_external_result_workflow_config,
    )

    config_path, participants = _approved_files(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    policy = catalog["body"]["executionTemplates"][0]["executionPolicy"]
    policy[field] = value
    _write_private(catalog_path, catalog)

    with pytest.raises(ExternalQuantitativeWorkflowConfigUnavailable):
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
