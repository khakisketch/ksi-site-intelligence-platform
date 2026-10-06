"""HTTP-only native-window consumer; creates no rights, policy or worker authority.

Use returned assetRef/observedCrsDigest and a pre-existing Core grant. This example
checks transport/byte identity, not survey accuracy or actual producer compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Never
from urllib.parse import quote, urlsplit

import httpx

JOB = re.compile(r"sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class NativeWindowClientError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)  # Never reflect URL, bearer, server body or filesystem path.


def strict_json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def nonfinite(_: str) -> Never:
        raise ValueError("nonfinite JSON")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


def private_token(path: Path) -> str:
    directory = protected_directory(path.absolute().parent)
    try:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    finally:
        os.close(directory)
    try:
        state = os.fstat(fd)
        if (
            not stat.S_ISREG(state.st_mode)
            or state.st_uid != os.geteuid()
            or stat.S_IMODE(state.st_mode) != 0o600
            or state.st_nlink != 1
        ):
            raise NativeWindowClientError("TOKEN_UNAVAILABLE")
        raw = os.read(fd, 8193)
        token = raw.decode("ascii").strip()
        if not token or len(raw) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise NativeWindowClientError("TOKEN_UNAVAILABLE")
        return token
    finally:
        os.close(fd)


def protected_directory(path: Path) -> int:
    descriptors = []
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise NativeWindowClientError("PRIVATE_DIRECTORY_UNAVAILABLE")
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for component in path.parts[1:]:
            before = os.fstat(parent)
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            descriptors.append(child)
            after = os.fstat(child)
            if (
                after.st_uid not in (0, os.geteuid())
                or before.st_mode & 0o022
                and not (before.st_mode & stat.S_ISVTX and after.st_uid == os.geteuid())
            ):
                raise NativeWindowClientError("PRIVATE_DIRECTORY_UNAVAILABLE")
            parent = child
        descriptors.remove(parent)
        return parent
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def bounded_file(path: Path, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            raise NativeWindowClientError("INPUT_UNAVAILABLE")
        raw = os.read(fd, maximum + 1)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(raw) != before.st_size:
            raise NativeWindowClientError("INPUT_UNAVAILABLE")
        return raw
    finally:
        os.close(fd)


class NativeWindowClient:
    def __init__(
        self,
        *,
        base_url: str,
        site_id: str,
        work_area_id: str,
        token: str,
        max_json_bytes: int,
        max_file_bytes: int,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme not in {"https", "http"}
            or url.scheme == "http"
            and url.hostname not in {"127.0.0.1", "::1"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or any(type(n) is not int or n <= 0 for n in (max_json_bytes, max_file_bytes))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or not token
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
            or any(not isinstance(x, str) or not 0 < len(x) <= 256 for x in (site_id, work_area_id))
        ):
            raise NativeWindowClientError("INVALID_CONFIGURATION")
        self.base = (
            f"/v1/sites/{quote(site_id, safe='')}/work-areas/"
            f"{quote(work_area_id, safe='')}/spatial-data-requests"
        )
        self.max_json_bytes, self.max_file_bytes, self.timeout = (
            max_json_bytes,
            max_file_bytes,
            timeout_seconds,
        )
        self.http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": "Bearer " + token, "Accept-Encoding": "identity"},
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self.http.close()

    def _job(self, job_id: object) -> str:
        if not isinstance(job_id, str) or JOB.fullmatch(job_id) is None:
            raise NativeWindowClientError("INVALID_JOB_ID")
        return self.base + "/" + job_id

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            started = monotonic()
            with self.http.stream(method, path, **kwargs) as response:
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise NativeWindowClientError("INVALID_RESPONSE")
                raw = bytearray()
                for chunk in response.iter_raw(chunk_size=min(65536, self.max_json_bytes)):
                    if (
                        len(raw) + len(chunk) > self.max_json_bytes
                        or monotonic() - started >= self.timeout
                    ):
                        raise NativeWindowClientError("RESPONSE_LIMIT_EXCEEDED")
                    raw.extend(chunk)
                body = strict_json(bytes(raw))
                if not isinstance(body, dict):
                    raise NativeWindowClientError("INVALID_RESPONSE")
                if response.status_code not in {200, 201}:
                    reason = body.get("reason")
                    if not isinstance(reason, str) or re.fullmatch(r"[A-Z_]{1,80}", reason) is None:
                        reason = "REQUEST_DENIED"
                    raise NativeWindowClientError(reason)
                self._job(body.get("jobId"))
                return body
        except NativeWindowClientError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, RecursionError) as exc:
            raise NativeWindowClientError("INVALID_RESPONSE") from exc

    def issue(self, *, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._json(
            "POST", self.base, json=request, headers={"Idempotency-Key": idempotency_key}
        )

    def status(self, job_id: str) -> dict[str, Any]:
        body = self._json("GET", self._job(job_id))
        if body["jobId"] != job_id:
            raise NativeWindowClientError("INVALID_RESPONSE")
        return body

    def wait(
        self, job_id: str, *, timeout_seconds: float, poll_seconds: float = 0.5
    ) -> dict[str, Any]:
        if not all(math.isfinite(n) and n > 0 for n in (timeout_seconds, poll_seconds)):
            raise NativeWindowClientError("INVALID_CONFIGURATION")
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            body = self.status(job_id)
            if body.get("executionState") == "COMPLETED":
                return body
            if body.get("executionState") in {"FAILED", "CANCELED", "EXPIRED"}:
                reason = body.get("reason")
                if not isinstance(reason, str) or re.fullmatch(r"[A-Z_]{1,80}", reason) is None:
                    reason = "PREPARATION_FAILED"
                raise NativeWindowClientError(reason)
            sleep(min(poll_seconds, max(0, deadline - monotonic())))
        raise NativeWindowClientError("DEADLINE_EXCEEDED")

    def download(self, *, status: dict[str, Any], output_dir: Path) -> Path:
        path = self._job(status.get("jobId")) + "/file"
        receipt = status.get("receipt")
        if (
            not isinstance(receipt, dict)
            or status.get("executionState") != "COMPLETED"
            or receipt.get("jobId") != status["jobId"]
        ):
            raise NativeWindowClientError("OUTPUT_NOT_READY")
        size, digest = receipt.get("outputSizeBytes"), receipt.get("outputSha256")
        if (
            type(size) is not int
            or not 0 < size <= self.max_file_bytes
            or not isinstance(digest, str)
            or DIGEST.fullmatch(digest) is None
        ):
            raise NativeWindowClientError("INVALID_RECEIPT")
        actual_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {k: v for k, v in receipt.items() if k != "receiptDigest"},
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        if receipt.get("receiptDigest") != actual_digest:
            raise NativeWindowClientError("INVALID_RECEIPT")
        output_dir = output_dir.absolute()
        parent = protected_directory(output_dir.parent)
        try:
            with suppress(FileExistsError):
                os.mkdir(output_dir.name, 0o700, dir_fd=parent)
            directory = os.open(
                output_dir.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        state = os.fstat(directory)
        if state.st_uid != os.geteuid() or stat.S_IMODE(state.st_mode) != 0o700:
            os.close(directory)
            raise NativeWindowClientError("OUTPUT_DIRECTORY_UNAVAILABLE")
        candidate = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b", dir=f"/proc/self/fd/{directory}", prefix=".native-", delete=False
            ) as sink:
                candidate = Path(sink.name)
                hashed, count, started = hashlib.sha256(), 0, monotonic()
                with self.http.stream("GET", path) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-encoding", "identity").lower()
                        != "identity"
                        or response.headers.get("content-length") != str(size)
                        or response.headers.get("x-content-sha256") != digest
                        or response.headers.get("cache-control") != "private, no-store"
                        or response.headers.get("x-content-type-options") != "nosniff"
                    ):
                        raise NativeWindowClientError("INVALID_FILE_RESPONSE")
                    for chunk in response.iter_raw(chunk_size=65536):
                        count += len(chunk)
                        if count > size or monotonic() - started >= self.timeout:
                            raise NativeWindowClientError("FILE_LIMIT_EXCEEDED")
                        sink.write(chunk)
                        hashed.update(chunk)
                if count != size or "sha256:" + hashed.hexdigest() != digest:
                    raise NativeWindowClientError("INTEGRITY_MISMATCH")
                sink.flush()
                os.fsync(sink.fileno())
            target = output_dir / (status["jobId"] + ".tif")
            os.link(
                candidate.name, target.name, src_dir_fd=directory, dst_dir_fd=directory
            )  # Atomic no-overwrite.
            return target
        except NativeWindowClientError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise NativeWindowClientError("DOWNLOAD_UNAVAILABLE") from exc
        finally:
            if candidate is not None:
                os.unlink(candidate.name, dir_fd=directory)
            os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--work-area-id", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-file-bytes", type=int, required=True)
    parser.add_argument("--deadline-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    client = None
    try:
        raw = bounded_file(args.request_file, 65536)
        client = NativeWindowClient(
            base_url=args.core_url,
            site_id=args.site_id,
            work_area_id=args.work_area_id,
            token=private_token(args.token_file),
            max_json_bytes=65536,
            max_file_bytes=args.max_file_bytes,
            timeout_seconds=min(30, args.deadline_seconds),
        )
        issued = client.issue(request=strict_json(raw), idempotency_key=args.idempotency_key)
        status = client.wait(issued["jobId"], timeout_seconds=args.deadline_seconds)
        output = client.download(status=status, output_dir=args.output_dir)
        print(
            json.dumps(
                {"jobId": status["jobId"], "outputFile": output.name, "receipt": status["receipt"]},
                allow_nan=False,
            )
        )
        return 0
    except (NativeWindowClientError, OSError, ValueError, TypeError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": exc.reason
                    if isinstance(exc, NativeWindowClientError)
                    else "INPUT_UNAVAILABLE",
                }
            )
        )
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
