"""Read current, caller-authorized surface-profile results from Core."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileComparisonV1,
    SurfaceProfileResultViewV1,
)
from pydantic import ValidationError

from ksi_processing_controller.spatial_data_worker_config import (
    SpatialDataWorkerConfigError,
    parse_strict_json,
    read_spatial_data_core_token,
)

MAX_RESPONSE_BYTES = 2_000_000
JOB_ID = re.compile(r"^spj-[0-9a-f]{32}$")
SCOPE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class ProfileCliError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        self.exit_code = exit_code
        super().__init__(message)


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ProfileCliError("Core 오리진 형식이 올바르지 않습니다.", exit_code=2) from exc
    host = parsed.hostname
    local_http = False
    if host:
        try:
            local_http = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_http = host.lower() == "localhost"
    if (
        parsed.scheme not in ({"https", "http"} if local_http else {"https"})
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ProfileCliError(
            "Core 주소는 HTTPS 오리진이어야 합니다. HTTP는 localhost와 loopback에서만 허용됩니다.",
            exit_code=2,
        )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, "", "", ""))


def _identifier(value: str, label: str) -> str:
    if not SCOPE_ID.fullmatch(value) or value in {".", ".."}:
        raise ProfileCliError(f"{label} 식별자 형식이 올바르지 않습니다.", exit_code=2)
    return value


def _job_id(value: str) -> str:
    if not JOB_ID.fullmatch(value):
        raise ProfileCliError("단면 작업 ID 형식이 올바르지 않습니다.", exit_code=2)
    return value


def _decision_id(value: str) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProfileCliError("비교 판정 ID 형식이 올바르지 않습니다.", exit_code=2) from exc
    if not value or len(encoded) > 255 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProfileCliError("비교 판정 ID 형식이 올바르지 않습니다.", exit_code=2)
    return value


def _read_bearer(path: Path) -> str:
    try:
        return read_spatial_data_core_token(path)
    except SpatialDataWorkerConfigError as exc:
        raise ProfileCliError(
            "소유자 전용 인증 파일에서 유효한 bearer token을 읽을 수 없습니다.", exit_code=2
        ) from exc


def _safe_reason(body: bytes) -> str | None:
    try:
        value: Any = parse_strict_json(body)
    except (ValueError, RecursionError):
        value = None
    if isinstance(value, dict):
        for key in ("reason", "code", "detail"):
            reason = value.get(key)
            if isinstance(reason, str) and _REASON_CODE.fullmatch(reason):
                return reason
            if isinstance(reason, dict):
                nested = reason.get("reason")
                if isinstance(nested, str) and _REASON_CODE.fullmatch(nested):
                    return nested
    return None


def _http_reason(status: int) -> str:
    return {
        401: "AUTHENTICATION_REQUIRED",
        403: "CURRENT_READ_PERMISSION_REQUIRED",
        404: "NOT_FOUND_OR_OUTSIDE_CURRENT_SCOPE",
        409: "RESULT_UNAVAILABLE_OR_CURRENT_DECISION_CHANGED",
        410: "RETENTION_EXPIRED",
        422: "INVALID_REQUEST",
        429: "REQUEST_LIMIT_REACHED",
        503: "CURRENT_AUTHORITY_UNAVAILABLE",
    }.get(status, "CORE_REQUEST_FAILED")


class SurfaceProfileReadClient:
    """Two purpose-built GETs; this client does not accept an arbitrary route or HTTP method."""

    def __init__(
        self,
        *,
        core_origin: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._origin = _origin(core_origin)
        self._http = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(connect=4.0, read=20.0, write=4.0, pool=4.0),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self._origin}{path}"
        if params:
            url += "?" + urlencode(params)
        try:
            with self._http.stream("GET", url) as response:
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ProfileCliError("Core가 요청한 인코딩으로 응답하지 않았습니다.")
                if response.status_code != 200:
                    error_body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16_384):
                        if len(error_body) + len(chunk) > 16_384:
                            error_body.clear()
                            break
                        error_body.extend(chunk)
                    reason = _safe_reason(bytes(error_body)) or _http_reason(response.status_code)
                    raise ProfileCliError(f"Core 요청 거부. HTTP {response.status_code} {reason}")
                declared_length = response.headers.get("Content-Length")
                if declared_length is not None and int(declared_length) > MAX_RESPONSE_BYTES:
                    raise ProfileCliError("Core 응답이 허용 크기를 넘었습니다.")
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65_536):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ProfileCliError("Core 응답이 허용 크기를 넘었습니다.")
                    body.extend(chunk)
                value = parse_strict_json(bytes(body))
        except ProfileCliError:
            raise
        except (httpx.HTTPError, OSError, ValueError, RecursionError) as exc:
            raise ProfileCliError(
                "Core 조회에 실패했습니다. 연결과 현재 권한을 확인하세요."
            ) from exc
        if not isinstance(value, dict):
            raise ProfileCliError("Core 응답의 형태가 올바르지 않습니다.")
        return value

    def profile(self, *, site_id: str, work_area_id: str, job_id: str) -> dict[str, Any]:
        site = quote(_identifier(site_id, "현장"), safe="")
        area = quote(_identifier(work_area_id, "작업구역"), safe="")
        job = quote(_job_id(job_id), safe="")
        path = f"/v1/sites/{site}/work-areas/{area}/surface-profile-jobs/{job}/result"
        payload = self._get(path)
        try:
            view = SurfaceProfileResultViewV1.model_validate(payload)
            stored, result = view.job, view.result
            receipt = stored.receipt
            if (
                stored.job_id != job_id
                or stored.site_id != site_id
                or stored.work_area_id != work_area_id
                or stored.execution_state != "COMPLETED"
                or stored.availability != "AVAILABLE"
                or stored.asset_ref != result.asset_ref
                or stored.feature != result.feature
                or stored.feature.line_digest != result.line_digest
                or result.result_digest is None
                or receipt is None
                or receipt.receipt_digest is None
                or receipt.job_id != job_id
                or receipt.result_digest != result.result_digest
                or receipt.window_cells_read != result.window_cells_read
            ):
                raise ValueError("result, job and receipt must agree")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ProfileCliError(
                "Core 결과가 완료된 현재 범위의 단면 계약과 일치하지 않습니다."
            ) from exc
        return view.model_dump(mode="json", by_alias=True)

    def comparison(
        self,
        *,
        site_id: str,
        work_area_id: str,
        baseline_job_id: str,
        current_job_id: str,
        decision_id: str,
    ) -> dict[str, Any]:
        site = quote(_identifier(site_id, "현장"), safe="")
        area = quote(_identifier(work_area_id, "작업구역"), safe="")
        baseline = _job_id(baseline_job_id)
        current = _job_id(current_job_id)
        decision = _decision_id(decision_id)
        if baseline == current:
            raise ProfileCliError("기준과 현재 작업은 서로 다른 ID여야 합니다.", exit_code=2)
        path = f"/v1/sites/{site}/work-areas/{area}/surface-profile-comparisons"
        payload = self._get(
            path,
            params={
                "baseline_job_id": baseline,
                "current_job_id": current,
                "decision_id": decision,
            },
        )
        try:
            comparison = SurfaceProfileComparisonV1.model_validate(payload)
            if (
                comparison.baseline_job_id != baseline
                or comparison.current_job_id != current
                or comparison.decision_id != decision
                or (comparison.result is not None and comparison.result.comparison_digest is None)
            ):
                raise ValueError("stored comparison identity does not match the request")
        except (TypeError, ValueError, ValidationError) as exc:
            raise ProfileCliError(
                "Core 비교 결과가 저장된 두 작업 및 판정 ID와 일치하지 않습니다."
            ) from exc
        return comparison.model_dump(mode="json", by_alias=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksi-surface-profile",
        description="현재 권한으로 저장 선의 단면 또는 이미 저장된 두 시점 비교를 읽습니다.",
    )
    parser.add_argument(
        "--core-origin", required=True, help="Core HTTPS origin, 예: https://core.example.org"
    )
    parser.add_argument(
        "--token-file", required=True, type=Path, help="소유자 전용 0600 bearer 파일"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    profile = commands.add_parser("profile", help="완료된 단일 표면 단면을 읽습니다.")
    profile.add_argument("--site-id", required=True)
    profile.add_argument("--work-area-id", required=True)
    profile.add_argument("--job-id", required=True)
    comparison = commands.add_parser(
        "comparison", help="정확한 저장 판정과 현재 두 시점 결과를 읽습니다."
    )
    comparison.add_argument("--site-id", required=True)
    comparison.add_argument("--work-area-id", required=True)
    comparison.add_argument("--baseline-job-id", required=True)
    comparison.add_argument("--current-job-id", required=True)
    comparison.add_argument("--decision-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    values = _parser().parse_args(argv)
    try:
        token = _read_bearer(values.token_file)
        client = SurfaceProfileReadClient(core_origin=values.core_origin, token=token)
        try:
            if values.command == "profile":
                value = client.profile(
                    site_id=values.site_id,
                    work_area_id=values.work_area_id,
                    job_id=values.job_id,
                )
            else:
                value = client.comparison(
                    site_id=values.site_id,
                    work_area_id=values.work_area_id,
                    baseline_job_id=values.baseline_job_id,
                    current_job_id=values.current_job_id,
                    decision_id=values.decision_id,
                )
        finally:
            client.close()
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except ProfileCliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
