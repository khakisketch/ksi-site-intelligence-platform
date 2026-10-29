"""Token-continuity binding for the Analysis MCP adapter.

A machine-acknowledged preflight GET and every later mutation inside one
logical tool invocation must present the same credential snapshot. The
credential file is read once per invocation and never reread in between, so
an owner-side rotation mid-call cannot turn an acknowledged machine
preflight into a human POST, and a statically misconfigured human token
fails before any mutation. The next independent invocation snapshots again.

The local fixture reproduces Core's ack semantics (verified against Core
source: spatial_tasks.headers(), guard_external_ai_egress(), and the delta
consent() helper emit ``X-KSI-External-AI-Egress: ALLOWED`` only for the
dedicated ``ANALYSIS_MCP_CLIENT`` principal; a scoped human OPERATOR read or
mutation succeeds without that header). Auth values are captured only as
generated fixture labels (``machine``/``human``/``unknown``), never raw.
"""

from __future__ import annotations

import asyncio
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

import pytest

SITE = "site-a"
AREA = "area-a"
PUB = "pub-01"
TASK_ID = "st-" + "ab" * 16
MACHINE = "tk-fixture-machine-aaa"
HUMAN = "tk-fixture-human-bbb"
UNKNOWN = "tk-fixture-unknown-zzz"

BASELINE = {
    "workOrderId": "wo-1",
    "submissionRef": "ers-v1-" + "11" * 32,
    "revision": 1,
}
CURRENT = {
    "workOrderId": "wo-1",
    "submissionRef": "ers-v1-" + "22" * 32,
    "revision": 2,
}

CALC = "sha256:" + "aa" * 32
NUMERIC = "sha256:" + "bb" * 32
COVERAGE = "sha256:" + "cc" * 32
POLICY = "sha256:" + "dd" * 32


def _task_view() -> dict[str, Any]:
    return {
        "task": {
            "taskId": TASK_ID,
            "siteId": SITE,
            "revision": 1,
            "selection": {"purpose": "CLARIFY"},
            "analysisId": None,
            "executionRequested": False,
            "createdAt": "2026-10-26T00:00:00Z",
            "expiresAt": "2026-11-02T00:00:00Z",
        },
        "state": "AREA_REQUIRED",
        "selectionHref": f"/sites/{SITE}/spatial-tasks/{TASK_ID}",
        "analysisHref": None,
        "readiness": None,
        "analysis": None,
    }


def _analysis_view() -> dict[str, Any]:
    return {
        "analysisId": "an-1",
        "siteId": SITE,
        "workAreaId": AREA,
        "baseline": BASELINE,
        "current": CURRENT,
        "executionState": "QUEUED",
        "suitabilityState": "REMEDIATION_REQUIRED",
        "blockers": [],
        "result": None,
        "evidenceRevision": 1,
        "evidenceDigest": "sha256:" + "ee" * 32,
        "evidenceHref": f"/v2/sites/{SITE}/analyses/an-1/evidence",
        "coverageHref": None,
        "createdAt": "2026-10-26T00:00:00Z",
    }


def _intent_view() -> dict[str, Any]:
    from ksi_event_contracts.external_delta_publication_api import (
        DeltaPublicationIntentViewV1,
    )

    return DeltaPublicationIntentViewV1.model_validate(
        {
            "publicationId": PUB,
            "organizationId": "org-a",
            "siteId": SITE,
            "workAreaId": AREA,
            "sourceContractVersion": "external-relative-volume-calculation-report.v2",
            "outputId": "delta-out-pub-01",
            "uploadFenceId": "upload-fence-pub-01",
            "sourceCalculationIdentityDigest": CALC,
            "sourceNumericResultIdentityDigest": NUMERIC,
            "sourceCoverageWitnessDigest": COVERAGE,
            "gridRows": 2,
            "gridColumns": 2,
            "issuedAt": "2026-10-26T00:00:00Z",
            "expiresAt": "2026-10-27T00:00:00Z",
            "policyDigest": POLICY,
            "status": "PENDING",
            "leaseGeneration": 0,
            "leaseHolderPrincipalId": None,
            "leaseHolderInstanceId": None,
            "leaseIssuedAt": None,
            "leaseExpiresAt": None,
        }
    ).model_dump(by_alias=True, mode="json")


