#!/usr/bin/env python3
"""로컬 사진 디렉터리를 원본 미디어 번들로 업로드 (B1 — 3D 파이프라인 입구).

디렉터리의 사진을 ``POST /v1/missions/{mission_id}/source-media`` 로 배치
등록해 presigned PUT URL 을 받고, 그 URL 로 실제 바이트를 올린 뒤(``--seal``
지정 시) ``POST .../source-media/seal`` 로 번들을 봉인한다.

``mediaId`` 는 파일명 그대로 쓴다 — 같은 파일명으로 재시도하면 같은 신고값일
때 멱등 재발급(새 URL)이고, 다른 신고값이면 서버가 ``CLAIM_CONFLICT`` 로
거부한다(파일이 그 사이 바뀌었다는 뜻이므로 조용히 넘어가지 않는다).

Usage::

    uv run python tools/upload_source_bundle.py \\
        --core-url http://127.0.0.1:8010 \\
        --token dev-admin-token \\
        --mission-id mission-abc \\
        --source-dir /path/to/photos \\
        --seal
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

_EXTENSION_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image  # noqa: PLC0415 -- 지연 import(이 스크립트 실행 시에만 필요)

    with Image.open(path) as img:
        return img.size


def _collect_files(source_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _EXTENSION_CONTENT_TYPES
    )


def _build_claim(path: Path) -> dict[str, Any]:
    width, height = _image_size(path)
    return {
        "mediaId": path.name,
        "sha256": _sha256_of(path),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "contentType": _EXTENSION_CONTENT_TYPES[path.suffix.lower()],
    }


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _register_and_upload(
    client: httpx.Client,
    *,
    mission_id: str,
    files: list[Path],
    batch_size: int,
    timeout: float,
) -> tuple[int, list[str]]:
    """등록 + 실제 PUT 업로드까지 수행한다. 반환: (성공 업로드 수, 실패 메시지 목록)."""
    uploaded = 0
    failures: list[str] = []

    for batch_index, batch in enumerate(_chunks(files, batch_size), start=1):
        claims: list[dict[str, Any]] = []
        path_by_media_id: dict[str, Path] = {}
        for path in batch:
            try:
                claim = _build_claim(path)
            except Exception as exc:  # noqa: BLE001 -- 파일 하나의 실패로 배치 전체를 죽이지 않는다
                failures.append(f"{path.name}: claim 생성 실패 — {type(exc).__name__}: {exc}")
                continue
            claims.append(claim)
            path_by_media_id[claim["mediaId"]] = path

        if not claims:
            continue

        response = client.post(
            f"/v1/missions/{mission_id}/source-media", json={"files": claims}
        )
        print(
            f"[batch {batch_index}] POST source-media -> {response.status_code} "
            f"({len(claims)}건 신고)"
        )
        if response.status_code >= 400:
            failures.append(
                f"batch {batch_index}: 등록 요청 실패({response.status_code}) — {response.text}"
            )
            continue

        for item in response.json()["results"]:
            media_id = item["mediaId"]
            verdict = item["verdict"]
            if verdict != "REGISTERED" or not item.get("uploadUrl"):
                failures.append(f"{media_id}: {verdict} — {item.get('detail')}")
                continue
            path = path_by_media_id[media_id]
            content_type = _EXTENSION_CONTENT_TYPES[path.suffix.lower()]
            try:
                put_response = httpx.put(
                    item["uploadUrl"],
                    content=path.read_bytes(),
                    headers={"Content-Type": content_type},
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                failures.append(f"{media_id}: PUT 요청 실패 — {type(exc).__name__}: {exc}")
                continue
            if put_response.status_code not in (200, 201, 204):
                failures.append(
                    f"{media_id}: PUT 실패({put_response.status_code}) — {put_response.text[:200]}"
                )
                continue
            uploaded += 1

    return uploaded, failures


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
        "--batch-size", type=int, default=200, help="요청 1건당 파일 수(서버 상한 200)"
    )
    parser.add_argument(
        "--seal", action="store_true", help="업로드 완료 후 번들을 봉인한다(기본은 봉인하지 않음)"
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP 요청 타임아웃(초)")
    args = parser.parse_args()

    token = args.token or os.environ.get("KSI_CORE_TOKEN")
    if not token:
        parser.error("--token 또는 KSI_CORE_TOKEN 환경변수가 필요하다")

    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"{source_dir}: 디렉터리가 아니다", file=sys.stderr)
        return 1

    files = _collect_files(source_dir)
    if not files:
        print(
            f"{source_dir}: 업로드할 사진이 없다(확장자 {sorted(_EXTENSION_CONTENT_TYPES)})",
            file=sys.stderr,
        )
        return 1

    print(f"{len(files)}장 발견 — {source_dir}")

    with httpx.Client(
        base_url=args.core_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=args.timeout,
    ) as client:
        uploaded, failures = _register_and_upload(
            client,
            mission_id=args.mission_id,
            files=files,
            batch_size=args.batch_size,
            timeout=args.timeout,
        )

        print(f"업로드 완료 {uploaded}/{len(files)}")
        if failures:
            print(f"{len(failures)}건 실패:", file=sys.stderr)
            for message in failures[:20]:
                print(f"  - {message}", file=sys.stderr)
            if len(failures) > 20:
                print(f"  ... 외 {len(failures) - 20}건", file=sys.stderr)

        if not args.seal:
            print("--seal 이 지정되지 않아 봉인하지 않았다.")
            return 1 if failures else 0

        if failures:
            print("업로드 실패가 있어 봉인하지 않는다 — 재시도 후 다시 실행하라.", file=sys.stderr)
            return 2

        seal_response = client.post(f"/v1/missions/{args.mission_id}/source-media/seal")
        print(f"POST source-media/seal -> {seal_response.status_code}")
        print(json.dumps(seal_response.json(), ensure_ascii=False, indent=2))
        return 0 if seal_response.status_code in (200, 201) else 3


if __name__ == "__main__":
    raise SystemExit(main())
