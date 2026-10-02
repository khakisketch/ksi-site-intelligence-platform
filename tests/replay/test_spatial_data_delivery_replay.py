"""HTTP identities/receipts and revoked rights survive actual durable job re-open."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["dsm", "ortho"])
def test_generated_mounted_job_id_receipt_and_bytes_survive_restart(
    tmp_path: Path, kind: str
) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path, kind=kind) as lane:
        status = lane.request_and_run()
        before = lane.consumer.download(status=status, output_dir=tmp_path / "before").read_bytes()
        lane.restart()
        repeated = lane.consumer.issue(request=lane.request, idempotency_key="integration-1")
        assert repeated["jobId"] == status["jobId"]
        assert lane.consumer.status(status["jobId"])["receipt"] == status["receipt"]
        after = lane.consumer.download(status=status, output_dir=tmp_path / "after").read_bytes()
        assert after == before and lane.provider.uploads == 1


def test_generated_completed_revocation_is_not_rewritten_by_replay(tmp_path: Path) -> None:
    from spatial_data_http_fixture import http_lane

    with http_lane(tmp_path) as lane:
        status = lane.request_and_run()
        lane.revoke()
        lane.restart()
        retained = lane.consumer.status(status["jobId"])
        assert (
            retained["receipt"] == status["receipt"] and retained["executionState"] == "COMPLETED"
        )
        assert lane.http.get(lane.file_url(status), headers=lane.auth).status_code == 403
