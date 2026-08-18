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

계약 정본은 ``contracts/schemas/processing-artifact.v1.2.json``이고 이 모듈은 그
스키마의 Python 표현이다(v1.1·v1.0은 이 파일이 새 필드 없이도 여전히 유효하다는
것을 보이는 golden 비교용으로 보존한다 — coverage-report.v1/v1.1과 같은 관례).

## ``vertical_reference`` — v1.2, 그리고 왜 "없음"이 승격되지 않는가

이 산출물의 높이가 **어느 수직기준의 높이인가**를 산출물 자신이 싣는다. 이 값이
없던 동안 그 사실을 아는 유일한 자리는 비교 워커의 하드코딩 상수
(``comparison_worker._LEGACY_VERTICAL_DATUM``)였다 — 즉 리포트는 "이건 타원체고다"라고
말하면서 그걸 어떻게 아는지는 아무도 몰랐다. 두 epoch 가 같은 파이프라인에서
나오는 동안은 틀려도 상쇄돼 드러나지 않지만, 설계면처럼 **바깥에서 들어온
높이**와 비교하는 순간 지오이드고(한국 20~30m)가 조용히 섞인다.

**옛 산출물은 소급 승격되지 않는다.** 이 필드가 없는 v1.1 레코드는 journal
replay 에서 ``None``으로 재생된다(``extra="forbid"``는 *추가* 필드만 막는다).
그 ``None``에 기본 datum 을 채워 넣는 경로는 **의도적으로 없다** — 채우면
"기록된 사실"과 "우리가 가정한 값"이 같은 자리에 앉아 구분이 사라지고, 그
가정이 설계 대비 비교에 그대로 흘러든다. 소비자는 ``None``을 "수직기준이
기록되기 전에 등록된 산출물"로 읽고 fail-closed 해야 한다
(설계 대비 비교의 ``VERTICAL_REFERENCE_UNKNOWN``).

그래서 wire 규약도 대칭이다: 값이 있으면 실어서 **v1.2 문서**가 되고, 없으면
키째 빠져 **v1.1 문서**로 남는다(``auxiliary_files``·``RiskField.hazardType``과
같은 관례) — 문서의 버전 자체가 "생산자가 수직기준을 밝혔는가"를 말한다.
명시적 ``null``(v1.2 를 아는 생산자가 "모른다"고 밝힌 경우)도 계약상 유효하며
모델은 그것을 ``None``으로 읽는다.

## ``auxiliary_files`` — mesh-multi-file-artifact-persistence

