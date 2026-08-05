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
    # NodeODM ``/task/{uuid}/download/{asset}`` 의 asset 경로.
    asset_path: str
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
        asset_path="cameras.json",
        kind=ProcessingArtifactKind.CAMERA_POSES,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        fmt="json",
        # 카메라 포즈는 그 자체로 공간 좌표계를 갖는 산출물이 아니다.
        needs_crs=False,
    ),
    OdmAsset(
        artifact_id=POINT_CLOUD_ID,
        asset_path="odm_georeferencing/odm_georeferenced_model.laz",
        kind=ProcessingArtifactKind.POINT_CLOUD,
        authority=LineageAuthority.SOURCE,
        derived_from=(),
        fmt="laz",
    ),
    OdmAsset(
        artifact_id="mesh",
        asset_path="odm_texturing/odm_textured_model_geo.obj",
        kind=ProcessingArtifactKind.MESH,
        authority=LineageAuthority.DERIVED,
        # 메시는 포인트 클라우드에서 재구성된다 — 파이프라인 사실이지 추측이 아니다.
        derived_from=(POINT_CLOUD_ID,),
        fmt="obj",
    ),
    OdmAsset(
        artifact_id="orthophoto",
        asset_path="odm_orthophoto/odm_orthophoto.tif",
        kind=ProcessingArtifactKind.ORTHO,
        authority=LineageAuthority.DERIVED,
        derived_from=("mesh",),
        fmt="cog",
        needs_gsd=True,
    ),
    OdmAsset(
        artifact_id="dsm",
        asset_path="odm_dem/dsm.tif",
        kind=ProcessingArtifactKind.DSM,
        authority=LineageAuthority.DERIVED,
        derived_from=(POINT_CLOUD_ID,),
        fmt="cog",
        needs_gsd=True,
    ),
    OdmAsset(
        artifact_id="dtm",
        asset_path="odm_dem/dtm.tif",
        kind=ProcessingArtifactKind.DTM,
        authority=LineageAuthority.DERIVED,
        derived_from=(POINT_CLOUD_ID,),
        fmt="cog",
        needs_gsd=True,
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
