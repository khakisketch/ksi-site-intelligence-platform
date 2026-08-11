"""요청/작업 단위 correlation id + 구조화(JSON) 로깅 (M3 관측성).

## 왜 지금까지 없었나

``logging.getLogger(__name__)`` 산발 호출뿐이었다 — 각 모듈이 자기 로거를
만들어 쓰지만, 그 출력을 한 줄로 묶는 자리(correlation id)도 기계가 읽을
형식(JSON)도 없었다. 사고가 나면 "이 요청이 어느 로그 줄들로 이어졌는가"를
사람이 타임스탬프로 눈대중 짜맞춰야 했다.

## correlation id 는 두 갈래로 들어온다

- **HTTP 요청**: :class:`CorrelationIdMiddleware` 가 ``X-Request-Id`` 헤더를
  읽거나(재현·추적 연결용 — 클라이언트가 이미 아는 id 를 그대로 쓰게 해준다)
  없으면 새로 만들어, 그 요청을 처리하는 동안의 모든 로그 줄에 실리게 한다.
- **워커 루프**: HTTP 요청이 아니라 폴링이 스스로 시작하는 작업 단위라
  헤더가 없다. :func:`bind_correlation_id` 로 같은 contextvar 를 직접
  묶는다 — ``runner.py``/``comparison_worker.py`` 가 이미 각 작업의
  jobId/requestId 를 ``now_message`` 문자열 접두사로 쓰고 있었으니(예:
  ``f"[{job_id}] ..."``), 그 id 를 그대로 여기 넘기면 문자열 접두사이던
  것이 구조화된 필드가 된다.

## 왜 새 의존성을 끌어오지 않았나

``python-json-logger``·``structlog`` 등 기존 패키지가 있지만, 이 모듈이
필요한 것은 "표준 로그 레코드에 correlation_id 필드 하나를 얹고 JSON 으로
찍는다"뿐이다 — 표준 라이브러리 ``logging.Formatter`` 서브클래스 20줄로
충분한 일에 의존성을 추가하면 그 패키지의 나머지 기능(구조화 바인딩 체인,
프로세서 파이프라인 등)은 전부 안 쓰는 무게로 남는다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: 지금 처리 중인 요청/작업의 correlation id. 요청/작업 경계 밖(모듈 최상단
#: import 시점 등)에서 로깅하면 기본값 ``None`` 이 찍힌다 — 그 자체가
#: "요청 밖에서 로깅했다"는 진단 정보이므로 가짜 값으로 채우지 않는다.
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

#: 응답에도 같은 id 를 돌려준다 — 클라이언트가 자기 요청을 서버 로그에서
#: 되짚어 찾을 수 있게(운영 문의·재현 요청의 표준 동선).
REQUEST_ID_HEADER = "X-Request-Id"


def current_correlation_id() -> str | None:
    return _correlation_id.get()


@contextmanager
def bind_correlation_id(correlation_id: str) -> Iterator[None]:
    """이 블록 안의 모든 로그 줄에 ``correlation_id`` 를 싣는다(워커 루프용).

    HTTP 미들웨어와 같은 contextvar 를 쓴다 — 요청 안에서 워커가 아니라
    Core 자신이 부수 작업을 벌이는 경우(지금은 없지만)에도 같은 메커니즘이
    그대로 맞는다.
    """
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


class _CorrelationIdFilter(logging.Filter):
    """모든 :class:`logging.LogRecord` 에 ``correlation_id`` 속성을 얹는다.

    필터를 쓰는 이유(포매터에서 직접 contextvar 를 읽지 않는 이유)는
    ``logging`` 표준 확장점이 필터이기 때문이다 — 루트 로거에 필터 하나만
    붙이면 그 아래 전 로거(모듈별 ``getLogger(__name__)`` 전부 포함)에
    전파된다. 포매터에서 읽으면 JSON 포매터를 안 쓰는 다른 핸들러(있다면)는
    이 필드를 못 본다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """한 줄 = 로그 레코드 하나 = JSON 객체 하나(JSON Lines).

    로그 수집기(있다면)가 파싱하기 쉬운 형태이지 사람이 터미널에서 읽기
    좋은 형태가 아니다 — dev 환경은 이 포매터를 쓰지 않는다
    (:func:`configure_structured_logging` 의 ``json_format=False`` 경로,
    ``scripts/run_core_dev.py`` 가 그쪽을 쓴다).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlationId": getattr(record, "correlation_id", None) or "-",
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(*, level: str = "INFO", json_format: bool = True) -> None:
    """루트 로거를 correlation id 필터 + (선택) JSON 포매터로 재구성한다.

    프로세스 진입점(``production.py``·``run_core_dev.py``·워커 ``runner.py``)
    에서 한 번만 부른다 — 라이브러리 코드(``ksi_core`` 내부 모듈)는 이 함수를
    부르지 않고 그냥 ``logging.getLogger(__name__)`` 만 쓴다("라이브러리는
    로깅 설정을 스스로 정하지 않는다"는 표준 관례 — 무엇을 어디로 보낼지는
    이 프로세스를 띄우는 쪽이 정한다).
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.addFilter(_CorrelationIdFilter())
    if json_format:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s]: %(message)s"
            )
        )
    root.addHandler(handler)


class CorrelationIdMiddleware:
    """ASGI 미들웨어 — 요청마다 correlation id 를 굳히고 응답에 되돌려준다.

    ``starlette.middleware.base.BaseHTTPMiddleware`` 대신 순수 ASGI 로 쓴 이유:
    ``BaseHTTPMiddleware`` 는 응답을 스트리밍이 아니라 통째로 버퍼링해서
    넘기는 것으로 알려진 성능 함정이 있다(대용량 presigned URL 리다이렉트·
    다운로드 응답이 이 앱에 실재한다) — 이 미들웨어가 하는 일은 헤더 하나
    읽고 하나 얹는 것뿐이라 그 함정을 감수할 이유가 없다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(REQUEST_ID_HEADER.lower().encode("latin-1"))
        correlation_id = incoming.decode("latin-1") if incoming else str(uuid.uuid4())

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                response_headers.append(
                    (REQUEST_ID_HEADER.encode("latin-1"), correlation_id.encode("latin-1"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        token = _correlation_id.set(correlation_id)
        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id.reset(token)


__all__ = [
    "REQUEST_ID_HEADER",
    "CorrelationIdMiddleware",
    "JsonLogFormatter",
    "bind_correlation_id",
    "configure_structured_logging",
    "current_correlation_id",
]
