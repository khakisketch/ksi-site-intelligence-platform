"""현장의 공간모델 유무·최신도 판정 (ADR-KSI-019 G1).

## 두 번째 원장을 만들지 않는다

"이 현장에 공간모델이 있는가"는 새 저장소가 아니라 **처리 작업 원장 위의 순수
파생 판정**이다. :class:`~ksi_core.processing_jobs.ProcessingJobRecord` 가 곧
재구성 epoch 이고(ADR-KSI-016 D3, ``ProcessingJobStore.list_for_site`` docstring),
그 옆에 ``SpatialModel`` 레코드를 따로 두면 job 과 1:1 그림자 원장이 생겨 "둘 중
뭐가 진실이냐"가 만들어진다.

그래서 :func:`evaluate_spatial_model` 은 순수 함수다 — 입력은 그 현장의 처리 작업
목록과 시각과 정책값뿐이고 아무것도 쓰지 않는다. 호출자의 정렬에도 좌우되지
않는다(스스로 최신을 고른다).

## 무엇을 "공간모델이 있다"로 세는가

``SUCCEEDED`` 이면서 ``lineage.authority == source`` 산출물을 최소 1건 가진 작업만
센다. 이건 INV-051 의 :func:`~ksi_core.processing_jobs.assert_succeeded_is_backed`
게이트가 전이 시점에 이미 강제하는 조건과 **같은 조건을 읽는 쪽에서 다시 확인**하는
것이다 — 게이트가 나중에 완화되거나 손으로 고친 원장이 재생돼도 조회 판정은
독립적으로 성립해야 한다.

파생 산출물(Mesh·정사영상·DSM)만 있는 작업은 세지 않는다: 원본 없이 파생만 있는
상태를 "모델이 있다"로 읽으면 ADR-KSI-003 의 원본/파생 권위 구분이 조회 표면에서
무너진다.

## 나이 기준을 서버가 지어내지 않는다

MASTER_PRD §6.3 은 ``MODEL_STALE`` 이라는 **상태만** 정의하고 며칠이면 낡은
것인지는 정하지 않는다. 서버가 임의의 기본값(예: 30일)을 박으면 근거 없는 숫자가
현장의 자율운영 가능 여부를 가르게 된다.

그래서 나이 기준은 **현장이 선언한다**(``SiteRecord.model_max_age_days``).
선언하지 않은 현장은 ``FRESH`` 로 뭉개지 않고 :attr:`SpatialModelState.
AGE_POLICY_UNDECLARED` 로 낸다 — "판정하지 않았다"와 "판정했더니 최신이다"는 다른
사실이고, 전자를 후자로 표시하면 화면이 근거 없는 안심을 준다(INV-040 정신).

## ``registered_at`` 은 "모델이 등록된 시각"이지 "세상을 관측한 시각"이 아니다

나이의 기준점은 그 작업이 ``SUCCEEDED`` 로 전이한 시각(``updated_at``)이다.
정확히는 촬영 시각이 더 옳지만, 촬영 시각을 임무 원장에서 끌어오려면 임무 실행
생애주기(ADR-KSI-019 G2)가 먼저 있어야 한다. 필드 이름이 그 한계를 말하게 두고
나중에 좁힐 여지를 남긴다 — 이름을 ``captured_at`` 으로 붙여놓고 등록 시각을 담는
것이 더 나쁘다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from fastapi import APIRouter, Depends, HTTPException
from ksi_domain.enums import MissionType, SiteStatus
from ksi_domain.mission_gating import MAPPING_FROM_SCRATCH_MISSION_TYPES
from ksi_event_contracts.processing_artifact import LineageAuthority
from ksi_event_contracts.processing_job import ProcessingJobStatus

from ksi_core.api_base import CamelModel
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.metrics import SITE_AUTO_ADVANCES
from ksi_core.sites import SiteVerdict

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.processing_jobs import ProcessingJobRecord
    from ksi_core.sites import SiteStore

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400.0
_SITE_NOT_FOUND_DETAIL = "현장을 찾을 수 없다"


class SpatialModelState(StrEnum):
    """현장의 공간모델 판정 결과 4종."""

    #: 원본 산출물을 가진 성공한 재구성이 하나도 없다.
    ABSENT = "ABSENT"
    #: 최신 epoch 이 현장이 선언한 나이 기준 안이다(경계 포함).
    FRESH = "FRESH"
    #: 최신 epoch 이 현장이 선언한 나이 기준을 넘었다.
    STALE = "STALE"
    #: epoch 은 있는데 현장이 나이 기준을 선언하지 않아 노후를 **판정하지 않았다**.
    AGE_POLICY_UNDECLARED = "AGE_POLICY_UNDECLARED"


@dataclass(frozen=True, slots=True)
class SpatialModelStatus:
    """판정 1건 — 결론과 그 결론이 나온 근거를 함께 들고 다닌다."""

    state: SpatialModelState
    #: 판정 근거가 된 최신 epoch 의 작업 id. ``ABSENT`` 면 ``None``.
    epoch_job_id: str | None
    #: 그 epoch 이 ``SUCCEEDED`` 로 전이한 시각(모듈 docstring 참조).
    registered_at: datetime | None
    #: ``now - registered_at`` (일). 음수는 0 으로 절단한다.
    age_days: float | None
    #: 현장이 선언한 나이 기준. 미선언이면 ``None``.
    max_age_days: int | None
    #: 최신 epoch 의 ``authority=source`` 산출물 수.
    source_artifact_count: int
    #: 이 현장의 원본 뒷받침된 성공 epoch 총수(이력 깊이).
    succeeded_epoch_count: int


def has_source_artifact(record: ProcessingJobRecord) -> bool:
    """이 작업이 원본(SSOT) 산출물을 가졌는가 — 파생만으로는 거짓."""
    return any(
        artifact.lineage.authority is LineageAuthority.SOURCE for artifact in record.artifacts
    )


def is_spatial_model_epoch(record: ProcessingJobRecord) -> bool:
    """이 작업을 "공간모델 1세대"로 셀 수 있는가 — 성공 + 원본 산출물 둘 다."""
    return record.status is ProcessingJobStatus.SUCCEEDED and has_source_artifact(record)


def evaluate_spatial_model(
    jobs: Sequence[ProcessingJobRecord],
    *,
    now: datetime,
    max_age_days: int | None,
) -> SpatialModelStatus:
    """이 현장의 공간모델 상태를 판정한다 — 순수 함수, 아무것도 쓰지 않는다.

    Args:
        jobs: 이 현장의 처리 작업 전량. 정렬은 무관하다 — 이 함수가 스스로 최신을
            고른다(호출자의 정렬에 판정이 좌우되면 같은 원장에서 다른 답이 나온다).
        now: 판정 시각(tz-aware 필수).
        max_age_days: 현장이 선언한 노후 기준. ``None`` 이면 노후를 **판정하지 않는다**.

    Raises:
        ValueError: ``now`` 가 naive 일 때.
    """
    if now.tzinfo is None:
        raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")

    epochs = [record for record in jobs if is_spatial_model_epoch(record)]
    if not epochs:
        # 모델이 없으면 정책 미선언보다 "없음"이 먼저다 — 없는 모델은 나이가 없다.
        return SpatialModelStatus(
            state=SpatialModelState.ABSENT,
            epoch_job_id=None,
            registered_at=None,
            age_days=None,
            max_age_days=max_age_days,
            source_artifact_count=0,
            succeeded_epoch_count=0,
        )

    # 같은 시각이면 job_id 로 결정적으로 고른다 — 재생마다 다른 epoch 를 고르면
    # 같은 원장에서 다른 판정이 나온다.
    newest = max(epochs, key=lambda record: (record.updated_at, record.job_id))
    # 시계 어긋남으로 미래 시각이 들어와도 음수 나이를 내지 않는다.
    age_days = max(0.0, (now - newest.updated_at).total_seconds() / _SECONDS_PER_DAY)

    if max_age_days is None:
        state = SpatialModelState.AGE_POLICY_UNDECLARED
    elif age_days > max_age_days:
        state = SpatialModelState.STALE
    else:
        # 경계는 포함이다 — "30일 기준"이 30일째에 끊기면 사용자 기대와 어긋난다.
        state = SpatialModelState.FRESH

    return SpatialModelStatus(
        state=state,
        epoch_job_id=newest.job_id,
        registered_at=newest.updated_at,
        age_days=age_days,
        max_age_days=max_age_days,
        source_artifact_count=sum(
            1
            for artifact in newest.artifacts
            if artifact.lineage.authority is LineageAuthority.SOURCE
        ),
        succeeded_epoch_count=len(epochs),
    )


#: 그 현장 상태가 "공간모델이 있다"를 전제로 하는가.
#:
#: ``MODEL_VALIDATION`` 을 포함한다 — 검증할 모델이 없는 검증 상태는 성립하지 않는다.
#: ``MODEL_STALE`` 도 포함한다 — 낡았다는 판정 자체가 모델의 존재를 전제한다.
#: ``BASELINE_MAPPING``·``MODEL_PROCESSING`` 은 **제외**다: 그 둘은 정확히 "아직
#: 모델이 없고 만드는 중"인 상태다.
_STATUSES_THAT_ASSUME_A_MODEL: frozenset[SiteStatus] = frozenset(
    {
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
        SiteStatus.PATROL_ACTIVE,
        SiteStatus.MODEL_STALE,
    }
)


def site_status_matches_model(state: SpatialModelState, site_status: SiteStatus) -> bool:
    """현장 상태가 실제 모델 유무와 앞뒤가 맞는가.

    거짓이면 자동 전진이 막혔거나 사람이 근거 없이 상태를 올린 것이다 — 화면이 그
    모순을 볼 수 있어야 한다. 이 함수는 **판정만** 하고 아무것도 고치지 않는다:
    조회가 원장을 되돌리기 시작하면 상태가 조회 시점에 따라 달라진다.

    낡은 모델(``STALE``)은 모순이 아니다 — 모델이 낡은 것과 없는 것은 다른 사실이고,
    ``MODEL_STALE`` 은 그 낡음을 이미 표현하는 정상 상태다.
    """
    if site_status not in _STATUSES_THAT_ASSUME_A_MODEL:
        return True
    return state is not SpatialModelState.ABSENT


class SiteAdvanceOutcome(StrEnum):
    """자동 전진 1회의 결과 — 실패도 typed 로 돌려주고 예외를 던지지 않는다."""

    ADVANCED = "ADVANCED"
    #: 이 신호에 대응하는 전진 규칙이 없다(FAILED·CANCELLED 등).
    NO_RULE = "NO_RULE"
    #: 규칙의 출발 상태가 아니고, 진행 축에서 이미 도착 상태를 지났다.
    ALREADY_PAST = "ALREADY_PAST"
    #: 출발 상태도 아니고 뒤쪽도 아니다 — 상태머신이 허용하지 않는다.
    ILLEGAL_FROM_CURRENT = "ILLEGAL_FROM_CURRENT"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


#: SSOT — 처리 작업 상태가 현장을 **어디서 어디로** 밀어야 하는가. (출발, 도착) 쌍인
#: 것이 요점이다: 출발 상태가 아닌 현장은 건드리지 않는다. 상태머신이 허용한다는
#: 이유로 아무 데서나 밀면 자동화가 사람의 판단을 덮어쓴다.
#:
#: 이 표에 자율운영 승인 간선(``requires_autonomy_approval`` 참)을 넣지 않는다 —
#: 그 보증은 ``test_spatial_model.py`` 의 규칙표 전수 검사가 구조적으로 강제한다.
_JOB_STATUS_SITE_ADVANCE: dict[ProcessingJobStatus, tuple[SiteStatus, SiteStatus]] = {
    # 재구성 작업이 만들어졌다 = 처리가 시작됐다.
    ProcessingJobStatus.QUEUED: (SiteStatus.BASELINE_MAPPING, SiteStatus.MODEL_PROCESSING),
    # 원본 산출물을 가진 성공 = 공간모델이 생겼다. **검증까지 자동으로 하지 않는다** —
    # MODEL_VALIDATION 이 종착이고 그 다음(자율 개시)은 사람의 승인이다.
    ProcessingJobStatus.SUCCEEDED: (
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
    ),
}

#: 매핑 진행 축의 선형 순서 — "이미 지났다"를 판정하는 데만 쓴다. ``SUSPENDED``·
#: ``REMAP_REQUIRED`` 는 축 밖이라 넣지 않는다(둘 다 ILLEGAL 로 읽히는 것이 맞다:
#: 운영 중단·재매핑 대기 현장을 자동화가 앞으로 밀면 안 된다).
_PROGRESS_ORDER: tuple[SiteStatus, ...] = (
    SiteStatus.UNMAPPED,
    SiteStatus.BASELINE_MAPPING,
    SiteStatus.MODEL_PROCESSING,
    SiteStatus.MODEL_VALIDATION,
    SiteStatus.PROVISIONAL_AUTONOMY,
    SiteStatus.PATROL_READY,
    SiteStatus.PATROL_ACTIVE,
)

#: 자동 전이의 actor — 사람과 구분된다. 감사 원장에서 "이 전이를 누가 했나"에
#: 답할 수 있어야 자동화가 사람의 결정을 조용히 대신하지 않았음을 보일 수 있다.
_SYSTEM_ACTOR = "system:spatial-model-lifecycle"


def _is_at_or_past(current: SiteStatus, target: SiteStatus) -> bool:
    """``current`` 가 매핑 진행 축에서 ``target`` 이후인가 — 축 밖이면 거짓."""
    if current not in _PROGRESS_ORDER or target not in _PROGRESS_ORDER:
        return False
    return _PROGRESS_ORDER.index(current) >= _PROGRESS_ORDER.index(target)


class SpatialModelLifecycle:
    """재구성 신호를 받아 현장 상태를 전진시킨다 — 라우터 계층에서만 호출한다.

    ## 왜 저장소 안이 아니라 여기인가

    ``ProcessingJobStore`` 안에서 ``SiteStore`` 를 부르면 두 잠금을 겹쳐 쥐게 되고,
    그 순간 잠금 순서가 아키텍처 제약이 된다. 여기서는 작업 저장소 호출이 **끝난
    뒤** 별도로 부르므로 겹치지 않는다.

    ## 전진 실패는 원래 요청을 깨뜨리지 않는다

    모든 실패를 :class:`SiteAdvanceOutcome` 으로 돌려주고 예외를 던지지 않는다.
    현장 상태가 어긋났다는 이유로 워커의 재구성 성공 보고가 500 이 되면, 되돌릴 수
    없는 계산 결과가 유실된다. 대신 결과를 metric(``SITE_AUTO_ADVANCES``)으로 세고
    비정상(``ILLEGAL_FROM_CURRENT``)만 로그로 남긴다.
    """

    def __init__(
        self,
        *,
        site_store: SiteStore,
        processing_job_store: _SiteJobLister | None = None,
    ) -> None:
        """``processing_job_store`` 는 노후 스윕에만 필요하다.

        없이도 임무 배포·재구성 신호에 따른 전진은 성립한다 — 재구성 원장이 없는
        조립에서도 "매핑 임무가 배포됐으니 현장이 매핑을 시작했다"는 사실은 참이다.
        스윕만 판정 근거(epoch 목록)를 잃어 아무것도 하지 않고, 그 사실을 로그로
        드러낸다(조용한 no-op 을 만들지 않는다).
        """
        self._site_store = site_store
        self._processing_job_store = processing_job_store

    def advance_for_job_status(
        self,
        site_id: str,
        job_status: ProcessingJobStatus,
        *,
        job_id: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        """재구성 작업 상태 하나를 현장 전진 신호로 해석한다."""
        rule = _JOB_STATUS_SITE_ADVANCE.get(job_status)
        if rule is None:
            return _record_outcome(SiteAdvanceOutcome.NO_RULE, target=None)
        source, target = rule
        return self._advance(
            site_id,
            source_statuses=(source,),
            target=target,
            evidence=f"processingJob={job_id} status={job_status.value}",
            reason="재구성 신호에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )

    def advance_for_mission_dispatched(
        self,
        site_id: str,
        mission_type: MissionType,
        *,
        mission_id: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        """매핑 계열 임무가 기체로 넘어갔다 = 그 현장의 매핑이 시작됐다.

        **발급이 아니라 배포가 기준이다** — 발급만 하고 안 날린 임무가 현장 상태를
        옮기면, 계획 단계의 문서가 관측 사실을 참칭한다. 어느 임무타입이 "지도를
        처음부터 만드는" 계열인지는 :data:`~ksi_domain.mission_gating.
        MAPPING_FROM_SCRATCH_MISSION_TYPES` 가 SSOT다(여기에 목록을 복사하지 않는다).
        """
        if mission_type not in MAPPING_FROM_SCRATCH_MISSION_TYPES:
            return _record_outcome(SiteAdvanceOutcome.NO_RULE, target=None)
        return self._advance(
            site_id,
            # REMAP_REQUIRED 도 출발점이다 — 재매핑 지시를 받은 현장에 매핑 임무가
            # 배포되면 그것이 곧 재매핑 시작이다(_MAPPING_FROM_SCRATCH 와 같은 집합).
            source_statuses=(SiteStatus.UNMAPPED, SiteStatus.REMAP_REQUIRED),
            target=SiteStatus.BASELINE_MAPPING,
            evidence=f"mission={mission_id} type={mission_type.value} dispatched",
            reason="매핑 계열 임무 배포에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )

    def sweep_staleness(self, site_id: str, *, now: datetime) -> SiteAdvanceOutcome:
        """모델이 현장이 선언한 나이 기준을 넘었으면 ``MODEL_STALE`` 로 옮긴다.

        선언이 없으면(``AGE_POLICY_UNDECLARED``) 아무것도 하지 않는다 — 서버가 기준을
        지어내 자율운영을 끊지 않는다.

        ``PATROL_READY``·``PATROL_ACTIVE`` 에서만 동작한다: 그 둘이 "이 모델을 믿고
        자율로 돈다"를 뜻하는 상태이고, 나머지 상태에서는 노후가 이미 진행 중인
        작업(매핑·처리·검증)으로 표현돼 있다.

        **조회가 아니라 명시적 표면이 부른다** — 조회가 원장을 바꾸면 상태가 조회
        시점에 따라 달라진다. 주기 실행은 배포 운영(systemd timer·cron)의 몫이다.
        """
        if self._processing_job_store is None:
            # 판정 근거(재구성 epoch 목록)가 없는 조립이다. 조용히 넘기지 않고
            # 로그로 드러낸다 — 이 조립에서는 노후가 영원히 판정되지 않는다.
            logger.warning(
                "노후 스윕 건너뜀 — site=%s: 재구성 원장이 이 조립에 없다", site_id
            )
            return _record_outcome(SiteAdvanceOutcome.NO_RULE, target=None)
        site = self._site_store.get(site_id)
        if site is None:
            return _record_outcome(
                SiteAdvanceOutcome.UNKNOWN_SITE, target=SiteStatus.MODEL_STALE
            )
        if site.status not in (SiteStatus.PATROL_READY, SiteStatus.PATROL_ACTIVE):
            return _record_outcome(SiteAdvanceOutcome.NO_RULE, target=None)
        status = evaluate_spatial_model(
            self._processing_job_store.list_for_site(site_id),
            now=now,
            max_age_days=site.model_max_age_days,
        )
        if status.state is not SpatialModelState.STALE:
            return _record_outcome(SiteAdvanceOutcome.NO_RULE, target=None)
        assert status.age_days is not None  # noqa: S101 -- STALE 은 나이가 있을 때만 나온다
        return self._advance(
            site_id,
            source_statuses=(SiteStatus.PATROL_READY, SiteStatus.PATROL_ACTIVE),
            target=SiteStatus.MODEL_STALE,
            evidence=(
                f"epoch={status.epoch_job_id} age={status.age_days:.1f}d "
                f"maxAge={status.max_age_days}d"
            ),
            reason="공간모델 노후 판정에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )

    def _advance(
        self,
        site_id: str,
        *,
        source_statuses: tuple[SiteStatus, ...],
        target: SiteStatus,
        evidence: str,
        reason: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        """전진 1회 — 세 진입점(작업 상태·임무 배포·노후 스윕)이 공유한다."""
        site = self._site_store.get(site_id)
        if site is None:
            return _record_outcome(SiteAdvanceOutcome.UNKNOWN_SITE, target=target)
        if site.status not in source_statuses:
            outcome = (
                SiteAdvanceOutcome.ALREADY_PAST
                if _is_at_or_past(site.status, target)
                else SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
            )
            if outcome is SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT:
                logger.warning(
                    "자동 전진 건너뜀 — site=%s 현재=%s 규칙=%s→%s (%s)",
                    site_id,
                    site.status.value,
                    "|".join(s.value for s in source_statuses),
                    target.value,
                    evidence,
                )
            return _record_outcome(outcome, target=target)

        result = self._site_store.transition(
            site_id,
            target,
            evidence=evidence,
            reason=reason,
            actor=_SYSTEM_ACTOR,
            now=now,
        )
        if result.verdict is SiteVerdict.TRANSITIONED:
            return _record_outcome(SiteAdvanceOutcome.ADVANCED, target=target)
        if result.verdict is SiteVerdict.STORE_UNAVAILABLE:
            return _record_outcome(SiteAdvanceOutcome.STORE_UNAVAILABLE, target=target)
        return _record_outcome(SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT, target=target)


def _record_outcome(
    outcome: SiteAdvanceOutcome, *, target: SiteStatus | None
) -> SiteAdvanceOutcome:
    """결과를 세고 그대로 돌려준다 — 건너뛴 전진이 조용히 사라지지 않게."""
    SITE_AUTO_ADVANCES.inc(
        outcome=outcome.value, target_status=target.value if target is not None else "none"
    )
    return outcome


class SpatialModelView(CamelModel):
    """조회 응답 — 결론과 근거와 현장 상태 정합을 함께 낸다."""

    site_id: str
    state: str
    epoch_job_id: str | None
    registered_at: str | None
    age_days: float | None
    max_age_days: int | None
    source_artifact_count: int
    succeeded_epoch_count: int
    site_status: str
    #: 거짓이면 현장 상태가 실제 모델 유무와 어긋난다(위 함수 docstring).
    site_status_matches_model: bool


class _SiteJobLister(Protocol):
    """이 라우터가 처리 작업 저장소에 요구하는 전부 — 그 현장의 작업 목록 하나뿐.

    ``ProcessingJobStore`` 전체를 타입으로 요구하면 이 모듈이 그 저장소의 발급·
    lease·산출물 표면 전체에 결합된다. 조회 판정에 필요한 것은 읽기 하나다.
    """

    def list_for_site(
        self, site_id: str, *, limit: int | None = ...
    ) -> list[ProcessingJobRecord]: ...


def build_spatial_model_router(
    *,
    site_store: SiteStore,
    processing_job_store: _SiteJobLister,
    lifecycle: SpatialModelLifecycle | None = None,
) -> APIRouter:
    """``lifecycle`` 을 주면 노후 스윕 표면이 함께 장착된다."""
    router = APIRouter(prefix="/v1/sites", tags=["sites"])

    @router.get("/{site_id}/spatial-model", response_model=SpatialModelView)
    def get_spatial_model(
        site_id: str,
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> SpatialModelView:
        """이 현장의 공간모델 유무·최신도. 저장된 값이 아니라 **매 호출 재계산**이다.

        재계산이 요점이다 — 판정을 어딘가에 저장하면 그 값과 처리 작업 원장이
        갈라질 수 있고, 그 순간 "둘 중 뭐가 진실이냐"가 생긴다(모듈 docstring).
        """
        site = site_store.get(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail=_SITE_NOT_FOUND_DETAIL)
        status = evaluate_spatial_model(
            processing_job_store.list_for_site(site_id),
            now=datetime.now(UTC),
            max_age_days=site.model_max_age_days,
        )
        return SpatialModelView(
            site_id=site_id,
            state=status.state.value,
            epoch_job_id=status.epoch_job_id,
            registered_at=(
                status.registered_at.isoformat() if status.registered_at is not None else None
            ),
            age_days=status.age_days,
            max_age_days=status.max_age_days,
            source_artifact_count=status.source_artifact_count,
            succeeded_epoch_count=status.succeeded_epoch_count,
            site_status=site.status.value,
            site_status_matches_model=site_status_matches_model(status.state, site.status),
        )

    if lifecycle is not None:

        @router.post(
            "/{site_id}/spatial-model/staleness-sweep", response_model=SpatialModelView
        )
        def sweep_site_staleness(
            site_id: str,
            _principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
        ) -> SpatialModelView:
            """노후 판정을 지금 적용한다 — 운영자·배치 잡이 부르는 **명시적** 표면.

            조회(``GET .../spatial-model``)가 이 일을 하지 않는 것이 의도다: 조회가
            원장을 바꾸면 현장 상태가 "누가 언제 화면을 열었는가"에 좌우된다.

            **주기 실행은 이 서비스가 소유하지 않는다** — systemd timer·cron 같은
            배포 운영 계층이 이 엔드포인트를 부른다. 서버 안에 스케줄러를 두면 그
            주기가 배포 설정이 아니라 코드가 되고, 운영에서 관측하기 어려워진다.

            ``SITES_AUTONOMY_APPROVE`` 를 요구하지 않는다 — PATROL_READY →
            MODEL_STALE 은 자율을 **끊는** 방향이라 승인 간선이 아니다
            (``requires_autonomy_approval`` 참조). 자율 복귀에는 여전히 재검증
            경로와 승인이 필요하다.
            """
            if site_store.get(site_id) is None:
                raise HTTPException(status_code=404, detail=_SITE_NOT_FOUND_DETAIL)
            lifecycle.sweep_staleness(site_id, now=datetime.now(UTC))
            # 스윕 결과와 무관하게 **판정 후 현재 상태**를 그대로 낸다 — 옮겼든
            # 안 옮겼든 호출자가 알고 싶은 것은 "지금 이 현장이 어떤가"다.
            return get_spatial_model(site_id, _principal)

    return router


def mount_spatial_model(
    app: FastAPI,
    *,
    site_store: SiteStore,
    processing_job_store: _SiteJobLister,
    lifecycle: SpatialModelLifecycle | None = None,
) -> None:
    """앱에 공간모델 조회 라우터를 장착한다.

    호출자는 **처리 작업 저장소가 실제로 있을 때만** 부른다 — 재구성 원장이 없는
    조립에서 이 표면을 열면 모든 현장이 영원히 ``ABSENT`` 라고 답하는 거짓 표면이
    된다(``create_app`` 참조).
    """
    app.include_router(
        build_spatial_model_router(
            site_store=site_store,
            processing_job_store=processing_job_store,
            lifecycle=lifecycle,
        )
    )


__all__ = [
    "SiteAdvanceOutcome",
    "SpatialModelLifecycle",
    "SpatialModelState",
    "SpatialModelStatus",
    "SpatialModelView",
    "build_spatial_model_router",
    "evaluate_spatial_model",
    "has_source_artifact",
    "is_spatial_model_epoch",
    "mount_spatial_model",
    "site_status_matches_model",
]
