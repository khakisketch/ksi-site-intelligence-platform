"""NodeODM 산출물 → ``ProcessingArtifact`` 계보 매핑 (ADR-KSI-012 D1, ADR-KSI-003).

NodeODM 은 작업이 끝나면 정해진 이름의 파일들을 내놓는다. 그 이름을 계약의
``kind`` 와 ``lineage.authority`` 로 옮기는 것이 이 모듈의 전부다 — 그리고
**그 옮김이 INV-051 의 실질**이다.

## 무엇이 원본이고 무엇이 파생인가

ADR-KSI-003 은 "Point Cloud 가 원본 SSOT, Mesh/정사영상/3D Tiles 는 파생 서빙
계층"이라고 정했다. ODM 파이프라인의 실제 데이터 흐름이 정확히 그렇다:

- SfM/MVS 가 사진에서 **카메라 포즈**와 **포인트 클라우드**를 직접 만든다 → 원본
- 메시는 포인트 클라우드에서 재구성된다 → 파생
- 정사영상·DSM·DTM 은 메시/포인트 클라우드를 래스터화한 것이다 → 파생

그래서 ``derived_from`` 이 비어 있지 않은 파생물의 부모는 **추측이 아니라
파이프라인 사실**이다. 이 매핑이 틀리면 "파생을 원본의 권위로 쓰지 않는다"는
불변식이 이름표만 남고 실질을 잃는다.

### 알려진 한계 — ``--fast-orthophoto`` 모드는 모델링돼 있지 않다

이 표는 **기본 ODM 파이프라인**의 계보다. ODM 을 ``--fast-orthophoto`` 로 돌리면
텍스처링(메시)을 건너뛰고 포인트 클라우드에서 정사영상을 바로 만들어서, 정사영상의
직접 부모가 메시가 아니라 포인트 클라우드가 된다. 지금 표는 그 분기를 표현하지
못하므로 그 모드에서는 정사영상이 **등록되지 않고 건너뛰어진다**(부모 부재 —
``odm.plan_artifacts`` 가 경고를 남긴다).

틀린 부모를 다는 것보다 빠뜨리는 쪽을 택했다 — 계보가 거짓이면 INV-051 이
무의미해지지만, 빠진 산출물은 로그에 남고 사람이 알아챈다. 그 모드를 실제로 쓸
때 표를 옵션별로 가른다.

## 실물이 고쳐준 것 — ``cameras.json`` 은 포즈가 아니다

처음엔 ``cameras.json`` 을 ``CAMERA_POSES`` 로 매핑했는데, 실제 아카이브를 열어
보니 그 파일은 카메라 **내부 파라미터**였다(``focal_x``·``c_x``·``k1``… ,
카메라 *모델*당 1개). 사진마다의 위치·자세는 ``odm_report/shots.geojson`` 에
있다 — 사진 1장당 feature 1개, ``translation``·``rotation`` 과 Point geometry.
파일 이름만 보고 정한 매핑이 틀렸고, 실물 완주 전까지 드러나지 않았다
(2026-08-06, ODM 3.5.6 / pacifica 12장).

## 매핑하지 않은 실제 산출물

실물 아카이브에는 있지만 여기 표에 넣지 않은 것들이다 — 없어서 안 넣은 게
아니라 **지금 모델로는 한 산출물 = 한 파일 = 한 digest 가 성립하지 않아서**다:

- ``entwine_pointcloud/``(EPT) · ``3d_tiles``: 포인트 클라우드 스트리밍 서빙
  계층으로 ``tiles_3d`` 에 해당하지만, 파일 수십 개짜리 디렉터리라 단일 digest 가
  대표하지 못한다. 서빙 계층을 실제로 쓸 때 "디렉터리 산출물"을 어떻게 봉인할지
  함께 정한다.
- ``odm_texturing/`` 의 텍스처(``*_map_Kd.png``)·``.mtl``: 메시 artifact 의
  digest 는 ``.obj`` **하나만** 덮는다. 텍스처가 바뀌어도 digest 가 그대로라는
  뜻이다 — 메시를 시각 산출물로 납품하기 전에 닫아야 할 구멍이다.
- ``odm_report/stats.json``·``images.json``·``log.json``: 진단용이고 계약의
  ``kind`` 에 대응이 없다.

## 정확도는 ``None`` 이다 — 비어 있는 게 아니라 없는 것

ODM 에는 구조화된 GCP/RMSE 리포트가 없다(ADR-KSI-012 D3). 이 값이 null 인 비율이
Pix4D 전환 트리거의 계측점이라, 지어내지 않고 명시적으로 ``None`` 을 싣는다.

## 이 모듈이 ODM 코드를 부르지 않는다는 것

여기 있는 건 **파일 이름 문자열**뿐이다. ODM/WebODM 을 import 하지 않고, 그
소스 트리를 참조하지도 않는다 — AGPL 경계(ADR-KSI-012 D2)는 프로세스 경계이자
저작물 경계이고, 이 패키지 전체가 그 경계 바깥에 있다는 것은
``tests/contract/test_odm_adapter.py`` 의 import 검사가 기계로 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ksi_event_contracts.processing_artifact import (
    LineageAuthority,
    ProcessingArtifactKind,
)

# 계보의 부모로 쓰이는 원본 산출물의 artifactId — 파생물의 ``derived_from`` 이
# 이 값을 가리킨다. Core 는 "같은 작업에 실재하는 부모"만 허용하므로
# (``processing_jobs._check_artifact_identity_locked``) 등록 순서가 곧 계보다.
POINT_CLOUD_ID = "point-cloud"
CAMERA_POSES_ID = "camera-poses"


@dataclass(frozen=True, slots=True)
class OdmAsset:
    """NodeODM 이 내놓는 산출물 1건과 그 계보.

    ``artifact_id`` 는 KSI 가 정하는 이름이지 ODM 의 파일명이 아니다 — 엔진을
    갈아끼워도(Pix4D 등) 같은 식별자 체계를 쓸 수 있게 분리한다.
    """

    artifact_id: str
    # **``all.zip`` 안의 엔트리 경로**다(다운로드 엔드포인트의 asset 이름이 아니다).
    # NodeODM 의 ``Task.getAssetsArchivePath`` 는 ``all.zip`` 외의 이름을 전부
    # 거부하므로(실기동 확인, 2026-08-06) 산출물은 아카이브 하나로만 나온다.
    # 이 경로들은 NodeODM ``libs/Task.js`` 의 ``allPaths`` 목록과 같은 값이다.
    archive_entry: str
    kind: ProcessingArtifactKind
    authority: LineageAuthority
    derived_from: tuple[str, ...]
    fmt: str
    # 래스터 계열만 gsd 가 산출물 고유 속성이다 — 나머지는 계약이 null 을 허용한다
    # (``processing_artifact._GSD_REQUIRED_KINDS``). 실제 값은 엔진 리포트에서
    # 읽어 채운다(:func:`resolve_gsd` 가 아직 없으므로 지금은 호출자가 준다).
    needs_gsd: bool = False
    # 공간 좌표계가 없는 산출물(카메라 포즈)은 crs 가 null 이어야 한다.
    needs_crs: bool = True


# ODM 파이프라인의 표준 산출물. **순서가 곧 등록 순서다** — 원본이 먼저 등록돼야
# 파생물의 ``derivedFrom`` 이 실재하는 부모를 가리킨다.
ODM_ASSETS: tuple[OdmAsset, ...] = (
    OdmAsset(
        artifact_id=CAMERA_POSES_ID,
        # **``cameras.json`` 이 아니다.** 그 파일은 카메라 **내부 파라미터**
        # (focal·주점·왜곡계수)이고 카메라 *모델*당 1개다 — 사진마다의 위치·자세가
        # 아니다. 실제 포즈는 여기 있다: 사진 1장당 feature 1개, translation·
        # rotation 과 Point geometry(실측 확인, 2026-08-06).
        archive_entry="odm_report/shots.geojson",
        kind=ProcessingArtifactKind.CAMERA_POSES,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        fmt="geojson",
        # 카메라 포즈는 그 자체로 공간 좌표계를 갖는 산출물이 아니다.
        needs_crs=False,
    ),
    OdmAsset(
        artifact_id=POINT_CLOUD_ID,
        archive_entry="odm_georeferencing/odm_georeferenced_model.laz",
        kind=ProcessingArtifactKind.POINT_CLOUD,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        fmt="laz",
    ),
    OdmAsset(
        artifact_id="mesh",
        archive_entry="odm_texturing/odm_textured_model_geo.obj",
        kind=ProcessingArtifactKind.MESH,
        authority=LineageAuthority.DERIVED,
        # 메시는 포인트 클라우드에서 재구성된다 — 파이프라인 사실이지 추측이 아니다.
        derived_from=(POINT_CLOUD_ID,),
        fmt="obj",
    ),
    OdmAsset(
        artifact_id="orthophoto",
        archive_entry="odm_orthophoto/odm_orthophoto.tif",
        kind=ProcessingArtifactKind.ORTHO,
        authority=LineageAuthority.DERIVED,
        derived_from=("mesh",),
        fmt="cog",
        needs_gsd=True,
    ),
    OdmAsset(
        artifact_id="dsm",
        archive_entry="odm_dem/dsm.tif",
        kind=ProcessingArtifactKind.DSM,
        authority=LineageAuthority.DERIVED,
        derived_from=(POINT_CLOUD_ID,),
        fmt="cog",
        needs_gsd=True,
    ),
    OdmAsset(
        artifact_id="dtm",
        archive_entry="odm_dem/dtm.tif",
        kind=ProcessingArtifactKind.DTM,
        authority=LineageAuthority.DERIVED,
        derived_from=(POINT_CLOUD_ID,),
        fmt="cog",
        needs_gsd=True,
    ),
    OdmAsset(
        artifact_id="report",
        archive_entry="odm_report/report.pdf",
        kind=ProcessingArtifactKind.REPORT,
        authority=LineageAuthority.DERIVED,
        derived_from=(POINT_CLOUD_ID,),
        fmt="pdf",
        # 리포트는 좌표계도 픽셀 표본거리도 갖지 않는다 — 계약이 둘 다 null 을
        # 허용하는 유일한 kind 조합이고, 그래서 지어낼 필요가 없다.
        needs_crs=False,
    ),
)


def assets_by_id() -> dict[str, OdmAsset]:
    return {asset.artifact_id: asset for asset in ODM_ASSETS}


__all__ = [
    "CAMERA_POSES_ID",
    "ODM_ASSETS",
    "POINT_CLOUD_ID",
    "OdmAsset",
    "assets_by_id",
]
