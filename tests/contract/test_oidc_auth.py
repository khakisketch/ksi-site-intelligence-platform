"""OIDC 사람 JWT와 opaque 장비 자격 분리 계약."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig

_ISSUER = "https://issuer.example.test"
_AUDIENCE = "ksi-core"
_NOW = int(time.time())


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _jwk(key: RSAPrivateKey, kid: str) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    encode = lambda value: jwt.utils.base64url_encode(  # noqa: E731 -- JWK 두 정수 동일 변환
        value.to_bytes((value.bit_length() + 7) // 8, "big")
    ).decode()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": _NOW + 3600,
        "nbf": _NOW - 60,
        "ksi_principal_id": "oidc-user-1",
        "ksi_organization_id": "org-1",
        "ksi_role": "FIELD_OPERATOR",
    }
    claims.update(overrides)
    return claims


def _token(
    key: RSAPrivateKey,
    *,
    kid: str = "key-1",
    claims: dict[str, Any] | None = None,
    algorithm: str = "RS256",
) -> str:
    return jwt.encode(claims or _claims(), key, algorithm=algorithm, headers={"kid": kid})


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("opaque-operator"),
                principal=Principal(
                    principal_id="legacy-op",
                    organization_id="org-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest("gateway-token"),
                principal=Principal(
                    principal_id="gateway-1",
                    organization_id="org-1",
                    kind=PrincipalKind.GATEWAY_DEVICE,
                    role=None,
                    device_id="rc-1",
                ),
            ),
        ]
    )


def _verifier(key: RSAPrivateKey) -> OidcJwtVerifier:
    return OidcJwtVerifier(
        OidcVerifierConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=f"{_ISSUER}/jwks.json",
        ),
        fetch_jwks=lambda: {"keys": [_jwk(key, "key-1")]},
    )


def _client(mode: HumanAuthMode, verifier: OidcJwtVerifier) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry(), human_auth_mode=mode, oidc_verifier=verifier)
    return TestClient(app)


def test_valid_oidc_operator_maps_existing_role_and_permissions() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    response = _client(HumanAuthMode.OIDC, _verifier(key)).get(
        "/v1/auth/whoami", headers={"Authorization": f"Bearer {_token(key)}"}
    )

    assert response.status_code == 200
    assert response.json()["principalId"] == "oidc-user-1"
    assert response.json()["organizationId"] == "org-1"
    assert response.json()["role"] == "FIELD_OPERATOR"
    assert "MISSIONS_ISSUE" in response.json()["permissions"]


def test_openapi_describes_human_jwt_and_device_opaque_bearer_split() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    client = _client(HumanAuthMode.OIDC, _verifier(key))
    scheme = cast(FastAPI, client.app).openapi()["components"]["securitySchemes"][
        "KsiBearer"
    ]
    assert scheme["type"] == "http"
    assert "OIDC operator JWT" in scheme["bearerFormat"]
    assert "GATEWAY_DEVICE" in scheme["description"]


@pytest.mark.parametrize(
    "claims",
    [
        _claims(iss="https://evil.example"),
        _claims(aud="other-api"),
        _claims(exp=_NOW - 60),
        _claims(nbf=_NOW + 3600),
        _claims(ksi_role="UNKNOWN"),
        _claims(ksi_organization_id=""),
        _claims(ksi_principal_id="bad/principal"),
        {key: value for key, value in _claims().items() if key != "ksi_role"},
        {key: value for key, value in _claims().items() if key != "nbf"},
    ],
)
def test_invalid_or_incomplete_oidc_claims_are_uniform_401(claims: dict[str, Any]) -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    response = _client(HumanAuthMode.OIDC, _verifier(key)).get(
        "/v1/auth/whoami",
        headers={"Authorization": f"Bearer {_token(key, claims=claims)}"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_tampered_signature_and_unknown_algorithm_are_401() -> None:
    trusted = generate_private_key(public_exponent=65537, key_size=2048)
    attacker = generate_private_key(public_exponent=65537, key_size=2048)
    client = _client(HumanAuthMode.OIDC, _verifier(trusted))

    forged = _token(attacker, kid="key-1")
    assert client.get(
        "/v1/auth/whoami", headers={"Authorization": f"Bearer {forged}"}
    ).status_code == 401

    unsupported_algorithm = jwt.encode(
        _claims(),
        "test-only-shared-secret-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "key-1"},
    )
    assert client.get(
        "/v1/auth/whoami",
        headers={"Authorization": f"Bearer {unsupported_algorithm}"},
    ).status_code == 401


def test_oidc_mode_rejects_opaque_human_but_keeps_device_credential() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    client = _client(HumanAuthMode.OIDC, _verifier(key))

    operator = client.get(
        "/v1/auth/whoami", headers={"Authorization": "Bearer opaque-operator"}
    )
    gateway = client.get(
        "/v1/auth/whoami", headers={"Authorization": "Bearer gateway-token"}
    )
    assert operator.status_code == 401
    assert gateway.status_code == 200
    assert gateway.json()["kind"] == "GATEWAY_DEVICE"


def test_dual_mode_accepts_oidc_and_opaque_operator_for_migration() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    client = _client(HumanAuthMode.DUAL, _verifier(key))
    assert client.get(
        "/v1/auth/whoami", headers={"Authorization": "Bearer opaque-operator"}
    ).status_code == 200
    assert client.get(
        "/v1/auth/whoami", headers={"Authorization": f"Bearer {_token(key)}"}
    ).status_code == 200


def test_unknown_kid_refreshes_jwks_once() -> None:
    old_key = generate_private_key(public_exponent=65537, key_size=2048)
    new_key = generate_private_key(public_exponent=65537, key_size=2048)
    payloads = iter(
        [
            {"keys": [_jwk(old_key, "old")]},
            {"keys": [_jwk(old_key, "old"), _jwk(new_key, "new")]},
        ]
    )
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return next(payloads)

    verifier = OidcJwtVerifier(
        OidcVerifierConfig(_ISSUER, _AUDIENCE, f"{_ISSUER}/jwks.json"),
        fetch_jwks=fetch,
    )
    assert verifier.verify(_token(old_key, kid="old")) is not None
    assert verifier.verify(_token(new_key, kid="new")) is not None
    assert calls == 2


def test_expired_jwks_cache_and_issuer_failure_is_fail_closed() -> None:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    clock = [0.0]
    def available() -> dict[str, Any]:
        return {"keys": [_jwk(key, "key-1")]}

    fetch: Callable[[], dict[str, Any]] = available
    verifier = OidcJwtVerifier(
        OidcVerifierConfig(
            _ISSUER, _AUDIENCE, f"{_ISSUER}/jwks.json", jwks_ttl_seconds=1
        ),
        fetch_jwks=lambda: fetch(),
        monotonic=lambda: clock[0],
    )
    token = _token(key)
    assert verifier.verify(token) is not None

    def unavailable() -> dict[str, Any]:
        raise OSError("issuer unavailable")

    fetch = unavailable
    clock[0] = 2.0
    assert verifier.verify(token) is None
