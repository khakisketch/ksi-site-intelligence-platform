"""Closed contract tests for the additive delta-publication MCP tools.

Real loopback HTTP only (no external network). Every Core reply must carry the
machine-channel ``X-KSI-External-AI-Egress: ALLOWED`` marker; byte chunks are
opaque worker output that the adapter passes through without recomputation or
TIFF parsing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

SITE = "site-a"
AREA = "area-a"
PUB = "pub-01"
CALC = "sha256:" + "aa" * 32
NUMERIC = "sha256:" + "bb" * 32
COVERAGE = "sha256:" + "cc" * 32
POLICY = "sha256:" + "dd" * 32
WRONG_DIGEST = "sha256:" + "ff" * 32

CREATE_ARGUMENTS = {
    "siteId": SITE,
    "workAreaId": AREA,
    "publicationId": PUB,
    "sourceCalculationIdentityDigest": CALC,
    "sourceNumericResultIdentityDigest": NUMERIC,
    "sourceCoverageWitnessDigest": COVERAGE,
    "lifetimeSeconds": 3600,
}


def _digest(payload: dict[str, Any]) -> str:
    from ksi_domain.canonical_json import canonical_json_bytes

    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _intent_payload(**overrides: Any) -> dict[str, Any]:
    from ksi_event_contracts.external_delta_publication_api import (
        DeltaPublicationIntentViewV1,
    )

    base: dict[str, Any] = {
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
    base.update(overrides)
    return DeltaPublicationIntentViewV1.model_validate(base).model_dump(
        by_alias=True, mode="json"
    )


def _descriptor_payload() -> dict[str, Any]:
    from ksi_event_contracts.external_delta_publication_api import DeltaPublicationViewV1
    from ksi_event_contracts.external_masked_volume import DeltaRasterPublicationV1

    transform = [1.0, 0.0, 0.0, 0.0, -1.0, 2.0]
    descriptor: dict[str, Any] = {
        "publicationId": PUB,
        "organizationId": "org-a",
        "siteId": SITE,
        "workAreaId": AREA,
        "sourceContractVersion": "external-relative-volume-calculation-report.v2",
        "sourceCalculationIdentityDigest": CALC,
        "sourceNumericResultIdentityDigest": NUMERIC,
        "sourceCoverageWitnessDigest": COVERAGE,
        "deltaSign": "CURRENT_MINUS_BASELINE",
        "gridRows": 2,
        "gridColumns": 2,
        "transform": transform,
        "transformDigest": _digest({"transform": transform}),
        "gridCrsIdentifier": "EPSG:5186",
        "gridCrsDigest": POLICY,
        "bounds": [0.0, 0.0, 2.0, 2.0],
        "verticalUnit": "metre",
        "dtype": "FLOAT64",
        "outputId": "delta-out-pub-01",
        "outputSha256": "sha256:" + "ee" * 32,
        "outputSizeBytes": 16,
        "issuedAt": "2026-10-26T00:00:00Z",
        "expiresAt": "2026-10-27T00:00:00Z",
        "publicationPolicyDigest": POLICY,
        "publicationDigest": None,
    }
    sealed = DeltaRasterPublicationV1.model_validate(descriptor).sealed()
    view = {
        "publicationId": PUB,
        "organizationId": "org-a",
        "siteId": SITE,
        "workAreaId": AREA,
        "outputId": "delta-out-pub-01",
        "issuedAt": "2026-10-26T00:00:00Z",
        "expiresAt": "2026-10-27T00:00:00Z",
        "policyDigest": POLICY,
        "status": "PUBLISHED",
        "reason": None,
        "descriptor": sealed.model_dump(by_alias=True, mode="json"),
    }
    return DeltaPublicationViewV1.model_validate(view).model_dump(
        by_alias=True, mode="json"
    )


_CHUNK = b"0123456789abcdef"


def _bytes_payload(offset: int = 0, length: int = 16, **overrides: Any) -> dict[str, Any]:
    from ksi_event_contracts.external_delta_publication_api import DeltaPublicationBytesV1

    base: dict[str, Any] = {
        "publicationId": PUB,
        "offset": offset,
        "contentBase64": base64.b64encode(_CHUNK[:length]).decode("ascii"),
    }
    base.update(overrides)
    return DeltaPublicationBytesV1.model_validate(base).model_dump(
        by_alias=True, mode="json"
    )


def _client(tmp_path: Path, handler: type[BaseHTTPRequestHandler]):
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAnalysisClient

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("delta-test-token", encoding="ascii")
    token_file.chmod(0o600)
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}",
            token_file=str(token_file),
        )
    )
    return client, server, thread


def _stop(server: ThreadingHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_delta_create_posts_source_only_body_and_requires_machine_ack(
    tmp_path: Path,
) -> None:
    """The intent POST carries sources only; Core resolves all grid facts."""
    import json

    from ksi_analysis_mcp.core_client import CoreAdapterError

    seen: dict[str, Any] = {}

    class CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            seen["path"] = self.path
            seen["headers"] = {k.lower(): v for k, v in self.headers.items()}
            seen["body"] = json.loads(self.rfile.read(length))
            if seen["body"].get("publicationId") == "pub-noack-scenario":
                payload = _intent_payload(publicationId="pub-noack-scenario")
            elif seen["body"].get("publicationId") == "pub-wrongdigest":
                payload = _intent_payload(
                    publicationId="pub-wrongdigest",
                    sourceNumericResultIdentityDigest=WRONG_DIGEST,
                )
            else:
                payload = _intent_payload()
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            if seen["body"].get("publicationId") != "pub-noack-scenario":
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        result = asyncio.run(
            client.invoke("ksi_create_delta_publication", dict(CREATE_ARGUMENTS))
        )
        assert result["publicationId"] == PUB
        assert result["siteId"] == SITE
        assert seen["path"] == f"/v1/sites/{SITE}/work-areas/{AREA}/delta-publications"
        assert set(seen["body"]) == {
            "publicationId",
            "sourceCalculationIdentityDigest",
            "sourceNumericResultIdentityDigest",
            "sourceCoverageWitnessDigest",
            "lifetimeSeconds",
        }
        assert "x-ksi-access-purpose" not in seen["headers"]
        assert seen["headers"]["authorization"] == "Bearer delta-test-token"
        with pytest.raises(CoreAdapterError, match="CORE_EGRESS_ACKNOWLEDGMENT_MISSING"):
            asyncio.run(
                client.invoke(
                    "ksi_create_delta_publication",
                    {**CREATE_ARGUMENTS, "publicationId": "pub-noack-scenario"},
                )
            )
        # A right-scope reply bound to the wrong numeric result is not valid.
        with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
            asyncio.run(
                client.invoke(
                    "ksi_create_delta_publication",
                    {**CREATE_ARGUMENTS, "publicationId": "pub-wrongdigest"},
                )
            )
    finally:
        _stop(server, thread)


def test_delta_create_rejects_nonfinite_lifetime_and_unsafe_ids_before_network(
    tmp_path: Path,
) -> None:
    from ksi_analysis_mcp.core_client import CoreAdapterError

    calls = 0

    class CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal calls
            calls += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        # Only a finite 32-bit protocol bound applies client-side; retention
        # ceilings belong to Core policy, never to a guessed MCP lifetime cap.
        for bad_lifetime in (0, -1, 2**31, True, "3600", 3.5):
            with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
                asyncio.run(
                    client.invoke(
                        "ksi_create_delta_publication",
                        {**CREATE_ARGUMENTS, "lifetimeSeconds": bad_lifetime},
                    )
                )
        for bad in ("../x", "pub/01", "http://x", "a" * 129):
            with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
                asyncio.run(
                    client.invoke(
                        "ksi_create_delta_publication",
                        {**CREATE_ARGUMENTS, "publicationId": bad},
                    )
                )
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            asyncio.run(
                client.invoke(
                    "ksi_create_delta_publication",
                    {**CREATE_ARGUMENTS, "sourceCoverageWitnessDigest": "not-a-digest"},
                )
            )
        assert calls == 0
    finally:
        _stop(server, thread)


def test_delta_create_maps_native_core_errors_honestly(tmp_path: Path) -> None:
    import json

    from ksi_analysis_mcp.core_client import CoreAdapterError

    class CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body_in = json.loads(self.rfile.read(length))
            if body_in.get("publicationId") == "denied":
                body = json.dumps({"detail": "AI_EGRESS_NOT_ALLOWED"}).encode()
                self.send_response(403)
            else:
                body = json.dumps(
                    {"detail": "DELTA_SOURCE_OR_AUTHORITY_UNAVAILABLE"}
                ).encode()
                self.send_response(409)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        with pytest.raises(
            CoreAdapterError, match="DELTA_SOURCE_OR_AUTHORITY_UNAVAILABLE"
        ):
            asyncio.run(
                client.invoke("ksi_create_delta_publication", dict(CREATE_ARGUMENTS))
            )
        with pytest.raises(CoreAdapterError, match="AI_EGRESS_NOT_ALLOWED"):
            asyncio.run(
                client.invoke(
                    "ksi_create_delta_publication",
                    {**CREATE_ARGUMENTS, "publicationId": "denied"},
                )
            )
    finally:
        _stop(server, thread)


def test_delta_get_enforces_scope_echo_and_rejects_malicious_responses(
    tmp_path: Path,
) -> None:
    import json

    from ksi_analysis_mcp.core_client import CoreAdapterError

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.endswith("/pub-wrongsite"):
                payload = {**_descriptor_payload(), "siteId": "site-other"}
            elif self.path.endswith("/pub-unknownfield"):
                payload = {**_descriptor_payload(), "unexpectedField": True}
            elif self.path.endswith("/pub-nestedorg"):
                payload = _descriptor_payload()
                payload["descriptor"]["organizationId"] = "org-other"
            elif self.path.endswith("/pub-nestedoutput"):
                payload = _descriptor_payload()
                payload["descriptor"]["outputId"] = "delta-out-someone-else"
            elif self.path.endswith("/pub-nestedpolicy"):
                payload = _descriptor_payload()
                payload["descriptor"]["publicationPolicyDigest"] = WRONG_DIGEST
            elif self.path.endswith("/pub-noack"):
                payload = _descriptor_payload()
            elif self.path.endswith("/pub-missing"):
                body = json.dumps(
                    {"detail": "DELTA_PUBLICATION_NOT_AVAILABLE"}
                ).encode()
                self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                payload = _descriptor_payload()
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            if not self.path.endswith("/pub-noack"):
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        result = asyncio.run(
            client.invoke(
                "ksi_get_delta_publication",
                {"siteId": SITE, "workAreaId": AREA, "publicationId": PUB},
            )
        )
        assert result["descriptor"]["dtype"] == "FLOAT64"
        for pub_id, code in (
            ("pub-wrongsite", "INVALID_CORE_RESPONSE"),
            ("pub-unknownfield", "INVALID_CORE_RESPONSE"),
            ("pub-nestedorg", "INVALID_CORE_RESPONSE"),
            ("pub-nestedoutput", "INVALID_CORE_RESPONSE"),
            ("pub-nestedpolicy", "INVALID_CORE_RESPONSE"),
            ("pub-noack", "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"),
            ("pub-missing", "DELTA_PUBLICATION_NOT_AVAILABLE"),
        ):
            with pytest.raises(CoreAdapterError, match=code):
                asyncio.run(
                    client.invoke(
                        "ksi_get_delta_publication",
                        {"siteId": SITE, "workAreaId": AREA, "publicationId": pub_id},
                    )
                )
    finally:
        _stop(server, thread)


def test_delta_bytes_pass_through_opaque_chunk_and_deny_tampering(
    tmp_path: Path,
) -> None:
    import json

    from ksi_analysis_mcp.core_client import CoreAdapterError

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            offset = int(query.get("offset", ["0"])[0])
            pub = parts.path.split("/")[-2]
            if parts.path.endswith("/pub-badoffset/bytes"):
                payload = _bytes_payload(offset=offset + 8)
                payload["publicationId"] = pub
            elif parts.path.endswith("/pub-badbase64/bytes"):
                payload = {"publicationId": pub, "offset": offset,
                           "contentBase64": "!!!not-base64!!!"}
            elif parts.path.endswith("/pub-oversized/bytes"):
                payload = _bytes_payload(offset=offset, length=16)
                payload["publicationId"] = pub
                payload["contentBase64"] = base64.b64encode(b"y" * 17).decode()
            elif parts.path.endswith("/pub-unknownfield/bytes"):
                payload = {**_bytes_payload(offset=offset), "extra": 1}
                payload["publicationId"] = pub
            elif parts.path.endswith("/pub-padbits/bytes"):
                # Valid base64 with non-zero pad bits; non-canonical encoding.
                payload = {"publicationId": pub, "offset": offset,
                           "contentBase64": "AB=="}
            elif parts.path.endswith("/pub-short/bytes"):
                payload = {"detail": "DELTA_READ_RANGE_INVALID"}
                body = json.dumps(payload).encode()
                self.send_response(422)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                payload = _bytes_payload(offset=offset, length=16)
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        result = asyncio.run(
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
        # Opaque passthrough: the exact worker chunk, never recomputed.
        assert result["contentBase64"] == base64.b64encode(_CHUNK).decode("ascii")
        assert base64.b64decode(result["contentBase64"]) == _CHUNK
        for pub_id, code in (
            ("pub-badoffset", "INVALID_CORE_RESPONSE"),
            ("pub-badbase64", "INVALID_CORE_RESPONSE"),
            ("pub-padbits", "INVALID_CORE_RESPONSE"),
            ("pub-oversized", "INVALID_CORE_RESPONSE"),
            ("pub-unknownfield", "INVALID_CORE_RESPONSE"),
            ("pub-short", "DELTA_READ_RANGE_INVALID"),
        ):
            with pytest.raises(CoreAdapterError, match=code):
                asyncio.run(
                    client.invoke(
                        "ksi_read_delta_publication_bytes",
                        {
                            "siteId": SITE,
                            "workAreaId": AREA,
                            "publicationId": pub_id,
                            "offset": 0,
                            "length": 16,
                        },
                    )
                )
        # Range caps are enforced before any network use; bools and strings
        # must not coerce into a range.
        for bad_range in (
            {"offset": True, "length": 16},
            {"offset": 0, "length": True},
            {"offset": "0", "length": 16},
            {"offset": 0, "length": "16"},
            {"offset": -1, "length": 16},
            {"offset": 0, "length": 0},
            {"offset": 0, "length": 1024 * 1024 + 1},
        ):
            with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
                asyncio.run(
                    client.invoke(
                        "ksi_read_delta_publication_bytes",
                        {
                            "siteId": SITE,
                            "workAreaId": AREA,
                            "publicationId": PUB,
                            **bad_range,
                        },
                    )
                )
    finally:
        _stop(server, thread)


def test_delta_tools_leave_established_analysis_tools_unchanged(tmp_path: Path) -> None:
    """The seven frozen tools keep their shapes and behavior."""
    import json

    from ksi_analysis_mcp.core_client import TOOL_ARGUMENT_MODELS, TOOL_RESULT_MODELS

    assert set(TOOL_ARGUMENT_MODELS) == {
        "ksi_list_analysis_observations",
        "ksi_list_analyses",
        "ksi_create_analysis",
        "ksi_check_analysis_readiness",
        "ksi_get_analysis",
        "ksi_get_analysis_result",
        "ksi_get_analysis_evidence",
        "ksi_create_delta_publication",
        "ksi_get_delta_publication",
        "ksi_read_delta_publication_bytes",
    }
    assert TOOL_RESULT_MODELS["ksi_get_analysis"] is TOOL_RESULT_MODELS[
        "ksi_get_analysis_result"
    ]

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            assert self.path == f"/v1/sites/{SITE}/analysis-observations"
            body = json.dumps({"items": []}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    client, server, thread = _client(tmp_path, CoreHandler)
    try:
        assert asyncio.run(
            client.invoke("ksi_list_analysis_observations", {"siteId": SITE})
        ) == {"items": []}
    finally:
        _stop(server, thread)
