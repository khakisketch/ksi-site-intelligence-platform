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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_event_contracts.processing_artifact import LineageAuthority
from ksi_event_contracts.processing_job import ProcessingJobStatus

if TYPE_CHECKING:
    from ksi_core.processing_jobs import ProcessingJobRecord

_SECONDS_PER_DAY = 86400.0


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


__all__ = [
    "SpatialModelState",
    "SpatialModelStatus",
    "evaluate_spatial_model",
    "has_source_artifact",
    "is_spatial_model_epoch",
]