산출물 하나가 파일 여러 개(메시의 .obj+.mtl+텍스처)로 이뤄질 때, ``digest``는
이미 그 전부를 정렬된 (경로, 내용) 결합으로 해싱한 값이다
(``ksi_processing_controller.odm.digest_archive_entries``와 동형 — 이 필드
신설 이전부터 그랬다, risk mesh-digest-ignores-textures 참고). 이 필드는 digest
계산식을 바꾸지 않고, 그 파일들 중 주 파일(``objectKey``가 가리키는 파일) 외
나머지의 저장 위치를 알려주는 **basename 목록**일 뿐이다 — 빈 배열(기본값)이면
파일 하나짜리 산출물(v1.0과 동일 동작)이다.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.vertical_reference import VerticalReference

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
# contracts/schemas/processing-artifact.v1.1.json 의 auxiliaryFiles.items.pattern 과
# 정확히 같은 문자열(services/core/src/ksi_core/identifiers.py의
# PATH_SAFE_IDENTIFIER_PATTERN 과도 동형) — event-contracts 는 services/core 를
# 참조할 수 없는 계층이라(반대 방향 의존) 값을 여기 다시 적는다. 이 필드가
# 이 검증 없이 통과하면(reviewer 지적 C1, 2026-08-08) 등록은 성공하고
# (build_processing_artifact_object_key 가 다운로드 시점에만 거부해) 그 산출물이
# 영구히 다운로드 불가능한 상태로 durable 하게 남는다 — 등록 시점에 막아야 한다.
_BASENAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


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
    """측량 정확도 리포트 — ODM 경로에서는 이 모델 전체가 None이 된다.

    **``rmse`` 는 절대정확도가 아니다**(INV-024). GCP 로 피팅한 뒤의 잔차, 즉 "쓴
    점들에 얼마나 잘 맞췄나"이지 "쓰지 않은 지점에서 얼마나 틀리나"가 아니다. 피팅에
    쓴 점의 잔차로 절대정확도를 주장하는 것은 자기 답안으로 자기 채점을 하는 것과
    같아서, 독립 검사점(checkpoint — 피팅에 쓰지 않고 남겨 둔 측량점) 없이는 절대
    RMSE 를 말할 수 없다. Terra 수용 기준의 "GCP 와 CP 가 분리된다"가 이 뜻이다.

    그래서 절대정확도 주장은 ``checkpoint_count``·``checkpoint_rmse_m`` 쌍으로만
    표현되고, 둘은 함께 있거나 함께 없어야 한다. 검사점 없이 절대 RMSE 를 싣는
    wire 는 이 계약에서 **표현 자체가 불가능**하다 — 그것이 INV-024 의 강제 지점이다.

    **경계(중요)**: 이 게이트가 강제하는 것은 *형식*이지 숫자의 참이 아니다. Core 는
    산출물 바이트를 읽지 않으므로(openapi-core.yaml 의 등록 계약 명시) 생산자가 신고한
    검사점 수·잔차가 사실인지 확인할 방법이 없다 — ``verticalReference`` 와 같은
    성질의 **귀속(provenance)이지 관측이 아니다**. 신고값을 사실로 올리려면 현장
    측량 검사점 좌표와 산출물을 대조하는 별도 경로가 필요하고, 그건 측량기·현장
    작업이다. 이 docstring 을 지우지 말 것 — 없으면 다음 사람이 이 게이트를
    "정확도가 검증됐다"로 읽는다.
    """

    gcp_count: int = Field(ge=0)
    rmse: float = Field(ge=0)
    report_uri: str = Field(min_length=1)
    checkpoint_count: int = Field(default=0, ge=0)
    checkpoint_rmse_m: float | None = None

    @model_validator(mode="after")
    def _rmse_must_be_finite(self) -> ArtifactAccuracy:
        """``Field(ge=0)``는 ``+inf``를 걸러내지 않는다 — ``inf >= 0``은 참이라 통과한다.

        JSON 자체도 리터럴 ``Infinity``/``NaN``을 ``json.loads`` 기본값으로 허용해
        wire 상에서 그대로 들어올 수 있다. rmse는 측량 정확도의 실측값이라 non-finite는
        "정확도를 측정했다"는 주장과 모순된다 — 등록 시점에 거부한다.
        """
        if not math.isfinite(self.rmse):
            raise ValueError(f"rmse 는 finite 여야 한다 (got {self.rmse!r})")
        return self

    @model_validator(mode="after")
    def _absolute_rmse_needs_independent_checkpoints(self) -> ArtifactAccuracy:
        """INV-024 — 검사점과 그 잔차는 함께 있거나 함께 없다.

        한쪽만 실리면 둘 다 거부한다. ``checkpoint_rmse_m`` 만 있으면 근거 없는 절대
        정확도 주장이고, ``checkpoint_count`` 만 있으면 "검사점을 뒀다"는 말만 남아
        아무것도 강제하지 못하는 장식이 된다.
        """
        has_count = self.checkpoint_count > 0
        has_rmse = self.checkpoint_rmse_m is not None
        if has_rmse and not has_count:
            raise ValueError(
                "INV-024 위반: checkpointRmseM 은 독립 검사점 없이 주장할 수 없다 "
                f"(checkpointCount={self.checkpoint_count})"
            )
        if has_count and not has_rmse:
            raise ValueError(
                f"INV-024 위반: checkpointCount={self.checkpoint_count} 인데 "
                "checkpointRmseM 이 없다 — 검사점 잔차 없이는 정확도 주장이 성립하지 않는다"
            )
        if self.checkpoint_rmse_m is not None and not math.isfinite(self.checkpoint_rmse_m):
            raise ValueError(
                f"checkpointRmseM 은 finite 여야 한다 (got {self.checkpoint_rmse_m!r})"
            )
        if self.checkpoint_rmse_m is not None and self.checkpoint_rmse_m <= 0:
            # 0 도 거부한다 — 절대오차 0m 은 물리적으로 불가능한 주장이고, 그것을
            # 받아주면 "검사점을 뒀다"는 형식만 갖춘 완벽 정확도 신고가 통과한다.
            raise ValueError(
                f"checkpointRmseM 은 양수여야 한다 (got {self.checkpoint_rmse_m!r})"
            )
        return self


