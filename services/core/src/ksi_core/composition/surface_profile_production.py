"""Signed, operator supplied configuration for the optional production profile lane."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ksi_event_contracts._spatial_data import Digest, PositiveInt, PositiveSeconds, SpatialDataModel
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileActivationV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileRuntimeV1,
)
from pydantic import Field

from ksi_core.auth import PrincipalKind, PrincipalTokenRecord
from ksi_core.composition.spatial_data_production import (
    SpatialDataCoreConfigError,
    SpatialDataCoreConfigV1,
    _read_protected_file,
    _strict_json,
    _verify_detached_signature,
)
from ksi_core.composition.surface_profile_graph import SurfaceProfileGraphConfig
from ksi_core.domains.external.delivery.surface_profile_api import SurfaceProfileHttpLimits


class SurfaceProfileCoreConfigError(RuntimeError):
    """Protected opt-in configuration is unavailable or does not bind current Core inputs."""


class _HttpLimits(SpatialDataModel):
    request_max_bytes: PositiveInt
    complete_max_bytes: PositiveInt
    timeout_seconds: PositiveSeconds

    def to_limits(self) -> SurfaceProfileHttpLimits:
        return SurfaceProfileHttpLimits(
            request_max_bytes=self.request_max_bytes,
            complete_max_bytes=self.complete_max_bytes,
            timeout_seconds=self.timeout_seconds,
        )


class SurfaceProfileCoreConfigV1(SpatialDataModel):
    version: Literal["surface-profile-core-config.v1"]
    policy: SurfaceProfilePolicyV1
    runtime: SurfaceProfileRuntimeV1
    activation: SurfaceProfileActivationV1
    activation_signature: str = Field(strict=True, min_length=1, max_length=128, repr=False)
    trusted_public_key: str = Field(strict=True, min_length=1, max_length=64, repr=False)
    revoked_activation_digests: tuple[Digest, ...] = Field(max_length=4096)
    http_limits: _HttpLimits

    def verify_at(
        self,
        *,
        spatial: SpatialDataCoreConfigV1,
        principal_records: list[PrincipalTokenRecord],
        now: datetime,
    ) -> None:
        for snapshot in (self.policy, self.runtime, self.activation):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("surface profile authority is not sealed")
        if (
            self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
            or self.activation.organization_id != spatial.activation.organization_id
            or not self.activation.is_current_at(now)
            or tuple(sorted(set(self.revoked_activation_digests)))
            != self.revoked_activation_digests
            or self.activation.activation_digest in self.revoked_activation_digests
        ):
            raise ValueError("surface profile activation is expired, revoked or unbound")

        matching = {
            record.principal
            for record in principal_records
            if record.principal.principal_id == self.activation.worker_principal_id
        }
        if len(matching) != 1:
            raise ValueError("surface profile activation requires one registered worker")
        worker = next(iter(matching))
        if (
            worker.kind is not PrincipalKind.SPATIAL_DATA_WORKER
            or worker.organization_id != self.activation.organization_id
            or worker.role is not None
            or worker.device_id is not None
        ):
            raise ValueError("surface profile activation worker identity is invalid")

        _verify_detached_signature(
            public_key_b64=self.trusted_public_key,
            signature_b64=self.activation_signature,
            signing_bytes=self.activation.signing_bytes(),
        )
        self.http_limits.to_limits().validate_for(self.policy)

    def graph_config(
        self,
        *,
        clock: Callable[[], datetime],
        activation_is_current: Callable[[datetime], bool],
    ) -> SurfaceProfileGraphConfig:
        return SurfaceProfileGraphConfig(
            policy=self.policy,
            runtime=self.runtime,
            activation=self.activation,
            http_limits=self.http_limits.to_limits(),
            clock=clock,
            activation_is_current=activation_is_current,
        )


def load_surface_profile_core_config(
    path: Path,
    *,
    spatial: SpatialDataCoreConfigV1,
    principal_records: list[PrincipalTokenRecord],
    now: datetime,
) -> SurfaceProfileCoreConfigV1:
    try:
        raw = _read_protected_file(path, maximum_bytes=262144)
        config = SurfaceProfileCoreConfigV1.model_validate(_strict_json(raw))
        config.verify_at(spatial=spatial, principal_records=principal_records, now=now)
        return config
    except (SpatialDataCoreConfigError, ValueError, TypeError, RecursionError) as exc:
        raise SurfaceProfileCoreConfigError from exc


def build_surface_profile_production_config(
    path: Path,
    *,
    spatial: SpatialDataCoreConfigV1,
    principal_records: list[PrincipalTokenRecord],
    now: datetime,
) -> SurfaceProfileGraphConfig:
    config = load_surface_profile_core_config(
        path, spatial=spatial, principal_records=principal_records, now=now
    )

    def activation_is_current(current_time: datetime) -> bool:
        try:
            current = load_surface_profile_core_config(
                path,
                spatial=spatial,
                principal_records=principal_records,
                now=current_time,
            )
        except SurfaceProfileCoreConfigError:
            return False
        return current == config

    return config.graph_config(
        clock=lambda: datetime.now(UTC), activation_is_current=activation_is_current
    )
