"""요청 검증 422 는 **어느 라우트에서도** JSON 으로 그려진다 — 500 유출 횡단 게이트.

2026-08-18 전수 조사가 찾은 결함 클래스: pydantic 은 올바르게 검증 오류를 내는데,
FastAPI 기본 핸들러가 오류 상세의 ``input`` 에 **문제의 값을 그대로 되싣고**,
Starlette ``JSONResponse.render`` 의 ``json.dumps(allow_nan=False)`` / ``.encode("utf-8")``
가 그 값에서 터진다. 아무도 안 잡아 **500 + text/plain** 이 나간다.

이게 왜 중요한가: 워커의 ``core_client._post`` 는 본문 JSON 파싱 실패를
``NON_JSON_RESPONSE`` 로 싼다 — 운영자·워커가 **"생산자의 영구 계약 위반"과
"Core 일시 장애"를 구분할 수 없다.** 전자는 재시도해도 영원히 실패하고 후자는
재시도가 맞는데 응답이 같아 판단이 불가능하다.

**입력은 전부 문법적으로 합법인 JSON 이다.** ``1e400`` 은 RFC 8259 상 정상 숫자
리터럴이고 ``\\ud800`` 이스케이프도 유효하다 — 파서 우회가 아니라 정상 요청이라
제약이 걸린 필드를 가진 **모든** 라우트에서 재현된다. 그래서 라우트별 회귀가 아니라
이 횡단 게이트가 필요하다.

**기법 주의**: 반드시 ``raise_server_exceptions=False`` 로 클라이언트를 만든다.
기본값이면 500 이 예외로 튀어 테스트가 "에러"로만 보이고 "422 가 아니다"로는
안 보인다 — 기존 계약 테스트 전부가 이걸 안 해서 이 클래스를 통째로 못 봤다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.sites import SiteStore

_ADMIN_TOKEN = "test-admin-token"


def _auth_registry() -> AuthRegistry:
    """다른 계약 테스트와 같은 관용구(`test_processing_jobs.py:_auth_registry`)."""
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_ADMIN_TOKEN.encode()).hexdigest(),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _client(tmp_path: Path) -> TestClient:
    """``/v1/sites`` 가 **실제로 장착된** 앱 — 조립에 라우트가 없으면 본문 검증 층에
    닿지 못해 이 게이트가 통째로 공허해진다(초록불이 거짓말이 된다)."""
    app = create_app(
        auth_registry=_auth_registry(),
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    return client


# 문법상 합법이지만 그대로 되실으면 JSON 렌더가 깨지는 값들.
_HOSTILE_BODIES: list[tuple[str, str]] = [
    ("NaN", '{"x": NaN}'),
    ("Infinity", '{"x": Infinity}'),
    ("-Infinity", '{"x": -Infinity}'),
    ("1e400(오버플로 리터럴)", '{"x": 1e400}'),
    ("lone surrogate", '{"x": "a\\ud800b"}'),
    ("중첩된 lone surrogate", '{"x": {"y": ["a\\udfffb"]}}'),
]


@pytest.mark.parametrize(("label", "raw"), _HOSTILE_BODIES, ids=[c[0] for c in _HOSTILE_BODIES])
def test_hostile_json_body_never_renders_as_a_500(label: str, raw: str, tmp_path: Path) -> None:
    """장착된 표면에 쏴도 500 + text/plain 이 나오지 않는다."""
    client = _client(tmp_path)
    response = client.post(
        "/v1/sites", content=raw.encode("utf-8", "surrogatepass"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 500, f"{label}: {response.status_code} {response.text[:200]}"


@pytest.mark.parametrize(("label", "raw"), _HOSTILE_BODIES, ids=[c[0] for c in _HOSTILE_BODIES])
def test_hostile_json_body_error_is_machine_readable(
    label: str, raw: str, tmp_path: Path
) -> None:
    """거부 응답이 **JSON 이어야** 워커가 '계약 위반'과 '서버 장애'를 가른다.

    404(라우트 미장착)면 본문 검증까지 가지 않으므로 이 단언의 대상이 아니다.
    """
    client = _client(tmp_path)
    response = client.post(
        "/v1/sites", content=raw.encode("utf-8", "surrogatepass"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 404, "라우트가 장착되지 않으면 이 게이트는 공허하다"
    assert response.headers["content-type"].startswith("application/json"), (
        f"{label}: content-type={response.headers.get('content-type')!r} body={response.text[:200]}"
    )
    json.loads(response.text)  # 파싱 자체가 되는지 — 워커의 _post 가 하는 일


def test_render_safe_keeps_the_offending_value_visible() -> None:
    """[비공허 대조] 값을 지워버리지 않는다 — 요청자가 어느 값이 문제인지 알아야 고친다."""
    from ksi_core.api_base import _render_safe  # noqa: PLC2701 -- 순수 판정 함수 직접 시험

    assert _render_safe(float("nan")) == "nan"
    assert _render_safe(float("inf")) == "inf"
    assert _render_safe(1.5) == 1.5
    assert _render_safe("정상") == "정상"
    assert "\\ud800" in _render_safe("a\ud800b")
    nested: dict[str, Any] = {"k": [float("-inf"), {"deep": "a\ud800"}]}
    rendered = _render_safe(nested)
    json.dumps(rendered, allow_nan=False)  # 이게 터지지 않는 것이 이 함수의 계약이다


def test_normal_body_is_unaffected(tmp_path: Path) -> None:
    """[비공허 대조] 정상 요청은 이 핸들러를 타지 않는다 — 422 를 남발하지 않는다."""
    client = _client(tmp_path)
    response = client.post("/v1/sites", json={"siteId": "site-1"})
    # 필드가 모자라 422 인 것은 정상이다 — 이 게이트가 막는 것은 500 하나다.
    assert response.status_code != 500, response.text
    assert response.status_code != 404, "라우트가 장착되지 않으면 이 게이트는 공허하다"
