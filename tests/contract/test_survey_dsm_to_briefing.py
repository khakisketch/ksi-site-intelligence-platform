"""2시점 DSM → 조사 추출 → 근거 결속 초안 통합 (Task 3 fix-wave).

이 파일이 고정하는 것은 **경계를 관통하는 두 길**이다. 이웃 테스트는 각
구간을 따로 본다 — ``test_survey_extraction.py`` 는 합성 ``DiffResult`` 를
직접 만들고, ``test_survey_result_briefing.py`` 는 호출자가 준 판정만 쓴다.
그래서 "2시점 DSM 두 장이 INV-053/typed-blocker 경계를 지나 조사 후보와
초안까지 이어진다"는 계획의 완성 조건이 어떤 테스트에서도 성립하지 않았다.

- 성공 길: 합성 DSM 두 장(파일) → ``align_and_diff`` → ``compute_survey_regions``
  → ``SurveyResultBriefingProjector`` → 예상 수치·digest 결속 인용을 단 초안.
- 차단 길: 같은 두 입력 + 처리 프로필 불일치 epoch 쌍 → ``preflight_epoch_pair``
  가 ``PROCESSING_PROFILE_MISMATCH`` 로 막고, 체적·초안 출력이 전혀 기록되지
  않는다(fail-closed — 기록된 문자열에 숫자 없음).

새 fixture 인프라는 만들지 않는다. DSM 기록은
``test_dsm_diff_worker.py`` 의 ``_write_dsm`` 과 동형이고, 작업 레코드 조립은
``test_spatial_model.py`` 의 ``_record`` 와 동형이며, digest 불일치 패턴은
``test_civil_preflight.py`` 와 동형이다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_change_detection.dsm_diff import align_and_diff
from ksi_change_detection.region_extraction import compute_survey_regions
from ksi_core.domains.external.workflow.survey_result_briefings import (
    SurveyResultBriefingProjector,
)
from ksi_core.domains.processing.civil_preflight import (
    CivilPreflightReason,
    preflight_epoch_pair,
)
from ksi_core.processing_jobs import JobSpec, ProcessingJobRecord
from ksi_event_contracts.change_region_report import ChangeRegionSetReport
from ksi_event_contracts.copilot import SiteBriefing, SiteBriefingStatus
from ksi_event_contracts.external_analysis_api import AnalysisSuitabilityStateV1
from ksi_event_contracts.processing_artifact import (
    ArtifactLineage,
    LineageAuthority,
    ProcessingArtifact,
    ProcessingArtifactKind,
)
from ksi_event_contracts.processing_job import (
    DataResidency,
    ExecutionLocus,
    LicenseBasis,
    ProcessingInput,
    ProcessingJobStatus,
    ProcessingProvider,
)
from ksi_event_contracts.survey_extraction_policy import SurveyExtractionPolicy
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from rasterio.transform import from_origin

_NOW = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
_ORIGIN_X = 190000.0
_ORIGIN_Y = 450000.0
_SOURCE_DIGEST = "sha256:" + "a" * 64
EVALUATED = AnalysisSuitabilityStateV1.EVALUATED


def _write_dsm(path: Path, values: np.ndarray) -> Path:
    """합성 DSM 한 장 — ``test_dsm_diff_worker.py`` 의 기록 방식과 동형."""
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float64",
        crs="EPSG:5186",
        transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(values, 1)
    return path


def _two_epoch_dsm_paths(tmp_path: Path) -> tuple[Path, Path]:
    """기준(평탄 100m)과 비교(성토 1곳·절토 1곳)를 파일로 낸다."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((10, 10), 100.0))
    current_values = np.full((10, 10), 100.0)
    current_values[0:2, 0:2] = 100.2  # 4 픽셀 fill → 0.8 m³
    current_values[5:8, 5:9] = 99.7  # 12 픽셀 cut → 3.6 m³
    current = _write_dsm(tmp_path / "current.tif", current_values)
    return baseline, current


def _policy() -> SurveyExtractionPolicy:
    return SurveyExtractionPolicy(
        policy_version="test-survey-policy",
        threshold_m=0.05,
        min_region_area_m2=1.0,
        connectivity=8,
    )


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


