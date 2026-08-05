"""NodeODM 어댑터 — REST 프로세스 경계 하나만 통해 엔진과 말한다 (ADR-KSI-012).

## AGPL 경계가 이 모듈의 형태를 정한다 (D2)

ODM/NodeODM 은 AGPL-3.0 이고, ADR-KSI-012 D2 가 그은 금지선은 **"엔진 코드를 한
줄도 고치지 말고, 우리 코드와 한 저작물로 묶지 마라"**다. 그래서 이 모듈은
:class:`NodeOdmClient` 라는 **포트 하나**만 알고, 그 포트는 HTTP REST 호출
다섯 개(``info``·``new_task``·``task_info``·``download``·``remove``)로만 이뤄진다.

- ODM/WebODM 을 import 하지 않는다.
- 컨테이너 이미지를 만들지도 고치지도 않는다 — 무수정 이미지를 **기동해서
  URL 로 부를** 뿐이다.
- 이 패키지가 AGPL 저작물과 링크되지 않는다는 사실은
  ``tests/contract/test_odm_adapter.py`` 의 import 검사가 기계로 고정한다
  (사람이 기억해서 지키는 규칙으로 두지 않는다).

## ``engineVersion`` 은 지시였다 — 여기서 사실과 대조한다

``ProcessingJob.engineVersion`` 은 발급자가 "이걸로 돌려라"라고 적은 값이고,
B2 시점에는 그게 실제로 돌았는지 확인할 방법이 없었다. 이 어댑터는 작업을
제출하기 **전에** NodeODM ``/info`` 가 보고하는 실제 버전과 대조하고, 다르면
제출하지 않는다(:class:`EngineIdentityMismatch`). 다른 엔진이 돌아놓고 계약에는
지시된 버전이 적히는 상태를 막는다 — 재현성의 앵커가 거짓이 되는 자리다.

**대조하지 못하는 것:** 컨테이너 이미지 digest. NodeODM ``/info`` 는 버전
문자열만 주고 자기 이미지 digest 를 말하지 않는다. ``engineDigest`` 가 실제
이미지와 같은지는 배포 계층(compose/k8s 의 이미지 핀)이 보장해야 하고, 이
어댑터는 그것을 확인할 수단이 없다 — 그래서 확인한 척하지 않는다.

## 실행 순서가 곧 계보다

:data:`~ksi_processing_controller.odm_assets.ODM_ASSETS` 순서대로 등록한다.
Core 는 ``derivedFrom`` 이 **같은 작업에 이미 등록된** artifactId 만 가리키게
강제하므로(``ksi_core.processing_jobs``), 원본(카메라 포즈·포인트 클라우드)이
먼저 등록되지 않으면 파생물 등록이 422 로 거부된다. 순서를 지키는 것이 곧
INV-051 을 지키는 것이다.

## 이 모듈이 하지 않는 것

- **HTTP 구현.** :class:`NodeOdmClient` 는 Protocol 이다. 실제 httpx 구현은
  ``http_node_odm.py`` 에 있고 **실제 NodeODM 대상 검증은 아직 없다**.
- **바이트 전송.** 산출물을 KSI 스토리지로 올리는 경로는 아직 없다 — 이
  어댑터는 NodeODM 이 준 asset 경로와 digest 를 Core 에 등록할 뿐이다.
- **lease·재시도·크래시 복구.** 작업 하나를 끝까지 도는 것만 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from ksi_processing_controller.odm_assets import ODM_ASSETS, OdmAsset

logger = logging.getLogger(__name__)


class OdmTaskStatus(StrEnum):
    """NodeODM 작업 상태 (REST ``/task/{uuid}/info`` 의 ``status.code`` 매핑).

    NodeODM 은 숫자 코드를 쓴다(10=QUEUED, 20=RUNNING, 30=FAILED, 40=COMPLETED,
    50=CANCELED). 숫자를 이 모듈 밖으로 내보내지 않는다 — 엔진의 내부 표현이
    KSI 도메인으로 새면 엔진을 갈아끼울 때 그 숫자가 따라온다.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


# NodeODM 숫자 코드 → 도메인 상태. 이 표가 엔진 표현이 새는 유일한 지점이다.
_NODE_ODM_STATUS_CODES: dict[int, OdmTaskStatus] = {
    10: OdmTaskStatus.QUEUED,
    20: OdmTaskStatus.RUNNING,
    30: OdmTaskStatus.FAILED,
    40: OdmTaskStatus.COMPLETED,
    50: OdmTaskStatus.CANCELED,
}

_TERMINAL_STATUSES = frozenset(
    {OdmTaskStatus.FAILED, OdmTaskStatus.COMPLETED, OdmTaskStatus.CANCELED}
)


