"""Real-Core Site/consent/grant boundaries for Analysis MCP result and evidence.

Core owns path identity, EGRESS/permission revocation and response binding;
the adapter preflight is not a grant and this suite proposes no wire-contract
change (the evidence page carries no Site echo by contract, so the adapter
binds Analysis ID only and Core's path-scoped read enforces the Site).

What this proves on the current checkout, with generated synthetic identities
and loopback only (no customer/real-host/external credentials):

1. Positive: the machine-created analysis and its evidence page return only
   through the authorized Site path.
2. Cross-Site negative: the same ``analysisId`` under a foreign Site path is
   Core ``404 ANALYSIS_RESOURCE_NOT_FOUND`` through the adapter (direct client
   and official SDK stdio); no foreign payload becomes MCP output.
3. Consent negative: a site with ``ai_egress_allowed=False`` refuses every
   MCP lane with ``AI_EGRESS_NOT_ALLOWED`` through the adapter and records
   no intent.
4. WorkArea-grant negative: a machine identity scoped to another WorkArea can
   neither create on, nor read, the fixture's WorkArea intent
   (``ANALYSIS_RESOURCE_NOT_FOUND``, no new record).

Stub loopback scope-echo tests isolate the adapter projection seam; the
assertions below run against the real assembled Core app. This is boundary
evidence, not a vulnerability claim.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests" / "contract"))

from analysis_api_local_fixture import build_local_analysis_api_fixture  # noqa: E402
from test_external_analysis_activation import _write_activation  # noqa: E402

FOREIGN_SITE = "site-org-b"
OTHER_KEY = "real-core-scope-other-key-1"
CONSENT_KEY = "real-core-consent-denied-key-1"
SITE_B = "site-b"
DUAL_TOKEN = "analysis-dual-site-mcp-test-01"
DUAL_CREATE_KEY = "real-core-dual-grant-create-1"
DUAL_STDIO_CREATE_KEY = "real-core-dual-grant-stdio-create-1"


def _active_activation_factory(tmp_path: Path) -> Any:
    def active_activation(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "mcp-scope-activation",
            bindings={
                "organization_id": "org-a",
                "policy": config.policy,
                "runtime": config.runtime,
                "resource_envelope": config.resource_envelope,
                "worker_principal": worker,
            },
            activation_fields={
                "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        )[2]

    return active_activation


class _LabelTransport(httpx.AsyncBaseTransport):
    """ASGI transport that labels synthetic identities and records ACKs."""

    def __init__(self, app: Any, *, machine_raw: str) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self._machine_raw = machine_raw
        self.requests: list[dict[str, Any]] = []

    def _who(self, request: httpx.Request) -> str:
        return (
            "machine"
            if request.headers.get("authorization", "") == "Bearer " + self._machine_raw
            else "other"
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        entry: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "who": self._who(request),
        }
        if request.method == "POST":
            entry["idempotency_key"] = request.headers.get("idempotency-key")
        self.requests.append(entry)
        return response


def _client_for(
    tmp_path: Path,
    app: Any,
    machine_raw: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_raw: str,
    token_name: str,
) -> Any:
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAnalysisClient

    token_file = tmp_path / token_name
    token_file.write_text(token_raw, encoding="ascii")
    token_file.chmod(0o600)
    transport = _LabelTransport(app, machine_raw=machine_raw)
    monkeypatch.setattr(
        AdapterConfig,
        "new_http_client",
        lambda self: httpx.AsyncClient(
            transport=transport,
            base_url=self.core_origin,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        ),
    )
    config = AdapterConfig.from_values(core_origin="http://127.0.0.1:9", token_file=str(token_file))
    return CoreAnalysisClient(config), transport


async def _direct_core(
    app: Any, method: str, path: str, *, headers: dict[str, str]
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", trust_env=False
    ) as client:
        return await client.request(method, path, headers=headers)


def _setup_dual_site_and_identity(fixture: Any) -> tuple[str, str]:
    """Register synthetic site-B and install a dual-grant MCP identity.

    Runtime-only setup on the synthetic fixture (no shared-file change, no
    real permission widening): site-B lives in the same test organization
    with ``ai_egress_allowed=True``, and one new test-only
    ``ANALYSIS_MCP_CLIENT`` holds explicit grants for site-A/B and both
    WorkAreas. Existing registry records are preserved. Returns
    ``(site_b_area_id, dual_raw_token)``.
    """

    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord
    from ksi_event_contracts.site_frame import SiteFrame

    site_a = fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
    assert site_a is not None
    frame = SiteFrame.model_validate(site_a.site_frame)
    now = datetime.now(UTC)
    registered_b = fixture.app.state.site_store.register(
        SITE_B,
        "Dual-grant second site",
        frame,
        organization_id=fixture.organization_id,
        ai_egress_allowed=True,
        actor="analysis-local-operator",
        now=now,
    )
    assert registered_b.record is not None
    site_b = fixture.app.state.site_store.get_scoped(SITE_B, fixture.organization_id)
    assert site_b is not None, "synthetic site-B must actually exist"
    assert site_b.ai_egress_allowed is True

    area_a = fixture.app.state.work_area_store.get(fixture.work_area_id)
    assert area_a is not None
    registered_area_b = fixture.app.state.work_area_store.register(
        SITE_B,
        name="Dual-grant second area",
        polygon=area_a.polygon,
        crs=area_a.crs,
        supersedes=None,
        actor="analysis-local-operator",
        now=datetime.now(UTC),
    )
    assert registered_area_b.work_area is not None
    site_b_area_id = registered_area_b.work_area.work_area_id
    assert site_b_area_id != fixture.work_area_id

    dual_principal = Principal(
        principal_id="analysis-local-mcp-client-dual",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=None,
        device_id=None,
        organization_id=fixture.organization_id,
        allowed_site_ids=frozenset({fixture.site_id, SITE_B}),
        allowed_work_area_ids=frozenset({fixture.work_area_id, site_b_area_id}),
    )
    dual_record = PrincipalTokenRecord(
        token_sha256=hashlib.sha256(DUAL_TOKEN.encode()).hexdigest(),
        principal=dual_principal,
    )
    existing = list(fixture.app.state.auth_registry._by_digest.values())
    assert all(
        getattr(record, "token_sha256", None) != dual_record.token_sha256 for record in existing
    )
    fixture.app.state.auth_registry = AuthRegistry([*existing, dual_record])
    return site_b_area_id, DUAL_TOKEN


def test_real_core_cross_site_detail_and_evidence_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same analysisId under a foreign Site path is 404 via Core and adapter."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    try:
        machine_raw = fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
        client, _transport = _client_for(
            tmp_path,
            fixture.app,
            machine_raw,
            monkeypatch,
            token_raw=machine_raw,
            token_name="token-machine",
        )
        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        created = asyncio.run(
            client.invoke(
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": "real-core-scope-positive-1",
                },
            )
        )
        analysis_id = created["analysisId"]
        assert created["siteId"] == fixture.site_id
        assert created["workAreaId"] == fixture.work_area_id

        # Positive controls through the authorized Site path.
        detail = asyncio.run(
            client.invoke(
                "ksi_get_analysis", {"siteId": fixture.site_id, "analysisId": analysis_id}
            )
        )
        assert detail["analysisId"] == analysis_id
        assert detail["siteId"] == fixture.site_id
        evidence = asyncio.run(
            client.invoke(
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id, "limit": 32},
            )
        )
        assert evidence["analysisId"] == analysis_id
        listing = asyncio.run(
            client.invoke("ksi_list_analyses", {"siteId": fixture.site_id, "limit": 50})
        )
        assert listing["siteId"] == fixture.site_id
        assert [item["analysisId"] for item in listing["items"]] == [analysis_id]

        # Direct Core owns the path binding: foreign Site path is 404 with no
        # machine ACK, for detail, result alias and evidence alike.
        for suffix in ("", "/evidence"):
            method_path = f"/v2/sites/{FOREIGN_SITE}/analyses/{analysis_id}{suffix}"
            response = asyncio.run(
                _direct_core(
                    fixture.app,
                    "GET",
                    method_path,
                    headers=fixture.mcp_client_headers(),
                )
            )
            assert response.status_code == 404, (method_path, response.text)
            assert response.json() == {"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}
            assert response.headers.get("X-KSI-External-AI-Egress") is None

        # Adapter surfaces the same Core refusal; the foreign payload never
        # becomes MCP output and no raw credential leaks into the typed error.
        for tool, args in (
            ("ksi_get_analysis", {"siteId": FOREIGN_SITE, "analysisId": analysis_id}),
            ("ksi_get_analysis_result", {"siteId": FOREIGN_SITE, "analysisId": analysis_id}),
            (
                "ksi_get_analysis_evidence",
                {"siteId": FOREIGN_SITE, "analysisId": analysis_id, "limit": 32},
            ),
            ("ksi_list_analyses", {"siteId": FOREIGN_SITE, "limit": 50}),
        ):
            with pytest.raises(CoreAdapterError, match="ANALYSIS_RESOURCE_NOT_FOUND") as exc_info:
                asyncio.run(client.invoke(tool, dict(args)))
            assert machine_raw not in str(exc_info.value)

        # Evidence has no Site echo by contract: a same-site foreign Analysis
        # ID is likewise 404, never a foreign record.
        with pytest.raises(CoreAdapterError, match="ANALYSIS_RESOURCE_NOT_FOUND"):
            asyncio.run(
                client.invoke(
                    "ksi_get_analysis_evidence",
                    {"siteId": fixture.site_id, "analysisId": "an-unknown-999", "limit": 32},
                )
            )
    finally:
        fixture.close()


def test_real_core_consent_denied_fails_closed_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A site without external-AI consent refuses every MCP lane via Core."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    denied_dir = tmp_path / "denied"
    denied_dir.mkdir()
    denied_dir.chmod(0o700)
    fixture = build_local_analysis_api_fixture(
        denied_dir,
        ai_egress_allowed=False,
        analysis_activation=_active_activation_factory(denied_dir),
    )
    try:
        machine_raw = fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
        token_file = tmp_path / "denied-token"
        token_file.write_text(machine_raw, encoding="ascii")
        token_file.chmod(0o600)
        from ksi_analysis_mcp.config import AdapterConfig
        from ksi_analysis_mcp.core_client import CoreAnalysisClient

        transport = _LabelTransport(fixture.app, machine_raw=machine_raw)
        monkeypatch.setattr(
            AdapterConfig,
            "new_http_client",
            lambda self: httpx.AsyncClient(
                transport=transport,
                base_url=self.core_origin,
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ),
        )
        client = CoreAnalysisClient(
            AdapterConfig.from_values(core_origin="http://127.0.0.1:9", token_file=str(token_file))
        )
        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")

        # Direct Core owns the EGRESS gate: no ACK header on the refusal.
        direct = asyncio.run(
            _direct_core(
                fixture.app,
                "GET",
                f"/v1/sites/{fixture.site_id}/analysis-observations",
                headers=fixture.mcp_client_headers(),
            )
        )
        assert direct.status_code == 403
        assert direct.json() == {"detail": "AI_EGRESS_NOT_ALLOWED"}
        assert direct.headers.get("X-KSI-External-AI-Egress") is None

        # Every adapter read lane surfaces the same Core refusal.
        for tool, args in (
            ("ksi_list_analysis_observations", {"siteId": fixture.site_id}),
            ("ksi_list_analyses", {"siteId": fixture.site_id, "limit": 50}),
        ):
            with pytest.raises(CoreAdapterError, match="AI_EGRESS_NOT_ALLOWED"):
                asyncio.run(client.invoke(tool, dict(args)))

        # Mutation lanes are refused by Core consent: create stops at its
        # acknowledged GET preflight (no POST); readiness is itself a POST
        # read-only preflight and is refused as a POST. Neither records an
        # intent.
        intents_before = len(
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a"
            )
        )
        posts_before = len([r for r in transport.requests if r["method"] == "POST"])
        with pytest.raises(CoreAdapterError, match="AI_EGRESS_NOT_ALLOWED"):
            asyncio.run(
                client.invoke(
                    "ksi_create_analysis",
                    {
                        "siteId": fixture.site_id,
                        "workAreaId": fixture.work_area_id,
                        "baseline": baseline,
                        "current": current,
                        "idempotencyKey": CONSENT_KEY,
                    },
                )
            )
        assert len([r for r in transport.requests if r["method"] == "POST"]) == posts_before
        with pytest.raises(CoreAdapterError, match="AI_EGRESS_NOT_ALLOWED"):
            asyncio.run(
                client.invoke(
                    "ksi_check_analysis_readiness",
                    {
                        "siteId": fixture.site_id,
                        "workAreaId": fixture.work_area_id,
                        "baseline": baseline,
                        "current": current,
                    },
                )
            )
        posts_after_readiness = [r for r in transport.requests if r["method"] == "POST"]
        assert len(posts_after_readiness) == posts_before + 1
        assert posts_after_readiness[-1]["path"].endswith("/analysis-readiness")
        assert (
            len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id="org-a"
                )
            )
            == intents_before
        )
    finally:
        fixture.close()


def test_real_core_work_area_grant_denies_foreign_area_and_intent_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine identity scoped to another WorkArea cannot use this intent."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    try:
        machine_raw = fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
        other_raw = fixture.mcp_other_area_headers()["Authorization"].removeprefix("Bearer ")
        assert fixture.work_area_id == "wa-site-a-0001"
        assert other_raw != machine_raw
        from ksi_analysis_mcp.config import AdapterConfig
        from ksi_analysis_mcp.core_client import CoreAnalysisClient

        shared = _LabelTransport(fixture.app, machine_raw=machine_raw)
        monkeypatch.setattr(
            AdapterConfig,
            "new_http_client",
            lambda self: httpx.AsyncClient(
                transport=shared,
                base_url=self.core_origin,
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ),
        )
        machine_token = tmp_path / "token-machine-wa"
        machine_token.write_text(machine_raw, encoding="ascii")
        machine_token.chmod(0o600)
        other_token = tmp_path / "token-other-wa"
        other_token.write_text(other_raw, encoding="ascii")
        other_token.chmod(0o600)
        machine_client = CoreAnalysisClient(
            AdapterConfig.from_values(
                core_origin="http://127.0.0.1:9", token_file=str(machine_token)
            )
        )
        other_client = CoreAnalysisClient(
            AdapterConfig.from_values(core_origin="http://127.0.0.1:9", token_file=str(other_token))
        )
        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        created = asyncio.run(
            machine_client.invoke(
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": "real-core-scope-workarea-1",
                },
            )
        )
        analysis_id = created["analysisId"]

        intents_before = len(
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a"
            )
        )
        # Creation and readiness on the fixture's WorkArea are outside the
        # other identity's grant: Core 404, adapter surfaces the same code,
        # and no second intent is recorded.
        for tool, args in (
            (
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": OTHER_KEY,
                },
            ),
            (
                "ksi_check_analysis_readiness",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                },
            ),
        ):
            with pytest.raises(CoreAdapterError, match="ANALYSIS_RESOURCE_NOT_FOUND") as exc_info:
                asyncio.run(other_client.invoke(tool, dict(args)))
            assert other_raw not in str(exc_info.value)
            assert machine_raw not in str(exc_info.value)
        assert (
            len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id="org-a"
                )
            )
            == intents_before
        )
        # The intent scope also binds reads: the other WorkArea identity gets
        # 404 for the same analysisId on detail, result and evidence paths.
        for tool, args in (
            ("ksi_get_analysis", {"siteId": fixture.site_id, "analysisId": analysis_id}),
            ("ksi_get_analysis_result", {"siteId": fixture.site_id, "analysisId": analysis_id}),
            (
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id, "limit": 32},
            ),
        ):
            with pytest.raises(CoreAdapterError, match="ANALYSIS_RESOURCE_NOT_FOUND"):
                asyncio.run(other_client.invoke(tool, dict(args)))
        # Direct Core agrees on the detail path with no ACK header.
        direct = asyncio.run(
            _direct_core(
                fixture.app,
                "GET",
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                headers=fixture.mcp_other_area_headers(),
            )
        )
        assert direct.status_code == 404
        assert direct.json() == {"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}
        assert direct.headers.get("X-KSI-External-AI-Egress") is None
    finally:
        fixture.close()


def test_official_stdio_cross_site_evidence_fails_closed(tmp_path: Path) -> None:
    """Official SDK stdio returns the Core scoped not-found for foreign Site."""
    import socket
    import time
    from threading import Thread

    import uvicorn
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    core_socket: socket.socket | None = None
    core_server: uvicorn.Server | None = None
    core_thread: Thread | None = None
    try:
        core_socket = socket.socket()
        core_socket.bind(("127.0.0.1", 0))
        core_socket.listen(128)
        core_origin = f"http://127.0.0.1:{core_socket.getsockname()[1]}"
        core_server = uvicorn.Server(
            uvicorn.Config(fixture.app, log_level="warning", access_log=False)
        )
        core_thread = Thread(target=lambda: core_server.run(sockets=[core_socket]), daemon=True)
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive()
            time.sleep(0.02)
        assert core_server.started

        token_file = tmp_path / "mcp-stdio-token"
        token_file.write_text(
            fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer "),
            encoding="ascii",
        )
        token_file.chmod(0o600)

        async def mcp_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            import sys as _sys

            root = Path(__file__).resolve().parents[3]
            sources = [
                root / "services" / "analysis-mcp" / "src",
                root / "packages" / "event-contracts" / "src",
                root / "packages" / "domain" / "src",
            ]
            entries = ", ".join(repr(str(source)) for source in sources)
            script = (
                "import runpy, sys; "
                f"sys.path[:0] = [{entries}]; "
                "runpy.run_module('ksi_analysis_mcp.server', run_name='__main__')"
            )
            parameters = StdioServerParameters(
                command=_sys.executable,
                args=["-c", script],
                env={
                    "KSI_ANALYSIS_MCP_CORE_ORIGIN": core_origin,
                    "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
                },
            )
            async with (
                stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(name, arguments)
                assert isinstance(result.structured_content, dict)
                return {
                    "is_error": bool(result.is_error),
                    "payload": dict(result.structured_content),
                }

        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        created = asyncio.run(
            mcp_call(
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": "real-core-stdio-scope-1",
                },
            )
        )
        assert created["is_error"] is False
        analysis_id = created["payload"]["analysisId"]

        honest = asyncio.run(
            mcp_call(
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id, "limit": 32},
            )
        )
        assert honest["is_error"] is False
        assert honest["payload"]["analysisId"] == analysis_id

        refused = asyncio.run(
            mcp_call(
                "ksi_get_analysis_evidence",
                {"siteId": FOREIGN_SITE, "analysisId": analysis_id, "limit": 32},
            )
        )
        assert refused["is_error"] is True
        assert refused["payload"] == {"code": "ANALYSIS_RESOURCE_NOT_FOUND"}

        refused_detail = asyncio.run(
            mcp_call(
                "ksi_get_analysis",
                {"siteId": FOREIGN_SITE, "analysisId": analysis_id},
            )
        )
        assert refused_detail["is_error"] is True
        assert refused_detail["payload"] == {"code": "ANALYSIS_RESOURCE_NOT_FOUND"}
    finally:
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=5)
        if core_socket is not None:
            core_socket.close()
        fixture.close()


def test_real_core_dual_grant_cross_site_binding_is_intent_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same principal valid on A/B still gets 404 for A's analysis via B's path.

    Site-B is proven to exist with consent and to answer the same machine
    principal with ``200 + ALLOWED`` first, so the later B-path 404 isolates
    the ``intent.site_id`` binding in Core's ``get()``/snapshot read, not a
    missing grant or consent.
    """
    from ksi_analysis_mcp.core_client import CoreAdapterError

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    try:
        site_b_area_id, dual_raw = _setup_dual_site_and_identity(fixture)
        dual_headers = {"Authorization": "Bearer " + dual_raw}
        assert dual_raw == DUAL_TOKEN

        # B positive via actual Core: grant + consent valid, ACK present.
        direct_b_obs = asyncio.run(
            _direct_core(
                fixture.app,
                "GET",
                f"/v1/sites/{SITE_B}/analysis-observations",
                headers=dual_headers,
            )
        )
        assert direct_b_obs.status_code == 200, direct_b_obs.text
        assert direct_b_obs.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
        direct_b_list = asyncio.run(
            _direct_core(fixture.app, "GET", f"/v2/sites/{SITE_B}/analyses", headers=dual_headers)
        )
        assert direct_b_list.status_code == 200, direct_b_list.text
        assert direct_b_list.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
        assert direct_b_list.json()["siteId"] == SITE_B

        client, _transport = _client_for(
            tmp_path,
            fixture.app,
            dual_raw,
            monkeypatch,
            token_raw=dual_raw,
            token_name="token-dual",
        )
        adapter_b_obs = asyncio.run(
            client.invoke("ksi_list_analysis_observations", {"siteId": SITE_B})
        )
        assert adapter_b_obs == {"items": []}
        adapter_b_list = asyncio.run(
            client.invoke("ksi_list_analyses", {"siteId": SITE_B, "limit": 50})
        )
        assert adapter_b_list["siteId"] == SITE_B
        assert adapter_b_list["items"] == []

        # Create in A with the same dual principal and keep the A positive.
        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        created = asyncio.run(
            client.invoke(
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": DUAL_CREATE_KEY,
                },
            )
        )
        analysis_id = created["analysisId"]
        assert created["siteId"] == fixture.site_id
        assert created["workAreaId"] == fixture.work_area_id
        assert site_b_area_id != fixture.work_area_id
        detail_a = asyncio.run(
            client.invoke(
                "ksi_get_analysis", {"siteId": fixture.site_id, "analysisId": analysis_id}
            )
        )
        assert detail_a["analysisId"] == analysis_id
        assert detail_a["siteId"] == fixture.site_id
        evidence_a = asyncio.run(
            client.invoke(
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id, "limit": 32},
            )
        )
        assert evidence_a["analysisId"] == analysis_id

        # Same analysisId via B's path: actual Core 404 with no ACK, even
        # though grants and consent pass for B. This is the intent↔Site bind.
        for suffix in ("", "/evidence"):
            direct = asyncio.run(
                _direct_core(
                    fixture.app,
                    "GET",
                    f"/v2/sites/{SITE_B}/analyses/{analysis_id}{suffix}",
                    headers=dual_headers,
                )
            )
            assert direct.status_code == 404, (suffix, direct.text)
            assert direct.json() == {"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}
            assert direct.headers.get("X-KSI-External-AI-Egress") is None

        for tool, args in (
            ("ksi_get_analysis", {"siteId": SITE_B, "analysisId": analysis_id}),
            ("ksi_get_analysis_result", {"siteId": SITE_B, "analysisId": analysis_id}),
            (
                "ksi_get_analysis_evidence",
                {"siteId": SITE_B, "analysisId": analysis_id, "limit": 32},
            ),
        ):
            with pytest.raises(CoreAdapterError, match="ANALYSIS_RESOURCE_NOT_FOUND") as exc_info:
                asyncio.run(client.invoke(tool, dict(args)))
            assert dual_raw not in str(exc_info.value)
    finally:
        fixture.close()


def test_official_stdio_dual_grant_cross_site_evidence_fails_closed(tmp_path: Path) -> None:
    """Official stdio with a dual-grant principal proves B 200 then B-path 404."""
    import socket
    import time
    from threading import Thread

    import uvicorn
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    core_socket: socket.socket | None = None
    core_server: uvicorn.Server | None = None
    core_thread: Thread | None = None
    try:
        _site_b_area_id, dual_raw = _setup_dual_site_and_identity(fixture)
        core_socket = socket.socket()
        core_socket.bind(("127.0.0.1", 0))
        core_socket.listen(128)
        core_origin = f"http://127.0.0.1:{core_socket.getsockname()[1]}"
        core_server = uvicorn.Server(
            uvicorn.Config(fixture.app, log_level="warning", access_log=False)
        )
        core_thread = Thread(target=lambda: core_server.run(sockets=[core_socket]), daemon=True)
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive()
            time.sleep(0.02)
        assert core_server.started

        token_file = tmp_path / "mcp-stdio-dual-token"
        token_file.write_text(dual_raw, encoding="ascii")
        token_file.chmod(0o600)

        async def mcp_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            import sys as _sys

            root = Path(__file__).resolve().parents[3]
            sources = [
                root / "services" / "analysis-mcp" / "src",
                root / "packages" / "event-contracts" / "src",
                root / "packages" / "domain" / "src",
            ]
            entries = ", ".join(repr(str(source)) for source in sources)
            script = (
                "import runpy, sys; "
                f"sys.path[:0] = [{entries}]; "
                "runpy.run_module('ksi_analysis_mcp.server', run_name='__main__')"
            )
            parameters = StdioServerParameters(
                command=_sys.executable,
                args=["-c", script],
                env={
                    "KSI_ANALYSIS_MCP_CORE_ORIGIN": core_origin,
                    "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
                },
            )
            async with (
                stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(name, arguments)
                assert isinstance(result.structured_content, dict)
                return {
                    "is_error": bool(result.is_error),
                    "payload": dict(result.structured_content),
                }

        # B positive on the stdio surface first: valid grant + consent.
        b_obs = asyncio.run(mcp_call("ksi_list_analysis_observations", {"siteId": SITE_B}))
        assert b_obs["is_error"] is False
        assert b_obs["payload"] == {"items": []}
        b_list = asyncio.run(mcp_call("ksi_list_analyses", {"siteId": SITE_B, "limit": 50}))
        assert b_list["is_error"] is False
        assert b_list["payload"]["siteId"] == SITE_B

        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        created = asyncio.run(
            mcp_call(
                "ksi_create_analysis",
                {
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "baseline": baseline,
                    "current": current,
                    "idempotencyKey": DUAL_STDIO_CREATE_KEY,
                },
            )
        )
        assert created["is_error"] is False
        analysis_id = created["payload"]["analysisId"]

        honest = asyncio.run(
            mcp_call(
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id, "limit": 32},
            )
        )
        assert honest["is_error"] is False
        assert honest["payload"]["analysisId"] == analysis_id

        for tool in ("ksi_get_analysis", "ksi_get_analysis_result", "ksi_get_analysis_evidence"):
            args: dict[str, Any] = {"siteId": SITE_B, "analysisId": analysis_id}
            if tool == "ksi_get_analysis_evidence":
                args["limit"] = 32
            refused = asyncio.run(mcp_call(tool, args))
            assert refused["is_error"] is True, tool
            assert refused["payload"] == {"code": "ANALYSIS_RESOURCE_NOT_FOUND"}, tool
    finally:
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=5)
        if core_socket is not None:
            core_socket.close()
        fixture.close()
