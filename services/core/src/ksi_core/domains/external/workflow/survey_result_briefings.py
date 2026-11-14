"""전수측량 구역별 근거 인용 브리핑 초안 (Task 3).

``ExternalResultBriefingProjector`` 의 survey용 변형이다 — 기존 projector를
뜯지 않고 이 모듈을 옆에 둔다. 기존 규칙은 그대로 따른다: 봉인값 복사(재계산
없음) · 인용 필수(``SiteBriefing`` READY는 citation 없으면 계약이 거부) ·
워터마크 중복제거 · uncertainty 전파. 다른 점은 셋뿐이다.

1. 입력이 봉인된 ``ChangeRegionSetReport`` + 구역별 검증 판정이다. 숫자는
   ``EVALUATED`` 판정 구역에서만 복사한다. ``PROVISIONAL_ACCURACY_UNVERIFIED``
   등 미검증 상태와 판정 없음은 수치 차단이다 — 라벨을 붙이는 것으로 대신하지
   않으며, 미검증 구역의 수치는 초안 어디에도 싣지 않는다(본문·사유·불확도·
   인용 요약 전부). 검증된 구역이 하나도 없으면 READY가 아니라 BLOCKED를
   기록한다(빈 인용 READY는 계약이 거부하므로, 코드가 그 길로 갈 수 없게).
2. 구역별 수치는 출처 digest에 결속한다. 리포트 전체의 canonical digest를
   워터마크와 구역 인용 id에 싣는다 — 같은 바이트에서 같은 digest가 나와야
   같은 초안이며, 한 글자라도 바뀌면 다른 초안이 된다.
3. ``designConformanceId`` 가 ``survey:`` 로 시작하지 않으면 fail-closed 로
   거부한다 — 설계 리포트가 이 경로로 들어오는 일을 코드에서 막는다(인계 a).

호출 방식이 기존과 다르다: 기존 projector는 저장소 이벤트 리스너라 큐+워커로
돌지만, 이 projector는 봉인 리포트를 직접 받아 동기 호출된다. 바인딩할
이벤트 소스가 없으므로 큐를 두지 않는다(YAGNI).

INV-053·CRS/수직기준 게이트는 앞단이 그대로 맡는다 — 이 projector는 게이트를
통과해 봉인된 리포트의 값만 복사하고, 검증 판정 입력 자체를 만들지 않는다.
정량·정산·현장·고객 수락을 주장하지 않는다: 본문에 그렇게 밝힌다.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.change_region_report import ChangeRegionSetReport
from ksi_event_contracts.copilot import CopilotCitation, SiteBriefingStatus
from ksi_event_contracts.external_analysis_api import AnalysisSuitabilityStateV1

_LOGGER = logging.getLogger(__name__)
_ACTOR = "system:survey-result-briefing"

#: ``designConformanceId`` 자리에서 조사 출처를 표시하는 접두사 — Task 1과
#: 같은 값(``region_extraction._SURVEY_ANCHOR_PREFIX``). 설계 리포트 id로
#: 해석·조회하지 않는다.
_SURVEY_ANCHOR_PREFIX = "survey:"

#: 수치가 초안에 들어갈 수 있는 유일한 검증 상태. 나머지는 전부 미검증으로
#: 취급한다 — ``PROVISIONAL_ACCURACY_UNVERIFIED`` 도 예외가 아니다(라벨이
#: 아니라 차단이므로).
_VERIFIED_STATE = AnalysisSuitabilityStateV1.EVALUATED


class SurveyBriefingError(RuntimeError):
    """조사 브리핑 초안이 성립하지 않는다 — 부분 초안을 기록하지 않는다."""


def _m3(value: float) -> str:
    # ``external_result_briefings._m3`` 과 같은 표시 — 봉인값의 렌더링이 두 경로에서
    # 갈라지면 같은 숫자가 다르게 보인다. private import 대신 같은 의미를 적은다.
    rounded = round(value, 1)
    if rounded == 0.0:
        rounded = 0.0  # never render a negative zero
    return f"{rounded:,.1f} m³"


def _pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def _hull_ratio_text(region: Any) -> str:
    ratio = region.hull_overcapture_ratio
    if ratio is None:
        reason = region.aoi_draft_unavailable_reason or "사유 없음"
        return f"껍질 과대포함 계산 안 됨({reason})"
    return f"껍질 과대포함 {ratio:.2f}배"


def _report_digest(report: ChangeRegionSetReport) -> str:
    """봉인 리포트 바이트의 canonical digest — 구역 수치의 출처 결속점."""
    payload = report.model_dump(by_alias=True, mode="json")
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _verification_digest(
    report: ChangeRegionSetReport,
    suitability_by_region: Mapping[str, AnalysisSuitabilityStateV1],
) -> str:
    """구역별 판정 스냅샷의 digest — 판정이 바뀌면 다른 초안이다."""
    snapshot = {
        "regions": [
            {
                "region_id": region.region_id,
                "suitability": (
                    state.value
                    if (state := suitability_by_region.get(region.region_id)) is not None
                    else "NO_VERDICT"
                ),
            }
            for region in sorted(report.regions, key=lambda item: item.region_id)
        ]
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()


class SurveyResultBriefingProjector:
    """봉인된 전수측량 리포트에서 구역별 근거 인용 브리핑 초안을 만든다.

    ``briefings`` 는 기존 projector와 같은 duck-type 저장소다 —
    ``record(...)`` 와 ``latest(site_id, organization_id=...)`` (``.source_watermark``
    보유) 만 쓴다. 같은 저장소·같은 ``SiteBriefing`` 계약에 기록하므로,
    대시보드가 기존 브리핑과 같은 방식으로 읽는다.
    """

    def __init__(
        self,
        *,
        briefings: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._briefings = briefings
        self._clock = clock or (lambda: datetime.now(UTC))

    def project(
        self,
        report: ChangeRegionSetReport,
        *,
        organization_id: str,
        site_id: str,
        suitability_by_region: Mapping[str, AnalysisSuitabilityStateV1],
    ) -> bool:
        """한 봉인 리포트를 한 초안으로 기록한다. 중복이면 건너뛰고 False.

        Raises:
            SurveyBriefingError: ``survey:`` 앵커가 아니거나, 판정 입력에
                리포트에 없는 구역 id가 있으면 — 어느 쪽도 조용한 성공으로
                만들지 않는다.
        """
        survey_id = self._survey_id_of(report)
        unknown = sorted(set(suitability_by_region) - {r.region_id for r in report.regions})
        if unknown:
            raise SurveyBriefingError(
                f"리포트({report.change_region_set_id})에 없는 구역의 판정이 들어왔다: "
                f"{unknown} — 판정과 리포트의 짝이 어긋난 초안은 만들지 않는다"
            )
        report_digest = _report_digest(report)
        verification_digest = _verification_digest(report, suitability_by_region)
        watermark = f"survey-briefing:{report_digest}:{verification_digest}"
        latest = self._briefings.latest(site_id, organization_id=organization_id)
        if latest is not None and latest.source_watermark == watermark:
            return False

        verified = [
            region
            for region in report.regions
            if suitability_by_region.get(region.region_id) == _VERIFIED_STATE
        ]
        verified_ids = {region.region_id for region in verified}
        unverified = [region for region in report.regions if region.region_id not in verified_ids]
        digest_short = report_digest.removeprefix("sha256:")[:12]
        uncertainty = self._uncertainty_text(report)

        if not verified:
            self._briefings.record(
                organization_id=organization_id,
                site_id=site_id,
                status=SiteBriefingStatus.BLOCKED,
                what_changed=self._blocked_what_changed(report, survey_id, unverified),
                why_it_matters=(
                    "미검증 구역의 수치는 초안에 싣지 않는다(라벨로 대신하지 않음). "
                    "이 초안은 정량·정산·현장·고객 수락의 근거가 아니다."
                ),
                decision_prompt="구역 검증을 완료한 뒤 초안을 다시 만드세요.",
                citations=[],
                uncertainty=uncertainty,
                source_watermark=watermark,
                missing_data=self._missing_entries(report, suitability_by_region, unverified),
                actor=_ACTOR,
                now=self._clock(),
            )
            return True

        citations = [
            CopilotCitation(
                citation_id=f"survey-region:{region.region_id}:{report_digest}",
                object_type="survey-change-region",
                object_id=region.region_id,
                label=f"전수측량 {survey_id} 후보 {region.region_id} 체적",
                # 이 리포트를 서빙하는 전용 resolver가 없으므로, 해석 가능한
                # fetch URL을 지어내지 않고 리포트가 속한 현장 스코프를 싣는다
                # (정확한 바이트는 citationId의 digest가 가리킨다).
                source_path=f"/v1/sites/{site_id}",
                uncertainty_summary=region.volume.uncertainty_note[:500],
            )
            for region in verified
        ]
        self._briefings.record(
            organization_id=organization_id,
            site_id=site_id,
            status=SiteBriefingStatus.READY,
            what_changed=self._ready_what_changed(
                report, survey_id, verified, unverified, digest_short
            ),
            why_it_matters=(
                f"검증 완료(EVALUATED) {len(verified)}개 구역의 수치만 봉인 리포트에서 "
                "그대로 복사했다. "
                + (
                    f"미검증 {len(unverified)}개 구역의 수치는 초안에 싣지 않는다."
                    if unverified
                    else "모든 후보 구역이 검증됐다."
                )
                + " 이 초안은 정량·정산·현장·고객 수락의 근거가 아니다."
            ),
            decision_prompt="검증 완료 구역의 수치와 근거를 검토하세요.",
            citations=citations,
            uncertainty=uncertainty,
            source_watermark=watermark,
            missing_data=self._missing_entries(report, suitability_by_region, unverified),
            actor=_ACTOR,
            now=self._clock(),
        )
        return True

    def _survey_id_of(self, report: ChangeRegionSetReport) -> str:
        anchor = report.design_conformance_id
        if not anchor.startswith(_SURVEY_ANCHOR_PREFIX):
            raise SurveyBriefingError(
                f"designConformanceId({anchor!r})가 'survey:' 로 시작하지 않는다 — "
                "설계 리포트는 조사 브리핑 경로로 만들지 않는다"
            )
        return anchor[len(_SURVEY_ANCHOR_PREFIX) :]

    def _missing_entries(
        self,
        report: ChangeRegionSetReport,
        suitability_by_region: Mapping[str, AnalysisSuitabilityStateV1],
        unverified: list[Any],
    ) -> list[str]:
        if not report.regions:
            return ["후보 구역 없음 — 비교 대상 수치가 없다"]
        entries = []
        for region in unverified:
            state = suitability_by_region.get(region.region_id)
            if state is None:
                entries.append(f"{region.region_id}: 검증 판정 없음 — 수치 제외")
            else:
                entries.append(f"{region.region_id}: {state.value} — 수치 제외")
        return entries

    def _uncertainty_text(self, report: ChangeRegionSetReport) -> str:
        notes: list[str] = []
        for region in report.regions:
            note = region.volume.uncertainty_note
            if note not in notes:
                notes.append(note)
        if not notes:
            return "후보 구역이 없어 오차한계 대상 수치가 없다."
        return " / ".join(notes)[:1000]

    def _blocked_what_changed(
        self,
        report: ChangeRegionSetReport,
        survey_id: str,
        unverified: list[Any],
    ) -> str:
        if not report.regions:
            return (
                f"전수측량 {survey_id}: 문턱 {report.threshold_m} m에서 후보 구역 없음 "
                f"(정책 {report.extraction_policy.policy_version})."
            )
        ids = ", ".join(region.region_id for region in unverified)
        return (
            f"전수측량 {survey_id}: 후보 {len(unverified)}개({ids}) 모두 미검증이라 "
            "수치를 싣지 않는다."
        )

    def _ready_what_changed(
        self,
        report: ChangeRegionSetReport,
        survey_id: str,
        verified: list[Any],
        unverified: list[Any],
        digest_short: str,
    ) -> str:
        header = (
            f"전수측량 {survey_id} — 후보 {len(report.regions)}개 중 검증 {len(verified)}개 "
            f"수치 (문턱 {report.threshold_m} m, 정책 "
            f"{report.extraction_policy.policy_version}, 근거 sha256:{digest_short})."
        )
        lines = [header]
        for region in verified:
            volume = region.volume
            lines.append(
                f"후보 {region.region_id}: 절토 {_m3(volume.cut_m3)}, "
                f"성토 {_m3(volume.fill_m3)}, 순변화 {_m3(volume.net_m3)}, "
                f"면적 {volume.area_m2:,.1f} m², "
                f"측정불가율 {_pct(region.unmeasurable_ratio)}, "
                f"{_hull_ratio_text(region)}."
            )
        if unverified:
            ids = ", ".join(region.region_id for region in unverified)
            lines.append(f"미검증 {len(unverified)}개({ids})는 수치 없이 제외.")
        return "\n".join(lines)


__all__ = ["SurveyBriefingError", "SurveyResultBriefingProjector"]