def parse_task_status(code: int) -> OdmTaskStatus:
    """NodeODM 상태 코드를 도메인 상태로. **모르는 코드는 실패로 읽는다.**

    새 코드가 생겼는데 "아직 안 끝났나 보다"로 읽으면 워커가 영원히 폴링한다.
    모르는 상태에서 성공을 가정할 근거도 없으므로 fail-closed 다.
    """
    status = _NODE_ODM_STATUS_CODES.get(code)
    if status is None:
        logger.warning("알 수 없는 NodeODM 상태 코드 %s — FAILED 로 읽는다", code)
        return OdmTaskStatus.FAILED
    return status


class OdmError(RuntimeError):
    """NodeODM 경계에서 발생한 실패 — 호출자가 작업을 FAILED 로 보고한다."""


class EngineIdentityMismatch(OdmError):
    """계약이 지시한 엔진과 실제로 응답한 엔진이 다르다."""


@dataclass(frozen=True, slots=True)
class OdmEngineInfo:
    """NodeODM ``/info`` 응답 중 우리가 쓰는 부분."""

    version: str
    task_queue_count: int = 0


@dataclass(frozen=True, slots=True)
class OdmTaskState:
    status: OdmTaskStatus
    # 실패 사유. NodeODM 이 주면 그대로 옮긴다(우리가 지어내지 않는다).
    error_message: str | None = None
    progress: float | None = None


@dataclass(frozen=True, slots=True)
class SourceImage:
    """워커가 받아둔 원본 1장 — Core 가 준 다운로드 URL 과 그 식별자.

    바이트를 이 모듈이 들고 있지 않다. NodeODM 에 넘기는 실제 전송은 클라이언트
    구현의 몫이고, 여기서는 "무엇을 넘길지"만 정한다.
    """

    media_id: str
    download_url: str


class NodeOdmClient(Protocol):
    """NodeODM REST 표면 — **이 다섯 개가 AGPL 경계의 전부다.**

    구현체를 갈아끼워 테스트한다(네트워크·컨테이너 없이). 이 Protocol 에 없는
    방식으로 엔진과 말하는 경로를 이 패키지에 만들지 않는다.
    """

    def info(self) -> OdmEngineInfo:
        """``GET /info`` — 엔진 신원 확인용."""
        ...

    def new_task(self, images: Sequence[SourceImage], options: dict[str, Any]) -> str:
        """``POST /task/new`` — 작업 uuid 를 돌려준다."""
        ...

    def task_info(self, uuid: str) -> OdmTaskState:
        """``GET /task/{uuid}/info``."""
        ...

    def download(self, uuid: str, asset_path: str) -> str:
        """``GET /task/{uuid}/download/{asset}`` — 산출물의 sha256 digest.

        바이트가 아니라 digest 를 돌려주는 것이 의도다. 이 어댑터는 산출물의
        **계보**를 Core 에 등록할 뿐 내용을 들고 있지 않다.
        """
        ...

    def remove_task(self, uuid: str) -> None:
        """``POST /task/remove`` — 끝난 작업의 엔진 쪽 정리."""
        ...


@dataclass(frozen=True, slots=True)
class ArtifactReport:
    """Core 에 등록할 산출물 1건 — ``ProcessingArtifactRequest`` 로 그대로 옮겨진다.

    ``source_digest`` 가 없는 것이 의도다. 계보 앵커는 Core 가 작업 원장에서
    채운다(``ksi_core.processing_jobs``) — 워커가 실어 보낼 자리가 없다.
    """

    artifact_id: str
    kind: str
    authority: str
    derived_from: tuple[str, ...]
    digest: str
    fmt: str
    crs: str | None
    gsd: float | None


def assert_engine_matches(info: OdmEngineInfo, *, expected_version: str) -> None:
    """계약이 지시한 엔진 버전과 실제 응답이 같은지.

    같은지만 본다 — "호환되는가"를 판정하지 않는다. semver 호환 판정을 넣으면
    이 함수가 엔진별 버전 정책을 알아야 하고, 그 정책이 틀렸을 때 조용히
    다른 엔진이 도는 것을 허용하게 된다.
    """
    if info.version != expected_version:
        raise EngineIdentityMismatch(
            f"계약이 지시한 엔진은 {expected_version!r} 인데 실제 응답은 "
            f"{info.version!r} 이다 — 다른 엔진이 돌면 engineVersion 이 거짓이 되고 "
            "재현성 앵커가 무너진다. 작업을 제출하지 않는다"
        )


