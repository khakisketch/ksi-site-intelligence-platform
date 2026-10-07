"""Task5 example e2e: the workflow script against a real lane over real HTTP.

Runs `examples/spatial-data/mcp_native_window_workflow.py` as a subprocess
while a separately started worker prepares the requested bytes. Asserts safe
receipt persistence, guarded download parity with the hand-derived oracle,
same-key recovery, and closed failure without secret or raster leakage.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import spatial_data_mcp_fixture as fixture

fixture.ensure_source_path()

EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "spatial-data"
    / "mcp_native_window_workflow.py"
)


def _example_args(
    lane: Any,
    config: Path,
    *,
    key: str,
    receipt: Path,
    download: Path | None,
    wrapper: Path,
    diag: Path,
) -> list[str]:
    workflow = [
        "--config",
        str(config),
        "--site-id",
        "site-1",
        "--work-area-id",
        lane.area_id,
        "--asset-ref",
        lane.assets["primary"]["asset_ref"],
        "--bounds",
        *[str(v) for v in fixture.TASK5_REQUEST_BOUNDS],
        "--crs-digest",
        lane.assets["primary"]["observed_crs_digest"],
        "--idempotency-key",
        key,
        "--poll-budget-seconds",
        "60",
        "--receipt-out",
        str(receipt),
    ]
    if download is not None:
        workflow += ["--download-dir", str(download)]
    # Test-owned diagnostic wrapper: same interpreter, same workflow argv
    # (sys.argv[0] stays the example path inside the wrapper), same config
    # source, no extra env/processes. The normal example CLI is unmodified.
    return [sys.executable, str(wrapper), str(diag), str(EXAMPLE), *workflow]


# Test-only trusted wrapper around the generated workflow entry. It replays
# the exact workflow argv via runpy, traces exception CLASS + source file:line
# only (never messages, values, locals, args, tokens, headers, config, JSON),
# and keeps the latest _DIAG_MAX_RECORDS immutable records plus the exit code
# to a 0600 task-owned diagnostic file. Nothing is written to public stderr.
# Benign StopIteration/StopAsyncIteration (coroutine machinery) are skipped;
# ExceptionGroup leaves and suppressed __context__/__cause__ chains are recorded
# as leaf class + raise-site file:line; an EXACT workflow._SAFE_CODES ValueError
# code may be recorded (allowlist, never arbitrary strings).
_WRAPPER_SOURCE = """\
\"\"\"Test-only diagnostic wrapper: exact workflow argv, class+file:line only.\"\"\"
import os
import runpy
import sys

_DIAG_MAX_RECORDS = 16
_DIAG_MAX_LEAVES = 8
_SKIP_TYPES = (StopIteration, StopAsyncIteration)


def _relevant(filename: str, example_path: str) -> bool:
    if filename == example_path:
        return True
    normalized = filename.replace(os.sep, "/")
    return "/mcp/client/" in normalized or "/mcp/shared/" in normalized


