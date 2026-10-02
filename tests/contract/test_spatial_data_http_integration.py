"""Generated trusted rasters through real inspection, worker and guarded mounted HTTP.

Breaks caught: substituting measured input/grid, publication without prepared bytes,
incorrect cell-edge expansion, mask loss, and hidden cross-tenant/rights widening.
"""

from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
import rasterio


@pytest.mark.parametrize("kind", ["dsm", "ortho"])
def test_generated_inspector_worker_and_independent_http_consumer_preserve_native_cells(
    tmp_path: Path, kind: str
) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path, kind=kind) as lane:
        status = lane.request_and_run()
        receipt = status["receipt"]
        assert status["executionState"] == "COMPLETED"
        assert lane.inspection.outcome.value == "MEASURED"
        assert receipt["pixelWindow"] == [1, 5, 3, 9]
        assert receipt["actualBounds"] == [102, 182, 110, 194]
        assert receipt["transform"] == [2, 0, 102, 0, -2, 194]
        assert receipt["sourceSha256"] == "sha256:" + sha256(lane.source_bytes).hexdigest()
        assert receipt["accuracyAssessed"] is False
        assert "UNKNOWN_VERTICAL_REFERENCE" in receipt["limitations"]
        assert receipt["attribution"] == "Generated raster; local test only"
        downloaded = lane.consumer.download(status=status, output_dir=tmp_path / "consumer")
        assert downloaded.stat().st_size == receipt["outputSizeBytes"]
        assert "sha256:" + sha256(downloaded.read_bytes()).hexdigest() == receipt["outputSha256"]
        with rasterio.open(lane.source_path) as original, rasterio.open(downloaded) as output:
            np.testing.assert_array_equal(output.read(), original.read()[:, 3:9, 1:5])
            np.testing.assert_array_equal(output.dataset_mask(), original.dataset_mask()[3:9, 1:5])
            assert tuple(output.transform)[:6] == (2, 0, 102, 0, -2, 194)
            assert tuple(output.bounds) == (102, 182, 110, 194)
            assert output.crs == original.crs and output.nodata == original.nodata
            assert "PRODUCER_NOTE" not in output.tags()
            assert int(np.count_nonzero(output.dataset_mask())) == receipt["validPixelCount"]
        assert lane.provider.uploads == 1
        assert list(lane.workspace.iterdir()) == []
        assert lane.downloads.active_downloads == 0


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("source", "SOURCE_BYTES_MISMATCH"),
        ("receipt", "OUTPUT_VERIFICATION_FAILED"),
        ("candidate", "OUTPUT_VERIFICATION_FAILED"),
    ],
)
def test_mounted_worker_cannot_publish_substituted_source_receipt_or_candidate(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path, mutation=mutation) as lane:
        status = lane.request_and_run()
        assert status["executionState"] == "FAILED" and status["reason"] == reason
        assert status["receipt"] is None and lane.provider.uploads == 0
        assert lane.http.get(lane.file_url(status), headers=lane.auth).status_code != 200
        assert list(lane.workspace.iterdir()) == []


def test_mounted_completed_history_remains_after_revocation_but_head_get_are_denied(
    tmp_path: Path,
) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        lane.revoke()
        history = lane.consumer.status(status["jobId"])
        assert history["executionState"] == "COMPLETED" and history["receipt"] == status["receipt"]
        for method in ("get", "head"):
            response = getattr(lane.http, method)(lane.file_url(status), headers=lane.auth)
            assert response.status_code == 403
        assert (
            lane.http.post(
                lane.base, json=lane.request, headers=lane.auth | {"Idempotency-Key": "other"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("method", ["get", "head"])
def test_generated_mounted_foreign_files_and_range_do_not_disclose_receipt_or_storage(
    tmp_path: Path, method: str
) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        response = getattr(lane.http, method)(
            lane.file_url(status), headers={"Authorization": "Bearer foreign", "Range": "bytes=0-1"}
        )
        assert response.status_code == 404
        assert (
            lane.http.get(
                lane.base + "/" + status["jobId"], headers={"Authorization": "Bearer foreign"}
            ).status_code
            == 404
        )
        own = getattr(lane.http, method)(
            lane.file_url(status), headers=lane.auth | {"Range": "bytes=0-1"}
        )
        assert own.status_code == 416