def plan_artifacts(
    uuid: str,
    client: NodeOdmClient,
    *,
    crs: str,
    gsd_by_artifact: dict[str, float] | None = None,
    assets: Sequence[OdmAsset] = ODM_ASSETS,
) -> list[ArtifactReport]:
    """완료된 작업의 산출물을 **등록 순서대로** 만든다.

    순서가 곧 계보다 — 원본이 먼저 나와야 파생물의 ``derivedFrom`` 이 실재하는
    부모를 가리킨다(모듈 docstring). 엔진이 내놓지 않은 산출물은 조용히 건너뛴다:
    ODM 은 옵션에 따라 DTM·정사영상을 만들지 않을 수 있고, 없는 것을 실패로
    읽으면 정상 설정이 실패가 된다. 대신 **원본이 하나도 없으면** 그건 성공한
    재구성이 아니므로 :class:`OdmError` 다(Core 의 SUCCEEDED 게이트와 같은 판단).

    ``gsd_by_artifact`` 는 래스터 계열에만 필요하다 — 없으면 그 산출물을 건너뛴다.
    지어낸 GSD 를 싣느니 산출물을 빼는 편이 낫다(계약이 null 을 금지하는 kind 라
    싣는 순간 거짓이 된다).
    """
    gsd_map = gsd_by_artifact or {}
    reports: list[ArtifactReport] = []
    for asset in assets:
        try:
            digest = client.download(uuid, asset.asset_path)
        except OdmError:
            logger.info("엔진이 %s 를 내놓지 않았다 — 건너뛴다", asset.asset_path)
            continue
        gsd = gsd_map.get(asset.artifact_id)
        if asset.needs_gsd and gsd is None:
            logger.warning(
                "%s 는 GSD 가 필수인데 값이 없다 — 지어내지 않고 건너뛴다",
                asset.artifact_id,
            )
            continue
        # 파생물의 부모가 실제로 등록 목록에 있는지 여기서 본다. 엔진이 부모를
        # 안 내놨는데 자식만 등록하면 Core 가 422 로 거부하고, 그 거부는 워커
        # 로그에서 원인을 알기 어렵다 — 여기서 걸러 이유를 남긴다.
        planned = {report.artifact_id for report in reports}
        missing_parents = [p for p in asset.derived_from if p not in planned]
        if missing_parents:
            logger.warning(
                "%s 의 부모 %s 가 이번 산출물에 없다 — 계보 없는 파생은 등록하지 않는다",
                asset.artifact_id,
                missing_parents,
            )
            continue
        reports.append(
            ArtifactReport(
                artifact_id=asset.artifact_id,
                kind=asset.kind.value,
                authority=asset.authority.value,
                derived_from=asset.derived_from,
                digest=digest,
                fmt=asset.fmt,
                crs=crs if asset.needs_crs else None,
                gsd=gsd,
            )
        )
    if not any(report.authority == "source" for report in reports):
        raise OdmError(
            "엔진이 원본 산출물(포인트 클라우드·카메라 포즈)을 하나도 내놓지 "
            "않았다 — 파생물만으로는 성공한 재구성이 아니다(INV-051)"
        )
    return reports


def run_to_completion(
    client: NodeOdmClient,
    images: Sequence[SourceImage],
    *,
    expected_version: str,
    options: dict[str, Any],
    poll: Callable[[], None],
    max_polls: int = 10_000,
) -> str:
    """엔진 신원 확인 → 제출 → 종료까지 폴링. 완료된 작업의 uuid 를 돌려준다.

    ``poll`` 은 호출자가 주는 대기 함수다(``time.sleep`` 을 이 모듈이 직접 부르지
    않는다 — 테스트가 실제로 기다리게 만들지 않기 위해서다).

    ``max_polls`` 는 상한이다. NodeODM 이 상태를 영영 바꾸지 않는 경우(엔진
    행) 워커가 무한 루프에 갇히는 대신 실패로 끝난다 — 갇힌 워커는 lease 가
    없는 지금 구조에서 그 작업을 영구히 점유한다.
    """
    assert_engine_matches(client.info(), expected_version=expected_version)
    uuid = client.new_task(images, options)
    for _ in range(max_polls):
        state = client.task_info(uuid)
        if state.status in _TERMINAL_STATUSES:
            if state.status is not OdmTaskStatus.COMPLETED:
                raise OdmError(
                    f"엔진 작업이 {state.status.value} 로 끝났다"
                    + (f": {state.error_message}" if state.error_message else "")
                )
            return uuid
        poll()
    raise OdmError(
        f"엔진 작업이 {max_polls}회 폴링 동안 종료 상태에 도달하지 않았다 — "
        "행으로 보고 실패 처리한다(무한 대기는 워커를 영구 점유한다)"
    )


__all__ = [
    "ArtifactReport",
    "EngineIdentityMismatch",
    "NodeOdmClient",
    "OdmEngineInfo",
    "OdmError",
    "OdmTaskState",
    "OdmTaskStatus",
    "SourceImage",
    "assert_engine_matches",
    "parse_task_status",
    "plan_artifacts",
    "run_to_completion",
]
