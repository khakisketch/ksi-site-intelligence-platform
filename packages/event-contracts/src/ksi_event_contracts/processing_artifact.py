"""ProcessingArtifact — 재구성 산출물 계보 계약 (ADR-KSI-012, ADR-KSI-003, INV-051).

## 왜 이 계약이 필요한가

ADR-KSI-003(공간 데이터 계보)은 "Point Cloud가 원본 SSOT, Mesh/3D Tiles/정사영상은
파생 서빙 계층"이라는 원칙을 정하면서 "구체 스키마는 Processing 구현 시 확정한다"고
미뤄뒀다. 이 모듈이 그 스키마다 — ADR-KSI-012가 확정한 실제 처리 엔진(ODM 등)의
산출물에도 같은 원칙을 강제한다(INV-051).

## authority/derivedFrom이 강제하는 것

파생 산출물을 원본의 권위로 대체해 측정·완료 판정 근거로 쓰지 않는다는 원칙을,
"파생이라고 주장하려면 무엇에서 파생됐는지 밝혀라"는 형태로 코드에 옮긴다
(:meth:`ArtifactLineage._derived_requires_parents`). ``kind`` 값(point_cloud vs
mesh 등) 자체는 authority를 강제하지 않는다 — 계보의 진실은 ``lineage.authority``
필드이지 산출물 종류 라벨이 아니다. 이는 향후 provider별 예외(예: 어떤 엔진이
point_cloud를 다른 원본에서 재생성하는 경로)를 스키마 레벨에서 미리 봉인하지
않기 위한 의도적 선택이다.

## accuracy/crs/gsd가 nullable인 이유

ODM에는 구조화된 측량 정확도(GCP/RMSE) 리포트가 없다(ADR-KSI-012 결과). 이 필드가
null인 비율은 ADR-KSI-012 D3("Pix4D로 갈아타는 전환 트리거" 판단)의 계측점이라,
필드를 생략하는 대신 명시적으로 null을 싣는다 — "측정하지 않았다"와 "필드를
잊었다"를 구분하기 위해서다. 그래서 :func:`processing_artifact_wire_dict`는
``exclude_none``에서 ``accuracy``·``crs``·``gsd``를 제외한다.

같은 이유로 ``crs``·``gsd``도 nullable이다(독립 재검토 지적) — 처음 버전은 두
필드를 모든 kind에 non-nullable로 강제했는데, 이러면 ``report``·``camera_poses``
같이 공간 좌표계·픽셀 GSD가 원천적으로 없는 산출물의 생산자가 값을 지어내야
한다. "요청이 자기 증명서를 스스로 쓰는" 클래스의 결함(ADR-KSI-011 D3)과 같은
문제라 고쳤다. 대신 ``_CRS_REQUIRED_KINDS``/``_GSD_REQUIRED_KINDS``가
kind별로 null을 금지한다 — 공간 산출물(report/camera_poses 제외)은 crs가
필수이고, 그중 래스터 계열(ortho/dsm/dtm)만 gsd도 필수다. point_cloud(점
간격이지 픽셀 GSD가 아니다)·mesh(포인트클라우드+텍스처에서 유도된 근사 기하)·
tiles_3d(다중 LOD라 단일 해상도로 대표되지 않는다)는 gsd를 null로 둘 수 있다 —
이 셋의 "GSD가 고유 속성인가"는 근거가 갈리는 판단이라, 근거가 갈리면 생산자
쪽을 더 신뢰해 허용하는 쪽을 택했다.

계약 정본은 ``contracts/schemas/processing-artifact.v1.json``이고 이 모듈은 그
스키마의 Python 표현이다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ProcessingArtifactKind(StrEnum):
    """산출물 종류. ADR-KSI-003 원칙상 POINT_CLOUD/CAMERA_POSES가 원본,
    ORTHO/DSM/DTM/MESH/TILES_3D가 파생 서빙 계층, REPORT가 파생 분석 산출물이다 —
    실제 계보는 이 값이 아니라 ``lineage.authority``가 밝힌다."""

    POINT_CLOUD = "point_cloud"
    CAMERA_POSES = "camera_poses"
    ORTHO = "ortho"
    DSM = "dsm"
    DTM = "dtm"
    MESH = "mesh"
    TILES_3D = "tiles_3d"
    REPORT = "report"


class LineageAuthority(StrEnum):
    """INV-051 — 원본(raw capture를 직접 처리한 결과)인가 파생(원본에서 재생성한
    서빙 계층)인가."""

    SOURCE = "source"
    DERIVED = "derived"


# crs가 null일 수 없는 kind — report/camera_poses를 제외한 모든 공간 산출물.
_CRS_REQUIRED_KINDS = frozenset(
    {
        ProcessingArtifactKind.POINT_CLOUD,
        ProcessingArtifactKind.ORTHO,
        ProcessingArtifactKind.DSM,
        ProcessingArtifactKind.DTM,
        ProcessingArtifactKind.MESH,
        ProcessingArtifactKind.TILES_3D,
    }
)
# gsd가 null일 수 없는 kind — 픽셀 표본거리가 산출물 자체의 고유 속성인 래스터 계열만.
_GSD_REQUIRED_KINDS = frozenset(
    {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM, ProcessingArtifactKind.DTM}
)


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class ArtifactLineage(_CamelModel):
    """INV-051 강제 지점 — 원본/파생 계보(ADR-KSI-003)."""

    authority: LineageAuthority
    derived_from: list[str] = Field(default_factory=list)
    source_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _derived_requires_parents(self) -> ArtifactLineage:
        """authority=derived인 산출물은 derivedFrom 없이 성립하지 않는다.

        파생은 단방향이고 계보를 남긴다(ADR-KSI-003 결정 3) — "무엇에서 파생됐는가"
        없이 파생을 주장하면 그 원칙이 조용히 깨진다.
        """
        if self.authority is LineageAuthority.DERIVED and not self.derived_from:
            raise ValueError(
                "INV-051 위반: authority=derived 인 산출물은 derivedFrom 이 "
                "최소 1개 필요하다 — 파생 산출물은 원본 참조 없이 성립하지 않는다"
            )
        return self


class ArtifactAccuracy(_CamelModel):
    """측량 정확도(GCP/RMSE) 리포트 — ODM 경로에서는 이 모델 전체가 None이 된다."""

    gcp_count: int = Field(ge=0)
    rmse: float = Field(ge=0)
    report_uri: str = Field(min_length=1)


class ProcessingArtifact(_CamelModel):
    """재구성 산출물 1건 — ``contracts/schemas/processing-artifact.v1.json`` SSOT."""

    artifact_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    kind: ProcessingArtifactKind
    lineage: ArtifactLineage
    digest: str = Field(pattern=_DIGEST_PATTERN)
    format: str = Field(min_length=1)
    crs: str | None = Field(default=None, min_length=1)
    gsd: float | None = Field(default=None, gt=0)
    accuracy: ArtifactAccuracy | None = None

    @model_validator(mode="after")
    def _crs_and_gsd_required_by_kind(self) -> ProcessingArtifact:
        """공간 산출물은 crs를, 래스터 계열은 gsd를 null로 둘 수 없다.

        ``report``·``camera_poses``처럼 좌표계·픽셀 GSD가 원천적으로 없는
        산출물의 생산자가 값을 지어내지 않도록 두 필드를 nullable로 열어두되
        (모듈 docstring), 공간적으로 의미가 확실한 kind에서는 null을 막는다.
        """
        if self.kind in _CRS_REQUIRED_KINDS and self.crs is None:
            raise ValueError(
                f"{self.kind.value} 산출물은 crs 가 null 일 수 없다 — 공간 좌표계 "
                "없이 성립하는 산출물이 아니다(report/camera_poses 만 예외)"
            )
        if self.kind in _GSD_REQUIRED_KINDS and self.gsd is None:
            raise ValueError(
                f"{self.kind.value} 산출물은 gsd 가 null 일 수 없다 — 래스터 계열은 "
                "지상표본거리 없이 성립하는 산출물이 아니다"
            )
        return self


def processing_artifact_wire_dict(artifact: ProcessingArtifact) -> dict[str, Any]:
    """ProcessingArtifact의 wire 직렬화 규약.

    ``accuracy``·``crs``·``gsd``는 스키마상 nullable **필수** 필드다 — 다른
    optional 필드처럼 ``exclude_none``으로 생략하면 "값이 없다"와 "필드를 안 줬다"를
    소비자가 구분할 수 없다(모듈 docstring 참고). 그래서 이 셋만 예외로 두고
    항상 명시적으로 싣는다(값 또는 null).
    """
    data = artifact.model_dump(by_alias=True, mode="json", exclude={"accuracy", "crs", "gsd"})
    data["accuracy"] = (
        artifact.accuracy.model_dump(by_alias=True, mode="json")
        if artifact.accuracy is not None
        else None
    )
    data["crs"] = artifact.crs
    data["gsd"] = artifact.gsd
    return data
