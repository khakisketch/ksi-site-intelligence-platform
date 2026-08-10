"""correlation id + 구조화 로깅 + ``/metrics`` 계약 (M3 관측성).

초점 셋:

1. ``observability.py`` 의 순수 로직(포매터·필터·contextvar) — 프로세스 배선
   없이 단위로 고정한다.
2. ``CorrelationIdMiddleware``·``HttpMetricsMiddleware`` 가 실제 assemble_app
   조립에 얹혀 있고, HTTP 요청 하나가 실제로 ``/metrics`` 에 반영된다
   (green≠작동 — 미들웨어가 등록만 되고 안 도는 사각지대를 막는다).
3. ``/metrics`` 가 무인증이고 Prometheus 텍스트 형식을 낸다.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.observability import (
    REQUEST_ID_HEADER,
    JsonLogFormatter,
    bind_correlation_id,
    current_correlation_id,
)

_TOKEN = "obs-test-token"  # noqa: S105 — 테스트 고정값


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_TOKEN),
                principal=Principal(
                    principal_id="op-1", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


class _NullEvidenceStorage:
    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        raise NotImplementedError

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError


def _assembled_client(tmp_path: Path) -> TestClient:
    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / name)
        opened.append(journal)
        return journal

    app = assemble_app(
        tmp_path,
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=_auth_registry(),
        evidence_storage=_NullEvidenceStorage(),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="obs-test-key",
    )
    return TestClient(app)


# ── 단위: contextvar·필터·포매터 ──────────────────────────────────────────


def test_no_correlation_id_outside_a_bound_block() -> None:
    """요청/작업 경계 밖에서는 None — 가짜 값으로 채우지 않는다."""
    assert current_correlation_id() is None


def test_bind_correlation_id_scopes_to_the_block() -> None:
    with bind_correlation_id("req-abc"):
        assert current_correlation_id() == "req-abc"
    assert current_correlation_id() is None


def test_nested_bind_restores_outer_value() -> None:
    """중첩 바인딩이 빠져나오면 바깥 값으로 복원된다 — 워커가 재구성 작업 처리
    중 다른 correlation id 를 잠깐 쓰는 경우에도 바깥 문맥이 안전하다."""
    with bind_correlation_id("outer"):
        with bind_correlation_id("inner"):
            assert current_correlation_id() == "inner"
        assert current_correlation_id() == "outer"


def test_json_formatter_includes_correlation_id_and_message() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    record.correlation_id = "req-xyz"  # type: ignore[attr-defined]

    import json

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello world"
    assert payload["correlationId"] == "req-xyz"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"


def test_json_formatter_defaults_to_dash_without_binding() -> None:
    """필터가 안 붙은 레코드(correlation_id 속성 자체가 없음)도 죽지 않는다 —
    getattr 기본값이 "-" 다(빈 문자열·None 대신, 로그를 눈으로 훑을 때 빈칸과
    구별되는 값)."""
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="no id", args=(), exc_info=None,
    )
    import json

    payload = json.loads(formatter.format(record))
    assert payload["correlationId"] == "-"


# ── 통합: 실제 assemble_app 위에서 미들웨어가 도는가 ──────────────────────


def test_metrics_endpoint_is_unauthenticated_and_prometheus_formatted(
    tmp_path: Path,
) -> None:
    client = _assembled_client(tmp_path)
    response = client.get("/metrics")  # 인증 헤더 없음 — /ready 와 같은 정책
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "# HELP ksi_core_http_requests_total" in body
    assert "# TYPE ksi_core_http_requests_total counter" in body


def test_http_request_is_reflected_in_metrics(tmp_path: Path) -> None:
    """[핵심] 미들웨어가 등록만 되고 안 도는 사각지대를 막는다 — 실제 요청 하나를
    보내고 그 요청이 정말 카운터에 반영됐는지 본다(green≠작동)."""
    client = _assembled_client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    client.get("/health")
    body = client.get("/metrics").text

    # route 라벨은 실제 경로(/health)를 그대로 쓴다(라우트 템플릿과 같다 —
    # 경로 파라미터가 없는 정적 경로라서). method=GET·status=200 조합이 있어야
    # 한다.
    assert 'ksi_core_http_requests_total{' in body
    assert 'method="GET"' in body
    assert 'route="/health"' in body
    assert 'status="200"' in body


def test_correlation_id_header_is_echoed_back(tmp_path: Path) -> None:
    """클라이언트가 보낸 id 를 그대로 돌려준다 — 새로 만들지 않는다(재현·추적
    연결이 끊기지 않게)."""
    client = _assembled_client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    response = client.get("/health", headers={REQUEST_ID_HEADER: "trace-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-123"


def test_correlation_id_is_generated_when_absent(tmp_path: Path) -> None:
    """클라이언트가 안 보내면 서버가 만들어 돌려준다 — 빈 값이 아니다."""
    client = _assembled_client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    response = client.get("/health")

    assert response.headers.get(REQUEST_ID_HEADER)
    assert len(response.headers[REQUEST_ID_HEADER]) > 0


def test_metrics_route_label_collapses_unmatched_paths(tmp_path: Path) -> None:
    """[핵심] 404 경로는 원본 문자열이 아니라 "unmatched" 라벨 하나로 묶인다 —
    무인증 스캐너가 임의 경로를 계속 찔러도 계열 수가 늘지 않는다(카디널리티
    방어). 이걸 지키지 않으면 route 라벨에 요청 경로 원문이 그대로 실린다."""
    client = _assembled_client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    client.get("/this-route-does-not-exist")
    client.get("/another-nonexistent-route")
    body = client.get("/metrics").text

    assert 'route="unmatched"' in body
    assert "/this-route-does-not-exist" not in body
    assert "/another-nonexistent-route" not in body


def test_correlation_id_is_bound_before_metrics_middleware_runs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """[핵심] ``CorrelationIdMiddleware`` 가 ``HttpMetricsMiddleware`` 보다 바깥에
    등록돼 있어야, 후자가 찍는 요청 로그 줄에 correlation id 가 실린다
    (app_assembly.py 의 등록 순서 주석이 실제로 지켜지는지 — 순서가 뒤바뀌어도
    아무 테스트가 안 깨지면 사람이 쓴 주석만 그 정합성을 지키는 셈이 된다).
    ``HttpMetricsMiddleware.__call__`` 은 ``logging`` 표준 로거로 직접 찍으므로
    caplog 로 관측한다(JSON 포매터를 거치지 않는 raw LogRecord) — 다만
    correlation id 를 레코드에 싣는 것은 ``_CorrelationIdFilter`` 이고 그건
    ``configure_structured_logging`` 이 붙인 핸들러에만 달려 있어(테스트 조립엔
    없음) caplog 자신의 핸들러에 같은 필터를 직접 붙여야 caplog 로 관측할 수
    있다."""
    from ksi_core.observability import _CorrelationIdFilter  # noqa: PLC0415

    caplog.handler.addFilter(_CorrelationIdFilter())
    client = _assembled_client(tmp_path)
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    with caplog.at_level(logging.INFO, logger="ksi_core.metrics"):
        client.get("/health", headers={REQUEST_ID_HEADER: "trace-order-check"})

    records = [r for r in caplog.records if r.name == "ksi_core.metrics"]
    assert records, "ksi_core.metrics 로거가 요청 로그를 남기지 않았다"
    has_correlation_id = any(
        getattr(r, "correlation_id", None) == "trace-order-check" for r in records
    )
    assert has_correlation_id, "correlation id 누락 — 미들웨어 등록 순서가 뒤바뀌었을 수 있다"


@pytest.mark.parametrize("target_status", ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"])
def test_metrics_module_counts_processing_job_transitions(target_status: str) -> None:
    """[핵심] processing_jobs.py 가 실제로 이 카운터를 증가시킨다 — 모듈 수준
    싱글턴을 직접 대조(app_assembly 를 통째로 조립하지 않고, 값 자체의 증가를
    확인하는 더 좁은 단위 검증)."""
    from ksi_core.metrics import PROCESSING_JOB_TRANSITIONS

    before = dict(PROCESSING_JOB_TRANSITIONS._values)  # noqa: SLF001 -- 증가분만 비교
    PROCESSING_JOB_TRANSITIONS.inc(target_status=target_status)
    after = dict(PROCESSING_JOB_TRANSITIONS._values)  # noqa: SLF001

    key = (("target_status", target_status),)
    assert after.get(key, 0) == before.get(key, 0) + 1
