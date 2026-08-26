#!/usr/bin/env python3
"""KSI 개발 전용 OIDC issuer.

이 모듈은 외부 IdP가 아직 선정되지 않은 개발 환경에서만 쓴다. Dashboard가 상용과
동일한 Authorization Code + PKCE 흐름을 실제로 수행하고, Core가 실제 JWKS 서명과
KSI organization/role claims를 검증하게 만드는 최소 OIDC issuer다. production image,
compose, import graph에는 이 모듈을 넣지 않는다.

이것은 사람 계정 시스템이나 상용 IdP가 아니다. 프로세스는 항상 loopback에만 bind하고,
표준 개발 명령은 필요할 때 WireGuard 터널 안의 Tailnet 전용 Tailscale Serve origin을
앞에 둔다. 화면에는 합성 개발 계정만 표시한다. 외부 VM에서는 승인된 IdP의 HTTPS
issuer를 사용해야 한다.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

_CODE_TTL_SECONDS = 120
_REFRESH_TTL_SECONDS = 8 * 60 * 60
_ACCESS_TTL_SECONDS = 5 * 60
_REFRESH_GRANTS_SCHEMA_VERSION = 1
_DEVELOPMENT_ACCOUNTS: tuple[dict[str, str], ...] = (
    {
        "principal_id": "local-admin",
        "organization_id": "org-local-pilot",
        "role": "ADMIN",
        "label": "KSI 개발 관리자",
        "description": "Site·Mission·승인까지 전체 운영 권한을 점검합니다.",
    },
    {
        "principal_id": "local-field-operator",
        "organization_id": "org-local-pilot",
        "role": "FIELD_OPERATOR",
        "label": "KSI 개발 현장 운영자",
        "description": "현장 작업·이벤트·Mission 준비 권한을 점검합니다.",
    },
    {
        "principal_id": "local-viewer",
        "organization_id": "org-local-pilot",
        "role": "VIEWER",
        "label": "KSI 개발 열람자",
        "description": "조직 격리와 읽기 전용 화면을 점검합니다.",
    },
    {
        "principal_id": "local-empty-org-admin",
        "organization_id": "org-local-empty",
        "role": "ADMIN",
        "label": "KSI 빈 조직 관리자",
        "description": "조직 격리와 0건 상태의 다음 행동을 점검합니다.",
    },
)
_DEFAULT_DEVELOPMENT_ACCOUNT = _DEVELOPMENT_ACCOUNTS[0]


def _development_origin(value: str, *, name: str, allow_tailnet: bool) -> str:
    """개발 origin을 loopback 또는 명시적으로 허용된 Tailnet Serve로 제한한다."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name}은 http(s) origin이어야 한다")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{name}은 path/query 없는 origin이어야 한다")
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost", "::1"} and (
        not allow_tailnet
        or not host
        or not host.endswith(".ts.net")
    ):
        raise ValueError(f"{name}은 loopback 또는 허용된 Tailnet Serve host여야 한다")
    return parsed.geturl().rstrip("/")


def _read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"OIDC client secret 파일을 읽을 수 없다: {path}") from exc
    if len(value) < 32:
        raise ValueError("OIDC client secret은 최소 32자여야 한다")
    return value


def _load_or_create_key(path: Path) -> RSAPrivateKey:
    if path.exists():
        try:
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"로컬 OIDC 서명키를 읽을 수 없다: {path}") from exc
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("로컬 OIDC 서명키는 RSA private key여야 한다")
        return key

    path.parent.mkdir(parents=True, exist_ok=True)
    key = generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    path.chmod(0o600)
    return key


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwk(key: RSAPrivateKey, kid: str) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _form_value(values: dict[str, list[str]], name: str) -> str | None:
    value = values.get(name)
    return value[0] if value and len(value) == 1 else None


async def _urlencoded_form(request: Request) -> dict[str, list[str]]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        return {}
    from urllib.parse import parse_qs

    return parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)


