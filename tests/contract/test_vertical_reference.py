"""수직기준 참조 계약과 계열(family) 판정.

**이 파일이 지키는 한 문장:** 타원체고와 정표고를 변환 없이 빼면 한국에서
20~30m 가 조용히 틀린다. 그래서 (1) 계열이 다르면 거부하고, (2) 계열을 모르는
값은 추측하지 않으며, (3) 수직기준을 "왜 아는지"(``basis``) 없이 선언할 수 없다.

세 번째가 특히 중요하다 — 지금 저장소의 ``vertical_datum`` 값은 비교 워커의
하드코딩 상수에서 나오고 있어서, 리포트는 근거 없이 "타원체고"라고 말한다.
계약이 근거를 요구하지 않으면 그 상태가 설계면 비교까지 그대로 이어진다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ksi_event_contracts.vertical_reference import (
    _DATUM_FAMILY,  # noqa: PLC2701 -- 표 전수 커버 검사를 위한 의도적 내부 접근
    _VERTICAL_CRS_EPSG_TO_DATUM,  # noqa: PLC2701 -- 화이트리스트 전수 검사
    UnrecognizedVerticalCrsError,
    VerticalDatum,
    VerticalDatumFamily,
    VerticalDatumIncompatibleError,
    VerticalReference,
    VerticalReferenceSource,
    assert_comparable_vertical,
    family_of,
    vertical_datum_from_epsg,
)
from pydantic import ValidationError


def _ref(datum: VerticalDatum) -> VerticalReference:
    return VerticalReference(
        datum=datum,
        basis="테스트 픽스처",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


# --------------------------------------------------------------------------
# family_of — 전 멤버 커버
# --------------------------------------------------------------------------


def test_family_of_covers_every_datum_member() -> None:
    """``VerticalDatum`` 전 멤버가 계열을 갖는다 — 조용한 기본값이 없다."""
    assert set(_DATUM_FAMILY) == set(VerticalDatum)
    for datum in VerticalDatum:
        assert isinstance(family_of(datum), VerticalDatumFamily)


def test_family_of_maps_each_member_to_the_expected_family() -> None:
    assert family_of(VerticalDatum.ELLIPSOIDAL) is VerticalDatumFamily.ELLIPSOIDAL
    assert family_of(VerticalDatum.ELLIPSOIDAL_NATIVE) is VerticalDatumFamily.ELLIPSOIDAL
    assert (
        family_of(VerticalDatum.ORTHOMETRIC_KNGEOID2018) is VerticalDatumFamily.ORTHOMETRIC
    )


def test_adding_a_datum_member_without_a_family_row_fails_at_import() -> None:
    """새 멤버를 표에 안 넣으면 **임포트 시점에** 터진다.

    표 완전성 가드가 실제로 작동하는지를 조건식 복제가 아니라 **모듈 소스에 새
    멤버를 넣어 실행**해서 확인한다. 가드가 사라지거나 약해지면 이 테스트가
    실패한다 — 계열을 추측해 넣는 경로가 조용히 열리는 것이 이 milestone 에서
    가장 비싼 사고다.
    """
    import ksi_event_contracts.vertical_reference as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    anchor = '    ORTHOMETRIC_KNGEOID2018 = "orthometric_kngeoid2018"'
    assert anchor in source, "enum 정의 형태가 바뀌었다 — 이 테스트의 앵커를 갱신할 것"
    patched = source.replace(anchor, anchor + '\n    FUTURE_DATUM = "future_datum"', 1)

    with pytest.raises(AssertionError, match="전 멤버를 커버하지 않는다"):
        exec(  # noqa: S102 -- 가드 발화를 실증하려면 패치된 모듈 소스를 실제로 실행해야 한다
            compile(patched, "<patched vertical_reference>", "exec"),
            {"__name__": "patched_vertical_reference"},
        )


# --------------------------------------------------------------------------
# assert_comparable_vertical
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (VerticalDatum.ELLIPSOIDAL, VerticalDatum.ELLIPSOIDAL),
        (VerticalDatum.ELLIPSOIDAL_NATIVE, VerticalDatum.ELLIPSOIDAL_NATIVE),
        # 설계면(의도적 타원체고) ↔ 재구성 산출물(변환 못 해 남은 타원체고).
        # **이 조합이 통과하는 것이 설계 대비 비교의 정상 경로다.**
        (VerticalDatum.ELLIPSOIDAL, VerticalDatum.ELLIPSOIDAL_NATIVE),
        (VerticalDatum.ELLIPSOIDAL_NATIVE, VerticalDatum.ELLIPSOIDAL),
        (VerticalDatum.ORTHOMETRIC_KNGEOID2018, VerticalDatum.ORTHOMETRIC_KNGEOID2018),
    ],
)
def test_same_family_is_comparable(a: VerticalDatum, b: VerticalDatum) -> None:
    # 예외가 나지 않는 것이 통과 조건이다(반환값 없음).
    assert_comparable_vertical(_ref(a), _ref(b))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (VerticalDatum.ELLIPSOIDAL, VerticalDatum.ORTHOMETRIC_KNGEOID2018),
        (VerticalDatum.ELLIPSOIDAL_NATIVE, VerticalDatum.ORTHOMETRIC_KNGEOID2018),
        (VerticalDatum.ORTHOMETRIC_KNGEOID2018, VerticalDatum.ELLIPSOIDAL),
        (VerticalDatum.ORTHOMETRIC_KNGEOID2018, VerticalDatum.ELLIPSOIDAL_NATIVE),
    ],
)
def test_different_family_is_refused(a: VerticalDatum, b: VerticalDatum) -> None:
    """계열이 다르면 거부한다 — 지오이드 격자 없이 맞추지 않는다."""
    with pytest.raises(VerticalDatumIncompatibleError) as excinfo:
        assert_comparable_vertical(_ref(a), _ref(b))

    message = str(excinfo.value)
    # 메시지가 두 값과 두 계열을 모두 말해야 한다 — 화면·로그에서 "왜 거부됐나"가
    # 바로 읽혀야 재처리 판단이 가능하다.
    assert a.value in message
    assert b.value in message
    assert family_of(a).value in message
    assert family_of(b).value in message


def test_every_datum_pair_is_decided_by_family_not_by_equality() -> None:
    """전 조합 전수 — 판정 기준이 값 일치가 아니라 계열 일치임을 고정한다."""
    for a in VerticalDatum:
        for b in VerticalDatum:
            comparable = family_of(a) == family_of(b)
            if comparable:
                assert_comparable_vertical(_ref(a), _ref(b))
            else:
                with pytest.raises(VerticalDatumIncompatibleError):
                    assert_comparable_vertical(_ref(a), _ref(b))


# --------------------------------------------------------------------------
# vertical_datum_from_epsg
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (5019, VerticalDatum.ELLIPSOIDAL),  # GeoTIFF: GRS 1980 타원체 기준 높이
        (5030, VerticalDatum.ELLIPSOIDAL),  # GeoTIFF: WGS 84 타원체 기준 높이
        (5193, VerticalDatum.ORTHOMETRIC_KNGEOID2018),  # KVD1964 height
    ],
)
def test_known_vertical_crs_codes_map(code: int, expected: VerticalDatum) -> None:
    assert vertical_datum_from_epsg(code) is expected


@pytest.mark.parametrize(
    "code",
    [
        3855,  # EGM2008 height — 정표고 계열이지만 한국 국가 수직기준이 아니다
        5773,  # EGM96 height — 같은 이유
        4326,  # 수직 CRS 가 아니다
        5186,  # 수평(투영) CRS 를 수직 자리에 넣은 경우
        0,
        -1,
    ],
)
def test_unknown_vertical_crs_code_is_refused_not_ignored(code: int) -> None:
    """모르는 코드는 무시도 기본값도 아니고 **typed 거부**다.

    조용히 통과시키면 정표고 파일이 타원체고로 둔갑해 20~30m 가 결과에 들어간다.
    EGM2008/EGM96 을 ``ORTHOMETRIC_KNGEOID2018`` 로 넘기지 않는 것도 같은 이유 —
    계열은 같아도 그 이름을 붙이면 거짓말이 된다.
    """
    with pytest.raises(UnrecognizedVerticalCrsError) as excinfo:
        vertical_datum_from_epsg(code)
    assert str(code) in str(excinfo.value)


def test_observed_codes_never_map_to_the_native_residual_state() -> None:
    """관측 결과가 ``ellipsoidal_native`` 가 되는 경로는 없다.

    ``ELLIPSOIDAL_NATIVE`` 는 "우리 파이프라인이 변환을 안 했다"는 우리 쪽
    귀속이지 파일에서 읽을 수 있는 성질이 아니다.
    """
    assert VerticalDatum.ELLIPSOIDAL_NATIVE not in set(_VERTICAL_CRS_EPSG_TO_DATUM.values())


# --------------------------------------------------------------------------
# VerticalReference 모델
# --------------------------------------------------------------------------


def test_vertical_reference_round_trips_in_camel_case() -> None:
    payload = {
        "datum": "ellipsoidal_native",
        "basis": "ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
        "source": "pipeline_declared",
    }
    reference = VerticalReference.model_validate(payload)

    assert reference.datum is VerticalDatum.ELLIPSOIDAL_NATIVE
    assert reference.source is VerticalReferenceSource.PIPELINE_DECLARED
    assert reference.model_dump(by_alias=True, mode="json") == payload


def test_vertical_reference_accepts_user_declared_source() -> None:
    reference = VerticalReference.model_validate(
        {
            "datum": "ellipsoidal",
            "basis": "설계사 제공 도면 표제부에 타원체고 명시",
            "source": "user_declared",
        }
    )
    assert reference.source is VerticalReferenceSource.USER_DECLARED


@pytest.mark.parametrize("basis", ["", "   ", "\n\t"])
def test_empty_basis_is_refused(basis: str) -> None:
    """근거 없는 수직기준 선언은 계약에 실을 수 없다.

    ``basis`` 가 비어 있으면 소비자는 "이 값을 왜 아는가"에 답할 수 없고,
    그러면 그 값은 추측인데 계약에 실린 순간 사실처럼 다뤄진다.
    """
    with pytest.raises(ValidationError):
        VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis=basis,
            source=VerticalReferenceSource.USER_DECLARED,
        )


def test_unknown_source_value_is_refused() -> None:
    """``producer_measured`` 같은 옛 이름은 이제 계약 밖이다(모듈 docstring 근거)."""
    with pytest.raises(ValidationError):
        VerticalReference.model_validate(
            {"datum": "ellipsoidal", "basis": "x", "source": "producer_measured"}
        )


def test_extra_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        VerticalReference.model_validate(
            {
                "datum": "ellipsoidal",
                "basis": "x",
                "source": "user_declared",
                "geoidModel": "KNGeoid18",
            }
        )


def test_geo_spatial_re_export_is_the_same_object() -> None:
    """``ksi_geo_spatial.vertical`` 경로로 들어와도 같은 값 객체다 — 정본은 하나."""
    from ksi_geo_spatial import vertical as geo_vertical

    assert geo_vertical.VerticalDatum is VerticalDatum
    assert geo_vertical.VerticalReference is VerticalReference
    assert geo_vertical.family_of is family_of
    assert geo_vertical.assert_comparable_vertical is assert_comparable_vertical
    assert geo_vertical.vertical_datum_from_epsg is vertical_datum_from_epsg
