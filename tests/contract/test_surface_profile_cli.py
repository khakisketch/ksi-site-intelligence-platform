"""Local operator CLI tests use a mocked Core origin and synthetic numbers only."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from ksi_event_contracts.measurement_feature import MeasurementFeatureRefV1
from ksi_event_contracts.surface_profile import SurfaceProfileResultV1, SurfaceProfileSampleV1
from ksi_event_contracts.surface_profile_job import SurfaceProfileComparisonV1
from ksi_processing_controller.surface_profile_cli import (
    ProfileCliError,
    SurfaceProfileReadClient,
    _read_bearer,
    main,
)
from surface_profile_job_fixture import receipt_for
from test_surface_profile_job_contracts import _job

SITE = "site-operator-test"
AREA = "wa-operator-test-0001"
JOB_A = "spj-" + "a" * 32
JOB_B = "spj-" + "b" * 32
DECISION = "external-use-decision-" + "c" * 32
ASSET = "ksa-v1-" + "d" * 64
FEATURE = MeasurementFeatureRefV1(
    feature_id="mf-" + "1" * 32,
    revision=3,
    line_digest="sha256:" + "e" * 64,
)


def _profile_payload(*, site_id: str = SITE, work_area_id: str = AREA) -> dict:
    result = SurfaceProfileResultV1(
        asset_ref=ASSET,
        line_digest=FEATURE.line_digest,
        feature=FEATURE,
        horizontal_crs="EPSG:5186",
        line_length_m=10.0,
        sample_spacing_m=10.0,
        window_cells_read=4,
        samples=(
            SurfaceProfileSampleV1(
                index=0,
                distance_m=0.0,
                x=1.0,
                y=2.0,
                elevation_m=10.0,
                invalid_reason=None,
            ),
            SurfaceProfileSampleV1(
                index=1,
                distance_m=10.0,
                x=11.0,
                y=2.0,
                elevation_m=None,
                invalid_reason="NODATA",
            ),
        ),
        valid_count=1,
        unknown_count=1,
        minimum_m=10.0,
        maximum_m=10.0,
    ).sealed()
    frozen = _job(job_id=JOB_A)
    receipt = receipt_for(frozen, result, frozen.created_at)
    return {
        "job": {
            "jobId": JOB_A,
            "assetRef": ASSET,
            "siteId": site_id,
            "workAreaId": work_area_id,
            "feature": FEATURE.model_dump(by_alias=True, mode="json"),
            "createdAt": frozen.created_at.isoformat(),
            "executionState": "COMPLETED",
            "availability": "AVAILABLE",
            "receipt": receipt.model_dump(by_alias=True, mode="json"),
        },
        "result": result.model_dump(by_alias=True, mode="json"),
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> SurfaceProfileReadClient:
    return SurfaceProfileReadClient(
        core_origin="https://core.example.invalid",
        token="operator-secret-that-must-not-be-printed",
        transport=httpx.MockTransport(handler),
    )


def test_profile_reads_only_exact_scoped_result_and_preserves_unknown_samples() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer operator-secret-that-must-not-be-printed"
        return httpx.Response(200, json=_profile_payload())

    client = _client(handler)
    try:
        output = client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()

    assert len(calls) == 1
    assert (
        calls[0].url.path
        == f"/v1/sites/{SITE}/work-areas/{AREA}/surface-profile-jobs/{JOB_A}/result"
    )
    assert output["job"]["feature"]["revision"] == 3
    assert output["result"]["samples"][1]["elevationM"] is None
    assert output["result"]["samples"][1]["invalidReason"] == "NODATA"


def test_profile_fails_closed_when_scope_or_saved_line_does_not_match() -> None:
    client = _client(lambda _: httpx.Response(200, json=_profile_payload(site_id="other-site")))
    try:
        with pytest.raises(ProfileCliError, match="단면 계약"):
            client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()


@pytest.mark.parametrize("missing", ["resultDigest", "receiptDigest", "receipt", "mismatchedJob"])
def test_only_results_with_their_own_sealed_receipt_are_returned(missing: str) -> None:
    from ksi_event_contracts.surface_profile_job import SurfaceProfileReceiptV1

    payload = _profile_payload()
    if missing == "resultDigest":
        payload["result"]["resultDigest"] = None
    elif missing == "receiptDigest":
        payload["job"]["receipt"]["receiptDigest"] = None
    elif missing == "receipt":
        payload["job"]["receipt"] = None
    else:
        receipt = payload["job"]["receipt"]
        receipt.update(jobId=JOB_B, receiptDigest=None)
        payload["job"]["receipt"] = (
            SurfaceProfileReceiptV1.model_validate(receipt)
            .sealed()
            .model_dump(by_alias=True, mode="json")
        )
    client = _client(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProfileCliError, match="단면 계약"):
            client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()


def test_comparison_rereads_exact_order_and_keeps_blocked_decision_nonnumeric() -> None:
    blocked = SurfaceProfileComparisonV1(
        baseline_job_id=JOB_A,
        current_job_id=JOB_B,
        decision_id=DECISION,
        decision_digest="sha256:" + "f" * 64,
        verdict="BLOCKED",
        reasons=("PROFILE_COMPARISON_NO_LONGER_ELIGIBLE",),
        remediations=("RECHECK_CURRENT_PAIR",),
        result=None,
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.params["baseline_job_id"] == JOB_A
        assert request.url.params["current_job_id"] == JOB_B
        assert request.url.params["decision_id"] == DECISION
        return httpx.Response(200, json=blocked.model_dump(by_alias=True, mode="json"))

    client = _client(handler)
    try:
        output = client.comparison(
            site_id=SITE,
            work_area_id=AREA,
            baseline_job_id=JOB_A,
            current_job_id=JOB_B,
            decision_id=DECISION,
        )
    finally:
        client.close()

    assert len(calls) == 1
    assert output["verdict"] == "BLOCKED"
    assert output["result"] is None
    assert output["reasons"] == ["PROFILE_COMPARISON_NO_LONGER_ELIGIBLE"]


@pytest.mark.parametrize(
    ("site_id", "work_area_id", "job_id"),
    [("../other", AREA, JOB_A), (SITE, "area/foreign", JOB_A), (SITE, AREA, "spj-short")],
)
def test_bad_identifiers_do_not_reach_core(site_id: str, work_area_id: str, job_id: str) -> None:
    client = _client(lambda request: pytest.fail("invalid identifiers reached Core"))
    try:
        with pytest.raises(ProfileCliError, match="식별자 형식|작업 ID 형식"):
            client.profile(site_id=site_id, work_area_id=work_area_id, job_id=job_id)
    finally:
        client.close()


@pytest.mark.parametrize(
    "core_origin",
    ["http://core.example.org", "https://u:p@core.example.org", "https://core.example.org/api"],
)
def test_nonlocal_http_credentials_or_path_origin_are_refused(core_origin: str) -> None:
    with pytest.raises(ProfileCliError):
        SurfaceProfileReadClient(core_origin=core_origin, token="credential")


def test_only_owner_private_bearer_files_are_read(tmp_path: Path) -> None:
    token_file = tmp_path / "operator-token"
    token_file.write_text("opaque-operator-token\n")
    token_file.chmod(0o600)
    assert _read_bearer(token_file) == "opaque-operator-token"
    token_file.chmod(0o644)
    with pytest.raises(ProfileCliError, match="소유자 전용"):
        _read_bearer(token_file)


def test_command_prints_contract_json_and_never_prints_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token_file = tmp_path / "operator-token"
    token_file.write_text("operator-token-for-test\n")
    token_file.chmod(0o600)
    profile = _profile_payload()

    class FakeClient:
        def __init__(self, *, core_origin: str, token: str) -> None:
            assert core_origin == "https://core.example.invalid"
            assert token == "operator-token-for-test"

        def profile(self, **_: str) -> dict:
            return profile

        def comparison(self, **_: str) -> dict:
            raise AssertionError("profile command called comparison")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "ksi_processing_controller.surface_profile_cli.SurfaceProfileReadClient", FakeClient
    )
    exit_code = main(
        [
            "--core-origin",
            "https://core.example.invalid",
            "--token-file",
            str(token_file),
            "profile",
            "--site-id",
            SITE,
            "--work-area-id",
            AREA,
            "--job-id",
            JOB_A,
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["job"]["jobId"] == JOB_A
    assert "operator-token-for-test" not in captured.out
    assert captured.err == ""


def test_http_errors_preserve_closed_reason_codes_without_echoing_server_body() -> None:
    secret_text = "a server-provided message that must not be printed"
    client = _client(
        lambda _: httpx.Response(403, json={"reason": "ACCESS_REVOKED", "detail": secret_text})
    )
    try:
        with pytest.raises(ProfileCliError, match="ACCESS_REVOKED") as caught:
            client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()
    assert secret_text not in str(caught.value)
    assert "operator-secret-that-must-not-be-printed" not in str(caught.value)


def test_expired_result_keeps_core_retention_reason_without_echoing_message() -> None:
    secret_text = "private server diagnostic"
    client = _client(
        lambda _: httpx.Response(410, json={"reason": "RETENTION_EXPIRED", "message": secret_text})
    )
    try:
        with pytest.raises(ProfileCliError, match="HTTP 410 RETENTION_EXPIRED") as caught:
            client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()
    assert secret_text not in str(caught.value)


def test_response_size_is_bounded_before_json_parsing() -> None:
    from ksi_processing_controller.surface_profile_cli import MAX_RESPONSE_BYTES

    client = _client(lambda _: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    try:
        with pytest.raises(ProfileCliError, match="허용 크기") as caught:
            client.profile(site_id=SITE, work_area_id=AREA, job_id=JOB_A)
    finally:
        client.close()
    assert "x" * 256 not in str(caught.value)