def _load_safe_codes(example_path: str) -> set:
    try:
        import ast

        with open(example_path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = {getattr(t, "id", "") for t in node.targets}
            if "_SAFE_CODES" not in names:
                continue
            return {
                n.value
                for n in ast.walk(node.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
    except Exception:
        pass
    return set()


def _leaf_facts(value, seen: set, out: list, safe_codes) -> None:
    if len(out) >= _DIAG_MAX_LEAVES or len(seen) > 24:
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, BaseExceptionGroup):
        try:
            subs = list(value.exceptions)[:_DIAG_MAX_LEAVES]
        except Exception:
            subs = []
        for sub in subs:
            _leaf_facts(sub, seen, out, safe_codes)
        return
    leaf_name = type(value).__name__
    if (
        isinstance(value, ValueError)
        and len(value.args) == 1
        and value.args[0] in safe_codes
    ):
        leaf_name = "ValueError:" + value.args[0]
    try:
        tb = value.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        if tb is not None:
            out.append(
                (
                    leaf_name,
                    str(tb.tb_frame.f_code.co_filename),
                    int(tb.tb_lineno),
                )
            )
        else:
            out.append((leaf_name, "<no-tb>", 0))
    except Exception:
        out.append((leaf_name, "<unreadable-tb>", 0))
    for nxt in (getattr(value, "__cause__", None), getattr(value, "__context__", None)):
        if nxt is not None and len(out) < _DIAG_MAX_LEAVES:
            _leaf_facts(nxt, seen, out, safe_codes)


def _spawn() -> int:
    diag_path = sys.argv[1]
    example_path = sys.argv[2]
    sys.argv = [example_path, *sys.argv[3:]]
    import collections

    records = collections.deque(maxlen=_DIAG_MAX_RECORDS)
    safe_codes = _load_safe_codes(example_path)
    seen_objs: list = []

    def _tracer(frame, event, arg):
        try:
            if event != "call":
                return None
            if _relevant(str(frame.f_code.co_filename), example_path):
                return _local
            return None
        except Exception:
            return None

    def _local(frame, event, arg):
        try:
            if event != "exception":
                return _local
            if not (isinstance(arg, tuple) and arg):
                return _local
            exc_type, exc_value = arg[0], arg[1]
            if isinstance(exc_type, type) and issubclass(exc_type, _SKIP_TYPES):
                return _local
            fname = str(frame.f_code.co_filename)
            lineno = int(frame.f_lineno)
            if (
                exc_type is ValueError
                and isinstance(exc_value, ValueError)
                and len(exc_value.args) == 1
                and exc_value.args[0] in safe_codes
            ):
                records.append(("ValueError:" + exc_value.args[0], fname, lineno))
                return _local
            name = exc_type.__name__ if isinstance(exc_type, type) else "Unknown"
            records.append((name, fname, lineno))
            known = False
            for known_obj in seen_objs:
                if known_obj is exc_value:
                    known = True
                    break
            if not known:
                if len(seen_objs) < 256:
                    seen_objs.append(exc_value)
                try:
                    leaves: list = []
                    _leaf_facts(exc_value, set(), leaves, safe_codes)
                except Exception:
                    leaves = []
                for leaf in leaves:
                    records.append(leaf)
            return _local
        except Exception:
            return None

    sys.settrace(_tracer)
    try:
        import threading

        threading.settrace(_tracer)
    except Exception:
        pass
    code = 0
    try:
        runpy.run_path(example_path, run_name="__main__")
    except SystemExit as exit_event:
        raw = exit_event.code
        code = raw if isinstance(raw, int) else 0
        raise
    except BaseException as escaping:
        records.append((type(escaping).__name__, "<wrapper>", 0))
        raise
    finally:
        try:
            fd = os.open(diag_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as sink:
                sink.write(f"exit={code}\\n")
                for name, filename, lineno in list(records):
                    sink.write(f"{name} {filename}:{lineno}\\n")
        except Exception:
            pass
    return code


_spawn()
"""

_DIAG_MAX_RECORDS = 16
_DIAG_WRAPPER_NAME = "_diag_workflow_wrapper.py"
_DIAG_FILE_NAME = "workflow-diag.txt"


def _write_workflow_wrapper(root: Path) -> tuple[Path, Path]:
    """Generate the wrapper + diagnostic paths inside a unique 0700 test root."""
    wrapper = root / _DIAG_WRAPPER_NAME
    wrapper.write_text(_WRAPPER_SOURCE, encoding="utf-8")
    os.chmod(wrapper, 0o600)
    return wrapper, root / _DIAG_FILE_NAME


def _diag_summary(diag: Path) -> str:
    """Safe assertion suffix: diagnostic path + recorded classes/lines only."""
    try:
        text = diag.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"diag=absent path={diag.name}"
    lines = [line for line in text.splitlines() if line][: _DIAG_MAX_RECORDS + 1]
    return "diag[" + diag.name + "]=" + ";".join(lines)


def _wait_for_job(lane: Any, *, timeout: float = 20.0) -> str:
    import httpx

    client = httpx.Client(
        base_url=lane.origin,
        headers={"Authorization": "Bearer " + fixture.TASK5_AI_TOKEN},
        timeout=10,
        trust_env=False,
    )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            page = client.get(lane.base, params={"limit": 2})
            assert page.status_code == 200
            items = page.json()["items"]
            if items:
                return str(items[0]["jobId"])
            time.sleep(0.2)
    finally:
        client.close()
    raise AssertionError("example never issued its single request")


def test_workflow_example_requests_polls_persists_and_downloads(tmp_path: Path) -> None:
    from test_spatial_data_mcp_http_integration import _assert_no_raster_bytes, _expected_oracle

    root = tmp_path / "example"
    root.mkdir(mode=0o700)
    download_dir = tmp_path / "example-bytes"
    download_dir.mkdir(mode=0o700)
    with fixture.task5_ai_lane(root, kind="dsm") as lane:
        config = fixture.task5_sdk_config(lane.origin, name="example")
        receipt_path = tmp_path / "receipt-1.json"
        wrapper, diag_path = _write_workflow_wrapper(root)
        worker = subprocess.Popen(
            _example_args(
                lane,
                config,
                key="example-1",
                receipt=receipt_path,
                download=download_dir,
                wrapper=wrapper,
                diag=diag_path,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            job_id = _wait_for_job(lane)
            status = lane.run_worker(job_id)
            assert status["executionState"] == "COMPLETED"
            stdout, stderr = worker.communicate(timeout=90)
        finally:
            if worker.poll() is None:
                worker.kill()
        assert worker.returncode == 0, stderr + "\n" + _diag_summary(diag_path)
        assert fixture.TASK5_AI_TOKEN not in stdout and "bytes" not in stdout.lower()

        record = json.loads(receipt_path.read_bytes())
        assert record["jobId"] == job_id
        assert record["executionState"] == "COMPLETED"
        assert record["receipt"] == status["receipt"]
        assert record["fileReference"]["outputSha256"] == status["receipt"]["outputSha256"]
        assert record["downloadedFileName"] == job_id + ".tif"
        _assert_no_raster_bytes(record)
        assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600

        oracle = _expected_oracle(lane)
        import numpy as np
        import rasterio

        downloaded = download_dir / (job_id + ".tif")
        with rasterio.open(downloaded) as output:
            np.testing.assert_array_equal(output.read(), oracle["array"])
            np.testing.assert_array_equal(output.dataset_mask(), oracle["mask"])

        again_receipt = tmp_path / "receipt-2.json"
        again_bytes = tmp_path / "example-bytes-2"
        again_bytes.mkdir(mode=0o700)
        recovered = subprocess.run(
            _example_args(
                lane,
                config,
                key="example-1",
                receipt=again_receipt,
                download=again_bytes,
                wrapper=wrapper,
                diag=diag_path,
            ),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert recovered.returncode == 0, recovered.stderr + "\n" + _diag_summary(diag_path)
        again = json.loads(again_receipt.read_bytes())
        assert again["jobId"] == job_id
        assert (again_bytes / (job_id + ".tif")).read_bytes() == downloaded.read_bytes()


def test_workflow_example_refuses_without_leakage(tmp_path: Path) -> None:
    root = tmp_path / "example-denied"
    root.mkdir(mode=0o700)
    with fixture.task5_ai_lane(root, kind="dsm") as lane:
        config = fixture.task5_sdk_config(lane.origin, name="example-denied")
        lane.revoke_grant()
        receipt_path = tmp_path / "receipt-denied.json"
        wrapper, diag_path = _write_workflow_wrapper(root)
        completed = subprocess.run(
            _example_args(
                lane,
                config,
                key="example-denied",
                receipt=receipt_path,
                download=None,
                wrapper=wrapper,
                diag=diag_path,
            ),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert completed.returncode == 2, _diag_summary(diag_path)
        # Constant guard: a revoked-grant denial must surface the exact closed
        # code, never the generic mapping. The refined trace proved the true
        # ValueError("REQUEST_DENIED") is absorbed into anyio ExceptionGroups
        # during SDK teardown; the example normalizer must recover it.
        assert "REQUEST_DENIED" in completed.stderr, _diag_summary(diag_path)
        assert "ADAPTER_UNAVAILABLE" not in completed.stderr, _diag_summary(diag_path)
        assert not receipt_path.exists()
        assert fixture.TASK5_AI_TOKEN not in completed.stdout + completed.stderr


def _load_workflow_module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("mcp_native_window_workflow", str(EXAMPLE))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli_base(tmp_path: Path, config: Path, receipt: Path) -> list[str]:
    return [
        "--config",
        str(config),
        "--site-id",
        "site-1",
        "--work-area-id",
        "area-1",
        "--asset-ref",
        "asset-1",
        "--bounds",
        "0.0",
        "0.0",
        "1.0",
        "1.0",
        "--crs-digest",
        "sha256:" + "ab" * 32,
        "--idempotency-key",
        "key-1",
        "--poll-budget-seconds",
        "5",
        "--receipt-out",
        str(receipt),
    ]


def test_parse_rejects_nonfinite_budgets_and_bounds(tmp_path: Path, capsys: Any) -> None:
    workflow = _load_workflow_module()
    config = tmp_path / "c.json"
    config.write_text("{}")
    receipt = tmp_path / "r.json"
    for budget, interval in [
        ("inf", "0.5"),
        ("nan", "0.5"),
        ("0", "0.5"),
        ("-1", "0.5"),
        ("5", "inf"),
        ("5", "nan"),
        ("5", "0"),
        ("1", "5"),
    ]:
        argv = _cli_base(tmp_path, config, receipt)
        argv[argv.index("--poll-budget-seconds") + 1] = budget
        if "--poll-interval-seconds" in argv:
            argv[argv.index("--poll-interval-seconds") + 1] = interval
        else:
            argv += ["--poll-interval-seconds", interval]
        with __import__("pytest").raises(SystemExit) as exc:
            workflow._parse_args(argv)
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "inf" not in err.lower() or "finite" in err.lower()
        assert "nan" not in err.lower() or "finite" in err.lower()
    argv = _cli_base(tmp_path, config, receipt)
    bounds_at = argv.index("--bounds") + 1
    argv[bounds_at] = "inf"
    with __import__("pytest").raises(SystemExit) as exc:
        workflow._parse_args(argv)
    assert exc.value.code == 2


def test_unknown_cli_errors_hide_arguments(tmp_path: Path, capsys: Any) -> None:
    workflow = _load_workflow_module()
    marker = "SECRET-MARKER-9f31"
    config = tmp_path / "c.json"
    config.write_text("{}")
    receipt = tmp_path / "r.json"
    argv = _cli_base(tmp_path, config, receipt) + ["--no-such-flag", marker]
    code = workflow.main(argv)
    assert code == 2
    captured = capsys.readouterr()
    assert marker not in captured.err + captured.out


def test_fail_emits_closed_codes_only(capsys: Any) -> None:
    workflow = _load_workflow_module()
    assert workflow.main is not None
    code = workflow._fail("super-secret-marker-xyz-123")
    assert code == 2
    err = capsys.readouterr().err
    assert "super-secret-marker-xyz-123" not in err
    code = workflow._fail("REQUEST_DENIED")
    assert code == 2
    err = capsys.readouterr().err
    assert "REQUEST_DENIED" in err


def test_protected_config_and_token_refused(tmp_path: Path) -> None:
    workflow = _load_workflow_module()
    import spatial_data_mcp_fixture as fix

    origin = "http://127.0.0.1:9"
    good_token = fix.write_token("subtb-good-token", "opaque-test-token")
    good_config = fix.write_adapter_config(
        "subtb-good-adapter.json", origin=origin, token_path=good_token
    )
    loaded = workflow._load_config(good_config)
    assert loaded.core_origin == origin
    assert loaded.read_token() == "opaque-test-token"
    bad_token = fix.write_token("subtb-bad-token", "opaque-test-token")
    bad_token.chmod(0o644)
    bad_config = fix.write_adapter_config(
        "subtb-bad-adapter.json", origin=origin, token_path=bad_token
    )
    with __import__("pytest").raises(ValueError) as exc:
        workflow._load_config(bad_config)
    assert "opaque-test-token" not in str(exc.value)
    assert str(exc.value) in workflow._SAFE_CODES


def test_run_enforces_overall_deadline_on_stalled_sdk(tmp_path: Path) -> None:
    workflow = _load_workflow_module()
    import argparse
    import asyncio
    import time as _time

    async def _stall(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(30)
        raise AssertionError("stalled call was not bounded")

    class _FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def initialize(self) -> None:
            await _stall()

        async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
            await _stall()

    class _FakeStdio:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Any:
            return (None, None)

        async def __aexit__(self, *args: Any) -> bool:
            return False

    import mcp.client.session as _session_mod
    import mcp.client.stdio as _stdio_mod

    real_session = _session_mod.ClientSession
    real_stdio = _stdio_mod.stdio_client
    _session_mod.ClientSession = _FakeSession  # type: ignore[assignment, misc]
    _stdio_mod.stdio_client = lambda *a, **k: _FakeStdio()  # type: ignore[assignment]
    try:
        args = argparse.Namespace(
            config=tmp_path / "c.json",
            site_id="site-1",
            work_area_id="area-1",
            asset_ref="asset-1",
            bounds=(0.0, 0.0, 1.0, 1.0),
            crs_digest="sha256:" + "ab" * 32,
            idempotency_key="key-1",
            poll_budget_seconds=0.4,
            poll_interval_seconds=0.05,
        )
        started = _time.monotonic()
        with __import__("pytest").raises(ValueError) as exc:
            asyncio.run(workflow._run(args, config=None))
        elapsed = _time.monotonic() - started
        assert str(exc.value) in workflow._SAFE_CODES
        assert elapsed < 5.0
    finally:
        _session_mod.ClientSession = real_session  # type: ignore[misc]
        _stdio_mod.stdio_client = real_stdio


def test_validates_scope_and_rejects_free_text() -> None:
    workflow = _load_workflow_module()
    import pytest as _pytest

    job = {
        "jobId": "sdj-v1-11111111-1111-1111-1111-111111111111",
        "assetRef": "asset-1",
        "siteId": "WRONG-SITE",
        "workAreaId": "area-1",
        "createdAt": "2026-01-01T00:00:00Z",
        "executionState": "QUEUED",
        "availability": "UNAVAILABLE",
    }
    with _pytest.raises(ValueError) as exc:
        workflow._validated_create_view(
            job, site_id="site-1", work_area_id="area-1", asset_ref="asset-1"
        )
    assert "WRONG-SITE" not in str(exc.value)
    assert str(exc.value) in workflow._SAFE_CODES
    coerced = workflow._coerce_code("free reason string with secrets")
    assert coerced in workflow._SAFE_CODES
    assert "free reason" not in coerced


def test_persist_is_atomic_no_partial(tmp_path: Path) -> None:
    workflow = _load_workflow_module()
    import json as _json
    import os as _os

    target = tmp_path / "receipt.json"
    workflow._persist_json(target, {"jobId": "a"})
    first = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    with __import__("pytest").raises(ValueError) as exc:
        workflow._persist_json(target, {"jobId": "b"})
    assert target.read_bytes() == first
    assert str(exc.value) in workflow._SAFE_CODES
    link_target = tmp_path / "real.json"
    link_target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    _os.symlink(link_target, link)
    with __import__("pytest").raises(ValueError):
        workflow._persist_json(link, {"jobId": "c"})
    assert link.is_symlink()
    assert link_target.read_bytes() == b"{}"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".receipt-")]
    assert leftovers == []
    record = _json.loads(target.read_bytes())
    assert record["jobId"] == "a"


def _spy_consumer(monkeypatch: Any) -> Any:
    import native_window_client as _consumer_mod

    seen: dict[str, Any] = {}

    class _SpyClient:
        def __init__(self, **kwargs: Any) -> None:
            seen.clear()
            seen.update(kwargs)

        def download(self, *, status: dict[str, Any], output_dir: Path) -> Path:
            seen["status_job_id"] = status.get("jobId")
            seen["output_dir"] = str(output_dir)
            return Path("sdj-v1-11111111-1111-1111-1111-111111111111.tif")

        def close(self) -> None:
            return None

    monkeypatch.setattr(_consumer_mod, "NativeWindowClient", _SpyClient)
    return seen


def _spy_view() -> dict[str, Any]:
    job_id = "sdj-v1-11111111-1111-1111-1111-111111111111"
    return {
        "jobId": job_id,
        "executionState": "COMPLETED",
        "receipt": {
            "jobId": job_id,
            "outputSha256": "sha256:" + "cd" * 32,
            "outputSizeBytes": 200000,
        },
    }


def test_max_download_bytes_custom_honored_without_raising_json_quota(
    tmp_path: Path, monkeypatch: Any
) -> None:
    workflow = _load_workflow_module()
    import spatial_data_mcp_fixture as fix

    token = fix.write_token("fix2-spy-token", "opaque-test-token")
    config = fix.write_adapter_config(
        "fix2-spy-adapter.json", origin="http://127.0.0.1:9", token_path=token
    )
    argv = _cli_base(tmp_path, config, tmp_path / "r.json")
    argv += ["--max-download-bytes", "300000"]
    args = workflow._parse_args(argv)
    assert args.max_download_bytes == 300000
    assert workflow._parse_download_budget(300000) == 300000
    seen = _spy_consumer(monkeypatch)
    download_dir = tmp_path / "bytes"
    download_dir.mkdir(mode=0o700)
    args.download_dir = download_dir
    name = workflow._download(args, _spy_view(), config=workflow._load_config(config))
    assert name == "sdj-v1-11111111-1111-1111-1111-111111111111.tif"
    assert seen["max_file_bytes"] == 300000
    assert seen["max_json_bytes"] == 131072
    assert seen["status_job_id"] == "sdj-v1-11111111-1111-1111-1111-111111111111"


def test_max_download_bytes_invalid_rejected_without_reflection(
    tmp_path: Path, capsys: Any
) -> None:
    workflow = _load_workflow_module()
    import pytest as _pytest

    config = tmp_path / "c.json"
    config.write_text("{}")
    for raw in ["0", "-1", "-100", "abc", "1.5", "", "1" * 30, "SECRET-MARKER-77"]:
        argv = _cli_base(tmp_path, config, tmp_path / "r.json")
        argv += ["--max-download-bytes", raw]
        with _pytest.raises(SystemExit) as exit_info:
            workflow._parse_args(argv)
        assert exit_info.value.code == 2
        err = capsys.readouterr().err
        assert "INVALID_ARGUMENTS" in err
        assert "SECRET-MARKER-77" not in err
    for candidate in [True, False, 1.5, "300000", -3, 0, 1 << 41]:
        with _pytest.raises(ValueError) as value_info:
            workflow._parse_download_budget(candidate)
        assert str(value_info.value) in workflow._SAFE_CODES
        assert "SECRET" not in str(value_info.value)
    assert workflow._parse_download_budget(None) is None


def test_max_download_bytes_default_unchanged(tmp_path: Path, monkeypatch: Any) -> None:
    workflow = _load_workflow_module()
    import spatial_data_mcp_fixture as fix

    token = fix.write_token("fix2-default-token", "opaque-test-token")
    config = fix.write_adapter_config(
        "fix2-default-adapter.json", origin="http://127.0.0.1:9", token_path=token
    )
    args = workflow._parse_args(_cli_base(tmp_path, config, tmp_path / "r.json"))
    assert args.max_download_bytes is None
    seen = _spy_consumer(monkeypatch)
    download_dir = tmp_path / "bytes"
    download_dir.mkdir(mode=0o700)
    args.download_dir = download_dir
    workflow._download(args, _spy_view(), config=workflow._load_config(config))
    assert seen["max_file_bytes"] == 131072
    assert seen["max_json_bytes"] == 131072


def _closed(value: str) -> ValueError:
    return ValueError(value)


def test_group_normalizer_keeps_single_closed_code_with_teardown_noise() -> None:
    import asyncio

    workflow = _load_workflow_module()
    group = BaseExceptionGroup(
        "teardown",
        [
            _closed("REQUEST_DENIED"),
            asyncio.CancelledError(),
            RuntimeError("teardown-boom-marker"),
        ],
    )
    mapped = workflow._normalize_group_error(group)
    assert isinstance(mapped, ValueError)
    assert str(mapped) == "REQUEST_DENIED"
    assert "teardown-boom-marker" not in str(mapped)


def test_group_normalizer_keeps_poll_denied_code() -> None:
    workflow = _load_workflow_module()
    mapped = workflow._normalize_group_error(ExceptionGroup("g", [_closed("STATUS_DENIED")]))
    assert str(mapped) == "STATUS_DENIED"


def test_group_normalizer_flattens_nested_single_code() -> None:
    workflow = _load_workflow_module()
    inner = ExceptionGroup("inner", [_closed("POLL_BUDGET_EXCEEDED")])
    mapped = workflow._normalize_group_error(ExceptionGroup("outer", [inner]))
    assert str(mapped) == "POLL_BUDGET_EXCEEDED"


def test_group_normalizer_recovers_code_from_suppressed_context() -> None:
    workflow = _load_workflow_module()
    try:
        raise _closed("REQUEST_DENIED")
    except ValueError as closed:
        try:
            raise RuntimeError("teardown-context-marker")
        except RuntimeError as noise:
            group = ExceptionGroup("teardown", [noise])
            group.__context__ = closed
    mapped = workflow._normalize_group_error(group)
    assert str(mapped) == "REQUEST_DENIED"
    assert "teardown-context-marker" not in str(mapped)


def test_group_normalizer_mixed_codes_stay_unavailable() -> None:
    workflow = _load_workflow_module()
    group = ExceptionGroup("g", [_closed("REQUEST_DENIED"), _closed("STATUS_DENIED")])
    assert str(workflow._normalize_group_error(group)) == "ADAPTER_UNAVAILABLE"


def test_group_normalizer_unknown_stays_unavailable_without_reflection() -> None:
    workflow = _load_workflow_module()
    group = ExceptionGroup("g", [RuntimeError("SECRET-MARKER-41")])
    mapped = workflow._normalize_group_error(group)
    assert str(mapped) == "ADAPTER_UNAVAILABLE"
    assert "SECRET-MARKER-41" not in str(mapped)


def test_group_normalizer_non_allowlisted_code_stays_unavailable() -> None:
    workflow = _load_workflow_module()
    mapped = workflow._normalize_group_error(ExceptionGroup("g", [_closed("EVIL-RAW")]))
    assert str(mapped) == "ADAPTER_UNAVAILABLE"
    assert "EVIL-RAW" not in str(mapped)


def test_group_normalizer_rejects_subclass_and_shapeless_codes() -> None:
    workflow = _load_workflow_module()

    class _Sub(ValueError):
        pass

    assert (
        str(workflow._normalize_group_error(ExceptionGroup("g", [_Sub("REQUEST_DENIED")])))
        == "ADAPTER_UNAVAILABLE"
    )
    assert (
        str(workflow._normalize_group_error(ExceptionGroup("g", [ValueError()])))
        == "ADAPTER_UNAVAILABLE"
    )
    assert (
        str(workflow._normalize_group_error(ExceptionGroup("g", [ValueError("A", "B")])))
        == "ADAPTER_UNAVAILABLE"
    )


def test_group_normalizer_noise_only_stays_unavailable() -> None:
    import asyncio

    workflow = _load_workflow_module()
    group = BaseExceptionGroup("g", [asyncio.CancelledError()])
    assert str(workflow._normalize_group_error(group)) == "ADAPTER_UNAVAILABLE"


def test_group_normalizer_preserves_interruption() -> None:
    workflow = _load_workflow_module()
    group = BaseExceptionGroup("g", [_closed("REQUEST_DENIED"), KeyboardInterrupt()])
    with __import__("pytest").raises(BaseExceptionGroup) as exc:
        workflow._normalize_group_error(group)
    assert exc.value is group


def test_run_propagates_true_outer_cancellation(tmp_path: Path) -> None:
    workflow = _load_workflow_module()
    import argparse
    import asyncio

    async def _stall(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(30)
        raise AssertionError("stalled call was not bounded")

    class _FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def initialize(self) -> None:
            await _stall()

        async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
            await _stall()

    class _FakeStdio:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Any:
            return (None, None)

        async def __aexit__(self, *args: Any) -> bool:
            return False

    import mcp.client.session as _session_mod
    import mcp.client.stdio as _stdio_mod

    real_session = _session_mod.ClientSession
    real_stdio = _stdio_mod.stdio_client
    _session_mod.ClientSession = _FakeSession  # type: ignore[assignment, misc]
    _stdio_mod.stdio_client = lambda *a, **k: _FakeStdio()  # type: ignore[assignment]
    try:
        args = argparse.Namespace(
            config=tmp_path / "c.json",
            site_id="site-1",
            work_area_id="area-1",
            asset_ref="asset-1",
            bounds=(0.0, 0.0, 1.0, 1.0),
            crs_digest="sha256:" + "ab" * 32,
            idempotency_key="key-1",
            poll_budget_seconds=60.0,
            poll_interval_seconds=0.05,
        )

        async def _drive() -> None:
            runner = asyncio.ensure_future(workflow._run(args, config=None))
            await asyncio.sleep(0.1)
            runner.cancel()
            await runner

        with __import__("pytest").raises(asyncio.CancelledError):
            asyncio.run(_drive())
    finally:
        _session_mod.ClientSession = real_session  # type: ignore[misc]
        _stdio_mod.stdio_client = real_stdio
