"""camelCase alias·extra forbid 공통 베이스 — 이 패키지의 모든 계약 모델이 공유한다.

패키지 안의 다른 모듈에서 이미 서로를 import 하는 관례가 있다(예:
``comparison_request.py`` 가 ``change_detection_result.ArtifactRef`` 를 가져다 쓴다) —
이 leaf 모듈도 같은 관례를 따른다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
