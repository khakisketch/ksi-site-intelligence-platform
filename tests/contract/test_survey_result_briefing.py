"""조사 브리핑 초안 계약 — 구역별 인용 결속·미검증 수치 차단·digest·워터마크 (Task 3).

초점 셋:

1. **인용 없는 READY 거부** — ``SiteBriefing`` 계약이 READY+빈 인용을 거부한다.
   projector는 검증 구역이 없을 때 READY가 아니라 BLOCKED를 기록하므로 이 길로
   갈 수 없다.
2. **미검증 구역 수치 제외** — ``PROVISIONAL_ACCURACY_UNVERIFIED`` 등 미검증
   구역의 수치는 초안 어디에도 없다(본문·사유·불확도·인용 요약 전부). 라벨만
   붙이는 것으로 대신하지 않는다.
3. **digest 결속** — 구역 인용 id가 봉인 리포트의 canonical digest를 싣는다.
   같은 바이트는 같은 digest, 한 글자라도 바뀌면 다른 초안이다.
4. **워터마크 중복제거** — 같은 리포트+같은 판정의 재투영은 기록하지 않는다.
   판정이 바뀌면 다른 워터마크라 다시 기록한다.

리포트는 합성 diff를 ``compute_survey_regions`` 으로 계산한 봉인 출력만 쓴다
(숫자를 손으로 만들지 않는다). 검증 판정은 호출자가 주는 입력이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.region_extraction import compute_survey_regions
from ksi_core.domains.external.workflow.survey_result_briefings import (
    SurveyBriefingError,
    SurveyResultBriefingProjector,
)
from ksi_event_contracts.change_region_report import ChangeRegionSetReport
from ksi_event_contracts.copilot import SiteBriefing, SiteBriefingStatus
from ksi_event_contracts.external_analysis_api import AnalysisSuitabilityStateV1
from ksi_event_contracts.survey_extraction_policy import SurveyExtractionPolicy
from pydantic import ValidationError
from rasterio import Affine

_NOW = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
_TRANSFORM = Affine(1.0, 0.0, 190000.0, 0.0, -1.0, 450000.0)
EVALUATED = AnalysisSuitabilityStateV1.EVALUATED
PROVISIONAL = AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED


class _FakeBriefings:
    """duck-type 저장소 — ``record`` 인자를 그대로 보관하고 계약으로 검증한다."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._watermark: str | None = None

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)
        self._watermark = kwargs["source_watermark"]

    def latest(self, site_id: str, organization_id: str | None = None) -> Any:
        if self._watermark is None:
            return None
        return SimpleNamespace(source_watermark=self._watermark)


def _policy() -> SurveyExtractionPolicy:
    return SurveyExtractionPolicy(
        policy_version="test-survey-policy",
        threshold_m=0.05,
        min_region_area_m2=1.0,
        connectivity=8,
    )


def _two_blob_diff() -> DiffResult:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.ones((10, 10), dtype=bool)
    diff_m[0:2, 0:2] = 0.2  # 4 픽셀 fill → 0.8 m³
    diff_m[5:8, 5:9] = -0.3  # 12 픽셀 cut → 3.6 m³
    return DiffResult(
        diff_m=diff_m,
        valid=valid,
        transform=_TRANSFORM,
        crs="EPSG:5186",
        cell_area_m2=1.0,
    )


def _survey(survey_id: str = "srv-1") -> ChangeRegionSetReport:
    return compute_survey_regions(
        _two_blob_diff(),
        policy=_policy(),
        change_region_set_id="srv-1-sex1",
        survey_id=survey_id,
        diff_raster_id="srv-1-diff",
        computed_at=_NOW,
    )


def _fill_region(report: ChangeRegionSetReport) -> Any:
    return next(r for r in report.regions if r.volume.fill_m3 > 0)


def _cut_region(report: ChangeRegionSetReport) -> Any:
    return next(r for r in report.regions if r.volume.cut_m3 > 0)


def _projector(store: _FakeBriefings) -> SurveyResultBriefingProjector:
    return SurveyResultBriefingProjector(briefings=store, clock=lambda: _NOW)


def _briefing_kwargs(store: _FakeBriefings, index: int = 0) -> dict[str, Any]:
    return store.records[index]


