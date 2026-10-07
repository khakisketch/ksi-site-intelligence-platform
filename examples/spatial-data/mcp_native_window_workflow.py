"""Generated-software example: request one native window over the local MCP adapter.

The caller supplies scope, idempotency key, owner-protected adapter config,
and local output targets. The script requests exactly once through the
official SDK stdio adapter, polls a finite caller budget, persists only safe
IDs/receipt/reference, and optionally downloads bytes through the existing
guarded consumer. It takes no token, no remote reference, and no database
or store handle; it installs or starts nothing. All failures surface as
fixed closed codes — raw transport detail is never echoed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[1]
ADAPTER_SRC = REPO_ROOT / "services" / "spatial-data-mcp" / "src"

for _candidate in (str(ADAPTER_SRC), str(EXAMPLE_DIR)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELED", "EXPIRED"}

_SAFE_CODES = frozenset(
    {
        "REQUEST_DENIED",
        "STATUS_DENIED",
        "POLL_BUDGET_EXCEEDED",
        "DOWNLOAD_DENIED",
        "PERSIST_FAILED",
        "RECEIPT_EXISTS",
        "RECEIPT_TOO_LARGE",
        "ADAPTER_UNAVAILABLE",
        "CONFIG_UNREADABLE",
        "CREDENTIAL_UNREADABLE",
        "CONSUMER_MISCONFIGURED",
        "INVALID_ARGUMENTS",
        "NOT_COMPLETED",
        "INVALID_CORE_RESPONSE",
        "OUTPUT_NOT_READY",
        "INVALID_RECEIPT",
    }
)


def _coerce_code(value: object) -> str:
    """Return only a closed code; unknown text never reaches callers."""
    if isinstance(value, str) and value in _SAFE_CODES:
        return value
    return "ADAPTER_UNAVAILABLE"


def _fail(code: object) -> int:
    print(f"mcp_native_window_workflow: {_coerce_code(code)}", file=sys.stderr)
    return 2


def _normalize_group_error(group: BaseExceptionGroup) -> ValueError:
    """Map a teardown exception group to the error to raise (never success).

    Side-effect free: only reads exception structure, never messages, values,
    or payloads. A single unambiguous exact closed ValueError leaf (exact type,
    single string arg, member of _SAFE_CODES) is retained as its code, whether
    it travels as a group member or in a suppressed __context__/__cause__
    chain. KeyboardInterrupt/SystemExit anywhere re-raises the group unchanged
    so interruption is never coerced into a code. Anything else (unknown
    leaves, mixed distinct closed codes) maps to ADAPTER_UNAVAILABLE.
    """
    codes: set[str] = set()
    interrupted = False
    seen: set[int] = set()
    stack: list[BaseException] = [group]
    while stack and len(seen) < 64:
        exc = stack.pop()
        if id(exc) in seen:
            continue
        seen.add(id(exc))
        if isinstance(exc, BaseExceptionGroup):
            stack.extend(exc.exceptions)
            continue
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            interrupted = True
            continue
        if (
            type(exc) is ValueError
            and len(exc.args) == 1
            and isinstance(exc.args[0], str)
            and exc.args[0] in _SAFE_CODES
        ):
            codes.add(exc.args[0])
            continue
        for nxt in (exc.__cause__, exc.__context__):
            if isinstance(nxt, BaseException):
                stack.append(nxt)
    if interrupted:
        raise group
    if len(codes) == 1:
        return ValueError(codes.pop())
    return ValueError("ADAPTER_UNAVAILABLE")


class _ClosedParser(argparse.ArgumentParser):
    """Argument parser that never echoes raw values, markers, or tracebacks."""

    def error(self, message: object) -> Any:
        print("mcp_native_window_workflow: INVALID_ARGUMENTS", file=sys.stderr)
        raise SystemExit(2)


# CLI representation bound for one caller download quota (1 TiB): a parsing
# guard so no huge integer reaches transport, not a Core/MCP file maximum.
_MAX_DOWNLOAD_BYTES = 1 << 40


def _parse_download_budget(value: object) -> int | None:
    """One optional caller byte quota: strict positive int within the CLI bound."""
    if value is None:
        return None
    if isinstance(value, bool) or type(value) is not int:
        raise ValueError("INVALID_ARGUMENTS")
    if not 1 <= value <= _MAX_DOWNLOAD_BYTES:
        raise ValueError("INVALID_ARGUMENTS")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _ClosedParser(
        description="Request one spatial-data native window via the local MCP adapter."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--work-area-id", required=True)
    parser.add_argument("--asset-ref", required=True)
    parser.add_argument(
        "--bounds", required=True, nargs=4, type=float, metavar=("W", "S", "E", "N")
    )
    parser.add_argument("--crs-digest", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--poll-budget-seconds", required=True, type=float)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.5)
    parser.add_argument("--receipt-out", required=True, type=Path)
    parser.add_argument("--download-dir", type=Path, default=None)
    parser.add_argument("--max-download-bytes", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        args.max_download_bytes = _parse_download_budget(args.max_download_bytes)
    except ValueError:
        parser.error("download budget must be a positive integer within bounds")
    if (
        not isinstance(args.poll_budget_seconds, float)
        or not math.isfinite(args.poll_budget_seconds)
        or not args.poll_budget_seconds > 0
        or not isinstance(args.poll_interval_seconds, float)
        or not math.isfinite(args.poll_interval_seconds)
        or not args.poll_interval_seconds > 0
        or args.poll_interval_seconds > args.poll_budget_seconds
    ):
        parser.error("poll budget/interval must be finite and positive")
    if any(not math.isfinite(v) for v in args.bounds):
        parser.error("bounds must be finite numbers")
    for label in ("site-id", "work-area-id", "asset-ref", "idempotency-key"):
        value = getattr(args, label.replace("-", "_"))
        if not isinstance(value, str) or not 0 < len(value) <= 255:
            parser.error(f"--{label} must be a 1..255 character identifier")
    if not isinstance(args.crs_digest, str) or not 0 < len(args.crs_digest) <= 255:
        parser.error("--crs-digest must be a 1..255 character digest")
    try:
        from ksi_spatial_data_mcp.tool_models import CreateArguments

        CreateArguments.model_validate(
            {
                "siteId": args.site_id,
                "workAreaId": args.work_area_id,
                "assetRef": args.asset_ref,
                "requestedBounds": list(args.bounds),
                "observedCrsDigest": args.crs_digest,
                "idempotencyKey": args.idempotency_key,
            }
        )
    except Exception:
        parser.error("caller identifiers must satisfy the closed tool model")
    return args


def _load_config(config: Path) -> Any:
    """Load the owner-protected adapter config; never a raw byte read."""
    from ksi_spatial_data_mcp.config import AdapterConfig, AdapterConfigurationError

    try:
        return AdapterConfig.from_file(config)
    except (AdapterConfigurationError, OSError, ValueError):
        raise ValueError("CONFIG_UNREADABLE") from None


def _check_caller_budgets(args: argparse.Namespace, config: Any) -> None:
    """Enforce the owner identifier byte budget on caller-supplied values."""
    try:
        limit = int(config.max_identifier_bytes)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("CONFIG_UNREADABLE") from None
    for value in (
        args.site_id,
        args.work_area_id,
        args.asset_ref,
        args.idempotency_key,
    ):
        if len(str(value).encode("utf-8")) > limit:
            raise ValueError("INVALID_ARGUMENTS")


def _validated_create_view(
    payload: object, *, site_id: str, work_area_id: str, asset_ref: str
) -> dict:
    """Strict create outcome: exact requested scope/asset, no free text."""
    try:
        from ksi_event_contracts.spatial_data import SpatialDataJobViewV1

        view = SpatialDataJobViewV1.model_validate(payload)
    except Exception:
        raise ValueError("INVALID_CORE_RESPONSE") from None
    if view.site_id != site_id or view.work_area_id != work_area_id or view.asset_ref != asset_ref:
        raise ValueError("INVALID_CORE_RESPONSE") from None
    return view.model_dump(by_alias=True, mode="json")


def _validated_poll_view(
    payload: object, *, site_id: str, work_area_id: str, job_id: str
) -> tuple[dict, dict | None]:
    """Strict poll outcome: exact scope/job with a coherent receipt/reference."""
    try:
        from ksi_event_contracts.spatial_data_ai import SpatialDataMcpJobViewV1

        wrapper = SpatialDataMcpJobViewV1.model_validate(payload)
    except Exception:
        raise ValueError("INVALID_CORE_RESPONSE") from None
    job = wrapper.job
    if job.site_id != site_id or job.work_area_id != work_area_id or job.job_id != job_id:
        raise ValueError("INVALID_CORE_RESPONSE") from None
    dumped = wrapper.model_dump(by_alias=True, mode="json")
    job_dict = dumped.get("job")
    file_ref = dumped.get("fileReference")
    if not isinstance(job_dict, dict):
        raise ValueError("INVALID_CORE_RESPONSE") from None
    if file_ref is not None and not isinstance(file_ref, dict):
        raise ValueError("INVALID_CORE_RESPONSE") from None
    return job_dict, file_ref


def _parameters(config: Path) -> Any:
    from mcp.client.stdio import StdioServerParameters

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"}
    }
    env["PYTHONPATH"] = str(ADAPTER_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "ksi_spatial_data_mcp.server", f"--config={config}"],
        env=env,
    )


async def _call_with_remaining(coro: Any, deadline: float) -> Any:
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    if remaining <= 0:
        raise ValueError("POLL_BUDGET_EXCEEDED")
    try:
        return await asyncio.wait_for(asyncio.ensure_future(coro), timeout=remaining)
    except TimeoutError:
        raise ValueError("POLL_BUDGET_EXCEEDED") from None


async def _run(args: argparse.Namespace, *, config: Any = None) -> dict:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    loop = asyncio.get_running_loop()
    budget = args.poll_budget_seconds
    if not isinstance(budget, float) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("INVALID_ARGUMENTS")
    deadline = loop.time() + budget
    try:
        async with asyncio.timeout(budget):
            async with (
                stdio_client(_parameters(args.config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await _call_with_remaining(session.initialize(), deadline)
                created = await _call_with_remaining(
                    session.call_tool(
                        "ksi_create_spatial_data_request",
                        {
                            "siteId": args.site_id,
                            "workAreaId": args.work_area_id,
                            "assetRef": args.asset_ref,
                            "requestedBounds": list(args.bounds),
                            "observedCrsDigest": args.crs_digest,
                            "idempotencyKey": args.idempotency_key,
                        },
                    ),
                    deadline,
                )
                if getattr(created, "is_error", False) or not getattr(
                    created, "structured_content", None
                ):
                    raise ValueError("REQUEST_DENIED")
                job = _validated_create_view(
                    created.structured_content,
                    site_id=args.site_id,
                    work_area_id=args.work_area_id,
                    asset_ref=args.asset_ref,
                )
                job_id = job.get("jobId")
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError("INVALID_CORE_RESPONSE")
                view: dict | None = None
                file_reference: dict | None = None
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise ValueError("POLL_BUDGET_EXCEEDED")
                    gotten = await _call_with_remaining(
                        session.call_tool(
                            "ksi_get_spatial_data_request",
                            {
                                "siteId": args.site_id,
                                "workAreaId": args.work_area_id,
                                "jobId": job_id,
                            },
                        ),
                        deadline,
                    )
                    if getattr(gotten, "is_error", False) or not getattr(
                        gotten, "structured_content", None
                    ):
                        raise ValueError("STATUS_DENIED")
                    view, file_reference = _validated_poll_view(
                        gotten.structured_content,
                        site_id=args.site_id,
                        work_area_id=args.work_area_id,
                        job_id=job_id,
                    )
                    if view.get("executionState") in TERMINAL_STATES:
                        break
                    await asyncio.sleep(
                        min(args.poll_interval_seconds, max(0.0, deadline - loop.time()))
                    )
                if not isinstance(view, dict) or view.get("executionState") not in TERMINAL_STATES:
                    raise ValueError("POLL_BUDGET_EXCEEDED")
                return {"job": view, "fileReference": file_reference}
    except ValueError:
        raise
    except TimeoutError:
        raise ValueError("POLL_BUDGET_EXCEEDED") from None
    except BaseExceptionGroup as group:
        raise _normalize_group_error(group) from None
    except Exception:
        raise ValueError("ADAPTER_UNAVAILABLE") from None


def _persist_json(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > 1_000_000:
        raise ValueError("RECEIPT_TOO_LARGE")
    path = path.absolute()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        raise ValueError("RECEIPT_EXISTS")
    stamp = f"{os.getpid()}-{time.monotonic_ns()}"
    tmp = parent / f".receipt-{stamp}.tmp"
    tmp_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(tmp_fd, "wb") as sink:
            sink.write(raw)
            sink.flush()
            os.fsync(sink.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise ValueError("RECEIPT_EXISTS") from None
        except OSError:
            raise ValueError("PERSIST_FAILED") from None
        try:
            dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
    except ValueError:
        raise
    except (OSError, Exception):
        raise ValueError("PERSIST_FAILED") from None
    finally:
        with suppress(OSError):
            os.unlink(tmp)


def _download(args: argparse.Namespace, view: dict, *, config: Any) -> str | None:
    if args.download_dir is None:
        return None
    from native_window_client import NativeWindowClient

    try:
        fresh = _load_config(args.config)
        token = fresh.read_token()
    except ValueError as exc:
        raise ValueError(_coerce_code(str(exc))) from None
    try:
        quota = _parse_download_budget(getattr(args, "max_download_bytes", None))
    except ValueError:
        raise ValueError("INVALID_ARGUMENTS") from None
    try:
        max_json = int(fresh.max_structured_response_bytes)
        # Caller quota for raster bytes only: an explicit --max-download-bytes
        # or, absent, the owner response ceiling as a conservative example
        # fallback (not a Core/MCP file maximum). The JSON quota never rises.
        max_file = quota if quota is not None else int(fresh.max_structured_response_bytes)
        timeout = float(fresh.read_timeout_seconds)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("CONFIG_UNREADABLE") from None
    if not math.isfinite(timeout) or timeout <= 0 or max_json <= 0 or max_file <= 0:
        raise ValueError("CONFIG_UNREADABLE") from None
    try:
        client = NativeWindowClient(
            base_url=fresh.core_origin,
            site_id=args.site_id,
            work_area_id=args.work_area_id,
            token=token,
            max_json_bytes=max_json,
            max_file_bytes=max_file,
            timeout_seconds=timeout,
            transport=None,
        )
    except Exception:
        raise ValueError("CONSUMER_MISCONFIGURED") from None
    try:
        target = client.download(status=view, output_dir=args.download_dir)
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, str) and reason in _SAFE_CODES:
            raise ValueError(reason) from None
        raise ValueError("DOWNLOAD_DENIED") from None
    finally:
        with suppress(Exception):
            client.close()
    return target.name


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    try:
        config = _load_config(args.config)
    except ValueError as exc:
        return _fail(_coerce_code(str(exc)))
    try:
        _check_caller_budgets(args, config)
    except ValueError as exc:
        return _fail(_coerce_code(str(exc)))
    try:
        outcome = asyncio.run(_run(args, config=config))
    except ValueError as exc:
        return _fail(_coerce_code(str(exc)))
    except Exception:
        return _fail("ADAPTER_UNAVAILABLE")
    view = outcome["job"]
    if view.get("executionState") != "COMPLETED":
        return _fail("NOT_COMPLETED")
    try:
        downloaded = _download(args, view, config=config)
        record = {
            "jobId": view.get("jobId"),
            "executionState": view.get("executionState"),
            "receipt": view.get("receipt"),
            "fileReference": outcome.get("fileReference"),
            "downloadedFileName": downloaded,
        }
        _persist_json(args.receipt_out, record)
    except ValueError as exc:
        return _fail(_coerce_code(str(exc)))
    except Exception:
        return _fail("PERSIST_FAILED")
    print(f"completed jobId={record['jobId']} receipt={args.receipt_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
