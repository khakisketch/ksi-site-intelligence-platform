"""원본 사진 번들 입구 (3D 파이프라인의 첫 관문).

기존 evidence 업로드(``events.py``)는 이미 존재하는 Event 에 종속된다(객체 키가
``sites/{siteId}/events/{deviceId}/{eventId}/{artifactId}``) — 매핑 원본 수천
장에는 매달 사건이 없다. 이 모듈은 **Mission** 에 종속된 별도 입구를 연다.

## sourceBundleDigest 는 Core 가 계산한다 — 요청이 자기 증명서를 쓰지 못한다

``contracts/schemas/processing-job.v1.json`` 의 ``input.sourceBundleDigest`` 가
이 모듈이 만들어야 할 값이다. 클라이언트가 준 값을 그대로 싣지 않는다 — Core 가
정규 정렬된 매니페스트에서 직접 계산한다(:func:`compute_source_bundle_digest`).
정규화는 이 저장소의 유일한 문서화 정규화인
``ksi_mission_contracts.signing.canonical_payload_bytes`` 관습을 그대로
재사용한다(ADR-KSI-002 §2/§3, ``mission_plans.py`` 의 ``_pair_digest`` 와 동일
구성 — ``sha256_digest(canonical_payload_bytes(payload))``). 그 함수는 dict 의
**키**만 정렬하므로(``sort_keys=True``), 파일 리스트 순서 자체는 여기서
``mediaId`` 기준으로 먼저 정렬해 고정한다 — 그래야 같은 파일 집합을 다른 순서로
올려도 같은 digest 가 나온다.

## 업로더의 신고값은 주장이다 — 이 단계는 검증하지 않는다

파일마다 ``sha256``·``bytes``·``width``·``height`` 를 신고받지만, 이 값들을
서버가 재계산해 대조하지 않는다 — 전 바이트를 읽는 워커가 B3 에서 한다. 그래서
번들 조회 응답은 ``verifiedAt: null`` 을 그대로 노출한다(검증된 척하는 필드명을
쓰지 않는다). ``mediaId`` 는 호출자가 정한다(``evidence.py`` 의 ``artifactId``
관습과 동일) — 같은 mediaId·같은 claim 재전송은 멱등 재발급(새 presigned
URL)이고, 같은 mediaId·다른 claim 은 ``CLAIM_CONFLICT`` 로 거부한다.

## 객체 키는 서버가 만든다

``sites/{siteId}/missions/{missionId}/source/{mediaId}`` — 세 구성요소 전부
:func:`~ksi_core.identifiers.is_path_safe_identifier` 로 검증한다(evidence.py
``build_object_key`` 관습 대칭).

## 봉인 후에는 거부한다

:meth:`SourceMediaStore.seal` 이후 추가 등록은 ``BUNDLE_SEALED`` 로 거부된다.
재생(``_replay``)도 live 와 같은 게이트를 다시 태운다 — journal 을 손으로 고쳐
봉인 상태·digest 를 위조할 수 없다(``coverage_reports._replay`` 와 동일 원칙).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_UPLOAD_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 임무의 원본 미디어 번들을 찾을 수 없다"
# 한 요청당 상한 — 수백~수천 장이 몇 번의 요청으로 끝나되, 한 요청이 무한정
# 커져 journal 잠금을 오래 쥐는 것을 막는다.
MAX_BATCH_SIZE = 200


class SourceMediaBatchVerdict(StrEnum):
    """배치 요청 **전체** 수준 판정. ``PROCESSED`` 면 개별 결과는 항목별로 갈린다."""

    PROCESSED = "PROCESSED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    BUNDLE_SEALED = "BUNDLE_SEALED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class SourceMediaItemVerdict(StrEnum):
    """배치 안 파일 1건의 판정.

    ``STORAGE_UNAVAILABLE`` 은 store 가 아니라 **라우터**가 매긴다 — store 는
    스토리지를 모른다(원장 기록과 URL 발급을 분리하는 evidence.py 원칙과 동일).
    """

    REGISTERED = "REGISTERED"
    INVALID_MEDIA_ID = "INVALID_MEDIA_ID"
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
    # 같은 mediaId 가 **다른** claim 으로 이미 등록돼 있다 — 같은 claim 재전송은
    # 이 값이 아니라 REGISTERED(멱등 재발급)다.
    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    JOURNAL_UNAVAILABLE = "JOURNAL_UNAVAILABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class SourceBundleSealVerdict(StrEnum):
    SEALED = "SEALED"
    ALREADY_SEALED = "ALREADY_SEALED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    EMPTY_BUNDLE = "EMPTY_BUNDLE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_BATCH_STATUS: dict[SourceMediaBatchVerdict, int] = {
    SourceMediaBatchVerdict.PROCESSED: 201,
    SourceMediaBatchVerdict.UNKNOWN_MISSION: 404,
    SourceMediaBatchVerdict.BUNDLE_SEALED: 409,
    SourceMediaBatchVerdict.STORE_UNAVAILABLE: 503,
}

_SEAL_STATUS: dict[SourceBundleSealVerdict, int] = {
    SourceBundleSealVerdict.SEALED: 201,
    SourceBundleSealVerdict.ALREADY_SEALED: 200,
    SourceBundleSealVerdict.UNKNOWN_MISSION: 404,
    SourceBundleSealVerdict.EMPTY_BUNDLE: 422,
    SourceBundleSealVerdict.STORE_UNAVAILABLE: 503,
}


class SourceMediaRecoveryError(RuntimeError):
    """source-media journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


