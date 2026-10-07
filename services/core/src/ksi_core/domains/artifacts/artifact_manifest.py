"""Generation-fenced processing artifact authority.

The event-contract ``ProcessingArtifact`` describes what an artifact means.  It
intentionally does not describe where its bytes live.  This module owns the
durable Core-side binding between those meanings and immutable object bytes.

New processing results are authoritative only through
``AuthoritativeArtifactManifestV1``.  Legacy journal records are adapted by the
processing-job store and never fabricated into a manifest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ksi_domain.signed_payload import canonical_payload_bytes, sha256_digest
from ksi_event_contracts.processing_artifact import (
    ProcessingArtifact,
    processing_artifact_wire_dict,
)


class ArtifactManifestError(ValueError):
    """A candidate/manifest is incomplete, inconsistent, or forged."""


def _require_sha256(value: str, *, field: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ArtifactManifestError(f"{field} must be sha256:<64 lowercase hex>")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ArtifactManifestError(f"{field} must be sha256:<64 lowercase hex>") from exc
    if value != value.lower():
        raise ArtifactManifestError(f"{field} must use lowercase hex")


@dataclass(frozen=True, slots=True)
class ArtifactObjectBinding:
    """Immutable identity and integrity facts for one stored object."""

    object_key: str
    sha256: str
    size_bytes: int
    content_type: str

    def __post_init__(self) -> None:
        if (
            not self.object_key
            or self.object_key.startswith("/")
            or ".." in self.object_key.split("/")
        ):
            raise ArtifactManifestError("objectKey must be a non-empty relative storage key")
        _require_sha256(self.sha256, field="sha256")
        if self.size_bytes < 0:
            raise ArtifactManifestError("sizeBytes must be non-negative")
        if not self.content_type:
            raise ArtifactManifestError("contentType must be non-empty")

    def to_wire(self) -> dict[str, Any]:
        return {
            "objectKey": self.object_key,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "contentType": self.content_type,
        }

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactObjectBinding:
        try:
            return cls(
                object_key=str(raw["objectKey"]),
                sha256=str(raw["sha256"]),
                size_bytes=int(raw["sizeBytes"]),
                content_type=str(raw["contentType"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactManifestError(f"invalid artifact object binding: {exc}") from exc


@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    """A durable, generation-owned artifact that is not yet authoritative."""

    artifact: ProcessingArtifact
    worker_instance_id: str
    lease_acquisition_id: str
    lease_generation: int
    primary: ArtifactObjectBinding
    auxiliary_files: tuple[tuple[str, ArtifactObjectBinding], ...] = ()

    def __post_init__(self) -> None:
        if not self.worker_instance_id or not self.lease_acquisition_id:
            raise ArtifactManifestError("candidate provenance identities must be non-empty")
        if self.lease_generation < 1:
            raise ArtifactManifestError("candidate leaseGeneration must be >= 1")
        if self.primary.sha256 != self.artifact.digest:
            raise ArtifactManifestError(
                "primary object sha256 must equal the artifact digest"
            )
        names = tuple(name for name, _ in self.auxiliary_files)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ArtifactManifestError("auxiliaryFiles must be a unique, sorted mapping")
        declared = tuple(sorted(self.artifact.auxiliary_files))
        if names != declared:
            raise ArtifactManifestError(
                "auxiliary object bindings must exactly match artifact.auxiliaryFiles"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "artifact": processing_artifact_wire_dict(self.artifact),
            "workerInstanceId": self.worker_instance_id,
            "leaseAcquisitionId": self.lease_acquisition_id,
            "leaseGeneration": self.lease_generation,
            "primary": self.primary.to_wire(),
            "auxiliaryFiles": {name: binding.to_wire() for name, binding in self.auxiliary_files},
        }

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> CandidateArtifact:
        try:
            auxiliary_raw = raw.get("auxiliaryFiles", {})
            if not isinstance(auxiliary_raw, Mapping):
                raise ArtifactManifestError("auxiliaryFiles must be an object")
            return cls(
                artifact=ProcessingArtifact.model_validate(raw["artifact"]),
                worker_instance_id=str(raw["workerInstanceId"]),
                lease_acquisition_id=str(raw["leaseAcquisitionId"]),
                lease_generation=int(raw["leaseGeneration"]),
                primary=ArtifactObjectBinding.from_wire(raw["primary"]),
                auxiliary_files=tuple(
                    (str(name), ArtifactObjectBinding.from_wire(binding))
                    for name, binding in sorted(auxiliary_raw.items())
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ArtifactManifestError):
                raise
            raise ArtifactManifestError(f"invalid candidate artifact: {exc}") from exc


@dataclass(frozen=True, slots=True)
class AuthoritativeArtifactManifestV1:
    """The sole byte-location authority for one new-format successful job."""

    job_id: str
    producing_worker_instance_id: str
    lease_acquisition_id: str
    lease_generation: int
    entries: tuple[CandidateArtifact, ...]
    manifest_digest: str

    @staticmethod
    def _payload(
        *,
        job_id: str,
        producing_worker_instance_id: str,
        lease_acquisition_id: str,
        lease_generation: int,
        entries: tuple[CandidateArtifact, ...],
    ) -> dict[str, Any]:
        return {
            "manifestVersion": "AuthoritativeArtifactManifestV1",
            "jobId": job_id,
            "producingWorkerInstanceId": producing_worker_instance_id,
            "leaseAcquisitionId": lease_acquisition_id,
            "leaseGeneration": lease_generation,
            "entries": [entry.to_wire() for entry in entries],
        }

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        producing_worker_instance_id: str,
        lease_acquisition_id: str,
        lease_generation: int,
        entries: tuple[CandidateArtifact, ...],
    ) -> AuthoritativeArtifactManifestV1:
        ordered = tuple(sorted(entries, key=lambda item: item.artifact.artifact_id))
        payload = cls._payload(
            job_id=job_id,
            producing_worker_instance_id=producing_worker_instance_id,
            lease_acquisition_id=lease_acquisition_id,
            lease_generation=lease_generation,
            entries=ordered,
        )
        return cls(
            job_id=job_id,
            producing_worker_instance_id=producing_worker_instance_id,
            lease_acquisition_id=lease_acquisition_id,
            lease_generation=lease_generation,
            entries=ordered,
            manifest_digest=sha256_digest(canonical_payload_bytes(payload)),
        )

    def __post_init__(self) -> None:
        if self.lease_generation < 1:
            raise ArtifactManifestError("manifest leaseGeneration must be >= 1")
        ids = tuple(entry.artifact.artifact_id for entry in self.entries)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ArtifactManifestError("manifest entries must be unique and sorted")
        for entry in self.entries:
            if entry.artifact.job_id != self.job_id:
                raise ArtifactManifestError("manifest entry jobId mismatch")
            if (
                entry.worker_instance_id != self.producing_worker_instance_id
                or entry.lease_acquisition_id != self.lease_acquisition_id
                or entry.lease_generation != self.lease_generation
            ):
                raise ArtifactManifestError("manifest contains cross-generation provenance")
        expected = sha256_digest(
            canonical_payload_bytes(
                self._payload(
                    job_id=self.job_id,
                    producing_worker_instance_id=self.producing_worker_instance_id,
                    lease_acquisition_id=self.lease_acquisition_id,
                    lease_generation=self.lease_generation,
                    entries=self.entries,
                )
            )
        )
        if self.manifest_digest != expected:
            raise ArtifactManifestError("artifact manifest digest mismatch")

    def to_wire(self) -> dict[str, Any]:
        return {
            **self._payload(
                job_id=self.job_id,
                producing_worker_instance_id=self.producing_worker_instance_id,
                lease_acquisition_id=self.lease_acquisition_id,
                lease_generation=self.lease_generation,
                entries=self.entries,
            ),
            "manifestDigest": self.manifest_digest,
        }

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> AuthoritativeArtifactManifestV1:
        if raw.get("manifestVersion") != "AuthoritativeArtifactManifestV1":
            raise ArtifactManifestError("unsupported artifact manifest version")
        try:
            entries_raw = raw["entries"]
            if not isinstance(entries_raw, list):
                raise ArtifactManifestError("manifest entries must be a list")
            return cls(
                job_id=str(raw["jobId"]),
                producing_worker_instance_id=str(raw["producingWorkerInstanceId"]),
                lease_acquisition_id=str(raw["leaseAcquisitionId"]),
                lease_generation=int(raw["leaseGeneration"]),
                entries=tuple(CandidateArtifact.from_wire(entry) for entry in entries_raw),
                manifest_digest=str(raw["manifestDigest"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ArtifactManifestError):
                raise
            raise ArtifactManifestError(f"invalid artifact manifest: {exc}") from exc

    def entry(self, artifact_id: str) -> CandidateArtifact | None:
        return next(
            (entry for entry in self.entries if entry.artifact.artifact_id == artifact_id),
            None,
        )


__all__ = [
    "ArtifactManifestError",
    "ArtifactObjectBinding",
    "AuthoritativeArtifactManifestV1",
    "CandidateArtifact",
]