@dataclass(frozen=True, slots=True)
class LocalOidcConfig:
    issuer: str
    dashboard_origin: str
    client_id: str
    client_secret_file: Path
    key_file: Path
    refresh_grants_file: Path | None = None
    core_audience: str = "ksi-core"
    allow_tailnet_origins: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "issuer",
            _development_origin(
                self.issuer,
                name="issuer",
                allow_tailnet=self.allow_tailnet_origins,
            ),
        )
        object.__setattr__(
            self,
            "dashboard_origin",
            _development_origin(
                self.dashboard_origin,
                name="dashboard origin",
                allow_tailnet=self.allow_tailnet_origins,
            ),
        )
        issuer_host = urlparse(self.issuer).hostname
        dashboard_host = urlparse(self.dashboard_origin).hostname
        if (
            issuer_host not in {"127.0.0.1", "localhost", "::1"}
            and issuer_host != dashboard_host
        ):
            raise ValueError(
                "Tailnet issuer와 Dashboard는 같은 장비의 MagicDNS host를 사용해야 한다"
            )
        if not self.client_id:
            raise ValueError("client_id는 비어 있을 수 없다")
        if not self.core_audience:
            raise ValueError("core audience는 비어 있을 수 없다")
        if self.refresh_grants_file is None:
            object.__setattr__(
                self,
                "refresh_grants_file",
                self.key_file.with_name("local-oidc-refresh-grants.json"),
            )

    @property
    def redirect_uri(self) -> str:
        return f"{self.dashboard_origin}/api/auth/callback/ksi-oidc"

    def is_registered_redirect_uri(self, candidate: str | None) -> bool:
        """127.0.0.1과 localhost alias만 같은 loopback callback으로 취급한다.

        in-app browser와 Auth.js가 loopback origin을 서로 다른 alias로 정규화할 수
        있다. production issuer에서는 exact redirect URI를 쓰며, 이 예외는 개발
        전용 issuer에서만 port·path까지 고정한 뒤 적용한다.
        """
        if not candidate:
            return False
        actual = urlparse(candidate)
        expected = urlparse(self.redirect_uri)
        expected_is_loopback = expected.hostname in {"127.0.0.1", "localhost", "::1"}
        allowed_hosts = (
            {"127.0.0.1", "localhost", "::1"}
            if expected_is_loopback
            else {expected.hostname}
        )
        return (
            actual.scheme == expected.scheme
            and actual.hostname in allowed_hosts
            and actual.port == expected.port
            and actual.path == expected.path
            and not actual.params
            and not actual.query
            and not actual.fragment
        )


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    client_id: str
    redirect_uri: str
    code_challenge: str
    account: dict[str, str]
    scope: frozenset[str]
    nonce: str | None
    expires_at: int


@dataclass(frozen=True, slots=True)
class RefreshGrant:
    account: dict[str, str]
    scope: frozenset[str]
    expires_at: int


def _known_development_account(principal_id: object) -> dict[str, str] | None:
    if not isinstance(principal_id, str):
        return None
    return next(
        (
            account
            for account in _DEVELOPMENT_ACCOUNTS
            if account["principal_id"] == principal_id
        ),
        None,
    )


def _refresh_token_digest(refresh_token: str) -> str:
    """Persist only a verifier for an opaque bearer refresh token.

    The Local Identity process never needs the token value after it has been
    returned once.  A SHA-256 verifier is sufficient because the token is
    generated from high-entropy ``secrets.token_urlsafe`` output.
    """

    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _load_refresh_grants(path: Path) -> dict[str, RefreshGrant]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"local OIDC refresh grant 상태를 읽을 수 없다: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _REFRESH_GRANTS_SCHEMA_VERSION
    ):
        raise ValueError("local OIDC refresh grant 상태 schema가 올바르지 않다")
    records = payload.get("grants")
    if not isinstance(records, dict):
        raise ValueError("local OIDC refresh grant 상태의 grants가 올바르지 않다")

    grants: dict[str, RefreshGrant] = {}
    for token_digest, raw_grant in records.items():
        if (
            not isinstance(token_digest, str)
            or len(token_digest) != 64
            or token_digest.lower() != token_digest
            or any(character not in "0123456789abcdef" for character in token_digest)
            or not isinstance(raw_grant, dict)
        ):
            raise ValueError("local OIDC refresh grant 레코드가 올바르지 않다")
        account = _known_development_account(raw_grant.get("principal_id"))
        scope = raw_grant.get("scope")
        expires_at = raw_grant.get("expires_at")
        if (
            account is None
            or not isinstance(scope, list)
            or not scope
            or any(not isinstance(item, str) or not item for item in scope)
            or type(expires_at) is not int
            or expires_at <= 0
        ):
            raise ValueError("local OIDC refresh grant 내용이 올바르지 않다")
        grants[token_digest] = RefreshGrant(
            account=account,
            scope=frozenset(scope),
            expires_at=expires_at,
        )
    return grants


