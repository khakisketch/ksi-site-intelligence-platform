"""F-01 — 서버 발급 Site bootstrap 과 site 단위 grant 수용 계약.

D1 2안(지정 고객 org-admin self-bootstrap)과 C3(생성과 scope 의 분리)를 고정한다:

- mapped bootstrap 은 **서버 발급 siteId** 를 쓴다 — 고객 입력 ID 의 전역 중복
  조회가 다른 조직의 Site 존재를 알려주는 오라클이 되지 않는다(INV-060).
- 재시도는 ``(organizationId, actor, requestKey)`` namespace 의 durable binding
  으로 해소된다 — journal 은 하나의 ``site-registered`` 레코드이고, 같은 payload
  는 같은 Site, 바뀐 payload 는 typed 409 다.
- scope 축소 후 재시도는 숨겨진 영수증을 돌려주지 않는다(미지 Site 와 같은 404).

같은 Site WorkArea 상속(C1)의 소비자별 검증은 이 파일의 후속 절에서 커진다.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
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
from ksi_core.domains.external.quantity.external_analysis_api import ExternalAnalysisFacade
from ksi_core.domains.sites.sites import (
    SiteStore,
    SiteStoreRecoveryError,
    SiteVerdict,
    _bootstrap_payload_digest,
    mount_sites,
)
from ksi_core.domains.sites.work_areas import WorkAreaStore, mount_work_areas
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_event_contracts.site_frame import SiteFrame

_ISSUER = "https://issuer.example.test"
_AUDIENCE = "ksi-core"
_OPAQUE_TOKEN = "opaque-op-token"

_SITE_FRAME = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _frame_payload() -> dict[str, str]:
    return dict(_SITE_FRAME)


def _frame_model() -> SiteFrame:
    return SiteFrame.model_validate(_SITE_FRAME)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _opaque_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_OPAQUE_TOKEN),
                principal=Principal(
                    principal_id="opaque-op",
                    organization_id="org-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


def _jwk(key: RSAPrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()

    def encode(value: int) -> str:
        return jwt.utils.base64url_encode(
            value.to_bytes((value.bit_length() + 7) // 8, "big")
        ).decode()

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "bootstrap-key",
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


def _oidc_token(key: RSAPrivateKey, *, subject: str = "bootstrap-subject") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": subject,
            "exp": now + 600,
            "nbf": now - 5,
            "ksi_role": "ADMIN",  # 무시되어야 하는 미검증 claim
        },
        key,
        algorithm="RS256",
        headers={"kid": "bootstrap-key"},
    )


def _v2_registry(
    *,
    capabilities: list[str],
    site_ids: list[str] | None,
    area_ids: list[str] | None,
    role: str = "FIELD_OPERATOR",
    organization_id: str = "org-1",
) -> OidcSubjectRegistry:
    return OidcSubjectRegistry.from_document(
        {
            "version": "oidc-subject-registry.v2",
            "subjects": [
                {
                    "issuer": _ISSUER,
                    "subject": "bootstrap-subject",
                    "principalId": "bootstrap-operator",
                    "organizationId": organization_id,
                    "role": role,
                    "status": "ACTIVE",
                    "capabilities": capabilities,
                    "allowedSiteIds": site_ids,
                    "allowedWorkAreaIds": area_ids,
                }
            ],
        },
        expected_issuer=_ISSUER,
    )


def _install_mapped_v2(
    app: FastAPI,
    *,
    capabilities: list[str],
    site_ids: list[str] | None,
    area_ids: list[str] | None,
    organization_id: str = "org-1",
) -> tuple[str, RSAPrivateKey]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(
            issuer=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=f"{_ISSUER}/jwks.json",
        ),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=_v2_registry(
            capabilities=capabilities,
            site_ids=site_ids,
            area_ids=area_ids,
            organization_id=organization_id,
        ),
    )
    app.state.human_auth_mode = HumanAuthMode.DUAL
    return _oidc_token(key), key


def _store(tmp_path: Path, *, cap: int = 1000, name: str = "sites.jsonl") -> SiteStore:
    return SiteStore(DurableJournal(tmp_path / name), max_bootstrap_sites_per_org=cap)


# ── 1. store 수준: 발급·멱등·namespace ────────────────────────────────


def test_bootstrap_issues_server_site_id_and_replays(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    journal = DurableJournal(journal_path)
    store = SiteStore(journal)
    key = str(uuid.uuid4())
    result = store.register_bootstrap(
        key,
        "테스트 현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert result.verdict is SiteVerdict.REGISTERED
    assert result.record is not None
    site_id = result.record.site_id
    assert site_id.startswith("site-")
    assert result.record.organization_id == "org-1"
    journal.close()

    # 재시작 후에도 같은 binding·Site 가 재현되고, 같은 요청 키는 같은 ID 다.
    store2 = SiteStore(DurableJournal(journal_path))
    retry = store2.register_bootstrap(
        key,
        "테스트 현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert retry.verdict is SiteVerdict.REGISTERED
    assert retry.record is not None and retry.record.site_id == site_id
    # 원장에는 등록 레코드가 정확히 하나다(재시도가 새 레코드를 만들지 않는다).
    lines = [
        line
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if '"site-registered"' in line
    ]
    assert len(lines) == 1


def test_bootstrap_retry_same_key_changed_payload_is_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = str(uuid.uuid4())
    first = store.register_bootstrap(
        key,
        "첫 이름",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert first.record is not None

    changed = store.register_bootstrap(
        key,
        "다른 이름",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert changed.verdict is SiteVerdict.BOOTSTRAP_REQUEST_CONFLICT
    assert changed.record is None


def test_bootstrap_namespace_is_org_and_actor_scoped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = str(uuid.uuid4())
    _first = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    other_actor = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-2",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    other_org = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-2",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert other_actor.verdict is SiteVerdict.REGISTERED
    assert other_org.verdict is SiteVerdict.REGISTERED
    assert _first.record is not None and other_actor.record is not None
    assert _first.record.site_id != other_actor.record.site_id


def test_bootstrap_hidden_after_scope_narrowing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    key = str(uuid.uuid4())
    created = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert created.record is not None
    site_id = created.record.site_id

    hidden = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=frozenset(),
        now=datetime.now(UTC),
    )
    assert hidden.verdict is SiteVerdict.UNKNOWN_SITE
    assert hidden.record is None
    # payload 가 바뀐 경우에도 숨겨진 상태에서는 충돌을 알려주지 않는다.
    hidden_changed = store.register_bootstrap(
        key,
        "다른 이름",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=frozenset(),
        now=datetime.now(UTC),
    )
    assert hidden_changed.verdict is SiteVerdict.UNKNOWN_SITE

    visible_again = store.register_bootstrap(
        key,
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=frozenset({site_id}),
        now=datetime.now(UTC),
    )
    assert visible_again.verdict is SiteVerdict.REGISTERED
    assert visible_again.record is not None and visible_again.record.site_id == site_id


def test_bootstrap_org_cap_counts_all_registered_sites(tmp_path: Path) -> None:
    store = _store(tmp_path, cap=2)
    created = {
        store.register_bootstrap(
            str(uuid.uuid4()),
            "현장",
            _frame_model(),
            organization_id="org-1",
            actor="op-1",
            allowed_site_ids=None,
            now=datetime.now(UTC),
        ).verdict
        for _ in range(2)
    }
    assert created == {SiteVerdict.REGISTERED}
    third = store.register_bootstrap(
        str(uuid.uuid4()),
        "현장",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert third.verdict is SiteVerdict.SITE_BOOTSTRAP_LIMIT_REACHED
    # 다른 조직은 자기 상한을 따로 갖는다.
    other = store.register_bootstrap(
        str(uuid.uuid4()),
        "현장",
        _frame_model(),
        organization_id="org-2",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert other.verdict is SiteVerdict.REGISTERED
    # legacy opaque 등록은 상한을 쓰지 않는다(소급 제한 없음).
    assert (
        store.register(
            "legacy-site",
            "레거시",
            _frame_model(),
            organization_id="org-1",
            actor="legacy-op",
            now=datetime.now(UTC),
        ).verdict
        is SiteVerdict.REGISTERED
    )


def test_bootstrap_invalid_request_key_and_actor_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for request_key in ("", "not-a-uuid", "A" * 36, str(uuid.uuid4()).upper()):
        result = store.register_bootstrap(
            request_key,
            "현장",
            _frame_model(),
            organization_id="org-1",
            actor="op-1",
            allowed_site_ids=None,
            now=datetime.now(UTC),
        )
        assert result.verdict is SiteVerdict.INVALID_SITE
    assert (
        store.register_bootstrap(
            str(uuid.uuid4()),
            "현장",
            _frame_model(),
            organization_id="org-1",
            actor="",
            allowed_site_ids=None,
            now=datetime.now(UTC),
        ).verdict
        is SiteVerdict.INVALID_SITE
    )


# ── 2. 재생 fail-closed ────────────────────────────────────────────────


def _bootstrap_raw(
    *,
    site_id: str,
    request_key: str,
    name: str = "현장",
    actor: str = "op-1",
    organization_id: str = "org-1",
    digest: str | None = None,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "kind": "site-registered",
        "ts": datetime.now(UTC).isoformat(),
        "actor": actor,
        "before": None,
        "after": "UNMAPPED",
        "evidence": None,
        "reason": None,
        "siteId": site_id,
        "organizationId": organization_id,
        "name": name,
        "siteFrame": _frame_payload(),
        "aoi": None,
        "dataResidency": None,
        "aiEgressAllowed": False,
    }
    if binding is not None:
        raw["bootstrap"] = binding
    else:
        raw["bootstrap"] = {
            "version": "site-bootstrap-binding.v1",
            "requestKey": request_key,
            "requestDigest": digest or _bootstrap_payload_digest(raw),
        }
    return raw


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["bootstrap"].pop("requestDigest"),  # 부분 metadata
        lambda raw: raw["bootstrap"].update({"extra": True}),
        lambda raw: raw["bootstrap"].update({"version": "site-bootstrap-binding.v2"}),
        lambda raw: raw["bootstrap"].update({"requestKey": "not-a-uuid"}),
        lambda raw: raw["bootstrap"].update({"requestDigest": "0" * 63}),
        lambda raw: raw["bootstrap"].update({"requestDigest": "f" * 64}),  # digest 불일치
        lambda raw: raw.update({"actor": ""}),
    ],
)
def test_replay_rejects_malformed_bootstrap_binding(tmp_path: Path, mutate: Any) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    raw = _bootstrap_raw(site_id="site-corrupt", request_key=str(uuid.uuid4()))
    mutate(raw)
    seed.append(raw)
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_rejects_duplicate_bootstrap_namespace(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    key = str(uuid.uuid4())
    seed.append(_bootstrap_raw(site_id="site-a", request_key=key))
    seed.append(_bootstrap_raw(site_id="site-b", request_key=key))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_legacy_registration_shares_journal_with_bootstrap(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    journal = DurableJournal(journal_path)
    store = SiteStore(journal)
    assert (
        store.register(
            "legacy-site",
            "레거시",
            _frame_model(),
            organization_id="org-1",
            actor="legacy-op",
            now=datetime.now(UTC),
        ).verdict
        is SiteVerdict.REGISTERED
    )
    key = str(uuid.uuid4())
    boot = store.register_bootstrap(
        key,
        "부트스트랩",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert boot.record is not None
    journal.close()

    store2 = SiteStore(DurableJournal(journal_path))
    assert store2.get("legacy-site") is not None
    retry = store2.register_bootstrap(
        key,
        "부트스트랩",
        _frame_model(),
        organization_id="org-1",
        actor="op-1",
        allowed_site_ids=None,
        now=datetime.now(UTC),
    )
    assert retry.record is not None and retry.record.site_id == boot.record.site_id


# ── 3. route 수준: mapped/opaque 형태 강제 ─────────────────────────────


def _build_auth_app(
    tmp_path: Path,
    *,
    capabilities: list[str],
    site_ids: list[str] | None,
    area_ids: list[str] | None,
    role: str = "FIELD_OPERATOR",
    cap: int = 1000,
) -> tuple[FastAPI, SiteStore, str]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    store = _store(tmp_path, cap=cap)
    app = FastAPI()
    mount_auth(
        app,
        _opaque_registry(),
        human_auth_mode=HumanAuthMode.DUAL,
        oidc_verifier=OidcJwtVerifier(
            OidcVerifierConfig(
                issuer=_ISSUER,
                audience=_AUDIENCE,
                jwks_url=f"{_ISSUER}/jwks.json",
            ),
            fetch_jwks=lambda: {"keys": [_jwk(key)]},
            subject_registry=_v2_registry(
                capabilities=capabilities, site_ids=site_ids, area_ids=area_ids, role=role
            ),
        ),
    )
    mount_sites(app, store)
    return app, store, _oidc_token(key)


def _bootstrap_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "bootstrapRequestId": str(uuid.uuid4()),
        "name": "새 현장",
        "siteFrame": _frame_payload(),
    }
    body.update(overrides)
    return body


def test_mapped_bootstrap_route_creates_and_is_idempotent(tmp_path: Path) -> None:
    app, store, token = _build_auth_app(
        tmp_path, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    body = _bootstrap_body()

    created = client.post("/v1/sites", headers=headers, json=body)
    assert created.status_code == 201, created.text
    site_id = created.json()["site"]["siteId"]
    assert site_id.startswith("site-")

    retry = client.post("/v1/sites", headers=headers, json=body)
    assert retry.status_code == 201
    assert retry.json()["site"]["siteId"] == site_id

    listed = client.get("/v1/sites", headers=headers)
    assert listed.status_code == 200
    assert [site["siteId"] for site in listed.json()["sites"]] == [site_id]
    detail = client.get(f"/v1/sites/{site_id}", headers=headers)
    assert detail.status_code == 200

    # mapped 신원은 client 지정 sitId 형태를 쓸 수 없다.
    mismatched = client.post(
        "/v1/sites",
        headers=headers,
        json={
            "siteId": "customer-picked",
            "name": "새 현장",
            "siteFrame": _frame_payload(),
        },
    )
    assert mismatched.status_code == 422

    # 감사 기록: actor 는 인증 principal 이다.
    record = store.get(site_id)
    assert record is not None and record.organization_id == "org-1"


def test_mapped_without_capability_is_403_even_with_admin_claim(tmp_path: Path) -> None:
    app, store, token = _build_auth_app(tmp_path, capabilities=[], site_ids=None, area_ids=None)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    denied = client.post("/v1/sites", headers=headers, json=_bootstrap_body())
    assert denied.status_code == 403
    assert store.list_scoped("org-1") == []


def test_opaque_bootstrap_form_is_422(tmp_path: Path) -> None:
    app, store, _token_value = _build_auth_app(
        tmp_path, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_OPAQUE_TOKEN}"}

    rejected = client.post("/v1/sites", headers=headers, json=_bootstrap_body())
    assert rejected.status_code == 422
    assert store.list_scoped("org-1") == []

    # opaque legacy 형태는 그대로 동작한다.
    legacy = client.post(
        "/v1/sites",
        headers=headers,
        json={"siteId": "opaque-site", "name": "레거시", "siteFrame": _frame_payload()},
    )
    assert legacy.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "siteFrame": _SITE_FRAME},  # 키 누락
        {
            "siteId": "a",
            "bootstrapRequestId": str(uuid.uuid4()),
            "name": "x",
            "siteFrame": _SITE_FRAME,
        },  # 동시 제공
        {"bootstrapRequestId": "not-a-uuid", "name": "x", "siteFrame": _SITE_FRAME},
    ],
)
def test_registration_form_violations_are_422(tmp_path: Path, body: dict[str, Any]) -> None:
    app, store, token = _build_auth_app(
        tmp_path, capabilities=["SITE_BOOTSTRAP"], site_ids=None, area_ids=None
    )
    client = TestClient(app)
    response = client.post("/v1/sites", headers={"Authorization": f"Bearer {token}"}, json=body)
    assert response.status_code == 422
    assert store.list_scoped("org-1") == []


def test_mapped_explicit_list_creation_returns_receipt_without_access(
    tmp_path: Path,
) -> None:
    app, store, token = _build_auth_app(
        tmp_path, capabilities=["SITE_BOOTSTRAP"], site_ids=[], area_ids=[]
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    body = _bootstrap_body()

    # body 의 organizationId/actor 위조 주입은 저장소 이전에 422 다.
    forged = client.post(
        "/v1/sites",
        headers=headers,
        json=_bootstrap_body(organizationId="attacker-org", actor="attacker"),
    )
    assert forged.status_code == 422
    assert store.list_scoped("org-1") == []

    created = client.post("/v1/sites", headers=headers, json=body)
    assert created.status_code == 201, created.text
    site_id = created.json()["site"]["siteId"]

    # C3 explicit-list 예외: 최초 생성 영수증은 돌려주지만 목록 밖 새 Site 는
    # 보이지 않는다 — lockout 을 성공처럼 숨기지 않는다. 조직 귀속은 인증
    # Principal 값이다.
    assert client.get("/v1/sites", headers=headers).json()["sites"] == []
    assert client.get(f"/v1/sites/{site_id}", headers=headers).status_code == 404
    record = store.get(site_id)
    assert record is not None
    assert record.organization_id == "org-1"

    # 같은 요청 키 재시도는 숨겨진 영수증을 반복해 주지 않는다.
    retry = client.post("/v1/sites", headers=headers, json=body)
    assert retry.status_code == 404
    assert retry.json().get("site") is None
    assert [item.site_id for item in store.list_scoped("org-1")] == [site_id]


# ── 4. same-Site 상속 소비자 (KTD5) ────────────────────────────────────

_NOW = datetime(2026, 10, 10, tzinfo=UTC)


def _polygon(x: float = 127.0, y: float = 37.0) -> dict[str, object]:
    ring = [[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]
    return {"type": "Polygon", "coordinates": [ring]}


def test_work_area_site_store_absent_is_fail_closed_for_mapped_scope(tmp_path: Path) -> None:
    """site_store 없는 최소 조립에서 mapped 신원이 legacy 가시성 경로로 새지 않는다."""
    store = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"), site_exists=lambda site_id: True
    )
    assert (
        store.register(
            "site-any",
            name="구역",
            polygon=_polygon(),
            crs="EPSG:4326",
            supersedes=None,
            now=_NOW,
            actor="seed",
        ).work_area
        is not None
    )
    app = FastAPI()
    mount_auth(app, _opaque_registry())
    mapped_token, _key = _install_mapped_v2(app, capabilities=[], site_ids=None, area_ids=None)
    mount_work_areas(app, store)  # site_store 미주입 — fallback 경로
    client = TestClient(app)

    denied = client.get(
        "/v1/sites/site-any/work-areas", headers={"Authorization": f"Bearer {mapped_token}"}
    )
    assert denied.status_code == 404

    # opaque legacy 신원은 주입된 사이트 판정(여기선 True)으로 종전처럼 동작한다.
    allowed = client.get(
        "/v1/sites/site-any/work-areas", headers={"Authorization": f"Bearer {_OPAQUE_TOKEN}"}
    )
    assert allowed.status_code == 200


def test_supersedes_other_site_area_folds_to_not_found(tmp_path: Path) -> None:
    """타 Site 소속 supersedes 대상은 미지 area 와 같은 404 — siteId 설명 노출 없음."""
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    frame = _frame_model()
    for site_id, org in (("site-a", "org-1"), ("site-b", "org-2")):
        assert (
            site_store.register(
                site_id,
                site_id,
                frame,
                organization_id=org,
                actor="seed",
                now=_NOW,
            ).record
            is not None
        )
    area_store = WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"), site_exists=site_store.get
    )
    area_a = area_store.register(
        "site-a",
        name="A구역",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="seed",
    ).work_area
    area_b = area_store.register(
        "site-b",
        name="B구역",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="seed",
    ).work_area
    assert area_a is not None and area_b is not None

    app = FastAPI()
    mount_auth(app, _opaque_registry())
    mapped_token, _key = _install_mapped_v2(app, capabilities=[], site_ids=None, area_ids=None)
    mount_work_areas(app, area_store, site_store=site_store)
    client = TestClient(app)

    body = {"name": "수정", "polygon": _polygon(128.0), "crs": "EPSG:4326"}
    for token in (mapped_token, _OPAQUE_TOKEN):
        response = client.post(
            "/v1/sites/site-a/work-areas",
            headers={"Authorization": f"Bearer {token}"},
            json={**body, "supersedes": area_b.work_area_id},
        )
        assert response.status_code == 404
        assert "site-b" not in response.text
        assert "다른 현장" not in response.text

    # 같은 Site supersedes 는 그대로 동작한다.
    ok = client.post(
        "/v1/sites/site-a/work-areas",
        headers={"Authorization": f"Bearer {mapped_token}"},
        json={**body, "supersedes": area_a.work_area_id},
    )
    assert ok.status_code == 201, ok.text


def test_analysis_selector_scope_requires_work_order_binding_for_mapped_null() -> None:
    """area null(mapped)도 WorkOrder Org·Site binding 확인을 생략하지 않는다."""
    facade = object.__new__(ExternalAnalysisFacade)
    facade._work_orders = None
    mapped_null = Principal(
        principal_id="mapped-null",
        organization_id="org-1",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        registry_scoped=True,
    )
    legacy = Principal(
        principal_id="legacy",
        organization_id="org-1",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
    )
    selector = SimpleNamespace(work_order_id="order-1")
    selectors = cast(Any, (selector,))

    # 원장이 없으면 mapped 는 unrestricted 가 아니라 fail-closed 다.
    assert not facade._selectors_are_in_scope(mapped_null, "site-1", selectors)

    class _Orders:
        def __init__(self, row: Any) -> None:
            self._row = row

        def get(self, work_order_id: str, *, organization_id: str) -> Any:
            row = self._row
            if (
                row is not None
                and row.work_order_id == work_order_id
                and row.organization_id == organization_id
            ):
                return row
            return None

    def _order(*, org: str, site: str) -> Any:
        return SimpleNamespace(
            work_order_id="order-1",
            organization_id=org,
            site_id=site,
            work_area_ids=("wa-1",),
        )

    facade._work_orders = _Orders(_order(org="org-2", site="site-1"))
    assert not facade._selectors_are_in_scope(mapped_null, "site-1", selectors)
    facade._work_orders = _Orders(_order(org="org-1", site="site-2"))
    assert not facade._selectors_are_in_scope(mapped_null, "site-1", selectors)
    facade._work_orders = _Orders(_order(org="org-1", site="site-1"))
    assert facade._selectors_are_in_scope(mapped_null, "site-1", selectors)

    # legacy 미분화 신원(area None, marker 없음)은 종전 계약 그대로다.
    facade._work_orders = None
    assert facade._selectors_are_in_scope(legacy, "site-1", selectors)


def test_mapped_null_analysis_flow_matches_legacy_contract(tmp_path: Path) -> None:
    """정상 selector 는 mapped null 에서도 추가 grant provisioning 없이 진행된다."""
    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        token, _key = _install_mapped_v2(
            fixture.app,
            capabilities=[],
            site_ids=None,
            area_ids=None,
            organization_id=fixture.organization_id,
        )
        client = TestClient(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "f01-mapped-null-analysis",
            },
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
    finally:
        fixture.close()
