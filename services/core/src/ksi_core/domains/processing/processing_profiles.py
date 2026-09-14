"""Issued processing-profile registry (ADR-KSI-030, REQ-INT-104).

Profiles are code-owned immutable recipes, not customer supplied executable
configuration.  The registry expands the small public ``processingProfileId``
request into a complete snapshot before a ProcessingJob journal entry exists.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable

from ksi_event_contracts.processing_job import ExecutionLocus, LicenseBasis, ProcessingProvider
from ksi_event_contracts.processing_profile import (
    ProcessingPreprocessingPolicy,
    ProcessingProfileV1,
    processing_profile_wire_dict,
)

KSI_ODM_CIVIL_V1_ID = "ksi-odm-civil-v1"
KSI_NODEODM_IMAGE = "opendronemap/nodeodm"
KSI_NODEODM_IMAGE_DIGEST = "sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"


def ksi_odm_civil_v1() -> ProcessingProfileV1:
    """The single v1 civil default, sealed on every read for value semantics."""
    return ProcessingProfileV1(
        processing_profile_id=KSI_ODM_CIVIL_V1_ID,
        provider=ProcessingProvider.ODM,
        engine_version="3.5.6",
        node_odm_version="2.2.4",
        oci_image=KSI_NODEODM_IMAGE,
        oci_image_digest=KSI_NODEODM_IMAGE_DIGEST,
        execution_locus=ExecutionLocus.KSI_SERVER_GPU,
        processing_params={"dsm": True, "dtm": True, "pc-quality": "medium"},
        preprocessing=ProcessingPreprocessingPolicy(
            dynamic_object_masking=False,
            policy_version="none-v1",
        ),
        required_artifacts=("point_cloud", "dsm", "dtm"),
        license_basis=LicenseBasis(
            license_id="AGPL-3.0",
            tier="self_hosted_unmodified_container",
            attribution_required=False,
        ),
        agpl_boundary=(
            "Unmodified NodeODM container is isolated behind its REST API; any customer "
            "on-prem image distribution requires source-offer notice and legal review."
        ),
    ).sealed()


class UnknownProcessingProfileError(LookupError):
    """No issued profile has the requested identifier."""


class ProcessingProfileRegistry:
    """Read-only registry; construction rejects conflicting identifiers/digests."""

    def __init__(self, profiles: Iterable[ProcessingProfileV1] | None = None) -> None:
        issued = tuple(profiles if profiles is not None else (ksi_odm_civil_v1(),))
        by_id: dict[str, ProcessingProfileV1] = {}
        for profile in issued:
            sealed = profile.sealed()
            if (
                profile.profile_digest is not None
                and profile.profile_digest != sealed.profile_digest
            ):
                raise ValueError(
                    f"processing profile digest 불일치: {profile.processing_profile_id}"
                )
            if sealed.processing_profile_id in by_id:
                raise ValueError(f"processing profile id 중복: {sealed.processing_profile_id}")
            by_id[sealed.processing_profile_id] = sealed
        self._by_id = by_id

    def get(self, processing_profile_id: str) -> ProcessingProfileV1:
        profile = self._by_id.get(processing_profile_id)
        if profile is None:
            raise UnknownProcessingProfileError(processing_profile_id)
        # Pydantic models may contain mutable nested dictionaries.  Never hand
        # out the registry-owned object: callers get value snapshots and cannot
        # mutate the recipe used by a later job issuance.
        return profile.model_copy(deep=True)

    def list(self) -> tuple[ProcessingProfileV1, ...]:
        return tuple(self.get(key) for key in sorted(self._by_id))

    def wire_list(self) -> builtins.list[dict[str, object]]:
        return [processing_profile_wire_dict(profile) for profile in self.list()]


__all__ = [
    "KSI_NODEODM_IMAGE",
    "KSI_NODEODM_IMAGE_DIGEST",
    "KSI_ODM_CIVIL_V1_ID",
    "ProcessingProfileRegistry",
    "UnknownProcessingProfileError",
    "ksi_odm_civil_v1",
]
