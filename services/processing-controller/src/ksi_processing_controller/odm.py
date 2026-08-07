"""NodeODM 어댑터 — REST 프로세스 경계 하나만 통해 엔진과 말한다 (ADR-KSI-012).

## AGPL 경계가 이 모듈의 형태를 정한다 (D2)

ODM/NodeODM 은 AGPL-3.0 이고, ADR-KSI-012 D2 가 그은 금지선은 **"엔진 코드를 한
줄도 고치지 말고, 우리 코드와 한 저작물로 묶지 마라"**다. 그래서 이 모듈은
:class:`NodeOdmClient` 라는 **포트 하나**만 알고, 그 포트는 HTTP REST 호출
다섯 개(``info``·``new_task``·``task_info``·``download_archive``·``remove_task``)
로만 이뤄진다.

- ODM/WebODM 을 import 하지 않는다.
- 컨테이너 이미지를 만들지도 고치지도 않는다 — 무수정 이미지를 **기동해서
  URL 로 부를** 뿐이다.
- 이 패키지가 AGPL 저작물과 링크되지 않는다는 사실은
  ``tests/contract/test_odm_adapter.py`` 의 import 검사가 기계로 고정한다
  (사람이 기억해서 지키는 규칙으로 두지 않는다).

## 실물이 고쳐준 것 — 이 모듈의 형태는 추측이 아니다

아래 넷은 무수정 ``opendronemap/nodeodm:latest``(NodeODM 2.2.4 / ODM 3.5.6)를
띄워 REST 를 직접 두드려 확인한 사실이고, 처음 설계는 넷 다 틀렸다(2026-08-06).

1. **``/info`` 는 버전을 둘 준다** — ``version`` 은 NodeODM 자신(2.2.4),
   ``engineVersion`` 이 ODM 엔진(3.5.6)이다. ``ProcessingJob.engineVersion`` 이
   가리키는 것은 후자다. 처음엔 ``version`` 을 대조해서, 늘 어긋나면서 애초에
   다른 것을 비교하고 있었다.
2. **산출물은 ``all.zip`` 하나로만 나온다** — ``Task.getAssetsArchivePath`` 가
   ``all.zip`` 외의 이름을 전부 거부한다. 개별 asset 다운로드는 NodeODM 에
   존재하지 않는 기능이라, 산출물별 digest 는 아카이브 **안에서** 계산한다.
3. **에러가 HTTP 200 으로 온다** — 미지 uuid 도, 준비 안 된 asset 도 200 에
   ``{"error": ...}`` 본문이다. 상태 코드만 보는 클라이언트는 그것을 성공으로
   읽고 다음 줄에서 KeyError 를 낸다(:func:`_unwrap`).
4. **상태 코드 30 은 ``errorMessage`` 를 동반한다** — ``{"status": {"code": 30,
   "errorMessage": "Cannot process dataset"}}``. 그 문자열을 우리가 지어내지
   않고 그대로 옮긴다.

## ``engineVersion`` 은 지시였다 — 여기서 사실과 대조한다

``ProcessingJob.engineVersion`` 은 발급자가 "이걸로 돌려라"라고 적은 값이고,
그게 실제로 돌았는지 확인할 방법이 없었다. 이 어댑터는 작업을 제출하기 **전에**
``/info`` 가 보고하는 실제 엔진 이름·버전과 대조하고, 다르면 제출하지 않는다
(:class:`EngineIdentityMismatch`). 다른 엔진이 돌아놓고 계약에는 지시된 버전이
적히는 상태를 막는다 — 재현성의 앵커가 거짓이 되는 자리다.

**대조하지 못하는 것:** 컨테이너 이미지 digest. ``/info`` 는 버전 문자열만 주고
자기 이미지 digest 를 말하지 않는다. ``engineDigest`` 가 실제 이미지와 같은지는
배포 계층(compose/k8s 의 이미지 핀)이 보장해야 하고, 이 어댑터는 그것을 확인할
수단이 없다 — 그래서 확인한 척하지 않는다.

## 실행 순서가 곧 계보다

:data:`~ksi_processing_controller.odm_assets.ODM_ASSETS` 순서대로 등록한다.
Core 는 ``derivedFrom`` 이 **같은 작업에 이미 등록된** artifactId 만 가리키게
강제하므로(``ksi_core.processing_jobs``), 원본(카메라 포즈·포인트 클라우드)이
먼저 등록되지 않으면 파생물 등록이 422 로 거부된다. 순서를 지키는 것이 곧
INV-051 을 지키는 것이다.

## 산출물 바이트 — digest 를 잰 그 파일을 다시 흘려보낸다

:func:`plan_artifacts` 가 계산한 digest 와 :func:`iter_archive_entry_bytes` 가
내주는 바이트는 **같은 아카이브 엔트리**다(``ArtifactReport.archive_entry`` 가
그 연결이다). 이 등식이 깨지면 계보 검증이 의미를 잃으므로 계약 테스트가
단일 파일 산출물 전부에서 이를 대조한다.

**저장 시점에 포맷을 변환하지 않는다.** GeoTIFF→COG 변환은 원본에서 재생성하는
파생 서빙 계층의 몫이고(ADR-KSI-003, INV-051), 저장 단계에서 바꾸면 저장된
바이트가 등록된 digest 와 달라진다.

**메시는 예외다.** 텍스처·재질이 digest 에 함께 들어가 산출물 하나가 파일
하나가 아니라서(``is_single_file=False``) 객체 키 하나에 충실히 담을 수 없다 —
업로드 여부는 워커가 이 플래그로 판단한다.

## 이 모듈이 하지 않는 것

- **업로드 자체.** 여기는 바이트를 *흘려보내는* 데까지고, presigned PUT 으로
  실제로 쓰는 것은 워커의 몫이다(Core 가 자리를 정하고 워커가 쓴다).
- **lease 갱신 루프.** Core 의 lease 는 15분이고 ODM 재구성은 몇 시간이라
  워커는 폴링 중에 갱신해야 한다 — 그 배선은 워커 데몬의 몫이다.
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from ksi_processing_controller.odm_assets import ODM_ASSETS, OdmAsset

logger = logging.getLogger(__name__)

# NodeODM 이 내주는 유일한 산출물 asset 이름(실기동 확인 — 그 외는 전부 거부된다).
ARCHIVE_ASSET = "all.zip"
# ``/info`` 의 ``engine`` 값. provider 가 odm 인 작업만 이 어댑터가 받는다.
ODM_ENGINE_NAME = "odm"


class OdmTaskStatus(StrEnum):
    """NodeODM 작업 상태 (REST ``/task/{uuid}/info`` 의 ``status.code`` 매핑).

    NodeODM 은 숫자 코드를 쓴다. 숫자를 이 모듈 밖으로 내보내지 않는다 — 엔진의
    내부 표현이 KSI 도메인으로 새면 엔진을 갈아끼울 때 그 숫자가 따라온다.
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


