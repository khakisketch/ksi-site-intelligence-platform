"""Closed, local durable attempt records for the external inspector.

This journal is intentionally not a Core journal or a wire contract.  It stores
only exact local resources that may be recovered, and every mutation is a
canonical JSON line fsynced while an advisory lock is held.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from ksi_domain.canonical_json import canonical_json_bytes

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_VERSION = "external-inspector-attempt.v1"
_EVENT_BASE_FIELDS = {
    "version",
    "timestamp",
    "phase",
    "attemptNonce",
    "bindingDigest",
    "previousEventDigest",
    "eventDigest",
}


class AttemptJournalError(RuntimeError):
    """A local attempt record is malformed, reordered, or cannot advance safely."""


class AttemptPhaseV1(StrEnum):
    INTENDED = "INTENDED"
    STAGING_ALLOCATED = "STAGING_ALLOCATED"
    INPUT_BOUND = "INPUT_BOUND"
    RUNTIME_PARENT_CREATING = "RUNTIME_PARENT_CREATING"
    RUNTIME_PARENT_BOUND = "RUNTIME_PARENT_BOUND"
    CONTAINER_CREATING = "CONTAINER_CREATING"
    CONTAINER_BOUND = "CONTAINER_BOUND"
    CLEANUP_REQUIRED = "CLEANUP_REQUIRED"
    STAGING_OWNERSHIP_UNCERTAIN = "STAGING_OWNERSHIP_UNCERTAIN"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    CLEANED = "CLEANED"


_EVENT_ADDITION_FIELDS: dict[AttemptPhaseV1, set[str]] = {
    AttemptPhaseV1.INTENDED: {"binding"},
    AttemptPhaseV1.STAGING_ALLOCATED: {"allocation"},
    AttemptPhaseV1.INPUT_BOUND: {"sealedInput"},
    AttemptPhaseV1.RUNTIME_PARENT_CREATING: set(),
    AttemptPhaseV1.RUNTIME_PARENT_BOUND: {"runtimeParent"},
    AttemptPhaseV1.CONTAINER_CREATING: set(),
    AttemptPhaseV1.CONTAINER_BOUND: {"runtimeId"},
    AttemptPhaseV1.CLEANUP_REQUIRED: {"disposition", "cleanupOrigin"},
    AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN: set(),
    AttemptPhaseV1.CLEANUP_FAILED: {"reason"},
    AttemptPhaseV1.CLEANED: set(),
}


@dataclass(frozen=True, slots=True)
class PrivateStagingRootV1:
    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int

    def __post_init__(self) -> None:
        if (self.mode & 0o777) != 0o700:
            raise ValueError("private staging root mode must be exactly 0700")
        _nonnegative(self.device, self.inode, self.owner_uid, self.owner_gid)

    def wire(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "ownerUid": self.owner_uid,
            "ownerGid": self.owner_gid,
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> PrivateStagingRootV1:
        _exact_keys(value, {"device", "inode", "mode", "ownerUid", "ownerGid"})
        return cls(
            device=_integer(value, "device"),
            inode=_integer(value, "inode"),
            mode=_integer(value, "mode"),
            owner_uid=_integer(value, "ownerUid"),
            owner_gid=_integer(value, "ownerGid"),
        )


@dataclass(frozen=True, slots=True)
class StagingFileIdentityV1:
    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int
    link_count: int
    size: int

    def __post_init__(self) -> None:
        _nonnegative(
            self.device,
            self.inode,
            self.owner_uid,
            self.owner_gid,
            self.link_count,
            self.size,
        )
        if self.link_count == 0:
            raise ValueError("staged identity link count must be positive")

    def wire(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "ownerUid": self.owner_uid,
            "ownerGid": self.owner_gid,
            "linkCount": self.link_count,
            "size": self.size,
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> StagingFileIdentityV1:
        _exact_keys(
            value,
            {"device", "inode", "mode", "ownerUid", "ownerGid", "linkCount", "size"},
        )
        return cls(
            device=_integer(value, "device"),
            inode=_integer(value, "inode"),
            mode=_integer(value, "mode"),
            owner_uid=_integer(value, "ownerUid"),
            owner_gid=_integer(value, "ownerGid"),
            link_count=_integer(value, "linkCount"),
            size=_integer(value, "size"),
        )


@dataclass(frozen=True, slots=True)
class StagingAllocationPlanV1:
    attempt_nonce: str
    binding_digest: str
    owner: str
    allocation_nonce: str
    root: PrivateStagingRootV1
    staging_name: str
    artifact_leaf: str
    provisional_marker_name: str
    committed_marker_name: str

    def __post_init__(self) -> None:
        _digest_value(self.binding_digest)
        for value in (
            self.attempt_nonce,
            self.owner,
            self.allocation_nonce,
            self.staging_name,
            self.artifact_leaf,
            self.provisional_marker_name,
            self.committed_marker_name,
        ):
            _safe_name(value)
        if self.artifact_leaf != "artifact":
            raise ValueError("staging artifact leaf is fixed")

    def marker_payload(self) -> dict[str, str]:
        return {
            "version": "external-inspector-staging-marker.v1",
            "attemptNonce": self.attempt_nonce,
            "bindingDigest": self.binding_digest,
            "stagingName": self.staging_name,
            "owner": self.owner,
            "allocationNonce": self.allocation_nonce,
        }

    @property
    def marker_bytes(self) -> bytes:
        return canonical_json_bytes(self.marker_payload())

    @property
    def marker_sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.marker_bytes).hexdigest()

    def wire(self) -> dict[str, Any]:
        return {
            "attemptNonce": self.attempt_nonce,
            "bindingDigest": self.binding_digest,
            "owner": self.owner,
            "root": self.root.wire(),
            "stagingName": self.staging_name,
            "artifactLeaf": self.artifact_leaf,
            "provisionalMarkerName": self.provisional_marker_name,
            "committedMarkerName": self.committed_marker_name,
            "allocationNonce": self.allocation_nonce,
            "markerLength": len(self.marker_bytes),
            "markerSha256": self.marker_sha256,
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> StagingAllocationPlanV1:
        try:
            _exact_keys(
                value,
                {
                    "attemptNonce",
                    "bindingDigest",
                    "owner",
                    "root",
                    "stagingName",
                    "artifactLeaf",
                    "provisionalMarkerName",
                    "committedMarkerName",
                    "allocationNonce",
                    "markerLength",
                    "markerSha256",
                },
            )
            plan = cls(
                attempt_nonce=_string(value, "attemptNonce"),
                binding_digest=_string(value, "bindingDigest"),
                owner=_string(value, "owner"),
                allocation_nonce=_string(value, "allocationNonce"),
                root=PrivateStagingRootV1.from_wire(_mapping(value, "root")),
                staging_name=_string(value, "stagingName"),
                artifact_leaf=_string(value, "artifactLeaf"),
                provisional_marker_name=_string(value, "provisionalMarkerName"),
                committed_marker_name=_string(value, "committedMarkerName"),
            )
        except (TypeError, ValueError) as exc:
            raise AttemptJournalError("staging allocation plan is malformed") from exc
        if (
            _integer(value, "markerLength") != len(plan.marker_bytes)
            or _string(value, "markerSha256") != plan.marker_sha256
        ):
            raise AttemptJournalError("staging allocation marker binding is invalid")
        return plan


@dataclass(frozen=True, slots=True)
class StagingAllocationReceiptV1:
    marker: StagingFileIdentityV1
    directory: StagingFileIdentityV1
    artifact: StagingFileIdentityV1

    def wire(self) -> dict[str, dict[str, int]]:
        return {
            "marker": self.marker.wire(),
            "directory": self.directory.wire(),
            "artifact": self.artifact.wire(),
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> StagingAllocationReceiptV1:
        try:
            _exact_keys(value, {"marker", "directory", "artifact"})
            return cls(
                marker=StagingFileIdentityV1.from_wire(value["marker"]),
                directory=StagingFileIdentityV1.from_wire(value["directory"]),
                artifact=StagingFileIdentityV1.from_wire(value["artifact"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AttemptJournalError("allocation receipt is malformed") from exc


@dataclass(frozen=True, slots=True)
class RuntimeParentReceiptV1:
    """Durable systemd/cgroup parent fact observed before Docker create."""

    unit_name: str
    object_path: str
    description: str
    slice_name: str
    control_group: str
    invocation_id: str
    device: int
    inode: int
    controllers: tuple[str, ...]
    cpu_counter_unit: str
    baseline_cpu_counter: int
    cpu_budget_counter: int

    def __post_init__(self) -> None:
        if (
            not self.unit_name.endswith(".slice")
            or not self.object_path.startswith("/")
            or not self.slice_name.endswith(".slice")
            or not self.description.startswith("ksi-external-inspector-attempt.v1:sha256:")
            or re.fullmatch(r"[0-9a-f]{32}", self.invocation_id) is None
        ):
            raise ValueError("runtime parent unit or object path is invalid")
        if not self.control_group.startswith("/"):
            raise ValueError("runtime parent ControlGroup is invalid")
        _nonnegative(self.device, self.inode, self.baseline_cpu_counter)
        if type(self.cpu_budget_counter) is not int or self.cpu_budget_counter <= 0:
            raise ValueError("runtime parent CPU budget is invalid")
        if self.controllers != ("cpu", "memory", "pids"):
            raise ValueError("runtime parent must prove exact cgroup controllers")
        if self.cpu_counter_unit != "CPU_USEC":
            raise ValueError("runtime parent CPU counter unit is invalid")

    def wire(self) -> dict[str, Any]:
        return {
            "unitName": self.unit_name,
            "objectPath": self.object_path,
            "description": self.description,
            "sliceName": self.slice_name,
            "controlGroup": self.control_group,
            "invocationId": self.invocation_id,
            "device": self.device,
            "inode": self.inode,
            "controllers": list(self.controllers),
            "cpuCounterUnit": self.cpu_counter_unit,
            "baselineCpuCounter": self.baseline_cpu_counter,
            "cpuBudgetCounter": self.cpu_budget_counter,
        }

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> RuntimeParentReceiptV1:
        try:
            _exact_keys(
                value,
                {
                    "unitName",
                    "objectPath",
                    "description",
                    "sliceName",
                    "controlGroup",
                    "invocationId",
                    "device",
                    "inode",
                    "controllers",
                    "cpuCounterUnit",
                    "baselineCpuCounter",
                    "cpuBudgetCounter",
                },
            )
            controllers = value["controllers"]
            if not isinstance(controllers, list) or any(
                not isinstance(item, str) for item in controllers
            ):
                raise ValueError
            return cls(
                unit_name=_string(value, "unitName"),
                object_path=_string(value, "objectPath"),
                description=_string(value, "description"),
                slice_name=_string(value, "sliceName"),
                control_group=_string(value, "controlGroup"),
                invocation_id=_string(value, "invocationId"),
                device=_integer(value, "device"),
                inode=_integer(value, "inode"),
                controllers=tuple(controllers),
                cpu_counter_unit=_string(value, "cpuCounterUnit"),
                baseline_cpu_counter=_integer(value, "baselineCpuCounter"),
                cpu_budget_counter=_integer(value, "cpuBudgetCounter"),
            )
        except (TypeError, ValueError) as exc:
            raise AttemptJournalError("runtime parent receipt is malformed") from exc


@dataclass(frozen=True, slots=True)
class AttemptBindingV1:
    attempt_nonce: str
    canonical_input_digest: str
    operation: str
    owner: str
    container_name: str
    systemd_slice_name: str
    systemd_base_slice: str
    execution_manifest_digest: str
    parser_build_digest: str
    oci_manifest_digest: str
    oci_config_digest: str
    backend_profile_digest: str
    security_profile_digest: str
    resource_envelope_digest: str
    inspector_protocol_digest: str
    cpu_budget_counter: int
    staging: StagingAllocationPlanV1

    def __post_init__(self) -> None:
        for value in (
            self.canonical_input_digest,
            self.execution_manifest_digest,
            self.parser_build_digest,
            self.oci_manifest_digest,
            self.oci_config_digest,
            self.backend_profile_digest,
            self.security_profile_digest,
            self.resource_envelope_digest,
            self.inspector_protocol_digest,
        ):
            _digest_value(value)
        for value in (
            self.attempt_nonce,
            self.operation,
            self.owner,
            self.container_name,
            self.systemd_slice_name,
            self.systemd_base_slice,
        ):
            _safe_name(value)
        if not self.systemd_slice_name.endswith(".slice") or not self.systemd_base_slice.endswith(
            ".slice"
        ):
            raise ValueError("attempt systemd units must be slice names")
        if type(self.cpu_budget_counter) is not int or self.cpu_budget_counter <= 0:
            raise ValueError("attempt CPU budget is invalid")
        if self.staging.attempt_nonce != self.attempt_nonce or self.staging.owner != self.owner:
            raise ValueError("staging plan must bind this exact attempt owner and nonce")

    def wire(self) -> dict[str, Any]:
        return {
            "attemptNonce": self.attempt_nonce,
            "canonicalInputDigest": self.canonical_input_digest,
            "operation": self.operation,
            "owner": self.owner,
            "containerName": self.container_name,
            "systemdSliceName": self.systemd_slice_name,
            "systemdBaseSlice": self.systemd_base_slice,
            "executionManifestDigest": self.execution_manifest_digest,
            "parserBuildDigest": self.parser_build_digest,
            "ociManifestDigest": self.oci_manifest_digest,
            "ociConfigDigest": self.oci_config_digest,
            "backendProfileDigest": self.backend_profile_digest,
            "securityProfileDigest": self.security_profile_digest,
            "resourceEnvelopeDigest": self.resource_envelope_digest,
            "inspectorProtocolDigest": self.inspector_protocol_digest,
            "cpuBudgetCounter": self.cpu_budget_counter,
            "staging": self.staging.wire(),
        }

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self.wire())).hexdigest()

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> AttemptBindingV1:
        try:
            _exact_keys(
                value,
                {
                    "attemptNonce",
                    "canonicalInputDigest",
                    "operation",
                    "owner",
                    "containerName",
                    "systemdSliceName",
                    "systemdBaseSlice",
                    "executionManifestDigest",
                    "parserBuildDigest",
                    "ociManifestDigest",
                    "ociConfigDigest",
                    "backendProfileDigest",
                    "securityProfileDigest",
                    "resourceEnvelopeDigest",
                    "inspectorProtocolDigest",
                    "cpuBudgetCounter",
                    "staging",
                },
            )
            return cls(
                attempt_nonce=_string(value, "attemptNonce"),
                canonical_input_digest=_string(value, "canonicalInputDigest"),
                operation=_string(value, "operation"),
                owner=_string(value, "owner"),
                container_name=_string(value, "containerName"),
                systemd_slice_name=_string(value, "systemdSliceName"),
                systemd_base_slice=_string(value, "systemdBaseSlice"),
                execution_manifest_digest=_string(value, "executionManifestDigest"),
                parser_build_digest=_string(value, "parserBuildDigest"),
                oci_manifest_digest=_string(value, "ociManifestDigest"),
                oci_config_digest=_string(value, "ociConfigDigest"),
                backend_profile_digest=_string(value, "backendProfileDigest"),
                security_profile_digest=_string(value, "securityProfileDigest"),
                resource_envelope_digest=_string(value, "resourceEnvelopeDigest"),
                inspector_protocol_digest=_string(value, "inspectorProtocolDigest"),
                cpu_budget_counter=_integer(value, "cpuBudgetCounter"),
                staging=StagingAllocationPlanV1.from_wire(_mapping(value, "staging")),
            )
        except (TypeError, ValueError) as exc:
            raise AttemptJournalError("attempt binding is malformed") from exc


@dataclass(frozen=True, slots=True)
class RecoverableAttemptV1:
    binding: AttemptBindingV1
    phase: AttemptPhaseV1
    receipt: StagingAllocationReceiptV1 | None
    runtime_parent: RuntimeParentReceiptV1 | None
    runtime_id: str | None
    cleanup_disposition: str | None
    cleanup_origin: AttemptPhaseV1 | None


class AttemptRecoveryUnavailable(RuntimeError):
    """An unfinished local allocation cannot be proven safe to recover."""


class AttemptStagingRecoveryPort(Protocol):
    def recover_registered(
        self,
        *,
        plan: StagingAllocationPlanV1,
        receipt: StagingAllocationReceiptV1 | None,
    ) -> str: ...


class AttemptRuntimeRecoveryPort(Protocol):
    """The adapter may resolve only this fully bound runtime, never enumerate labels."""

    def resolve_exact(self, binding: AttemptBindingV1) -> str | None: ...

    def quiesce_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool: ...

    def remove_exact(self, *, binding: AttemptBindingV1, runtime_id: str) -> bool: ...


class AttemptRuntimeParentRecoveryPort(Protocol):
    """Recover only the deterministic transient slice recorded by INTENDED."""

    def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> RuntimeParentReceiptV1 | None: ...

    def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool: ...

    def verify_before_quiesce(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...

    def verify_final_before_remove(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...


class InspectorAttemptJournal:
    """Append-only local attempt lifecycle with strict replay validation."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = path
        self._clock = clock
        self._closed = False
        self._phases: dict[str, AttemptPhaseV1] = {}
        self._allocations: dict[str, StagingAllocationReceiptV1] = {}
        self._digests: dict[str, str] = {}
        self._bindings: dict[str, AttemptBindingV1] = {}
        self._runtime_parents: dict[str, RuntimeParentReceiptV1] = {}
        self._runtime_ids: dict[str, str] = {}
        self._cleanup_dispositions: dict[str, str] = {}
        self._cleanup_origins: dict[str, AttemptPhaseV1] = {}
        self._reload()

    def close(self) -> None:
        self._closed = True

    def phase_of(self, attempt_nonce: str) -> AttemptPhaseV1:
        try:
            return self._phases[attempt_nonce]
        except KeyError as exc:
            raise AttemptJournalError("attempt nonce is unknown") from exc

    def recoverable_attempts(self) -> tuple[RecoverableAttemptV1, ...]:
        """Return only exact durable allocations that have not reached CLEANED."""
        attempts: list[RecoverableAttemptV1] = []
        for nonce, phase in self._phases.items():
            if phase is AttemptPhaseV1.CLEANED:
                continue
            binding = self._bindings.get(nonce)
            if binding is None:
                raise AttemptJournalError("unfinished attempt lacks its durable binding")
            attempts.append(
                RecoverableAttemptV1(
                    binding=binding,
                    phase=phase,
                    receipt=self._allocations.get(nonce),
                    runtime_parent=self._runtime_parents.get(nonce),
                    runtime_id=self._runtime_ids.get(nonce),
                    cleanup_disposition=self._cleanup_dispositions.get(nonce),
                    cleanup_origin=self._cleanup_origins.get(nonce),
                )
            )
        return tuple(attempts)

    def intend(self, binding: AttemptBindingV1) -> None:
        if binding.attempt_nonce in self._phases:
            raise AttemptJournalError("attempt nonce is retired or already active")
        self._append(
            AttemptPhaseV1.INTENDED,
            binding.attempt_nonce,
            binding.digest,
            {"binding": binding.wire()},
        )

    def staging_allocated(self, attempt_nonce: str, receipt: StagingAllocationReceiptV1) -> None:
        self._append(
            AttemptPhaseV1.STAGING_ALLOCATED,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {"allocation": receipt.wire()},
        )

    def input_bound(
        self,
        attempt_nonce: str,
        *,
        artifact: StagingFileIdentityV1,
        observed_size_bytes: int,
        observed_sha256: str,
        reader_mapping_witness: str,
    ) -> None:
        receipt = self._allocations.get(attempt_nonce)
        if receipt is None or (artifact.device, artifact.inode) != (
            receipt.artifact.device,
            receipt.artifact.inode,
        ):
            raise AttemptJournalError("sealed input inode differs from durable allocation receipt")
        if artifact.size != observed_size_bytes or observed_size_bytes <= 0:
            raise AttemptJournalError("sealed input size is not the durable artifact size")
        _digest_value(observed_sha256)
        _safe_name(reader_mapping_witness)
        self._append(
            AttemptPhaseV1.INPUT_BOUND,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {
                "sealedInput": {
                    "artifact": artifact.wire(),
                    "observedSizeBytes": observed_size_bytes,
                    "observedSha256": observed_sha256,
                    "readerMappingWitness": reader_mapping_witness,
                }
            },
        )

    def container_bound(self, attempt_nonce: str, runtime_id: str) -> None:
        _safe_name(runtime_id)
        self._append(
            AttemptPhaseV1.CONTAINER_BOUND,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {"runtimeId": runtime_id},
        )

    def runtime_parent_bound(self, attempt_nonce: str, receipt: RuntimeParentReceiptV1) -> None:
        self._append(
            AttemptPhaseV1.RUNTIME_PARENT_BOUND,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {"runtimeParent": receipt.wire()},
        )

    def runtime_parent_creating(self, attempt_nonce: str) -> None:
        self._append(
            AttemptPhaseV1.RUNTIME_PARENT_CREATING,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {},
        )

    def container_creating(self, attempt_nonce: str) -> None:
        self._append(
            AttemptPhaseV1.CONTAINER_CREATING,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {},
        )

    def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None:
        _safe_name(disposition)
        try:
            origin = self._phases[attempt_nonce]
        except KeyError as exc:
            raise AttemptJournalError("attempt nonce is unknown") from exc
        if origin in {
            AttemptPhaseV1.CLEANUP_REQUIRED,
            AttemptPhaseV1.CLEANUP_FAILED,
            AttemptPhaseV1.CLEANED,
            AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
        }:
            raise AttemptJournalError("cleanup origin is not an active lifecycle phase")
        self._append(
            AttemptPhaseV1.CLEANUP_REQUIRED,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {"disposition": disposition, "cleanupOrigin": origin.value},
        )

    def ownership_uncertain(self, attempt_nonce: str) -> None:
        self._append(
            AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {},
        )

    def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None:
        _safe_name(reason)
        self._append(
            AttemptPhaseV1.CLEANUP_FAILED,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {"reason": reason},
        )

    def cleaned(self, attempt_nonce: str) -> None:
        self._append(
            AttemptPhaseV1.CLEANED,
            attempt_nonce,
            self._binding_digest(attempt_nonce),
            {},
        )

    def _binding_digest(self, attempt_nonce: str) -> str:
        try:
            return self._digests[attempt_nonce]
        except KeyError as exc:
            raise AttemptJournalError("attempt nonce is unknown") from exc

    def _append(
        self, phase: AttemptPhaseV1, nonce: str, binding_digest: str, additions: dict[str, Any]
    ) -> None:
        if self._closed:
            raise AttemptJournalError("attempt journal is closed")
        with self._open_journal_handle(writable=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                self._reload_from_handle(handle)
                previous = self._last_event_digest(handle)
                self._validate_transition(nonce, phase)
                now = self._clock()
                if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
                    raise AttemptJournalError(
                        "attempt journal clock must return aware UTC timestamps"
                    )
                event: dict[str, Any] = {
                    "version": _EVENT_VERSION,
                    "timestamp": now.isoformat().replace("+00:00", "Z"),
                    "phase": phase.value,
                    "attemptNonce": nonce,
                    "bindingDigest": binding_digest,
                    "previousEventDigest": previous,
                    **additions,
                }
                event["eventDigest"] = _event_digest(event)
                self._validate_event(event)
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                self._apply(event)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _reload(self) -> None:
        if not self._path.exists():
            return
        with self._open_journal_handle(writable=False) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                self._reload_from_handle(handle)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _reload_from_handle(self, handle: Any) -> None:
        handle.seek(0)
        self._phases = {}
        self._allocations = {}
        self._digests = {}
        self._bindings = {}
        self._runtime_parents = {}
        self._runtime_ids = {}
        self._cleanup_dispositions = {}
        self._cleanup_origins = {}
        previous: str | None = None
        for line in handle:
            try:
                event = json.loads(line, object_pairs_hook=_reject_duplicate_json_keys)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AttemptJournalError("attempt journal contains invalid JSON") from exc
            phase, nonce, digest = self._validate_event(event)
            if event["eventDigest"] != _event_digest(event):
                raise AttemptJournalError("attempt journal event digest is invalid")
            if event.get("previousEventDigest") != previous:
                raise AttemptJournalError("attempt journal chain is reordered")
            self._validate_transition(nonce, phase)
            if phase is AttemptPhaseV1.INTENDED:
                binding = event.get("binding")
                if not isinstance(binding, dict):
                    raise AttemptJournalError("attempt binding is malformed")
                if digest != AttemptBindingV1.from_wire(binding).digest:
                    raise AttemptJournalError("attempt binding digest is invalid")
            elif self._digests.get(nonce) != digest:
                raise AttemptJournalError("attempt event changed its immutable binding")
            self._apply(event)
            previous = event["eventDigest"]

    @staticmethod
    def _last_event_digest(handle: Any) -> str | None:
        handle.seek(0)
        digest: str | None = None
        for line in handle:
            event = json.loads(line, object_pairs_hook=_reject_duplicate_json_keys)
            if not isinstance(event, dict) or not isinstance(event.get("eventDigest"), str):
                raise AttemptJournalError("attempt journal event shape is invalid")
            digest = event["eventDigest"]
        return digest

    def _open_journal_handle(self, *, writable: bool) -> Any:
        """Open the journal only through a private, fsynced parent directory."""
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            parent_fd = os.open(
                self._path.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            raise AttemptJournalError("attempt journal directory is unavailable") from exc
        try:
            parent = os.fstat(parent_fd)
            if (
                not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.geteuid()
                or parent.st_gid != os.getegid()
                or parent.st_mode & 0o077
            ):
                raise AttemptJournalError("attempt journal directory is not private")
            os.fsync(parent_fd)
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            if writable:
                flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(self._path.name, flags, 0o600, dir_fd=parent_fd)
            try:
                identity = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(identity.st_mode)
                    or identity.st_nlink != 1
                    or identity.st_uid != os.geteuid()
                    or identity.st_gid != os.getegid()
                    or identity.st_mode & 0o077
                ):
                    raise AttemptJournalError("attempt journal file is not private")
                if writable:
                    os.fsync(parent_fd)
                return os.fdopen(descriptor, "r+" if writable else "r", encoding="utf-8")
            except Exception:
                os.close(descriptor)
                raise
        finally:
            os.close(parent_fd)

    def _validate_event(self, event: object) -> tuple[AttemptPhaseV1, str, str]:
        if not isinstance(event, dict):
            raise AttemptJournalError("attempt journal event shape is invalid")
        try:
            phase = AttemptPhaseV1(event["phase"])
        except (KeyError, ValueError, TypeError) as exc:
            raise AttemptJournalError("attempt journal event phase is invalid") from exc
        _exact_keys(event, _EVENT_BASE_FIELDS | _EVENT_ADDITION_FIELDS[phase])
        if event.get("version") != _EVENT_VERSION:
            raise AttemptJournalError("attempt journal event version is invalid")
        _canonical_timestamp(event.get("timestamp"))
        nonce = event.get("attemptNonce")
        digest = event.get("bindingDigest")
        if not isinstance(nonce, str) or not isinstance(digest, str):
            raise AttemptJournalError("attempt journal event bindings are invalid")
        try:
            _safe_name(nonce)
            _digest_value(digest)
            previous = event.get("previousEventDigest")
            if previous is not None:
                _digest_value(previous)
            _digest_value(event.get("eventDigest"))
            self._validate_phase_additions(phase, event)
        except (TypeError, ValueError, AttemptJournalError) as exc:
            raise AttemptJournalError("attempt journal event values are invalid") from exc
        return phase, nonce, digest

    def _validate_phase_additions(self, phase: AttemptPhaseV1, event: dict[str, Any]) -> None:
        if phase is AttemptPhaseV1.INTENDED:
            AttemptBindingV1.from_wire(_mapping(event, "binding"))
        elif phase is AttemptPhaseV1.STAGING_ALLOCATED:
            StagingAllocationReceiptV1.from_wire(_mapping(event, "allocation"))
        elif phase is AttemptPhaseV1.INPUT_BOUND:
            sealed = _mapping(event, "sealedInput")
            _exact_keys(
                sealed,
                {"artifact", "observedSizeBytes", "observedSha256", "readerMappingWitness"},
            )
            artifact = StagingFileIdentityV1.from_wire(_mapping(sealed, "artifact"))
            observed_size = _integer(sealed, "observedSizeBytes")
            if observed_size <= 0 or artifact.size != observed_size:
                raise AttemptJournalError("sealed input size is invalid")
            _digest_value(_string(sealed, "observedSha256"))
            _safe_name(_string(sealed, "readerMappingWitness"))
            allocation = self._allocations.get(_string(event, "attemptNonce"))
            if allocation is None or (artifact.device, artifact.inode) != (
                allocation.artifact.device,
                allocation.artifact.inode,
            ):
                raise AttemptJournalError("sealed input inode is not the recorded allocation")
        elif phase is AttemptPhaseV1.RUNTIME_PARENT_BOUND:
            runtime_parent = RuntimeParentReceiptV1.from_wire(_mapping(event, "runtimeParent"))
            binding = self._bindings.get(_string(event, "attemptNonce"))
            if binding is None or not _receipt_matches_binding(binding, runtime_parent):
                raise AttemptJournalError("runtime parent receipt is not the intended binding")
        elif phase is AttemptPhaseV1.CONTAINER_BOUND:
            _safe_name(_string(event, "runtimeId"))
        elif phase is AttemptPhaseV1.CLEANUP_REQUIRED:
            _safe_name(_string(event, "disposition"))
            try:
                origin = AttemptPhaseV1(_string(event, "cleanupOrigin"))
            except ValueError as exc:
                raise AttemptJournalError("cleanup origin is invalid") from exc
            if origin in {
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.CLEANUP_FAILED,
                AttemptPhaseV1.CLEANED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            }:
                raise AttemptJournalError("cleanup origin is invalid")
            current = self._phases.get(_string(event, "attemptNonce"))
            if current is not origin:
                raise AttemptJournalError("cleanup origin does not match prior phase")
        elif phase is AttemptPhaseV1.CLEANUP_FAILED:
            _safe_name(_string(event, "reason"))

    def _validate_transition(self, nonce: str, phase: AttemptPhaseV1) -> None:
        current = self._phases.get(nonce)
        allowed = {
            None: {AttemptPhaseV1.INTENDED},
            AttemptPhaseV1.INTENDED: {
                AttemptPhaseV1.STAGING_ALLOCATED,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.STAGING_ALLOCATED: {
                AttemptPhaseV1.INPUT_BOUND,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.INPUT_BOUND: {
                AttemptPhaseV1.RUNTIME_PARENT_CREATING,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.RUNTIME_PARENT_CREATING: {
                AttemptPhaseV1.RUNTIME_PARENT_BOUND,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.RUNTIME_PARENT_BOUND: {
                AttemptPhaseV1.CONTAINER_CREATING,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.CONTAINER_CREATING: {
                AttemptPhaseV1.CONTAINER_BOUND,
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.CONTAINER_BOUND: {
                AttemptPhaseV1.CLEANUP_REQUIRED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.CLEANUP_REQUIRED: {
                AttemptPhaseV1.RUNTIME_PARENT_BOUND,
                AttemptPhaseV1.CONTAINER_BOUND,
                AttemptPhaseV1.CLEANED,
                AttemptPhaseV1.CLEANUP_FAILED,
                AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN,
            },
            AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN: {AttemptPhaseV1.CLEANUP_FAILED},
            AttemptPhaseV1.CLEANUP_FAILED: {
                AttemptPhaseV1.RUNTIME_PARENT_BOUND,
                AttemptPhaseV1.CONTAINER_BOUND,
                AttemptPhaseV1.CLEANED,
            },
            AttemptPhaseV1.CLEANED: set(),
        }
        if phase not in allowed[current]:
            raise AttemptJournalError("attempt lifecycle transition is invalid")
        if current in {AttemptPhaseV1.CLEANUP_REQUIRED, AttemptPhaseV1.CLEANUP_FAILED}:
            if (
                phase is AttemptPhaseV1.CONTAINER_BOUND
                and self._cleanup_dispositions.get(nonce)
                not in {"STARTUP_RECOVERY", "CONTAINER_CREATE_AMBIGUOUS", "POST_CREATE_INTERRUPTED"}
            ):
                raise AttemptJournalError(
                    "runtime resolution is not durable for this cleanup state"
                )
            if (
                phase is AttemptPhaseV1.RUNTIME_PARENT_BOUND
                and self._cleanup_origins.get(nonce) is not AttemptPhaseV1.RUNTIME_PARENT_CREATING
            ):
                raise AttemptJournalError(
                    "runtime parent resolution is not durable for this cleanup state"
                )

    def _apply(self, event: dict[str, Any]) -> None:
        phase = AttemptPhaseV1(event["phase"])
        nonce = event["attemptNonce"]
        self._phases[nonce] = phase
        self._digests[nonce] = event["bindingDigest"]
        if phase is AttemptPhaseV1.INTENDED:
            binding = event.get("binding")
            if not isinstance(binding, dict):
                raise AttemptJournalError("attempt binding is malformed")
            self._bindings[nonce] = AttemptBindingV1.from_wire(binding)
        if phase is AttemptPhaseV1.STAGING_ALLOCATED:
            self._allocations[nonce] = StagingAllocationReceiptV1.from_wire(event["allocation"])
        if phase is AttemptPhaseV1.RUNTIME_PARENT_BOUND:
            self._runtime_parents[nonce] = RuntimeParentReceiptV1.from_wire(event["runtimeParent"])
        if phase is AttemptPhaseV1.CONTAINER_BOUND:
            runtime_id = event.get("runtimeId")
            if not isinstance(runtime_id, str):
                raise AttemptJournalError("runtime binding is malformed")
            self._runtime_ids[nonce] = runtime_id
        if phase is AttemptPhaseV1.CLEANUP_REQUIRED:
            disposition = event.get("disposition")
            cleanup_origin = event.get("cleanupOrigin")
            if not isinstance(disposition, str) or not isinstance(cleanup_origin, str):
                raise AttemptJournalError("cleanup disposition is malformed")
            self._cleanup_dispositions[nonce] = disposition
            self._cleanup_origins[nonce] = AttemptPhaseV1(cleanup_origin)


class InspectorAttemptRecovery:
    """Startup-only exact recovery for local journal records, never a broad inventory scan."""

    def __init__(
        self,
        *,
        journal: InspectorAttemptJournal,
        staging: AttemptStagingRecoveryPort,
        runtime_registry: AttemptRuntimeRecoveryPort,
        runtime_parent: AttemptRuntimeParentRecoveryPort,
    ) -> None:
        self._journal = journal
        self._staging = staging
        self._runtime_registry = runtime_registry
        self._runtime_parent = runtime_parent

    def recover_startup(self) -> None:
        """Close admission by raising when even one recorded allocation is uncertain."""
        for attempt in self._journal.recoverable_attempts():
            attempt = self._adopt_preparent_receipt(attempt)
            attempt = self._record_cleanup_required_before_mutation(attempt)
            runtime_id = self._recover_runtime(attempt)
            self._verify_runtime_parent_before_quiesce(attempt, runtime_id)
            self._recover_runtime_parent_before_remove(attempt, runtime_id)
            self._remove_quiesced_runtime(attempt, runtime_id)
            self._recover_runtime_parent_after_remove(attempt)
            if attempt.phase is AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN:
                self._record_uncertainty(attempt)
            try:
                disposition = self._staging.recover_registered(
                    plan=attempt.binding.staging,
                    receipt=attempt.receipt,
                )
            except Exception as exc:
                self._record_uncertainty(attempt)
                raise AttemptRecoveryUnavailable(
                    "registered staging recovery is unavailable"
                ) from exc
            if disposition == "CLEANED":
                self._record_cleaned(attempt)
                continue
            self._record_uncertainty(attempt)
        finish = getattr(self._staging, "finish_recovery", None)
        if callable(finish):
            try:
                finish()
            except Exception as exc:
                raise AttemptRecoveryUnavailable(
                    "registered staging recovery finalization is unavailable"
                ) from exc

    def _adopt_preparent_receipt(self, attempt: RecoverableAttemptV1) -> RecoverableAttemptV1:
        if attempt.runtime_parent is not None:
            if not _receipt_matches_binding(attempt.binding, attempt.runtime_parent):
                self._record_runtime_parent_cleanup_failed(attempt)
                raise AttemptRecoveryUnavailable("recorded runtime parent binding is invalid")
            return attempt
        parent_create_ambiguous = (
            attempt.phase is AttemptPhaseV1.RUNTIME_PARENT_CREATING
            or attempt.cleanup_origin is AttemptPhaseV1.RUNTIME_PARENT_CREATING
        )
        if not parent_create_ambiguous and attempt.phase is not AttemptPhaseV1.INPUT_BOUND:
            return attempt
        try:
            receipt = self._runtime_parent.adopt_if_prebound(binding=attempt.binding)
        except Exception as exc:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable(
                "runtime parent pre-receipt recovery is unavailable"
            ) from exc
        if receipt is None:
            if parent_create_ambiguous:
                self._record_runtime_parent_cleanup_failed(attempt)
                raise AttemptRecoveryUnavailable("runtime parent creation outcome is unavailable")
            return attempt
        if not _receipt_matches_binding(attempt.binding, receipt):
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("runtime parent pre-receipt binding is invalid")
        self._journal.runtime_parent_bound(attempt.binding.attempt_nonce, receipt)
        return replace(
            attempt,
            phase=AttemptPhaseV1.RUNTIME_PARENT_BOUND,
            runtime_parent=receipt,
        )

    def _record_cleanup_required_before_mutation(
        self, attempt: RecoverableAttemptV1
    ) -> RecoverableAttemptV1:
        if attempt.phase in {AttemptPhaseV1.CLEANUP_REQUIRED, AttemptPhaseV1.CLEANUP_FAILED}:
            return attempt
        self._journal.cleanup_required(
            attempt.binding.attempt_nonce, disposition="STARTUP_RECOVERY"
        )
        return replace(
            attempt,
            phase=AttemptPhaseV1.CLEANUP_REQUIRED,
            cleanup_disposition="STARTUP_RECOVERY",
        )

    def _record_cleaned(self, attempt: RecoverableAttemptV1) -> None:
        if attempt.phase not in {AttemptPhaseV1.CLEANUP_REQUIRED, AttemptPhaseV1.CLEANUP_FAILED}:
            raise AttemptRecoveryUnavailable("cleanup was not durably required before mutation")
        self._journal.cleaned(attempt.binding.attempt_nonce)

    def _recover_runtime(self, attempt: RecoverableAttemptV1) -> str | None:
        if attempt.runtime_parent is None:
            return None
        runtime_id = attempt.runtime_id
        if runtime_id is None:
            try:
                runtime_id = self._runtime_registry.resolve_exact(attempt.binding)
            except Exception as exc:
                self._record_uncertainty(attempt)
                raise AttemptRecoveryUnavailable("recorded runtime lookup is unavailable") from exc
            if runtime_id is not None and attempt.cleanup_disposition in {
                "STARTUP_RECOVERY",
                "CONTAINER_CREATE_AMBIGUOUS",
                "POST_CREATE_INTERRUPTED",
            }:
                try:
                    self._journal.container_bound(attempt.binding.attempt_nonce, runtime_id)
                    self._journal.cleanup_required(
                        attempt.binding.attempt_nonce, disposition="RECOVERED_RUNTIME_CLEANUP"
                    )
                except Exception as exc:
                    self._record_uncertainty(attempt)
                    raise AttemptRecoveryUnavailable(
                        "recorded runtime binding is unavailable"
                    ) from exc
        if runtime_id is None:
            if attempt.cleanup_disposition in {
                "CONTAINER_CREATE_AMBIGUOUS",
                "POST_CREATE_INTERRUPTED",
            }:
                self._record_runtime_cleanup_failed(attempt)
                raise AttemptRecoveryUnavailable("exact runtime creation outcome is unavailable")
            return None
        return runtime_id

    def _verify_runtime_parent_before_quiesce(
        self, attempt: RecoverableAttemptV1, runtime_id: str | None
    ) -> None:
        receipt = attempt.runtime_parent
        if receipt is None or runtime_id is None:
            return
        try:
            verified = self._runtime_parent.verify_before_quiesce(
                binding=attempt.binding, receipt=receipt, runtime_id=runtime_id
            )
        except Exception as exc:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime parent proof is unavailable") from exc
        if verified is not True:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime parent proof is unavailable")
        try:
            quiesced = self._runtime_registry.quiesce_exact(
                binding=attempt.binding, runtime_id=runtime_id
            )
        except Exception as exc:
            self._record_runtime_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime cleanup is unavailable") from exc
        if quiesced is not True:
            self._record_runtime_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime cleanup is unavailable")

    def _recover_runtime_parent_before_remove(
        self, attempt: RecoverableAttemptV1, runtime_id: str | None
    ) -> None:
        receipt = attempt.runtime_parent
        if receipt is None or runtime_id is None:
            return
        try:
            finalized = self._runtime_parent.verify_final_before_remove(
                binding=attempt.binding,
                receipt=receipt,
                runtime_id=runtime_id or "",
            )
        except Exception as exc:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable(
                "exact runtime parent finalization is unavailable"
            ) from exc
        if finalized is not True:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime parent finalization is unavailable")

    def _remove_quiesced_runtime(
        self, attempt: RecoverableAttemptV1, runtime_id: str | None
    ) -> None:
        if runtime_id is None:
            return
        try:
            removed = self._runtime_registry.remove_exact(
                binding=attempt.binding, runtime_id=runtime_id
            )
        except Exception as exc:
            self._record_runtime_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime cleanup is unavailable") from exc
        if removed is not True:
            self._record_runtime_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime cleanup is unavailable")

    def _recover_runtime_parent_after_remove(self, attempt: RecoverableAttemptV1) -> None:
        receipt = attempt.runtime_parent
        if receipt is None:
            return
        try:
            stopped = self._runtime_parent.stop_exact(binding=attempt.binding, receipt=receipt)
        except Exception as exc:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime parent cleanup is unavailable") from exc
        if stopped is not True:
            self._record_runtime_parent_cleanup_failed(attempt)
            raise AttemptRecoveryUnavailable("exact runtime parent cleanup is unavailable")

    def _record_runtime_cleanup_failed(self, attempt: RecoverableAttemptV1) -> None:
        if attempt.phase not in {AttemptPhaseV1.CLEANUP_REQUIRED, AttemptPhaseV1.CLEANUP_FAILED}:
            self._journal.cleanup_required(
                attempt.binding.attempt_nonce, disposition="STARTUP_RUNTIME_CLEANUP"
            )
        if attempt.phase is not AttemptPhaseV1.CLEANUP_FAILED:
            self._journal.cleanup_failed(
                attempt.binding.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE"
            )

    def _record_runtime_parent_cleanup_failed(self, attempt: RecoverableAttemptV1) -> None:
        if attempt.phase not in {AttemptPhaseV1.CLEANUP_REQUIRED, AttemptPhaseV1.CLEANUP_FAILED}:
            self._journal.cleanup_required(
                attempt.binding.attempt_nonce, disposition="STARTUP_RUNTIME_PARENT_CLEANUP"
            )
        if attempt.phase is not AttemptPhaseV1.CLEANUP_FAILED:
            self._journal.cleanup_failed(
                attempt.binding.attempt_nonce,
                reason="EXACT_RUNTIME_PARENT_CLEANUP_UNAVAILABLE",
            )

    def _record_uncertainty(self, attempt: RecoverableAttemptV1) -> None:
        if attempt.phase is AttemptPhaseV1.CLEANUP_FAILED:
            raise AttemptRecoveryUnavailable("registered staging ownership remains uncertain")
        if attempt.phase is not AttemptPhaseV1.STAGING_OWNERSHIP_UNCERTAIN:
            self._journal.ownership_uncertain(attempt.binding.attempt_nonce)
        self._journal.cleanup_failed(
            attempt.binding.attempt_nonce, reason="STAGING_OWNERSHIP_UNCERTAIN"
        )
        raise AttemptRecoveryUnavailable("registered staging ownership remains uncertain")


def _event_digest(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _receipt_matches_binding(binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
    return (
        receipt.unit_name == binding.systemd_slice_name
        and receipt.slice_name == binding.systemd_base_slice
        and receipt.description == "ksi-external-inspector-attempt.v1:" + binding.digest
    )


def _safe_name(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or "/" in value
        or "\x00" in value
    ):
        raise ValueError("attempt value must be a bounded path-free token")


def _digest_value(value: object) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("attempt digest must be a lowercase SHA-256 digest")


def _nonnegative(*values: int) -> None:
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("staging identity fields must be non-negative integers")


def _integer(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if type(result) is not int:
        raise ValueError(f"{key} must be an integer")
    return result


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError(f"{key} must be a string")
    return result


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"{key} must be an object")
    return result


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise AttemptJournalError("attempt journal object fields are not closed")


def _canonical_timestamp(value: object) -> None:
    if not isinstance(value, str) or len(value) > 64 or not value.endswith("Z"):
        raise AttemptJournalError("attempt journal timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AttemptJournalError("attempt journal timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise AttemptJournalError("attempt journal timestamp is invalid")
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if value != canonical:
        raise AttemptJournalError("attempt journal timestamp is not canonical")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AttemptJournalError("attempt journal JSON contains duplicate keys")
        result[key] = value
    return result


__all__ = [
    "AttemptBindingV1",
    "AttemptJournalError",
    "AttemptPhaseV1",
    "AttemptRecoveryUnavailable",
    "AttemptStagingRecoveryPort",
    "InspectorAttemptJournal",
    "InspectorAttemptRecovery",
    "PrivateStagingRootV1",
    "RecoverableAttemptV1",
    "RuntimeParentReceiptV1",
    "StagingAllocationPlanV1",
    "StagingAllocationReceiptV1",
    "StagingFileIdentityV1",
]