class LocalOidcIssuer:
    def __init__(self, config: LocalOidcConfig) -> None:
        self.config = config
        self._client_secret = _read_secret(config.client_secret_file)
        self._key = _load_or_create_key(config.key_file)
        self._kid = "local-dev-rsa-1"
        self._authorization_codes: dict[str, AuthorizationGrant] = {}
        # Authorization codes intentionally remain in memory: they are short-lived
        # and a process restart must force a new PKCE authorization request.  Refresh
        # grants instead belong to the eight-hour Dashboard session and therefore
        # survive a local stack restart without storing the bearer token itself.
        assert config.refresh_grants_file is not None
        self._refresh_tokens = _load_refresh_grants(config.refresh_grants_file)
        self._prune()

    def _now(self) -> int:
        return int(time.time())

    def _prune(self) -> None:
        now = self._now()
        self._authorization_codes = {
            code: grant
            for code, grant in self._authorization_codes.items()
            if grant.expires_at > now
        }
        refreshed = {
            token: grant for token, grant in self._refresh_tokens.items() if grant.expires_at > now
        }
        if refreshed != self._refresh_tokens:
            self._refresh_tokens = refreshed
            self._persist_refresh_grants()

    def _persist_refresh_grants(self) -> None:
        """Atomically store hashed refresh-grant metadata with owner-only mode."""

        assert self.config.refresh_grants_file is not None
        path = self.config.refresh_grants_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _REFRESH_GRANTS_SCHEMA_VERSION,
            "grants": {
                token_digest: {
                    "principal_id": grant.account["principal_id"],
                    "scope": sorted(grant.scope),
                    "expires_at": grant.expires_at,
                }
                for token_digest, grant in sorted(self._refresh_tokens.items())
            },
        }
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def _mint_access_token(self, account: dict[str, str], scope: frozenset[str]) -> str:
        now = self._now()
        claims: dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.core_audience,
            "sub": account["principal_id"],
            "iat": now,
            "nbf": now - 1,
            "exp": now + _ACCESS_TTL_SECONDS,
            "scope": " ".join(sorted(scope)),
            "ksi_principal_id": account["principal_id"],
            "ksi_organization_id": account["organization_id"],
            "ksi_role": account["role"],
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self._kid})

    def _mint_id_token(self, account: dict[str, str], nonce: str | None) -> str:
        now = self._now()
        claims: dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.client_id,
            "sub": account["principal_id"],
            "iat": now,
            "nbf": now - 1,
            "exp": now + _ACCESS_TTL_SECONDS,
            "name": account["label"],
            "preferred_username": account["principal_id"],
        }
        if nonce:
            claims["nonce"] = nonce
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self._kid})

    def _tokens_for(self, grant: AuthorizationGrant) -> dict[str, Any]:
        refresh_token = secrets.token_urlsafe(48)
        self._refresh_tokens[_refresh_token_digest(refresh_token)] = RefreshGrant(
            account=grant.account,
            scope=grant.scope,
            expires_at=self._now() + _REFRESH_TTL_SECONDS,
        )
        self._persist_refresh_grants()
        return {
            "access_token": self._mint_access_token(grant.account, grant.scope),
            "token_type": "Bearer",
            "expires_in": _ACCESS_TTL_SECONDS,
            "refresh_token": refresh_token,
            "id_token": self._mint_id_token(grant.account, grant.nonce),
            "scope": " ".join(sorted(grant.scope)),
        }

    def _client_authenticated(self, request: Request, form: dict[str, list[str]]) -> bool:
        client_id = _form_value(form, "client_id")
        client_secret = _form_value(form, "client_secret")
        authorization = request.headers.get("authorization")
        if authorization:
            scheme, _, encoded = authorization.partition(" ")
            if scheme.lower() != "basic" or not encoded:
                return False
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return False
            client_id, separator, client_secret = decoded.partition(":")
            if not separator:
                return False
        return bool(
            client_id == self.config.client_id
            and client_secret
            and hmac.compare_digest(client_secret, self._client_secret)
        )

    def authorization_request_valid(self, values: dict[str, str]) -> bool:
        return (
            values.get("response_type") == "code"
            and values.get("client_id") == self.config.client_id
            and self.config.is_registered_redirect_uri(values.get("redirect_uri"))
            and values.get("code_challenge_method") == "S256"
            and bool(values.get("code_challenge"))
            and bool(values.get("state"))
            and "openid" in set(values.get("scope", "").split())
        )

    def complete_authorization(self, values: dict[str, str]) -> RedirectResponse | HTMLResponse:
        if not self.authorization_request_valid(values):
            return _error_page("잘못된 local OIDC authorization 요청입니다.", status_code=400)
        account = _known_development_account(values.get("account"))
        if account is None:
            return _error_page("선택한 개발 계정이 없습니다.", status_code=400)
        self._prune()
        code = secrets.token_urlsafe(40)
        self._authorization_codes[code] = AuthorizationGrant(
            client_id=self.config.client_id,
            redirect_uri=values["redirect_uri"],
            code_challenge=values["code_challenge"],
            account=account,
            scope=frozenset(values["scope"].split()),
            nonce=values.get("nonce") or None,
            expires_at=self._now() + _CODE_TTL_SECONDS,
        )
        target = f"{values['redirect_uri']}?{urlencode({'code': code, 'state': values['state']})}"
        return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})

    def exchange_code(self, request: Request, form: dict[str, list[str]]) -> JSONResponse:
        if not self._client_authenticated(request, form):
            return _oauth_error("invalid_client", status_code=401)
        if _form_value(form, "grant_type") != "authorization_code":
            return _oauth_error("unsupported_grant_type", status_code=400)
        code = _form_value(form, "code")
        redirect_uri = _form_value(form, "redirect_uri")
        code_verifier = _form_value(form, "code_verifier")
        if not code:
            return _oauth_error(
                "invalid_grant", status_code=400, description="authorization code가 없습니다"
            )
        if not code_verifier:
            return _oauth_error(
                "invalid_grant", status_code=400, description="PKCE code verifier가 없습니다"
            )
        if not self.config.is_registered_redirect_uri(redirect_uri):
            return _oauth_error(
                "invalid_grant",
                status_code=400,
                description="등록된 redirect URI가 일치하지 않습니다",
            )
        self._prune()
        # 코드 1회성은 verifier mismatch도 포함해 fail-closed로 소비한다.
        grant = self._authorization_codes.pop(code, None)
        if grant is None or grant.expires_at <= self._now():
            return _oauth_error(
                "invalid_grant",
                status_code=400,
                description="authorization code가 없거나 이미 사용 또는 만료되었습니다",
            )
        actual_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
        if not hmac.compare_digest(actual_challenge, grant.code_challenge):
            return _oauth_error(
                "invalid_grant",
                status_code=400,
                description="PKCE verifier가 authorization request의 challenge와 일치하지 않습니다",
            )
        return JSONResponse(self._tokens_for(grant), headers={"Cache-Control": "no-store"})

    def exchange_refresh_token(self, request: Request, form: dict[str, list[str]]) -> JSONResponse:
        if not self._client_authenticated(request, form):
            return _oauth_error("invalid_client", status_code=401)
        if _form_value(form, "grant_type") != "refresh_token":
            return _oauth_error("unsupported_grant_type", status_code=400)
        refresh_token = _form_value(form, "refresh_token")
        if not refresh_token:
            return _oauth_error("invalid_grant", status_code=400)
        self._prune()
        grant = self._refresh_tokens.pop(_refresh_token_digest(refresh_token), None)
        if grant is None or grant.expires_at <= self._now():
            return _oauth_error("invalid_grant", status_code=400)
        authorization_grant = AuthorizationGrant(
            client_id=self.config.client_id,
            redirect_uri=self.config.redirect_uri,
            code_challenge="",
            account=grant.account,
            scope=grant.scope,
            nonce=None,
            expires_at=self._now(),
        )
        return JSONResponse(
            self._tokens_for(authorization_grant), headers={"Cache-Control": "no-store"}
        )

    def can_auto_authorize_default_account(self, values: dict[str, str]) -> bool:
        """Accept only the Dashboard's LOCAL-only default-account hint.

        This is a development convenience, not a production authentication
        feature.  A manual RBAC test supplies ``prompt=select_account`` and
        therefore always keeps the explicit selector.  The normal OIDC
        authorization code, state, and PKCE checks still run through
        ``complete_authorization``.
        """

        requested_prompts = set(values.get("prompt", "").split())
        return (
            values.get("login_hint") == _DEFAULT_DEVELOPMENT_ACCOUNT["principal_id"]
            and requested_prompts.isdisjoint({"login", "select_account"})
        )

    def userinfo(self, authorization: str | None) -> JSONResponse:
        """Return the minimal standard profile only for a valid local access token."""
        scheme, separator, access_token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not separator or not access_token:
            return _oauth_error("invalid_token", status_code=401)
        try:
            claims = jwt.decode(
                access_token,
                self._key.public_key(),
                algorithms=["RS256"],
                audience=self.config.core_audience,
                issuer=self.config.issuer,
            )
        except jwt.InvalidTokenError:
            return _oauth_error("invalid_token", status_code=401)
        principal_id = claims.get("sub")
        account = next(
            (
                candidate
                for candidate in _DEVELOPMENT_ACCOUNTS
                if candidate["principal_id"] == principal_id
            ),
            None,
        )
        if account is None:
            return _oauth_error("invalid_token", status_code=401)
        return JSONResponse(
            {
                "sub": account["principal_id"],
                "name": account["label"],
                "preferred_username": account["principal_id"],
            },
            headers={"Cache-Control": "no-store"},
        )