def unwrap_response(payload: Any, *, what: str) -> dict[str, Any]:
    """NodeODM 응답 봉투를 벗긴다 — **에러가 HTTP 200 으로 온다**(실기동 확인).

    미지 uuid 도 준비 안 된 asset 도 상태 코드는 200 이고 본문만
    ``{"error": "..."}`` 다. 상태 코드로 성공을 판정하면 그 응답을 성공으로
    읽고 다음 줄에서 KeyError 가 난다 — 원인이 두 겹 뒤에서 드러나는 실패다.
    """
    if not isinstance(payload, dict):
        raise OdmError(f"{what}: 응답이 JSON 객체가 아니다({type(payload).__name__})")
    error = payload.get("error")
    if error is not None:
        raise OdmError(f"{what}: {error}")
    return payload


@dataclass(frozen=True, slots=True)
class OdmEngineInfo:
    """``/info`` 응답 중 우리가 쓰는 부분.

    ``node_version`` 과 ``engine_version`` 이 **다른 값**이라는 것이 요점이다
    (모듈 docstring 1번) — 계약의 ``engineVersion`` 이 가리키는 것은 후자다.
    """

    engine: str
    engine_version: str
    node_version: str = ""
    task_queue_count: int = 0
    max_images: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OdmEngineInfo:
        data = unwrap_response(payload, what="/info")
        try:
            return cls(
                engine=data["engine"],
                engine_version=data["engineVersion"],
                node_version=data.get("version", ""),
                task_queue_count=data.get("taskQueueCount", 0),
                max_images=data.get("maxImages"),
            )
        except KeyError as exc:
            raise OdmError(f"/info 응답에 필수 필드가 없다: {exc}") from exc


