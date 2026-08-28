"""Temporary, local-only FIELD-0a evidence upload receiver.

The receiver deliberately has a very small surface: a capability URL presents
one Korean multipart form and accepts one evidence object into a pre-existing,
owner-only FIELD-0a session.  It has no discovery, download, listing, or
outbound network functionality.  It is separate from the read-only Pilot 2
JSBridge probe because this process performs a narrowly scoped evidence-store
write.  It never calls a DJI function or writes to the aircraft/controller.
A short menu can be enabled on the private bind address so an operator never
needs to type or copy the capability token.  Exact client IPs remain an
optional additional restriction when the WebView source address is stable.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import ipaddress
import json
import os
import re
import secrets
import stat
import zipfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Final, cast
from urllib.parse import parse_qs, urlencode, urlsplit

_ROOT_PATH: Final = "/"
_UPLOAD_PATH: Final = "/field-evidence/upload"
_MAX_UPLOAD_BYTES: Final = 64 * 1024 * 1024
_MAX_PART_HEADER_BYTES: Final = 8 * 1024
_MAX_KMZ_MEMBERS: Final = 512
_MAX_KMZ_UNCOMPRESSED_BYTES: Final = 128 * 1024 * 1024
_BOUNDARY_RE: Final = re.compile(r"^[A-Za-z0-9'()+_,./:=?-]{1,70}$")
_SLOT_FILENAMES: Final = {
    "pilot-import-a": "pilot-import-A.raw",
    "pilot-import-b": "pilot-import-B.raw",
    "pilot-import-c": "pilot-import-C.raw",
    "pilot-export": "pilot-export.kmz",
    "m4d-original": "m4d-original.raw",
}
_SLOT_LABELS: Final = {
    "pilot-import-a": "Pilot import A 화면",
    "pilot-import-b": "Pilot import B 화면",
    "pilot-import-c": "Pilot import C 화면",
    "pilot-export": "Pilot export KMZ",
    "m4d-original": "M4D 원본 JPEG/MPO",
}


class EvidenceUploadError(ValueError):
    """Raised for a client payload that cannot be accepted as FIELD evidence."""


@dataclass(frozen=True, slots=True)
class MultipartEvidence:
    """The only accepted multipart fields, after filename information is discarded."""

    slot: str
    data: bytes


def canonical_evidence_root() -> Path:
    """Return the sole allowed root; the CLI intentionally has no root option."""

    return Path.home() / ".local" / "share" / "ksi-field-evidence"


def _validate_private_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{label} 디렉터리가 존재하지 않는다") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} 디렉터리는 symlink일 수 없다")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} 경로는 디렉터리여야 한다")
    if metadata.st_uid != os.getuid():
        raise ValueError(f"{label} 디렉터리 소유자가 현재 사용자와 다르다")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError(f"{label} 디렉터리 권한은 정확히 0700이어야 한다")


def _open_validated_session(root: Path, session_name: str) -> int:
    """Validate and open exactly one direct child session without following links."""

    if not session_name or Path(session_name).name != session_name:
        raise ValueError("session은 증거 루트의 직접 자식 이름이어야 한다")
    _validate_private_directory(root, label="증거 루트")
    session = root / session_name
    if session.parent != root:
        raise ValueError("session은 증거 루트의 직접 자식 이름이어야 한다")
    _validate_private_directory(session, label="FIELD-0a session")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    root_fd = os.open(root, os.O_RDONLY | directory | nofollow)
    try:
        session_fd = os.open(
            session_name,
            os.O_RDONLY | directory | nofollow,
            dir_fd=root_fd,
        )
    finally:
        os.close(root_fd)
    try:
        opened = os.fstat(session_fd)
        if not stat.S_ISDIR(opened.st_mode) or opened.st_uid != os.getuid():
            raise ValueError("FIELD-0a session 디렉터리 검증이 실패했다")
        if stat.S_IMODE(opened.st_mode) != 0o700:
            raise ValueError("FIELD-0a session 디렉터리 권한은 정확히 0700이어야 한다")
    except Exception:
        os.close(session_fd)
        raise
    return session_fd


def _parse_multipart_content_type(value: str | None) -> bytes:
    if value is None:
        raise EvidenceUploadError("Content-Type이 필요하다")
    parts = [part.strip() for part in value.split(";")]
    if not parts or parts[0].casefold() != "multipart/form-data":
        raise EvidenceUploadError("multipart/form-data만 허용한다")
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            raise EvidenceUploadError("multipart boundary가 올바르지 않다")
        name, raw_value = part.split("=", 1)
        name = name.strip().casefold()
        raw_value = raw_value.strip()
        if name in params or not name:
            raise EvidenceUploadError("multipart parameter가 올바르지 않다")
        if raw_value.startswith('"') and raw_value.endswith('"') and len(raw_value) >= 2:
            raw_value = raw_value[1:-1]
        params[name] = raw_value
    if set(params) != {"boundary"} or not _BOUNDARY_RE.fullmatch(params["boundary"]):
        raise EvidenceUploadError("multipart boundary가 올바르지 않다")
    return params["boundary"].encode("ascii")


def _parse_part_headers(raw_headers: bytes) -> Mapping[str, str]:
    if len(raw_headers) > _MAX_PART_HEADER_BYTES:
        raise EvidenceUploadError("multipart part header가 너무 크다")
    headers: dict[str, str] = {}
    for raw_line in raw_headers.split(b"\r\n"):
        if not raw_line or raw_line.startswith((b" ", b"\t")) or b":" not in raw_line:
            raise EvidenceUploadError("multipart part header가 올바르지 않다")
        raw_name, raw_value = raw_line.split(b":", 1)
        try:
            name = raw_name.decode("ascii").casefold()
            value = raw_value.decode("latin-1").strip()
        except UnicodeDecodeError as error:
            raise EvidenceUploadError("multipart part header가 올바르지 않다") from error
        if not name or name in headers:
            raise EvidenceUploadError("중복 multipart part header는 허용하지 않는다")
        headers[name] = value
    return headers


def _form_field_name(content_disposition: str) -> tuple[str, bool]:
    pieces = [piece.strip() for piece in content_disposition.split(";")]
    if not pieces or pieces[0].casefold() != "form-data":
        raise EvidenceUploadError("Content-Disposition은 form-data여야 한다")
    params: dict[str, str] = {}
    for piece in pieces[1:]:
        if "=" not in piece:
            raise EvidenceUploadError("Content-Disposition parameter가 올바르지 않다")
        name, value = piece.split("=", 1)
        name = name.strip().casefold()
        value = value.strip()
        if name in params or not name:
            raise EvidenceUploadError("Content-Disposition parameter가 올바르지 않다")
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        params[name] = value
    field_name = params.get("name")
    if field_name not in {"slot", "evidence"}:
        raise EvidenceUploadError("허용되지 않은 multipart field다")
    # filename is intentionally never interpreted or used as a filesystem path.
    return field_name, "filename" in params


def parse_multipart_evidence(*, content_type: str | None, body: bytes) -> MultipartEvidence:
    """Strictly parse exactly ``slot`` text and one ``evidence`` file part."""

    boundary = _parse_multipart_content_type(content_type)
    opening = b"--" + boundary + b"\r\n"
    if not body.startswith(opening):
        raise EvidenceUploadError("multipart body 시작 boundary가 올바르지 않다")

    cursor = len(opening)
    slot: str | None = None
    evidence: bytes | None = None
    part_count = 0
    separator = b"\r\n--" + boundary
    while True:
        headers_end = body.find(b"\r\n\r\n", cursor)
        if headers_end < 0:
            raise EvidenceUploadError("multipart part header가 끝나지 않았다")
        headers = _parse_part_headers(body[cursor:headers_end])
        disposition = headers.get("content-disposition")
        if disposition is None:
            raise EvidenceUploadError("Content-Disposition이 필요하다")
        field_name, has_filename = _form_field_name(disposition)
        data_start = headers_end + 4
        boundary_at = body.find(separator, data_start)
        if boundary_at < 0:
            raise EvidenceUploadError("multipart 종료 boundary가 없다")
        value = body[data_start:boundary_at]
        part_count += 1
        if part_count > 2:
            raise EvidenceUploadError("multipart field는 정확히 두 개여야 한다")

        if field_name == "slot":
            if has_filename or slot is not None:
                raise EvidenceUploadError("slot field가 올바르지 않다")
            try:
                slot = value.decode("utf-8")
            except UnicodeDecodeError as error:
                raise EvidenceUploadError("slot은 UTF-8이어야 한다") from error
        elif evidence is not None or not has_filename:
            raise EvidenceUploadError("evidence file field가 올바르지 않다")
        else:
            evidence = value

        boundary_suffix = boundary_at + len(separator)
        if body[boundary_suffix:].startswith(b"--\r\n"):
            if body[boundary_suffix + 4 :] != b"":
                raise EvidenceUploadError("multipart 종료 뒤에 추가 bytes가 있다")
            break
        if body[boundary_suffix:].startswith(b"\r\n"):
            cursor = boundary_suffix + 2
            continue
        raise EvidenceUploadError("multipart boundary가 올바르지 않다")

    if part_count != 2 or slot not in _SLOT_FILENAMES or evidence is None:
        raise EvidenceUploadError("slot과 evidence file을 각각 하나씩 제공해야 한다")
    return MultipartEvidence(slot=slot, data=evidence)


def _is_jpeg(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == b"\xff\xd8\xff"


def _validate_pilot_import(data: bytes) -> None:
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or _is_jpeg(data)):
        raise EvidenceUploadError("pilot-import는 PNG 또는 JPEG여야 한다")


def _validate_pilot_export(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise EvidenceUploadError("pilot-export는 ZIP/KMZ magic이 필요하다")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        raise EvidenceUploadError("pilot-export ZIP/KMZ를 열 수 없다") from error
    if not 1 <= len(infos) <= _MAX_KMZ_MEMBERS:
        raise EvidenceUploadError("pilot-export member 수가 허용 범위를 벗어났다")

    names: set[str] = set()
    leaf_names: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or name in names
            or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
        ):
            raise EvidenceUploadError("pilot-export archive member가 안전하지 않다")
        if path.name in leaf_names:
            raise EvidenceUploadError("pilot-export archive leaf member가 중복됐다")
        names.add(name)
        leaf_names.add(path.name)
        if info.flag_bits & 0x1:
            raise EvidenceUploadError("암호화된 pilot-export member는 허용하지 않는다")
        total_uncompressed += info.file_size
        if (
            info.file_size > _MAX_KMZ_UNCOMPRESSED_BYTES
            or total_uncompressed > _MAX_KMZ_UNCOMPRESSED_BYTES
        ):
            raise EvidenceUploadError("pilot-export 압축 해제 크기가 너무 크다")
        if info.compress_size == 0 and info.file_size > 0:
            raise EvidenceUploadError("pilot-export archive member 압축 크기가 올바르지 않다")
        if info.compress_size > 0 and info.file_size > info.compress_size * 1_000:
            raise EvidenceUploadError("pilot-export archive member 압축 비율이 너무 크다")
    if not {"template.kml", "waylines.wpml"}.issubset(leaf_names):
        raise EvidenceUploadError("pilot-export에 template.kml과 waylines.wpml이 필요하다")


def validate_evidence(slot: str, data: bytes) -> None:
    """Validate the minimum magic and archive safety for a server-fixed slot."""

    if not data:
        raise EvidenceUploadError("빈 evidence file은 허용하지 않는다")
    if slot in {"pilot-import-a", "pilot-import-b", "pilot-import-c"}:
        _validate_pilot_import(data)
    elif slot == "pilot-export":
        _validate_pilot_export(data)
    elif slot == "m4d-original":
        if not _is_jpeg(data):
            raise EvidenceUploadError("m4d-original은 JPEG/MPO magic이 필요하다")
    else:
        raise EvidenceUploadError("알 수 없는 evidence slot이다")


class Field0aEvidenceReceiver(ThreadingHTTPServer):
    """Server state containing one opened private session and one capability."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        session_fd: int,
        capability_token: str,
        short_entry_enabled: bool,
        short_entry_clients: frozenset[str],
    ) -> None:
        super().__init__(server_address, Field0aEvidenceReceiverHandler)
        self.session_fd = session_fd
        self.capability_token = capability_token
        self.short_entry_enabled = short_entry_enabled
        self.short_entry_clients = short_entry_clients

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            if self.session_fd >= 0:
                os.close(self.session_fd)
                self.session_fd = -1


