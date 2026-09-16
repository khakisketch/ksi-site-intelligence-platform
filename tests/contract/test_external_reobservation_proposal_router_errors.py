"""Proposal routes map an unavailable source to 409, never to a 500."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.external_reobservation_proposals import (
    ExternalReobservationProposalUnavailableError,
    build_external_reobservation_proposal_router,
)

_TOKEN = "token-router-errors"


def _unavailable(**_kwargs: Any) -> None:
    raise ExternalReobservationProposalUnavailableError("EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")


def _client() -> TestClient:
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_TOKEN.encode()).hexdigest(),
                    principal=Principal(
                        principal_id="operator-a",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                        organization_id="org-a",
                    ),
                )
            ]
        ),
    )
    service = SimpleNamespace(create=_unavailable, approve=_unavailable)
    app.include_router(
        build_external_reobservation_proposal_router(
            service,  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 9, 17, tzinfo=UTC),
        )
    )
    return TestClient(app)


def test_unavailable_source_is_a_409_on_create_and_approve() -> None:
    client = _client()
    headers = {"Authorization": f"Bearer {_TOKEN}", "Idempotency-Key": "k-1"}
    created = client.post(
        "/v1/external-reobservation-proposals",
        headers=headers,
        json={"reportRef": "report-1", "targetWorkAreaIds": ["area-1"]},
    )
    assert created.status_code == 409, created.text
    assert created.json()["detail"] == "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"
    approved = client.post(
        "/v1/external-reobservation-proposals/approve",
        headers=headers,
        json={"proposalRef": "erop-v1-" + "a" * 64, "expectedVersion": 1},
    )
    assert approved.status_code == 409, approved.text
