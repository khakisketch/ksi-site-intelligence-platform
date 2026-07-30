"""URL 경로-세그먼트 안전 식별자 검증 (2차 독립 재검토 P1/P2 — SSOT).

``siteId``/``missionId``/``eventKey`` 구성요소(``edgeDeviceId``·``eventId``)는
전부 라우터 경로 세그먼트(``/v1/sites/{site_id}``·``/v1/missions/{mission_id}``·
``/v1/events/{event_key}``)로 쓰인다. 이 값을 만드는 주체(Edge 장비·API 호출자)가
'/'·공백·제어문자·빈 문자열을 실으면, 그 레코드는 durable 기록(201/PROJECTED)
까지는 성공하고 이후 상세 조회·전이 라우트에는 영구히 도달할 수 없는 트랩이
된다(FastAPI str convertor 는 ``/`` 를 포함할 수 없고, uvicorn 이 라우팅 전에
``%2F`` 를 언쿼트하므로 인코딩으로도 우회되지 않는다).

원래 ``mission_records.py`` 에 지역 정의됐던 패턴(1차 재검토 폐쇄)을, 2차
독립 재검토가 ``events.py``(eventId·edgeDeviceId)·``sites.py``(siteId) 에
동일 클래스 결함이 남아있음을 지적해 공유 모듈로 승격했다 — 세 모듈이 각자
패턴을 재구현하면 drift(문자 집합이 조용히 갈라짐) 위험이 생긴다.
"""

from __future__ import annotations

import re

# 첫 글자를 영숫자로 강제해 '.'·'-' 로만 이뤄진 경로 세그먼트(".."·"-" 등
# 특수 의미)를 배제한다. 길이 상한은 두지 않는다(운영 규모에서 URL 길이
# 한도에 닿을 실사용 사례가 없어, 상한값 자체를 대표자 결정 없이 임의로
# 고정하지 않는다 — 필요해지면 별도 결정 사안).
PATH_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def is_path_safe_identifier(value: str) -> bool:
    """``value`` 가 경로 세그먼트로 안전한지(빈 문자열도 거부).

    ``fullmatch``를 쓴다 — ``match``+``$``는 Python 정규식 관용상 문자열
    끝의 개행 1개를 허용해(``"site-1\\n"``이 매치) 최종검토 3차에서 지적된
    갭(트레일링 개행이 서로 다른 레코드로 공존)을 열어둔다.
    """
    return PATH_SAFE_IDENTIFIER_PATTERN.fullmatch(value) is not None


__all__ = ["PATH_SAFE_IDENTIFIER_PATTERN", "is_path_safe_identifier"]