class ProcessingArtifact(_CamelModel):
    """재구성 산출물 1건 — SSOT 는 ``contracts/schemas/processing-artifact.v1.2.json``
    (검사점을 실으면 ``v1.3.json``)."""

    artifact_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    kind: ProcessingArtifactKind
    lineage: ArtifactLineage
    digest: str = Field(pattern=_DIGEST_PATTERN)
    format: str = Field(min_length=1)
    crs: str | None = Field(default=None, min_length=1)
    gsd: float | None = Field(default=None, gt=0)
    accuracy: ArtifactAccuracy | None = None
    auxiliary_files: tuple[Annotated[str, Field(pattern=_BASENAME_PATTERN)], ...] = Field(
        default_factory=tuple
    )
    #: v1.2 — 이 산출물 높이의 수직기준 + 근거 + 귀속. ``None``은 "아직 기록되기
    #: 전에 등록된 산출물"이고 **그 상태 그대로 남는다**(모듈 docstring).
    vertical_reference: VerticalReference | None = None

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
    if artifact.accuracy is not None:
        accuracy = artifact.accuracy.model_dump(by_alias=True, mode="json")
        if artifact.accuracy.checkpoint_rmse_m is None:
            # **v1.3 과 v1.2 의 경계** — verticalReference 와 같은 관례다. 독립
            # 검사점을 주장하지 않는 정확도 리포트는 그 사실을 0/null 로 싣지 않고
            # 키째 빠져 v1.2 문서로 남는다. 검사점을 실은 리포트만 v1.3 이고,
            # v1.2 는 그것을 거부한다(additionalProperties:false) — 이행이 실제로
            # 일어났음이 두 방향에서 확인된다.
            accuracy.pop("checkpointCount", None)
            accuracy.pop("checkpointRmseM", None)
        data["accuracy"] = accuracy
    else:
        data["accuracy"] = None
    data["crs"] = artifact.crs
    data["gsd"] = artifact.gsd
    if not artifact.auxiliary_files:
        # 빈 배열은 "파일 하나짜리 산출물"의 기본값이다 — v1.0 소비자와의 wire
        # 호환을 위해 키째 뺀다(RiskField의 hazardType 과 같은 관례).
        data.pop("auxiliaryFiles", None)
    if artifact.vertical_reference is None:
        # **여기가 v1.2와 v1.1의 경계다.** 수직기준을 모르는 산출물은 그 사실을
        # null 로 주장하지 않고 v1.1 문서로 남는다 — v1.1 소비자(와 v1.1 골든
        # 스키마)가 옛 산출물을 그대로 계속 읽는다. 반대로 값이 있으면 실려서
        # 그 문서는 v1.2이고 v1.1 은 그것을 거부한다(additionalProperties:false).
        # "이행"이 실제로 일어났다는 것이 두 방향 모두에서 확인된다.
        data.pop("verticalReference", None)
    return data
