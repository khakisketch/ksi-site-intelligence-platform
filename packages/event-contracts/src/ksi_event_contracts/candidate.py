"""EventCandidate 최소 모델 — Detection → Observation → Candidate 진입 전 표현.

upstream Scout contracts/event.py @42ccc0db 의 ``EventCandidate``/``Event`` 패턴을
PORT — 단일 프레임 감지 결과를 이벤트 상태머신에 진입시키기 전 최소 필드(track 참조·
type·severity·first/last seen·status)만 채택한다. Scout의 ``bbox``/``actions``/
장비별 detail 등 site-safety 세부 필드는 KSI Site Intelligence 계약 범위 밖이라
제외했다(dedup·temporal 누적은 상위 Event Engine 책임 — Scout와 동일 분리).

INV-031(Detector 결과를 Event로 직접 저장하지 않는다)에 따라 이 모델은 상태전이표
바깥의 임시 표현이다 — Event로 승격할 때는 ``ksi_domain.enums.assert_event_transition``
을 경유해 ``status``를 부여한다(``cur=None`` → ``OBSERVATION``만 허용).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ksi_domain.enums import EventStatus, Severity
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class EventCandidate(BaseModel):
    """단일 프레임 이벤트 후보. dedup·temporal 누적은 Event Engine이 담당한다."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    track_ref: str | None = None
    event_type: str
    severity: Severity
    first_seen_at: datetime
    last_seen_at: datetime
    status: EventStatus = EventStatus.OBSERVATION
    detail: dict[str, Any] = Field(default_factory=dict)
