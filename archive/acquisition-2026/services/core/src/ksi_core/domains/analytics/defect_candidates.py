"""DefectCandidate 수신·조회 — Phase 4 "표면 점검·결함 후보"의 운영자 도달 지점.

## 이 모듈이 채우는 자리

``packages/defect-detection`` 은 확률맵 → :class:`DefectCandidate` 변환까지 정확하게
만들어놨지만 **그 결과를 아무도 볼 수 없었다** — 저장소도 엔드포인트도 없어서
프로덕션 호출부가 0건이었다. 계약과 골든벡터가 아무리 정확해도, 부를 수 있는 표면이
없으면 제품 기능이 아니라 라이브러리다. 이 모듈이 그 표면이다.

``coverage_reports.py`` 와 같은 3단 구성(Store on ``DurableJournal`` → ``build_*_router``
→ ``mount_*``)을 따른다. 새 구조를 만들지 않는다.

## 서버는 후보를 그대로 받아 적지 않는다

결함 후보는 "이 사진의 이 픽셀 영역이 균열이다"라는 주장이다. 그 주장이 참조하는
사진과 좌표계가 실재하는지는 서버가 검사할 수 있고, 검사하지 않으면 원장에
**그릴 수 없는 도형**이 쌓인다:

1. 미등록 ``sourceMediaId`` → ``UNKNOWN_SOURCE_MEDIA``. 어느 사진 위의 좌표인지
   모르는 폴리곤은 화면에 띄울 수도, 나중에 대조할 수도 없다.
2. 등록된 사진의 실제 화소수와 ``imageSize`` 불일치 → ``IMAGE_SIZE_MISMATCH``.
   축소본에서 뽑은 좌표를 원본 기준으로 신고하면 폴리곤이 통째로 엉뚱한 자리를
   가리킨다 — 값은 전부 유효 범위라 스키마 검증으로는 절대 안 잡힌다.
3. 폴리곤 정점이 이미지 밖 → ``GEOMETRY_OUT_OF_BOUNDS``. 4000px 사진의 x=5000 은
   어떤 해석으로도 그 사진 위의 점이 아니다.

``events.py`` 가 확정 이벤트를 Edge 가 주장하지 못하게 한 것과 같은 원칙이다 —
**서버가 검증할 수 있는 것을 검증하지 않고 수용하지 않는다.**

## 봉인(seal)을 요구하지 않는 이유

``processing_jobs.py`` 는 입력 번들이 봉인돼야 작업을 만든다 — 거기서 봉인은
``sourceBundleDigest`` (번들 **전체**의 지문)가 재현성 앵커이기 때문이다. 결함
후보의 앵커는 번들이 아니라 **개별 사진**이고, ``SourceMediaRecord`` 는 등록 시점에
이미 ``sha256`` 이 고정된다 — 나중에 다른 사진이 추가돼도 이 후보가 가리키는 바이트는
변하지 않는다. 게다가 후보 자신이 ``model.sourceDigests`` 로 "어느 가중치가 냈는가"를
따로 나른다. 여기에 봉인 게이트를 더 얹으면 실제로 막는 것 없이 게이트만 늘어난다.

## 배치는 전부-또는-전무다

한 사진(또는 한 임무)의 추론 결과는 후보 여러 건이 한 번에 나온다. 그중 일부만
기록되면 "이 임무의 결함이 몇 건인가"에 원장이 답할 수 없다 — 부분 기록은 조용한
누락이라 조회 시점에는 정상으로 보인다. 하나라도 판정에 걸리면 배치 전체를 거부한다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.defect_candidate import (
    DefectCandidate,
    defect_candidate_wire_dict,
)
from pydantic import Field

from ksi_core.domains.missions.mission_records import reject_lone_surrogates
from ksi_core.foundation.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.domains.artifacts.source_media import SourceMediaStore
    from ksi_core.domains.missions.mission_records import MissionStore

logger = logging.getLogger("ksi_core.defect_candidates")


class DefectCandidateVerdict(StrEnum):
    """배치 수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    EMPTY_BATCH = "EMPTY_BATCH"
    UNKNOWN_SOURCE_MEDIA = "UNKNOWN_SOURCE_MEDIA"
    IMAGE_SIZE_MISMATCH = "IMAGE_SIZE_MISMATCH"
    GEOMETRY_OUT_OF_BOUNDS = "GEOMETRY_OUT_OF_BOUNDS"
    DUPLICATE_CANDIDATE_ID = "DUPLICATE_CANDIDATE_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[DefectCandidateVerdict, int] = {
    DefectCandidateVerdict.RECORDED: 201,
    DefectCandidateVerdict.UNKNOWN_MISSION: 404,
    DefectCandidateVerdict.EMPTY_BATCH: 422,
    DefectCandidateVerdict.UNKNOWN_SOURCE_MEDIA: 422,
    DefectCandidateVerdict.IMAGE_SIZE_MISMATCH: 422,
    DefectCandidateVerdict.GEOMETRY_OUT_OF_BOUNDS: 422,
    DefectCandidateVerdict.DUPLICATE_CANDIDATE_ID: 409,
    DefectCandidateVerdict.STORE_UNAVAILABLE: 503,
}


