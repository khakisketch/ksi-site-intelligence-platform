"""Two generated, independently specified surfaces through real requester and worker HTTP.

The compatibility record and checkpoint attestations are local fixtures. No field material,
customer acceptance or external mapping authority participates in this test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import rasterio
from analysis_api_local_fixture import (
    _ORIGIN_X,
    _ORIGIN_Y,
    _register_and_seal_v2_dsm,
    _validate_evidence,
)
from fastapi.testclient import TestClient
from ksi_core.domains.external.quantity.external_profile_difference_authorities import (
    ExternalProfileDifferenceAuthority,
    SyntheticExternalProfileDifferenceAuthorityPort,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1
from ksi_processing_controller.surface_profile_cli import main as read_profile_cli
from pyproj import CRS
from rasterio.transform import from_origin
from spatial_data_fixture import make_revocation
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_platform_core_http_integration import (
    _admit_real_inspection_policy,
    _create_external_order,
    _lane_view,
    _seed_site_and_area,
    _store_order,
)
from test_surface_profile_http_integration import (
    _READER_TOKEN,
    _feature_ref,
    _height_decision_id,
    _provision_surface_grant,
    _reader_headers,
    _ReadyFlow,
    _retain_real_parser_report,
    _run_surface_worker,
)


def _digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()


def _surface(*, current: bool) -> bytes:
    row, col = np.indices((16, 48))
    grid = 100.0 + col * 0.25 + row * 0.125
    if current:
        grid += (col - 23) / 8.0
        grid[:, 30:32] = -9999
    else:
        grid[:, 11:13] = -9999
    with rasterio.MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=48,
            height=16,
            count=1,
            dtype="float64",
            compress="deflate",
            crs="EPSG:5186+5773",
            transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1, 1),
            nodata=-9999,
        ) as dataset:
            dataset.write(grid, 1)
        return memory.read()


class _LocalMapping:
    """A test-owned mapping, published only for the preselected earlier and later sources."""

    def __init__(self) -> None:
        self.registry: SyntheticExternalProfileDifferenceAuthorityPort | None = None
        self.active = False

    def build(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _LocalMapping:
        self.currentness_coordinator = coordinator
        return self

    def register(self, record: ExternalProfileDifferenceAuthority) -> None:
        with self.currentness_coordinator.mutation():
            self.registry = SyntheticExternalProfileDifferenceAuthorityPort(
                (record,), currentness_coordinator=self.currentness_coordinator
            )

    def resolve_for_use(self, **selection: Any) -> ExternalProfileDifferenceAuthority | None:
        return self.registry.resolve_for_use(**selection) if self.active and self.registry else None

    def is_current_for_use(
        self, authority: ExternalProfileDifferenceAuthority, **when: Any
    ) -> bool:
        return bool(
            self.active and self.registry and self.registry.is_current_for_use(authority, **when)
        )

    def resolve_historical_for_decision(
        self, decision: Any
    ) -> ExternalProfileDifferenceAuthority | None:
        return self.registry.resolve_historical_for_decision(decision) if self.registry else None

    def set_active(self, active: bool) -> None:
        with self.currentness_coordinator.mutation():
            self.active = active


@contextmanager
def _pair_scene(tmp_path: Path) -> Iterator[tuple[_ReadyFlow, _LocalMapping, list[str]]]:
    mapping = _LocalMapping()
    flow = _ReadyFlow(tmp_path, build_profile_difference_authority=mapping.build)
    ctx = flow.ctx
    try:
        epochs = []
        identities = {}
        with TestClient(ctx.app) as setup:
            flow.area_id = _seed_site_and_area(ctx, extent_m=48.0)
            for side, days in (("baseline", 3), ("current", 1)):
                raw = _surface(current=side == "current")
                order = _store_order(
                    ctx, _create_external_order(setup, flow.area_id, key=side)["workOrderId"]
                )
                start = ctx.now - timedelta(days=days)
                end = start + timedelta(minutes=5)
                revision, subject = _register_and_seal_v2_dsm(
                    setup,
                    ctx.app,
                    order,
                    "profile-" + side,
                    start=start,
                    end=end,
                    storage=ctx.storage,
                    dsm_bytes=raw,
                )
                entry = revision.manifest.entries[0]
                digest = _digest(raw)
                assert entry.observed_sha256 == digest.removeprefix("sha256:")
                identities.update(
                    {
                        side + "_subject_digest": subject.canonical_digest(),
                        side + "_artifact_id": entry.artifact_id,
                        side + "_source_sha256": digest,
                    }
                )
                epochs.append((order, revision, subject, start, end))
                flow.source_bytes[digest] = raw
            mapping_digest = _digest(
                canonical_json_bytes(
                    {
                        "fixture": "profile-comparison-two-planes-v1",
                        **identities,
                        "crs": "EPSG:5186",
                        "vertical": "EPSG:5773",
                        "baselineStarted": epochs[0][3].isoformat(),
                        "currentStarted": epochs[1][3].isoformat(),
                    }
                )
            )
            policy, manifest = _admit_real_inspection_policy(
                ctx,
                (epochs[0][2], epochs[1][2]),
                allow_height=True,
                profile_mapping_digest=mapping_digest,
            )
            feature = setup.post(
                f"/v1/sites/site-a/work-areas/{flow.area_id}/measurement-features",
                headers=_reader_headers("comparison-line"),
                json={
                    "workAreaId": flow.area_id,
                    "name": "합성 구역 동서 측정선",
                    "line": {
                        "crs": "EPSG:5186",
                        "vertices": [
                            [_ORIGIN_X + 1.5, _ORIGIN_Y - 7.5],
                            [_ORIGIN_X + 45.5, _ORIGIN_Y - 7.5],
                        ],
                    },
                },
            )
            assert feature.status_code == 201, feature.text
            flow.feature = feature.json()["revision"]
        flow.view = _lane_view(
            ctx, epochs[0][1], epochs[0][2], epochs[1][1], epochs[1][2], policy, manifest
        )
        flow.servers = _CoreAndObjectServers(flow.view)
        flow.servers.__enter__()
        flow.http = httpx.Client(base_url=flow.servers.core_origin, trust_env=False, timeout=10)
        job_ids = []
        for order, revision, subject, _, _ in epochs:
            _retain_real_parser_report(flow, subject=subject, revision=revision)
            _validate_evidence(
                ctx.app,
                revision=revision,
                subject=subject,
                policy=policy,
                context_authority=ctx.context_authority,
                now=ctx.now,
                storage=ctx.storage,
            )
            asset_ref = _provision_surface_grant(ctx, flow.area_id, revision, extent_m=48)
            decision_id = _height_decision_id(flow.http, order, subject, key="height-" + asset_ref)
            job = flow.http.post(
                flow.requester_base,
                headers=_reader_headers("job-" + asset_ref),
                json={
                    "assetRef": asset_ref,
                    "feature": _feature_ref(flow.feature),
                    "heightDecisionId": decision_id,
                    "sampleSpacingM": 1.0,
                },
            )
            assert job.status_code == 200, job.text
            job_ids.append(job.json()["jobId"])
        for _ in epochs:
            assert _run_surface_worker(flow, flow.servers.core_origin)
        crs_digest = _digest(
            CRS.from_epsg(5186)
            .to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
            .encode()
        )
        vertical_digest = ObservedVerticalReferenceV1(
            identifier="EPSG:5773", basis="EGM96 height"
        ).canonical_digest()
        mapping.register(
            ExternalProfileDifferenceAuthority(
                **identities,
                baseline_capture_started_at=epochs[0][3],
                baseline_capture_ended_at=epochs[0][4],
                current_capture_started_at=epochs[1][3],
                current_capture_ended_at=epochs[1][4],
                observed_crs_digest=crs_digest,
                observed_vertical_reference_digest=vertical_digest,
                policy_digest=policy.policy_digest,
                compatibility_mapping_digest=mapping_digest,
                historical_authority_digest=_digest(
                    b"local-profile-mapping-history:" + mapping_digest.encode()
                ),
                valid_from=ctx.now - timedelta(hours=1),
                valid_until=ctx.now + timedelta(days=1),
                synthetic_test_only=True,
            )
        )
        yield flow, mapping, job_ids
    finally:
        flow.close()


def test_profile_comparison_requires_mapping_and_matches_the_analytic_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _pair_scene(tmp_path) as (flow, mapping, job_ids):
        http = flow.http
        assert http is not None and flow.servers is not None
        base = f"/v1/sites/site-a/work-areas/{flow.area_id}/surface-profile-comparisons"
        body = dict(zip(("baselineJobId", "currentJobId"), job_ids, strict=True))
        blocked = http.post(base, headers=_reader_headers("comparison-no-mapping"), json=body)
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["verdict"] == "BLOCKED"
        assert blocked.json()["result"] is None
        assert "COMPATIBILITY_MAPPING_MISSING" in blocked.json()["reasons"]
        mapping.set_active(True)
        retry = http.post(base, headers=_reader_headers("comparison-no-mapping"), json=body)
        assert retry.status_code == 200, retry.text
        assert retry.json() == blocked.json()
        response = http.post(base, headers=_reader_headers("comparison-approved"), json=body)
        assert response.status_code == 200, response.text
        comparison = response.json()
        assert comparison["verdict"] == "ELIGIBLE", comparison["reasons"]
        result = comparison["result"]
        assert len(result["samples"]) == 45
        for index, sample in enumerate(result["samples"]):
            col = index + 1
            baseline_expected = 100.0 + col * 0.25 + 7 * 0.125
            difference = (col - 23) / 8.0
            assert sample["distanceM"] == pytest.approx(index)
            if col in (11, 12):
                assert sample["invalidReason"] == "BASELINE_UNAVAILABLE"
                assert sample["baselineM"] is None
                assert sample["currentM"] == pytest.approx(baseline_expected + difference)
                assert sample["differenceM"] is None
            elif col in (30, 31):
                assert sample["invalidReason"] == "CURRENT_UNAVAILABLE"
                assert sample["baselineM"] == pytest.approx(baseline_expected)
                assert sample["currentM"] is None
                assert sample["differenceM"] is None
            else:
                assert sample["invalidReason"] is None
                assert sample["baselineM"] == pytest.approx(baseline_expected)
                assert sample["currentM"] == pytest.approx(baseline_expected + difference)
                assert sample["differenceM"] == pytest.approx(difference)
        assert result["validCount"] == 41
        assert result["largestRiseM"] == pytest.approx(2.75)
        assert result["largestDropM"] == pytest.approx(-2.75)
        assert any(row["differenceM"] == 0 for row in result["samples"])
        params = dict(
            baseline_job_id=job_ids[0],
            current_job_id=job_ids[1],
            decision_id=comparison["decisionId"],
        )
        reread = http.get(base, headers=_reader_headers(), params=params)
        assert reread.status_code == 200 and reread.json() == comparison
        token_file = tmp_path.resolve() / "profile-reader.token"
        token_file.write_text(_READER_TOKEN)
        token_file.chmod(0o600)
        cli = ["--core-origin", flow.servers.core_origin, "--token-file", str(token_file)]
        scope = ["--site-id", flow.ctx.site_id, "--work-area-id", flow.area_id]
        for job_id in job_ids:
            assert read_profile_cli([*cli, "profile", *scope, "--job-id", job_id]) == 0
            retained = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
            assert (
                retained.status_code == 200
                and json.loads(capsys.readouterr().out) == retained.json()
            )
        compare_command = [
            *cli,
            "comparison",
            *scope,
            "--baseline-job-id",
            job_ids[0],
            "--current-job-id",
            job_ids[1],
            "--decision-id",
            comparison["decisionId"],
        ]
        assert read_profile_cli(compare_command) == 0
        assert json.loads(capsys.readouterr().out) == comparison
        reversed_pair = http.post(
            base,
            headers=_reader_headers("comparison-reversed"),
            json={"baselineJobId": job_ids[1], "currentJobId": job_ids[0]},
        )
        assert reversed_pair.status_code == 200, reversed_pair.text
        assert reversed_pair.json()["verdict"] == "BLOCKED"
        # The admitted policy selects only the ordered earlier/later pair.
        assert reversed_pair.json()["reasons"] == ["POLICY_UNAVAILABLE"]
        assert reversed_pair.json()["result"] is None
        wrong_decision = http.get(
            base,
            headers=_reader_headers(),
            params={**params, "decision_id": reversed_pair.json()["decisionId"]},
        )
        assert wrong_decision.status_code == 404, wrong_decision.text
        mapping.set_active(False)
        revoked = http.get(base, headers=_reader_headers(), params=params)
        assert revoked.status_code == 409, revoked.text
        assert revoked.json()["reason"] == "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE"
        assert read_profile_cli(compare_command) == 1
        denied_output = capsys.readouterr()
        assert (
            denied_output.out == "" and "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE" in denied_output.err
        )
        assert "differenceM" not in revoked.text
        retry = http.post(base, headers=_reader_headers("comparison-approved"), json=body)
        assert retry.status_code == 409, retry.text
        assert "differenceM" not in retry.text
        for job_id in job_ids:
            assert (
                http.get(
                    f"{flow.requester_base}/{job_id}/result", headers=_reader_headers()
                ).status_code
                == 200
            )

        mapping.set_active(True)
        baseline_job = http.get(
            f"{flow.requester_base}/{job_ids[0]}", headers=_reader_headers()
        ).json()
        grants = flow.ctx.app.state.spatial_data.grants
        grant = grants.historical_grant(
            organization_id="org-a",
            grant_id="surface-grant-" + baseline_job["assetRef"],
            revision=1,
        )
        assert grant is not None
        grants.revoke(
            make_revocation(
                organization_id=grant.organization_id,
                grant_id=grant.grant_id,
                revision=grant.revision,
                grant_digest=grant.grant_digest,
                revoked_at=flow.ctx.now,
            )
        )
        denied = http.get(base, headers=_reader_headers(), params=params)
        assert denied.status_code == 403, denied.text
        assert "differenceM" not in denied.text
        current_only = http.get(
            f"{flow.requester_base}/{job_ids[1]}/result", headers=_reader_headers()
        )
        assert current_only.status_code == 200, current_only.text
