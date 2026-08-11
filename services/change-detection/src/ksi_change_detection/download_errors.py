"""다운로드 실패 메시지를 사람에게 내보내기 전에 서명을 지운다.

## 왜 한 곳에 있나

``run_change_detection``·``run_volume_change`` 는 서로 대칭인 ``_download`` 를
각자 갖는다(두 모듈 docstring — 구조는 복제하되 판단은 복제하지 않는다).
그런데 **무엇을 지울지는 판단이고, 보안 규칙이다** — 한쪽만 고쳐지면 다른
쪽으로 서명이 계속 샌다. 그래서 이 함수만 공용으로 둔다.

## 무엇이 문제였나

presigned URL 의 쿼리스트링에는 서명(``X-Amz-Signature`` 등)이 실린다. 이
메시지는 비교 요청의 ``FAILED`` detail 로 원장에 영구 기록되고 ``/reports``
화면에 그대로 보인다 — 즉 화면을 보는 누구나 그 서명으로 원본 산출물을 직접
받을 수 있게 된다(TTL 안에서). 2026-08-10 실 인프라 재현 중 발견했다.

## 왜 예외 타입을 열거하지 않나

처음 고칠 때는 ``httpx.HTTPStatusError`` 만 URL 을 품는다는 실측에 기대어
나머지는 예외 **클래스 이름만** 남겼다. 그러면 안전하긴 한데 ``ConnectError``
가 들고 있던 ``[Errno 111] Connection refused`` 같은 진짜 원인이 통째로
사라진다 — 방화벽 변경인지 DNS 실패인지 백엔드 지연인지 구분할 수 없어지고,
그 구분이 필요한 자리가 정확히 실 인프라 장애 대응이다.

지금은 반대로 간다: 메시지는 그대로 살리되 **서명처럼 보이는 것을 지운다**.
어느 예외가 URL 을 품는지 열거해 두면 httpx 가 바뀌거나 새 예외가 생길 때
그 목록이 조용히 낡는다 — 열거 대신 출력을 검사하는 편이 늙지 않는다.
"""

from __future__ import annotations

import re

#: 쿼리스트링을 통째로 지운다. 서명 파라미터 이름을 열거하지 않는 이유는 위와
#: 같다 — 스토리지 구현마다 이름이 다르고(AWS SigV4·SigV2·MinIO·GCS), 목록은
#: 낡는다. presigned URL 에서 물음표 뒤는 전부 인가 재료라고 본다.
_QUERY = re.compile(r"\?[^\s\"'<>]*")


def redact_url_query(text: str) -> str:
    """문자열 안의 모든 ``?...`` 를 지운다 — URL 이 어디에 박혀 있든.

    호출자가 URL 을 어디에 넣었는지(직접 포맷했는지, 예외 메시지 안에 있는지)
    알 필요 없이 **나가는 문자열 전체**에 한 번 걸면 된다.

    >>> redact_url_query("받지 못했다(http://h/o?X-Amz-Signature=abc): timed out")
    '받지 못했다(http://h/o): timed out'
    """
    return _QUERY.sub("", text)


def download_failure_detail(*, what: str, url: str, cause: str) -> str:
    """실패 사유 한 줄 — 경로는 남기고 서명은 지운 채, 원인은 그대로.

    Args:
        what: 무엇을 받으려 했는지(사람 말). 예: ``"point cloud"``.
        url: 받으려던 주소. 쿼리스트링은 지워진다.
        cause: 원인 문자열(``str(exc)`` 또는 ``HTTP 404`` 같은 요약).
            여기에도 URL 이 섞여 있을 수 있어 같이 지운다.
    """
    return redact_url_query(f"{what} 를 받지 못했다({url}): {cause}")


__all__ = ["download_failure_detail", "redact_url_query"]
