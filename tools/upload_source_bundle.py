#!/usr/bin/env python3
"""로컬 사진 디렉터리를 원본 미디어 번들로 업로드하고 재구성까지 발행 (B1 — 3D 파이프라인 입구).

디렉터리의 사진을 ``POST /v1/missions/{mission_id}/source-media`` 로 배치
등록해 presigned PUT URL 을 받고, 그 URL 로 실제 바이트를 올린 뒤(``--seal``
지정 시) ``POST .../source-media/seal`` 로 번들을 봉인하고, (``--start-reconstruction``
지정 시) ``POST /v1/missions/{mission_id}/processing-jobs`` 로 재구성 작업까지
발행한다.

## 이 도구가 닫는 구멍 — 사람이 브라우저에서 사진을 고르는 단계

제품 목표는 "사람이 웹 화면에서 사진을 직접 선택해서 업로드하는 작업 0회"다
(ADR-KSI-018 P1). 서버 쪽 입구(``source_media.py``)와 재구성 발행
(``processing_jobs.py``)은 이미 순수 JSON REST 라 브라우저가 필요 없는데,
**그 셋을 순서대로 부르는 주체가 대시보드의 버튼 세 개뿐이었다.** 이 도구가
그 주체를 사람에서 프로그램으로 옮긴다.

## 어디서 도는가 — 기체가 아니라 지상이다

ADR-KSI-013 D1/D2 확정: 매핑 원본의 주 반출 경로는 **비행 종료 후 조종기
(RC Plus 2) → 현장 서버**이고, 그 경로가 실기로 검증되기 전까지는 **SD카드
회수·수동 오프로드가 정상 경로**다. 즉 이 도구의 입력(``--source-dir``)을
채우는 주체는 매니폴드 기체가 아니라 지상의 회수 절차이며, 이 도구도 지상
서버에서 돈다. (기체 위 파이썬은 별개 문제로 막혀 있다 — 실기 인벤토리 실측
Python 3.8.10 vs 이 저장소 요구 3.12, ``hil_raw_logs/SESS-20260803T125616Z-
PENDING-SN/01_env_inventory/``. 이 도구는 그 제약과 무관하다.)

**이 도구가 하지 않는 것**: 카메라를 눌러 사진을 만드는 일. 그건 실기 종속이라
(ADR-KSI-011 H4 미검증) 여기서 흉내 내지 않는다 — 이 도구의 계약은 "누군가
디렉터리를 채워 놓으면 그 뒤는 사람 손 없이 서버까지 간다"까지다.

## 멱등성 — 서버가 이미 보장한다, 캐시는 속도일 뿐이다

같은 ``mediaId`` + 같은 신고값 재전송은 서버가 멱등 재발급으로 받고
(``source_media.py`` ``_register_one_locked``), 다른 신고값이면
``CLAIM_CONFLICT`` 로 거부한다(파일이 그 사이 바뀌었다는 뜻이므로 조용히
넘어가지 않는다). 봉인·재구성 발행도 각각 ``ALREADY_SEALED``/``ALREADY_ISSUED``
로 재시도가 안전하다.

그래서 이 도구는 **새 durable queue 를 만들지 않는다.** ``--state-dir`` 에 두는
확인 캐시는 정합성 장치가 아니라 "이미 올린 바이트를 다시 올리지 않는" 속도
장치다 — 캐시를 잃으면 전량 재업로드가 되고, 그래도 결과는 같다(서버 멱등성).

Usage::

    uv run python tools/upload_source_bundle.py \\
        --core-url http://127.0.0.1:8010 \\
        --token dev-admin-token \\
        --mission-id mission-abc \\
        --source-dir /path/to/photos \\
        --state-dir /var/lib/ksi/upload-state \\
        --seal --start-reconstruction
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from _digest import sha256_file
from ksi_core.source_media import (
    GroundControlRecord,
    SourceMediaClaim,
    compute_source_bundle_digest_from_claims,
)

_EXTENSION_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Ground-side watch/automation must use this exact set.  Keeping a second
# handwritten suffix list let the watcher announce DNG-only directories even
# though the upload/API contract rejects them; that produces a misleading
# "capture found" state with zero sealable SourceMedia records.
SUPPORTED_SOURCE_MEDIA_SUFFIXES = frozenset(_EXTENSION_CONTENT_TYPES)

# Core expands this id to the immutable profile snapshot. Keeping engine knobs
# out of the local uploader prevents it from drifting from the Console path.
RECONSTRUCTION_SPEC: dict[str, Any] = {"processingProfileId": "ksi-odm-civil-v1"}

_CONFIRMED_CACHE_NAME = "uploaded.json"

#: 지문 계산에는 쓰이지 않는 자리를 채우기 위한 고정 시각 — 이 레코드는 서버에
#: 보내지 않고 매니페스트 대조에만 쓴다(내용 필드만 지문에 들어간다).
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: presigned URL 에 바이트를 올리는 이음매 — ``(url, body, *, content_type, timeout) -> 상태코드``.
PutObject = Callable[..., int]


class _SourceBundleResponse(Protocol):
    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class _SourceBundleHttpClient(Protocol):
    def get(self, url: str) -> _SourceBundleResponse: ...

    def post(self, url: str, *, json: dict[str, Any] | None = None) -> _SourceBundleResponse: ...


def default_put_object(url: str, body: bytes, *, content_type: str, timeout: float) -> int:
    """presigned URL 로 바이트를 올린다 — **Core 인증 헤더를 절대 싣지 않는다.**

    Core 클라이언트(``httpx.Client(headers={"Authorization": ...})``)로 이 URL 을
    부르면 Core 의 bearer 토큰이 스토리지 호스트로 새어 나간다. presigned URL 은
    그 자체가 이미 자격증명이라 추가 인증이 필요 없고, 서로 다른 신뢰 경계다 —
    그래서 별도 요청으로 보낸다.

    반환은 HTTP 상태코드 하나다(호출부가 그것만 판정한다) — 테스트가 이 함수를
    갈아끼워 실제 스토리지 없이도 오케스트레이션 계약을 고정할 수 있게 하는
    이음매이기도 하다.
    """
    response = httpx.put(
        url, content=body, headers={"Content-Type": content_type}, timeout=timeout
    )
    return response.status_code


@dataclass
class SyncOutcome:
    """한 번의 동기화 실행 결과 — CLI 출력과 테스트 단언이 같은 값을 본다."""

    discovered: int = 0
    uploaded: int = 0
    #: 확인 캐시에 있어 바이트를 다시 올리지 않은 파일 수(정합성이 아니라 절약된 일).
    skipped_already_uploaded: int = 0
    failures: list[str] = field(default_factory=list)
    sealed: bool = False
    source_bundle_digest: str | None = None
    processing_job_id: str | None = None
    #: 이번 실행 전에 이미 봉인이 끝나 있었다 — 재실행이 아무것도 새로 하지 않았다는 뜻이고,
    #: 실패가 아니다(주기 실행이 첫 성공 이후 영원히 실패로 뜨는 것을 막는다).
    already_complete: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image  # noqa: PLC0415 -- 지연 import(이 스크립트 실행 시에만 필요)

    with Image.open(path) as img:
        return img.size


def _collect_files(source_dir: Path) -> list[Path]:
    """디렉터리(하위 포함)의 사진 파일 — ``ingest_watch._image_files`` 와 같은
    재귀 규칙이다. SD카드 회수 레이아웃(``<root>/<missionId>/DCIM/100MEDIA/*.JPG``)은
    한 단계짜리 나열(``iterdir``)로는 안 잡혀 발견 0장·영구 재시도 실패로 이어진다
    (``tests/contract/test_ingest_watch.py::test_finds_images_in_nested_directories``
    가 같은 레이아웃을 고정한다).
    """
    return sorted(
        p
        for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in _EXTENSION_CONTENT_TYPES
    )


def _build_claim(path: Path) -> dict[str, Any]:
    width, height = _image_size(path)
    return {
        "mediaId": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "contentType": _EXTENSION_CONTENT_TYPES[path.suffix.lower()],
    }


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ── 확인 캐시 (속도 장치, 정합성 장치가 아니다 — 모듈 docstring) ──────────────


def load_confirmed(state_dir: Path | None) -> dict[str, str]:
    """``{mediaId: sha256}`` — 바이트까지 올라간 것이 확인된 파일들.

    캐시가 없거나 깨졌으면 **빈 값으로 시작한다**(예외를 올리지 않는다). 그러면
    전량 재업로드가 되고, 서버 멱등성이 결과를 같게 만든다 — 캐시를 신뢰할 수
    없을 때 더 많이 일하는 쪽이 안전한 방향이다.
    """
    if state_dir is None:
        return {}
    path = state_dir / _CONFIRMED_CACHE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def store_confirmed(state_dir: Path | None, confirmed: dict[str, str]) -> None:
    """원자적으로 교체한다 — 중간에 죽어도 반쯤 쓰인 캐시가 남지 않는다.

    임시 파일을 **대상 디렉터리 안에** 만들어(``tempfile.mkstemp(dir=...)``)
    ``os.replace`` 가 같은 파일시스템 안 원자적 교체가 되게 한다.
    """
    if state_dir is None:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / _CONFIRMED_CACHE_NAME
    descriptor, temporary = tempfile.mkstemp(dir=str(state_dir), prefix=".uploaded-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(confirmed, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


# ── 단계별 동작 ──────────────────────────────────────────────────────────────


def _is_bundle_sealed_response(response: _SourceBundleResponse) -> bool:
    """배치 등록 거부 사유가 "이미 봉인됨"인가 — 다른 409 와 구분한다."""
    if response.status_code != 409:
        return False
    try:
        return bool(response.json().get("verdict") == "BUNDLE_SEALED")
    except ValueError:
        return False


def _local_bundle_digest(
    mission_id: str,
    claims: list[dict[str, Any]],
    ground_control: GroundControlRecord | None = None,
) -> str:
    """이 디렉터리가 만들 번들의 지문 — 서버의 sourceBundleDigest 와 같은 규칙이다.

    매니페스트 구성은 Core 함수 하나가 SSOT 다. 여기서 다시 짜면 한쪽만 바뀌는
    순간 이 대조가 조용히 무의미해진다.

    **기준점도 세어야 한다.** 서버는 봉인 지문에 기준점을 포함하므로, 여기서 빼면
    기준점을 붙인 조사를 재실행할 때마다 "다른 묶음"으로 읽혀 재등록을 시도하고
    BUNDLE_SEALED 로 실패한다(2026-08-18 병합에서 실제로 그렇게 깨졌다).
    """
    return compute_source_bundle_digest_from_claims(
        mission_id,
        [
            SourceMediaClaim(
                media_id=claim["mediaId"],
                sha256=claim["sha256"],
                size_bytes=claim["bytes"],
                width=claim["width"],
                height=claim["height"],
                content_type=claim["contentType"],
            )
            for claim in claims
        ],
        ground_control,
    )


def _sealed_bundle_matches(
    client: _SourceBundleHttpClient, *, mission_id: str, expected_digest: str
) -> bool:
    """서버의 봉인된 번들이 우리가 가진 **그 묶음**인가.

    같으면 "이미 다 올려서 봉인까지 끝난 상태"로 본다. 다르면 그건 수렴이 아니라
    **실제 불일치**다(다른 사진 묶음이 이미 그 임무에 봉인돼 있다) — 그때는 조용히
    넘어가지 않고 실패로 남긴다.

    판정 근거는 ``sourceBundleDigest`` 다. 장수로는 부족하다 — 같은 장수의 다른
    묶음을 올리려는 재실행이 조용히 성공으로 보고되고, 그 임무의 재구성은 이미 다른
    입력으로 돌아 있다(risk source-media-sealed-bundle-identity-count-only).
    """
    try:
        response = client.get(f"/v1/missions/{mission_id}/source-media")
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        bundle = response.json()
    except ValueError:
        return False
    return bool(
        bundle.get("status") == "SEALED"
        and bundle.get("sourceBundleDigest") == expected_digest
    )


def _register_and_upload(
    client: _SourceBundleHttpClient,
    *,
    mission_id: str,
    files: list[Path],
    batch_size: int,
    timeout: float,
    confirmed: dict[str, str],
    state_dir: Path | None,
    outcome: SyncOutcome,
    # 봉인 지문 대조용 — 서버가 기준점을 지문에 포함하므로 여기서도 세야 한다.
    ground_control_record: GroundControlRecord | None = None,
    put_object: PutObject,
) -> None:
    """등록 + 실제 PUT 업로드. 결과는 ``outcome`` 에 누적한다."""
    # claim 을 **배치 루프 앞에서** 전부 만든다 — 첫 배치가 BUNDLE_SEALED 로 거부될 때
    # "이 디렉터리가 그 봉인된 묶음인가"를 판정하려면 그 시점에 전체 지문이 있어야
    # 한다. 예전에는 배치 안에서 만들어서, 판정에 쓸 수 있는 사실이 장수뿐이었다
    # (risk source-media-sealed-bundle-identity-count-only).
    #
    # claim 생성 실패는 예전과 같이 그 파일만 건너뛴다. 그러면 그 파일이 지문
    # 계산에서도 빠지고 서버 지문과 달라져 수렴하지 않는데, **그것이 옳은 동작이다**
    # — 일부만 올라간 묶음을 "이미 완료"로 접으면 안 된다.
    claim_by_path: dict[Path, dict[str, Any]] = {}
    for path in files:
        try:
            claim_by_path[path] = _build_claim(path)
        except Exception as exc:  # noqa: BLE001 -- 파일 하나의 실패로 전체를 죽이지 않는다
            outcome.failures.append(f"{path.name}: claim 생성 실패 — {type(exc).__name__}: {exc}")
    local_digest = _local_bundle_digest(
        mission_id, list(claim_by_path.values()), ground_control_record
    )

    for batch_index, batch in enumerate(_chunks(files, batch_size), start=1):
        claims: list[dict[str, Any]] = []
        path_by_media_id: dict[str, Path] = {}
        for path in batch:
            claim = claim_by_path.get(path)
            if claim is None:  # claim 생성이 위에서 실패한 파일
                continue
            # 같은 mediaId 를 같은 내용으로 이미 올렸다면 바이트를 다시 올리지 않는다.
            # 등록 자체는 건너뛰지 않는다 — 서버 번들에 그 항목이 있다는 사실은
            # 서버가 답할 일이고, 캐시는 그 답을 대신하지 않는다.
            claims.append(claim)
            path_by_media_id[claim["mediaId"]] = path

        if not claims:
            continue

        try:
            response = client.post(
                f"/v1/missions/{mission_id}/source-media", json={"files": claims}
            )
        except httpx.HTTPError as exc:
            # 서버에 닿지 못하는 것은 흔한 현장 상황(네트워크 두절)이다 — traceback 이
            # 아니라 판정으로 낸다. 배치 하나가 못 갔다고 나머지 배치를 포기하지도
            # 않는다(뒤 배치가 연결 복구 후 성공할 수 있다).
            outcome.failures.append(
                f"batch {batch_index}: 등록 요청 실패 — {type(exc).__name__}: {exc}"
            )
            continue
        if response.status_code >= 400:
            # 이미 봉인된 번들에 다시 올리려 한 것은 **대개 재실행이 목표 상태에
            # 이미 도달했다는 뜻**이다 — 주기 실행이 첫 성공 이후 영원히 실패로
            # 뜨는 것을 막으려면 이것을 실패로 다루면 안 된다. 다만 "봉인돼 있다"만
            # 으로는 내용이 같다고 말할 수 없어, **번들 지문까지 대조해서 같을 때만**
            # 수렴으로 본다. 장수 대조로는 같은 장수의 다른 묶음을 걸러내지 못했다.
            if _is_bundle_sealed_response(response) and _sealed_bundle_matches(
                client, mission_id=mission_id, expected_digest=local_digest
            ):
                outcome.already_complete = True
                return
            outcome.failures.append(
                f"batch {batch_index}: 등록 요청 실패({response.status_code}) — "
                f"{response.text[:200]}"
            )
            continue

        newly_confirmed = False
        for item in response.json()["results"]:
            media_id = item["mediaId"]
            verdict = item["verdict"]
            if verdict != "REGISTERED" or not item.get("uploadUrl"):
                outcome.failures.append(f"{media_id}: {verdict} — {item.get('detail')}")
                continue
            path = path_by_media_id[media_id]
            claim_sha = next(c["sha256"] for c in claims if c["mediaId"] == media_id)
            if confirmed.get(media_id) == claim_sha:
                outcome.skipped_already_uploaded += 1
                continue
            content_type = _EXTENSION_CONTENT_TYPES[path.suffix.lower()]
            try:
                status = put_object(
                    item["uploadUrl"],
                    path.read_bytes(),
                    content_type=content_type,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                outcome.failures.append(f"{media_id}: PUT 요청 실패 — {type(exc).__name__}: {exc}")
                continue
            if status not in (200, 201, 204):
                outcome.failures.append(f"{media_id}: PUT 실패({status})")
                continue
            outcome.uploaded += 1
            confirmed[media_id] = claim_sha
            newly_confirmed = True

        # 배치마다 캐시를 굳힌다 — 중간에 죽어도 그 배치까지는 재업로드가 필요 없다.
        if newly_confirmed:
            store_confirmed(state_dir, confirmed)


def attach_ground_control(
    client: _SourceBundleHttpClient,
    mission_id: str,
    path: Path,
    crs: str,
    outcome: SyncOutcome,
    *,
    put_object: PutObject = default_put_object,
    timeout: float = 60.0,
) -> bool:
    """기준점 파일을 번들에 붙인다 — **봉인 전에** 불러야 한다.

    이 파일이 있어야 재구성 성과가 한국 평면직각좌표계로 나오고, 그래야 두 시점
    비교가 성립한다(없으면 엔진이 EXIF 로 UTM 을 고르고 비교 단계에서 거부된다).
    ``crs`` 는 파일 첫 줄과 같아야 한다 — 다르면 워커가 제출 전에 멈춘다.

    ## 재실행이 실패가 되지 않게 하는 것이 이 함수의 절반이다

    이 도구의 계약은 "재시도는 같은 명령을 다시 부르면 된다"이다(모듈 docstring).
    그런데 서버는 봉인된 번들의 기준점 등록을 ``BUNDLE_SEALED`` 로 거부하므로,
    등록을 무조건 부르면 **성공적으로 끝난 조사를 같은 명령으로 재실행할 때마다
    실패로 끝난다** — FIELD_1_GROUND_CONTROL.md 가 제시하는 명령이 정확히 그 형태다
    (독립 검토 2026-08-18 적발).

    그래서 먼저 번들 상태를 본다. 이미 봉인됐고 붙어 있는 기준점이 **같은 파일**
    이면 할 일이 없다(성공). 봉인됐는데 **다른 파일**이거나 기준점이 아예 없으면
    그건 조용히 넘어갈 일이 아니다 — 그 조사는 지금 올리려는 기준점으로 만들어진
    성과가 아니다.
    """
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()

    bundle = _fetch_bundle(client, mission_id)
    if bundle is not None and bundle.get("status") == "SEALED":
        if bundle.get("groundControlSha256") == digest and bundle.get("groundControlCrs") == crs:
            # 같은 명령의 재실행 — 이미 이 기준점으로 봉인돼 있다.
            return True
        registered_crs = bundle.get("groundControlCrs")
        registered_sha = str(bundle.get("groundControlSha256"))[:12]
        outcome.failures.append(
            "이 임무는 이미 봉인됐고, 붙어 있는 기준점이 지금 올리려는 파일과 다르다"
            f"(등록됨: {registered_crs}/{registered_sha}, 요청: {crs}/{digest[:12]}) — "
            "새 임무로 발급해 다시 올려야 한다"
        )
        return False

    request = {"sha256": digest, "bytes": len(payload), "crs": crs}
    try:
        response = client.post(
            f"/v1/missions/{mission_id}/source-media/ground-control", json=request
        )
    except httpx.HTTPError as exc:
        outcome.failures.append(f"기준점 등록 요청 실패 — {type(exc).__name__}: {exc}")
        return False
    if response.status_code not in (200, 201):
        body = response.json() if response.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}
        outcome.failures.append(
            f"기준점 등록 거부({response.status_code}) — "
            f"{body.get('verdict')}: {body.get('detail')}"
        )
        return False
    upload_url = response.json().get("uploadUrl")
    if not upload_url:
        outcome.failures.append("기준점 등록은 됐으나 업로드 URL 이 오지 않았다")
        return False
    status = put_object(
        upload_url, payload, content_type="application/octet-stream", timeout=timeout
    )
    if status not in (200, 201, 204):
        outcome.failures.append(f"기준점 PUT 실패({status})")
        return False
    return True


def _fetch_bundle(client: _SourceBundleHttpClient, mission_id: str) -> dict[str, Any] | None:
    """현재 번들 상태 — 등록된 적 없으면(404) None. 조회 실패도 None 으로 접는다.

    조회가 안 되면 등록을 시도해 서버가 판정하게 둔다 — 여기서 실패로 끊으면
    일시적 조회 오류가 업로드 전체를 막는다.
    """
    try:
        response = client.get(f"/v1/missions/{mission_id}/source-media")
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def seal_bundle(client: _SourceBundleHttpClient, mission_id: str, outcome: SyncOutcome) -> bool:
    """번들 봉인. ``ALREADY_SEALED``(200)도 성공으로 다룬다 — 재시도가 안전해야 한다."""
    try:
        response = client.post(f"/v1/missions/{mission_id}/source-media/seal")
    except httpx.HTTPError as exc:
        outcome.failures.append(f"봉인 요청 실패 — {type(exc).__name__}: {exc}")
        return False
    if response.status_code not in (200, 201):
        outcome.failures.append(
            f"봉인 실패({response.status_code}) — {response.text[:200]}"
        )
        return False
    body = response.json()
    outcome.sealed = True
    bundle = body.get("bundle") or {}
    outcome.source_bundle_digest = bundle.get("sourceBundleDigest")
    return True


def issue_reconstruction(
    client: _SourceBundleHttpClient,
    mission_id: str,
    outcome: SyncOutcome,
    *,
    spec: dict[str, Any] | None = None,
) -> bool:
    """재구성 작업 발행. ``ALREADY_ISSUED``(200)도 성공으로 다룬다(같은 사양 재요청)."""
    try:
        response = client.post(
            f"/v1/missions/{mission_id}/processing-jobs", json=spec or RECONSTRUCTION_SPEC
        )
    except httpx.HTTPError as exc:
        outcome.failures.append(f"재구성 발행 요청 실패 — {type(exc).__name__}: {exc}")
        return False
    if response.status_code not in (200, 201):
        outcome.failures.append(
            f"재구성 발행 실패({response.status_code}) — {response.text[:200]}"
        )
        return False
    job = response.json().get("job") or {}
    outcome.processing_job_id = job.get("jobId")
    return True


def run_sync(
    client: _SourceBundleHttpClient,
    *,
    mission_id: str,
    source_dir: Path,
    batch_size: int = 200,
    timeout: float = 60.0,
    state_dir: Path | None = None,
    seal: bool = False,
    start_reconstruction: bool = False,
    ground_control: Path | None = None,
    ground_control_crs: str | None = None,
    put_object: PutObject = default_put_object,
) -> SyncOutcome:
    """디렉터리 → 등록 → 업로드 → (봉인) → (재구성 발행) 전 과정 1회.

    **fail-closed 순서**: 업로드에 하나라도 실패가 있으면 봉인하지 않고, 봉인하지
    않았으면 재구성도 발행하지 않는다 — 빠진 사진이 있는 채로 번들이 잠기거나
    그 위에서 재구성이 도는 것을 막는다. 재시도는 같은 명령을 다시 부르면 된다.
    """
    outcome = SyncOutcome()
    files = _collect_files(source_dir)
    outcome.discovered = len(files)
    if not files:
        outcome.failures.append(
            f"{source_dir}: 업로드할 사진이 없다(확장자 {sorted(_EXTENSION_CONTENT_TYPES)})"
        )
        return outcome

    confirmed = load_confirmed(state_dir)
    # 기준점을 붙일 예정이면 그 레코드를 미리 만들어 지문 대조에 함께 넣는다 —
    # 서버의 봉인 지문이 기준점을 포함하기 때문이다(_local_bundle_digest).
    ground_control_record: GroundControlRecord | None = None
    if ground_control is not None and ground_control_crs is not None:
        payload = ground_control.read_bytes()
        ground_control_record = GroundControlRecord(
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            crs=ground_control_crs,
            object_key="",  # 지문에 안 들어간다(내용의 지문이지 저장소 배치의 지문이 아니다)
            registered_at=_EPOCH,
            registered_by="",
        )
    _register_and_upload(
        client,
        mission_id=mission_id,
        files=files,
        batch_size=batch_size,
        timeout=timeout,
        confirmed=confirmed,
        state_dir=state_dir,
        outcome=outcome,
        put_object=put_object,
        ground_control_record=ground_control_record,
    )

    # 기준점은 **봉인 전**에 붙인다 — 봉인이 입력 확정이라 그 뒤에는 못 붙인다.
    if ground_control is not None and not outcome.failures:
        if ground_control_crs is None:
            outcome.failures.append("기준점 파일에는 좌표계를 함께 줘야 한다")
        elif not attach_ground_control(
            client,
            mission_id,
            ground_control,
            ground_control_crs,
            outcome,
            put_object=put_object,
            timeout=timeout,
        ):
            return outcome

    if not seal or outcome.failures:
        return outcome
    # already_complete 여도 봉인·발행을 그대로 부른다 — 둘 다 멱등이라
    # (ALREADY_SEALED / ALREADY_ISSUED) 결과가 바뀌지 않고, 대신 "봉인은 됐는데
    # 재구성 발행이 빠진" 중간 상태에서 재실행이 그 구멍을 메운다.
    if not seal_bundle(client, mission_id, outcome):
        return outcome
    if not start_reconstruction:
        return outcome
    issue_reconstruction(client, mission_id, outcome)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--core-url", default="http://127.0.0.1:8000", help="Core API 베이스 URL")
    parser.add_argument(
        "--token", default=None, help="Bearer 토큰(미지정 시 KSI_CORE_TOKEN 환경변수)"
    )
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--source-dir", required=True, help="사진이 든 로컬 디렉터리")
    parser.add_argument(
        "--state-dir",
        default=None,
        help="확인 캐시를 둘 디렉터리(재실행 시 이미 올린 바이트를 건너뛴다). "
        "미지정 시 매번 전량 재업로드 — 결과는 같고 시간만 더 걸린다",
    )
    parser.add_argument(
        "--batch-size", type=int, default=200, help="요청 1건당 파일 수(서버 상한 200)"
    )
    parser.add_argument(
        "--seal", action="store_true", help="업로드 완료 후 번들을 봉인한다(기본은 봉인하지 않음)"
    )
    parser.add_argument(
        "--start-reconstruction",
        action="store_true",
        help="봉인 후 재구성 작업까지 발행한다(--seal 필요). 이 플래그가 사람의 마지막 "
        "버튼을 대체한다",
    )
    parser.add_argument(
        "--ground-control",
        default=None,
        help="지상 기준점 파일(gcp_list.txt) 경로 — 봉인 전에 번들에 붙는다. "
        "이 파일이 있어야 재구성 성과가 한국 좌표계로 나오고 두 시점 비교가 성립한다",
    )
    parser.add_argument(
        "--ground-control-crs",
        default=None,
        help="기준점 성과의 좌표계(예: EPSG:5186) — 파일 첫 줄과 같아야 한다",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP 요청 타임아웃(초)")
    args = parser.parse_args()

    token = args.token or os.environ.get("KSI_CORE_TOKEN")
    if not token:
        parser.error("--token 또는 KSI_CORE_TOKEN 환경변수가 필요하다")
    if bool(args.ground_control) != bool(args.ground_control_crs):
        parser.error("--ground-control 과 --ground-control-crs 는 함께 줘야 한다")
    if args.start_reconstruction and not args.seal:
        parser.error("--start-reconstruction 은 --seal 과 함께 써야 한다(봉인 전 재구성 불가)")

    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"{source_dir}: 디렉터리가 아니다", file=sys.stderr)
        return 1

    state_dir = Path(args.state_dir) if args.state_dir else None

    with httpx.Client(
        base_url=args.core_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=args.timeout,
    ) as client:
        outcome = run_sync(
            client,
            mission_id=args.mission_id,
            source_dir=source_dir,
            batch_size=args.batch_size,
            timeout=args.timeout,
            state_dir=state_dir,
            seal=args.seal,
            start_reconstruction=args.start_reconstruction,
            ground_control=Path(args.ground_control) if args.ground_control else None,
            ground_control_crs=args.ground_control_crs,
        )

    if outcome.already_complete:
        print(f"{outcome.discovered}장 발견 · 이미 봉인된 번들과 장수가 같아 새로 올릴 것이 없다")
    else:
        print(
            f"{outcome.discovered}장 발견 · 업로드 {outcome.uploaded} · "
            f"이미 올림 {outcome.skipped_already_uploaded}"
        )
    if outcome.failures:
        print(f"{len(outcome.failures)}건 실패:", file=sys.stderr)
        for message in outcome.failures[:20]:
            print(f"  - {message}", file=sys.stderr)
        if len(outcome.failures) > 20:
            print(f"  ... 외 {len(outcome.failures) - 20}건", file=sys.stderr)

    if outcome.discovered == 0:
        return 1
    if outcome.failures:
        # 업로드 실패가 봉인을 막은 경우와, 봉인·발행 자체가 실패한 경우를 나눈다.
        return 2 if not outcome.sealed and args.seal else 3
    if not args.seal:
        print("--seal 이 지정되지 않아 봉인하지 않았다.")
        return 0

    print(f"봉인 완료 — sourceBundleDigest={outcome.source_bundle_digest}")
    if args.start_reconstruction:
        print(f"재구성 발행 완료 — jobId={outcome.processing_job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
