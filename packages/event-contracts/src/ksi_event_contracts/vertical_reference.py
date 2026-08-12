"""수직기준 참조 — "이 높이가 어느 기준의 높이이고, 그걸 왜 아는가".

## 문제

``VolumeChangeReport.vertical_datum`` 은 문자열 하나다. 그 값의 출처는 비교
워커의 하드코딩 상수(``comparison_worker._LEGACY_VERTICAL_DATUM``)였지 산출물의
사실이 아니었다. 즉 리포트는 "이 높이는 타원체고다"라고 **말하지만 그걸 어떻게
아는지는 아무도 모른다.** M1 처럼 두 epoch 가 같은 파이프라인에서 나오는 동안은
틀려도 상쇄돼 드러나지 않지만, 설계면처럼 **바깥에서 들어온 높이**와 비교하는
순간 20~30m(한국의 지오이드고)가 조용히 섞인다.

그래서 datum 값 하나가 아니라 **datum + 근거 + 귀속**을 한 묶음으로 싣는다.

## source 이름을 왜 이렇게 골랐나 (``VerticalReferenceSource``)

초안은 ``PRODUCER_MEASURED`` / ``USER_DECLARED`` 였고, 이는 **범주 오류**라서
버렸다. :class:`VerticalDatum` 의 ``ELLIPSOIDAL_NATIVE`` 는 그 docstring 이
명시하듯 "의도적으로 선택한 기준"이 아니라 **변환을 하지 못해 남은 상태**다.
재구성 파이프라인은 높이를 *측정*해서 "이건 타원체고다"라고 판정한 적이 없다 —
RTK 가 준 타원체고를 변환 없이 그대로 흘려보냈을 뿐이고, 우리가 아는 것은
**파이프라인이 무엇을 하지 않았는가**뿐이다. 그걸 ``MEASURED`` 라고 부르면
"관측된 사실"이라는 신뢰도가 근거 없이 붙는다.

관측이 아니라는 점은 사용자 쪽도 같다. GeoTIFF 는 수직기준을 신뢰성 있게 담지
않으므로(compound CRS 가 있을 때만 부분적으로 관측 가능), 업로더가 적어낸 값도
파일에서 확인된 사실이 아니다. **이 계약에 담기는 값은 어느 쪽이든 관측이 아니라
귀속(provenance)이다.** 그래서 두 멤버를 ``_DECLARED`` 로 대칭시킨다:

- :attr:`VerticalReferenceSource.PIPELINE_DECLARED` — 산출물을 만든 처리
  파이프라인이 **자기가 무엇을 했는지**를 근거로 귀속한 값. 근거가 코드·설정에
  있어 감사 가능하고 같은 파이프라인의 모든 산출물에 균일하게 적용된다.
- :attr:`VerticalReferenceSource.USER_DECLARED` — 업로더가 주장한 값. 자동으로
  확인할 방법이 없고 파일마다 다르다.

둘 다 주장이지만 **틀렸을 때 어디를 고쳐야 하는지가 다르다**(파이프라인 설정 vs
그 파일의 등록 정보). 나중에 "사용자 선언 설계면은 추가 확인을 요구한다" 같은
정책을 붙일 자리도 여기다.

**관측(observed)은 이 enum 에 넣지 않는다.** 파일에서 실제로 읽어낸 사실은
별도 ``observed`` 계층(``DesignSurface.observed.verticalCrsEpsg``)에 살고,
선언과 모순되면 거부된다 — 계약 위치 자체가 "이건 주장이다"를 말하게 둔다.

## 왜 이 모듈이 geo-spatial 이 아니라 계약 패키지에 사는가

``VerticalDatum`` 은 원래 :mod:`ksi_geo_spatial.vertical` 에 있었다. 그런데
이 판정들의 **소비자가 Core(control plane)** 다 — 설계 대비 비교 요청을 만들 때
"두 수직기준이 비교 가능한가"를 계산 전에 강제해야 한다. ``ksi-geo-spatial`` 은
pyproj·rasterio(GDAL) 를 물고 있어 Core 가 그걸 의존하면 control plane 에
래스터 스택이 딸려온다. 이 저장소가 ``comparison_policy`` 와
``exceeds_revisit_threshold`` 를 계약 패키지로 끌어올린 것과 **같은 이유이자 같은
해법**이다(``comparison_policy.py`` 모듈 docstring: "규칙이든 상수든, 두 소비자가
있으면 정본은 하나여야 한다").

그래서 **정본은 여기**이고, :mod:`ksi_geo_spatial.vertical` 은 이 이름들을
그대로 재수출한다(기존 import 경로는 전부 살아 있다). 지오이드 격자 보간처럼
실제 측지 연산이 필요한 것은 계속 geo-spatial 의 몫이다 — 이 모듈에는
순수 표·순수 판정만 둔다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

from ksi_event_contracts._base import _CamelModel


class VerticalDatum(StrEnum):
    """산출물이 어느 수직기준인지 — wire 계약에 실리는 값.

    ``ELLIPSOIDAL_NATIVE`` 는 "재구성 엔진이 낸 타원체고를 변환 없이 그대로
    쓴다"는 뜻이다. ``ELLIPSOIDAL`` 과 굳이 나눈 이유는, 전자가 **의도적으로
    선택한 기준**이 아니라 **변환을 하지 못해 남은 상태**임을 소비자가 구분할
    수 있어야 하기 때문이다 — 나중에 격자가 확보되면 이 값이 남아 있는
    산출물이 곧 재처리 대상 목록이 된다.

    두 값의 이 차이는 **호환성 판정에는 영향이 없다** — 둘 다 타원체 기준의
    높이라 서로 빼도 되는 값이다(:func:`family_of`). 재처리 대상 표시와
    비교 가능성은 다른 축이다.

    **정표고 멤버가 지오이드 모델 이름을 달고 있는 이유.** 정표고가 서 있는
    기준면은 하나다(KVD1964 = 인천 평균해면, EPSG:5193). 그런데 그 높이를
    타원체고와 잇는 지오이드고 N 은 **격자 모델이 준다** — 즉 모델 이름은
    "이 높이가 어느 격자로 되돌려지는가"다. 모델이 다르면 국내 지점 대조에서
    수 cm 가 어긋나고(KNGeoid18↔24 실측 비교 0.001~0.071m), 그 크기는 체적
    집계 문턱(``DEFAULT_VOLUME_THRESHOLD_M`` = 0.05m)과 같은 자릿수다. 그래서
    모델을 이름에 박아 두고, **우리가 실제로 격자를 가진 모델만** 타원체고와
    잇는다(:data:`_GEOID_BRIDGEABLE_ORTHOMETRIC`).
    """

    ELLIPSOIDAL = "ellipsoidal"
    ELLIPSOIDAL_NATIVE = "ellipsoidal_native"
    ORTHOMETRIC_KNGEOID2018 = "orthometric_kngeoid2018"
    ORTHOMETRIC_KNGEOID2024 = "orthometric_kngeoid2024"


class VerticalDatumFamily(StrEnum):
    """수직기준의 **계열** — 변환 없이 서로 빼도 되는가만 가른다.

    같은 계열이면 두 높이의 차이가 그대로 의미를 갖는다. 다른 계열이면 그
    차이에 지오이드고(한국 20~30m)가 섞이므로, 격자로 변환하기 전에는 어떤
    수치도 내면 안 된다.
    """

    ELLIPSOIDAL = "ellipsoidal"
    ORTHOMETRIC = "orthometric"


#: SSOT — ``VerticalDatum`` 전 멤버의 계열. 조용한 기본값 없이 전수를 명시한다
#: (``mission_gating.MISSION_TYPE_ALLOWED_SITE_STATUSES`` 관습).
_DATUM_FAMILY: dict[VerticalDatum, VerticalDatumFamily] = {
    VerticalDatum.ELLIPSOIDAL: VerticalDatumFamily.ELLIPSOIDAL,
    VerticalDatum.ELLIPSOIDAL_NATIVE: VerticalDatumFamily.ELLIPSOIDAL,
    VerticalDatum.ORTHOMETRIC_KNGEOID2018: VerticalDatumFamily.ORTHOMETRIC,
    VerticalDatum.ORTHOMETRIC_KNGEOID2024: VerticalDatumFamily.ORTHOMETRIC,
}

# 표 완전성 자가검증 — 새 VerticalDatum 멤버를 추가하고 이 표를 안 고치면
# 여기서 즉시 ImportError 로 드러난다. 기본 계열을 추측해 넣는 경로를 만들지
# 않는 것이 핵심이다: 계열을 잘못 추측하면 20~30m 가 조용히 섞인다.
if set(_DATUM_FAMILY) != set(VerticalDatum):
    raise AssertionError("_DATUM_FAMILY 가 VerticalDatum 전 멤버를 커버하지 않는다")


#: **지오이드 격자로 타원체고와 이어붙일 수 있는 정표고 기준** — 이 시스템이 실제로
#: 격자를 가진 모델만 넣는다.
#:
#: 2026-08-12 현재 확보·검증된 격자는 KNGeoid24 하나다(``data/geoid/KNGeoid24.tif``,
#: 국토지리정보원 정식 취득, 전국 통합기준점 10점 전원 통과·최대오차 0.0401m —
#: ``docs/geo/GEOID_ACQUISITION.md``). ``ORTHOMETRIC_KNGEOID2018`` 은 **일부러 빼
#: 두었다**: KNGeoid18 격자가 없고, 대신 KNGeoid24 격자를 써서 "KNGeoid18 로 실현한
#: 정표고"를 되돌리면 두 모델의 차이(국내 지점 대조 0.001~0.071m)가 결과에 그대로
#: 들어간다. 그 크기는 집계 문턱 0.05m 와 같은 자릿수라 무시할 수 없고, 무엇보다
#: 리포트가 "KNGeoid18 기준으로 변환했다"고 말하게 되는데 그건 사실이 아니다
#: (``_VERTICAL_CRS_EPSG_TO_DATUM`` 이 EGM96/EGM2008 을 거부하는 것과 같은 근거 —
#: 계열이 맞아도 이름이 틀리면 거짓말이다).
#:
#: 이 집합이 비면 정표고 경로 전체가 자동으로 닫힌다(격자를 잃었을 때의 정상 상태).
_GEOID_BRIDGEABLE_ORTHOMETRIC: frozenset[VerticalDatum] = frozenset(
    {VerticalDatum.ORTHOMETRIC_KNGEOID2024}
)

#: 관측된 수직 CRS(EPSG) → 그 파일이 말하는 수직기준.
#:
#: **왜 화이트리스트인가.** 모르는 코드를 "아마 타원체고겠지"로 넘기면 정표고
#: 파일이 타원체고로 둔갑해 20~30m 가 조용히 들어온다(:mod:`ksi_geo_spatial.crs`
#: 의 투영좌표계 화이트리스트와 같은 정신). 그래서 아는 코드만 매핑하고 나머지는
#: :class:`UnrecognizedVerticalCrsError` 로 거부한다.
#:
#: **5019/5030 은 현행 PROJ DB 에 CRS 로 남아 있지 않다**(2026-08-12 실측:
#: ``CRS.from_epsg(5030)`` 실패, proj.db 에 행 없음). 그래도 표에 두는 이유는
#: GeoTIFF 1.0 의 ``VerticalCSTypeGeoKey`` 가 여전히 이 레거시 코드로 "타원체
#: 기준 높이"를 표기하고 생산자들이 그대로 쓰기 때문이다 — pyproj 조회가 아니라
#: 명시 표로 다뤄야 하는 값들이다.
#:
#: **관측값은 ``ELLIPSOIDAL`` 로 매핑하고 ``ELLIPSOIDAL_NATIVE`` 로는 절대
#: 매핑하지 않는다.** 후자는 "우리 파이프라인이 변환을 안 했다"는 우리 쪽 귀속
#: 상태이지 파일에서 관측될 수 있는 성질이 아니다.
#:
#: EGM96(5773)·EGM2008(3855) 같은 세계 지오이드 높이는 **의도적으로 넣지
#: 않았다** — 계열은 정표고지만 한국 국가 수직기준이 아니라서 그 값을
#: ``ORTHOMETRIC_KNGEOID2018`` 이라고 부르면 거짓말이 된다. 거부가 정답이다.
_VERTICAL_CRS_EPSG_TO_DATUM: dict[int, VerticalDatum] = {
    # GeoTIFF VerticalCSTypeGeoKey — GRS 1980 타원체 기준 높이(KGD2002 계열).
    5019: VerticalDatum.ELLIPSOIDAL,
    # GeoTIFF VerticalCSTypeGeoKey — WGS 84 타원체 기준 높이.
    5030: VerticalDatum.ELLIPSOIDAL,
    # EPSG:5193 KVD1964 height — 인천 평균해면 기준 한국 정표고.
    #
    # **EPSG 수직 CRS 코드는 기준면을 식별하지 지오이드 모델을 식별하지 않는다.**
    # 2026-08-12 실측(``pyproj.database.query_crs_info(pj_types=["VERTICAL_CRS"])``
    # 전수 조회): 한국 육상을 덮는 비폐기 수직 CRS 는 5193 하나뿐이고, 나머지
    # (3855 EGM2008 / 5773 EGM96 / 5714 MSL …)는 전부 세계 기준이라 아래 화이트
    # 리스트가 이미 거부한다. 즉 **KNGeoid24 용으로 새로 매핑할 코드가 없다.**
    #
    # 그래서 이 표가 정표고 멤버 중 무엇을 돌려줄지는 임의 선택이 될 수밖에 없고,
    # 여기서는 **격자로 이어붙일 수 없는 쪽**(KNGeoid2018)을 고른다. 이 함수의
    # 반환값은 :func:`family_of` 대조(선언 반박)에만 쓰이지만, 언젠가 누가
    # :func:`bridge_between` 에 잘못 먹이더라도 그 방향의 오작동이 "조용한 변환"이
    # 아니라 "거부"가 되게 하기 위해서다.
    5193: VerticalDatum.ORTHOMETRIC_KNGEOID2018,
}


class VerticalDatumIncompatibleError(ValueError):
    """서로 다른 계열의 수직기준을 직접 비교하려 했다 — 변환 없이 거부한다."""


class UnrecognizedVerticalCrsError(ValueError):
    """관측된 수직 CRS 를 안전하게 해석할 수 없다 — 무시하지 않고 거부한다."""


class VerticalReferenceSource(StrEnum):
    """이 수직기준 값이 **누구의 귀속인가**. 이름 선택 근거는 모듈 docstring 참조.

    둘 다 관측이 아니라 주장이다 — 차이는 신뢰도가 아니라 **틀렸을 때 고칠
    자리**다(파이프라인 설정 vs 그 파일의 등록 정보).
    """

    #: 산출물을 만든 처리 파이프라인이 자기 동작을 근거로 귀속한 값.
    PIPELINE_DECLARED = "pipeline_declared"
    #: 업로더가 주장한 값 — 파일에서 자동으로 확인할 수 없다.
    USER_DECLARED = "user_declared"


class VerticalReference(_CamelModel):
    """높이의 기준 + 그 기준을 아는 근거 + 귀속.

    ``basis`` 를 비울 수 없게 한 것이 이 계약의 핵심이다. "왜 이 값을 아는가"를
    적지 못하는 선언은 그냥 추측이고, 추측이 계약에 실리면 소비자는 그것을
    사실로 다룬다. 예: ``"ODM 이 RTK 타원체고를 변환 없이 그대로 출력"``,
    ``"설계사 제공 도면 표제부에 타원체고 명시"``.
    """

    datum: VerticalDatum
    #: 공백만 있는 근거는 빈 근거다 — ``min_length`` 만으로는 ``" "`` 가 통과한다.
    basis: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source: VerticalReferenceSource


def family_of(datum: VerticalDatum) -> VerticalDatumFamily:
    """그 수직기준이 어느 계열인가. 표에 없는 값은 있을 수 없다(위 완전성 검증)."""
    return _DATUM_FAMILY[datum]


def assert_comparable_vertical(a: VerticalReference, b: VerticalReference) -> None:
    """두 높이를 변환 없이 비교해도 되는지 — 아니면 typed 거부.

    비교·차분 연산의 입구에서 부른다(``crs.assert_same_crs`` 와 같은 자리·같은
    역할의 수직축 판)다. 통과 조건은 **계열 일치**이지 datum 값 일치가 아니다 —
    ``ellipsoidal``(설계자가 의도적으로 타원체고로 납품)과
    ``ellipsoidal_native``(우리 파이프라인이 변환하지 않고 남긴 상태)는 서로
    빼도 되는 같은 계열이다.
    """
    family_a = family_of(a.datum)
    family_b = family_of(b.datum)
    if family_a == family_b:
        return
    raise VerticalDatumIncompatibleError(
        f"수직기준 계열이 달라 변환 없이 비교할 수 없다: "
        f"{a.datum.value}({family_a.value}) vs {b.datum.value}({family_b.value}). "
        "타원체고와 정표고의 차이는 한국에서 20~30m 이고, 지오이드 격자 없이 "
        "맞추면 그 오차가 결과에 조용히 들어간다"
    )


class VerticalBridge(StrEnum):
    """두 수직기준을 나란히 놓으려면 무엇이 필요한가 — **판정만** 한다.

    :func:`assert_comparable_vertical` 은 "변환 없이 빼도 되는가" 하나만 묻는다.
    설계 대비 잔량은 그 질문으로 부족하다: 실무 설계도면은 거의 항상 정표고이고
    우리 재구성 파이프라인은 타원체고를 내므로, 그 조합을 통째로 거부하면
    **한국 도면이 100% 막힌다.** 그렇다고 격자 없이 맞추면 20~30m 가 조용히
    틀린다. 그래서 거부/통과의 2분법을 셋으로 나눈다.

    이 판정이 계약 패키지에 사는 이유는 :class:`VerticalDatum` 과 같다 —
    **소비자가 Core(control plane)** 다. Core 는 요청을 받는 자리에서 "이 지시가
    계산 가능한가"를 즉시 답해야 하는데, pyproj·rasterio 를 물고 있는
    ``ksi-geo-spatial`` 을 의존할 수 없다. 그래서 **"격자로 이을 수 있는가"라는
    순수 표 판정은 여기**, **실제로 격자를 읽어 N 을 보간하는 일은 워커**로
    나뉜다. 격자가 그 배포에 실제로 붙어 있는지는 Core 가 알 수 없는 사실이고
    (워커의 환경변수다), 그래서 :attr:`GEOID_GRID` 는 "된다"가 아니라
    **"격자가 있으면 된다"**는 뜻이다.
    """

    #: 같은 계열 — 변환 없이 그대로 뺀다.
    DIRECT = "direct"
    #: 계열이 다르지만 지오이드 격자로 이을 수 있다. 격자가 없으면 계산하는 쪽이
    #: 거부한다(``GeoidUnavailableError``) — 그 거부는 **이 판정과 다른 사실**이다.
    GEOID_GRID = "geoid_grid"
    #: 어떤 격자로도 이 시스템이 메울 수 없다 — 즉시 거부가 정답이다.
    NONE = "none"


def bridge_between(a: VerticalReference, b: VerticalReference) -> VerticalBridge:
    """두 수직기준을 잇는 방법 — 없으면 :attr:`VerticalBridge.NONE`.

    ``a``/``b`` 의 순서는 판정에 영향이 없다(어느 쪽을 옮길지는 계산하는 쪽이
    정한다 — 설계 대비 경로는 **측정물인 DSM 을 두고 설계면을 옮긴다**).
    """
    family_a = family_of(a.datum)
    family_b = family_of(b.datum)
    if family_a == family_b:
        # 같은 계열이라고 곧바로 DIRECT 는 아니다 — **정표고 계열 안에서도 실현이
        # 다르면 다른 기준이다.** KNGeoid18 과 KNGeoid24 는 둘 다 정표고지만 같은
        # 지점에서 서로 다른 값을 준다(docs/geo/GEOID_ACQUISITION.md 실측: 모델
        # 차이 최대 0.071m). 그 크기는 우리가 재구성 잡음으로 버리는 집계 문턱
        # (0.05m)과 같은 자릿수라, 변환 없이 빼면 "잡음보다 큰 오차"가 물량에
        # 그대로 들어간다. 이건 아래 GEOID_GRID 거부 문구가 말하는 것과 정확히
        # 같은 사고다 — 리포트가 말하는 기준과 실제로 쓴 기준이 갈라진다.
        #
        # 반대로 타원체고 계열의 두 값은 **같은 물리량**이다. ELLIPSOIDAL_NATIVE 는
        # "우리가 변환을 안 해서 타원체고로 남았다"는 우리 쪽 귀속 표시이지 다른
        # 기준이 아니다(이 모듈 상단 주석). 그래서 그 둘만 서로 DIRECT 다.
        #
        # 실현 간 변환(2018↔2024)은 이 시스템에 없다 — 두 격자를 모두 갖고 차분해야
        # 하는데 KNGeoid18 격자가 없다. 없는 능력을 있다고 판정하지 않는다.
        if a.datum == b.datum or family_a is VerticalDatumFamily.ELLIPSOIDAL:
            return VerticalBridge.DIRECT
        return VerticalBridge.NONE
    if {family_a, family_b} != {VerticalDatumFamily.ELLIPSOIDAL, VerticalDatumFamily.ORTHOMETRIC}:
        # 새 계열이 생겼는데 잇는 법을 아무도 안 적어 둔 경우. 추측하지 않는다.
        return VerticalBridge.NONE
    orthometric = a.datum if family_a is VerticalDatumFamily.ORTHOMETRIC else b.datum
    if orthometric in _GEOID_BRIDGEABLE_ORTHOMETRIC:
        return VerticalBridge.GEOID_GRID
    return VerticalBridge.NONE


def assert_bridgeable_vertical(a: VerticalReference, b: VerticalReference) -> VerticalBridge:
    """이을 수 있으면 그 방법을, 없으면 typed 거부.

    ``assert_comparable_vertical`` 과 같은 자리에서 부르되(비교 연산의 입구),
    **지오이드 격자를 쓸 수 있는 경로에서만** 쓴다. 두 epoch 비교처럼 변환 경로가
    아예 없는 계산은 계속 ``assert_comparable_vertical`` 이다 — 거기서 이 함수를
    쓰면 "이을 수 있다"는 판정만 받고 정작 아무도 잇지 않는다.
    """
    bridge = bridge_between(a, b)
    if bridge is not VerticalBridge.NONE:
        return bridge
    family_a = family_of(a.datum)
    family_b = family_of(b.datum)
    head = (
        f"수직기준을 이을 수 없다: {a.datum.value}({family_a.value}) vs "
        f"{b.datum.value}({family_b.value}). "
    )
    if family_a == family_b:
        # 같은 계열인데 거부됐다면 정표고 실현이 서로 다른 경우뿐이다 — 위
        # bridge_between 참조. 계열 불일치 문구를 그대로 쓰면 "타원체고와 정표고의
        # 차이"를 말하게 되는데 여기서는 둘 다 정표고라 사람을 헷갈리게 한다.
        raise VerticalDatumIncompatibleError(
            head + "둘 다 정표고지만 **실현한 지오이드 모델이 다르다** — 같은 지점에서 "
            "서로 다른 값을 준다(모델 차이 최대 0.071m, 재구성 잡음으로 버리는 집계 "
            "문턱 0.05m 보다 크다). 실현 간 변환은 두 모델의 격자를 모두 가져야 "
            "가능한데 이 시스템은 "
            f"{sorted(datum.value for datum in _GEOID_BRIDGEABLE_ORTHOMETRIC)} "
            "격자만 갖고 있다. 한쪽 격자로 대신 맞추면 리포트가 말하는 기준과 실제로 "
            "쓴 기준이 달라진다"
        )
    raise VerticalDatumIncompatibleError(
        head + "타원체고와 정표고의 차이는 한국에서 20~30m 이고, 그 간극은 **그 정표고를 "
        "실현한 지오이드 모델의 격자**로만 메울 수 있다 — 이 시스템이 격자를 가진 "
        f"정표고 기준은 {sorted(datum.value for datum in _GEOID_BRIDGEABLE_ORTHOMETRIC)} "
        "뿐이다. 다른 모델의 격자로 대신 변환하면 결과는 그럴듯한 숫자가 되지만 리포트가 "
        "말하는 기준과 실제로 쓴 기준이 달라진다"
    )


def vertical_datum_from_epsg(vertical_crs_epsg: int) -> VerticalDatum:
    """관측된 수직 CRS(EPSG 코드)가 말하는 수직기준. 모르면 거부한다.

    파일에서 실제로 읽어낸 수직 CRS 를 **선언과 대조**하는 데 쓴다(설계면 검증).
    아는 코드만 매핑하고 나머지는 :class:`UnrecognizedVerticalCrsError` 다 —
    조용히 무시하거나 기본값으로 넘기지 않는다. 해석되지 않는 수직 CRS 가 붙은
    파일은 "선언을 확인할 수 없는 파일"이지 "선언이 맞는 파일"이 아니다.

    반환값은 **계열 판정용**으로 쓰는 것이 정상 경로다(:func:`family_of`) —
    표 주석의 5193 항목 참조.
    """
    datum = _VERTICAL_CRS_EPSG_TO_DATUM.get(vertical_crs_epsg)
    if datum is None:
        raise UnrecognizedVerticalCrsError(
            f"수직 CRS EPSG:{vertical_crs_epsg} 를 해석할 수 없다 — 아는 코드: "
            f"{sorted(_VERTICAL_CRS_EPSG_TO_DATUM)}. 모르는 기준면을 추측해 "
            "통과시키면 타원체고와 정표고가 섞여 20~30m 가 조용히 틀린다"
        )
    return datum


__all__ = [
    "UnrecognizedVerticalCrsError",
    "VerticalBridge",
    "VerticalDatum",
    "VerticalDatumFamily",
    "VerticalDatumIncompatibleError",
    "VerticalReference",
    "VerticalReferenceSource",
    "assert_bridgeable_vertical",
    "assert_comparable_vertical",
    "bridge_between",
    "family_of",
    "vertical_datum_from_epsg",
]