def build_source_media_object_key(*, site_id: str, mission_id: str, media_id: str) -> str:
    """객체 키를 **서버가** 만든다(``evidence.build_object_key`` 관습 대칭).

    세 구성요소를 전부 재검증한다 — 호출부가 이미 검증했더라도, 이 함수가
    경로 탈출을 막는 마지막 지점이기 때문이다.
    """
    if not is_path_safe_identifier(site_id):
        raise ValueError(f"경로-안전하지 않은 siteId: {site_id!r}")
    if not is_path_safe_identifier(mission_id):
        raise ValueError(f"경로-안전하지 않은 missionId: {mission_id!r}")
    if not is_path_safe_identifier(media_id):
        raise ValueError(f"경로-안전하지 않은 mediaId: {media_id!r}")
    return f"sites/{site_id}/missions/{mission_id}/source/{media_id}"


@dataclass(frozen=True, slots=True)
class SourceMediaClaim:
    """업로더가 신고한 파일 1건의 주장 — 이 단계는 검증하지 않는다.

    전 바이트를 읽는 워커(B3)가 재계산해 대조한다.
    """

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    content_type: str


@dataclass(frozen=True, slots=True)
class SourceMediaRecord:
    """원장에 등록된 파일 1건 — claim + 서버가 만든 객체 키 + 등록 메타."""

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    content_type: str
    object_key: str
    registered_at: datetime
    registered_by: str

    @property
    def claim(self) -> SourceMediaClaim:
        """등록 메타를 뺀 claim 부분 — 재전송 대조(같은 claim인지)에 쓴다."""
        return SourceMediaClaim(
            media_id=self.media_id,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            width=self.width,
            height=self.height,
            content_type=self.content_type,
        )


@dataclass(frozen=True, slots=True)
class SourceMediaBundle:
    """한 임무의 원본 미디어 번들 상태 — 등록된 미디어 + 봉인 여부."""

    mission_id: str
    site_id: str
    media: tuple[SourceMediaRecord, ...] = ()
    sealed_at: datetime | None = None
    sealed_by: str | None = None
    source_bundle_digest: str | None = None

    @property
    def is_sealed(self) -> bool:
        return self.sealed_at is not None