def _as_briefing(store: _FakeBriefings, index: int = 0) -> SiteBriefing:
    kwargs = _briefing_kwargs(store, index)
    return SiteBriefing(
        briefing_id=f"b-{index}",
        organization_id=kwargs["organization_id"],
        site_id=kwargs["site_id"],
        generated_at=_NOW.isoformat(),
        **{
            k: v
            for k, v in kwargs.items()
            if k not in ("organization_id", "site_id", "actor", "now")
        },
    )


def _every_recorded_string(kwargs: dict[str, Any]) -> str:
    parts = [
        kwargs["what_changed"],
        kwargs["why_it_matters"],
        kwargs["decision_prompt"],
        kwargs["uncertainty"],
        *[m for m in kwargs["missing_data"]],
    ]
    for citation in kwargs["citations"]:
        parts.append(citation.label)
        parts.append(citation.citation_id)
        parts.append(citation.object_id)
        if citation.uncertainty_summary:
            parts.append(citation.uncertainty_summary)
    return "\n".join(parts)


# ── 1. 인용 없는 READY 거부 ────────────────────────────────────────────────


def test_ready_without_citations_is_rejected_by_the_contract() -> None:
    with pytest.raises(ValidationError, match="citation"):
        SiteBriefing(
            briefing_id="b-0",
            organization_id="org-1",
            site_id="site-1",
            status=SiteBriefingStatus.READY,
            what_changed="x",
            why_it_matters="y",
            decision_prompt="z",
            citations=[],
            uncertainty="u",
            source_watermark="w",
            missing_data=[],
            generated_at=_NOW.isoformat(),
        )


# ── 2. 미검증 구역 수치 제외 ───────────────────────────────────────────────


def test_verified_numbers_are_copied_and_unverified_numbers_are_excluded() -> None:
    store = _FakeBriefings()
    report = _survey()
    assert (
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={
                _fill_region(report).region_id: EVALUATED,
                _cut_region(report).region_id: PROVISIONAL,
            },
        )
        is True
    )

    assert len(store.records) == 1
    kwargs = _briefing_kwargs(store)
    assert kwargs["status"] is SiteBriefingStatus.READY
    briefing = _as_briefing(store)  # 계약 유효 — READY인데 인용이 있다
    assert len(briefing.citations) == 1

    text = _every_recorded_string(kwargs)
    assert "0.8 m³" in text  # 검증 fill 수치는 그대로 복사됐다
    assert "3.6 m³" not in text  # 미검증 cut 수치는 어디에도 없다
    cut = _cut_region(report)
    assert cut.region_id in text  # id는 투명하게 밝힌다(수치 없이)
    assert any(cut.region_id in entry for entry in kwargs["missing_data"])


def test_regions_without_a_verdict_are_excluded_fail_closed() -> None:
    store = _FakeBriefings()
    report = _survey()
    assert (
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={_fill_region(report).region_id: EVALUATED},
        )
        is True
    )

    kwargs = _briefing_kwargs(store)
    assert kwargs["status"] is SiteBriefingStatus.READY
    assert "3.6 m³" not in _every_recorded_string(kwargs)
    assert any("판정 없음" in entry for entry in kwargs["missing_data"])


def test_all_unverified_records_blocked_without_any_numbers() -> None:
    store = _FakeBriefings()
    report = _survey()
    assert (
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={r.region_id: PROVISIONAL for r in report.regions},
        )
        is True
    )

    kwargs = _briefing_kwargs(store)
    assert kwargs["status"] is SiteBriefingStatus.BLOCKED
    assert kwargs["citations"] == []
    text = _every_recorded_string(kwargs)
    assert "0.8 m³" not in text
    assert "3.6 m³" not in text
    _as_briefing(store)  # BLOCKED+빈 인용은 계약 유효