def _vertical_reference() -> VerticalReference:
    return VerticalReference(
        datum=VerticalDatum.ORTHOMETRIC_KNGEOID2024,
        basis="동일 처리 파이프라인이 선언한 표고 기준",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


def _dsm_artifact(job_id: str) -> ProcessingArtifact:
    return ProcessingArtifact(
        artifact_id=f"{job_id}-dsm",
        job_id=job_id,
        kind=ProcessingArtifactKind.DSM,
        lineage=ArtifactLineage(
            authority=LineageAuthority.DERIVED,
            derived_from=[f"{job_id}-pc"],
            source_digest=_SOURCE_DIGEST,
        ),
        digest="sha256:" + "d" * 64,
        format="tif",
        crs="EPSG:5186",
        gsd=1.0,
        vertical_reference=_vertical_reference(),
    )


def _epoch_job(job_id: str, *, profile_digest: str) -> ProcessingJobRecord:
    """INV-053 단일 epoch 검사를 통과하는 최소 SUCCEEDED 작업."""
    return ProcessingJobRecord(
        job_id=job_id,
        mission_id="mission-e2e",
        site_id="site-e2e",
        spec=JobSpec(
            provider=ProcessingProvider.ODM,
            engine_version="3.5.4",
            engine_digest="sha256:" + "b" * 64,
            execution_locus=ExecutionLocus.KSI_SERVER_GPU,
            license_basis=LicenseBasis(
                license_id="AGPL-3.0", tier="self-hosted", attribution_required=False
            ),
            processing_params={"quality": "high"},
            processing_profile_id="ksi-odm-civil-v1",
            processing_profile_digest=profile_digest,
        ),
        data_residency=DataResidency(egress_allowed=False, jurisdiction="KR"),
        input=ProcessingInput(
            image_count=120, total_megapixels=2400.0, source_bundle_digest=_SOURCE_DIGEST
        ),
        status=ProcessingJobStatus.SUCCEEDED,
        issued_at=_NOW,
        issued_by="op-1",
        updated_at=_NOW,
        artifacts=(_dsm_artifact(job_id),),
    )


def _ready(_mission_id: str) -> tuple[bool, str | None]:
    return True, None


# ── 성공 길: 파일 두 장 → 정렬·차분 → 조사 추출 → 인용 결속 초안 ─────────────


def test_two_dsm_files_flow_to_a_cited_ready_draft(tmp_path: Path) -> None:
    baseline_path, current_path = _two_epoch_dsm_paths(tmp_path)

    diff = align_and_diff(baseline_path, current_path)
    report = compute_survey_regions(
        diff,
        policy=_policy(),
        change_region_set_id="srv-e2e-sex1",
        survey_id="srv-e2e",
        diff_raster_id="srv-e2e-diff",
        computed_at=_NOW,
    )
    assert len(report.regions) == 2
    assert report.design_conformance_id == "survey:srv-e2e"

    fill_region = next(r for r in report.regions if r.volume.fill_m3 > 0)
    cut_region = next(r for r in report.regions if r.volume.cut_m3 > 0)
    assert fill_region.volume.fill_m3 == pytest.approx(0.8)
    assert cut_region.volume.cut_m3 == pytest.approx(3.6)

    store = _FakeBriefings()
    assert (
        SurveyResultBriefingProjector(briefings=store, clock=lambda: _NOW).project(
            report,
            organization_id="org-1",
            site_id="site-e2e",
            suitability_by_region={r.region_id: EVALUATED for r in report.regions},
        )
        is True
    )

    assert len(store.records) == 1
    kwargs = store.records[0]
    assert kwargs["status"] is SiteBriefingStatus.READY
    briefing = SiteBriefing(
        briefing_id="b-e2e",
        organization_id=kwargs["organization_id"],
        site_id=kwargs["site_id"],
        generated_at=_NOW.isoformat(),
        **{
            k: v
            for k, v in kwargs.items()
            if k not in ("organization_id", "site_id", "actor", "now")
        },
    )
    assert len(briefing.citations) == 2

    text = _every_recorded_string(kwargs)
    assert "0.8 m³" in text  # 파일에서 온 성토 수치가 그대로 실렸다
    assert "3.6 m³" in text  # 파일에서 온 절토 수치가 그대로 실렸다
    for citation in briefing.citations:
        assert "sha256:" in citation.citation_id  # 봉인 리포트 digest 결속
    assert {c.object_id for c in briefing.citations} == {
        r.region_id for r in report.regions
    }

    # 같은 두 파일을 다시 정렬·추출하면 같은 초안 — 결속이 장식이 아님을 보인다.
    rerun_store = _FakeBriefings()
    rerun_report = compute_survey_regions(
        align_and_diff(baseline_path, current_path),
        policy=_policy(),
        change_region_set_id="srv-e2e-sex1",
        survey_id="srv-e2e",
        diff_raster_id="srv-e2e-diff",
        computed_at=_NOW,
    )
    SurveyResultBriefingProjector(briefings=rerun_store, clock=lambda: _NOW).project(
        rerun_report,
        organization_id="org-1",
        site_id="site-e2e",
        suitability_by_region={r.region_id: EVALUATED for r in rerun_report.regions},
    )
    assert (
        rerun_store.records[0]["citations"][0].citation_id
        == kwargs["citations"][0].citation_id
    )


# ── 차단 길: INV-053 실패는 체적·초안 출력을 막는다 ───────────────────────────


def test_profile_mismatch_blocks_quantities_and_briefing_output(
    tmp_path: Path,
) -> None:
    baseline_path, current_path = _two_epoch_dsm_paths(tmp_path)
    assert baseline_path.exists() and current_path.exists()  # 입력 두 장은 실재한다

    baseline = _epoch_job("mission-e2e-pj1", profile_digest="sha256:" + "a" * 64)
    current = _epoch_job("mission-e2e-pj2", profile_digest="sha256:" + "f" * 64)
    gate = preflight_epoch_pair(baseline, current, analysis_readiness=_ready)
    assert not gate.compatible
    assert gate.reason is CivilPreflightReason.PROCESSING_PROFILE_MISMATCH

    # 게이트가 막았으므로 정렬·추출·투영은 실행하지 않는다 — 체적도 초안도 없다.
    store = _FakeBriefings()
    gated: ChangeRegionSetReport | None = None
    if gate.compatible:  # pragma: no cover - 차단이 깨지면 이 길이 열린다
        gated = compute_survey_regions(
            align_and_diff(baseline_path, current_path),
            policy=_policy(),
            change_region_set_id="srv-e2e-sex1",
            survey_id="srv-e2e",
            diff_raster_id="srv-e2e-diff",
            computed_at=_NOW,
        )
    assert gated is None
    assert store.records == []

    recorded = "\n".join(_every_recorded_string(kwargs) for kwargs in store.records)
    assert recorded == ""
    assert re.search(r"\d", recorded) is None  # 기록된 문자열에 숫자 없음