def compute_source_bundle_digest(mission_id: str, media: Iterable[SourceMediaRecord]) -> str:
    """정규 정렬된 매니페스트의 SHA-256 — 업로드 순서와 무관한 재현성 앵커.

    ``mediaId`` 기준으로 먼저 정렬해 리스트 순서를 고정한 뒤(``canonical_
    payload_bytes`` 는 dict 키만 정렬하고 리스트 순서는 건드리지 않는다),
    ``ksi_mission_contracts.signing`` 의 정규화·digest 함수를 그대로 재사용한다
    (``mission_plans._pair_digest`` 와 동일 구성 — 별도 정규화를 새로 만들지
    않는다, ADR-KSI-002 §2/§3).

    객체 키는 매니페스트에 싣지 않는다 — digest 는 **내용**의 지문이지 저장소
    레이아웃의 지문이 아니다(버킷 구조가 나중에 바뀌어도 과거 digest 가
    흔들리지 않게).
    """
    manifest: dict[str, Any] = {
        "missionId": mission_id,
        "media": sorted(
            (
                {
                    "mediaId": record.media_id,
                    "sha256": record.sha256,
                    "bytes": record.size_bytes,
                    "width": record.width,
                    "height": record.height,
                    "contentType": record.content_type,
                }
                for record in media
            ),
            key=lambda entry: entry["mediaId"],
        ),
    }
    return sha256_digest(canonical_payload_bytes(manifest))


@dataclass(frozen=True, slots=True)
class SourceMediaItemResult:
    media_id: str
    verdict: SourceMediaItemVerdict
    object_key: str | None = None
    # REGISTERED 일 때만 채워진다 — 라우터가 presigned PUT 을 서명할 때 필요하다
    # (evidence.py 관습과 동일: ContentType 을 서명에 포함하지 않으면 업로더가
    # 임의 타입으로 올릴 수 있어 MIME allowlist 가 발급 시점 장식이 된다).
    content_type: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRegistrationResult:
    verdict: SourceMediaBatchVerdict
    detail: str | None = None
    items: tuple[SourceMediaItemResult, ...] = ()


