"""Finite SDK-level substitute that a FRESH child interpreter can import.

The storage supervisor's child is now a new interpreter (``exec``), so it inherits
no client object from the parent. The contract suite therefore needs a substitute the
child can BUILD itself: this module is importable by dotted path, and the owner
points the child at it with ``KSI_CORE_S3_CLIENT_FACTORY``.

The substitute stays finite and local: it never performs remote I/O, it records
every call into a log file so the parent can assert on the exact operations, and it
can simulate the failure modes the storage contracts care about (hang, substitution,
partial inventory, late signing).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

#: Where the substitute records its calls. The owner sets it for the child.
LOG_PATH_ENV = "KSI_TEST_SDK_LOG"
#: Body bytes the substitute serves.
BODY_ENV = "KSI_TEST_SDK_BODY"
#: Failure behaviour the substitute should simulate.
BEHAVIOR_ENV = "KSI_TEST_SDK_BEHAVIOR"
#: Response overrides applied to the object metadata (JSON).
CHANGES_ENV = "KSI_TEST_SDK_CHANGES"

_DEFAULT_BODY = b"abcdefgh"


def _log_path() -> Path:
    return Path(os.environ.get(LOG_PATH_ENV, "/tmp/opencode/ksi-test-sdk.jsonl"))


def _body() -> bytes:
    return os.environ.get(BODY_ENV, "").encode() or _DEFAULT_BODY


def _behavior() -> str | None:
    value = os.environ.get(BEHAVIOR_ENV)
    return value or None


def _changes() -> dict[str, Any]:
    raw = os.environ.get(CHANGES_ENV)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class _StubBody:
    """The substitute's streaming body.

    It lives at module level on purpose: a class defined inside a method
    resolves ``self`` to the ENCLOSING instance, so the read cursor would land
    on the client instead of on the body.
    """

    def __init__(self, owner: SDKStub) -> None:
        self._owner = owner
        self.cursor = 0

    def read(self, size: int) -> bytes:
        owner = self._owner
        owner.record("read", size=size)
        if owner.behavior == "read-hang":
            Event().wait(10)
        value = owner.bytes[self.cursor : self.cursor + size]
        self.cursor += len(value)
        return value

    def close(self) -> None:
        self._owner.record("close")


class SDKStub:
    """Finite SDK-level remote substitute; actual child/process/framing stays real."""

    def __init__(
        self,
        log: Path,
        *,
        body: bytes = _DEFAULT_BODY,
        response_changes: dict[str, Any] | None = None,
        behavior: str | None = None,
    ) -> None:
        self.log = log
        self.bytes = body
        self.changes = response_changes or {}
        self.behavior = behavior
        self.meta = SimpleNamespace(
            config=SimpleNamespace(
                connect_timeout=0.05,
                read_timeout=0.05,
                retries={"total_max_attempts": 1},
                signature_version="s3v4",
            )
        )

    def record(self, name: str, **arguments: Any) -> None:
        with self.log.open("a") as output:
            output.write(json.dumps({"pid": os.getpid(), "operation": name, **arguments}) + "\n")

    def metadata(self) -> dict[str, Any]:
        import base64 as _base64
        import hashlib as _hashlib

        return {
            "ContentLength": len(self.bytes),
            "ChecksumSHA256": _base64.b64encode(_hashlib.sha256(self.bytes).digest()).decode(),
            "ChecksumType": "FULL_OBJECT",
            "VersionId": "version-1",
            "ContentType": "image/tiff",
            "ResponseMetadata": {"HTTPStatusCode": 200},
            **self.changes,
        }

    def head_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("head", **arguments)
        import sys as _s
        print("STUB head behavior=", self.behavior, file=_s.stderr, flush=True)
        if self.behavior == "head-hang":
            # A call that never returns: the supervisor must kill it at the
            # total deadline instead of holding the request open.
            Event().wait(30)
        return self.metadata()

    def get_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("get", **arguments)
        if self.behavior == "get-hang":
            Event().wait(10)
        return {**self.metadata(), "Body": _StubBody(self)}

    def generate_presigned_url(self, operation: str, **arguments: Any) -> str:
        self.record("sign", client_method=operation, **arguments)
        signed_at = "20261001T000001Z" if self.behavior == "sign-late" else "20261001T000000Z"
        headers = (
            "content-length;content-type;host;x-amz-checksum-sha256"
            if operation == "put_object"
            else "host;x-amz-checksum-mode"
        )
        return (
            "https://store.invalid/exact-version?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Date={signed_at}&X-Amz-Expires={arguments['ExpiresIn']}"
            f"&X-Amz-SignedHeaders={headers}&X-Amz-Signature=local-fixture"
        )

    def list_object_versions(self, **arguments: Any) -> dict[str, Any]:
        self.record("list", **arguments)
        listing = self.changes.get("__listing__")
        if isinstance(listing, dict):
            return {**self._default_listing(arguments), **listing}
        return self._default_listing(arguments)

    def _default_listing(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "Versions": [{"Key": arguments["Prefix"], "VersionId": "version-1"}],
            "IsTruncated": False,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

    def delete_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("delete", **arguments)
        if self.behavior == "delete-substitute":
            # The provider acknowledged a DIFFERENT version than the one we
            # asked to delete: the caller must refuse it.
            return {"VersionId": "version-other", "ResponseMetadata": {"HTTPStatusCode": 204}}
        deletion = self.changes.get("__deletion__")
        if isinstance(deletion, dict):
            return {
                "VersionId": arguments["VersionId"],
                "ResponseMetadata": {"HTTPStatusCode": 204},
                **deletion,
            }
        return {"VersionId": arguments["VersionId"], "ResponseMetadata": {"HTTPStatusCode": 204}}


def client_factory(operation_timeout_seconds: float, work: dict[str, Any] | None = None) -> SDKStub:
    """The child-side factory: builds a fresh substitute for THIS operation.

    The description carries the exact body/behaviour/log for this call, so two
    storages in the same process never share (or fight over) ambient state.
    """
    del operation_timeout_seconds
    settings = work or {}
    log = Path(settings.get("logPath") or _log_path())
    body = settings.get("body")
    if isinstance(body, str):
        body = body.encode("latin-1")
    changes = settings.get("changes")
    if not isinstance(changes, dict):
        changes = _changes()
    behavior = settings.get("behavior")
    if not isinstance(behavior, str) or not behavior:
        behavior = _behavior()
    client = SDKStub(
        log,
        body=body if isinstance(body, bytes) and body else _body(),
        response_changes=changes,
        behavior=behavior,
    )
    config_changes = settings.get("configChanges")
    if isinstance(config_changes, dict):
        for name, value in config_changes.items():
            setattr(client.meta.config, name, _number_back(value))
    return client


def _number_back(value: Any) -> Any:
    """Read a value the description carried, restoring non-finite numbers."""
    if isinstance(value, str):
        if value == "Infinity":
            return math.inf
        if value == "-Infinity":
            return -math.inf
    return value
