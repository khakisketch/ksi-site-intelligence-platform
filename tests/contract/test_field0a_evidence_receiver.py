"""Contract tests for the temporary, capability-gated FIELD-0a receiver."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPResponse
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "hil" / "field0a_evidence_receiver.py"

_TOKEN = "test-capability-token"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("field0a_evidence_receiver", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _make_private_session(tmp_path: Path) -> tuple[Path, str, Path]:
    root = tmp_path / "ksi-field-evidence"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    session_name = "field0a-test-session"
    session = root / session_name
    session.mkdir(mode=0o700)
    session.chmod(0o700)
    return root, session_name, session


@contextmanager
def _receiver_url(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    root, session_name, session = _make_private_session(tmp_path)
    server = _tool().build_evidence_receiver_server(
        bind="127.0.0.1",
        port=0,
        session_name=session_name,
        evidence_root=root,
        capability_token=_TOKEN,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        yield f"http://127.0.0.1:{port}/field-evidence/upload?token={_TOKEN}", session
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _multipart(slot: str, data: bytes, *, filename: str = "evidence.bin") -> tuple[bytes, str]:
    boundary = "KSI-FIELD0A-TEST-BOUNDARY"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"slot\"\r\n\r\n{slot}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"evidence\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _open(request: urllib.request.Request) -> HTTPResponse:
    return urllib.request.urlopen(request, timeout=2)  # noqa: S310 - loopback server.


def _post(base_url: str, slot: str, data: bytes, *, filename: str = "evidence.bin") -> HTTPResponse:
    body, content_type = _multipart(slot, data, filename=filename)
    return _open(
        urllib.request.Request(
            base_url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
    )


def _valid_kmz() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("wpmz/template.kml", "<kml/>")
        archive.writestr("wpmz/waylines.wpml", "<wpml/>")
    return stream.getvalue()


@pytest.mark.parametrize(
    ("slot", "payload", "stored_name"),
    [
        ("pilot-import-a", b"\x89PNG\r\n\x1a\nimage", "pilot-import-A.raw"),
        ("pilot-import-b", b"\xff\xd8\xffimage", "pilot-import-B.raw"),
        ("pilot-import-c", b"\x89PNG\r\n\x1a\nimage", "pilot-import-C.raw"),
        ("pilot-export", _valid_kmz(), "pilot-export.kmz"),
        ("m4d-original", b"\xff\xd8\xff\xe1original", "m4d-original.raw"),
    ],
)
def test_receiver_accepts_each_fixed_slot_once_and_returns_digest(
    tmp_path: Path, slot: str, payload: bytes, stored_name: str
) -> None:
    with (
        _receiver_url(tmp_path) as (base_url, session),
        _post(base_url, slot, payload, filename="../../not-used.jpg") as response,
    ):
        result = response.read().decode()
        assert response.status == 201
        assert hashlib.sha256(payload).hexdigest() in result
        assert slot in result
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert "connect-src 'none'" in response.headers["Content-Security-Policy"]

    stored = session / stored_name
    assert stored.read_bytes() == payload
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert not (session / "not-used.jpg").exists()


def test_receiver_rejects_wrong_token_and_exposes_only_authenticated_form(tmp_path: Path) -> None:
    with _receiver_url(tmp_path) as (base_url, _):
        with _open(urllib.request.Request(base_url)) as response:
            html = response.read().decode()
            assert response.status == 200
            assert "FIELD-0a 증거 업로드" in html
            assert "pilot-export" in html
            assert "download" not in html.casefold()

        bad_url = base_url.replace(_TOKEN, "wrong")
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(urllib.request.Request(bad_url))
        assert caught.value.code == 401

        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(bad_url, "pilot-import-a", b"\x89PNG\r\n\x1a\nx")
        assert caught.value.code == 401

        excessive_query = f"{base_url}&a=1&b=2"
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(urllib.request.Request(excessive_query))
        assert caught.value.code == 401


@pytest.mark.parametrize(
    ("slot", "payload"),
    [
        ("pilot-import-a", b"not-an-image"),
        ("m4d-original", b"not-a-jpeg"),
        ("pilot-export", b"PK\x03\x04not-a-real-zip"),
    ],
)
def test_receiver_rejects_bad_magic(tmp_path: Path, slot: str, payload: bytes) -> None:
    with _receiver_url(tmp_path) as (base_url, _):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(base_url, slot, payload)
        assert caught.value.code == 422


def test_receiver_rejects_unsafe_kmz_member(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../template.kml", "<kml/>")
        archive.writestr("wpmz/waylines.wpml", "<wpml/>")
    with _receiver_url(tmp_path) as (base_url, _):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(base_url, "pilot-export", stream.getvalue())
        assert caught.value.code == 422


def test_receiver_rejects_ambiguous_duplicate_kmz_leaf(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("wpmz/template.kml", "<kml/>")
        archive.writestr("other/template.kml", "<kml/>")
        archive.writestr("wpmz/waylines.wpml", "<wpml/>")
    with _receiver_url(tmp_path) as (base_url, _):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(base_url, "pilot-export", stream.getvalue())
        assert caught.value.code == 422


def test_receiver_rejects_duplicate_slot_without_overwrite(tmp_path: Path) -> None:
    first = b"\x89PNG\r\n\x1a\nfirst"
    with _receiver_url(tmp_path) as (base_url, session):
        with _post(base_url, "pilot-import-a", first) as response:
            assert response.status == 201
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(base_url, "pilot-import-a", b"\x89PNG\r\n\x1a\nsecond")
        assert caught.value.code == 409
        assert (session / "pilot-import-A.raw").read_bytes() == first


def test_receiver_rejects_missing_or_chunked_content_length(tmp_path: Path) -> None:
    with _receiver_url(tmp_path) as (base_url, _):
        body, content_type = _multipart("pilot-import-a", b"\x89PNG\r\n\x1a\nx")
        request = urllib.request.Request(
            base_url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        # urllib adds Content-Length for data, so force an unsupported transfer encoding too.
        request.add_header("Transfer-Encoding", "chunked")
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(request)
        assert caught.value.code == 411


def test_receiver_rejects_declared_oversize_before_reading(tmp_path: Path) -> None:
    tool = _tool()
    with _receiver_url(tmp_path) as (base_url, _):
        request = urllib.request.Request(
            base_url,
            data=b"x",
            method="POST",
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(tool._MAX_UPLOAD_BYTES + 1),
            },
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(request)
        assert caught.value.code == 413


@pytest.mark.parametrize("mode", [0o755, 0o600])
def test_receiver_rejects_non_private_root_or_session_mode(tmp_path: Path, mode: int) -> None:
    tool = _tool()
    root, session_name, session = _make_private_session(tmp_path)
    root.chmod(mode)
    with pytest.raises(ValueError, match="0700"):
        tool.build_evidence_receiver_server(
            bind="127.0.0.1", port=0, session_name=session_name, evidence_root=root
        )
    root.chmod(0o700)
    session.chmod(mode)
    with pytest.raises(ValueError, match="0700"):
        tool.build_evidence_receiver_server(
            bind="127.0.0.1", port=0, session_name=session_name, evidence_root=root
        )


def test_receiver_rejects_symlink_and_wrong_owner_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    root, session_name, session = _make_private_session(tmp_path)
    linked = root / "linked"
    linked.symlink_to(session, target_is_directory=True)
    with pytest.raises(ValueError, match="직접 자식"):
        tool.build_evidence_receiver_server(
            bind="127.0.0.1", port=0, session_name="linked/child", evidence_root=root
        )
    with pytest.raises(ValueError, match="symlink"):
        tool.build_evidence_receiver_server(
            bind="127.0.0.1", port=0, session_name="linked", evidence_root=root
        )
    monkeypatch.setattr(os, "getuid", lambda: session.stat().st_uid + 1)
    with pytest.raises(ValueError, match="소유자"):
        tool.build_evidence_receiver_server(
            bind="127.0.0.1", port=0, session_name=session_name, evidence_root=root
        )


def test_receiver_has_no_access_log_or_download_listing_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _receiver_url(tmp_path) as (base_url, _):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _open(
                urllib.request.Request(
                    base_url.replace("/field-evidence/upload", "/pilot-import.raw")
                )
            )
        assert caught.value.code == 404
        for method in ("HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"):
            request = urllib.request.Request(
                base_url,
                data=b"" if method != "HEAD" else None,
                method=method,
            )
            with pytest.raises(urllib.error.HTTPError) as rejected:
                _open(request)
            assert rejected.value.code == 405
            assert rejected.value.headers["Allow"] == "GET, POST"
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""
