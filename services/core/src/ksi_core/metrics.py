"""요청 수·지연·처리작업 상태 카운터 — Prometheus 텍스트 노출 형식 (M3 관측성).

## 왜 ``prometheus_client`` 를 새 의존성으로 끌어오지 않았나

이 모듈이 실제로 필요한 것은 Counter 하나·Histogram 하나·그 둘을 텍스트
노출 형식(Prometheus exposition format)으로 찍는 함수뿐이다 — 멀티프로세스
병합·푸시게이트웨이·커스텀 collector 같은 그 패키지의 나머지 기능은 이
배포(단일 프로세스 uvicorn)에 필요 없다. 노출 형식 자체는 공개 텍스트
스펙이라 패키지 없이도 정확히 구현할 수 있고, 그러면 실제 Prometheus 가
그대로 스크레이프할 수 있는 ``/metrics`` 를 의존성 0개로 얻는다.

## 스레드 안전성

FastAPI(uvicorn)는 sync 라우트를 스레드풀에서 돌린다 — Counter/Histogram
증가가 여러 스레드에서 동시에 일어날 수 있다. ``threading.Lock`` 하나로
전체 레지스트리를 보호한다(이 저장소의 다른 store 들과 같은 관용구) — 갱신
빈도가 낮고(요청당 몇 번) 잠금 구간이 짧아(딕셔너리 증가 하나) 경합 비용이
무시할 만하다.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

#: Histogram 버킷 경계(초) — prometheus_client 기본값과 동일해 낯설지 않다.
_DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0,
)


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    # 키 순서를 고정한다 — 같은 라벨 조합이 매번 같은 문자열이 되어야
    # 딕셔너리 키로 계열을 식별할 수 있다(순서가 흔들리면 같은 계열이 다른
    # 항목으로 갈라진다).
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + parts + "}"


class Counter:
    """단조 증가 카운터 — 요청 수·전이 횟수처럼 "지금까지 몇 번"을 센다."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._lock = threading.Lock()
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        with self._lock:
            items = sorted(self._values.items())
        for key, value in items:
            lines.append(f"{self.name}{_format_labels(dict(key))} {value}")
        return lines


class Histogram:
    """분포 — 지연시간처럼 "얼마나 걸렸나"의 버킷·합·건수를 함께 낸다.

    Prometheus 의 표준 히스토그램 노출 형식(``_bucket{le=...}`` 누적
    카운트 + ``_sum``/``_count``)을 그대로 따른다 — 이걸 지키면 표준
    Prometheus 쿼리(``histogram_quantile`` 등)가 별도 어댑터 없이 바로
    동작한다.
    """

    def __init__(
        self, name: str, help_text: str, buckets: tuple[float, ...] = _DEFAULT_BUCKETS
    ) -> None:
        self.name = name
        self.help_text = help_text
        self._buckets = buckets
        self._lock = threading.Lock()
        # label key → (누적 버킷 카운트 리스트, 합, 건수)
        self._data: dict[tuple[tuple[str, str], ...], tuple[list[int], float, int]] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            counts, total, count = self._data.get(
                key, ([0] * len(self._buckets), 0.0, 0)
            )
            counts = list(counts)
            for i, bound in enumerate(self._buckets):
                if value <= bound:
                    counts[i] += 1
            self._data[key] = (counts, total + value, count + 1)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        with self._lock:
            items = sorted(self._data.items())
        for key, (counts, total, count) in items:
            base_labels = dict(key)
            cumulative = 0
            for bound, bucket_count in zip(self._buckets, counts, strict=True):
                cumulative += bucket_count
                le_labels = {**base_labels, "le": str(bound)}
                lines.append(f"{self.name}_bucket{_format_labels(le_labels)} {cumulative}")
            inf_labels = {**base_labels, "le": "+Inf"}
            lines.append(f"{self.name}_bucket{_format_labels(inf_labels)} {count}")
            lines.append(f"{self.name}_sum{_format_labels(base_labels)} {total}")
            lines.append(f"{self.name}_count{_format_labels(base_labels)} {count}")
        return lines


# ── 이 배포가 실제로 내는 계열들 ──────────────────────────────────────────
#
# 새 계열을 추가할 때: 라벨에 요청 본문·자유 텍스트를 절대 넣지 않는다
# (카디널리티 폭발 — Prometheus 는 라벨 조합마다 별도 시계열을 만든다).
# path 라벨은 실제 URL 이 아니라 라우트 템플릿(``/v1/missions/{mission_id}``)
# 이어야 한다 — HTTP_REQUESTS 를 증가시키는 미들웨어(app_assembly.py)가
# ``request.scope["route"].path`` 로 이미 그렇게 채운다.

