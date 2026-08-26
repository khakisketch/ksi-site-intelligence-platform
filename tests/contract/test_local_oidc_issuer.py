"""loopback local issuer가 실제 Core OIDC verifier와 호환되는지 검증한다."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig

_ROOT = Path(__file__).resolve().parents[2]


def _load_issuer_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_local_oidc_issuer", _ROOT / "tools" / "run_local_oidc_issuer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


def _client(tmp_path: Path) -> tuple[TestClient, Any, str]:
    module = _load_issuer_module()
    secret = "s" * 48
    secret_file = tmp_path / "client.secret"
    secret_file.write_text(secret, encoding="utf-8")
    config = module.LocalOidcConfig(
        issuer="http://127.0.0.1:9010",
        dashboard_origin="http://127.0.0.1:3210",
        client_id="ksi-operations-console",
        client_secret_file=secret_file,
        key_file=tmp_path / "issuer-rsa.private.pem",
    )
    return TestClient(module.build_local_oidc_app(config)), module, secret


def _authorize_and_exchange(
    client: TestClient,
    secret: str,
    *,
    redirect_uri: str = "http://127.0.0.1:3210/api/auth/callback/ksi-oidc",
) -> dict[str, object]:
    verifier = "v" * 43
    params = {
        "response_type": "code",
        "client_id": "ksi-operations-console",
        "redirect_uri": redirect_uri,
        "scope": "openid profile offline_access",
        "state": "state-for-test",
        "nonce": "nonce-for-test",
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
    }
    selection = client.get("/authorize", params=params)
    assert selection.status_code == 200
    assert "KSI 로컬 인증 테스트" in selection.text
    assert "기본 개발 계정으로 계속" in selection.text
    assert "권한별 화면 테스트(선택)" in selection.text
    assert 'value="local-admin"' in selection.text
    assert "KSI 개발 현장 운영자" in selection.text
    assert "KSI 빈 조직 관리자" in selection.text
    assert "KSI 개발 열람자" in selection.text
    completed = client.post(
        "/authorize", data={**params, "account": "local-field-operator"}, follow_redirects=False
    )
    assert completed.status_code == 302
    query = parse_qs(urlparse(completed.headers["location"]).query)
    code = query["code"][0]
    assert query["state"] == ["state-for-test"]
    basic = base64.b64encode(f"ksi-operations-console:{secret}".encode("ascii")).decode("ascii")
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": params["redirect_uri"],
            "code_verifier": verifier,
        },
        headers={"Authorization": f"Basic {basic}"},
    )
    assert token.status_code == 200
    return {"payload": token.json(), "code": code, "basic": basic, "verifier": verifier}


def test_local_oidc_authorization_code_pkce_token_is_accepted_by_core(tmp_path: Path) -> None:
    client, module, secret = _client(tmp_path)
    result = _authorize_and_exchange(client, secret)
    payload = result["payload"]
    assert isinstance(payload, dict)
    access_token = payload["access_token"]
    assert isinstance(access_token, str)

    oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(
            issuer="http://127.0.0.1:9010",
            audience="ksi-core",
            jwks_url="http://127.0.0.1:9010/jwks.json",
        ),
        fetch_jwks=lambda: client.get("/jwks.json").json(),
    )
    principal = oidc_verifier.verify(access_token)
    assert principal is not None
    assert principal.principal_id == "local-field-operator"
    assert principal.organization_id == "org-local-pilot"
    assert principal.role is not None and principal.role.value == "FIELD_OPERATOR"

    userinfo = client.get("/userinfo", headers={"Authorization": f"Bearer {access_token}"})
    assert userinfo.status_code == 200
    assert userinfo.json() == {
        "sub": "local-field-operator",
        "name": "KSI 개발 현장 운영자",
        "preferred_username": "local-field-operator",
    }
    assert client.get("/userinfo").status_code == 401

    refresh = client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": payload["refresh_token"]},
        headers={"Authorization": f"Basic {result['basic']}"},
    )
    assert refresh.status_code == 200
    assert oidc_verifier.verify(refresh.json()["access_token"]) is not None
    del module


def test_local_oidc_refresh_grant_survives_restart_without_persisting_bearer_token(
    tmp_path: Path,
) -> None:
    client, module, secret = _client(tmp_path)
    result = _authorize_and_exchange(client, secret)
    payload = result["payload"]
    assert isinstance(payload, dict)
    refresh_token = payload["refresh_token"]
    assert isinstance(refresh_token, str)

    state_file = tmp_path / "local-oidc-refresh-grants.json"
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert refresh_token not in state_file.read_text(encoding="utf-8")
    assert hashlib.sha256(refresh_token.encode("utf-8")).hexdigest() in persisted["grants"]
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600

    restarted = TestClient(
        module.build_local_oidc_app(
            module.LocalOidcConfig(
                issuer="http://127.0.0.1:9010",
                dashboard_origin="http://127.0.0.1:3210",
                client_id="ksi-operations-console",
                client_secret_file=tmp_path / "client.secret",
                key_file=tmp_path / "issuer-rsa.private.pem",
            )
        )
    )
    refreshed = restarted.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers={"Authorization": f"Basic {result['basic']}"},
    )
    assert refreshed.status_code == 200
    rotated = refreshed.json()["refresh_token"]
    assert isinstance(rotated, str) and rotated != refresh_token

    replay = restarted.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers={"Authorization": f"Basic {result['basic']}"},
    )
    assert replay.status_code == 400

    restarted_again = TestClient(
        module.build_local_oidc_app(
            module.LocalOidcConfig(
                issuer="http://127.0.0.1:9010",
                dashboard_origin="http://127.0.0.1:3210",
                client_id="ksi-operations-console",
                client_secret_file=tmp_path / "client.secret",
                key_file=tmp_path / "issuer-rsa.private.pem",
            )
        )
    )
    assert (
        restarted_again.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": rotated},
            headers={"Authorization": f"Basic {result['basic']}"},
        ).status_code
        == 200
    )


def test_local_oidc_default_hint_auto_authorizes_but_rbac_prompt_stays_explicit(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    verifier = "b" * 43
    params = {
        "response_type": "code",
        "client_id": "ksi-operations-console",
        "redirect_uri": "http://127.0.0.1:3210/api/auth/callback/ksi-oidc",
        "scope": "openid profile offline_access",
        "state": "state-for-default-test",
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
    }
    automatic = client.get(
        "/authorize",
        params={**params, "login_hint": "local-admin"},
        follow_redirects=False,
    )
    assert automatic.status_code == 302
    assert parse_qs(urlparse(automatic.headers["location"]).query)["state"] == [
        "state-for-default-test"
    ]

    selector = client.get(
        "/authorize",
        params={**params, "login_hint": "local-admin", "prompt": "select_account"},
    )
    assert selector.status_code == 200
    assert "권한별 화면 테스트(선택)" in selector.text
    assert "KSI 개발 현장 운영자" in selector.text


def test_local_oidc_accepts_only_loopback_aliases_for_the_registered_callback(
    tmp_path: Path,
) -> None:
    client, _, secret = _client(tmp_path)
    result = _authorize_and_exchange(
        client,
        secret,
        redirect_uri="http://localhost:3210/api/auth/callback/ksi-oidc",
    )
    assert isinstance(result["payload"], dict)


def test_local_oidc_rejects_wrong_pkce_verifier_and_reused_authorization_code(
    tmp_path: Path,
) -> None:
    client, _, secret = _client(tmp_path)
    verifier = "a" * 43
    params = {
        "response_type": "code",
        "client_id": "ksi-operations-console",
        "redirect_uri": "http://127.0.0.1:3210/api/auth/callback/ksi-oidc",
        "scope": "openid profile offline_access",
        "state": "state-for-test",
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
    }
    completed = client.post(
        "/authorize", data={**params, "account": "local-admin"}, follow_redirects=False
    )
    code = parse_qs(urlparse(completed.headers["location"]).query)["code"][0]
    basic = base64.b64encode(f"ksi-operations-console:{secret}".encode("ascii")).decode("ascii")
    request = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": params["redirect_uri"],
        "code_verifier": "wrong" * 11,
    }
    wrong = client.post("/token", data=request, headers={"Authorization": f"Basic {basic}"})
    assert wrong.status_code == 400
    retry = client.post(
        "/token",
        data={**request, "code_verifier": verifier},
        headers={"Authorization": f"Basic {basic}"},
    )
    assert retry.status_code == 400


def test_local_oidc_refuses_non_loopback_configuration(tmp_path: Path) -> None:
    module = _load_issuer_module()
    secret_file = tmp_path / "client.secret"
    secret_file.write_text("s" * 48, encoding="utf-8")
    with pytest.raises(ValueError, match="loopback"):
        module.LocalOidcConfig(
            issuer="https://identity.example.com",
            dashboard_origin="http://127.0.0.1:3210",
            client_id="dashboard",
            client_secret_file=secret_file,
            key_file=tmp_path / "key.pem",
        )


def test_local_oidc_accepts_only_same_node_tailnet_serve_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    module = _load_issuer_module()
    secret_file = tmp_path / "client.secret"
    secret_file.write_text("s" * 48, encoding="utf-8")
    config = module.LocalOidcConfig(
        issuer="http://dev-node.example-tailnet.ts.net:9010",
        dashboard_origin="http://dev-node.example-tailnet.ts.net:3210",
        client_id="dashboard",
        client_secret_file=secret_file,
        key_file=tmp_path / "key.pem",
        allow_tailnet_origins=True,
    )

    assert config.is_registered_redirect_uri(
        "http://dev-node.example-tailnet.ts.net:3210/api/auth/callback/ksi-oidc"
    )
    assert not config.is_registered_redirect_uri(
        "http://other-node.example-tailnet.ts.net:3210/api/auth/callback/ksi-oidc"
    )

    with pytest.raises(ValueError, match="같은 장비"):
        module.LocalOidcConfig(
            issuer="http://identity.example-tailnet.ts.net:9010",
            dashboard_origin="http://dashboard.example-tailnet.ts.net:3210",
            client_id="dashboard",
            client_secret_file=secret_file,
            key_file=tmp_path / "other-key.pem",
            allow_tailnet_origins=True,
        )

    with pytest.raises(ValueError, match="Tailnet Serve"):
        module.LocalOidcConfig(
            issuer="http://attacker.example.com:9010",
            dashboard_origin="http://attacker.example.com:3210",
            client_id="dashboard",
            client_secret_file=secret_file,
            key_file=tmp_path / "insecure-key.pem",
            allow_tailnet_origins=True,
        )
