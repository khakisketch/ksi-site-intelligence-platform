"""Core-owned immutable Processing Resource Policy registry.

The registry deliberately has no mutation API.  ``ksi-civil-pilot-r1`` is an
operational safety envelope for a single-customer pilot, not a pricing plan or
an accuracy claim.  Future policies are added as new sealed snapshots so jobs
already admitted can always be replayed against their original decision.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable

from ksi_event_contracts.processing_resource_policy import (
    ProcessingResourcePolicyV1,
    processing_resource_policy_wire_dict,
)

KSI_CIVIL_PILOT_R1_ID = "ksi-civil-pilot-r1"


def ksi_civil_pilot_r1() -> ProcessingResourcePolicyV1:
    """The single-customer Civil Pilot admission envelope, sealed per read."""
    return ProcessingResourcePolicyV1(
        resource_policy_id=KSI_CIVIL_PILOT_R1_ID,
        max_source_media_files=5_000,
        max_source_media_file_bytes=1_073_741_824,
        max_source_bundle_bytes=1_099_511_627_776,
        max_total_megapixels=150_000.0,
        max_active_processing_jobs_per_organization=20,
    ).sealed()


class UnknownProcessingResourcePolicyError(LookupError):
    """No issued resource policy has the requested identifier."""


class ProcessingResourcePolicyRegistry:
    """Read-only registry which can retain multiple immutable policies."""

    def __init__(
        self,
        policies: Iterable[ProcessingResourcePolicyV1] | None = None,
        *,
        current_policy_id: str = KSI_CIVIL_PILOT_R1_ID,
    ) -> None:
        issued = tuple(policies if policies is not None else (ksi_civil_pilot_r1(),))
        by_id: dict[str, ProcessingResourcePolicyV1] = {}
        for policy in issued:
            sealed = policy.sealed()
            if (
                policy.resource_policy_digest is not None
                and policy.resource_policy_digest != sealed.resource_policy_digest
            ):
                raise ValueError(
                    f"processing resource policy digest 불일치: {policy.resource_policy_id}"
                )
            if sealed.resource_policy_id in by_id:
                raise ValueError(f"processing resource policy id 중복: {sealed.resource_policy_id}")
            by_id[sealed.resource_policy_id] = sealed
        if current_policy_id not in by_id:
            raise UnknownProcessingResourcePolicyError(current_policy_id)
        self._by_id = by_id
        self._current_policy_id = current_policy_id

    @property
    def current_policy_id(self) -> str:
        return self._current_policy_id

    def get(self, resource_policy_id: str) -> ProcessingResourcePolicyV1:
        policy = self._by_id.get(resource_policy_id)
        if policy is None:
            raise UnknownProcessingResourcePolicyError(resource_policy_id)
        return policy.model_copy(deep=True)

    def current(self) -> ProcessingResourcePolicyV1:
        return self.get(self._current_policy_id)

    def list(self) -> tuple[ProcessingResourcePolicyV1, ...]:
        return tuple(self.get(key) for key in sorted(self._by_id))

    def wire_list(self) -> builtins.list[dict[str, object]]:
        return [processing_resource_policy_wire_dict(policy) for policy in self.list()]


__all__ = [
    "KSI_CIVIL_PILOT_R1_ID",
    "ProcessingResourcePolicyRegistry",
    "UnknownProcessingResourcePolicyError",
    "ksi_civil_pilot_r1",
]