@dataclass(frozen=True, slots=True)
class SealResult:
    verdict: SourceBundleSealVerdict
    detail: str | None = None
    bundle: SourceMediaBundle | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _require_aware_iso(raw: Any, field_name: str, mission_id: str) -> datetime:
    """journal 의 ISO 시각을 tz-aware datetime 으로 — naive·비문자열은 기동 거부."""
    if not isinstance(raw, str):
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — missionId={mission_id}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — missionId={mission_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise SourceMediaRecoveryError(
            f"재생: {field_name} 가 naive datetime — missionId={mission_id}"
        )
    return parsed


class SourceMediaStore:
    """``DurableJournal`` 위의 원본 미디어 번들 저장소(``coverage_reports.py`` 형태 대칭).

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 판정+append+projection 을
    한 임계구역으로 묶는다(다른 저장소 관습 대칭).
    """

    def __init__(self, journal: DurableJournal, *, mission_store: MissionStore) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._lock = threading.Lock()
        self._bundles: dict[str, SourceMediaBundle] = {}
        try:
            self._replay(journal)
        except SourceMediaRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise SourceMediaRecoveryError(
                f"source-media journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw["kind"]
            mission_id = raw["missionId"]
            if kind == "source-media-registered":
                self._replay_registration(mission_id, raw)
            elif kind == "source-media-sealed":
                self._replay_seal(mission_id, raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise SourceMediaRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_registration(self, mission_id: str, raw: dict[str, Any]) -> None:
        bundle = self._bundles.get(mission_id)
        if bundle is not None and bundle.is_sealed:
            # live 는 봉인된 번들에 등록을 절대 만들지 않는다 — 봉인 후 등록
            # 레코드가 있다는 것은 journal 조작이거나 쓰기 경로가 깨진 것이다.
            raise SourceMediaRecoveryError(
                f"재생: 봉인된 번들에 등록 레코드가 있다 — missionId={mission_id}"
            )
        media_id = raw["mediaId"]
        if not is_path_safe_identifier(media_id):
            raise SourceMediaRecoveryError(
                f"재생: mediaId 가 유효하지 않다({media_id!r}) — missionId={mission_id}"
            )
        if raw["contentType"] not in ALLOWED_CONTENT_TYPES:
            raise SourceMediaRecoveryError(
                f"재생: 허용되지 않은 contentType({raw['contentType']!r}) — missionId={mission_id}"
            )
        if bundle is not None and any(m.media_id == media_id for m in bundle.media):
            # live 는 같은 claim 재전송을 journal 에 다시 쓰지 않는다(멱등 재발급은
            # 무기록) — 그래서 재생에서 같은 mediaId 가 두 번 나오면 진짜 중복이다.
            raise SourceMediaRecoveryError(
                f"재생: mediaId 중복 등록({media_id!r}) — missionId={mission_id}"
            )
        record = SourceMediaRecord(
            media_id=media_id,
            sha256=raw["sha256"],
            size_bytes=raw["bytes"],
            width=raw["width"],
            height=raw["height"],
            content_type=raw["contentType"],
            object_key=raw["objectKey"],
            registered_at=_require_aware_iso(raw["ts"], "ts", mission_id),
            registered_by=raw["registeredBy"],
        )
        if bundle is None:
            bundle = SourceMediaBundle(mission_id=mission_id, site_id=raw["siteId"])
        self._bundles[mission_id] = SourceMediaBundle(
            mission_id=bundle.mission_id,
            site_id=bundle.site_id,
            media=(*bundle.media, record),
            sealed_at=bundle.sealed_at,
            sealed_by=bundle.sealed_by,
            source_bundle_digest=bundle.source_bundle_digest,
        )

    def _replay_seal(self, mission_id: str, raw: dict[str, Any]) -> None:
        bundle = self._bundles.get(mission_id)
        if bundle is None or not bundle.media:
            raise SourceMediaRecoveryError(
                f"재생: 미등록 미디어(0건)로 봉인된 레코드 — missionId={mission_id}"
            )
        if bundle.is_sealed:
            raise SourceMediaRecoveryError(
                f"재생: 이미 봉인된 번들의 중복 봉인 레코드 — missionId={mission_id}"
            )
        recomputed = compute_source_bundle_digest(mission_id, bundle.media)
        if recomputed != raw["sourceBundleDigest"]:
            # 재생 게이트의 핵심 — journal 을 손으로 고쳐 매니페스트와 어긋난
            # digest 를 봉인 상태로 위조할 수 없다(coverage_reports._replay 대칭).
            raise SourceMediaRecoveryError(
                f"재생: 봉인 레코드의 digest 가 매니페스트 재계산과 불일치 — "
                f"missionId={mission_id} (기록={raw['sourceBundleDigest']!r}, "
                f"재계산={recomputed!r})"
            )
        self._bundles[mission_id] = SourceMediaBundle(
            mission_id=bundle.mission_id,
            site_id=bundle.site_id,
            media=bundle.media,
            sealed_at=_require_aware_iso(raw["ts"], "ts", mission_id),
            sealed_by=raw["sealedBy"],
            source_bundle_digest=recomputed,
        )

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def register_batch(
        self,
        mission_id: str,
        claims: Sequence[SourceMediaClaim],
        *,
        registered_by: str,
        now: datetime,
    ) -> BatchRegistrationResult:
        """배치 1건을 처리한다 — 요청 수준 게이트 통과 후 항목별로 typed 판정한다.

        요청 수준(``UNKNOWN_MISSION``/``BUNDLE_SEALED``/``STORE_UNAVAILABLE``)은
        배치 전체에 적용되고 개별 결과가 없다. 통과하면(``PROCESSED``) 항목마다
        독립 판정한다 — 한 파일의 claim 충돌이 나머지 파일의 등록을 막지 않는다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.STORE_UNAVAILABLE,
                    detail="journal 봉인됨 — 재시작 필요",
                )
            mission = self._mission_store.get(mission_id)
            if mission is None:
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            bundle = self._bundles.get(mission_id) or SourceMediaBundle(
                mission_id=mission_id, site_id=mission.site_id
            )
            if bundle.is_sealed:
                return BatchRegistrationResult(
                    SourceMediaBatchVerdict.BUNDLE_SEALED,
                    detail="번들이 이미 봉인됐다 — 추가 업로드를 받지 않는다",
                )

            items: list[SourceMediaItemResult] = []
            journal_sealed_mid_batch = False
            for claim in claims:
                if journal_sealed_mid_batch:
                    items.append(
                        SourceMediaItemResult(
                            claim.media_id,
                            SourceMediaItemVerdict.JOURNAL_UNAVAILABLE,
                            detail="journal 봉인됨 — 재시작 필요",
                        )
                    )
                    continue
                bundle, result, sealed = self._register_one_locked(
                    bundle, claim, registered_by=registered_by, now=now
                )
                items.append(result)
                journal_sealed_mid_batch = sealed

            self._bundles[mission_id] = bundle
            return BatchRegistrationResult(SourceMediaBatchVerdict.PROCESSED, items=tuple(items))

    def _register_one_locked(
        self,
        bundle: SourceMediaBundle,
        claim: SourceMediaClaim,
        *,
        registered_by: str,
        now: datetime,
    ) -> tuple[SourceMediaBundle, SourceMediaItemResult, bool]:
        """``claims`` 배치 안 한 항목의 등록. 반환: (갱신된 bundle, 결과, journal 봉인 여부)."""
        if not is_path_safe_identifier(claim.media_id):
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.INVALID_MEDIA_ID
            ), False
        if claim.content_type not in ALLOWED_CONTENT_TYPES:
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.UNSUPPORTED_CONTENT_TYPE
            ), False

        existing = next((m for m in bundle.media if m.media_id == claim.media_id), None)
        if existing is not None:
            if existing.claim == claim:
                # 같은 mediaId + 같은 claim 재전송 — 멱등 재발급(새 URL 은 라우터가
                # 발급한다). journal 에 다시 쓰지 않는다 — 새로 기록할 사실이 없다
                # (mission_plans.py "멱등 재발급" 관습과 동일 원칙).
                return bundle, SourceMediaItemResult(
                    claim.media_id, SourceMediaItemVerdict.REGISTERED,
                    object_key=existing.object_key, content_type=existing.content_type,
                ), False
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.CLAIM_CONFLICT,
                detail="같은 mediaId 가 다른 내용으로 이미 등록돼 있다",
            ), False

        try:
            object_key = build_source_media_object_key(
                site_id=bundle.site_id, mission_id=bundle.mission_id, media_id=claim.media_id
            )
        except ValueError:
            return bundle, SourceMediaItemResult(
                claim.media_id, SourceMediaItemVerdict.INVALID_MEDIA_ID
            ), False

        journal_record = {
            "kind": "source-media-registered",
            "ts": _iso(now),
            "missionId": bundle.mission_id,
            "siteId": bundle.site_id,
            "mediaId": claim.media_id,
            "objectKey": object_key,
            "sha256": claim.sha256,
            "bytes": claim.size_bytes,
            "width": claim.width,
            "height": claim.height,
            "contentType": claim.content_type,
            "registeredBy": registered_by,
        }
        try:
            self._journal.append(journal_record)
        except JournalSealedError:
            return bundle, SourceMediaItemResult(
                claim.media_id,
                SourceMediaItemVerdict.JOURNAL_UNAVAILABLE,
                detail="journal 봉인됨 — 재시작 필요",
            ), True

        record = SourceMediaRecord(
            media_id=claim.media_id,
            sha256=claim.sha256,
            size_bytes=claim.size_bytes,
            width=claim.width,
            height=claim.height,
            content_type=claim.content_type,
            object_key=object_key,
            registered_at=now,
            registered_by=registered_by,
        )
        updated_bundle = SourceMediaBundle(
            mission_id=bundle.mission_id,
            site_id=bundle.site_id,
            media=(*bundle.media, record),
            sealed_at=bundle.sealed_at,
            sealed_by=bundle.sealed_by,
            source_bundle_digest=bundle.source_bundle_digest,
        )
        return updated_bundle, SourceMediaItemResult(
            claim.media_id,
            SourceMediaItemVerdict.REGISTERED,
            object_key=object_key,
            content_type=claim.content_type,
        ), False

    def seal(self, mission_id: str, *, sealed_by: str, now: datetime) -> SealResult:
        """번들을 봉인하고 :func:`compute_source_bundle_digest` 로 digest 를 굳힌다.

        이미 봉인된 번들의 재호출은 에러가 아니라 ``ALREADY_SEALED``(기존 digest
        재반환) — 재시도가 안전해야 한다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SealResult(
                    SourceBundleSealVerdict.STORE_UNAVAILABLE, detail="journal 봉인됨 — 재시작 필요"
                )
            mission = self._mission_store.get(mission_id)
            if mission is None:
                return SealResult(
                    SourceBundleSealVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            bundle = self._bundles.get(mission_id)
            if bundle is None or not bundle.media:
                return SealResult(
                    SourceBundleSealVerdict.EMPTY_BUNDLE,
                    detail="등록된 미디어가 0건이다 — 빈 번들은 봉인할 수 없다",
                )
            if bundle.is_sealed:
                return SealResult(SourceBundleSealVerdict.ALREADY_SEALED, bundle=bundle)

            digest = compute_source_bundle_digest(mission_id, bundle.media)
            journal_record = {
                "kind": "source-media-sealed",
                "ts": _iso(now),
                "missionId": mission_id,
                "sourceBundleDigest": digest,
                "mediaCount": len(bundle.media),
                "sealedBy": sealed_by,
            }
            try:
                self._journal.append(journal_record)
            except JournalSealedError:
                return SealResult(
                    SourceBundleSealVerdict.STORE_UNAVAILABLE, detail="journal 봉인됨 — 재시작 필요"
                )
            sealed_bundle = SourceMediaBundle(
                mission_id=bundle.mission_id,
                site_id=bundle.site_id,
                media=bundle.media,
                sealed_at=now,
                sealed_by=sealed_by,
                source_bundle_digest=digest,
            )
            self._bundles[mission_id] = sealed_bundle
            return SealResult(SourceBundleSealVerdict.SEALED, bundle=sealed_bundle)

    def get(self, mission_id: str) -> SourceMediaBundle | None:
        with self._lock:
            return self._bundles.get(mission_id)


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SourceMediaFileClaim(_CamelModel):
    """업로더가 신고하는 파일 1건의 주장 — 이 시점에는 검증하지 않는다.

    ``mediaId`` 는 호출자가 정한다(``evidence.py`` 의 ``artifactId`` 관습과
    동일 — 재전송 시 멱등 키로 쓰인다).
    """

    media_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    content_type: str = Field(min_length=1)


class SourceMediaBatchRequest(_CamelModel):
    files: list[SourceMediaFileClaim] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class SourceMediaItemView(_CamelModel):
    media_id: str
    verdict: str
    object_key: str | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None
    detail: str | None = None


class SourceMediaBatchResponse(_CamelModel):
    verdict: str
    detail: str | None = None
    results: list[SourceMediaItemView]


class SourceMediaBundleView(_CamelModel):
    """번들 상태·장수·digest — 미검증 상태를 그대로 노출한다."""

    mission_id: str
    status: str
    media_count: int
    source_bundle_digest: str | None
    sealed_at: datetime | None
    # 항상 null(B1 범위) — Core 는 신고값(sha256·해상도)을 검증하지 않는다.
    # 전 바이트를 읽는 B3 워커가 실제로 대조하면 이 필드가 채워진다. "검증된
    # 척"하는 필드명을 쓰지 않는다.
    verified_at: datetime | None


class SourceMediaSealResponse(_CamelModel):
    verdict: str
    detail: str | None = None
    bundle: SourceMediaBundleView | None = None


def _to_bundle_view(bundle: SourceMediaBundle) -> SourceMediaBundleView:
    return SourceMediaBundleView(
        mission_id=bundle.mission_id,
        status="SEALED" if bundle.is_sealed else "OPEN",
        media_count=len(bundle.media),
        source_bundle_digest=bundle.source_bundle_digest,
        sealed_at=bundle.sealed_at,
        verified_at=None,
    )


def build_source_media_router(store: SourceMediaStore, storage: EvidenceStorage) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["source-media"])

    def _to_item_view(item: SourceMediaItemResult, *, now: datetime) -> SourceMediaItemView:
        """store 판정을 응답으로 번역하고, REGISTERED 항목만 presigned PUT 을 시도한다.

        store 는 스토리지를 모른다(원장 기록과 URL 발급을 분리하는 evidence.py
        원칙) — presign 실패는 여기서 ``STORAGE_UNAVAILABLE`` 로 격하한다. 원장
        등록 자체는 이미 성공했으므로(durable), 같은 claim 을 재전송하면 다음
        시도에서 멱등 재발급으로 URL 을 다시 받을 수 있다.
        """
        if item.verdict is not SourceMediaItemVerdict.REGISTERED or item.object_key is None:
            return SourceMediaItemView(
                media_id=item.media_id, verdict=item.verdict.value, detail=item.detail
            )
        assert item.content_type is not None  # noqa: S101 -- REGISTERED 는 store 가 항상 채운다
        try:
            url = storage.presigned_put(
                item.object_key, content_type=item.content_type, ttl=DEFAULT_UPLOAD_TTL
            )
        except EvidenceStorageError:
            logger.warning("source-media presigned PUT 발급 실패: %s", item.object_key)
            return SourceMediaItemView(
                media_id=item.media_id,
                verdict=SourceMediaItemVerdict.STORAGE_UNAVAILABLE.value,
                object_key=item.object_key,
                detail="등록은 됐으나 URL 발급에 실패했다 — 같은 내용으로 재요청하면 재발급된다",
            )
        return SourceMediaItemView(
            media_id=item.media_id,
            verdict=item.verdict.value,
            object_key=item.object_key,
            upload_url=url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
        )

    @router.post(
        "/{mission_id}/source-media", response_model=SourceMediaBatchResponse, status_code=201
    )
    def register_source_media(
        mission_id: str,
        request: SourceMediaBatchRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> SourceMediaBatchResponse:
        now = datetime.now(UTC)
        claims = [
            SourceMediaClaim(
                media_id=f.media_id,
                sha256=f.sha256,
                size_bytes=f.bytes,
                width=f.width,
                height=f.height,
                content_type=f.content_type,
            )
            for f in request.files
        ]
        result = store.register_batch(
            mission_id, claims, registered_by=principal.principal_id, now=now
        )
        response.status_code = _BATCH_STATUS[result.verdict]
        if result.verdict is SourceMediaBatchVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return SourceMediaBatchResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            results=[_to_item_view(item, now=now) for item in result.items],
        )

    @router.post(
        "/{mission_id}/source-media/seal",
        response_model=SourceMediaSealResponse,
        status_code=201,
    )
    def seal_source_media(
        mission_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> SourceMediaSealResponse:
        result = store.seal(mission_id, sealed_by=principal.principal_id, now=datetime.now(UTC))
        response.status_code = _SEAL_STATUS[result.verdict]
        if result.verdict is SourceBundleSealVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return SourceMediaSealResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            bundle=_to_bundle_view(result.bundle) if result.bundle is not None else None,
        )

    @router.get("/{mission_id}/source-media", response_model=SourceMediaBundleView)
    def get_source_media(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> SourceMediaBundleView:
        del principal
        bundle = store.get(mission_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_bundle_view(bundle)

    return router


def mount_source_media(app: FastAPI, store: SourceMediaStore, storage: EvidenceStorage) -> None:
    """앱에 원본 미디어 번들 라우터를 장착한다."""
    app.state.source_media_store = store
    app.include_router(build_source_media_router(store, storage))


__all__ = [
    "MAX_BATCH_SIZE",
    "BatchRegistrationResult",
    "SealResult",
    "SourceBundleSealVerdict",
    "SourceMediaBatchRequest",
    "SourceMediaBatchResponse",
    "SourceMediaBatchVerdict",
    "SourceMediaBundle",
    "SourceMediaBundleView",
    "SourceMediaClaim",
    "SourceMediaItemResult",
    "SourceMediaItemVerdict",
    "SourceMediaRecord",
    "SourceMediaRecoveryError",
    "SourceMediaSealResponse",
    "SourceMediaStore",
    "build_source_media_object_key",
    "build_source_media_router",
    "compute_source_bundle_digest",
    "mount_source_media",
]
