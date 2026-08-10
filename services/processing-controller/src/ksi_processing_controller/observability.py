"""작업 단위 correlation id + 구조화(JSON) 로깅 — ``ksi_core.observability`` 축소판.

## 왜 ``ksi_core`` 를 import 하지 않고 다시 쓰나

이 서비스(``ksi-processing-controller``)는 ``ksi-core`` 에 의존하지 않는다
(``pyproject.toml`` 확인 — 별도 프로세스로 배포되고 HTTP 로만 Core 와 말한다).
관측성 유틸 하나 때문에 그 경계를 허무는 대신, 이 서비스가 실제로 쓰는
조각(contextvar 바인딩 + JSON 포매터)만 다시 쓴다 — Starlette 미들웨어·
``/metrics`` 라우트는 이 서비스에 없다(HTTP 서버가 아니다, 폴링 루프다).

## 여기서는 워커가 이미 아는 id 를 그대로 묶는다

Core 쪽은 HTTP 헤더에서 correlation id 를 받거나 새로 만들지만, 이 워커는
이미 ``jobId``/``requestId`` 를 안다(``runner.py`` 가 폴링으로 골라온 값) —
그 값을 그대로 correlation id 로 쓴다. Core 의 로그와 워커의 로그를 같은 id
로 엮으려면(예: 처리 작업 하나의 전 과정을 한 id 로 검색), 워커가 Core 를
호출할 때 이 id 를 ``X-Request-Id`` 헤더로 실어 보내는 배선이 추가로
필요하다 — 지금은 아직 없다(``core_client.py`` 가 그 헤더를 넣지 않는다).
이 한계는 정직하게 남겨 둔다: 지금 닫는 것은 "이 워커 프로세스 안에서 한
작업의 로그 줄들이 서로 엮이는가"이지 "Core 로그까지 같은 id 로 엮이는가"가
아니다.
"""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


@contextmanager
def bind_correlation_id(correlation_id: str) -> Iterator[None]:
    """이 블록 안의 모든 로그 줄에 ``correlation_id`` 를 싣는다."""
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


class _CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """``ksi_core.observability.JsonLogFormatter`` 와 같은 필드 이름을 쓴다 —
    로그 수집기에서 두 서비스의 로그를 같은 스키마로 다룰 수 있게."""

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
    """프로세스 진입점(``runner.py::main``)에서 한 번만 부른다."""
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


__all__ = ["bind_correlation_id", "configure_structured_logging"]