TASK_CREATE_ARGS = {
    "siteId": SITE,
    "idempotencyKey": "race-key-1",
    "request": {"purpose": "CLARIFY"},
}
TASK_SELECT_ARGS = {
    "siteId": SITE,
    "taskId": TASK_ID,
    "request": {"expectedRevision": 1, "purpose": "CLARIFY"},
}
TASK_RUN_ARGS = {
    "siteId": SITE,
    "taskId": TASK_ID,
    "request": {"expectedRevision": 1},
}
ANALYSIS_CREATE_ARGS = {
    "siteId": SITE,
    "workAreaId": AREA,
    "baseline": BASELINE,
    "current": CURRENT,
    "idempotencyKey": "analysis-key-1",
}
DELTA_CREATE_ARGS = {
    "siteId": SITE,
    "workAreaId": AREA,
    "publicationId": PUB,
    "sourceCalculationIdentityDigest": CALC,
    "sourceNumericResultIdentityDigest": NUMERIC,
    "sourceCoverageWitnessDigest": COVERAGE,
    "lifetimeSeconds": 3600,
}

MUTATING_CASES = [
    ("ksi_create_spatial_task", TASK_CREATE_ARGS),
    ("ksi_select_spatial_task", TASK_SELECT_ARGS),
    ("ksi_run_spatial_task", TASK_RUN_ARGS),
    ("ksi_create_analysis", ANALYSIS_CREATE_ARGS),
    ("ksi_create_delta_publication", DELTA_CREATE_ARGS),
]


class FixtureState(dict[str, Any]):
    """Shared mutable fixture record (requests carry labels, never tokens)."""


def _label(auth: str | None) -> str:
    if auth == "Bearer " + MACHINE:
        return "machine"
    if auth == "Bearer " + HUMAN:
        return "human"
    return "unknown"


def _serve(tmp_path: Path, state: FixtureState) -> tuple[Any, ThreadingHTTPServer, Thread]:
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAnalysisClient

    token_file = tmp_path / "token"
    token_file.write_text(state["initial_token"], encoding="ascii")
    token_file.chmod(0o600)
    state["token_file"] = token_file

    class CoreHandler(BaseHTTPRequestHandler):
        def _send(self, payload: dict[str, Any], *, ack: bool, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            if ack:
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, status: int, detail: str) -> None:
            body = json.dumps({"detail": detail}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _principal(self) -> str:
            return _label(self.headers.get("Authorization"))

        def do_GET(self) -> None:  # noqa: N802
            who = self._principal()
            state["requests"].append({"method": "GET", "path": self.path, "who": who})
            if state.get("rewrite_on_get") and not state.get("rewritten"):
                state["rewritten"] = True
                tf: Path = state["token_file"]
                tf.write_text(state["rewrite_on_get"], encoding="ascii")
                tf.chmod(0o600)
            if who == "unknown":
                self._fail(401, "bad token")
                return
            # Core: scoped human reads succeed without the machine ack.
            ack = who == "machine"
            if self.path.endswith("/analysis-observations"):
                self._send({"items": []}, ack=ack)
            elif self.path.endswith("/options?offset=0"):
                self._send(
                    {"siteId": SITE, "areas": [], "observations": [], "nextOffset": None},
                    ack=ack,
                )
            elif "/spatial-tasks/" in self.path:
                self._send(_task_view(), ack=ack)
            elif self.path.endswith("/bytes?offset=0&length=16"):
                raw = b"0123456789abcdef"
                self._send(
                    {
                        "publicationId": PUB,
                        "offset": 0,
                        "contentBase64": base64.b64encode(raw).decode("ascii"),
                    },
                    ack=ack,
                )
            else:
                self._fail(404, "nope")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw_in = self.rfile.read(length)
            try:
                body_in = json.loads(raw_in) if raw_in else {}
            except ValueError:
                body_in = {}
            who = self._principal()
            state["requests"].append(
                {
                    "method": "POST",
                    "path": self.path,
                    "who": who,
                    "idempotencyKey": self.headers.get("Idempotency-Key"),
                }
            )
            if who == "unknown":
                self._fail(401, "bad token")
                return
            if state.get("revoke_on_post"):
                # Core independently enforces current consent on the POST
                # itself: no mutation, no machine ack, honest typed error.
                self._fail(403, "AI_EGRESS_NOT_ALLOWED")
                return
            # Core: both machine and scoped-human POSTs mutate; only the
            # machine reply carries the egress acknowledgment.
            state["mutations"][who] += 1
            ack = who == "machine"
            if self.path.endswith("/delta-publications"):
                assert set(body_in) == {
                    "publicationId",
                    "sourceCalculationIdentityDigest",
                    "sourceNumericResultIdentityDigest",
                    "sourceCoverageWitnessDigest",
                    "lifetimeSeconds",
                }, body_in
                self._send(_intent_view(), ack=ack, status=200)
            elif self.path.endswith("/spatial-tasks"):
                self._send(_task_view(), ack=ack, status=201)
            elif self.path.endswith(("/selection", "/readiness", "/run")):
                self._send(_task_view(), ack=ack, status=200)
            elif self.path.endswith("/analyses"):
                self._send(_analysis_view(), ack=ack, status=202)
            else:
                self._fail(404, "nope")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}",
            token_file=str(token_file),
            console_origin="http://localhost:3000",
        )
    )
    return client, server, thread


