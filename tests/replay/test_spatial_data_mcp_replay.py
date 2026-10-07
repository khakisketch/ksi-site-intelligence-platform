"""Task5 replay: lost-response single issuance + restart state machine.

Every test drives the real loopback Core (actual journal stores), a
separately started worker, and the guarded HTTP consumer. No mocks, no
forged oracles: the export receipt is the Core record.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture

fixture.ensure_source_path()

ACK = "X-KSI-Spatial-Data-AI-Egress"


def _raw_client(lane: Any) -> Any:
    import httpx

    return httpx.Client(
        base_url=lane.origin,
        headers={"Authorization": "Bearer " + fixture.TASK5_AI_TOKEN},
        timeout=10,
        trust_env=False,
    )


def _lose_create_response(*, origin: str, path: str, body: dict[str, Any], key: str) -> None:
    """POST a create over a raw socket and lose the response (never read it)."""
    import socket
    import time
    from urllib.parse import urlsplit

    port = urlsplit(origin).port
    assert port is not None
    payload = json.dumps(body).encode()
    request = (
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {fixture.TASK5_AI_TOKEN}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\nIdempotency-Key: {key}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + payload
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(request)
        time.sleep(1.0)  # bounded pacing: let Core issue + respond into the unread buffer
    finally:
        sock.close()  # the response is lost; nothing was ever read


def _job_journal_lines(root: Path, job_id: str) -> list[str]:
    return [line for line in (root / "jobs.jsonl").read_text().splitlines() if job_id in line]


def test_lost_create_response_issues_exactly_once(tmp_path: Path) -> None:
    """A lost create response retries to the SAME job; no duplicate issuance."""
    root = tmp_path / "lost"
    root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(root, kind="dsm") as lane:
        body = lane.request_body()
        _lose_create_response(origin=lane.origin, path=lane.base, body=body, key="lost-1")
        retried = lane.consumer.issue(request=lane.request_body(), idempotency_key="lost-1")
        assert retried["executionState"] == "QUEUED"
        client = _raw_client(lane)
        try:
            page = client.get(lane.base, params={"limit": 2})
            assert page.status_code == 200
            assert [item["jobId"] for item in page.json()["items"]] == [retried["jobId"]]
        finally:
            client.close()
        assert _job_journal_lines(root, retried["jobId"]) != []
        altered = dict(lane.request_body())
        altered["requestedBounds"] = [103.0, 184.0, 107.0, 192.0]
        with pytest.raises(RuntimeError, match="IDEMPOTENCY_CONFLICT"):
            lane.consumer.issue(request=altered, idempotency_key="lost-1")
        completed = lane.run_worker(retried["jobId"])
        assert completed["executionState"] == "COMPLETED"
        assert completed["receipt"] is not None


def test_restart_replays_queued_completed_canceled(tmp_path: Path) -> None:
    """Restart preserves QUEUED/COMPLETED/CANCELED; queue stays runnable."""
    root = tmp_path / "states"
    root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(root, kind="dsm") as lane:
        # Complete the first job while it is the ONLY queued job (the worker
        # leases FIFO); the stay-queued job is issued afterwards.
        done = lane.request_and_run(key="state-done")
        assert done["executionState"] == "COMPLETED"
        queued = lane.consumer.issue(request=lane.request_body(), idempotency_key="state-queued")
        before_bytes = lane.consumer.download(
            status=done, output_dir=tmp_path / "states-before"
        ).read_bytes()
        doomed = lane.consumer.issue(request=lane.request_body(), idempotency_key="state-doomed")
        client = _raw_client(lane)
        try:
            canceled = client.post(lane.base + "/" + doomed["jobId"] + "/cancel")
            assert canceled.status_code == 200
        finally:
            client.close()
        assert lane.consumer.status(doomed["jobId"])["executionState"] == "CANCELED"

        lane.restart()
        lane.set_consent(True)

        assert lane.consumer.status(queued["jobId"])["executionState"] == "QUEUED"

        # Re-download the old bytes BEFORE reviving the queued job: the lane's
        # object test-double retains only the latest upload (single slot), so
        # a second worker upload would displace these bytes. Versioned
        # retention is deployment storage territory, not this lane.
        retained = lane.consumer.status(done["jobId"])
        assert retained["executionState"] == "COMPLETED"
        assert retained["receipt"] == done["receipt"]
        after_bytes = lane.consumer.download(
            status=retained, output_dir=tmp_path / "states-after"
        ).read_bytes()
        assert after_bytes == before_bytes
        assert "sha256:" + sha256(after_bytes).hexdigest() == retained["receipt"]["outputSha256"]

        revived = lane.run_worker(queued["jobId"])
        assert revived["executionState"] == "COMPLETED"
        assert revived["receipt"] is not None

        still = lane.consumer.status(doomed["jobId"])
        assert still["executionState"] == "CANCELED"
        assert still["receipt"] is None


def test_revoked_completed_stays_frozen_in_journal_across_restart(tmp_path: Path) -> None:
    """Completed + revoked → restart: receipt frozen in journal, bytes denied."""
    root = tmp_path / "frozen"
    root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(root, kind="dsm") as lane:
        done = lane.request_and_run(key="frozen-done")
        assert done["executionState"] == "COMPLETED"
        digest = done["receipt"]["outputSha256"]
        journal_before = _job_journal_lines(root, done["jobId"])
        assert any(digest in line for line in journal_before)

        lane.revoke_grant()
        lane.restart()

        journal_after = _job_journal_lines(root, done["jobId"])
        assert journal_after == journal_before
        assert any(digest in line for line in journal_after)

        client = _raw_client(lane)
        try:
            metadata = client.get(lane.base + "/" + done["jobId"])
            assert metadata.status_code in {403, 404}
            assert metadata.headers.get(ACK) is None
            file_response = client.get(lane.file_url(done))
            assert file_response.status_code in {403, 404}
            assert file_response.headers.get(ACK) is None
        finally:
            client.close()
