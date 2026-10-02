"""OIDC operator JWT 검증과 bounded JWKS cache.

사람 access token만 이 adapter가 해석한다. Gateway·Edge·Processing Worker 자격은
``AuthRegistry``의 opaque digest 경로를 계속 사용한다. JWKS가 만료된 상태에서 issuer에
닿지 못하면 이전 키를 낙관적으로 쓰지 않고 검증을 거부한다(fail-closed).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt

from ksi_core.identity.auth import Principal
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry

JwksFetcher = Callable[[], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class OidcVerifierConfig:
    issuer: str
    audience: str
    jwks_url: str
    allowed_algorithms: tuple[str, ...] = ("RS256",)
    jwks_ttl_seconds: int = 300
    http_timeout_seconds: float = 5.0
    subject_registry_file: Path | None = None

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not self.jwks_url:
            raise ValueError("OIDC issuer, audience, jwks_url은 비어 있을 수 없다")
        if self.subject_registry_file is not None and (
            not self.subject_registry_file.is_absolute() or ".." in self.subject_registry_file.parts
        ):
            raise ValueError("OIDC subject registry file must be absolute and normalized")
        if not self.allowed_algorithms or any(not alg for alg in self.allowed_algorithms):
            raise ValueError("OIDC allowed_algorithms는 비어 있지 않은 문자열 집합이어야 한다")
        if self.jwks_ttl_seconds <= 0:
            raise ValueError("OIDC JWKS TTL은 양수여야 한다")
        if self.http_timeout_seconds <= 0:
            raise ValueError("OIDC HTTP timeout은 양수여야 한다")


class OidcJwtVerifier:
    """서명된 issuer-subject mapping으로 OPERATOR를 resolve한다."""

    def __init__(
        self,
        config: OidcVerifierConfig,
        *,
        subject_registry: OidcSubjectRegistry,
        fetch_jwks: JwksFetcher | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._subject_registry = subject_registry
        self._fetch_jwks = fetch_jwks or self._fetch_remote_jwks
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._keys_by_kid: dict[str, dict[str, Any]] = {}
        self._cache_expires_at = 0.0

    def verify(self, token: str) -> Principal | None:
        """검증 실패 사유를 외부에 구분하지 않고 ``None``으로 접는다."""
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in self._config.allowed_algorithms:
                return None
            if not isinstance(kid, str) or not kid:
                return None

            jwk = self._key_for_kid(kid)
            if jwk is None:
                return None
            key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self._config.allowed_algorithms),
                audience=self._config.audience,
                issuer=self._config.issuer,
                options={
                    "require": [
                        "exp",
                        "nbf",
                        "iss",
                        "aud",
                        "sub",
                    ]
                },
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject:
                return None
            return self._subject_registry.resolve(self._config.issuer, subject)
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            return None

    def _key_for_kid(self, kid: str) -> dict[str, Any] | None:
        keys = self._keys(force_refresh=False)
        if kid in keys:
            return keys[kid]
        # 키 회전 직후의 unknown kid는 TTL을 기다리지 않고 정확히 한 번 갱신한다.
        return self._keys(force_refresh=True).get(kid)

    def _keys(self, *, force_refresh: bool) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = self._monotonic()
            if not force_refresh and self._keys_by_kid and now < self._cache_expires_at:
                return self._keys_by_kid

            payload = self._fetch_jwks()
            raw_keys = payload.get("keys")
            if not isinstance(raw_keys, list) or not raw_keys:
                raise ValueError("JWKS keys는 비어 있지 않은 배열이어야 한다")
            parsed: dict[str, dict[str, Any]] = {}
            for raw_key in raw_keys:
                if not isinstance(raw_key, dict):
                    raise ValueError("JWKS key는 object여야 한다")
                kid = raw_key.get("kid")
                if not isinstance(kid, str) or not kid or kid in parsed:
                    raise ValueError("JWKS kid는 비어 있지 않고 중복되지 않아야 한다")
                parsed[kid] = raw_key
            self._keys_by_kid = parsed
            self._cache_expires_at = now + self._config.jwks_ttl_seconds
            return self._keys_by_kid

    def _fetch_remote_jwks(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self._config.jwks_url,
            headers={"Accept": "application/json", "User-Agent": "ksi-core-oidc/1"},
        )
        with urllib.request.urlopen(  # noqa: S310 -- URL은 fail-closed production config
            request, timeout=self._config.http_timeout_seconds
        ) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("JWKS 응답은 object여야 한다")
        return payload


__all__ = ["OidcJwtVerifier", "OidcVerifierConfig"]