@dataclass(frozen=True, slots=True)
class OdmTaskState:
    status: OdmTaskStatus
    # 실패 사유. NodeODM 이 주면 그대로 옮긴다(우리가 지어내지 않는다).
    error_message: str | None = None
    progress: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OdmTaskState:
        data = unwrap_response(payload, what="/task/info")
        status = data.get("status")
        if not isinstance(status, dict) or "code" not in status:
            raise OdmError(f"/task/info 응답에 status.code 가 없다: {data!r}")
        return cls(
            status=parse_task_status(int(status["code"])),
            error_message=status.get("errorMessage"),
            progress=data.get("progress"),
        )


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

    def download_archive(self, uuid: str, dest: Path) -> Path:
        """``GET /task/{uuid}/download/all.zip`` — **유일한** 산출물 경로.

        개별 asset 다운로드는 NodeODM 에 없다(모듈 docstring 2번).
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
    # 이 산출물의 바이트가 아카이브 어디에 있는가 — digest 를 계산한 그 파일이다.
    # 이 연결이 없어서 지금까지 digest 만 남기고 바이트를 버려 왔다.
    archive_entry: str = ""
    # 산출물 하나가 파일 하나인가. 메시처럼 텍스처·재질이 digest 에 함께 들어가는
    # 산출물은 False 이고, 그런 산출물은 **객체 키 하나에 충실히 담을 수 없다** —
    # 대표 파일만 올리면 저장된 바이트와 등록된 digest 가 어긋난다
    # (risk mesh-auxiliary-files-not-persisted).
    is_single_file: bool = True


def assert_engine_matches(
    info: OdmEngineInfo,
    *,
    expected_version: str,
    expected_engine: str = ODM_ENGINE_NAME,
) -> None:
    """계약이 지시한 엔진 이름·버전과 실제 응답이 같은지.

    ``info.engine_version`` 을 본다 — ``/info`` 의 ``version`` 은 NodeODM 자신의
    버전이라 계약이 말하는 엔진 버전이 아니다(모듈 docstring 1번).

    같은지만 본다 — "호환되는가"를 판정하지 않는다. semver 호환 판정을 넣으면
    이 함수가 엔진별 버전 정책을 알아야 하고, 그 정책이 틀렸을 때 조용히
    다른 엔진이 도는 것을 허용하게 된다.
    """
    if info.engine != expected_engine:
        raise EngineIdentityMismatch(
            f"이 어댑터는 {expected_engine!r} 엔진용인데 응답은 {info.engine!r} 이다"
        )
    if info.engine_version != expected_version:
        raise EngineIdentityMismatch(
            f"계약이 지시한 엔진은 {expected_version!r} 인데 실제 응답은 "
            f"{info.engine_version!r} 이다 — 다른 엔진이 돌면 engineVersion 이 "
            "거짓이 되고 재현성 앵커가 무너진다. 작업을 제출하지 않는다"
        )


def digest_archive_entry(archive: zipfile.ZipFile, entry: str) -> str:
    """아카이브 안 파일 하나의 sha256 — 스트리밍으로 읽는다.

    포인트 클라우드는 수 GB 가 될 수 있어 통째로 메모리에 올리지 않는다.
    """
    digest = hashlib.sha256()
    with archive.open(entry) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def digest_archive_entries(archive: zipfile.ZipFile, entries: Sequence[str]) -> str:
    """아카이브 안 여러 파일의 결합 sha256 — 경로 정렬 후 이름+내용을 함께 해싱한다.

    메시처럼 산출물이 파일 하나가 아니라 여러 파일(.obj+.mtl+텍스처)로 이뤄지면
    대표 파일 하나만 해싱해선 나머지가 바뀌어도 digest 가 그대로다
    (risk mesh-digest-ignores-textures). 정렬은 아카이브 내 나열 순서에 기대지
    않기 위함이고, 경로도 함께 해싱해 파일이 늘거나 줄어도 잡아낸다.
    """
    digest = hashlib.sha256()
    for entry in sorted(entries):
        digest.update(entry.encode("utf-8"))
        digest.update(b"\0")
        with archive.open(entry) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def iter_archive_entry_bytes(
    archive_path: Path, entry: str, *, chunk_size: int = 1024 * 1024
) -> Iterator[bytes]:
    """아카이브 안 파일 하나를 청크 단위로 흘려보낸다.

    :func:`digest_archive_entry` 와 **같은 읽기 관용구**다 — 그래야 "digest 를
    계산한 바이트"와 "업로드한 바이트"가 같은 것임을 말할 수 있다. 포인트
    클라우드는 수 GB 가 될 수 있어 통째로 메모리에 올리지 않는다.

    없는 엔트리는 :class:`OdmError` 다 — 빈 바이트를 돌려주면 호출부가 그것을
    유효한 빈 파일로 취급해 0바이트 산출물이 스토리지에 올라간다.
    """
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise OdmError(f"산출물 아카이브를 열 수 없다({archive_path}): {exc}") from exc
    with archive:
        try:
            handle = archive.open(entry)
        except KeyError as exc:
            raise OdmError(f"아카이브에 {entry} 가 없다") from exc
        with handle:
            yield from iter(lambda: handle.read(chunk_size), b"")


def plan_artifacts(
    archive_path: Path,
    *,
    crs: str,
    gsd_by_artifact: dict[str, float] | None = None,
    assets: Sequence[OdmAsset] = ODM_ASSETS,
) -> list[ArtifactReport]:
    """``all.zip`` 을 열어 산출물을 **등록 순서대로** 만든다.

    순서가 곧 계보다 — 원본이 먼저 나와야 파생물의 ``derivedFrom`` 이 실재하는
    부모를 가리킨다(모듈 docstring). 아카이브에 없는 산출물은 조용히 건너뛴다:
    ODM 은 옵션에 따라 DTM·정사영상을 만들지 않을 수 있고, 없는 것을 실패로
    읽으면 정상 설정이 실패가 된다. 대신 **원본이 하나도 없으면** 그건 성공한
    재구성이 아니므로 :class:`OdmError` 다(Core 의 SUCCEEDED 게이트와 같은 판단).

    ``gsd_by_artifact`` 는 래스터 계열에만 필요하다 — 없으면 그 산출물을 건너뛴다.
    지어낸 GSD 를 싣느니 산출물을 빼는 편이 낫다(계약이 null 을 금지하는 kind 라
    싣는 순간 거짓이 된다).
    """
    gsd_map = gsd_by_artifact or {}
    reports: list[ArtifactReport] = []
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise OdmError(f"산출물 아카이브를 열 수 없다({archive_path}): {exc}") from exc
    with archive:
        present = set(archive.namelist())
        for asset in assets:
            if asset.archive_entry not in present:
                logger.info("아카이브에 %s 가 없다 — 건너뛴다", asset.archive_entry)
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
            aux_entries: list[str] = []
            if asset.auxiliary_suffixes:
                directory = posixpath.dirname(asset.archive_entry)
                aux_entries = [
                    e
                    for e in present
                    if e != asset.archive_entry
                    and posixpath.dirname(e) == directory
                    and e.endswith(asset.auxiliary_suffixes)
                ]
            if aux_entries:
                digest = digest_archive_entries(archive, (asset.archive_entry, *aux_entries))
            else:
                digest = digest_archive_entry(archive, asset.archive_entry)
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
                    archive_entry=asset.archive_entry,
                    # 부속 파일이 **실제로 있을 때만** 파일 하나가 아니다. 선언만
                    # 돼 있고 아카이브에 없으면 digest 는 단일 엔트리 해시라
                    # 저장·대조가 그대로 성립한다.
                    is_single_file=not aux_entries,
                )
            )
    if not any(report.authority == "source" for report in reports):
        raise OdmError(
            "아카이브에 원본 산출물(포인트 클라우드·카메라 포즈)이 하나도 없다 — "
            "파생물만으로는 성공한 재구성이 아니다(INV-051)"
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
    않는다 — 테스트가 실제로 기다리게 만들지 않기 위해서다). 워커는 이 콜백
    안에서 Core lease 를 갱신한다(모듈 docstring "하지 않는 것").

    ``max_polls`` 는 상한이다. NodeODM 이 상태를 영영 바꾸지 않는 경우(엔진
    행) 워커가 무한 루프에 갇히는 대신 실패로 끝난다 — 갇힌 워커는 Core lease 를
    계속 갱신하며 그 작업을 점유한다.
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
    "ARCHIVE_ASSET",
    "ODM_ENGINE_NAME",
    "ArtifactReport",
    "EngineIdentityMismatch",
    "NodeOdmClient",
    "OdmEngineInfo",
    "OdmError",
    "OdmTaskState",
    "OdmTaskStatus",
    "SourceImage",
    "assert_engine_matches",
    "digest_archive_entry",
    "digest_archive_entries",
    "parse_task_status",
    "plan_artifacts",
    "run_to_completion",
    "unwrap_response",
]
