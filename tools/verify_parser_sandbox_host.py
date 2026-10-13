#!/usr/bin/env python3
"""Probe whether this host can run the bwrap parser-sandbox acceptance.

The F-03/F-04 parser -> VALIDATED -> review acceptance requires a host where the
bubblewrap parser sandbox actually works (user namespaces + UID mapping + network
namespace). On hosts where `PARSER_SANDBOX_UNAVAILABLE` was recorded, the product
stays fail-closed and only the pre-launch conditions are verifiable. This probe
runs the exact capability commands and reports PASS/FAIL per check so a candidate
verification host can be judged before the acceptance run.

Usage:
  uv run --locked python tools/verify_parser_sandbox_host.py
  uv run --locked python tools/verify_parser_sandbox_host.py --json
  uv run --locked python tools/verify_parser_sandbox_host.py \
      --core-url http://127.0.0.1:8051 --object-origin http://127.0.0.1:9100

Exit codes: 0 = every capability check passed (parser acceptance can run);
2 = blocked on a named capability; 1 = usage error. The probe changes nothing
on the host.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Runner = Callable[[Sequence[str]], "ProbeResult"]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    returncode: int
    stdout: str
    stderr: str


def _default_runner(command: Sequence[str]) -> ProbeResult:
    if shutil.which(command[0]) is None:
        return ProbeResult(returncode=127, stdout="", stderr=f"{command[0]} not found on PATH")
    try:
        completed = subprocess.run(
            list(command), capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProbeResult(returncode=126, stdout="", stderr=f"{type(exc).__name__}: {exc}")
    return ProbeResult(completed.returncode, completed.stdout, completed.stderr)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


@dataclass(frozen=True, slots=True)
class Capability:
    check_id: str
    description: str
    command: tuple[str, ...]
    expect_stdout_contains: str | None = None


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "bwrap-present",
        "bubblewrap binary is installed",
        ("bwrap", "--version"),
    ),
    Capability(
        "user-namespace",
        "unprivileged user namespaces are permitted",
        ("unshare", "-Ur", "true"),
    ),
    Capability(
        "bwrap-uid-map",
        "bwrap can set up its user/UID mapping",
        ("bwrap", "--ro-bind", "/", "/", "--", "/bin/true"),
    ),
    Capability(
        "bwrap-net-namespace",
        "bwrap can create an isolated network namespace",
        ("bwrap", "--unshare-net", "--ro-bind", "/", "/", "--", "/bin/true"),
    ),
)


def run_capabilities(runner: Runner) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for capability in CAPABILITIES:
        result = runner(capability.command)
        ok = result.returncode == 0
        detail = _last_line(result.stdout) or _last_line(result.stderr)
        results.append(
            {
                "id": capability.check_id,
                "description": capability.description,
                "command": " ".join(capability.command),
                "ok": ok,
                "exitCode": result.returncode,
                "detail": detail,
            }
        )
    return results


def run_endpoint(
    check_id: str, description: str, url: str, http_get: Callable[[str], int]
) -> dict[str, object]:
    try:
        status = http_get(url)
        ok = 200 <= status < 300
        detail = f"HTTP {status}"
    except Exception as exc:  # noqa: BLE001 -- the probe must report, never crash
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "id": check_id,
        "description": description,
        "command": url,
        "ok": ok,
        "exitCode": None,
        "detail": detail,
    }


def _default_http_get(url: str) -> int:
    import httpx  # noqa: PLC0415

    return httpx.get(url, timeout=5.0).status_code


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = _default_runner,
    http_get: Callable[[str], int] = _default_http_get,
) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--core-url", default=None, help="optional Core origin reachability check")
    parser.add_argument(
        "--object-origin", default=None, help="optional object-store origin reachability check"
    )
    args = parser.parse_args(argv)

    results = run_capabilities(runner)
    if args.core_url:
        results.append(
            run_endpoint(
                "core-ready",
                "Core readiness endpoint answers",
                f"{args.core_url.rstrip('/')}/ready",
                http_get,
            )
        )
    if args.object_origin:
        results.append(
            run_endpoint(
                "object-origin",
                "object-store origin answers",
                f"{args.object_origin.rstrip('/')}/minio/health/live",
                http_get,
            )
        )

    passed = [item for item in results if item["ok"]]
    failed = [item for item in results if not item["ok"]]
    verdict = "READY" if not failed else "BLOCKED"
    report = {
        "host": sys.platform,
        "verdict": verdict,
        "passed": len(passed),
        "failed": len(failed),
        "checks": results,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for item in results:
            marker = "PASS" if item["ok"] else "FAIL"
            print(f"[{marker}] {item['id']}: {item['description']}")
            print(f"       $ {item['command']}")
            if item["detail"]:
                print(f"       {item['detail']}")
        print(f"VERDICT {verdict} ({len(passed)} passed, {len(failed)} failed)")
    if failed:
        print(
            "parser-sandbox acceptance stays BLOCKED on this host; product behavior "
            "remains fail-closed (no code, fallback or host-security changes).",
            file=sys.stderr,
        )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
