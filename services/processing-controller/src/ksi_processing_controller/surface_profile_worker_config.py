"""단면 일꾼의 소유자 보호 설정. 활성화·자격 발급 수단이 아니다.

로드할 때마다 분리 서명, 철회, 유효 기간을 다시 확인한다. 신뢰 루트는 운영자가 고정한
설정이며 Core나 원본 산출물에서 배우지 않는다. 파일 보호와 엄격 JSON은 native 공간 자료
일꾼의 검증된 구현을 그대로 쓴다.
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ksi_event_contracts._spatial_data import Digest, PositiveInt, PositiveSeconds, SpatialDataModel
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileActivationV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileRuntimeV1,
)
from pydantic import Field

from ksi_processing_controller.external_object_streams import ExternalObjectTransportPolicyV1
from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    _ObjectSettings,
    _path,
    parse_strict_json,
    read_owner_private_file,
    require_owner_private_directory,
)


class SurfaceProfileWorkerConfigError(RuntimeError):
    def __init__(self, reason: str = "CONFIG_UNAVAILABLE") -> None:
        self.reason = reason
        super().__init__(reason)


class SurfaceProfileWorkerConfigV1(SpatialDataModel):
    version: Literal["surface-profile-worker-config.v1"]
    core_origin: str = Field(strict=True, min_length=1, max_length=4096)
    maximum_response_bytes: PositiveInt
    maximum_request_bytes: PositiveInt
    request_timeout_seconds: PositiveSeconds
    poll_interval_seconds: PositiveSeconds
    heartbeat_interval_millis: PositiveInt
    workspace_root: str = Field(strict=True, min_length=1, max_length=4096)
    policy: SurfaceProfilePolicyV1
    runtime: SurfaceProfileRuntimeV1
    activation: SurfaceProfileActivationV1
    activation_signature: str = Field(strict=True, min_length=1, max_length=128, repr=False)
    trusted_public_key: str = Field(strict=True, min_length=1, max_length=64, repr=False)
    revoked_activation_digests: tuple[Digest, ...] = Field(max_length=4096)
    object_transport: _ObjectSettings

    @property
    def worker_instance_id(self) -> str:
        return self.activation.worker_instance_id

    @property
    def object_policy(self) -> ExternalObjectTransportPolicyV1:
        return self.object_transport.policy()

    def verify_at(self, now: datetime) -> None:
        for snapshot in (self.activation, self.policy, self.runtime):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("봉인된 단면 권한이 필요하다")
        if (
            self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
            or not self.activation.is_current_at(now)
            or self.activation.activation_digest in self.revoked_activation_digests
            or tuple(sorted(set(self.revoked_activation_digests)))
            != self.revoked_activation_digests
        ):
            raise ValueError("현재 유효한 단면 권한이 아니다")
        key = base64.b64decode(self.trusted_public_key, validate=True)
        signature = base64.b64decode(self.activation_signature, validate=True)
        if (
            len(key) != 32
            or len(signature) != 64
            or base64.b64encode(key).decode("ascii") != self.trusted_public_key
            or base64.b64encode(signature).decode("ascii") != self.activation_signature
        ):
            raise ValueError("정규 분리 서명이 필요하다")
        Ed25519PublicKey.from_public_bytes(key).verify(signature, self.activation.signing_bytes())
        origin = urlsplit(self.core_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("명시적 보안 Core 주소가 필요하다")
        require_owner_private_directory(_path(self.workspace_root))
        envelope, transport = self.policy.resource_envelope, self.object_policy
        if (
            {v.origin for v in transport.endpoints} != set(self.activation.trusted_endpoint_origins)
            or self.maximum_response_bytes > envelope.max_input_bytes
            or not self.policy.max_result_bytes
            < self.maximum_request_bytes
            <= envelope.max_input_bytes
            or self.request_timeout_seconds > self.policy.lease_seconds / 2
            or self.heartbeat_interval_millis / 1000 >= self.policy.lease_seconds / 3
            or self.poll_interval_seconds > envelope.max_deadline_seconds
            or transport.max_object_bytes
            > min(envelope.max_input_bytes, envelope.max_streamed_bytes)
            or transport.max_header_bytes > 262144
        ):
            raise ValueError("유한한 예산으로 연결된 권한과 전송이 필요하다")


def load_surface_profile_worker_config(
    path: Path, *, now: datetime
) -> SurfaceProfileWorkerConfigV1:
    from cryptography.exceptions import InvalidSignature

    try:
        raw = read_owner_private_file(path, maximum_bytes=262144)
        config = SurfaceProfileWorkerConfigV1.model_validate(parse_strict_json(raw))
        config.verify_at(now)
        return config
    except (
        ValueError,
        TypeError,
        RecursionError,
        InvalidSignature,
        SpatialDataWorkerConfigError,
    ) as exc:
        raise SurfaceProfileWorkerConfigError() from exc
