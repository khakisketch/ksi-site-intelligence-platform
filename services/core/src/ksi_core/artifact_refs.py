"""산출물 참조 검증 — ``ChangeDetectionStore`` 와 ``VolumeChangeStore`` 가

공유하는 순수 함수 하나 (P2-5).

## 이 모듈이 소유하는 것

"``baseline``/``current`` 가 실제 등록된 산출물이고, 요구되는 kind 인가"라는
검사 하나. 두 store 모두 ``ArtifactRef``(``ksi_event_contracts.
change_detection_result.ArtifactRef``, 두 계약 모델이 함께 쓰는 타입)를
``ProcessingJobStore`` 에 대조하는 코드를 각자 들고 있었다 — 요구 kind
(``POINT_CLOUD`` vs ``DSM``)와 kind 불일치 상세 문구만 다르고 나머지는
동형이었다.

## 이 모듈이 소유하지 않는 것

verdict 열거형(``ChangeDetectionVerdict`` / ``VolumeChangeVerdict``), self-
comparison 검사, journal append — 이건 각 store 의 도메인 책임으로 남는다.
:class:`ArtifactRefIssue` 는 store 중립적인 "거부 사유의 종류"만 반환한다 —
``leasing.LeaseDenialReason`` 과 동일한 이유다. 여기서 verdict 를 직접
반환하면 두 store 가 이 모듈을 통해 결합되고, 한쪽 verdict 이름이 바뀔 때
다른 쪽까지 흔들린다.

kind 불일치 시의 상세 문구는 도메인마다 다르다(C2C 비교 vs 표면 적분) —
그래서 호출자가 ``kind_mismatch_detail`` 콜백으로 그 문구를 준다. "산출물이
없다" 쪽 문구는 두 store 에서 이미 동일했으므로 여기 고정한다.

## live 수신과 journal 재생이 같은 함수를 쓴다

``ChangeDetectionStore._judge_references`` / ``VolumeChangeStore.
_judge_references`` 는 각자 이 함수 하나를 호출하고, 그 두 메서드 자체가
``_replay``(재생)와 ``record``(live) 양쪽에서 불린다 — 각자 조건문을 들고
있으면 한쪽만 고쳐지는 순간 원장이 거짓 검증을 되살린다.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

if TYPE_CHECKING:
    from ksi_core.processing_jobs import ProcessingJobStore


class ArtifactRefIssue(StrEnum):
    """산출물 참조 검증이 거부할 때의 사유 종류 — store 중립적.

    각 store 의 ``_judge_references`` 가 이 값을 자기 자신의 verdict(예:
    ``ChangeDetectionVerdict.UNKNOWN_ARTIFACT`` /
    ``VolumeChangeVerdict.ARTIFACT_KIND_MISMATCH``)로 번역한다.
    """

    # jobId 자체가 없거나, 그 작업에 그 artifactId 가 등록된 적이 없다.
    UNKNOWN_ARTIFACT = "unknown_artifact"
    # 산출물은 있지만 kind 가 요구되는 것과 다르다.
    KIND_MISMATCH = "kind_mismatch"


def verify_artifact_ref(
    processing_job_store: ProcessingJobStore,
    ref: ArtifactRef,
    *,
    label: str,
    required_kind: ProcessingArtifactKind,
    kind_mismatch_detail: Callable[[str, ProcessingArtifactKind], str],
) -> tuple[ArtifactRefIssue, str] | None:
    """참조 **하나**가 실제 등록된 ``required_kind`` 산출물인가. 통과하면 ``None``.

    ``label`` 은 상세문구에 그대로 실리는 그 참조의 이름이다("baseline"·
    "current"). 쌍이 아니라 단일 참조를 보는 소비자가 생겨(설계 대비 잔량
    리포트는 비교 대상이 설계면이라 DSM 참조가 ``current`` 하나뿐이다) 원래
    :func:`verify_artifact_pair` 의 루프 본문이었던 것을 그대로 꺼낸 것이다 —
    쌍 버전은 이제 이 함수를 두 번 부른다(판정 로직 한 벌 유지).
    """
    job = processing_job_store.get(ref.job_id)
    if job is None:
        return (
            ArtifactRefIssue.UNKNOWN_ARTIFACT,
            f"{label}.jobId={ref.job_id!r} 인 처리 작업이 없다",
        )
    resolved = processing_job_store.resolve_artifact(ref.job_id, ref.artifact_id)
    if resolved is None:
        return (
            ArtifactRefIssue.UNKNOWN_ARTIFACT,
            f"{label}.artifactId={ref.artifact_id!r} 가 작업 {ref.job_id!r} 에"
            " 등록된 적이 없다",
        )
    if resolved.artifact.kind is not required_kind:
        return (
            ArtifactRefIssue.KIND_MISMATCH,
            kind_mismatch_detail(label, resolved.artifact.kind),
        )
    return None


def verify_artifact_pair(
    processing_job_store: ProcessingJobStore,
    baseline: ArtifactRef,
    current: ArtifactRef,
    *,
    required_kind: ProcessingArtifactKind,
    kind_mismatch_detail: Callable[[str, ProcessingArtifactKind], str],
) -> tuple[ArtifactRefIssue, str] | None:
    """``baseline``/``current`` 가 실제 등록된 ``required_kind`` 산출물인가.

    통과하면 ``None``. 실패하면 ``(사유, 상세문구)``. ``baseline`` 을
    ``current`` 보다 먼저 본다 — 둘 다 문제여도 ``baseline`` 쪽 상세문구가
    나온다(기존 두 store 의 순회 순서와 동일).
    """
    for label, ref in (("baseline", baseline), ("current", current)):
        issue = verify_artifact_ref(
            processing_job_store,
            ref,
            label=label,
            required_kind=required_kind,
            kind_mismatch_detail=kind_mismatch_detail,
        )
        if issue is not None:
            return issue
    return None


__all__ = ["ArtifactRefIssue", "verify_artifact_pair", "verify_artifact_ref"]