class Field0aEvidenceReceiverHandler(BaseHTTPRequestHandler):
    """Serve one IP-limited menu and one capability-authenticated upload form."""

    server_version = "KSI-FIELD0A-Evidence/1.1"
    sys_version = ""

    @property
    def evidence_server(self) -> Field0aEvidenceReceiver:
        return cast(Field0aEvidenceReceiver, self.server)

    def _is_upload_path(self) -> bool:
        return urlsplit(self.path).path == _UPLOAD_PATH

    def _is_root_path(self) -> bool:
        return urlsplit(self.path).path == _ROOT_PATH

    def _query_parameters(self) -> Mapping[str, list[str]] | None:
        try:
            return parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=False,
                max_num_fields=2,
            )
        except ValueError:
            return None

    def _authenticated(self) -> bool:
        query = self._query_parameters()
        if query is None:
            return False
        tokens = query.get("token")
        return tokens is not None and len(tokens) == 1 and secrets.compare_digest(
            tokens[0], self.evidence_server.capability_token
        )

    def _short_entry_allowed(self) -> bool:
        if not self.evidence_server.short_entry_enabled:
            return False
        if not self.evidence_server.short_entry_clients:
            return True
        try:
            client_ip = str(ipaddress.ip_address(self.client_address[0]))
        except ValueError:
            return False
        return client_ip in self.evidence_server.short_entry_clients

    def _requested_slot(self) -> str | None:
        query = self._query_parameters()
        if query is None:
            return None
        slots = query.get("slot")
        if slots is None:
            return next(iter(_SLOT_LABELS))
        if len(slots) != 1 or slots[0] not in _SLOT_LABELS:
            return None
        return slots[0]

    def _send(
        self,
        status: HTTPStatus,
        body: bytes = b"",
        *,
        content_type: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Security-Policy", _content_security_policy())
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _reject_method(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _upload_form(self, selected_slot: str) -> bytes:
        token = html.escape(self.evidence_server.capability_token, quote=True)
        action = f"{_UPLOAD_PATH}?token={token}"
        options = "".join(
            (
                f'<option value="{html.escape(slot, quote=True)}"'
                + (" selected" if slot == selected_slot else "")
                + f">{html.escape(label)}</option>"
            )
            for slot, label in _SLOT_LABELS.items()
        )
        return (
            f"""<!doctype html>
<html lang=\"ko\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>KSI FIELD-0a 증거</title></head>
<body><main><h1>FIELD-0a 증거 업로드</h1>
<p>이 임시 URL은 비공개입니다. 슬롯마다 원본 하나만 업로드합니다.</p>
<form method=\"post\" enctype=\"multipart/form-data\" action=\"{action}\">
<label>증거 종류 <select name=\"slot\" required>
{options}
</select></label>
<label>파일 <input type=\"file\" name=\"evidence\" required></label>
<button type=\"submit\">업로드</button></form>
<p><a href=\"/\">증거 메뉴로 돌아가기</a></p>
<p>업로드 뒤에는 SHA-256과 byte 수만 표시됩니다. 다운로드·목록·외부 전송은 제공하지 않습니다.</p>
</main></body></html>"""
        ).encode()

    def _root_menu(self) -> bytes:
        token = self.evidence_server.capability_token
        buttons = "".join(
            (
                '<a class="menu-button" href="'
                + html.escape(
                    f"{_UPLOAD_PATH}?{urlencode({'token': token, 'slot': slot})}",
                    quote=True,
                )
                + '">'
                + html.escape(label)
                + "</a>"
            )
            for slot, label in _SLOT_LABELS.items()
        )
        return (
            f"""<!doctype html>
<html lang=\"ko\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>KSI FIELD-0a 메뉴</title>
<style>
body{{font-family:sans-serif;margin:0;background:#f4f6f8;color:#17202a}}
main{{max-width:42rem;margin:0 auto;padding:1.25rem}}
.notice{{padding:1rem;border-radius:.75rem;background:#fff4d6;margin-bottom:1rem}}
.menu{{display:grid;gap:.75rem}}
.menu-button{{display:block;padding:1rem;border-radius:.75rem;background:#123b5d;color:white;
text-decoration:none;font-weight:700;font-size:1.05rem}}
</style></head>
<body><main><h1>FIELD-0a 증거 수집</h1>
<p class=\"notice\">프로펠러 제거 상태를 유지하고 비행·임무 실행·모터 동작을 하지 마세요.</p>
<p>올릴 증거 종류를 선택하세요.</p>
<nav class=\"menu\" aria-label=\"증거 종류\">{buttons}</nav>
<p>각 항목은 이 세션에서 한 번만 저장됩니다.</p>
</main></body></html>"""
        ).encode()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if self._is_root_path():
            if not self._short_entry_allowed():
                self._send(HTTPStatus.NOT_FOUND)
            else:
                self._send(
                    HTTPStatus.OK, self._root_menu(), content_type="text/html; charset=utf-8"
                )
        elif not self._is_upload_path():
            self._send(HTTPStatus.NOT_FOUND)
        elif not self._authenticated():
            self._send(HTTPStatus.UNAUTHORIZED)
        else:
            selected_slot = self._requested_slot()
            if selected_slot is None:
                self._send(HTTPStatus.BAD_REQUEST)
            else:
                self._send(
                    HTTPStatus.OK,
                    self._upload_form(selected_slot),
                    content_type="text/html; charset=utf-8",
                )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if not self._is_upload_path():
            self._send(HTTPStatus.NOT_FOUND)
            return
        if not self._authenticated():
            self._send(HTTPStatus.UNAUTHORIZED)
            return
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._send(HTTPStatus.LENGTH_REQUIRED)
            return
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            self.close_connection = True
            self._send(HTTPStatus.LENGTH_REQUIRED)
            return
        length = int(lengths[0])
        if length > _MAX_UPLOAD_BYTES:
            self.close_connection = True
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.close_connection = True
            self._send(HTTPStatus.BAD_REQUEST)
            return
        try:
            evidence = parse_multipart_evidence(
                content_type=self.headers.get("Content-Type"), body=body
            )
            validate_evidence(evidence.slot, evidence.data)
            digest = self._write_once(evidence.slot, evidence.data)
        except EvidenceUploadError:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        except FileExistsError:
            self._send(HTTPStatus.CONFLICT)
            return
        payload = json.dumps(
            {"slot": evidence.slot, "sha256": digest, "bytes": len(evidence.data)},
            separators=(",", ":"),
        ).encode()
        self._send(HTTPStatus.CREATED, payload, content_type="application/json; charset=utf-8")

    def _write_once(self, slot: str, data: bytes) -> str:
        filename = _SLOT_FILENAMES[slot]
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(filename, flags, 0o600, dir_fd=self.evidence_server.session_fd)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            # An incomplete object is never treated as accepted evidence.
            with suppress(FileNotFoundError):
                os.unlink(filename, dir_fd=self.evidence_server.session_fd)
            raise
        return hashlib.sha256(data).hexdigest()

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._reject_method()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._reject_method()

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._reject_method()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._reject_method()

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._reject_method()

    def log_message(self, format: str, *args: object) -> None:
        """Do not persist capability URLs, filenames, or RC addresses in access logs."""


def _content_security_policy() -> str:
    return "; ".join(
        (
            "default-src 'none'",
            "style-src 'unsafe-inline'",
            "connect-src 'none'",
            "img-src 'none'",
            "media-src 'none'",
            "object-src 'none'",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )


def build_evidence_receiver_server(
    *,
    bind: str,
    port: int,
    session_name: str,
    evidence_root: Path | None = None,
    capability_token: str | None = None,
    short_entry_enabled: bool = False,
    short_entry_clients: frozenset[str] | None = None,
) -> Field0aEvidenceReceiver:
    """Build one temporary receiver; ``evidence_root`` exists only for contract tests."""

    if not bind.strip():
        raise ValueError("bind address는 비어 있을 수 없다")
    if not 0 <= port <= 65535:
        raise ValueError("port는 0..65535 범위여야 한다")
    if capability_token is not None and not capability_token:
        raise ValueError("capability token은 비어 있을 수 없다")
    try:
        normalized_short_entry_clients = frozenset(
            str(ipaddress.ip_address(client)) for client in (short_entry_clients or ())
        )
    except ValueError as error:
        raise ValueError("short-entry client는 유효한 IP 주소여야 한다") from error
    root = canonical_evidence_root() if evidence_root is None else evidence_root
    session_fd = _open_validated_session(root, session_name)
    try:
        return Field0aEvidenceReceiver(
            (bind, port),
            session_fd=session_fd,
            capability_token=capability_token or secrets.token_urlsafe(32),
            short_entry_enabled=short_entry_enabled or bool(normalized_short_entry_clients),
            short_entry_clients=normalized_short_entry_clients,
        )
    except Exception:
        os.close(session_fd)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FIELD-0a 원본 증거를 기존 private session에 한 번씩만 업로드한다."
    )
    parser.add_argument(
        "--session",
        required=True,
        help="증거 루트 바로 아래의 기존 0700 session 이름",
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--short-menu",
        action="store_true",
        help="bind된 private network에서 짧은 / 메뉴를 활성화한다",
    )
    parser.add_argument(
        "--short-client",
        action="append",
        default=[],
        help="짧은 / 메뉴 진입을 허용할 Tailnet client IP; 반복 지정 가능",
    )
    args = parser.parse_args(argv)
    server = build_evidence_receiver_server(
        bind=args.bind,
        port=args.port,
        session_name=args.session,
        short_entry_enabled=args.short_menu,
        short_entry_clients=frozenset(args.short_client),
    )
    bound_host = server.server_address[0]
    host = bound_host.decode() if isinstance(bound_host, bytes) else bound_host
    port = int(server.server_address[1])
    if server.short_entry_enabled:
        print(f"KSI FIELD-0a private menu URL: http://{host}:{port}/", flush=True)
    else:
        print(
            f"KSI FIELD-0a private upload URL: http://{host}:{port}{_UPLOAD_PATH}?token={server.capability_token}",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EvidenceUploadError",
    "Field0aEvidenceReceiver",
    "MultipartEvidence",
    "build_evidence_receiver_server",
    "canonical_evidence_root",
    "main",
    "parse_multipart_evidence",
    "validate_evidence",
]
