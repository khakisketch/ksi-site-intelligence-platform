"""작업 임차(lease) 판정 — ``ProcessingJobStore`` 와 ``ComparisonRequestStore`` 가

공유하는 순수 함수 3개 (P1-2).

## 이 모듈이 소유하는 것

"발행 → **lease** → 입력조회 → 전이 → 만료회수" 프로토콜 중 **lease 판정**만.
``JobLease`` 데이터클래스(원래 ``processing_jobs.py`` 소속, 하위호환을 위해
거기서 그대로 재수출된다)와, 그 값을 놓고 "지금 이 워커가 쥐고 있는가",
"지금 누구든 새로 쥘 수 있는가", "새 lease 값은 무엇인가"를 판정하는 순수
함수 셋이다.

## 이 모듈이 소유하지 않는 것

journal append, verdict 열거형(``ProcessingJobVerdict`` / ``ComparisonRequestVerdict``),
FIFO 정렬, limit 처리, 상태 전이표 — 이건 전부 각 store 의 도메인 책임으로
남는다. 특히 :class:`LeaseDenialReason` 은 store 중립적인 "거부 사유의 종류"만
반환한다 — 각 store 가 이걸 자기 자신의 verdict enum 으로 번역해서 HTTP 상태
코드를 정한다. 여기서 verdict 를 직접 반환하면 두 store 가 이 모듈을 통해
결합되고, 한쪽 verdict 이름이 바뀔 때 다른 쪽까지 흔들린다.

## 왜 store 클래스를 합치지 않는가

``ProcessingJobStore`` 와 ``ComparisonRequestStore`` 는 레코드 타입도, 전이표도
(``CANCELLED`` 유무) 다르다 — 이 모듈은 그 둘이 우연히 같은 모양으로 반복한
lease 판정 3줄짜리 로직만 뽑아낸 것이지, 두 store 를 하나로 묶으려는 시도가
아니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from ksi_event_contracts.processing_job import ProcessingJobStatus


@dataclass(frozen=True, slots=True)
class JobLease:
    """작업 하나를 쥔 워커 — **만료는 저장된 플래그가 아니라 시각 비교다.**

    ``released``/``expired`` 같은 불리언을 두지 않는 것이 의도다. 그런 필드는
    누군가 갱신해줘야 참이 되고, 그 갱신을 빠뜨리면 죽은 워커가 영원히 살아
    있는 것으로 보인다 — 시간축 상태를 실체화한 불리언으로 들고 있으면 그
    불리언과 시계가 어긋나는 순간이 반드시 온다. 여기서는 ``expires_at`` 만
    남기고 :meth:`is_active` 가 매번 ``now`` 로 판정한다.

    재생에도 같은 성질이 필요하다 — journal 을 며칠 뒤에 재생하면 그때의
    ``now`` 로 판정되어 자동으로 만료된 상태가 된다(재생 시점에 별도 만료 처리를
    할 필요가 없다).
    """

    worker_id: str
    granted_at: datetime
    expires_at: datetime

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at

    def held_by(self, worker_id: str, now: datetime) -> bool:
        return self.is_active(now) and self.worker_id == worker_id


class LeaseDenialReason(StrEnum):
    """lease 소유권 검사가 거부할 때의 사유 종류 — store 중립적.

    각 store 의 ``_check_lease_locked`` 가 이 값을 자기 자신의 verdict(예:
    ``ProcessingJobVerdict.LEASE_REQUIRED`` / ``LEASE_HELD_BY_ANOTHER``)와
    detail 문면으로 번역한다. 이 모듈은 그 번역표를 갖지 않는다.
    """

    # lease 가 없거나(한 번도 잡힌 적 없음) 만료됐다 — 지금은 누구의 것도
    # 아니므로 새로 잡을 수 있다.
    MISSING_OR_EXPIRED = "missing_or_expired"
    # 유효한 lease 가 있는데 다른 워커의 것이다.
    HELD_BY_ANOTHER = "held_by_another"


def check_lease(
    lease: JobLease | None, *, worker_id: str, now: datetime
) -> LeaseDenialReason | None:
    """이 워커가 지금 이 lease 를 쥐고 있는가 — 워커 행위의 공통 관문.

    통과(``None``)는 "lease 가 있고, 만료되지 않았고, 이 워커의 것"일 때만이다.
    ``acquire_lease`` 의 경합 판정도 이 함수를 재사용한다 — "지금 이 워커의
    갱신인가"와 "다른 워커가 막고 있는가"가 같은 질문의 두 얼굴이기 때문이다
    (``None`` 이면 갱신, ``HELD_BY_ANOTHER`` 면 거부, ``MISSING_OR_EXPIRED`` 면
    새로 잡을 수 있다).
    """
    if lease is None or not lease.is_active(now):
        return LeaseDenialReason.MISSING_OR_EXPIRED
    if lease.worker_id != worker_id:
        return LeaseDenialReason.HELD_BY_ANOTHER
    return None


def is_claimable(status: ProcessingJobStatus, lease: JobLease | None, now: datetime) -> bool:
    """이 상태·lease 조합이 지금 획득 가능한 후보인가 — ``list_pending`` 필터.

    ``QUEUED`` 는 항상 후보다. ``RUNNING`` 은 lease 가 없거나 만료됐을 때만
    후보다(죽은 워커가 쥔 채 멈춘 작업의 회수 경로). 활성 lease 를 쥔
    ``RUNNING`` 과 종료 상태(``SUCCEEDED``·``FAILED``·``CANCELLED``)는 후보가
    아니다.
    """
    if status is ProcessingJobStatus.QUEUED:
        return True
    return status is ProcessingJobStatus.RUNNING and (lease is None or not lease.is_active(now))


def next_lease(
    *, worker_id: str, now: datetime, ttl: timedelta, granted_at: datetime | None = None
) -> JobLease:
    """새 lease 값을 조립한다.

    ``granted_at`` 을 생략하면 ``now`` 다(신규 취득). 갱신(같은 워커의 재호출)
    시에는 호출자가 기존 ``lease.granted_at`` 을 넘겨 최초 취득 시각을
    보존한다 — "얼마나 오래 쥐고 있었는지"가 남아야 정체된 워커를 알아볼 수
    있다.
    """
    return JobLease(
        worker_id=worker_id,
        granted_at=granted_at if granted_at is not None else now,
        expires_at=now + ttl,
    )


__all__ = [
    "JobLease",
    "LeaseDenialReason",
    "check_lease",
    "is_claimable",
    "next_lease",
]