def _stop(server: ThreadingHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _posts(state: FixtureState) -> list[dict[str, Any]]:
    return [r for r in state["requests"] if r["method"] == "POST"]


@pytest.mark.parametrize(("tool", "args"), MUTATING_CASES)
def test_rotation_between_preflight_and_post_keeps_snapshot_identity(
    tmp_path: Path, tool: str, args: dict[str, Any]
) -> None:
    """A mid-call credential rotation must not swap the POST identity."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    state: FixtureState = FixtureState(
        initial_token=MACHINE,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
        rewrite_on_get=HUMAN,
        rewritten=False,
    )
    client, server, thread = _serve(tmp_path, state)
    try:
        result = asyncio.run(client.invoke(tool, dict(args)))
        # The rotation demonstrably happened but was not picked up mid-call.
        assert state["rewritten"] is True
        assert state["token_file"].read_text(encoding="ascii") == HUMAN
        posts = _posts(state)
        assert len(posts) == 1
        # Preflight and mutation present the identical snapshot credential.
        assert posts[0]["who"] == "machine"
        assert state["mutations"] == {"machine": 1, "human": 0, "unknown": 0}
        assert tool != "ksi_create_spatial_task" or result["task"]["taskId"] == TASK_ID

        # The next independent invocation picks up the rotation: with the
        # human credential now on disk the preflight fails before any POST.
        state["requests"].clear()
        state["mutations"] = {"machine": 0, "human": 0, "unknown": 0}
        with pytest.raises(CoreAdapterError, match="CORE_EGRESS_ACKNOWLEDGMENT_MISSING"):
            asyncio.run(client.invoke(tool, dict(args)))
        assert _posts(state) == []
        assert state["mutations"] == {"machine": 0, "human": 0, "unknown": 0}
    finally:
        _stop(server, thread)


@pytest.mark.parametrize(("tool", "args"), MUTATING_CASES)
@pytest.mark.parametrize("token", [HUMAN, UNKNOWN])
def test_static_wrong_identity_blocked_before_any_mutation(
    tmp_path: Path, tool: str, args: dict[str, Any], token: str
) -> None:
    """A wrong credential fails the acknowledged preflight before any POST."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    state: FixtureState = FixtureState(
        initial_token=token,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
    )
    client, server, thread = _serve(tmp_path, state)
    try:
        with pytest.raises(CoreAdapterError) as exc_info:
            asyncio.run(client.invoke(tool, dict(args)))
        # No raw credential material ever surfaces in the typed error.
        assert "tk-fixture" not in str(exc_info.value)
        assert _posts(state) == []
        assert state["mutations"] == {"machine": 0, "human": 0, "unknown": 0}
        if token == HUMAN:
            # A scoped human identity is refused for lack of machine ack,
            # not silently mutated: Core would have mutated this POST.
            assert exc_info.value.code == "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"
        else:
            assert exc_info.value.code == "CORE_AUTHENTICATION_FAILED"
    finally:
        _stop(server, thread)


