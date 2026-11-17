"""단면 opt-in 조립 (platform Core assembly, C2c).

봉인된 단면 policy/runtime/activation, 명시적 HTTP 한도, clock만 받는다 —
기본값도 합성도 없다. 권한·작업 저장소는 장착된 공간 데이터 lane의 실제
참가자(sources, grant authorizer, currentness)와 저장 선
``MeasurementFeatureStore``, 실제 HEIGHT ``ExternalUseEvaluator`` 위에
조립되며, 하나의 Core coordinator를 공유한다. 전용 저널은 이 opt-in
경로에서만 열린다. 불일치는 라우트 장착 전에 모두 fail-closed로 거부한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileActivationV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileRuntimeV1,
)

from ksi_core.domains.external.delivery.surface_profile_api import SurfaceProfileHttpLimits
from ksi_core.domains.external.delivery.surface_profile_authority import (
    SurfaceProfileCoreAuthority,
)
from ksi_core.domains.external.delivery.surface_profile_jobs import SurfaceProfileJobStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal

SURFACE_PROFILE_JOBS_JOURNAL = "surface-profile-jobs.jsonl"
SURFACE_PROFILE_ASSEMBLY_TAG = "explicit-local-surface-profile-wiring"


@dataclass(frozen=True)
class SurfaceProfileGraphConfig:
    """봉인된 단면 스냅샷, 명시적 HTTP 한도, clock. 기본값 없음."""

    policy: SurfaceProfilePolicyV1
    runtime: SurfaceProfileRuntimeV1
    activation: SurfaceProfileActivationV1
    http_limits: SurfaceProfileHttpLimits
    clock: Callable[[], datetime]

    def __post_init__(self) -> None:
        for name, model in (
            ("policy", SurfaceProfilePolicyV1),
            ("runtime", SurfaceProfileRuntimeV1),
            ("activation", SurfaceProfileActivationV1),
        ):
            original = getattr(self, name)
            if not isinstance(original, model):
                raise ValueError("explicit complete profile policy/runtime/activation required")
            validated = model.model_validate(original.model_dump())
            if getattr(validated, validated._digest_field) != validated.canonical_digest():
                raise ValueError("sealed profile policy/runtime/activation required")
            object.__setattr__(self, name, validated.model_copy(deep=True))
        if (
            not isinstance(self.http_limits, SurfaceProfileHttpLimits)
            or not callable(self.clock)
            or self.activation.policy_digest != self.policy.policy_digest
            or self.activation.runtime_digest != self.runtime.runtime_digest
        ):
            raise ValueError("exact profile activation policy/runtime binding and clock required")
        self.http_limits.validate_for(self.policy)


@dataclass(frozen=True)
class SurfaceProfileWiring:
    """장착된 Core 실제 참가자에 결속된 권한·작업 저장소."""

    config: SurfaceProfileGraphConfig
    jobs: SurfaceProfileJobStore
    authority: SurfaceProfileCoreAuthority
    sources: Any
    authorizer: Any
    features: Any
    decisions: Any
    currentness: Any
    coordinator: ExternalAuthorityCurrentnessCoordinator

    def __post_init__(self) -> None:
        if (
            not isinstance(self.config, SurfaceProfileGraphConfig)
            or not isinstance(self.jobs, SurfaceProfileJobStore)
            or not isinstance(self.authority, SurfaceProfileCoreAuthority)
            or not isinstance(self.coordinator, ExternalAuthorityCurrentnessCoordinator)
            or any(
                part is None
                for part in (
                    self.sources,
                    self.authorizer,
                    self.features,
                    self.decisions,
                    self.currentness,
                )
            )
        ):
            raise ValueError("complete exact profile wiring required")
        self.verify_participants()

    def verify_participants(
        self,
        *,
        sources: Any = None,
        authorizer: Any = None,
        features: Any = None,
        decisions: Any = None,
        currentness: Any = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        """결속된 실제 참가자를 다시 증명한다.

        인자 없이 호출하면 결속된 참가자를 재확인하고, override를 넘기면 그
        참가자에 결속됨을 증명한다 — 불일치는 fail-closed.
        """
        expected = (
            self.sources if sources is None else sources,
            self.authorizer if authorizer is None else authorizer,
            self.features if features is None else features,
            self.decisions if decisions is None else decisions,
            self.currentness if currentness is None else currentness,
            self.coordinator if coordinator is None else coordinator,
        )
        if (
            not self.jobs.uses_exact_authority(authority=self.authority)
            or not self.authority.uses_exact_participants(
                sources=expected[0],
                grants=expected[1],
                features=expected[2],
                decisions=expected[3],
                currentness=expected[4],
                coordinator=expected[5],
            )
            or expected
            != (
                self.sources,
                self.authorizer,
                self.features,
                self.decisions,
                self.currentness,
                self.coordinator,
            )
            or self.config.policy != self.jobs.policy
        ):
            raise ValueError("surface profile must bind exact mounted Core participants")

    def uses_data_lane(self, data_lane: Any) -> bool:
        """sources/authorizer/currentness를 결속한 공간 데이터 lane."""
        return (
            data_lane is not None
            and self.sources is data_lane.sources
            and self.authorizer is data_lane.authorizer
            and self.currentness is data_lane.currentness
        )


def build_surface_profile_wiring(
    *,
    journal: Callable[[str], DurableJournal],
    config: SurfaceProfileGraphConfig,
    sources: Any,
    authorizer: Any,
    features: Any,
    decisions: Any,
    currentness: Any,
    data_policy: Any,
    coordinator: ExternalAuthorityCurrentnessCoordinator,
) -> SurfaceProfileWiring:
    """넘겨받은 Core 실제 참가자 위에 권한·작업 저장소를 조립한다."""
    if (
        not isinstance(config, SurfaceProfileGraphConfig)
        or not callable(journal)
        or sources is None
        or authorizer is None
        or features is None
        or decisions is None
        or currentness is None
        or data_policy is None
        or not isinstance(coordinator, ExternalAuthorityCurrentnessCoordinator)
    ):
        raise ValueError("surface profile requires complete explicit Core participants")
    authority = SurfaceProfileCoreAuthority(
        sources=sources,
        grants=authorizer,
        features=features,
        decisions=decisions,
        currentness=currentness,
        data_policy=data_policy,
        activation=config.activation,
        profile_policy_digest=config.policy.policy_digest or "",
        runtime_digest=config.runtime.runtime_digest or "",
        coordinator=coordinator,
    )
    jobs = SurfaceProfileJobStore(
        journal(SURFACE_PROFILE_JOBS_JOURNAL),
        authority=authority,
        policy=config.policy,
        runtime=config.runtime,
        coordinator=coordinator,
    )
    return SurfaceProfileWiring(
        config=config,
        jobs=jobs,
        authority=authority,
        sources=sources,
        authorizer=authorizer,
        features=features,
        decisions=decisions,
        currentness=currentness,
        coordinator=coordinator,
    )


def bind_surface_profile_openapi(app: FastAPI) -> None:
    """단면 계약의 정확한 bounds만 overlay한다. native 문서는 건드리지 않는다.

    단면이 아닌 공유 leaf 이름은 spatial-data overlay와 같은 방식으로
    namespace 처리하므로, 두 overlay는 서로 덮어쓰지 않고 공존한다. 실제
    라우트 탐색·캐시는 애플리케이션의 OpenAPI 생성기가 계속 담당한다.
    """
    from ksi_event_contracts.surface_profile_job import (  # noqa: PLC0415
        CreateSurfaceProfileJobV1,
        SurfaceProfileCompleteRequestV1,
        SurfaceProfileErrorV1,
        SurfaceProfileFailureRequestV1,
        SurfaceProfileJobPageV1,
        SurfaceProfileJobViewV1,
        SurfaceProfileLeaseRequestV1,
        SurfaceProfileLeaseViewV1,
        SurfaceProfileRenewRequestV1,
        SurfaceProfileResultViewV1,
        SurfaceProfileWorkerInputResponseV1,
        SurfaceProfileWorkerPendingItemV1,
        SurfaceProfileWorkerPendingPageV1,
    )

    from ksi_core.composition.spatial_data_graph import (  # noqa: PLC0415
        bind_exact_contract_models,
    )

    def name(value: str) -> str:
        if value.startswith("SurfaceProfile") or value.startswith("CreateSurfaceProfile"):
            return value
        return "SurfaceProfileV1__" + value

    bind_exact_contract_models(
        app,
        models=(
            SurfaceProfileErrorV1,
            SurfaceProfileJobPageV1,
            SurfaceProfileJobViewV1,
            SurfaceProfileResultViewV1,
            SurfaceProfileWorkerPendingItemV1,
            SurfaceProfileWorkerPendingPageV1,
            SurfaceProfileWorkerInputResponseV1,
            CreateSurfaceProfileJobV1,
            SurfaceProfileLeaseRequestV1,
            SurfaceProfileLeaseViewV1,
            SurfaceProfileRenewRequestV1,
            SurfaceProfileCompleteRequestV1,
            SurfaceProfileFailureRequestV1,
        ),
        path_marker="surface-profile",
        name=name,
    )


__all__ = [
    "SURFACE_PROFILE_ASSEMBLY_TAG",
    "SURFACE_PROFILE_JOBS_JOURNAL",
    "SurfaceProfileGraphConfig",
    "SurfaceProfileWiring",
    "bind_surface_profile_openapi",
    "build_surface_profile_wiring",
]