def test_empty_survey_is_blocked_not_ready() -> None:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.ones((10, 10), dtype=bool)
    empty = compute_survey_regions(
        DiffResult(
            diff_m=diff_m,
            valid=valid,
            transform=_TRANSFORM,
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        policy=_policy(),
        change_region_set_id="srv-1-sex1",
        survey_id="srv-1",
        diff_raster_id="srv-1-diff",
        computed_at=_NOW,
    )
    assert empty.regions == []

    store = _FakeBriefings()
    assert (
        _projector(store).project(
            empty, organization_id="org-1", site_id="site-1", suitability_by_region={}
        )
        is True
    )
    kwargs = _briefing_kwargs(store)
    assert kwargs["status"] is SiteBriefingStatus.BLOCKED
    _as_briefing(store)


# ── 3. digest 결속 ─────────────────────────────────────────────────────────


def test_citations_bind_the_sealed_report_digest() -> None:
    store = _FakeBriefings()
    report = _survey()
    region = _fill_region(report)
    _projector(store).project(
        report,
        organization_id="org-1",
        site_id="site-1",
        suitability_by_region={region.region_id: EVALUATED},
    )

    citations = _briefing_kwargs(store)["citations"]
    assert len(citations) == 1
    assert citations[0].object_id == region.region_id
    assert "sha256:" in citations[0].citation_id

    # 같은 바이트의 재계산은 같은 digest — 결속이 장식이 아님을 보인다.
    rerun_store = _FakeBriefings()
    rerun = _survey()
    rerun_region = _fill_region(rerun)
    _projector(rerun_store).project(
        rerun,
        organization_id="org-1",
        site_id="site-1",
        suitability_by_region={rerun_region.region_id: EVALUATED},
    )
    assert _briefing_kwargs(rerun_store)["citations"][0].citation_id == citations[0].citation_id


def test_changed_bytes_produce_a_different_digest() -> None:
    first_store, second_store = _FakeBriefings(), _FakeBriefings()
    first, second = _survey(survey_id="srv-1"), _survey(survey_id="srv-2")
    for store, report in ((first_store, first), (second_store, second)):
        region = _fill_region(report)
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={region.region_id: EVALUATED},
        )
    first_citation = _briefing_kwargs(first_store)["citations"][0].citation_id
    second_citation = _briefing_kwargs(second_store)["citations"][0].citation_id
    assert first_citation != second_citation
    assert (
        _briefing_kwargs(first_store)["source_watermark"]
        != (_briefing_kwargs(second_store)["source_watermark"])
    )


# ── 4. 워터마크 중복제거 ───────────────────────────────────────────────────


def test_same_report_and_verdict_is_not_recorded_twice() -> None:
    store = _FakeBriefings()
    report = _survey()
    verdict = {r.region_id: EVALUATED for r in report.regions}
    projector = _projector(store)
    assert (
        projector.project(
            report, organization_id="org-1", site_id="site-1", suitability_by_region=verdict
        )
        is True
    )
    assert (
        projector.project(
            report, organization_id="org-1", site_id="site-1", suitability_by_region=verdict
        )
        is False
    )
    assert len(store.records) == 1


def test_changed_verdict_records_again_with_a_new_watermark() -> None:
    store = _FakeBriefings()
    report = _survey()
    projector = _projector(store)
    fill_id = _fill_region(report).region_id
    cut_id = _cut_region(report).region_id
    assert (
        projector.project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={fill_id: EVALUATED, cut_id: PROVISIONAL},
        )
        is True
    )
    assert (
        projector.project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={fill_id: EVALUATED, cut_id: EVALUATED},
        )
        is True
    )
    assert len(store.records) == 2
    assert (
        _briefing_kwargs(store, 0)["source_watermark"]
        != (_briefing_kwargs(store, 1)["source_watermark"])
    )
    assert len(_briefing_kwargs(store, 1)["citations"]) == 2


# ── fail-closed 입력 거부 ──────────────────────────────────────────────────


def test_non_survey_anchor_is_rejected() -> None:
    store = _FakeBriefings()
    report = _survey().model_copy(update={"design_conformance_id": "dcr-1"})
    with pytest.raises(SurveyBriefingError, match="survey:"):
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={},
        )
    assert store.records == []


def test_verdict_for_an_unknown_region_is_rejected() -> None:
    store = _FakeBriefings()
    report = _survey()
    with pytest.raises(SurveyBriefingError, match="없는 구역"):
        _projector(store).project(
            report,
            organization_id="org-1",
            site_id="site-1",
            suitability_by_region={"no-such-region": EVALUATED},
        )
    assert store.records == []


# ── 표기 통일 (Task 2 인계: % · 배 · m³ · m²) ───────────────────────────────


def test_report_notation_unifies_percent_scale_and_units() -> None:
    store = _FakeBriefings()
    report = _survey()
    _projector(store).project(
        report,
        organization_id="org-1",
        site_id="site-1",
        suitability_by_region={r.region_id: EVALUATED for r in report.regions},
    )
    text = _every_recorded_string(_briefing_kwargs(store))
    assert "%" in text  # 측정불가율에 % 기호
    assert "배" in text  # 껍질 과대포함 비율에 배율 단위
    assert "m³" in text and "m²" in text
    assert "㎥" not in text and "㎡" not in text
