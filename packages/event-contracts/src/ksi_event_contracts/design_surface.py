"""DesignSurface — 설계 기준면 자산 1건. **선언(주장)과 관측(사실)을 이름으로 가른다.**

## 이 계약이 막는 것

사용자가 "EPSG:5186" 이라고 적었다고 그 파일이 EPSG:5186 인 것은 아니다. 업로드
폼의 값과 파일 안의 값은 **다른 종류의 사실**인데, 한 평면에 섞어 담으면 나중에
아무도 어느 쪽을 보고 있는지 알 수 없다. 그래서 두 계층을 필드 이름으로 분리한다:

- :class:`DesignSurfaceDeclared` — 전부 업로더의 주장. 아무도 확인하지 않았다.
- :class:`DesignSurfaceObserved` — 전부 신뢰 경로(워커)가 **바이트를 읽어 잰 값**.

``verticalReference`` 가 ``declared`` 안에만 있는 것이 이 분리의 시금석이다.
GeoTIFF 는 수직기준을 신뢰성 있게 담지 않으므로 **관측할 수 없다** — 계약에서의
위치 자체가 "이건 주장이다"를 말한다. 파일이 compound CRS 로 수직 CRS 를 갖고
있으면 그 코드는 ``observed.verticalCrsEpsg`` 로 관측되고, 선언과 모순되면
거부된다(``vertical_reference.vertical_datum_from_epsg`` + ``family_of``).

## 상태기계 — ``SEALED`` 는 사실이 아니라 **주장**이다

.. code-block:: text

    REGISTERED  ──seal──▶  SEALED  ──관측 대조──▶  VERIFIED
                                   └────────────▶  REJECTED

``services/core`` 의 ``source_media`` 3단(register → seal → verify)을 그대로
본뜬다. 그 모듈에서 실제로 무슨 일이 일어나는지 확인한 결과가 이 이름들의 근거다:

- ``SourceMediaStore.seal()`` 은 **스토리지 바이트를 한 번도 읽지 않는다.**
  등록된 신고값들로 매니페스트 digest 를 계산해 원장에 굳힐 뿐이다.
- 바이트를 읽는 것은 오직 ``SourceMediaStore.verify()`` 경로다 — 워커가 실측을
  보고하고 **Core 가** 신고값과 대조해 판정한다.

그래서 여기서도 **"클라이언트가 presigned PUT 을 완료했다"는 이유만으로 Core 의
durable 상태를 '올라갔다/검증됐다'로 만들지 않는다.** :attr:`DesignSurfaceStatus.SEALED`
는 "업로드를 마쳤다고 클라이언트가 주장했고, 그래서 검증 대기 큐에 들어갔다"는
뜻이지 그 이상이 아니다. 이 계약에서 ``SEALED`` 인 설계면은 **conformance 요청의
입력이 될 수 없다** — :attr:`DesignSurfaceStatus.VERIFIED` 만이 입력 자격이다.

``UPLOADED`` 라는 이름을 쓰지 않은 이유가 정확히 이것이다. 그 단어는 "파일이 거기
있다"는 사실을 주장하지만 Core 는 그것을 확인한 적이 없다(Core 는 객체 바이트를
중계하지 않는다, ADR-KSI-010 §1). ``SEALED`` 는 "더 이상 내용을 바꾸지 않기로
봉인했다"는 **원장 쪽 사실**만 말하고, 파일에 대해서는 아무것도 주장하지 않는다.

## VERIFIED 는 한 번만

설계면은 현장 재사용 자산이라 비교할 때마다 재측정하지 않는다. 업로드 직후 1회
검증해 굳히고, 이후 실행은 **다운로드한 바이트의 sha256 == ``observed.sha256``**
만 확인한다(값싸고, 스토리지 교체·손상을 잡는다). 그래서 ``VERIFIED``·``REJECTED``
는 둘 다 종단이다 — 거부된 설계면의 복구 경로는 "되돌리기"가 아니라 **새 revision
으로 다시 등록**이다(원본 사진 번들과 달리 설계면은 다시 올리는 비용이 낮고,
되돌리기를 허용하면 "검증됐다"의 뜻이 흐려진다).

## 관측 모델은 판정하지 않는다

:class:`DesignSurfaceObserved` 는 회전 래스터·역전 bounds 같은 이상한 값도
**담을 수 있다**. 담지 못하게 막으면 그 파일을 만난 워커가 typed 거부를 보고하는
대신 계약 예외로 죽고, 사용자는 "왜 실패했는지"를 못 받는다(``SourceMediaMeasurement``
가 판정 필드를 갖지 않는 것과 같은 자리). 판정은 Core 의 대조 단계가 한다.

예외는 **산술적으로 불가능한 조합**뿐이다 — ``finiteCellCount`` 가 전체 셀 수보다
큰 관측은 관측이 아니라 오류다(``ChangeDetectionResult`` 가 ``candidateCount >
pointCount`` 를 거부하는 것과 같은 근거).
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.vertical_reference import VerticalReference, VerticalReferenceSource

#: 파일 내용 해시의 **원시 16진** 표기. 이 저장소는 두 표기를 이름으로 구분한다 —
#: ``digest`` 는 ``sha256:`` 접두사가 붙은 산출물 참조용(``ProcessingArtifact.digest``),
#: ``sha256`` 은 접두사 없는 파일 해시(``SourceMediaFileClaim.sha256``)다. 설계면은
#: 업로더가 ``sha256sum`` 결과를 그대로 적어 넣는 자리라 후자를 쓴다.
SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


class DesignSurfaceStatus(StrEnum):
    """설계면 자산의 생애 — **이름 하나하나가 "누가 무엇을 확인했는가"를 말한다.**"""

    #: 선언 메타데이터가 원장에 기록되고 presigned PUT 이 발급됐다. 파일에 대해
    #: 아는 것은 아직 아무것도 없다.
    REGISTERED = "REGISTERED"
    #: **클라이언트가 업로드 완료를 주장했고, Core 는 그 주장을 기록했다.**
    #: 검증 대기 큐에 들어간 상태이며, Core 가 증명한 사실은 "더 이상 내용을 바꾸지
    #: 않기로 봉인했다"뿐이다 — 파일이 실제로 스토리지에 있는지, 그 내용이 선언과
    #: 같은지는 **아무도 확인하지 않았다**. 이 상태의 설계면으로는 비교를 시작할 수
    #: 없다(모듈 docstring "SEALED 는 사실이 아니라 주장이다").
    SEALED = "SEALED"
    #: 신뢰 경로가 실제 바이트를 읽어 측정했고, 그 관측이 선언과 전부 대조를
    #: 통과했다. **이때부터만** conformance 요청의 입력이 된다. 종단.
    VERIFIED = "VERIFIED"
    #: 대조 실패. ``rejectionReason`` 에 typed verdict 가 남는다. 종단 —
    #: 복구는 되돌리기가 아니라 새 revision 등록이다.
    REJECTED = "REJECTED"


#: SSOT — 허용된 상태 전이. Core 의 저장소(``design_surfaces.py``)와 그 journal
#: 재생이 **같은 표**를 태운다. 자기 자신으로의 전이(멱등 재호출)는 전이가 아니라
#: 무기록 재발급이라 여기 없다(``source_media.seal`` 의 ``ALREADY_SEALED`` 관습).
DESIGN_SURFACE_TRANSITIONS: dict[DesignSurfaceStatus, frozenset[DesignSurfaceStatus]] = {
    DesignSurfaceStatus.REGISTERED: frozenset({DesignSurfaceStatus.SEALED}),
    DesignSurfaceStatus.SEALED: frozenset(
        {DesignSurfaceStatus.VERIFIED, DesignSurfaceStatus.REJECTED}
    ),
    DesignSurfaceStatus.VERIFIED: frozenset(),
    DesignSurfaceStatus.REJECTED: frozenset(),
}

# 표 완전성 자가검증 — 새 상태를 추가하고 이 표를 안 고치면 import 시점에 드러난다
# (``vertical_reference._DATUM_FAMILY`` 와 같은 관습). 조용한 기본값을 만들지 않는
# 것이 핵심이다: 빠진 상태가 "아무 데로도 못 간다"로 취급되면 그 자산은 영구히 멈춘다.
if set(DESIGN_SURFACE_TRANSITIONS) != set(DesignSurfaceStatus):
    raise AssertionError("DESIGN_SURFACE_TRANSITIONS 가 DesignSurfaceStatus 전 멤버를 덮지 않는다")


def can_transition(current: DesignSurfaceStatus, following: DesignSurfaceStatus) -> bool:
    """``current`` 에서 ``following`` 으로 가도 되는가 — 판정의 정본."""
    return following in DESIGN_SURFACE_TRANSITIONS[current]


def is_terminal(status: DesignSurfaceStatus) -> bool:
    """더 갈 곳이 없는 상태인가(``VERIFIED``·``REJECTED``)."""
    return not DESIGN_SURFACE_TRANSITIONS[status]


class DesignSurfaceDeclared(_CamelModel):
    """업로더의 주장 한 벌 — **이 안의 값은 어느 것도 확인되지 않았다.**

    이름이 ``declared`` 인 것이 이 모델의 전부다. 소비자는 이 블록을 읽을 때
    "사용자가 그렇게 적었다"까지만 알고, "그래서 파일이 그렇다"로 읽으면 안 된다.
    """

    #: 사용자가 주장한 좌표계(예: ``"EPSG:5186"``). 관측된 ``observed.crs`` 와
    #: 정규화 후 다르면 ``CRS_DECLARATION_MISMATCH`` 로 거부된다 — 정규화
    #: (``ksi_geo_spatial.crs.normalise_crs``)는 Core 의 대조 단계가 한다.
    crs: str = Field(min_length=1)
    #: 평면 길이 단위. ``meter`` 만 받는다 — 피트 단위 설계도면이 미터로 취급되면
    #: 체적이 조용히 35배 틀린다. 확장이 필요하면 그때 Literal 을 늘린다.
    length_unit: Literal["meter"] = "meter"
    #: 업로더가 계산해 적은 파일 해시. 관측값과 다르면 ``DIGEST_MISMATCH``.
    sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    #: 이 설계면의 높이가 어느 수직기준인가 + **왜 그렇게 아는가**.
    #: ``source`` 는 ``VerticalReferenceSource.USER_DECLARED`` 여야 한다(아래 validator).
    vertical_reference: VerticalReference

    @model_validator(mode="after")
    def _vertical_reference_is_a_user_claim(self) -> DesignSurfaceDeclared:
        """``declared`` 블록에 파이프라인 귀속이 앉을 수 없다.

        이 블록의 뜻은 "업로더가 그렇게 주장했다"이고, ``PIPELINE_DECLARED`` 는
        "우리 처리 파이프라인이 자기 동작을 근거로 귀속했다"는 **다른 종류의
        주장**이다. 둘을 같은 자리에 담으면 소비자가 근거의 성질을 구분할 수 없다
        — 나중에 "사용자 선언 설계면은 추가 확인" 같은 정책을 붙일 자리도 사라진다.

        (M4-B 에서 IFC 를 래스터화해 설계면을 만들게 되면 그 산출물의 수직기준은
        여전히 도면·업로더에서 오지 우리가 측정하는 값이 아니다 — 그래도 귀속이
        파이프라인으로 바뀌어야 한다면 그때 이 계약을 명시적으로 확장한다.)
        """
        if self.vertical_reference.source is not VerticalReferenceSource.USER_DECLARED:
            raise ValueError(
                "declared.verticalReference.source 는 user_declared 여야 한다 "
                f"(got {self.vertical_reference.source.value}) — 이 블록은 업로더의 "
                "주장이지 파이프라인의 귀속이 아니다"
            )
        return self


class DesignSurfaceObserved(_CamelModel):
    """신뢰 경로가 **파일을 열어 실제로 잰 값** 한 벌 — 판정은 들어 있지 않다.

    ``measuredBy`` 는 "누가 쟀는가"이고 ``measuredAt`` 은 "언제 쟀는가"다. 어느
    필드도 "통과했다"를 말하지 않는다 — 대조는 Core 가 하고, 그 결과는
    :class:`DesignSurface` 의 ``status`` 에 산다(``source_media`` 의
    ``SourceMediaMeasurement`` 와 같은 경계).
    """

    #: 읽은 바이트 전체의 해시. ``declared.sha256`` 과의 대조가 이 관측의 앵커다.
    sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    #: 파일이 실제로 들고 있는 수평 CRS(정규화 전 원문 표기).
    crs: str = Field(min_length=1)
    #: compound CRS 의 수직 성분(EPSG). 대부분의 DEM 에는 **없다**(null 이 정상) —
    #: 있을 때만 선언과 대조해 모순이면 거부한다. "없음"은 선언을 뒷받침하지도
    #: 반박하지도 않는다.
    vertical_crs_epsg: int | None = Field(default=None, gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    #: 밴드 수. DEM 은 1 이어야 한다(그 판정은 Core 가 ``UNSUPPORTED_BAND_COUNT``
    #: 로 내린다 — 관측은 3밴드 정사영상을 잘못 올린 사실도 그대로 담는다).
    band_count: int = Field(ge=1)
    #: 화소 자료형 원문(예: ``"float32"``).
    dtype: str = Field(min_length=1)
    #: 파일이 선언한 nodata 값. 지정하지 않은 래스터면 null.
    #: **NaN 은 이 필드로 표현하지 않는다** — JSON 에 NaN 이 없어 실으면 계약이
    #: 왕복하지 못한다. 그 경우는 아래 ``nodata_is_nan`` 이 말한다.
    nodata: float | None = None
    #: 파일의 nodata 가 NaN 인가. ``nodata`` 를 null 로만 적으면 "nodata 를 지정하지
    #: 않은 파일"과 "NaN 을 nodata 로 쓰는 파일"이 같은 값이 돼, 차분 결과의
    #: 무효 셀 해석이 조용히 갈린다.
    nodata_is_nan: bool = False
    #: 화소 크기(m). 부호 없는 크기다 — GeoTIFF affine 의 y 항은 통상 음수지만,
    #: 여기 싣는 것은 그 **크기**다(방향은 ``transform`` 이 그대로 들고 있다).
    pixel_size_x_m: float = Field(gt=0.0)
    pixel_size_y_m: float = Field(gt=0.0)
    #: rasterio ``Affine`` 순서 그대로 ``(a, b, c, d, e, f)`` — 즉
    #: (x 화소크기, 행 회전, 좌상단 x, 열 회전, y 화소크기(통상 음수), 좌상단 y).
    #: 여섯 개 고정이며 ``to_gdal()`` 순서가 아니다(둘은 순서가 다르다).
    transform: tuple[float, float, float, float, float, float]
    bounds_min_x: float
    bounds_min_y: float
    bounds_max_x: float
    bounds_max_y: float
    #: nodata·NaN 이 아닌 셀 수. 0 이면 그 파일에는 표고가 하나도 없다
    #: (``NO_FINITE_CELLS``) — 0 을 담을 수 있어야 그 거부 사유를 원장이 설명한다.
    finite_cell_count: int = Field(ge=0)
    measured_at: datetime
    measured_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _measurement_is_internally_possible(self) -> DesignSurfaceObserved:
        """관측이 **산술적으로 성립하는가**만 본다 — 파일이 좋은지는 보지 않는다.

        ``finiteCellCount`` 가 전체 셀 수를 넘는 관측은 "이상한 파일"이 아니라
        측정 자체의 오류다(``ChangeDetectionResult`` 의 ``candidateCount >
        pointCount`` 와 같은 자리). 회전 변환·역전 bounds 처럼 "파일이 우리 전제와
        다른" 경우는 여기서 막지 않는다 — 그건 Core 가 typed verdict 로 거부해야
        사용자에게 이유가 전달된다(모듈 docstring).
        """
        for name, value in (
            ("pixelSizeXM", self.pixel_size_x_m),
            ("pixelSizeYM", self.pixel_size_y_m),
            ("boundsMinX", self.bounds_min_x),
            ("boundsMinY", self.bounds_min_y),
            ("boundsMaxX", self.bounds_max_x),
            ("boundsMaxY", self.bounds_max_y),
            *((f"transform[{i}]", v) for i, v in enumerate(self.transform)),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} 은 finite 여야 한다 (got {value!r})")
        if self.nodata is not None and not math.isfinite(self.nodata):
            raise ValueError(
                "nodata 는 finite 이거나 null 이어야 한다 — NaN nodata 는 "
                "nodataIsNan=true 로 싣는다(JSON 에 NaN 이 없다)"
            )
        if self.nodata_is_nan and self.nodata is not None:
            raise ValueError(
                "nodataIsNan=true 인데 nodata 에도 값이 있다 — 한 래스터의 nodata 는 하나다"
            )
        if self.measured_at.tzinfo is None:
            raise ValueError("measuredAt 은 tz-aware(offset 포함) 여야 한다")
        if self.finite_cell_count > self.width * self.height:
            raise ValueError(
                f"finiteCellCount({self.finite_cell_count}) 가 전체 셀 수"
                f"({self.width * self.height}) 보다 클 수 없다 — 측정이 스스로 모순이다"
            )
        return self


class DesignSurface(_CamelModel):
    """설계 기준면 자산 1건 — ``contracts/schemas/design-surface.v1.json`` 왕복 대상."""

    schema_version: Literal["1.0"] = "1.0"
    design_surface_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    #: 사람이 읽는 이름(예: ``"A공구 계획고"``).
    name: str = Field(min_length=1)
    #: 도면 개정 표기(예: ``"Rev.C"``). 같은 현장에 여러 판이 공존하므로, 어느 판을
    #: 기준으로 잔량을 냈는지가 리포트에서 되짚어져야 한다.
    revision: str = Field(min_length=1)
    #: 지금은 GeoTIFF 뿐이다 — IFC 유래 표면은 M4-B 에서 이 Literal 을 늘린다.
    format: Literal["geotiff"] = "geotiff"
    declared: DesignSurfaceDeclared
    #: 아직 아무도 재지 않았으면 null. ``REJECTED`` 인데 null 인 경우도 정상이다 —
    #: 파일을 열지 못했으면(``UNREADABLE_RASTER``) 관측 자체가 없다.
    observed: DesignSurfaceObserved | None = None
    status: DesignSurfaceStatus
    #: ``REJECTED`` 일 때의 typed verdict(그리고 사람 말 사유). 그 외 상태에서는 null.
    rejection_reason: str | None = None
    registered_at: datetime
    registered_by: str = Field(min_length=1)
    #: 클라이언트가 업로드 완료를 **주장한** 시각이다 — 파일을 확인한 시각이 아니다.
    sealed_at: datetime | None = None
    #: 관측이 선언과 전부 대조를 통과한 시각. 이 값이 있는 설계면만 비교에 쓸 수 있다.
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def _status_matches_the_evidence(self) -> DesignSurface:
        """상태가 **그 상태를 뒷받침하는 근거와 함께** 있는가.

        여기서 막는 것은 "VERIFIED 인데 관측이 없다" 같은, 어느 화면에서도
        이상해 보이지 않는 조합이다. 특히 ``VERIFIED`` 는 관측 해시가 선언 해시와
        같아야 성립한다 — 그 둘이 다른데 VERIFIED 인 레코드는 (원장 조작이든 버그든)
        "검증됐다"의 뜻을 통째로 무너뜨린다. 문자열 비교라 정규화가 필요 없어
        계약이 직접 볼 수 있는 유일한 대조이기도 하다(CRS 대조는 정규화가 필요해
        Core 의 몫이다).
        """
        for name, value in (
            ("registeredAt", self.registered_at),
            ("sealedAt", self.sealed_at),
            ("verifiedAt", self.verified_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} 은 tz-aware(offset 포함) 여야 한다")

        if self.status is DesignSurfaceStatus.REGISTERED:
            self._require_absent(sealed=True, verified=True, observed=True, reason=True)
        elif self.status is DesignSurfaceStatus.SEALED:
            self._require_sealed()
            self._require_absent(verified=True, observed=True, reason=True)
        elif self.status is DesignSurfaceStatus.VERIFIED:
            self._require_sealed()
            if self.verified_at is None:
                raise ValueError("status=VERIFIED 인데 verifiedAt 이 없다")
            if self.observed is None:
                raise ValueError(
                    "status=VERIFIED 인데 observed 가 없다 — 아무도 파일을 읽지 "
                    "않았는데 '관측이 선언과 일치했다'고 말할 수 없다"
                )
            if self.observed.sha256 != self.declared.sha256:
                raise ValueError(
                    "status=VERIFIED 인데 observed.sha256 과 declared.sha256 이 "
                    f"다르다({self.observed.sha256} != {self.declared.sha256}) — "
                    "대조를 통과하지 않은 검증은 검증이 아니다"
                )
            self._require_absent(reason=True)
        else:  # REJECTED
            self._require_sealed()
            self._require_absent(verified=True)
            if not (self.rejection_reason or "").strip():
                raise ValueError(
                    "status=REJECTED 인데 rejectionReason 이 비어 있다 — 사용자는 "
                    "무엇을 고쳐 다시 올려야 하는지 알 수 없다"
                )

        if self.sealed_at is not None and self.sealed_at < self.registered_at:
            raise ValueError("sealedAt 이 registeredAt 보다 앞선다")
        if (
            self.verified_at is not None
            and self.sealed_at is not None
            and self.verified_at < self.sealed_at
        ):
            raise ValueError("verifiedAt 이 sealedAt 보다 앞선다")
        return self

    def _require_sealed(self) -> None:
        if self.sealed_at is None:
            raise ValueError(
                f"status={self.status.value} 인데 sealedAt 이 없다 — 봉인 전에는 "
                "대조 대상 내용이 확정되지 않는다"
            )

    def _require_absent(
        self,
        *,
        sealed: bool = False,
        verified: bool = False,
        observed: bool = False,
        reason: bool = False,
    ) -> None:
        """그 상태에서 **있으면 안 되는** 근거들을 한자리에서 막는다."""
        if sealed and self.sealed_at is not None:
            raise ValueError(f"status={self.status.value} 인데 sealedAt 이 채워져 있다")
        if verified and self.verified_at is not None:
            raise ValueError(f"status={self.status.value} 인데 verifiedAt 이 채워져 있다")
        if observed and self.observed is not None:
            raise ValueError(
                f"status={self.status.value} 인데 observed 가 채워져 있다 — 관측은 "
                "검증 판정과 함께만 원장에 들어온다"
            )
        if reason and self.rejection_reason is not None:
            raise ValueError(
                f"status={self.status.value} 인데 rejectionReason 이 채워져 있다"
            )

    @property
    def is_usable_for_conformance(self) -> bool:
        """설계 대비 비교의 입력이 될 수 있는가 — ``VERIFIED`` 하나뿐이다.

        호출부가 ``status == "VERIFIED"`` 를 각자 적으면 언젠가 한 곳이
        ``in ("VERIFIED", "SEALED")`` 로 느슨해지고, 그 순간 **아무도 읽어보지 않은
        파일**로 잔량 숫자가 나온다.
        """
        return self.status is DesignSurfaceStatus.VERIFIED


__all__ = [
    "DESIGN_SURFACE_TRANSITIONS",
    "SHA256_HEX_PATTERN",
    "DesignSurface",
    "DesignSurfaceDeclared",
    "DesignSurfaceObserved",
    "DesignSurfaceStatus",
    "can_transition",
    "is_terminal",
]
