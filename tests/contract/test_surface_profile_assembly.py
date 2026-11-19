"""단면 opt-in 조립: 기본 비활성, fail-closed 결속, OpenAPI seam.

C2c 조립 소유 seam. 정상 HTTP 왕복 증거는 메인의
``test_platform_core_http_integration.py``이 맡고, 여기서는 기본 비활성,
부분/오류 결속, 시작 실패, native 문서 불변만 다룬다. 가짜 참가자로 정상
조립을 주장하지 않는다 — 성공 경로는 실제 배선 참가자 동일성 검사를 통과해야
한다.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from surface_profile_job_fixture import NOW, profile_policy, profile_runtime

ROOT = Path(__file__).resolve().parents[2]


def _sufficient_envelope() -> Any:
    return profile_policy().resource_envelope.model_copy(
        update={"max_input_bytes": 1_000_000, "resource_envelope_digest": None}
    ).sealed()


def _policy() -> Any:
    return profile_policy(resource_envelope=_sufficient_envelope())


def _limits() -> Any:
    from ksi_core.domains.external.delivery.surface_profile_api import (
        SurfaceProfileHttpLimits,
    )

    return SurfaceProfileHttpLimits(
        request_max_bytes=4096, complete_max_bytes=500_000, timeout_seconds=1.0
    )


def _activation(policy: Any, runtime: Any) -> Any:
    from ksi_event_contracts.surface_profile_job import SurfaceProfileActivationV1

    return SurfaceProfileActivationV1(
        activation_id="assembly-test-activation",
        organization_id="org-local",
        worker_principal_id="worker-local",
        worker_instance_id="instance-1",
        policy_digest=policy.policy_digest or "",
        runtime_digest=runtime.runtime_digest or "",
        trusted_endpoint_origins=("https://store.invalid",),
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    ).sealed()


def _config() -> Any:
    from ksi_core.composition.surface_profile_graph import SurfaceProfileGraphConfig

    policy = _policy()
    runtime = profile_runtime()
    return SurfaceProfileGraphConfig(
        policy=policy,
        runtime=runtime,
        activation=_activation(policy, runtime),
        http_limits=_limits(),
        clock=lambda: NOW,
    )


def _assemble(trace: list[str], opened: list[Any], path: Path, **kwargs: Any) -> FastAPI:
    from ksi_core.composition.platform_assembly import assemble_platform_app  # noqa: PLC0415
    from ksi_core.durable_journal import DurableJournal  # noqa: PLC0415
    from test_platform_core_assembly import _auth_registry, _Storage  # noqa: PLC0415

    def journal(name: str) -> Any:
        trace.append(name)
        item = DurableJournal(path / name)
        opened.append(item)
        return item

    try:
        return assemble_platform_app(
            path,
            journal=journal,
            opened=opened,
            auth_registry=_auth_registry(),
            evidence_storage=_Storage(),
            **kwargs,
        )
    except BaseException:
        for item in opened:
            item.close()
        raise


def _close_all(opened: list[Any]) -> None:
    for item in opened:
        item.close()
    opened.clear()


def _route_paths(app: FastAPI) -> set[tuple[str, str]]:
    from test_platform_core_assembly import _walk_routes  # noqa: PLC0415

    return {
        (method.upper(), route.path)
        for route in _walk_routes(app)
        if getattr(route, "methods", None)
        for method in (route.methods or set())
    }


# ── 기본 비활성 ─────────────────────────────────────────────────────────────


def test_default_off_mounts_no_surface_profile_surface(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(trace, opened, tmp_path)
    try:
        assert not any("surface-profile" in path for _, path in _route_paths(app))
        assert "surface-profile-jobs.jsonl" not in trace
        assert getattr(app.state, "surface_profile", None) is None
    finally:
        _close_all(opened)


def test_production_loader_keeps_surface_profile_default_none() -> None:
    import inspect  # noqa: PLC0415

    from ksi_core.composition.platform_assembly import (  # noqa: PLC0415
        assemble_platform_app,
    )

    assert inspect.signature(assemble_platform_app).parameters["surface_profile"].default is None


# ── fail-closed: 데이터 lane 부재 ────────────────────────────────────────────


def test_surface_profile_without_data_lane_fails_closed_before_journal(
    tmp_path: Path,
) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    with pytest.raises(ValueError, match="spatial data lane"):
        _assemble(trace, opened, tmp_path, surface_profile=_config())
    assert "surface-profile-jobs.jsonl" not in trace


def test_non_config_surface_profile_fails_closed(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    with pytest.raises(ValueError, match="explicit sealed graph config"):
        _assemble(trace, opened, tmp_path, surface_profile=object())


# ── fail-closed: 설정 ──────────────────────────────────────────────────────


def test_unsealed_policy_config_fails_closed() -> None:
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        SurfaceProfileGraphConfig,
    )

    raw = _policy().model_copy(update={"policy_digest": None})
    with pytest.raises(ValueError, match="sealed"):
        SurfaceProfileGraphConfig(
            policy=raw,
            runtime=profile_runtime(),
            activation=_activation(_policy(), profile_runtime()),
            http_limits=_limits(),
            clock=lambda: NOW,
        )


def test_activation_binding_mismatch_fails_closed() -> None:
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        SurfaceProfileGraphConfig,
    )

    policy = _policy()
    runtime = profile_runtime()
    other = profile_policy(
        policy_id="other-policy", resource_envelope=_sufficient_envelope()
    )
    with pytest.raises(ValueError, match="bind"):
        SurfaceProfileGraphConfig(
            policy=policy,
            runtime=runtime,
            activation=_activation(other, runtime),
            http_limits=_limits(),
            clock=lambda: NOW,
        )


def test_http_limits_outside_envelope_fail_closed() -> None:
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        SurfaceProfileGraphConfig,
    )
    from ksi_core.domains.external.delivery.surface_profile_api import (  # noqa: PLC0415
        SurfaceProfileHttpLimits,
    )

    policy = _policy()
    runtime = profile_runtime()
    bad = SurfaceProfileHttpLimits(
        request_max_bytes=4096, complete_max_bytes=100, timeout_seconds=1.0
    )
    with pytest.raises(ValueError, match="envelope"):
        SurfaceProfileGraphConfig(
            policy=policy,
            runtime=runtime,
            activation=_activation(policy, runtime),
            http_limits=bad,
            clock=lambda: NOW,
        )


# ── 참가자 결속 ────────────────────────────────────────────────────────────


def _stubs(coordinator: Any) -> dict[str, Any]:
    from types import SimpleNamespace  # noqa: PLC0415

    class _Currentness:
        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

        def resolve_requester(self, **kwargs: Any) -> Any:
            raise AssertionError("no requester in assembly binding probe")

        def is_current(self, **kwargs: Any) -> bool:
            return True

    return {
        "sources": SimpleNamespace(name="sources"),
        "authorizer": SimpleNamespace(name="authorizer"),
        "features": SimpleNamespace(name="features"),
        "decisions": SimpleNamespace(name="decisions"),
        "currentness": _Currentness(coordinator),
    }


def _wiring(tmp_path: Path, **overrides: Any) -> tuple[Any, list[Any]]:
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        build_surface_profile_wiring,
    )
    from ksi_core.durable_journal import DurableJournal  # noqa: PLC0415
    from ksi_core.foundation.currentness import (  # noqa: PLC0415
        ExternalAuthorityCurrentnessCoordinator,
    )

    config = _config()
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    parts: dict[str, Any] = {"coordinator": coordinator, **_stubs(coordinator)}
    parts.update(overrides)
    journals: list[Any] = []

    def journal(name: str) -> Any:
        item = DurableJournal(tmp_path / name)
        journals.append(item)
        return item

    from spatial_data_fixture import make_policy as make_data_policy  # noqa: PLC0415

    try:
        wiring = build_surface_profile_wiring(
            journal=journal,
            config=config,
            sources=parts["sources"],
            authorizer=parts["authorizer"],
            features=parts["features"],
            decisions=parts["decisions"],
            currentness=parts["currentness"],
            data_policy=make_data_policy(),
            coordinator=parts["coordinator"],
        )
    except BaseException:
        for item in journals:
            item.close()
        raise
    return wiring, journals


def test_wiring_rechecks_exact_participants(tmp_path: Path) -> None:
    wiring, journals = _wiring(tmp_path)
    try:
        wiring.verify_participants()
        from ksi_core.foundation.currentness import (  # noqa: PLC0415
            ExternalAuthorityCurrentnessCoordinator,
        )

        other = ExternalAuthorityCurrentnessCoordinator()
        swapped = _stubs(other)["sources"]
        with pytest.raises(ValueError, match="exact"):
            wiring.verify_participants(sources=swapped)
    finally:
        for item in journals:
            item.close()


def test_wiring_rejects_coordinator_split(tmp_path: Path) -> None:
    from ksi_core.foundation.currentness import (  # noqa: PLC0415
        ExternalAuthorityCurrentnessCoordinator,
    )

    with pytest.raises(ValueError, match="coordinator"):
        _wiring(tmp_path, coordinator=ExternalAuthorityCurrentnessCoordinator())


# ── OpenAPI: 정적 + 런타임 ──────────────────────────────────────────────────

_SURFACE_PROFILE_METHODS = {
    ("POST", "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs"),
    ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs"),
    ("POST", "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-comparisons"),
    ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-comparisons"),
    ("GET", "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs/{job_id}"),
    (
        "GET",
        "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs/{job_id}/result",
    ),
    (
        "POST",
        "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs/{job_id}/cancel",
    ),
    ("GET", "/v1/internal/surface-profile-jobs"),
    ("POST", "/v1/internal/surface-profile-jobs/{job_id}/lease"),
    ("POST", "/v1/internal/surface-profile-jobs/{job_id}/renew"),
    ("GET", "/v1/internal/surface-profile-jobs/{job_id}/input"),
    ("POST", "/v1/internal/surface-profile-jobs/{job_id}/complete"),
    ("POST", "/v1/internal/surface-profile-jobs/{job_id}/failure"),
}


def _static_document() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "contracts/api/openapi-core.yaml").read_text())


def test_static_openapi_lists_every_surface_profile_route_with_assembly_tag() -> None:
    document = _static_document()
    published = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        if "surface-profile" in path
        for method in item
        if method in {"get", "post", "put", "delete", "patch", "head"}
    }
    assert published >= _SURFACE_PROFILE_METHODS
    for _, path in _SURFACE_PROFILE_METHODS:
        assert (
            document["paths"][path]["x-assembly"] == "explicit-local-surface-profile-wiring"
        ), path


def test_static_openapi_success_is_always_200() -> None:
    document = _static_document()
    for _, path in _SURFACE_PROFILE_METHODS:
        item = document["paths"][path]
        for method, operation in item.items():
            if method in {"get", "post", "put", "delete", "patch", "head"} and isinstance(
                operation, dict
            ):
                assert "200" in operation.get("responses", {}), (method, path)
                assert "201" not in operation.get("responses", {}), (method, path)


def test_static_openapi_native_contracts_are_untouched() -> None:
    document = _static_document()
    base = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"
    assert document["paths"][base]["x-assembly"] == "explicit-local-spatial-data-wiring"
    assert "surface-profile" not in yaml.safe_dump(document["paths"][base])
    assert (
        document["paths"]["/v1/internal/spatial-data-jobs"]["x-assembly"]
        == "explicit-local-spatial-data-wiring"
    )


def test_runtime_overlay_keeps_native_bounds_and_adds_exact_models(tmp_path: Path) -> None:
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        bind_surface_profile_openapi,
    )
    from ksi_core.domains.external.delivery.surface_profile_api import (  # noqa: PLC0415
        build_surface_profile_router,
    )
    from test_surface_profile_jobs import Lane  # noqa: PLC0415

    lane = Lane(tmp_path, resource_envelope=_sufficient_envelope())
    app = FastAPI()
    app.include_router(
        build_surface_profile_router(jobs=lane.store, limits=_limits(), clock=lambda: NOW)
    )
    bind_surface_profile_openapi(app)
    schema = app.openapi()
    assert "SurfaceProfileJobViewV1" in schema["components"]["schemas"]
    assert "SurfaceProfileJobPageV1" in schema["components"]["schemas"]
    assert "SurfaceProfileErrorV1" in schema["components"]["schemas"]
    post = schema["paths"][
        "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs"
    ]["post"]
    ref = post["requestBody"]["content"]["application/json"]["schema"].get("$ref", "")
    assert ref == "#/components/schemas/CreateSurfaceProfileJobV1"
    view = schema["components"]["schemas"]["SurfaceProfileJobViewV1"]
    from ksi_event_contracts.surface_profile_job import (  # noqa: PLC0415
        SurfaceProfileJobViewV1,
    )

    live = SurfaceProfileJobViewV1.model_json_schema(by_alias=True)
    assert view["properties"]["jobId"] == live["properties"]["jobId"]


def test_runtime_overlays_do_not_clobber_each_other() -> None:
    from ksi_core.composition.spatial_data_graph import (  # noqa: PLC0415
        bind_spatial_data_openapi,
    )
    from ksi_core.composition.surface_profile_graph import (  # noqa: PLC0415
        bind_surface_profile_openapi,
    )

    app = FastAPI()
    bind_spatial_data_openapi(app)
    before = dict(app.openapi()["components"]["schemas"])
    bind_surface_profile_openapi(app)
    after = app.openapi()["components"]["schemas"]
    for name, schema in before.items():
        assert after[name] == schema
    assert "SurfaceProfileJobViewV1" in after


# ── 실제 데이터 lane 위 opt-in 장착 ──────────────────────────────────────────
#
# 바이트 백엔드(오브젝트 스토리지)는 stand-in으로 남는다 — 여기서는 요청을
# 보내지 않는다. 결속된 참가자는 모두 실제 조립된 저장소다: 봉인된 실제 공간
# 설정, 시험 레지스트리 위 실제 production currentness, 플랫폼 그래프의 실제
# 측정 저장소와 실제 HEIGHT evaluator. 요청/응답 동작은 delivery 시험과
# integration 시험의 요청자/일꾼 HTTP 왕복이 담당한다.


def _spatial_assembly() -> Any:
    from ksi_core.composition.spatial_data_graph import (  # noqa: PLC0415
        SpatialDataLocalAssemblyConfig,
        SpatialDataLocalGraphConfig,
    )
    from ksi_event_contracts.processing_job import ExecutionLocus  # noqa: PLC0415
    from spatial_data_fixture import (  # noqa: PLC0415
        make_activation as make_data_activation,
    )
    from spatial_data_fixture import make_policy as make_data_policy  # noqa: PLC0415
    from spatial_data_fixture import make_runtime as make_data_runtime  # noqa: PLC0415

    class _MountOnlyStorage:
        """장착 시점 stand-in: 라우팅은 결속하지만 여기서는 바이트를 읽지 않는다."""

        def observe_owned_output(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def open_version(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def issue_source_get(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def issue_output_put(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def list_owned_versions(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
            return ()

        def delete_owned_version(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    def _build_currentness(coordinator: Any) -> Any:
        from ksi_core.composition.spatial_data_production import (  # noqa: PLC0415
            SpatialDataProductionCurrentness,
        )
        from test_platform_core_assembly import _auth_registry  # noqa: PLC0415

        return SpatialDataProductionCurrentness(
            coordinator=coordinator,
            policy=make_data_policy(),
            runtime=make_data_runtime(),
            activation=make_data_activation(),
            revoked_activation_digests=(),
            auth_registry=_auth_registry(),
            oidc_subject_registry=None,
        )

    return SpatialDataLocalAssemblyConfig(
        config=SpatialDataLocalGraphConfig(
            policy=make_data_policy(),
            runtime=make_data_runtime(),
            activation=make_data_activation(),
            processing_location=ExecutionLocus.SITE_ONPREM,
            clock=lambda: NOW,
        ),
        build_storage=lambda reconstruction: _MountOnlyStorage(),
        build_currentness=_build_currentness,
    )


def test_opt_in_mount_exposes_requester_and_worker_roots(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(
        trace, opened, tmp_path, spatial_data=_spatial_assembly(), surface_profile=_config()
    )
    try:
        assert "spatial-data-jobs.jsonl" in trace
        assert "surface-profile-jobs.jsonl" in trace
        paths = _route_paths(app)
        assert (
            "POST",
            "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs",
        ) in paths
        assert (
            "GET",
            "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs",
        ) in paths
        assert ("GET", "/v1/internal/surface-profile-jobs") in paths
        assert ("GET", "/v1/internal/surface-profile-jobs/{job_id}/input") in paths
        wiring = getattr(app.state, "surface_profile", None)
        assert wiring is not None
        assert wiring.uses_data_lane(getattr(app.state, "spatial_data", None))
        schema = app.openapi()
        assert "SurfaceProfileJobViewV1" in schema["components"]["schemas"]
        assert "SpatialDataJobViewV1" in schema["components"]["schemas"]
    finally:
        _close_all(opened)
