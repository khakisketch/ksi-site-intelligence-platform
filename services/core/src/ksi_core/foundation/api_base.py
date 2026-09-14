"""services/core API 모듈 공용 기반 — camelCase 응답 모델·시각 표기·봉인 상세 문구 SSOT.

`_CamelModel` 은 services/core 의 12개 API 모듈(change_detection·comparison_requests·
coverage_reports·defect_candidates·equipment_states·equipment_support·events·
mission_plans·processing_jobs·sites·source_media·volume_reports)이 각자 재정의하고
있던 것을 기계적으로 옮긴 것 — 12벌 전부 `model_config` 가 동일함을 확인했다(2026-08
구조 리팩터링 P2-4 감사).

동일한 모양의 클래스가 `packages/event-contracts/src/ksi_event_contracts/_base.py` 에도
있지만, **여기서 그걸 import 하지 않는다**. services/core 는 서비스 계층이고
event-contracts 는 계약 패키지다 — 서비스가 계약 패키지의 private 심볼(`_CamelModel`)에
결합되면, 계약 패키지가 서비스 쪽 필요에 맞춰 바뀌어야 하는 역전이 생긴다. 모양이
같아도 소유는 계층별로 분리한다.

`iso_utc()` 는 각 모듈의 `_iso`/`_iso_utc` 헬퍼(본문 전부 동일:
``value.astimezone(UTC).isoformat()``)를 옮긴 것 — journal 에 쓰는 ``ts`` 를 항상 UTC 로
정규화해, 같은 순간이 원장에서 여러 오프셋 표기로 갈리지 않게 한다.

``JOURNAL_SEALED_DETAIL``/``JOURNAL_APPEND_FAILED_DETAIL`` 은 여러 모듈에 반복되는 오류
상세 문구 리터럴이다 — 문면이 API 응답 그대로 나가므로 한 글자도 바꾸지 않고 옮겼다.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """``allow_inf_nan=False`` 는 요청 표면의 durable 원장 보호다.

    ``NaN``/``Infinity`` 는 합법 JSON 입력인데 ``DurableJournal._append_durable`` 은
    ``json.dumps(allow_nan=False)`` 를 쓰고, ``append`` 는 그 예외를 **봉인으로 승격**한다
    — 한 번의 요청으로 그 저장소가 프로세스 수명 내내 죽는다(2026-08-18 전수 조사).
    요청 검증 단계에서 422 로 거부해야 워커가 "영구 계약 위반"과 "일시 장애"를 가른다.
    계약 패키지(`ksi_event_contracts._base._CamelModel`)도 같은 설정을 갖는다 — 소유는
    계층별로 분리하되 이 성질은 양쪽 다 필요하다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )


def iso_utc(value: datetime) -> str:
    """journal 에 쓸 ``ts`` — 항상 UTC 로 정규화한다(s2-residual-hardening #2).

    오프셋을 그대로 두면 같은 순간이 원장에서 여러 표기로 남아, 문자열 정렬·
    외부 도구의 시각 비교가 오프셋마다 다른 답을 낸다.
    """
    return value.astimezone(UTC).isoformat()


JOURNAL_SEALED_DETAIL = "journal 봉인됨 — 재시작 필요"
JOURNAL_APPEND_FAILED_DETAIL = "durable 기록 실패 — journal 봉인(재시작 필요)"


#: 422 본문에 되싣는 ``input`` 의 중첩 예산. 실제 오류 상세가 이 깊이를 쓸 일은
#: 없고, 이 상한이 없으면 깊게 중첩된 **합법** JSON(예: 970단 배열)이 422 를
#: 그리다 RecursionError 로 500 이 된다(2026-08-18 재조사 F5 — 임계 깊이는 그
#: 시점 스택 잔량에 따라 968~1000 사이에서 흔들렸다).
_RENDER_DEPTH_BUDGET = 32
_RENDER_TRUNCATED = "<truncated: nesting depth exceeded>"


def _render_safe(value: Any, *, depth: int = 0) -> Any:
    """422 본문에 실어도 JSON 직렬화가 깨지지 않는 형태로 바꾼다.

    FastAPI 기본 검증 핸들러는 오류 상세의 ``input`` 에 **문제의 값을 그대로**
    되싣는다. 그런데 Starlette ``JSONResponse.render`` 는 ``json.dumps(allow_nan=False)``
    + ``.encode("utf-8")`` 이라, 그 값이 ``NaN``/``Infinity`` 이거나 lone surrogate 를
    품은 문자열이면 **422 를 그리다가** 터진다 — 아무도 안 잡아 500 + text/plain 이
    나간다(2026-08-18 실측).

    비유한 실수도 lone surrogate 도 깊은 중첩도 **문법적으로 합법인 JSON 입력**이다.
    즉 파서 우회가 아니라 정상 요청이고, 그래서 어느 라우트에서든 재현된다.

    깊이 예산이 이 함수 자신에게도 걸리는 이유: 되싣는 값의 중첩이 재귀 한도를
    넘으면 이 함수 자체가 RecursionError 의 두 번째 근원이 된다. 예산 초과분은
    마커 문자열로 접는다 — 그 깊이의 오류 상세는 어차피 사람이 읽지 못한다.

    ``jsonable_encoder`` 를 거치지 않고 여기서 전 타입을 직접 접는 이유도 같다 —
    그 인코더의 재귀에는 예산을 줄 수 없다. JSON 원시 타입 밖의 값(pydantic 이
    ``ctx`` 에 싣는 예외 객체 등)은 ``repr`` 로 접는다.
    """
    if depth > _RENDER_DEPTH_BUDGET:
        return _RENDER_TRUNCATED
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return repr(value)
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            # backslashreplace 로 실제 코드포인트를 보존해 되돌려준다 — 어느 글자가
            # 문제인지 요청자가 알아야 고칠 수 있다.
            return value.encode("utf-8", "backslashreplace").decode("ascii")
        return value
    if isinstance(value, dict):
        return {
            str(_render_safe(k, depth=depth + 1)): _render_safe(v, depth=depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_render_safe(item, depth=depth + 1) for item in value]
    return repr(value)[:200]


def mount_validation_error_handler(app: FastAPI) -> None:
    """요청 검증 422 를 **항상 JSON 으로** 그리게 한다.

    ``RequestValidationError`` 는 FastAPI 의 요청 파싱 층만 던진다 — 여기에 핸들러를
    달아도 다른 예외는 하나도 삼키지 않는다. 바뀌는 것은 "이미 422 로 판정된 것"의
    렌더링뿐이라, 진짜 서버 결함을 4xx 로 감출 경로가 구조적으로 없다.

    **``pydantic.ValidationError`` 전역 핸들러는 일부러 달지 않는다.** 그건 핸들러
    본문·저장소에서 나는 오류까지 삼켜 "네 요청이 잘못됐다"는 거짓말로 원장 오염을
    덮는다 — 이 저장소의 규약은 "의심스러우면 크게 실패한다"이지 "4xx 로 접는다"가
    아니다(``DurableJournal.append`` 가 append 예외를 봉인으로 승격하는 것과 같은 정신).
    """

    @app.exception_handler(RequestValidationError)
    async def _validation_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # jsonable_encoder 를 쓰지 않는다 — 그 인코더의 재귀에는 깊이 예산을 줄 수
        # 없어, 깊게 중첩된 합법 입력이 되실릴 때 인코더가 먼저 터진다(F5 실측).
        return JSONResponse(
            status_code=422,
            content={"detail": _render_safe(list(exc.errors()))},
        )
