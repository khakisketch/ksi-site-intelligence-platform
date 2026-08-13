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

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def iso_utc(value: datetime) -> str:
    """journal 에 쓸 ``ts`` — 항상 UTC 로 정규화한다(s2-residual-hardening #2).

    오프셋을 그대로 두면 같은 순간이 원장에서 여러 표기로 남아, 문자열 정렬·
    외부 도구의 시각 비교가 오프셋마다 다른 답을 낸다.
    """
    return value.astimezone(UTC).isoformat()


JOURNAL_SEALED_DETAIL = "journal 봉인됨 — 재시작 필요"
JOURNAL_APPEND_FAILED_DETAIL = "durable 기록 실패 — journal 봉인(재시작 필요)"
