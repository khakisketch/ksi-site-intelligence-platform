"""Deterministic site briefings for external relative-volume results (AX-2).

The projector copies sealed report values into the existing ``SiteBriefing``
record after a report, review or approval is durably committed. The only
arithmetic is the delta between two retained net values. It never calls a
model, never blocks the source mutation, and never re-records the same
watermark (ADR-KSI-026 D6/D8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ksi_event_contracts.copilot import CopilotCitation, SiteBriefingStatus

_LOGGER = logging.getLogger(__name__)
_ACTOR = "system:external-result-briefing"
_HISTORY_WINDOW = 50


def _m3(value: float) -> str:
    return f"{value:,.1f} m³"


class ExternalResultBriefingProjector:
    """Writes one READY briefing per (report, stage) into the site briefing store."""

    def __init__(
        self,
        *,
        briefings: Any,
        projector: Any,
        work_areas: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._briefings = briefings
        self._projector = projector
        self._work_areas = work_areas
        self._clock = clock or (lambda: datetime.now(UTC))

    def bind(self, *, volumes: Any, reviews: Any, service: Any) -> None:
        volumes.bind_report_listener(self.on_report)
        reviews.bind_review_listener(self.on_review)
        service.bind_approval_listener(self.on_approval)

    def on_report(self, record: Any) -> None:
        subject = record.request.current.subject
        report = record.report
        if report is None:
            return
        self._record(subject.organization_id, subject.site_id, report.report_id, stage="REPORTED")

    def on_review(self, receipt: Any) -> None:
        self._record(receipt.organization_id, receipt.site_id, receipt.report_ref, stage="REVIEWED")

    def on_approval(self, receipt: Any) -> None:
        proposal = self._projector.workflow.proposals.get_scoped(
            receipt.proposal_id, organization_id=receipt.organization_id
        )
        if proposal is None:
            return
        self._record(
            receipt.organization_id,
            receipt.site_id,
            proposal.report_ref,
            stage="APPROVED",
            successor=receipt.successor_work_order_id,
        )

    def _record(
        self,
        organization_id: str,
        site_id: str,
        report_ref: str,
        *,
        stage: str,
        successor: str | None = None,
    ) -> None:
        try:
            view = self._projector.report_for_site(
                site_id, report_ref, organization_id=organization_id
            )
            result = view.result
            if result is None or result.metrics is None:
                return
            watermark = f"external-report:{result.report_digest}:{stage}"
            latest = self._briefings.latest(site_id, organization_id=organization_id)
            if latest is not None and latest.source_watermark == watermark:
                return
            area = self._work_areas.get(result.work_area_id)
            zone = area.name if area is not None else result.work_area_id
            metrics = result.metrics
            what_changed = (
                f"{zone} 구역의 상대 물량 결과: 절토 {_m3(metrics.cut_m3)}, "
                f"성토 {_m3(metrics.fill_m3)}, 순변화 {_m3(metrics.net_m3)} "
                f"(기준 {result.baseline_captured_from:%Y-%m-%d} → 현재 "
                f"{result.current_captured_from:%Y-%m-%d}, "
                f"유효 면적 {metrics.common_valid_fraction * 100:.0f}%)."
            )
            previous = self._previous_net(site_id, organization_id, result)
            if previous is None:
                why_it_matters = "이 구역의 첫 결과입니다. 이후 결과와 비교할 기준이 됩니다."
            else:
                delta = metrics.net_m3 - previous
                direction = "늘었습니다" if delta >= 0 else "줄었습니다"
                why_it_matters = (
                    f"직전 결과({_m3(previous)})보다 순변화가 {_m3(abs(delta))} {direction}."
                )
            if stage == "REPORTED":
                decision_prompt = "결과와 근거를 검토하세요."
            elif stage == "REVIEWED":
                decision_prompt = "재관측이 필요하면 제안을 만들고 승인하세요."
            else:
                decision_prompt = f"후속 작업 {successor}에 다음 산출물을 등록하세요."
            uncertainty = (
                metrics.uncertainty_note
                if metrics.uncertainty_m3 is None
                else f"불확도 ±{_m3(metrics.uncertainty_m3)} · {metrics.uncertainty_note}"
            )
            citations = [
                CopilotCitation(
                    citation_id=f"report:{report_ref}",
                    object_type="external-relative-volume-report",
                    object_id=report_ref,
                    label=f"{zone} 상대 물량 보고서",
                    source_path=f"/v1/external-relative-volume-reports/{report_ref}",
                    captured_from=result.baseline_captured_from.isoformat(),
                    captured_to=result.current_captured_to.isoformat(),
                    uncertainty_summary=uncertainty[:500],
                ),
                CopilotCitation(
                    citation_id=f"site-observation:{report_ref}",
                    object_type="site-observation",
                    object_id=report_ref,
                    label="현장 관측 결과 보기",
                    source_path=f"/v1/sites/{site_id}/observations/{report_ref}",
                ),
            ]
            self._briefings.record(
                organization_id=organization_id,
                site_id=site_id,
                status=SiteBriefingStatus.READY,
                what_changed=what_changed,
                why_it_matters=why_it_matters,
                decision_prompt=decision_prompt,
                citations=citations,
                uncertainty=uncertainty[:1000],
                source_watermark=watermark,
                missing_data=[],
                actor=_ACTOR,
                now=self._clock(),
            )
        except Exception:
            _LOGGER.exception(
                "external result briefing failed",
                extra={"site_id": site_id, "report_ref": report_ref, "stage": stage},
            )

    def _previous_net(self, site_id: str, organization_id: str, current: Any) -> float | None:
        history = self._projector.history_for_site(
            site_id, organization_id=organization_id, after=None, limit=_HISTORY_WINDOW
        )
        candidates = [
            item.result
            for item in history.items
            if item.result is not None
            and item.result.metrics is not None
            and item.result.work_area_id == current.work_area_id
            and item.result.report_ref != current.report_ref
            and item.result.reported_at < current.reported_at
        ]
        if not candidates:
            return None
        previous = max(candidates, key=lambda item: item.reported_at)
        assert previous.metrics is not None
        return float(previous.metrics.net_m3)


__all__ = ["ExternalResultBriefingProjector"]
