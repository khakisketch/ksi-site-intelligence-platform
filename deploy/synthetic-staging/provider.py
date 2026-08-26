#!/usr/bin/env python3
"""Deterministic OpenAI-compatible provider for synthetic Phase 2 evidence only.

The service has no network client and cannot forward data outside its container.
It exercises the same external-model adapter, tool-call transcript, citation
validation, timeout, and provider-error paths as an approved provider would.
"""

from __future__ import annotations

import argparse
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 1024 * 1024


class SyntheticProvider(BaseHTTPRequestHandler):
    api_key: str

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Never log prompts, authorization headers, or response bodies.
        print(f"synthetic-provider {self.command} {self.path} {args[1] if len(args) > 1 else '-'}")

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._json(HTTPStatus.OK, {"status": "ok", "mode": "synthetic-no-external-egress"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if self.headers.get("Authorization") != f"Bearer {self.api_key}":
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_api_key"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            messages = body["messages"]
            if not isinstance(messages, list):
                raise TypeError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return

        user_text = "\n".join(
            str(item.get("content", ""))
            for item in messages
            if isinstance(item, dict) and item.get("role") == "user"
        )
        if "[fixture:provider-500]" in user_text:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "synthetic_provider_failure"})
            return
        if "[fixture:timeout]" in user_text:
            time.sleep(5)
        if "[fixture:invalid-envelope]" in user_text:
            self._json(HTTPStatus.OK, {"choices": []})
            return

        tool_messages = [
            item for item in messages if isinstance(item, dict) and item.get("role") == "tool"
        ]
        if not tool_messages:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "phase2-site-snapshot-1",
                        "type": "function",
                        "function": {"name": "site_snapshot", "arguments": "{}"},
                    }
                ],
            }
        else:
            try:
                tool_result = json.loads(tool_messages[-1]["content"])
                citation_ids = tool_result.get("citationIds", [])
                site_name = tool_result.get("data", {}).get("siteName", "합성 현장")
            except (AttributeError, KeyError, TypeError, json.JSONDecodeError):
                citation_ids = []
                site_name = "합성 현장"
            if "[fixture:unknown-citation]" in user_text:
                citation_ids = ["site-workspace:cross-site-forbidden"]
            content = {
                "answer": (
                    f"{site_name}의 검증된 현장 원장을 조회했습니다. "
                    "이 답변은 합성 Staging 근거만 설명하며 승인이나 비행 명령을 만들지 않습니다."
                ),
                "citationIds": citation_ids,
            }
            message = {
                "role": "assistant",
                "content": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
            }
        self._json(
            HTTPStatus.OK,
            {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]},
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--api-key-file", type=Path, required=True)
    args = parser.parse_args()
    key = args.api_key_file.read_text(encoding="utf-8").strip()
    if len(key) < 32 or "\n" in key or "\r" in key:
        raise RuntimeError("synthetic provider API key file is invalid")
    SyntheticProvider.api_key = key
    server = ThreadingHTTPServer((args.host, args.port), SyntheticProvider)
    print(f"synthetic OpenAI-compatible provider ready on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
