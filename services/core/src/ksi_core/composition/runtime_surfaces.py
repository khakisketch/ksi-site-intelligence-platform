"""App-state, middleware, metrics, and readiness runtime surfaces."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from ksi_core.metrics import HttpMetricsMiddleware, render_prometheus_text
from ksi_core.observability import CorrelationIdMiddleware


def mount_runtime_surfaces(
    app: FastAPI,
    *,
    opened: list[Any],
    capability_authority_store: Any,
    runtime_route_configuration_registry: Any,
    runtime_route_observation_store: Any,
    external_validation_policy_registry: Any,
    external_artifact_inspection_store: Any,
    external_display_artifact_store: Any,
    external_evidence_store: Any,
    external_evidence_validation_store: Any,
    external_relative_volume_mapping_authority: Any,
    external_use_decision_store: Any,
    external_use_evaluator: Any,
    external_authority_currentness: Any,
) -> None:
    app.state.capability_authority_store = capability_authority_store
    app.state.runtime_route_configuration_registry = runtime_route_configuration_registry
    app.state.runtime_route_observation_store = runtime_route_observation_store
    app.state.external_validation_policy_registry = external_validation_policy_registry
    app.state.external_artifact_inspection_store = external_artifact_inspection_store
    app.state.external_display_artifact_store = external_display_artifact_store
    app.state.external_evidence_store = external_evidence_store
    app.state.external_evidence_validation_store = external_evidence_validation_store
    # Core-only inspection/admin access to the exact assembled mapping participant.
    # This does not create a route, admit a mapping, or alter default-closed
    # behavior; the configured authority remains absent when no workflow exists.
    app.state.external_relative_volume_mapping_authority = (
        external_relative_volume_mapping_authority
    )
    app.state.external_use_decision_store = external_use_decision_store
    app.state.external_use_evaluator = external_use_evaluator
    app.state.external_authority_currentness = external_authority_currentness

    # 미들웨어는 마지막 등록이 가장 바깥이다(Starlette 관례) — CorrelationId 를
    # 가장 바깥에 두어 그 안의 HttpMetrics·라우팅·인증 전부의 로그가 같은
    # correlation id 를 갖게 한다. 순서를 반대로 하면 미들웨어 자신의 로그(있다면)
    # 는 id 가 없는 채로 찍힌다.
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        """Prometheus 스크레이프 표면 — ``/ready`` 와 같은 이유로 무인증이다.

        스크레이퍼는 인증 헤더를 보내지 않는 것이 표준 배치이고(네트워크
        경계로 접근을 제한하는 것이 일반적 운영 관례), 이 표면 자체가 민감한
        요청 내용을 담지 않는다(집계된 카운트·지연 분포뿐, 요청 본문 없음).
        ``tests/contract/test_api_contract_sync.py`` 의
        ``_ASSEMBLE_APP_UNAUTHENTICATED_ALLOWLIST`` 에 명시적으로 올라 있다.
        """
        return PlainTextResponse(render_prometheus_text(), media_type="text/plain; version=0.0.4")

    @app.get("/ready")
    def ready() -> JSONResponse:
        """readiness — opened 원장 중 하나라도 봉인(sealed)됐으면 503.

        ``/health`` 는 프로세스 생존만 본다. 오케스트레이터가 ``/health`` 만 보면
        journal 이 봉인돼 모든 쓰기가 503 인 서버를 건강하다고 오판한다.

        ``opened`` 에는 ``DurableJournal`` 과 ``EdgeSyncStore`` 가 함께 들어온다 —
        둘 다 ``sealed_reason`` property 를 노출하므로(P0-1) ``getattr`` 은 순수
        방어적 접근일 뿐, 어느 쪽도 봉인 판정에서 빠지지 않는다.
        """
        sealed = [j for j in opened if getattr(j, "sealed_reason", None) is not None]
        if sealed:
            return JSONResponse(
                status_code=503, content={"ready": False, "sealedCount": len(sealed)}
            )
        return JSONResponse(status_code=200, content={"ready": True})
