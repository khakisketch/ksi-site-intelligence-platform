"""정규 JSON 직렬화 — mission-contracts(서명)와 event-contracts(offline sync)가
같은 정규화 규약을 공유해야 하므로 두 패키지의 공통 의존인 이 자리에 둔다.

key 정렬·최소 구분자(``,``/``:``)·``ensure_ascii=False``·``allow_nan=False``.
``allow_nan=False``: 기본값은 NaN/Infinity 를 비표준 JSON 토큰으로 직렬화해,
표준 파서(다른 언어·다른 프로세스)로는 재파싱 불가한 바이트열이 만들어진다 —
같은 내용이 평면마다 다르게 해석되는 정규화 분열이다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """``value`` 를 정규 JSON 바이트열로 직렬화한다.

    encode 도 이 함수 안에서 실패할 수 있다 — stdlib ``json.dumps`` 는 짝 없는
    surrogate(``"\\ud800"``)를 거부하지 않고 그대로 문자열에 담는데, 그 문자열은
    UTF-8 로 encode 할 수 없어 ``UnicodeEncodeError``(``ValueError`` 서브클래스)가
    난다. 호출자는 ``TypeError``(JSON 도메인 밖 타입: set·bytes 등)와
    ``ValueError``(NaN/Infinity·lone surrogate) 둘 다 잡아 자신의 typed 실패로
    강등해야 한다 — 이 함수 자신은 강등하지 않고 그대로 전파한다(호출자마다
    감싸는 예외 타입·문구가 다르다).
    """
    canonical = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return canonical.encode("utf-8")