@pytest.mark.parametrize(("tool", "args"), MUTATING_CASES)
def test_revoked_consent_on_post_fails_closed_without_mutation(
    tmp_path: Path, tool: str, args: dict[str, Any]
) -> None:
    """The POST independently enforces current consent; no mutation occurs."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    state: FixtureState = FixtureState(
        initial_token=MACHINE,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
        revoke_on_post=True,
    )
    client, server, thread = _serve(tmp_path, state)
    try:
        with pytest.raises(CoreAdapterError, match="AI_EGRESS_NOT_ALLOWED"):
            asyncio.run(client.invoke(tool, dict(args)))
        # The preflight was acknowledged, but the consent gate moved before
        # the POST: exactly one POST was attempted and nothing mutated.
        assert len(_posts(state)) == 1
        assert state["mutations"] == {"machine": 0, "human": 0, "unknown": 0}
    finally:
        _stop(server, thread)


def test_concurrent_invocations_do_not_share_snapshot(tmp_path: Path) -> None:
    """Two overlapping invocations on one client keep their own credential."""
    state: FixtureState = FixtureState(
        initial_token=MACHINE,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
        rewrite_on_get=HUMAN,
        rewritten=False,
    )
    client, server, thread = _serve(tmp_path, state)
    assert not any("token" in key.lower() for key in vars(client))
    try:

        async def main() -> tuple[Any, Any]:
            from ksi_analysis_mcp.core_client import CoreAdapterError

            first = asyncio.ensure_future(
                client.invoke(
                    "ksi_create_spatial_task",
                    {**TASK_CREATE_ARGS, "idempotencyKey": "concurrent-1"},
                )
            )
            # Wait until the first preflight GET has landed (which rotates
            # the file to HUMAN), then start the second invocation.
            for _ in range(1000):
                if any(r["method"] == "GET" for r in state["requests"]):
                    break
                await asyncio.sleep(0.005)
            second = asyncio.ensure_future(
                client.invoke(
                    "ksi_create_spatial_task",
                    {**TASK_CREATE_ARGS, "idempotencyKey": "concurrent-2"},
                )
            )
            pair = await asyncio.gather(first, second, return_exceptions=True)
            assert not isinstance(pair[1], dict)
            assert isinstance(pair[1], CoreAdapterError)
            return pair[0], pair[1]

        first_result, second_error = asyncio.run(main())
        assert first_result["task"]["taskId"] == TASK_ID
        assert second_error.code == "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"
        assert "tk-fixture" not in str(second_error)
        by_key = {p["idempotencyKey"]: p["who"] for p in _posts(state)}
        # The first call snapshots MACHINE before the rotation and mutates
        # once as machine; the second call snapshots HUMAN after it and is
        # refused before any POST. Neither borrows the other's credential.
        assert by_key == {"concurrent-1": "machine"}, by_key
        # The machine call mutated exactly once as machine; no human POST
        # from either call ever mutated.
        assert state["mutations"] == {"machine": 1, "human": 0, "unknown": 0}
    finally:
        _stop(server, thread)


def test_snapshot_read_exactly_once_per_invoke(tmp_path: Path, monkeypatch: Any) -> None:
    """Hard-timing seam: one file read per logical invocation, no reread."""
    from ksi_analysis_mcp.config import AdapterConfig

    state: FixtureState = FixtureState(
        initial_token=MACHINE,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
        rewrite_on_get=HUMAN,
        rewritten=False,
    )
    client, server, thread = _serve(tmp_path, state)
    original = AdapterConfig.read_token
    calls: list[str] = []

    def counting(self: Any) -> str:
        value = original(self)
        calls.append(value)
        return value

    monkeypatch.setattr(AdapterConfig, "read_token", counting)
    try:
        asyncio.run(client.invoke("ksi_create_spatial_task", dict(TASK_CREATE_ARGS)))
        assert calls == [MACHINE]
        posts = _posts(state)
        assert len(posts) == 1 and posts[0]["who"] == "machine"
    finally:
        _stop(server, thread)


def test_read_paths_and_scoped_reads_unchanged_with_snapshot(tmp_path: Path) -> None:
    """Reads keep working with the single snapshot; scope params pass through."""
    state: FixtureState = FixtureState(
        initial_token=MACHINE,
        requests=[],
        mutations={"machine": 0, "human": 0, "unknown": 0},
    )
    client, server, thread = _serve(tmp_path, state)
    try:
        assert asyncio.run(
            client.invoke("ksi_list_analysis_observations", {"siteId": SITE})
        ) == {"items": []}
        task = asyncio.run(
            client.invoke("ksi_get_spatial_task", {"siteId": SITE, "taskId": TASK_ID})
        )
        assert task["task"]["taskId"] == TASK_ID
        options = asyncio.run(
            client.invoke(
                "ksi_get_spatial_task_options",
                {"siteId": SITE, "taskId": TASK_ID, "offset": 0},
            )
        )
        assert options["siteId"] == SITE
        chunk = asyncio.run(
            client.invoke(
                "ksi_read_delta_publication_bytes",
                {
                    "siteId": SITE,
                    "workAreaId": AREA,
                    "publicationId": PUB,
                    "offset": 0,
                    "length": 16,
                },
            )
        )
        assert base64.b64decode(chunk["contentBase64"]) == b"0123456789abcdef"
        paths = [r["path"] for r in state["requests"]]
        assert f"/v1/sites/{SITE}/analysis-observations" in paths
        assert any(p.endswith("/options?offset=0") for p in paths)
        assert any(p.endswith("/bytes?offset=0&length=16") for p in paths)
        assert all(r["who"] == "machine" for r in state["requests"])
        assert state["mutations"] == {"machine": 0, "human": 0, "unknown": 0}
        # Query parsing uses the exact scope the adapter was given.
        for raw in ("/v1/sites/site-a/spatial-tasks/" + TASK_ID + "/options?offset=0",):
            parts = urlsplit(raw)
            assert parts.query == "offset=0"
    finally:
        _stop(server, thread)
