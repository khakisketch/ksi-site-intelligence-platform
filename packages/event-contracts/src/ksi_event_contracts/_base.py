"""camelCase alias·extra forbid 공통 베이스 — 이 패키지의 모든 계약 모델이 공유한다.

패키지 안의 다른 모듈에서 이미 서로를 import 하는 관례가 있다(예:
``comparison_request.py`` 가 ``change_detection_result.ArtifactRef`` 를 가져다 쓴다) —
이 leaf 모듈도 같은 관례를 따른다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """``allow_inf_nan=False`` 가 이 베이스에 있는 이유 — durable 원장 보호.

    ``NaN``/``Infinity`` 는 JSON 문법상 합법 입력인데(``json.loads`` 기본값이 받는다)
    ``DurableJournal._append_durable`` 은 ``json.dumps(allow_nan=False)`` 를 쓴다. 그래서
    비유한 실수가 계약 검증을 통과해 원장에 닿으면 append 가 터지고, ``append`` 는
    그 예외를 **봉인으로 승격**한다 — 그 저장소가 프로세스 수명 내내 죽는다. 한 번의
    요청으로 서비스가 영구히 멈추는 경로다(2026-08-18 전수 조사 Class C).

    필드마다 ``Field(allow_inf_nan=False)`` 를 다는 방식은 이미 실패했다. 이 패키지의
    float 필드 67개 중 65개가 그 지정 없이 있었고, 그중 다수는 ``ge``/``le`` 만 걸려
    ``inf >= 0`` 이 참이라 그대로 통과했다. 새 필드가 추가될 때마다 잊는 종류의
    규칙은 베이스에 두어야 한다 — 잊을 자리를 없앤다.

    운영상 이 값들은 "일시 장애(503+Retry-After)"로 보여 워커가 영원히 재시도하는데
    실제로는 생산자의 영구 계약 위반이다. 검증 단계에서 422 로 거부해야 그 구분이 선다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )
