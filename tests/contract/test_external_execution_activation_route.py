"""Authenticated issue intent is the only source of an execution principal."""

from pathlib import Path
from typing import Any

import pytest
from test_external_relative_volumes import (
    _NOW,
    _OPERATOR_TOKEN,
    _WORKER_TOKEN,
    _authority,
    _client,
    _headers,
    _principal,
)


def test_issue_activates_with_authenticated_principal_but_retry_does_not(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    available = False

    def activate(**context: Any) -> Any:
        nonlocal available
        available = True
        calls.append(context)
        return _authority()

    client, work_order_id = _client(
        tmp_path, _authority(), execution_activator=activate,
        authority_availability=lambda: available,
    )
    url = f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests"
    headers = _headers(_OPERATOR_TOKEN, idempotency_key="activation-request")
    with client:
        first = client.post(url, headers=headers, json={"decisionRef": "decision-a"})
        assert first.status_code == 201, first.text
        repeated = client.post(url, headers=headers, json={"decisionRef": "decision-a"})
        assert repeated.status_code == 200, repeated.text
    assert calls == [{
        "principal": _principal(), "current_work_order_id": work_order_id,
        "decision_ref": "decision-a", "now": _NOW,
    }]


def test_failed_activation_cannot_issue_from_an_unavailable_authority(tmp_path: Path) -> None:
    client, work_order_id = _client(
        tmp_path, _authority(), execution_activator=lambda **_kwargs: None,
        authority_availability=lambda: False,
    )
    with client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            headers=_headers(_OPERATOR_TOKEN, idempotency_key="activation-denied"),
            json={"decisionRef": "decision-a"},
        )
    assert response.json()["verdict"] == "AUTHORITY_UNAVAILABLE"
    assert response.json()["request"] is None


@pytest.mark.parametrize("mode", ["conflict", "natural_duplicate"])
def test_retained_issue_is_classified_before_execution_activation(
    tmp_path: Path, mode: str
) -> None:
    calls: list[dict[str, Any]] = []

    def activate(**context: Any) -> Any:
        calls.append(context)
        return _authority()

    client, work_order_id = _client(tmp_path, _authority(), execution_activator=activate)
    url = f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests"
    with client:
        first = client.post(url, headers=_headers(_OPERATOR_TOKEN, idempotency_key="first"),
                            json={"decisionRef": "decision-a"})
        assert first.status_code == 201
        before = list(calls)
        journal = tmp_path / "external-relative-volumes.jsonl"
        before_journal = journal.read_bytes()
        repeated = client.post(
            url,
            headers=_headers(_OPERATOR_TOKEN, idempotency_key=(
                "first" if mode == "conflict" else "another-key"
            )),
            json={"decisionRef": "decision-b" if mode == "conflict" else "decision-a"},
        )
        assert repeated.status_code == (409 if mode == "conflict" else 200)
        assert calls == before
        if mode == "conflict":
            assert journal.read_bytes() == before_journal
        else:
            assert journal.read_bytes().startswith(before_journal)
            assert b"external-relative-volume-idempotency-bound" in journal.read_bytes()
            after_binding = journal.read_bytes()
            exact_retry = client.post(
                url, headers=_headers(_OPERATOR_TOKEN, idempotency_key="another-key"),
                json={"decisionRef": "decision-a"},
            )
            assert exact_retry.status_code == 200
            assert journal.read_bytes() == after_binding
            assert calls == before


def test_current_execution_authority_needs_no_activation(tmp_path: Path) -> None:
    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("current execution authority was activated again")

    client, work_order_id = _client(tmp_path, _authority(), execution_activator=forbidden)
    with client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            headers=_headers(_OPERATOR_TOKEN, idempotency_key="already-active"),
            json={"decisionRef": "decision-a"},
        )
    assert response.status_code == 201


def test_activator_return_cannot_replace_the_authority_port(tmp_path: Path) -> None:
    client, work_order_id = _client(
        tmp_path, _authority(), execution_activator=lambda **_kwargs: _authority(),
        authority_availability=lambda: False,
    )
    with client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            headers=_headers(_OPERATOR_TOKEN, idempotency_key="uninstalled"),
            json={"decisionRef": "decision-a"},
        )
    assert response.json()["verdict"] == "AUTHORITY_UNAVAILABLE"


def test_authority_withdrawal_after_classification_cannot_issue(tmp_path: Path) -> None:
    reads = 0

    def availability() -> bool:
        nonlocal reads
        reads += 1
        return reads == 1

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("authority was reactivated after classification")

    client, work_order_id = _client(
        tmp_path, _authority(), execution_activator=forbidden,
        authority_availability=availability,
    )
    journal = tmp_path / "external-relative-volumes.jsonl"
    assert not journal.exists()
    with client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            headers=_headers(_OPERATOR_TOKEN, idempotency_key="withdrawn"),
            json={"decisionRef": "decision-a"},
        )
    assert response.json()["verdict"] == "AUTHORITY_UNAVAILABLE"
    assert not journal.exists()


@pytest.mark.parametrize("mode", ["worker", "missing_key", "foreign_work_order"])
def test_invalid_issue_never_activates_execution(tmp_path: Path, mode: str) -> None:
    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("unauthorized or invalid intent reached activation")

    client, work_order_id = _client(tmp_path, _authority(), execution_activator=forbidden)
    token = _WORKER_TOKEN if mode == "worker" else _OPERATOR_TOKEN
    if mode == "foreign_work_order":
        work_order_id = "missing-work-order"
    with client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            headers=_headers(token, idempotency_key=None if mode == "missing_key" else "key"),
            json={"decisionRef": "decision-a"},
        )
    assert response.status_code in {403, 404, 422}
