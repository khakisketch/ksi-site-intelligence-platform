"""Strict production wiring for the external quantitative authority catalog.

The configuration file names private paths only.  Its catalog envelope carries
an authority-record digest, never an authority record; the injected authority
port is the sole source of approval for the catalog's canonical body.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_relative_volume import ExternalRelativeVolumeExecutionPolicyV1

from ksi_core.durable_journal import DurableJournal
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence_validations import (
    EvidenceMeasurementContextAuthorityPort,
    ExternalEvidenceValidationStore,
)
from ksi_core.external_quantitative_authority import (
    ExternalQuantitativeAuthorityCatalog,
    ExternalQuantitativeAuthorityParticipants,
    ExternalQuantitativeCatalogAuthorityBinding,
    ExternalQuantitativeCatalogAuthorityCurrentnessPort,
    ExternalQuantitativeCatalogAuthorityPort,
    ExternalQuantitativeExecutionTemplate,
)
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_relative_volume_authorities import ExternalRelativeVolumeAuthorityPort
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeInputCapabilityIssuer,
    ExternalRelativeVolumeQueuePolicy,
)
from ksi_core.external_result_workflow_assembly import (
    ExternalRelativeVolumeInputCapabilityFactory,
    ExternalRelativeVolumeRuntimeAuthorities,
    ExternalResultWorkflowAssemblyConfig,
)
from ksi_core.external_use_decisions import ExternalUseDecisionStore
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityCurrentnessPort,
    PolicyAuthorityPort,
)
from ksi_core.work_areas import WorkAreaStore

_CONFIG_VERSION = "external-result-workflow-config.v1"
_CATALOG_VERSION = "external-quantitative-catalog.v1"
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_CATALOG_BYTES = 1024 * 1024
_DIGEST_PREFIX = "sha256:"


class ExternalQuantitativeWorkflowConfigBlockedCode(StrEnum):
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_SYNTAX = "CONFIG_SYNTAX"
    CONFIG_VALUE = "CONFIG_VALUE"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    CATALOG = "CATALOG"
    CATALOG_AUTHORITY = "CATALOG_AUTHORITY"


class ExternalQuantitativeWorkflowConfigUnavailable(RuntimeError):
    """A quantitative workflow must remain absent when its authority cannot be read."""

    def __init__(self, code: ExternalQuantitativeWorkflowConfigBlockedCode) -> None:
        self.code = code
        super().__init__("external quantitative workflow configuration blocked: " + code.value)


@dataclass(frozen=True, slots=True)
class ExternalQuantitativeWorkflowParticipants:
    """Non-configurable Core dependencies for a catalog-approved workflow."""

    catalog_authority_port: ExternalQuantitativeCatalogAuthorityPort
    catalog_administration_actor_id: str
    queue_policy: ExternalRelativeVolumeQueuePolicy
    clock: Callable[[], datetime]
    build_catalog_authority_currentness: (
        Callable[
            [ExternalAuthorityCurrentnessCoordinator],
            ExternalQuantitativeCatalogAuthorityCurrentnessPort,
        ]
        | None
    ) = None
    policy_authority_port: PolicyAuthorityPort | None = None
    build_policy_authority_currentness: (
        Callable[[ExternalAuthorityCurrentnessCoordinator], PolicyAuthorityCurrentnessPort] | None
    ) = None
    build_evidence_context_authority: (
        Callable[[ExternalAuthorityCurrentnessCoordinator], EvidenceMeasurementContextAuthorityPort]
        | None
    ) = None

    def __post_init__(self) -> None:
        if not callable(getattr(self.catalog_authority_port, "resolve", None)):
            raise ValueError("quantitative workflow requires a catalog authority port")
        if (
            not self.catalog_administration_actor_id
            or self.catalog_administration_actor_id != self.catalog_administration_actor_id.strip()
        ):
            raise ValueError("quantitative workflow requires a catalog administration actor")
        if not isinstance(self.queue_policy, ExternalRelativeVolumeQueuePolicy):
            raise ValueError("quantitative workflow requires an explicit queue policy")
        if not callable(self.clock):
            raise ValueError("quantitative workflow requires a clock")
        if self.build_catalog_authority_currentness is not None and not callable(
            self.build_catalog_authority_currentness
        ):
            raise ValueError("quantitative workflow requires a catalog currentness factory")
        if self.policy_authority_port is not None and not callable(
            getattr(self.policy_authority_port, "resolve", None)
        ):
            raise ValueError("quantitative workflow requires a policy authority port")
        if self.policy_authority_port is not None and not callable(
            getattr(self.policy_authority_port, "resolve_historical", None)
        ):
            raise ValueError("quantitative workflow requires policy historical resolution")
        if self.build_policy_authority_currentness is not None and not callable(
            self.build_policy_authority_currentness
        ):
            raise ValueError("quantitative workflow requires a policy currentness factory")
        if self.build_evidence_context_authority is not None and not callable(
            self.build_evidence_context_authority
        ):
            raise ValueError("quantitative workflow requires an evidence context authority factory")


@dataclass(frozen=True, slots=True)
class _Catalog:
    authority_journal_path: Path
    body_digest: str
    authority_record_digest: str
    organization_id: str
    template: ExternalQuantitativeExecutionTemplate


@dataclass(frozen=True, slots=True)
class _AuthorityJournalBundleIdentity:
    """The protected path identities that must survive tracked opening."""

    journal: tuple[int, int]
    lock: tuple[int, int]
    segments: tuple[tuple[Path, int, int], ...]
    directories: tuple[tuple[Path, int, int], ...]


def load_external_result_workflow_config(
    path: Path,
    *,
    participants: ExternalQuantitativeWorkflowParticipants,
    input_capability_issuer: ExternalRelativeVolumeInputCapabilityIssuer | None = None,
    build_input_capability_issuer: ExternalRelativeVolumeInputCapabilityFactory | None = None,
) -> ExternalResultWorkflowAssemblyConfig:
    """Load one exact catalog and produce closures for the common assembly.

    The catalog body intentionally excludes its approval pointer.  That avoids
    self-referential digest construction: the immutable authority record binds
    the complete numeric body, while the outer envelope binds that record by
    digest.  The loader attaches the resolved record digest to each execution
    policy before sealing it.
    """

    if not isinstance(participants, ExternalQuantitativeWorkflowParticipants):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_VALUE
        )
    if (input_capability_issuer is None) == (build_input_capability_issuer is None) or not callable(
        input_capability_issuer
        if input_capability_issuer is not None
        else build_input_capability_issuer
    ):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_VALUE
        )
    if (
        participants.policy_authority_port is None
        or not callable(getattr(participants.policy_authority_port, "resolve", None))
        or not callable(getattr(participants.policy_authority_port, "resolve_historical", None))
        or participants.build_policy_authority_currentness is None
        or not callable(participants.build_policy_authority_currentness)
        or participants.build_evidence_context_authority is None
        or not callable(participants.build_evidence_context_authority)
        or participants.build_catalog_authority_currentness is None
        or not callable(participants.build_catalog_authority_currentness)
    ):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_VALUE
        )
    config = _parse_json(
        _read_private(path, maximum_bytes=_MAX_CONFIG_BYTES),
        file_code=ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE,
    )
    try:
        config_body = _mapping(
            config,
            {"version", "authorityJournalPath", "catalogPath"},
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        if _text(config_body["version"]) != _CONFIG_VERSION:
            raise ValueError("unknown workflow configuration version")
        authority_journal_path = _absolute_path(config_body["authorityJournalPath"])
        _validate_authority_journal_bundle(authority_journal_path, create_missing=False)
        catalog_path = _absolute_path(config_body["catalogPath"])
    except ExternalQuantitativeWorkflowConfigUnavailable:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_VALUE
        ) from exc

    catalog_raw = _parse_json(
        _read_private(catalog_path, maximum_bytes=_MAX_CATALOG_BYTES),
        file_code=ExternalQuantitativeWorkflowConfigBlockedCode.CATALOG,
    )
    catalog = _parse_catalog(
        catalog_raw,
        authority_journal_path=authority_journal_path,
        participants=participants,
    )
    return _workflow_config(
        catalog, participants, input_capability_issuer, build_input_capability_issuer
    )


def _workflow_config(
    catalog: _Catalog,
    participants: ExternalQuantitativeWorkflowParticipants,
    input_capability_issuer: ExternalRelativeVolumeInputCapabilityIssuer | None,
    build_input_capability_issuer: ExternalRelativeVolumeInputCapabilityFactory | None,
) -> ExternalResultWorkflowAssemblyConfig:
    instance: ExternalQuantitativeAuthorityCatalog | None = None

    def build_mapping(
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
        work_areas: WorkAreaStore,
        open_authority_journal: Callable[[Path], DurableJournal],
    ) -> ExternalRelativeVolumeAuthorityPort:
        nonlocal instance
        if (
            reconstruction.coordinator is not coordinator
            or inspections.coordinator is not coordinator
            or policy_registry.coordinator is not coordinator
            or evidence_validations.coordinator is not coordinator
            or work_areas.coordinator is not coordinator
            or not callable(open_authority_journal)
        ):
            raise ValueError("quantitative workflow participants must share the Core coordinator")
        if instance is not None:
            if instance.currentness_coordinator is not coordinator:
                raise ValueError("quantitative workflow catalog cannot cross coordinators")
            return instance
        currentness_factory = participants.build_catalog_authority_currentness
        if currentness_factory is None:
            raise ValueError("quantitative workflow catalog currentness factory is missing")
        currentness_port = currentness_factory(coordinator)
        if (
            currentness_port is None
            or currentness_port.coordinator is not coordinator
            or not callable(getattr(currentness_port, "is_current", None))
        ):
            raise ValueError(
                "quantitative workflow catalog currentness must share the Core coordinator"
            )
        binding = ExternalQuantitativeCatalogAuthorityBinding(
            authority_port=participants.catalog_authority_port,
            catalog_body_digest=catalog.body_digest,
            organization_id=catalog.organization_id,
            administration_actor_id=participants.catalog_administration_actor_id,
            currentness_port=currentness_port,
        )

        def template_for(
            record: object, now: datetime
        ) -> ExternalQuantitativeExecutionTemplate | None:
            from ksi_core.external_quantitative_authority import (
                ExternalQuantitativeCompatibilityRecord,
            )

            if not isinstance(record, ExternalQuantitativeCompatibilityRecord):
                return None
            if (
                record.execution_policy_ref != catalog.authority_record_digest
                or not binding.permits(record, now)
                or not (catalog.template.valid_from <= now < catalog.template.valid_until)
            ):
                return None
            return catalog.template

        instance = ExternalQuantitativeAuthorityCatalog(
            _open_protected_authority_journal(
                open_authority_journal, catalog.authority_journal_path
            ),
            currentness_coordinator=coordinator,
            participants=ExternalQuantitativeAuthorityParticipants(
                reconstruction=reconstruction,
                inspections=inspections,
                policy_registry=policy_registry,
                evidence_validations=evidence_validations,
                work_areas=work_areas,
                catalog_authority=binding,
            ),
            execution_template_resolver=template_for,
        )
        return instance

    def build_runtime(
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        decisions: ExternalUseDecisionStore,
        mapping: ExternalRelativeVolumeAuthorityPort,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        policy_registry: ExternalValidationPolicyRegistry,
        evidence_validations: ExternalEvidenceValidationStore,
    ) -> ExternalRelativeVolumeRuntimeAuthorities:
        del reconstruction, inspections, policy_registry, evidence_validations
        if (
            instance is None
            or mapping is not instance
            or instance.currentness_coordinator is not coordinator
            or decisions.coordinator is not coordinator
        ):
            raise ValueError("quantitative workflow runtime requires its exact mapping catalog")
        instance.bind_decision_store(decisions)
        return ExternalRelativeVolumeRuntimeAuthorities(
            execution=instance, historical_use=instance,
            activate_execution=instance.activate_execution,
        )

    return ExternalResultWorkflowAssemblyConfig(
        build_mapping=build_mapping,
        build_runtime=build_runtime,
        queue_policy=participants.queue_policy,
        input_capability_issuer=input_capability_issuer,
        build_input_capability_issuer=build_input_capability_issuer,
        policy_authority_port=participants.policy_authority_port,
        build_policy_authority_currentness=participants.build_policy_authority_currentness,
        build_evidence_context_authority=participants.build_evidence_context_authority,
    )


def _parse_catalog(
    raw: object,
    *,
    authority_journal_path: Path,
    participants: ExternalQuantitativeWorkflowParticipants,
) -> _Catalog:
    try:
        envelope = _mapping(
            raw,
            {"version", "authorityRecordDigest", "body"},
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        if _text(envelope["version"]) != _CATALOG_VERSION:
            raise ValueError("unknown quantitative catalog version")
        authority_record_digest = _digest(envelope["authorityRecordDigest"])
        admission_body = _catalog_admission_body(envelope, authority_record_digest)
        body = _mapping(
            envelope["body"],
            {"organizationId", "executionTemplates"},
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        organization_id = _text(body["organizationId"])
        body_digest = _catalog_admission_body_digest(admission_body)
        now = participants.clock()
        _utc(now)
        authority = participants.catalog_authority_port.resolve(authority_record_digest, now)
        if (
            authority is None
            or authority.digest != authority_record_digest
            or not authority.permits_catalog(
                catalog_body_digest=body_digest,
                organization_id=organization_id,
                administration_actor_id=participants.catalog_administration_actor_id,
                now=now,
            )
        ):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CATALOG_AUTHORITY
            )
        templates = body["executionTemplates"]
        if not isinstance(templates, list) or len(templates) != 1:
            raise ValueError("V1 quantitative catalog requires exactly one execution template")
        template = _parse_template(templates[0], authority_record_digest)
        return _Catalog(
            authority_journal_path=authority_journal_path,
            body_digest=body_digest,
            authority_record_digest=authority_record_digest,
            organization_id=organization_id,
            template=template,
        )
    except ExternalQuantitativeWorkflowConfigUnavailable:
        raise
    except Exception as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CATALOG
        ) from exc


def _parse_template(
    raw: object, authority_record_digest: str
) -> ExternalQuantitativeExecutionTemplate:
    template = _mapping(
        raw,
        {
            "executionPolicy",
            "authorizedActorIds",
            "validFrom",
            "validUntil",
            "maximumZoneCellCount",
            "maximumZoneAreaM2",
        },
        unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
    )
    policy_body = _mapping(
        template["executionPolicy"],
        {
            "contractVersion",
            "policyId",
            "version",
            "algorithmBuildDigest",
            "configDigest",
            "thresholdM",
            "minimumCommonValidFraction",
            "uncertaintyMethod",
            "resourceEnvelopeDigest",
            "authorityRecordDigest",
            "syntheticTestOnly",
        },
        unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
    )
    if policy_body["authorityRecordDigest"] != authority_record_digest:
        raise ValueError("catalog execution policy authority reference does not match catalog")
    policy = ExternalRelativeVolumeExecutionPolicyV1.model_validate(policy_body).sealed()
    actor_ids = template["authorizedActorIds"]
    if (
        not isinstance(actor_ids, list)
        or not actor_ids
        or any(
            not isinstance(actor, str) or not actor or actor != actor.strip() for actor in actor_ids
        )
        or len(set(actor_ids)) != len(actor_ids)
    ):
        raise ValueError("catalog execution actors are invalid")
    return ExternalQuantitativeExecutionTemplate(
        execution_policy=policy,
        authorized_actor_ids=frozenset(actor_ids),
        valid_from=_parse_time(template["validFrom"]),
        valid_until=_parse_time(template["validUntil"]),
        maximum_zone_cell_count=_positive_integer(template["maximumZoneCellCount"]),
        maximum_zone_area_m2=_positive_float(template["maximumZoneAreaM2"]),
    )


def _read_private(path: Path, *, maximum_bytes: int) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute() or _has_symlink_component(path):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        )
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    try:
        node = os.fstat(descriptor)
        if (
            not stat.S_ISREG(node.st_mode)
            or node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or (node.st_mode & 0o777) != 0o600
            or node.st_nlink != 1
        ):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
        return _read_bounded(descriptor, maximum_bytes)
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    finally:
        os.close(descriptor)


def _validate_authority_journal_bundle(path: Path, *, create_missing: bool) -> None:
    """Require the configured authority journal and DurableJournal companions to be private.

    ``DurableJournal`` is intentionally domain-neutral and cannot know that this
    authority journal may be configured outside the normal private data root.
    The workflow boundary therefore validates existing nodes and creates only
    missing private nodes before the tracked opener can replay or append.
    """
    if not isinstance(path, Path) or not path.is_absolute() or _has_symlink_component(path):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        )
    _validate_journal_parent(path.parent)
    nodes = [path, path.with_suffix(path.suffix + ".lock"), *_journal_segments(path)]
    for node in nodes:
        if not _private_regular_file(node):
            if node.exists() or node.is_symlink():
                raise ExternalQuantitativeWorkflowConfigUnavailable(
                    ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
                )
            if create_missing and node in {path, path.with_suffix(path.suffix + ".lock")}:
                _create_private_journal_node(node)
            elif node.exists() or node.is_symlink():
                raise ExternalQuantitativeWorkflowConfigUnavailable(
                    ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
                )
    # Creation can race only with the configured owner in a protected parent;
    # still re-stat every node before handing it to the generic journal opener.
    for node in [path, path.with_suffix(path.suffix + ".lock"), *_journal_segments(path)]:
        if node.exists() and not _private_regular_file(node):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )


def _open_protected_authority_journal(
    opener: Callable[[Path], DurableJournal], path: Path
) -> DurableJournal:
    _validate_authority_journal_bundle(path, create_missing=True)
    expected = _authority_journal_bundle_identity(path)
    journal = opener(path)
    try:
        _validate_authority_journal_bundle(path, create_missing=False)
        if _authority_journal_bundle_identity(path) != expected:
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
    except BaseException:
        journal.close()
        raise
    return journal


def _validate_journal_parent(directory: Path) -> None:
    for current in _journal_parent_chain(directory):
        try:
            node = os.lstat(current)
        except OSError as exc:
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            ) from exc
        mode = node.st_mode
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
        if node.st_uid not in {os.geteuid(), 0}:
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
        writable_by_others = mode & 0o022
        if writable_by_others and not (mode & stat.S_ISVTX):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )


def _journal_parent_chain(directory: Path) -> tuple[Path, ...]:
    parents: list[Path] = []
    current = directory
    while True:
        parents.append(current)
        if current == current.parent:
            return tuple(parents)
        current = current.parent


def _authority_journal_bundle_identity(path: Path) -> _AuthorityJournalBundleIdentity:
    """Snapshot exact journal files and trusted directory chain after validation."""
    _validate_authority_journal_bundle(path, create_missing=False)
    lock = path.with_suffix(path.suffix + ".lock")
    return _AuthorityJournalBundleIdentity(
        journal=_private_node_identity(path),
        lock=_private_node_identity(lock),
        segments=tuple(
            (segment, *_private_node_identity(segment)) for segment in _journal_segments(path)
        ),
        directories=tuple(
            (directory, *_directory_identity(directory))
            for directory in _journal_parent_chain(path.parent)
        ),
    )


def _private_node_identity(path: Path) -> tuple[int, int]:
    if not _private_regular_file(path):
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        )
    try:
        node = os.lstat(path)
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    return node.st_dev, node.st_ino


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        node = os.lstat(path)
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    return node.st_dev, node.st_ino


def _private_regular_file(path: Path) -> bool:
    try:
        node = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    return bool(
        stat.S_ISREG(node.st_mode)
        and not stat.S_ISLNK(node.st_mode)
        and node.st_uid == os.geteuid()
        and node.st_gid == os.getegid()
        and (node.st_mode & 0o777) == 0o600
        and node.st_nlink == 1
    )


def _create_private_journal_node(path: Path) -> None:
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
    except FileExistsError:
        if not _private_regular_file(path):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            ) from None
        return
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    try:
        if not _private_regular_file(path):
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
        os.fsync(descriptor)
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    finally:
        os.close(descriptor)


def _journal_segments(path: Path) -> tuple[Path, ...]:
    try:
        candidates = tuple(path.parent.glob(f"{path.stem}.*{path.suffix}"))
    except OSError as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
        ) from exc
    return tuple(
        sorted(
            candidate
            for candidate in candidates
            if candidate.name.removeprefix(path.stem + ".").removesuffix(path.suffix).isdigit()
        )
    )


def _read_bounded(descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(8192, maximum_bytes - observed + 1))
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > maximum_bytes:
            raise ExternalQuantitativeWorkflowConfigUnavailable(
                ExternalQuantitativeWorkflowConfigBlockedCode.CONFIG_FILE
            )
        chunks.append(chunk)


def _parse_json(raw: bytes, *, file_code: ExternalQuantitativeWorkflowConfigBlockedCode) -> object:
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(file_code) from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _mapping(
    value: object,
    expected: set[str],
    *,
    unknown_code: ExternalQuantitativeWorkflowConfigBlockedCode,
) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("expected an object")
    keys = set(value)
    if keys - expected:
        raise ExternalQuantitativeWorkflowConfigUnavailable(unknown_code)
    if keys != expected:
        raise ValueError("object fields are incomplete")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 4096:
        raise ValueError("text is invalid")
    return value


def _digest(value: object) -> str:
    text = _text(value)
    if len(text) != 71 or not text.startswith(_DIGEST_PREFIX):
        raise ValueError("digest is invalid")
    if any(char not in "0123456789abcdef" for char in text[len(_DIGEST_PREFIX) :]):
        raise ValueError("digest is invalid")
    return text


def _absolute_path(value: object) -> Path:
    text = _text(value)
    path = Path(text)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\x00" in text
        or _has_symlink_component(path)
    ):
        raise ValueError("path is not a safe absolute path")
    return path


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return True
    return False


def catalog_admission_body_digest(catalog: object) -> str:
    """Digest the one allowed self-reference-free catalog admission body.

    The catalog authority record cannot include its own sealed digest.  This
    projection removes exactly the outer approval pointer and the matching
    execution-policy pointer; any absent, extra, or unequal field is rejected
    instead of becoming an arbitrary caller-controlled exclusion.
    """
    try:
        envelope = _mapping(
            catalog,
            {"version", "authorityRecordDigest", "body"},
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        if _text(envelope["version"]) != _CATALOG_VERSION:
            raise ValueError("unknown quantitative catalog version")
        return _catalog_admission_body_digest(
            _catalog_admission_body(envelope, _digest(envelope["authorityRecordDigest"]))
        )
    except ExternalQuantitativeWorkflowConfigUnavailable:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalQuantitativeWorkflowConfigUnavailable(
            ExternalQuantitativeWorkflowConfigBlockedCode.CATALOG
        ) from exc


def _catalog_admission_body(
    envelope: dict[str, object], authority_record_digest: str
) -> dict[str, object]:
    body = _mapping(
        envelope["body"],
        {"organizationId", "executionTemplates"},
        unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
    )
    organization_id = _text(body["organizationId"])
    templates = body["executionTemplates"]
    if not isinstance(templates, list) or len(templates) != 1:
        raise ValueError("V1 quantitative catalog requires exactly one execution template")
    admission_templates: list[dict[str, object]] = []
    for raw_template in templates:
        template = _mapping(
            raw_template,
            {
                "executionPolicy",
                "authorizedActorIds",
                "validFrom",
                "validUntil",
                "maximumZoneCellCount",
                "maximumZoneAreaM2",
            },
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        policy = _mapping(
            template["executionPolicy"],
            {
                "contractVersion",
                "policyId",
                "version",
                "algorithmBuildDigest",
                "configDigest",
                "thresholdM",
                "minimumCommonValidFraction",
                "uncertaintyMethod",
                "resourceEnvelopeDigest",
                "authorityRecordDigest",
                "syntheticTestOnly",
            },
            unknown_code=ExternalQuantitativeWorkflowConfigBlockedCode.UNKNOWN_FIELD,
        )
        if _digest(policy["authorityRecordDigest"]) != authority_record_digest:
            raise ValueError("catalog execution policy authority reference does not match catalog")
        admission_templates.append(
            {
                **template,
                "executionPolicy": {
                    key: value for key, value in policy.items() if key != "authorityRecordDigest"
                },
            }
        )
    return {"organizationId": organization_id, "executionTemplates": admission_templates}


def _catalog_admission_body_digest(body: dict[str, object]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {"domain": "ksi.external-quantitative-catalog.v1", "catalog": body}
            )
        ).hexdigest()
    )


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("time must be UTC-aware")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(parsed)
    return parsed


def _positive_integer(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("positive integer is required")
    return value


def _positive_float(value: object) -> float:
    if type(value) is not float or value <= 0.0 or value != value or value == float("inf"):
        raise ValueError("positive finite float is required")
    return value


__all__ = [
    "ExternalQuantitativeWorkflowConfigBlockedCode",
    "ExternalQuantitativeWorkflowConfigUnavailable",
    "ExternalQuantitativeWorkflowParticipants",
    "catalog_admission_body_digest",
    "load_external_result_workflow_config",
]