def _oauth_error(code: str, *, status_code: int, description: str | None = None) -> JSONResponse:
    payload: dict[str, str] = {"error": code}
    if description:
        payload["error_description"] = description
    return JSONResponse(
        payload,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "WWW-Authenticate": "Basic" if status_code == 401 else "",
        },
    )


def _error_page(message: str, *, status_code: int) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><title>KSI Local Identity</title><main>"
        f"<h1>개발 로그인 오류</h1><p>{html.escape(message)}</p></main>",
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _account_selection_page(issuer: LocalOidcIssuer, values: dict[str, str]) -> HTMLResponse:
    if not issuer.authorization_request_valid(values):
        return _error_page("잘못된 local OIDC authorization 요청입니다.", status_code=400)
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in values.items()
    )
    role_test_buttons = "".join(
        '<button type="submit" name="account" value="{principal}">'
        "<strong>{label}</strong><span>{description}</span></button>".format(
            principal=html.escape(account["principal_id"]),
            label=html.escape(account["label"]),
            description=html.escape(account["description"]),
        )
        for account in _DEVELOPMENT_ACCOUNTS[1:]
    )
    page = "\n".join(
        (
            "<!doctype html>",
            (
                '<html lang="ko"><head><meta charset="utf-8">'
                "<title>KSI Local Authentication Test</title>"
            ),
            "<style>",
            "body{font-family:system-ui,sans-serif;background:#f5f7fa;"
            "color:#18212b;margin:0;padding:2rem}",
            ".card{max-width:34rem;margin:5vh auto;background:#fff;"
            "border:1px solid #d9e0e8;border-radius:12px;padding:2rem}",
            "p{line-height:1.55;color:#5d6b78}.notice{background:#fff8d8;"
            "border:1px solid #e9cf68;border-radius:8px;padding:.75rem}",
            "form{display:grid;gap:.75rem;margin-top:1.25rem}"
            "button{text-align:left;border:1px solid #c7d1dd;background:#fff;"
            "border-radius:8px;padding:1rem;cursor:pointer}",
            "button:hover,button:focus{outline:3px solid #1f6feb;"
            "outline-offset:2px;border-color:#1f6feb}",
            "button strong,button span{display:block}button span{margin-top:.3rem;"
            "color:#5d6b78;font-size:.9rem}",
            ".primary{background:#135bb8;border-color:#135bb8;color:#fff;font-weight:700}"
            ".primary span{color:#eaf2ff}.advanced{margin-top:1.25rem}"
            ".advanced summary{cursor:pointer;color:#38516d;font-weight:650}"
            ".advanced[open] summary{margin-bottom:.75rem}",
            '</style></head><body><main class="card"><h1>KSI 로컬 인증 테스트</h1>',
            (
                "<p>상용 IdP를 연결하기 전, Operations Console의 OIDC 로그인 왕복만 "
                "확인하는 개발 화면입니다.</p>"
            ),
            (
                '<p class="notice"><strong>개발 전용</strong> · 실제 고객 계정·외부 IdP·'
                "고객 데이터에는 연결되지 않습니다.</p>"
            ),
            (
                "<p>이 화면은 권한별 화면을 점검하는 경우에만 사용합니다. 일상 개발은 "
                "Console의 기본 개발 계정 진입을 사용하세요. 상용 로그인에는 개발 계정을 "
                "고르는 화면이 나타나지 않습니다.</p>"
            ),
            f'<form method="post" action="/authorize">{hidden}'
            '<button class="primary" type="submit" name="account" '
            f'value="{html.escape(_DEFAULT_DEVELOPMENT_ACCOUNT["principal_id"])}">'
            '<strong>기본 개발 계정으로 계속</strong>'
            '<span>전체 운영 흐름을 확인하는 KSI 개발 관리자 계정입니다.</span></button></form>',
            '<details class="advanced"><summary>권한별 화면 테스트(선택)</summary>'
            '<p>RBAC와 읽기 전용 화면을 확인할 때만 다른 개발 계정을 선택하세요.</p>'
            f'<form method="post" action="/authorize">{hidden}{role_test_buttons}</form></details>',
            "</main></body></html>",
        )
    )
    return HTMLResponse(
        page,
        headers={"Cache-Control": "no-store"},
    )