HTTP_REQUESTS = Counter(
    "ksi_core_http_requests_total", "HTTP 요청 수(method·route 템플릿·상태코드별)"
)
HTTP_REQUEST_DURATION = Histogram(
    "ksi_core_http_request_duration_seconds", "HTTP 요청 처리 시간(초)"
)
PROCESSING_JOB_TRANSITIONS = Counter(
    "ksi_core_processing_job_transitions_total", "재구성 작업 상태 전이 수(도착 상태별)"
)
COMPARISON_REQUEST_TRANSITIONS = Counter(
    "ksi_core_comparison_request_transitions_total", "두 시점 비교 요청 상태 전이 수(도착 상태별)"
)
DESIGN_CONFORMANCE_REQUEST_TRANSITIONS = Counter(
    "ksi_core_design_conformance_request_transitions_total",
    "설계 대비 잔량 요청 상태 전이 수(도착 상태별)",
)

_ALL_METRICS: tuple[Counter | Histogram, ...] = (
    HTTP_REQUESTS,
    HTTP_REQUEST_DURATION,
    PROCESSING_JOB_TRANSITIONS,
    COMPARISON_REQUEST_TRANSITIONS,
    DESIGN_CONFORMANCE_REQUEST_TRANSITIONS,
)


class HttpMetricsMiddleware:
    """모든 HTTP 요청의 수·지연을 ``HTTP_REQUESTS``/``HTTP_REQUEST_DURATION`` 에 싣는다.

    ``CorrelationIdMiddleware``(observability.py)와 같은 이유로 순수 ASGI 로
    쓴다 — ``BaseHTTPMiddleware`` 의 응답 버퍼링을 피한다.

    ``route`` 라벨은 실제 요청 경로가 아니라 **라우트 템플릿**이다
    (``/v1/missions/{mission_id}`` 처럼) — 실제 경로를 라벨로 쓰면
    missionId 값마다 별도 시계열이 생겨 카디널리티가 무한히 는다. Starlette
    라우터가 매칭 중에 같은 ``scope`` dict 에 ``scope["route"]`` 를 채워
    두므로, 하위 앱 호출이 끝난 뒤 그 값을 읽으면 된다 — 매칭 실패(404)면
    ``route`` 가 없다. 이때 요청받은 원본 경로를 라벨로 그대로 쓰면
    ``/metrics`` 가 무인증 표면이라 임의 경로를 계속 찔러 계열이 무한정
    늘어나는 경로가 열린다 — 그래서 매칭 실패는 전부 ``"unmatched"`` 라벨
    하나로 묶는다(원본 경로는 로그 줄에 남으므로 진단은 거기서 한다).

    ## 요청마다 로그 한 줄도 낸다

    uvicorn 자신의 access 로그(``uvicorn.access``)는 이 서비스의 JSON
    포매터·correlation id 필터를 타지 않는다 — uvicorn 이 그 로거에 자기
    핸들러를 직접 붙이기 때문이다. 그래서 여기서 별도로 한 줄 낸다 — 이
    미들웨어가 ``CorrelationIdMiddleware`` 바로 안쪽에 등록되므로(app_assembly.py
    의 등록 순서 주석 참조) 이 시점엔 correlation id 가 이미 묶여 있다. 결과가
    두 줄(uvicorn 것 + 이것)로 겹치는 것은 감수한다 — uvicorn 의 로거 설정을
    가로채는 쪽이 이 저장소가 아직 손대지 않은 uvicorn 내부 배선에 더 깊이
    들어가야 해서, 겹침을 받아들이는 쪽이 더 정직하다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "?")
        started = time.perf_counter()
        status_holder: list[int] = []

        async def capture_status(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder.append(message["status"])
            await send(message)

        await self.app(scope, receive, capture_status)

        duration = time.perf_counter() - started
        route = scope.get("route")
        route_path = getattr(route, "path", None) or scope.get("path", "?")
        # 라벨은 매칭 실패 시 "unmatched" 로 뭉갠다(위 클래스 docstring) — 로그
        # 줄은 진단을 위해 원본 경로(route_path)를 그대로 남긴다.
        metric_route = route_path if route is not None else "unmatched"
        status = str(status_holder[0]) if status_holder else "-"

        HTTP_REQUESTS.inc(method=method, route=metric_route, status=status)
        HTTP_REQUEST_DURATION.observe(duration, method=method, route=metric_route)
        logger.info(
            "%s %s -> %s (%.1fms)", method, route_path, status, duration * 1000
        )


def render_prometheus_text() -> str:
    """등록된 모든 계열을 Prometheus 텍스트 노출 형식으로 찍는다.

    ``GET /metrics`` 가 그대로 응답 본문으로 돌려준다(``content-type:
    text/plain; version=0.0.4`` — Prometheus 스크레이퍼가 이 버전 문자열로
    형식을 확인한다).
    """
    lines: list[str] = []
    for metric in _ALL_METRICS:
        lines.extend(metric.render())
    return "\n".join(lines) + "\n"


__all__ = [
    "COMPARISON_REQUEST_TRANSITIONS",
    "DESIGN_CONFORMANCE_REQUEST_TRANSITIONS",
    "HTTP_REQUESTS",
    "HTTP_REQUEST_DURATION",
    "PROCESSING_JOB_TRANSITIONS",
    "Counter",
    "Histogram",
    "HttpMetricsMiddleware",
    "render_prometheus_text",
]
