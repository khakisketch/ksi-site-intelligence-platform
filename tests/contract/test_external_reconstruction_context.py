"""External upload context is a scoped pure read, independent of acquisition."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_core.domains.observations.epoch_identity import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from test_external_reconstruction_api import (
    _OTHER_TOKEN,
    _TOKEN,
    _client,
    _submission,
)


def test_context_supplies_registration_epoch_without_mutating_work_order(tmp_path: Path) -> None:
    client, _, order_id, epoch = _client(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")}
    response = client.get(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-context",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "workOrderId": order_id,
        "siteId": "site-a",
        "expectedEpochId": epoch,
        "cycleNumber": 1,
        "workOrderVersion": 1,
        "executionMode": "MANAGED_ACQUISITION",
        "externalPlanningBinding": None,
        "externalResult": {"state": "NOT_CONFIGURED", "result": None},
    }
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.jsonl")} == before
    # The actual ingress accepts this server-derived epoch without an AcquisitionRun.
    submission = _submission(work_order_id=order_id, epoch_id=response.json()["expectedEpochId"])
    submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(submission)
    registered = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=submission,
    )
    assert registered.status_code == 201
    assert (tmp_path / "orders.jsonl").read_bytes() == before["orders.jsonl"]
    assert not (tmp_path / "acquisition-runs.jsonl").exists()


def test_context_marks_initial_external_ingress_without_managed_authority(tmp_path: Path) -> None:
    client, _, _, _ = _client(tmp_path)
    work_orders = cast(Any, client.app).state.external_reconstruction_test_work_orders
    external = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="외부 결과 등록",
        work_area_ids=["wa-a"],
        schedule_id=None,
        execution_mode="EXTERNAL_RECONSTRUCTION",
        idempotency_key="context-external-1",
        actor="operator-a",
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )

    response = client.get(
        f"/v1/observation-work-orders/{external.work_order_id}/external-reconstruction-context",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["executionMode"] == "EXTERNAL_RECONSTRUCTION"
    assert response.json()["externalPlanningBinding"] is None


def test_initial_external_ingress_requires_an_explicit_ordered_capture_interval(
    tmp_path: Path,
) -> None:
    client, _, _, _ = _client(tmp_path)
    work_orders = cast(Any, client.app).state.external_reconstruction_test_work_orders
    external = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="촬영 시각 확인",
        work_area_ids=["wa-a"],
        schedule_id=None,
        execution_mode="EXTERNAL_RECONSTRUCTION",
        idempotency_key="capture-ingress-1",
        actor="operator-a",
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )
    context = client.get(
        f"/v1/observation-work-orders/{external.work_order_id}/external-reconstruction-context",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert context.status_code == 200
    payload = _submission(
        work_order_id=external.work_order_id,
        epoch_id=context.json()["expectedEpochId"],
        submission_id="capture-interval-1",
    )
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)
    path = (
        f"/v1/observation-work-orders/{external.work_order_id}/external-reconstruction-submissions"
    )

    missing = client.post(path, headers={"Authorization": f"Bearer {_TOKEN}"}, json=payload)
    assert missing.status_code == 422

    payload["inputDeclaration"]["captureStartedAt"] = "2026-09-06T00:00:00Z"
    payload["inputDeclaration"]["captureEndedAt"] = "2026-09-06T00:00:00Z"
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)
    equal = client.post(path, headers={"Authorization": f"Bearer {_TOKEN}"}, json=payload)
    assert equal.status_code == 422
    assert equal.json()["detail"] == "CAPTURE_INTERVAL_MUST_BE_POSITIVE_FOR_EXTERNAL_INGRESS"

    payload["inputDeclaration"]["captureEndedAt"] = "2026-09-06T00:10:00Z"
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)
    registered = client.post(path, headers={"Authorization": f"Bearer {_TOKEN}"}, json=payload)
    assert registered.status_code == 201, registered.text


def test_legacy_equal_capture_submission_replays_after_recovery(tmp_path: Path) -> None:
    """A retained V1 declaration may have a zero-duration capture interval."""
    client, _, _, _ = _client(tmp_path)
    work_orders = cast(Any, client.app).state.external_reconstruction_test_work_orders
    legacy_order = work_orders.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="기존 동일 시각 선언",
        work_area_ids=["wa-a"],
        schedule_id=None,
        actor="operator-a",
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )
    payload = _submission(
        work_order_id=legacy_order.work_order_id,
        epoch_id=observation_epoch_id(legacy_order),
        submission_id="legacy-equal-capture",
    )
    payload["inputDeclaration"]["captureStartedAt"] = "2026-09-06T00:00:00Z"
    payload["inputDeclaration"]["captureEndedAt"] = "2026-09-06T00:00:00Z"
    payload["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(payload)
    submission = ExternalReconstructionSubmissionV1.model_validate(payload)

    path = tmp_path / "legacy-equal-capture.jsonl"
    store = ExternalReconstructionStore(DurableJournal(path))
    registered = store.register(
        submission,
        work_order=legacy_order,
        registered_by="operator-a",
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert registered.revision is not None
    store._journal.close()

    reopened = ExternalReconstructionStore(DurableJournal(path))
    replayed = reopened.get(
        legacy_order.work_order_id,
        "legacy-equal-capture",
        1,
        organization_id="org-a",
        site_id="site-a",
    )
    assert replayed is not None
    assert replayed.submission.input_declaration.capture_started_at == datetime(
        2026, 9, 6, tzinfo=UTC
    )
    reopened._journal.close()


@pytest.mark.parametrize("foreign", [False, True])
def test_context_hides_missing_and_foreign_orders(tmp_path: Path, foreign: bool) -> None:
    client, _, order_id, _ = _client(tmp_path)
    target_id = order_id if foreign else "missing"
    response = client.get(
        f"/v1/observation-work-orders/{target_id}/external-reconstruction-context",
        headers={"Authorization": f"Bearer {_OTHER_TOKEN if foreign else _TOKEN}"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "EXTERNAL_RECONSTRUCTION_NOT_FOUND"}


def test_context_requires_authentication(tmp_path: Path) -> None:
    client, _, order_id, _ = _client(tmp_path)
    response = client.get(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-context",
    )
    assert response.status_code == 401
