"""단면 작업의 실제 권한 포트 — 각 사실을 그 사실의 소유자에게 묻고, 매 전이마다 다시 묻는다.

소유자(자료·grant·저장 선·HEIGHT 판정)는 좁은 가짜로 바꾼다. 실제 소유자와의 통합 시험은
라우트 단계에서 따로 한다. 이 시험은 어댑터가 무엇을 묻고 무엇을 거부하는지의 증거이지
측량 정확도의 증거가 아니다.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.surface_profile_authority import (
    SurfaceProfileCoreAuthority,
    read_window_for,
)
from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileDomainError,
    SurfaceProfileJobStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalUseDecisionV1,
)
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileActivationV1,
    SurfaceProfileLeaseRequestV1,
)
from ksi_geo_spatial.surface_profile import plan_surface_profile
from spatial_data_fixture import DIGEST, NOW, make_grant, make_measurements, make_policy
from surface_profile_job_fixture import (
    AREA,
    ORIGIN_X,
    ORIGIN_Y,
    SITE,
    feature_revision,
    genuine_answer,
    issue_request,
    later,
    line,
    measured_source,
    profile_policy,
    profile_runtime,
    requester,
    sdp,
    viewer,
    worker,
    write_raster,
)

DATA_POLICY = make_policy()


class Sources:
    def __init__(self) -> None:
        self.source = measured_source()
        self.scope_error: SpatialDataDomainError | None = None
        self.resolve_error: SpatialDataDomainError | None = None
        self.current_error: SpatialDataDomainError | None = None
        self.current: Any = None  # a different source, to simulate drift

    def require_history_scope(self, site_id: str, work_area_id: str, principal: Any) -> Any:
        if self.scope_error:
            raise self.scope_error

    def resolve(self, **kwargs: Any) -> Any:
        if self.resolve_error:
            raise self.resolve_error
        return self.source

    def require_current(self, *, source: Any, principal: Any, now: Any) -> Any:
        if self.current_error:
            raise self.current_error
        return self.current or source


class Grants:
    def __init__(self, grant: Any) -> None:
        self.grant = grant
        self.selected: list[dict[str, Any]] = []
        self.required: list[dict[str, Any]] = []
        self.error: SpatialDataDomainError | None = None
        self.other: Any = None  # a different grant for READ → ambiguous
        self.returned: Any = None

    def select_current(self, **kwargs: Any) -> Any:
        self.selected.append(kwargs)
        if self.error:
            raise self.error
        if self.other is not None and kwargs["operation"] == "READ":
            return self.other
        return self.grant

    def require_current(self, **kwargs: Any) -> Any:
        self.required.append(kwargs)
        if self.error:
            raise self.error
        return self.returned or self.grant


class Features:
    def __init__(self) -> None:
        self.feature: Any = feature_revision()

    def get(self, **kwargs: Any) -> Any:
        return self.feature


class Decisions:
    def __init__(self, source: Any) -> None:
        subject = source.sealed_subject
        self.decision: Any = ExternalUseDecisionV1(
            decision_id="external-use-decision-" + "a" * 32,
            subject=subject,
            subject_digest=subject.canonical_digest(),
            use="HEIGHT",
            policy_digest=DIGEST,
            inspection_report_digest=DIGEST,
            evidence_record_digests=(),
            verdict=DecisionVerdict.ELIGIBLE,
            reasons=("HEIGHT_ELIGIBLE",),
            remediations=("CURRENT_DEPENDENCIES_RETAINED",),
            decided_at=NOW,
        ).sealed()
        self.blocker: str | None = None
        self.asked: list[Any] = []

    def get_scoped(self, decision_id: str, *, principal: Any, site_id: str) -> Any:
        return self.decision

    def height_blocker_now(self, decision: Any, *, now: Any) -> str | None:
        self.asked.append(decision.decision_id)
        return self.blocker


class Currentness:
    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.principal: Any = requester()

    def resolve_requester(self, *, principal_id: str, organization_id: str, now: Any) -> Any:
        if self.principal is None:
            return None
        return self.principal

    def is_current(self, **kwargs: Any) -> bool:
        return True


class Rig:
    def __init__(self) -> None:
        self.coordinator = ExternalAuthorityCurrentnessCoordinator()
        self.sources = Sources()
        self.grants = Grants(
            make_grant(
                allowed_bounds=(ORIGIN_X, ORIGIN_Y - 20, ORIGIN_X + 30, ORIGIN_Y),
                observed_crs_digest=DIGEST,
            )
        )
        self.features = Features()
        self.decisions = Decisions(self.sources.source)
        self.currentness = Currentness(self.coordinator)
        self.policy = profile_policy()
        self.runtime = profile_runtime()
        self.activation = SurfaceProfileActivationV1(
            activation_id="local-activation",
            organization_id="org-local",
            worker_principal_id="worker-local",
            worker_instance_id="instance-1",
            policy_digest=self.policy.policy_digest or "",
            runtime_digest=self.runtime.runtime_digest or "",
            trusted_endpoint_origins=("https://store.invalid",),
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(hours=1),
        ).sealed()
        self.authority = self.build()

    def build(self, **overrides: Any) -> SurfaceProfileCoreAuthority:
        parts: dict[str, Any] = dict(
            sources=self.sources,
            grants=self.grants,
            features=self.features,
            decisions=self.decisions,
            currentness=self.currentness,
            data_policy=DATA_POLICY,
            activation=self.activation,
            profile_policy_digest=self.policy.policy_digest,
            runtime_digest=self.runtime.runtime_digest,
            coordinator=self.coordinator,
        )
        parts.update(overrides)
        return SurfaceProfileCoreAuthority(**parts)

    def admit(self, **req: Any) -> Any:
        return self.authority.admit(
            site_id=SITE,
            work_area_id=AREA,
            request=issue_request(**req),
            principal=requester(),
            policy=self.policy,
            now=NOW,
        )


@pytest.fixture
def rig() -> Rig:
    return Rig()


def _reason(call: Any) -> str:
    with pytest.raises(SurfaceProfileDomainError) as excinfo:
        call()
    return excinfo.value.reason


# ── 발급: 무엇을 묻는가 ──────────────────────────────────────────────────────


def test_admission_asks_the_grant_about_exactly_the_cells_the_sampler_reads(rig: Rig) -> None:
    admission = rig.admit()
    plan = plan_surface_profile(
        feature_revision().line.vertices,
        vertices_crs="EPSG:5186",
        horizontal_crs="EPSG:5186",
        sample_spacing_m=1.0,
        policy=sdp(rig.policy),
    )
    window = read_window_for(rig.sources.source, plan)
    assert window is not None and admission.read_window == window

    asked = rig.grants.selected
    assert [call["operation"] for call in asked] == ["PREPARE", "READ"]
    for call in asked:
        assert call["requested_bounds"] == window.actual_bounds
        assert call["geometry"].pixel_window == window.pixel_window
        assert call["purpose"].value == "GENERAL_DATA_USE" and call["policy"] == DATA_POLICY
    assert admission.grant == rig.grants.grant
    assert admission.data_policy_digest == DATA_POLICY.policy_digest
    assert admission.height_decision_digest == rig.decisions.decision.decision_digest
    # 선의 바운딩 박스나 래스터 전체가 아니다 — 필요한 셀뿐이다.
    assert window.cells < 30 * 20


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("feature_missing", "FEATURE_UNAVAILABLE"),
        ("feature_other_revision", "FEATURE_UNAVAILABLE"),
        ("decision_missing", "HEIGHT_NOT_ELIGIBLE"),
        ("decision_other_subject", "HEIGHT_NOT_ELIGIBLE"),
        ("decision_withdrawn", "HEIGHT_NOT_ELIGIBLE"),
        ("grants_differ", "AMBIGUOUS_GRANT"),
    ],
)
def test_admission_refuses_what_its_owners_do_not_vouch_for(
    rig: Rig, change: str, reason: str
) -> None:
    if change == "feature_missing":
        rig.features.feature = None
    elif change == "feature_other_revision":
        rig.features.feature = feature_revision(line((1.0, 1.0), (5.0, 5.0)), revision=2)
    elif change == "decision_missing":
        rig.decisions.decision = None
    elif change == "decision_other_subject":
        other = make_measurements()
        assert other  # 다른 subject 로 만든 결정
        from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

        subject = SealedExternalSubjectV1(
            organization_id="org-local",
            site_id="site-local",
            work_order_id="another-order",
            submission_id="submission-local",
            revision=1,
            submission_digest=DIGEST,
            manifest_digest=DIGEST,
        )
        rig.decisions.decision = rig.decisions.decision.model_copy(
            update={
                "subject": subject,
                "subject_digest": subject.canonical_digest(),
                "decision_digest": None,
            }
        ).sealed()
    elif change == "decision_withdrawn":
        rig.decisions.blocker = "POLICY_UNAVAILABLE"
    else:
        rig.grants.other = make_grant(
            grant_id="other-grant",
            allowed_bounds=rig.grants.grant.allowed_bounds,
            observed_crs_digest=DIGEST,
        )
    assert _reason(rig.admit) == reason


def test_a_decision_of_another_use_is_not_a_height_licence(rig: Rig) -> None:
    rig.decisions.decision = rig.decisions.decision.model_copy(
        update={"use": "DISPLAY", "decision_digest": None}
    )
    assert _reason(rig.admit) == "HEIGHT_NOT_ELIGIBLE"


@pytest.mark.parametrize(
    ("measurements", "reason"),
    [
        (dict(observed_crs_identifier="EPSG:3857"), "UNSUPPORTED_CRS"),
        (dict(observed_vertical_reference=None), "UNSUPPORTED_CRS"),
        (dict(transform=(1.0, 0.3, ORIGIN_X, 0.0, -1.0, ORIGIN_Y)), "UNSUPPORTED_RASTER"),
        (dict(band_count=3), "UNSUPPORTED_RASTER"),
    ],
)
def test_a_dsm_the_engine_cannot_read_is_refused_before_any_grant_is_asked(
    rig: Rig, measurements: dict[str, Any], reason: str
) -> None:
    source = rig.sources.source
    measured = source.inspection.measurements.model_copy(update=measurements)
    rig.sources.source = source.model_copy(
        update={"inspection": source.inspection.model_copy(update={"measurements": measured})}
    )
    assert _reason(rig.admit) == reason
    assert rig.grants.selected == []


def test_a_line_that_never_touches_the_surface_is_refused_not_read_as_empty(rig: Rig) -> None:
    rig.features.feature = feature_revision(line((60.0, 60.0), (70.0, 60.0)))
    assert _reason(lambda: rig.admit(feature=rig.features.feature.ref())) == "LINE_OUTSIDE_SURFACE"
    assert rig.grants.selected == []


def test_calculation_limits_are_refused_up_front_never_coarsened(rig: Rig) -> None:
    assert _reason(lambda: rig.admit(sample_spacing_m=1e-9)) == "TOO_MANY_SAMPLES"
    rig.policy = profile_policy(maximum_window_cells=20)
    assert _reason(rig.admit) == "WINDOW_TOO_LARGE"
    assert rig.grants.selected == []


def test_a_foreign_refusal_keeps_its_meaning_or_is_folded_by_status(rig: Rig) -> None:
    rig.sources.resolve_error = SpatialDataDomainError("GRANT_REQUIRED", 403)
    assert _reason(rig.admit) == "GRANT_REQUIRED"
    rig.sources.resolve_error = SpatialDataDomainError("INVALID_REQUEST_BOUNDS", 422)
    assert _reason(rig.admit) == "SOURCE_UNAVAILABLE"
    rig.sources.resolve_error = SpatialDataDomainError("NOT_READY", 404)
    assert _reason(rig.admit) == "NOT_FOUND"
    rig.sources.resolve_error = SpatialDataDomainError("AUDIT_UNAVAILABLE", 503)
    assert _reason(rig.admit) == "CURRENTNESS_UNAVAILABLE"
    rig.sources.resolve_error = None
    rig.grants.error = SpatialDataDomainError("OUTPUT_OUTSIDE_GRANT", 403)
    assert _reason(rig.admit) == "OUTPUT_OUTSIDE_GRANT"


def test_scope_errors_are_translated(rig: Rig) -> None:
    rig.sources.scope_error = SpatialDataDomainError("NOT_FOUND", 404)
    assert _reason(lambda: rig.authority.require_scope(SITE, AREA, requester())) == "NOT_FOUND"


# ── 이후의 모든 전이 ─────────────────────────────────────────────────────────


def _job(rig: Rig, tmp_path: Path) -> Any:
    admission = rig.admit()
    from ksi_event_contracts.surface_profile import CreateSurfaceProfileV1
    from ksi_event_contracts.surface_profile_job import SurfaceProfileFrozenJobV1

    request = issue_request()
    return SurfaceProfileFrozenJobV1(
        job_id="spj-" + "0" * 32,
        organization_id="org-local",
        requester_principal_id="reader-local",
        site_id=SITE,
        work_area_id=AREA,
        request=request,
        feature=admission.feature,
        profile_request=CreateSurfaceProfileV1(
            asset_ref=request.asset_ref,
            line=admission.feature.line,
            feature=admission.feature.ref(),
        ),
        source=admission.source,
        grant=admission.grant,
        data_policy_digest=admission.data_policy_digest,
        height_decision_digest=admission.height_decision_digest,
        policy=rig.policy,
        runtime=rig.runtime,
        read_window=admission.read_window,
        idempotency_key_hash=DIGEST,
        request_fingerprint=request.canonical_digest(),
        created_at=NOW,
        deadline=NOW + timedelta(seconds=30),
    ).sealed()


@pytest.mark.parametrize("operation", ["PREPARE", "READ"])
def test_reprove_asks_every_owner_again_for_the_same_window(
    rig: Rig, tmp_path: Path, operation: Literal["PREPARE", "READ"]
) -> None:
    job = _job(rig, tmp_path)
    rig.decisions.asked.clear()
    rig.authority.reprove(job, operation=operation, now=NOW + later(2))
    assert rig.decisions.asked == [rig.decisions.decision.decision_id]
    (call,) = rig.grants.required
    assert call["operation"] == operation
    assert call["requested_bounds"] == job.read_window.actual_bounds
    assert (call["grant_id"], call["revision"]) == (job.grant.grant_id, job.grant.revision)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("requester_gone", "ACCESS_REVOKED"),
        ("viewer_may_not_prepare", "PERMISSION_DENIED"),
        ("source_drifted", "SOURCE_MEASUREMENTS_MISMATCH"),
        ("source_unavailable", "SOURCE_UNAVAILABLE"),
        ("height_withdrawn", "HEIGHT_NOT_ELIGIBLE"),
        ("decision_replaced", "HEIGHT_NOT_ELIGIBLE"),
        ("grant_revoked", "ACCESS_REVOKED"),
        ("grant_replaced", "ACCESS_REVOKED"),
    ],
)
def test_reprove_refuses_when_any_owner_no_longer_vouches(
    rig: Rig, tmp_path: Path, change: str, reason: str
) -> None:
    job = _job(rig, tmp_path)
    if change == "requester_gone":
        rig.currentness.principal = None
    elif change == "viewer_may_not_prepare":
        rig.currentness.principal = viewer("reader-local")
    elif change == "source_drifted":
        rig.sources.current = rig.sources.source.model_copy(update={"observed_size_bytes": 1})
    elif change == "source_unavailable":
        rig.sources.current_error = SpatialDataDomainError("SOURCE_UNAVAILABLE", 503)
    elif change == "height_withdrawn":
        rig.decisions.blocker = "INSPECTION_REPORT_BINDING_INVALID"
    elif change == "decision_replaced":
        rig.decisions.decision = rig.decisions.decision.model_copy(
            update={"reasons": ("OTHER",), "decision_digest": None}
        ).sealed()
    elif change == "grant_revoked":
        rig.grants.error = SpatialDataDomainError("ACCESS_REVOKED", 403)
    else:
        rig.grants.returned = make_grant(
            grant_id="replacement",
            allowed_bounds=rig.grants.grant.allowed_bounds,
            observed_crs_digest=DIGEST,
        )
    operation: Literal["PREPARE", "READ"] = "PREPARE"
    assert (
        _reason(lambda: rig.authority.reprove(job, operation=operation, now=NOW + later(2)))
        == reason
    )


def test_a_reader_may_reprove_read_without_the_request_permission(rig: Rig, tmp_path: Path) -> None:
    job = _job(rig, tmp_path)
    rig.currentness.principal = viewer("reader-local")
    rig.authority.reprove(job, operation="READ", now=NOW + later(2))


# ── 일꾼 activation 과 구성 ─────────────────────────────────────────────────


def test_only_the_activated_worker_instance_in_its_window_may_work(rig: Rig) -> None:
    ok = rig.authority.worker_is_activated
    assert ok(worker(), "instance-1", NOW)
    assert not ok(worker("other-worker"), "instance-1", NOW)
    assert not ok(worker(org="org-other"), "instance-1", NOW)
    assert not ok(worker(), "instance-2", NOW)
    assert not ok(worker(), "instance-1", NOW + timedelta(hours=2))
    assert not ok(worker(), "instance-1", NOW - timedelta(hours=1))


def test_construction_requires_sealed_snapshots_one_coordinator_and_matching_digests(
    rig: Rig,
) -> None:
    with pytest.raises(ValueError, match="sealed"):
        rig.build(activation=rig.activation.model_copy(update={"activation_digest": None}))
    with pytest.raises(ValueError, match="policy and runtime"):
        rig.build(profile_policy_digest="sha256:" + "7" * 64)
    with pytest.raises(ValueError, match="coordinator"):
        rig.build(coordinator=ExternalAuthorityCurrentnessCoordinator())


# ── 저장소와 맞물려 끝까지 ───────────────────────────────────────────────────


def test_the_store_and_this_authority_complete_a_genuine_profile_and_stop_on_revocation(
    rig: Rig, tmp_path: Path
) -> None:
    store = SurfaceProfileJobStore(
        DurableJournal(tmp_path / "jobs.jsonl"),
        authority=rig.authority,
        policy=rig.policy,
        runtime=rig.runtime,
        coordinator=rig.coordinator,
    )
    # 신원이 일치하도록 요청자를 발급자와 같게 둔다.
    me = requester()
    job_id = store.issue(
        site_id=SITE,
        work_area_id=AREA,
        request=issue_request(),
        principal=me,
        idempotency_key="k",
        now=NOW,
    ).job_id
    attempt = store.lease(
        job_id=job_id,
        worker=worker(),
        request=SurfaceProfileLeaseRequestV1(worker_instance_id="instance-1", acquisition_id="a"),
        now=NOW + later(1),
    )
    job = store.worker_input(job_id=job_id, worker=worker(), attempt=attempt, now=NOW + later(1))
    result, receipt = genuine_answer(job, write_raster(tmp_path / "d.tif"), NOW + later(2))
    store.complete(
        job_id=job_id,
        worker=worker(),
        attempt=attempt,
        result=result,
        receipt=receipt,
        now=NOW + later(2),
    )
    assert store.result(job_id=job_id, principal=me, now=NOW + later(3)).result == result

    rig.grants.error = SpatialDataDomainError("ACCESS_REVOKED", 403)
    with pytest.raises(SurfaceProfileDomainError) as excinfo:
        store.result(job_id=job_id, principal=me, now=NOW + later(4))
    assert excinfo.value.reason == "ACCESS_REVOKED"
