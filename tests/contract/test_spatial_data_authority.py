"""Distinct signed activation and fresh credential identity, not production provisioning."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from ksi_core.auth import AuthRegistry, HumanAuthMode, PrincipalTokenRecord
from ksi_domain.canonical_json import canonical_json_bytes
from spatial_data_fixture import NOW, make_activation, make_policy, make_runtime
from starlette.requests import Request
from test_spatial_data_permissions import data_client

TOKEN = "ephemeral-data-credential"  # noqa: S105 -- local test, never provisioned


def material() -> Any:
    key = Ed25519PrivateKey.generate()
    activation = make_activation()
    return dict(
        payload=activation,
        signature=key.sign(activation.signing_bytes()),
        trusted_public_key=key.public_key().public_bytes_raw(),
        policy=make_policy(),
        runtime=make_runtime(),
        now=NOW,
    )


def test_distinct_activation_requires_real_domain_signature_and_detached_snapshot() -> None:
    """Digest-only validation could accept an unsigned or Analysis-domain runtime activation."""
    from ksi_core.domains.external.delivery.activation import verify_spatial_data_activation

    arguments = material()
    accepted = verify_spatial_data_activation(**arguments)
    assert accepted == arguments["payload"]
    object.__setattr__(accepted, "activation_id", "caller-mutated")
    assert verify_spatial_data_activation(**arguments).activation_id == "local-activation"


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "key",
        "domain",
        "organization",
        "policy",
        "runtime",
        "expiry",
        "unsealed",
        "short-key",
        "short-signature",
    ],
)
def test_distinct_activation_refuses_each_negative_binding(change: str) -> None:
    """Signing/digest/validity substitutions cannot enable a usable data-worker activation."""
    from ksi_core.domains.external.delivery.activation import (
        SpatialDataActivationVerificationError,
        verify_spatial_data_activation,
    )

    arguments = material()
    activation = arguments["payload"]
    if change == "signature":
        arguments["signature"] = b"f" * 64
    elif change == "key":
        arguments["trusted_public_key"] = (
            Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        )
    elif change == "domain":
        key = Ed25519PrivateKey.generate()
        arguments["trusted_public_key"] = key.public_key().public_bytes_raw()
        arguments["signature"] = key.sign(
            canonical_json_bytes(
                {
                    "domain": "ksi-analysis-activation.v1",
                    "payload": activation.model_dump(by_alias=True, mode="json"),
                }
            )
        )
    elif change == "organization":
        arguments["payload"] = activation.model_copy(
            update={"organization_id": "other-org", "activation_digest": None}
        ).sealed()
    elif change == "policy":
        arguments["policy"] = make_policy(revision=2)
    elif change == "runtime":
        arguments["runtime"] = make_runtime(build_digest="sha256:" + "f" * 64)
    elif change == "expiry":
        arguments["now"] = activation.valid_until
    elif change == "unsealed":
        arguments["payload"] = activation.model_copy(update={"activation_digest": None})
    elif change == "short-key":
        arguments["trusted_public_key"] = b"f"
    elif change == "short-signature":
        arguments["signature"] = b"f"
    with pytest.raises(SpatialDataActivationVerificationError):
        verify_spatial_data_activation(**arguments)


def credential_request(principal: Any = None, *, until: Any = None) -> Any:
    app = FastAPI()
    principal = principal or data_client()
    app.state.auth_registry = AuthRegistry(
        [PrincipalTokenRecord(sha256(TOKEN.encode()).hexdigest(), principal, not_after=until)]
    )
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})


def credential(request: Any) -> Any:
    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )

    return SpatialDataCredentialCurrentness(
        request, TOKEN, expected_principal_id="reader-local", expected_organization_id="org-local"
    )


def test_credential_resolution_reads_new_registry_scope_and_expiry_each_time() -> None:
    """Caching the initial Principal/token record would miss scope withdrawal and token expiry."""
    request = credential_request(until=NOW + timedelta(seconds=1))
    refreshed = credential(request)
    assert refreshed.resolve(now=NOW) == data_client()
    changed = replace(data_client(), allowed_site_ids=frozenset({"other-site"}))
    request.app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                sha256(TOKEN.encode()).hexdigest(), changed, not_after=NOW + timedelta(seconds=1)
            )
        ]
    )
    assert refreshed.resolve(now=NOW).allowed_site_ids == frozenset({"other-site"})
    with pytest.raises(HTTPException) as error:
        refreshed.resolve(now=NOW + timedelta(seconds=2))
    assert error.value.status_code == 401 and TOKEN not in str(error.value)
    assert TOKEN not in repr(refreshed)


@pytest.mark.parametrize("change", [{"organization_id": "other"}, {"principal_id": "other"}])
def test_credential_refuses_remapped_identity(change: dict) -> None:
    """The same bearer token may not switch the ownership identity of an in-flight download."""
    request = credential_request()
    refreshed = credential(request)
    principal = replace(data_client(), **change)
    request.app.state.auth_registry = AuthRegistry(
        [PrincipalTokenRecord(sha256(TOKEN.encode()).hexdigest(), principal)]
    )
    with pytest.raises(HTTPException) as error:
        refreshed.resolve(now=NOW)
    assert error.value.status_code == 401


def test_oidc_remapped_scopes_are_refreshed_without_reusing_initial_principal() -> None:
    """OIDC mapping updates must be reflected at every reauthentication, not frozen at headers."""
    from ksi_core.auth import Principal, PrincipalKind, Role

    operator = replace(data_client(), kind=PrincipalKind.OPERATOR, role=Role.FIELD_OPERATOR)
    request = credential_request()
    request.app.state.auth_registry = AuthRegistry([])
    request.app.state.human_auth_mode = HumanAuthMode.OIDC

    class TestVerifier:
        principal: Principal | None = operator

        def verify(self, token: str) -> Any:
            assert token == TOKEN
            return self.principal

    verifier = TestVerifier()
    request.app.state.oidc_verifier = verifier
    refreshed = credential(request)
    assert refreshed.resolve(now=NOW) == operator
    verifier.principal = replace(operator, allowed_work_area_ids=frozenset({"other-area"}))
    assert refreshed.resolve(now=NOW).allowed_work_area_ids == frozenset({"other-area"})
    verifier.principal = None
    with pytest.raises(HTTPException) as error:
        refreshed.resolve(now=NOW)
    assert error.value.status_code == 401