def build_local_oidc_app(config: LocalOidcConfig) -> FastAPI:
    """테스트와 CLI가 함께 쓰는 loopback-only local issuer 조립점."""
    issuer = LocalOidcIssuer(config)
    app = FastAPI(title="KSI Local OIDC Identity", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/openid-configuration")
    def discovery() -> JSONResponse:
        base = issuer.config.issuer
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "userinfo_endpoint": f"{base}/userinfo",
                "jwks_uri": f"{base}/jwks.json",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": ["openid", "profile", "offline_access"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_basic",
                    "client_secret_post",
                ],
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/jwks.json")
    def jwks() -> JSONResponse:
        return JSONResponse(
            {"keys": [_jwk(issuer._key, issuer._kid)]}, headers={"Cache-Control": "no-store"}
        )

    @app.get("/authorize")
    def authorize_get(request: Request) -> Response:
        values = {key: value for key, value in request.query_params.items()}
        if not issuer.authorization_request_valid(values):
            return _error_page("잘못된 local OIDC authorization 요청입니다.", status_code=400)
        if issuer.can_auto_authorize_default_account(values):
            return issuer.complete_authorization(
                {**values, "account": _DEFAULT_DEVELOPMENT_ACCOUNT["principal_id"]}
            )
        return _account_selection_page(issuer, values)

    @app.post("/authorize", response_model=None)
    async def authorize_post(request: Request) -> Response:
        form = await _urlencoded_form(request)
        return issuer.complete_authorization(
            {key: value[0] for key, value in form.items() if len(value) == 1}
        )

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = await _urlencoded_form(request)
        if _form_value(form, "grant_type") == "refresh_token":
            return issuer.exchange_refresh_token(request, form)
        return issuer.exchange_code(request, form)

    @app.get("/userinfo")
    def userinfo(request: Request) -> JSONResponse:
        return issuer.userinfo(request.headers.get("authorization"))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9010)
    parser.add_argument(
        "--issuer-origin",
        default=None,
        help="discovery/JWT에 쓸 loopback issuer origin (bind host와 분리 가능)",
    )
    parser.add_argument("--dashboard-origin", required=True)
    parser.add_argument("--client-id", default="ksi-operations-console")
    parser.add_argument("--client-secret-file", required=True)
    parser.add_argument("--state-dir", default=".dev-data/local-identity")
    parser.add_argument("--core-audience", default="ksi-core")
    parser.add_argument(
        "--allow-tailnet-origin",
        action="store_true",
        help="loopback bind 앞의 같은-node *.ts.net Tailnet Serve issuer/callback을 허용",
    )
    args = parser.parse_args()
    if args.port <= 0 or args.port > 65535:
        parser.error("--port는 1~65535여야 한다")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("개발 OIDC issuer는 loopback host에만 bind할 수 있다")

    state_dir = Path(args.state_dir)
    config = LocalOidcConfig(
        issuer=args.issuer_origin or f"http://{args.host}:{args.port}",
        dashboard_origin=args.dashboard_origin,
        client_id=args.client_id,
        client_secret_file=Path(args.client_secret_file),
        key_file=state_dir / "local-oidc-rsa.private.pem",
        core_audience=args.core_audience,
        allow_tailnet_origins=args.allow_tailnet_origin,
    )
    app = build_local_oidc_app(config)
    print(f"KSI Local Identity issuer — {config.issuer}")
    print(f"Dashboard callback — {config.redirect_uri}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
