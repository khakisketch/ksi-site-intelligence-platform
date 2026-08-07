"""KSI Core 프로덕션 조립 지점 — 유일한 실행 가능한 운영 배선(ADR-KSI-008).

``scripts/run_core_dev.py`` 는 그 스크립트 자체가 명시하듯 프로덕션 조립이
아니다 — 고정 dev 토큰 5개를 하드코딩해 ``AuthRegistry`` 를 구성한다. 이
모듈은 dev 스크립트를 전혀 import 하지 않는다(``run_core_dev`` 에 대한 어떤
의존도 없다) — 이 파일만 읽어서는 dev 토큰의 존재조차 알 수 없어야, "운영
빌드가 실수로 dev 자격증명을 끌고 들어온다"는 사고 클래스 자체가 성립하지
않는다.

## 전부 환경변수로만 조립한다 — fail-closed

필수 환경변수가 하나라도 없거나 형식이 틀리면 :class:`RuntimeError` 로 즉시
거부한다. 무엇도 조용히 기본값·빈 값으로 대체하지 않는다 — 조용한 기본값은
"인증 없이 뜬 프로덕션 서버"라는, 이 작업이 막으려는 바로 그 사고다. 검증은
무거운 부수효과(S3 client 생성, journal 파일 열기 등)를 만들기 **전에** 전부
끝낸다 — 잘못된 배포가 부분적으로 조립되다 알 수 없는 지점에서 죽는 대신,
어느 환경변수가 왜 문제인지 첫 실패에서 명확히 말한다.

## 서명키는 여기서 부트스트랩하지 않는다

``scripts/run_core_dev.py`` 의 ``_bootstrap_key_set`` 은 dev 편의로 키가 없으면
새로 만든다. 이 모듈은 :func:`ksi_core.signing_keys.load_signing_keys` 를 직접
호출한다 — **이미 있는 키만 로드**하고 새로 만들지 않는다. 컨테이너는
재생성될 수 있는 존재다(오케스트레이터 재스케줄·롤링 배포). 재생성마다 새
서명키가 생기면, 그 이전 키로 서명된 Mission Contract 는 재검증 시 새 키
registry 에 없는 keyId 를 참조하게 되어 전부 검증 실패한다 — 이미 현장에
발급된 계약이 서버 재시작 한 번으로 무효가 되는 것은 이 제품의 근본 전제
(server loss must not invalidate a locally valid Mission Contract)를 정면으로
어긴다. 키 파일은 컨테이너 밖(영속 볼륨)에 살아야 하고, 회전은 운영 절차
(``docs/security/SIGNING_KEY_LIFECYCLE.md``)로 명시적으로 한다.

## evidence storage 는 선택이 아니라 필수다

dev 조립은 ``--s3-endpoint``/``--s3-bucket`` 없이도 뜬다(증거·3D 파이프라인
표면이 그냥 장착되지 않을 뿐) — 로컬 UI 개발에는 그걸로 충분하다. 프로덕션은
그 타협을 허용하지 않는다: evidence storage 없는 운영 배포는 증거·3D 파이프라인
전체가 조용히 404 인 서버이고, 그 상태를 "정상 기동"으로 보고하면 안 된다.
그래서 ``KSI_CORE_S3_ENDPOINT``/``KSI_CORE_S3_BUCKET`` 을 둘 다 필수로 둔다.

## 원문 토큰은 이 프로세스 어디에도 없다

``KSI_CORE_PRINCIPAL_TOKENS_JSON`` 은 토큰 원문이 아니라 sha256 **digest** 만
싣는다(``AuthRegistry`` 자체가 이미 그 규약이다, ``auth.py`` 모듈 docstring
참조). 배포자가 토큰을 만들고 digest 를 미리 계산해 이 JSON 에 실으므로,
프로세스 메모리·로그·환경변수 어디에도 원문 토큰이 존재하지 않는다 — dev
스크립트처럼 콘솔에 토큰을 찍어 보여주는 경로도 여기 없다(그 경로 자체가
원문을 프로세스가 알고 있어야만 가능하다).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ksi_core.app_assembly import assemble_app, cli_optional_positive
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.signing_keys import load_signing_keys

if TYPE_CHECKING:
    from fastapi import FastAPI

_JOURNAL_SEGMENT_BYTES_DEFAULT = 64 * 1024 * 1024
_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT = 500

_KIND_VALUES = {kind.value: kind for kind in PrincipalKind}
_ROLE_VALUES = {role.value: role for role in Role}
# auth.py 의 AuthRegistry 가 강제하는 것과 동일한 규약(소문자 64자리 hex) —
# 형식이 틀린 digest 를 여기서 먼저 거부해야 "무거운 부수효과 이전에 검증을
# 전부 끝낸다"(모듈 docstring)는 약속이 이 필드에 대해서도 실제로 성립한다.
_TOKEN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} 환경변수가 필요하다 — 프로덕션 조립은 기본값으로 넘어가지 않는다"
        )
    return value


def _require_dir(name: str) -> Path:
    raw = _require_env(name)
    path = Path(raw)
    if not path.is_dir():
        raise RuntimeError(f"{name}={raw!r} 는 존재하는 디렉터리가 아니다")
    return path


def _optional_positive_env(name: str, *, default: int) -> int | None:
    if (raw := os.environ.get(name)) is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name}={raw!r} 는 정수여야 한다") from exc
    try:
        return cli_optional_positive(value, name=name)
    except ValueError as exc:
        # cli_optional_positive 는 라이브러리 계약(dev CLI 도 공유)이라 ValueError 를
        # 던진다 — 이 함수는 환경변수 검증 경계이므로 모듈 docstring 이 약속하는
        # "형식이 틀리면 RuntimeError" 를 이 실패에 대해서도 지킨다(음수 입력 등).
        raise RuntimeError(str(exc)) from exc


def _expose_docs_env() -> bool:
    """``KSI_CORE_EXPOSE_DOCS`` — 기본 ``False``(dev 는 기본 True 와 대칭적으로 반대).

    운영 배포는 명시적으로 켜지 않는 한 계약 문서 표면(``/docs`` 등)을 닫는다.
    """
    raw = os.environ.get("KSI_CORE_EXPOSE_DOCS", "false").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise RuntimeError(f"KSI_CORE_EXPOSE_DOCS={raw!r} 는 'true' 또는 'false' 여야 한다")


def _parse_principal_tokens(raw: str) -> list[PrincipalTokenRecord]:
    """``KSI_CORE_PRINCIPAL_TOKENS_JSON`` 을 파싱한다 — 원문 토큰은 여기 없다(digest 만).

    형식이 조금이라도 어긋나면 :class:`RuntimeError` — ``AuthRegistry`` 생성자
    자체도 불변식을 검증하지만(``AuthRegistryError``), 이 함수는 그보다 앞서
    "환경변수 자체가 잘못된 형식이다"를 배포자에게 명확히 알린다.
    """
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"KSI_CORE_PRINCIPAL_TOKENS_JSON 이 유효한 JSON 이 아니다 — {exc}"
        ) from exc
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("KSI_CORE_PRINCIPAL_TOKENS_JSON 은 비어 있지 않은 배열이어야 한다")

    records: list[PrincipalTokenRecord] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}] 는 object 여야 한다")

        token_sha256 = entry.get("tokenSha256")
        principal_id = entry.get("principalId")
        kind_raw = entry.get("kind")
        role_raw = entry.get("role")
        device_id = entry.get("deviceId")

        if not isinstance(token_sha256, str) or not token_sha256:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].tokenSha256 이 없거나 비어 있다"
            )
        if not _TOKEN_SHA256_RE.fullmatch(token_sha256):
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].tokenSha256 은 소문자 64자리 hex "
                f"여야 한다 (got {token_sha256!r}) — 원문 토큰·대문자는 거부된다"
            )
        if not isinstance(principal_id, str) or not principal_id:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].principalId 가 없거나 비어 있다"
            )
        if kind_raw not in _KIND_VALUES:
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].kind={kind_raw!r} 는 "
                f"{sorted(_KIND_VALUES)} 중 하나여야 한다"
            )
        kind = _KIND_VALUES[kind_raw]

        role: Role | None = None
        if role_raw is not None:
            if role_raw not in _ROLE_VALUES:
                raise RuntimeError(
                    f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].role={role_raw!r} 는 "
                    f"null 이거나 {sorted(_ROLE_VALUES)} 중 하나여야 한다"
                )
            role = _ROLE_VALUES[role_raw]

        if device_id is not None and not isinstance(device_id, str):
            raise RuntimeError(
                f"KSI_CORE_PRINCIPAL_TOKENS_JSON[{index}].deviceId 는 문자열이거나 null 이어야 한다"
            )

        records.append(
            PrincipalTokenRecord(
                token_sha256=token_sha256,
                principal=Principal(
                    principal_id=principal_id,
                    kind=kind,
                    role=role,
                    device_id=device_id,
                ),
            )
        )
    return records


def build_production_app() -> FastAPI:
    """환경변수만으로 프로덕션 Core 앱을 조립한다 — 실패는 전부 fail-closed.

    uvicorn 팩토리 진입점(``--factory``)으로 쓰인다:
    ``uvicorn ksi_core.production:build_production_app --factory``.
    """
    # ── 1단계: 검증(가벼운 것부터) — 무거운 부수효과(S3 client·journal open) 이전에
    # 전부 끝낸다. 잘못된 배포는 어느 환경변수가 문제인지 즉시 알아야 한다.
    data_dir = _require_dir("KSI_CORE_DATA_DIR")
    signing_keys_dir = _require_dir("KSI_CORE_SIGNING_KEYS_DIR")
    s3_endpoint = _require_env("KSI_CORE_S3_ENDPOINT")
    s3_bucket = _require_env("KSI_CORE_S3_BUCKET")
    principal_tokens_raw = _require_env("KSI_CORE_PRINCIPAL_TOKENS_JSON")

    journal_segment_bytes = _optional_positive_env(
        "KSI_CORE_JOURNAL_SEGMENT_BYTES", default=_JOURNAL_SEGMENT_BYTES_DEFAULT
    )
    edge_sync_snapshot_every = _optional_positive_env(
        "KSI_CORE_EDGE_SYNC_SNAPSHOT_EVERY", default=_EDGE_SYNC_SNAPSHOT_EVERY_DEFAULT
    )
    expose_docs = _expose_docs_env()

    principal_records = _parse_principal_tokens(principal_tokens_raw)

    # ── 2단계: 무거운 조립 — 여기부터는 검증을 통과한 입력만 다룬다.

    # 서명키는 **로드만** 한다(부트스트랩 없음) — 모듈 docstring 참조.
    key_set = load_signing_keys(signing_keys_dir)

    # AWS 자격증명은 boto3 기본 체인(환경변수/IAM role)에 맡긴다 — 이 함수는
    # endpoint_url·bucket 만 넘긴다(evidence_s3.py 어댑터가 이미 이 관습이다).
    from ksi_core.evidence_s3 import S3EvidenceStorage  # noqa: PLC0415 -- 지연 import(boto3)

    evidence_storage = S3EvidenceStorage(bucket=s3_bucket, endpoint_url=s3_endpoint)

    auth_registry = AuthRegistry(principal_records)

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name, max_segment_bytes=journal_segment_bytes)
        opened.append(journal)
        return journal

    try:
        return assemble_app(
            data_dir,
            journal=_journal,
            opened=opened,
            edge_sync_snapshot_every=edge_sync_snapshot_every,
            auth_registry=auth_registry,
            evidence_storage=evidence_storage,
            mission_signing_key=key_set.active_private_key,
            mission_signing_key_id=key_set.active_key_id,
            expose_docs=expose_docs,
        )
    except BaseException:
        # dev 조립(build_dev_app)과 같은 이유 — 안 닫으면 재시도가 flock 에 막혀
        # 진짜 실패 원인이 "다른 프로세스가 journal 을 소유 중"으로 덮인다.
        for journal in opened:
            journal.close()
        raise


__all__ = ["build_production_app"]