class DefectCandidateRecoveryError(RuntimeError):
    """defect journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class DefectCandidateResult:
    verdict: DefectCandidateVerdict
    detail: str | None = None
    recorded_count: int = 0


@dataclass(frozen=True, slots=True)
class RecordedDefectCandidate:
    """후보 1건 + 누가·언제 제출했는가(``coverage_reports.RecordedCoverageReport`` 대칭)."""

    candidate: DefectCandidate
    reported_by: str | None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class MediaFrame:
    """후보가 참조하는 사진의 실제 화소수 — 좌표계 대조의 기준."""

    width: int
    height: int


def judge_candidate(
    candidate: DefectCandidate, *, frame: MediaFrame | None
) -> tuple[DefectCandidateVerdict, str | None]:
    """후보 1건이 참조하는 사진·좌표계와 정합하는지 판정한다.

    ``frame`` 이 ``None`` 이면 그 ``sourceMediaId`` 가 이 임무에 등록된 적이 없다는
    뜻이다. live 수신과 journal 재생이 **같은 함수**를 쓴다 — 각자 조건문을 들고
    있으면 한쪽만 고쳐지는 순간 원장이 거짓 검증을 되살린다(``source_media.py`` 의
    ``compare_measurements`` 와 같은 원칙).
    """
    if frame is None:
        return (
            DefectCandidateVerdict.UNKNOWN_SOURCE_MEDIA,
            f"sourceMediaId={candidate.source_media_id!r} 가 이 임무에 등록된 적이 없다"
            " — 어느 사진 위의 좌표인지 모르는 폴리곤은 받지 않는다",
        )
    declared = candidate.image_size
    if (declared.width_px, declared.height_px) != (frame.width, frame.height):
        return (
            DefectCandidateVerdict.IMAGE_SIZE_MISMATCH,
            f"imageSize {declared.width_px}x{declared.height_px} 가 등록된 사진의 실제 "
            f"화소수 {frame.width}x{frame.height} 와 다르다 — 축소본 좌표를 원본 기준으로"
            " 신고하면 폴리곤이 통째로 다른 자리를 가리킨다",
        )
    polygon = candidate.geometry.payload
    if polygon is not None:
        for x, y in polygon:
            if not (0.0 <= x <= frame.width - 1) or not (0.0 <= y <= frame.height - 1):
                return (
                    DefectCandidateVerdict.GEOMETRY_OUT_OF_BOUNDS,
                    f"폴리곤 정점 ({x}, {y}) 이 이미지 {frame.width}x{frame.height} 밖이다"
                    " — 픽셀 좌표는 [0, width-1] x [0, height-1] 안에 있어야 한다",
                )
    return DefectCandidateVerdict.RECORDED, None


class DefectCandidateStore:
    """``DurableJournal`` 위의 결함 후보 원장 — append-only, 덮어쓰지 않는다.

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 판정+append+projection 을
    한 임계구역으로 묶는다(다른 저장소 관습 대칭).
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        source_media_store: SourceMediaStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._source_media_store = source_media_store
        self._lock = threading.Lock()
        # mission_id → 그 임무의 후보들(수신 순서 보존)
        self._by_mission: dict[str, list[RecordedDefectCandidate]] = {}
        # mission_id → 이미 쓰인 defectCandidateId (배치 간 중복 검출)
        self._ids_by_mission: dict[str, dict[str, DefectCandidate]] = {}
        try:
            self._replay(journal)
        except DefectCandidateRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise DefectCandidateRecoveryError(
                f"defect candidate journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def mission_is_visible(self, mission_id: str) -> bool:
        return self._mission_store.get(mission_id) is not None

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "defect-candidates-rejected":
                # 거부 감사기록 — 수용 상태에 반영하지 않는다(coverage_reports 대칭).
                continue
            if kind not in (None, "defect-candidates-recorded"):
                raise DefectCandidateRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            mission_id = raw["missionId"]
            recorded_at = datetime.fromisoformat(raw["ts"])
            reported_by = raw.get("reportedBy")
            for wire in raw["candidates"]:
                candidate = DefectCandidate.model_validate(wire)
                # 재생도 live 와 같은 게이트를 태운다 — journal 조작으로 사진에
                # 걸리지 않는 후보가 되살아나는 경로를 막는다(events.py 재생 게이트 대칭).
                frame = self._frame_for(mission_id, candidate.source_media_id)
                verdict, detail = judge_candidate(candidate, frame=frame)
                if verdict is not DefectCandidateVerdict.RECORDED:
                    raise DefectCandidateRecoveryError(
                        f"재생: 기록될 수 없는 후보({verdict.value}: {detail}) — "
                        f"missionId={mission_id} defectCandidateId={candidate.defect_candidate_id}"
                    )
                self._append_projection(mission_id, candidate, reported_by, recorded_at)

    def _append_projection(
        self,
        mission_id: str,
        candidate: DefectCandidate,
        reported_by: str | None,
        recorded_at: datetime,
    ) -> None:
        self._by_mission.setdefault(mission_id, []).append(
            RecordedDefectCandidate(
                candidate=candidate, reported_by=reported_by, recorded_at=recorded_at
            )
        )
        self._ids_by_mission.setdefault(mission_id, {})[candidate.defect_candidate_id] = candidate

    def _frame_for(self, mission_id: str, media_id: str) -> MediaFrame | None:
        """그 임무에 등록된 사진의 실제 화소수 — 미등록이면 ``None``."""
        bundle = self._source_media_store.get(mission_id)
        if bundle is None:
            return None
        for record in bundle.media:
            if record.media_id == media_id:
                return MediaFrame(width=record.width, height=record.height)
        return None

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record_batch(
        self,
        mission_id: str,
        candidates: list[DefectCandidate],
        *,
        now: datetime,
        reported_by: str | None = None,
    ) -> DefectCandidateResult:
        """후보 배치를 판정·durable 기록한다 — 전부 또는 전무(모듈 docstring)."""
        with self._lock:
            if self._journal.sealed_reason is not None:
                return DefectCandidateResult(
                    DefectCandidateVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            if not candidates:
                return self._reject(
                    mission_id,
                    candidates,
                    now,
                    reported_by,
                    DefectCandidateVerdict.EMPTY_BATCH,
                    "후보가 하나도 없는 배치는 받지 않는다 — '결함 0건'은 제출이 아니라"
                    " 조회 결과가 비어 있는 것으로 표현된다",
                )
            if self._mission_store.get(mission_id) is None:
                return self._reject(
                    mission_id,
                    candidates,
                    now,
                    reported_by,
                    DefectCandidateVerdict.UNKNOWN_MISSION,
                    "발급된 적 없는 임무의 결함 후보는 받지 않는다",
                )

            known_ids = self._ids_by_mission.get(mission_id, {})
            seen_in_batch: set[str] = set()
            for candidate in candidates:
                candidate_id = candidate.defect_candidate_id
                if candidate_id in seen_in_batch:
                    return self._reject(
                        mission_id,
                        candidates,
                        now,
                        reported_by,
                        DefectCandidateVerdict.DUPLICATE_CANDIDATE_ID,
                        f"같은 배치 안에 defectCandidateId={candidate_id!r} 가 두 번 있다",
                    )
                seen_in_batch.add(candidate_id)
                existing = known_ids.get(candidate_id)
                if existing is not None and existing != candidate:
                    # 같은 id 로 **다른 내용**을 다시 보내는 것은 재전송이 아니라 충돌이다
                    # (source_media.py 의 멱등 재등록 판정과 같은 구분).
                    return self._reject(
                        mission_id,
                        candidates,
                        now,
                        reported_by,
                        DefectCandidateVerdict.DUPLICATE_CANDIDATE_ID,
                        f"defectCandidateId={candidate_id!r} 는 이미 다른 내용으로 기록됐다"
                        " — 같은 id 로 다른 후보를 덮어쓸 수 없다",
                    )
                verdict, detail = judge_candidate(
                    candidate, frame=self._frame_for(mission_id, candidate.source_media_id)
                )
                if verdict is not DefectCandidateVerdict.RECORDED:
                    return self._reject(
                        mission_id, candidates, now, reported_by, verdict, detail
                    )

            fresh = [c for c in candidates if c.defect_candidate_id not in known_ids]
            if not fresh:
                # 전건이 동일 내용 재전송 — 멱등 성공(중복 기록하지 않는다).
                return DefectCandidateResult(
                    DefectCandidateVerdict.RECORDED,
                    detail="전건이 이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                    recorded_count=0,
                )

            record = {
                "kind": "defect-candidates-recorded",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "reportedBy": reported_by,
                "candidates": [defect_candidate_wire_dict(c) for c in fresh],
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return DefectCandidateResult(
                    DefectCandidateVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            for candidate in fresh:
                self._append_projection(mission_id, candidate, reported_by, now)
            return DefectCandidateResult(
                DefectCandidateVerdict.RECORDED, recorded_count=len(fresh)
            )

    def _reject(
        self,
        mission_id: str,
        candidates: list[DefectCandidate],
        now: datetime,
        reported_by: str | None,
        verdict: DefectCandidateVerdict,
        detail: str | None,
    ) -> DefectCandidateResult:
        """거부 판정도 감사기록에 남긴다 — 왜 결과가 안 보이는지 조회로 답할 수 있게.

        ``self._lock`` 을 쥔 :meth:`record_batch` 안에서만 호출된다. 수용 상태에는
        반영하지 않는다.
        """
        record = {
            "kind": "defect-candidates-rejected",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
            "candidateIds": [c.defect_candidate_id for c in candidates],
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return DefectCandidateResult(
                DefectCandidateVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        return DefectCandidateResult(verdict, detail=detail)

    def list_for_mission(self, mission_id: str) -> list[RecordedDefectCandidate]:
        """수신 순서를 보존한 그 임무의 전체 후보."""
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return list(self._by_mission.get(mission_id, ()))


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class DefectCandidateBatchRequest(CamelModel):
    """추론 워커가 한 번에 올리는 후보 묶음."""

    candidates: list[DefectCandidate] = Field(min_length=1)


class DefectCandidateBatchResponse(CamelModel):
    """세 필드 모두 **필수**다 — 기본값을 두지 않는다.

    ``verdict`` 만 읽는 클라이언트는 멱등 재전송(아무것도 새로 안 들어감)과 실제
    기록을 구분할 수 없다. ``recordedCount`` 가 그 구분의 유일한 신호라 응답에서
    빠질 수 있는 값이 아니고, 선택 필드로 두면 계약 문서상 "없을 수도 있는 값"이
    돼 소비자가 방어 코드를 짜게 된다.
    """

    verdict: str
    detail: str | None
    recorded_count: int


class DefectCandidateItem(CamelModel):
    """조회 응답의 후보 1건 — 계약 payload + 수신 메타."""

    candidate: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime


class DefectCandidateListView(CamelModel):
    """그 임무의 결함 후보 목록.

    ``sourceMediaIds`` 는 후보가 걸린 사진 목록이다 — 화면이 "어느 사진에 결함이
    있나"를 먼저 보여주고 사진별로 폴리곤을 겹치는 흐름을 위해, 클라이언트가
    전체 목록을 훑어 직접 집계하지 않아도 되게 서버가 함께 낸다.
    """

    mission_id: str
    candidate_count: int
    source_media_ids: list[str]
    candidates: list[DefectCandidateItem]


def build_defect_candidates_router(store: DefectCandidateStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["defect-candidates"])

    @router.post("/{mission_id}/defect-candidates", status_code=201)
    def submit_defect_candidates(
        mission_id: str,
        body: DefectCandidateBatchRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> DefectCandidateBatchResponse:
        """결함 후보 배치 접수 — **추론 워커만** 올린다.

        운영자 Role 에는 ``PROCESSING_WORK`` 가 매핑되지 않는다(``auth.py``) —
        사람이 손으로 "여기 균열이 있다"를 원장에 주장할 수 없다. 사람의 판단은
        결함 후보가 아니라 이벤트 트리아지로 표현된다.
        """
        # **원장 기록 전에** 거부한다. ``sourceDigests`` 같은 자유 문자열 자리에
        # lone surrogate 가 실리면 기록은 201 로 성공하는데, 그 임무의 조회가
        # 응답 직렬화에서 UnicodeEncodeError 로 **영원히** 500 이 된다 — 재기동
        # 후 재적재해도 그대로다(재조사 F2 실측). 나중에 올린 깨끗한 후보까지
        # 같은 500 에 파묻힌다.
        reject_lone_surrogates(body.model_dump(by_alias=True, mode="json", exclude_none=True))
        result = store.record_batch(
            mission_id,
            body.candidates,
            now=datetime.now(UTC),
            reported_by=principal.principal_id,
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is DefectCandidateVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return DefectCandidateBatchResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            recorded_count=result.recorded_count,
        )

    @router.get("/{mission_id}/defect-candidates", response_model=DefectCandidateListView)
    def list_defect_candidates(
        mission_id: str,
        source_media_id: str | None = Query(default=None, alias="sourceMediaId"),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> DefectCandidateListView:
        """그 임무의 결함 후보. ``sourceMediaId`` 로 사진 1장만 걸러 볼 수 있다.

        후보가 0건인 것은 404 가 아니라 빈 목록이다 — "아직 안 돌았다"와 "돌렸는데
        결함이 없다"를 이 엔드포인트는 구분하지 못하고, 구분하는 척하면 안 된다
        (그 구분은 처리 작업 상태가 답한다).
        """
        if not store.mission_is_visible(mission_id):
            raise HTTPException(status_code=404, detail="해당 임무의 결함 후보를 찾을 수 없다")
        recorded = store.list_for_mission(mission_id)
        if source_media_id is not None:
            recorded = [r for r in recorded if r.candidate.source_media_id == source_media_id]
        media_ids = sorted({r.candidate.source_media_id for r in recorded})
        return DefectCandidateListView(
            mission_id=mission_id,
            candidate_count=len(recorded),
            source_media_ids=media_ids,
            candidates=[
                DefectCandidateItem(
                    candidate=defect_candidate_wire_dict(r.candidate),
                    reported_by=r.reported_by,
                    recorded_at=r.recorded_at,
                )
                for r in recorded
            ],
        )

    return router


def mount_defect_candidates(app: FastAPI, store: DefectCandidateStore) -> None:
    app.include_router(build_defect_candidates_router(store))


__all__ = [
    "DefectCandidateListView",
    "DefectCandidateRecoveryError",
    "DefectCandidateResult",
    "DefectCandidateStore",
    "DefectCandidateVerdict",
    "MediaFrame",
    "build_defect_candidates_router",
    "judge_candidate",
    "mount_defect_candidates",
]
