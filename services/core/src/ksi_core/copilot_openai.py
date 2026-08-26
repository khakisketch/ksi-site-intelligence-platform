"""Strict OpenAI-compatible ``/v1/chat/completions`` Copilot adapter.

This adapter intentionally does not import a provider SDK. Its accepted surface
is limited to function tool calls with JSON-object arguments and one final JSON
assistant answer. Images, presigned URLs, arbitrary object keys, streaming, and
provider-specific extensions are outside the contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ksi_core.copilot import ModelToolCall, ModelTurn

_MAX_RESPONSE_BYTES = 1024 * 1024
_FORBIDDEN_KEYS = frozenset(
    {
        "presignedurl",
        "downloadurl",
        "uploadurl",
        "objectkey",
        "rawimage",
        "imagebase64",
        "sourcebytes",
    }
)


class CopilotProviderError(RuntimeError):
    """Provider request or response did not satisfy the narrow adapter contract."""


@dataclass(frozen=True, slots=True)
class CopilotRuntimeConfig:
    base_url: str
    model: str
    api_key_file: Path
    timeout_seconds: float
    planner_version: str
    provider_name: str = "openai-compatible"


def _assert_safe_egress(value: Any, *, path: str = "messages") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("_", "").lower()
            if normalized in _FORBIDDEN_KEYS:
                raise CopilotProviderError(f"외부 AI 반출 금지 필드: {path}.{key}")
            _assert_safe_egress(item, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_safe_egress(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith(("http://", "https://", "s3://")) or "x-amz-signature=" in lowered:
            raise CopilotProviderError(f"외부 AI 반출 금지 URL/object reference: {path}")


class OpenAiCompatibleModelAdapter:
    external = True

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_file: Path,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Copilot base URL은 http(s) URL이어야 한다")
        if not model.strip():
            raise ValueError("Copilot model은 비어 있을 수 없다")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Copilot timeout은 0초 초과 300초 이하여야 한다")
        if not api_key_file.is_file():
            raise ValueError("Copilot API key file이 존재하지 않는다")
        self._endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._model = model
        self._api_key_file = api_key_file
        self._timeout = timeout_seconds
        self._client = client or httpx.Client()

    def _api_key(self) -> str:
        try:
            key = self._api_key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CopilotProviderError("Copilot API key file을 읽을 수 없다") from exc
        if not key or len(key) > 4096 or "\n" in key or "\r" in key:
            raise CopilotProviderError("Copilot API key file 형식이 유효하지 않다")
        return key

    def complete(
        self,
        *,
        messages: tuple[dict[str, Any], ...],
        tools: tuple[dict[str, Any], ...],
    ) -> ModelTurn:
        _assert_safe_egress(messages)
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [self._message(item) for item in messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": item["inputSchema"],
                    },
                }
                for item in tools
            ],
            "tool_choice": "auto",
        }
        try:
            response = self._client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key()}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CopilotProviderError("Copilot provider 요청이 실패했다") from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise CopilotProviderError("Copilot provider 응답 크기 상한을 초과했다")
        try:
            body = response.json()
            choices = body["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("choices는 정확히 1개여야 한다")
            message = choices[0]["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("assistant message가 없다")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CopilotProviderError("Copilot provider 응답 envelope가 유효하지 않다") from exc

        raw_calls = message.get("tool_calls")
        if raw_calls:
            if not isinstance(raw_calls, list) or message.get("content") not in (None, ""):
                raise CopilotProviderError("tool call 응답은 content를 함께 가질 수 없다")
            calls: list[ModelToolCall] = []
            for raw in raw_calls:
                try:
                    if raw["type"] != "function":
                        raise ValueError("function tool call만 허용된다")
                    function = raw["function"]
                    arguments = json.loads(function["arguments"])
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments는 JSON object여야 한다")
                    calls.append(
                        ModelToolCall(
                            call_id=raw["id"],
                            name=function["name"],
                            arguments=arguments,
                        )
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise CopilotProviderError("Copilot tool call이 유효하지 않다") from exc
            return ModelTurn(tool_calls=tuple(calls))

        content = message.get("content")
        try:
            if not isinstance(content, str):
                raise ValueError("final content가 문자열이 아니다")
            final = json.loads(content)
            if not isinstance(final, dict) or set(final) != {"answer", "citationIds"}:
                raise ValueError("final answer shape 불일치")
            answer = final["answer"]
            citation_ids = final["citationIds"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("answer가 비어 있다")
            if not isinstance(citation_ids, list) or not all(
                isinstance(item, str) and item for item in citation_ids
            ):
                raise ValueError("citationIds가 문자열 배열이 아니다")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CopilotProviderError(
                "Copilot final answer는 answer/citationIds JSON이어야 한다"
            ) from exc
        return ModelTurn(answer=answer, citation_ids=tuple(citation_ids))

    @staticmethod
    def _message(message: dict[str, Any]) -> dict[str, Any]:
        role = message.get("role")
        if role in {"system", "user"}:
            return {"role": role, "content": message["content"]}
        if role == "assistant" and "toolCalls" in message:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": item["id"],
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(
                                item["arguments"], ensure_ascii=False, allow_nan=False
                            ),
                        },
                    }
                    for item in message["toolCalls"]
                ],
            }
        if role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message["toolCallId"],
                "content": json.dumps(
                    {
                        "data": message["content"],
                        "citationIds": message.get("citationIds", []),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            }
        raise CopilotProviderError(f"지원하지 않는 Copilot message role: {role!r}")


__all__ = [
    "CopilotProviderError",
    "CopilotRuntimeConfig",
    "OpenAiCompatibleModelAdapter",
]
