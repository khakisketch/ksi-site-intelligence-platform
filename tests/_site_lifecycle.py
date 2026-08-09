"""테스트 전용 — SiteStore 를 UNMAPPED 에서 목표 상태까지 합법 경로로 전진시킨다.

mission-type × site-status 게이트(INV-052, `packages/domain/src/ksi_domain/
mission_gating.py`) 테스트가 여러 파일에서 반복하는 "8단계 상태머신 중 몇
단계까지 전이해야 하는가"를 한 곳에 모은다(`test_dfine_detector.py` 등이 쓰는
공유 게이트 헬퍼 관습과 동일 근거 — 파일별 복붙은 한 곳만 갱신될 때 다른
파일이 조용히 낡은 경로를 쓰게 만든다).

HTTP 전이 엔드포인트가 아니라 :class:`~ksi_core.sites.SiteStore` 를 직접
호출한다 — 이 헬퍼가 검증 대상으로 삼는 것은 전이 자체(`test_site_transitions.py`
소관)가 아니라 그 결과 상태이므로, 왕복 비용 없이 지름길로 상태만 맞춘다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ksi_domain.enums import SiteStatus

if TYPE_CHECKING:
    from ksi_core.sites import SiteStore

# UNMAPPED 로부터 각 목표 상태까지의 합법 경로(enums._ALLOWED_SITE_TRANSITIONS
# 준수). MODEL_STALE·REMAP_REQUIRED 는 정상 매핑 사이클(PATROL_READY/
# MODEL_VALIDATION)을 통과한 뒤에만 도달 가능한 상태로 취급한다 — 최초 등록
# 직후 곧바로 그 상태로 갈 수 없는 것과 같은 이유다.
_PATH_FROM_UNMAPPED: dict[SiteStatus, tuple[SiteStatus, ...]] = {
    SiteStatus.UNMAPPED: (),
    SiteStatus.BASELINE_MAPPING: (SiteStatus.BASELINE_MAPPING,),
    SiteStatus.MODEL_PROCESSING: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
    ),
    SiteStatus.MODEL_VALIDATION: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
    ),
    SiteStatus.PROVISIONAL_AUTONOMY: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
    ),
    SiteStatus.PATROL_READY: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
    ),
    SiteStatus.PATROL_ACTIVE: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
        SiteStatus.PATROL_ACTIVE,
    ),
    SiteStatus.MODEL_STALE: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
        SiteStatus.MODEL_STALE,
    ),
    SiteStatus.REMAP_REQUIRED: (
        SiteStatus.BASELINE_MAPPING,
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.REMAP_REQUIRED,
    ),
    SiteStatus.SUSPENDED: (SiteStatus.SUSPENDED,),
}


def advance_site_status(
    site_store: SiteStore, site_id: str, target: SiteStatus, *, actor: str = "test-harness"
) -> None:
    """``site_id``(방금 UNMAPPED 로 등록된 site)를 ``target`` 까지 합법 경로로 전진시킨다."""
    for step in _PATH_FROM_UNMAPPED[target]:
        result = site_store.transition(
            site_id,
            step,
            evidence=f"{step.value} 증거(테스트 헬퍼)",
            reason=f"{step.value} 사유(테스트 헬퍼)",
            actor=actor,
            now=datetime.now(UTC),
        )
        assert result.verdict.value == "TRANSITIONED", (
            f"{site_id} 를 {step.value} 로 전이하지 못했다: {result.detail}"
        )
