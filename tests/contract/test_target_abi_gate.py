"""Manifold 3 타깃 ABI 게이트 검증 (tools/edge/check_target_abi.py).

green≠작동 방지 핵심: "파서가 있다"가 아니라 "실제 DPK 정적 링크 위반·glibc 초과·
절대 RPATH를 잡아내고, 위반이 없으면 통과한다"를 변이 테스트(위반 주입 → 실패,
위반 제거 → 통과)로 증명한다. subprocess/readelf 호출 없이 고정 텍스트 픽스처로
파싱·판정 로직만 검증한다 — CI가 실기 없이도 이 게이트의 유효성을 매 커밋 확인한다.

2026-08-03 실기 HIL 세션 중 발견한 회귀 사례(ld-linux-aarch64.so.1을 서드파티로
오탐)도 여기 고정한다 — 동적 링커 자체는 허용돼야 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "edge"))

from check_target_abi import (  # noqa: E402
    DEFAULT_MAX_GLIBC,
    evaluate_binary,
    parse_max_glibc_requirement,
    parse_needed,
    parse_rpaths,
)

# --- 실기(2026-08-03 HIL 세션, Manifold 3 aarch64) 실측 readelf -d 원문 발췌 ---
_REAL_DYNAMIC_SECTION = """
Dynamic section at offset 0x4ca8 contains 30 entries:
  Tag        Type                         Name/Value
 0x0000000000000001 (NEEDED)             Shared library: [libstdc++.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libgcc_s.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [ld-linux-aarch64.so.1]
 0x000000000000000c (INIT)               0xe68
"""

_VERSION_SECTION_2_31 = """
Version needs section '.gnu.version_r' contains 1 entry:
  Addr: 0x0000000000000000  Offset: 0x000000000000  Link: 3 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 3
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 3
  0x0020:   Name: GLIBC_2.29  Flags: none  Version: 2
  0x0030:   Name: GLIBC_2.31  Flags: none  Version: 4
"""

_VERSION_SECTION_2_35 = """
Version needs section '.gnu.version_r' contains 1 entry:
 0x0010:   Name: GLIBC_2.17  Flags: none  Version: 3
 0x0030:   Name: GLIBC_2.35  Flags: none  Version: 4
"""


class TestParsing:
    def test_parse_needed_extracts_all_libraries_in_order(self) -> None:
        assert parse_needed(_REAL_DYNAMIC_SECTION) == [
            "libstdc++.so.6",
            "libgcc_s.so.1",
            "libc.so.6",
            "ld-linux-aarch64.so.1",
        ]

    def test_parse_needed_empty_when_no_dynamic_section(self) -> None:
        # 완전 정적 바이너리는 .dynamic 섹션이 없다 — 실패가 아니라 빈 목록이다.
        assert parse_needed("readelf: Error: no dynamic section\n") == []

    def test_parse_rpaths_splits_colon_separated_absolute_paths(self) -> None:
        text = "0x000000000000000f (RPATH) Library rpath: [/opt/psdk/lib:/usr/local/lib]"
        assert parse_rpaths(text) == ["/opt/psdk/lib", "/usr/local/lib"]

    def test_parse_rpaths_recognizes_runpath_tag_too(self) -> None:
        text = "0x000000000000001d (RUNPATH) Library runpath: [$ORIGIN/../lib]"
        assert parse_rpaths(text) == ["$ORIGIN/../lib"]

    def test_parse_rpaths_empty_when_absent(self) -> None:
        assert parse_rpaths(_REAL_DYNAMIC_SECTION) == []

    def test_parse_max_glibc_picks_highest_of_several_versions(self) -> None:
        assert parse_max_glibc_requirement(_VERSION_SECTION_2_31) == (2, 31)

    def test_parse_max_glibc_none_when_no_version_requirements(self) -> None:
        # 버전 요구가 전혀 없으면(정적 바이너리 등) 비교 대상이 없다 — None이 맞다.
        assert parse_max_glibc_requirement("") is None


class TestEvaluateBinaryAllowedAndDisallowed:
    def test_glibc_family_alone_passes(self) -> None:
        result = evaluate_binary(
            binary_name="libksi.so",
            needed=["libc.so.6", "libm.so.6", "libpthread.so.0", "libgcc_s.so.1"],
            rpaths=[],
            max_glibc=(2, 31),
        )
        assert result.ok

    def test_dynamic_linker_itself_is_not_a_false_positive(self) -> None:
        # 회귀 고정: ld-linux-*는 서드파티 라이브러리가 아니라 glibc 로더 자체다.
        result = evaluate_binary(
            binary_name="control_plane_tests",
            needed=["libc.so.6", "ld-linux-aarch64.so.1"],
            rpaths=[],
            max_glibc=(2, 31),
        )
        assert result.ok

    def test_third_party_dynamic_link_is_rejected(self) -> None:
        result = evaluate_binary(
            binary_name="myapp",
            needed=["libc.so.6", "libz.so.1"],
            rpaths=[],
            max_glibc=(2, 31),
        )
        assert not result.ok
        assert result.findings[0].code == "DISALLOWED_DYNAMIC_LINK"
        assert "libz.so.1" in result.findings[0].detail

    def test_unstatic_libstdcxx_is_rejected_matching_real_device_build(self) -> None:
        # 2026-08-03 실기 세션 실측: KSI_TARGET_MANIFOLD3 정적 링크 정책을 아직
        # 적용하지 않은 빌드는 libstdc++.so.6을 동적으로 가져온다 — 이게 잡혀야
        # cmake/toolchain-manifold3.cmake의 -static-libstdc++가 존재하는 이유가 선다.
        result = evaluate_binary(
            binary_name="control_plane_tests",
            needed=parse_needed(_REAL_DYNAMIC_SECTION),
            rpaths=parse_rpaths(_REAL_DYNAMIC_SECTION),
            max_glibc=(2, 31),
        )
        codes = {f.code for f in result.findings}
        assert codes == {"DISALLOWED_DYNAMIC_LINK"}
        assert any("libstdc++.so.6" in f.detail for f in result.findings)

    def test_static_libstdcxx_build_passes_the_same_check(self) -> None:
        # 위 실패 케이스의 짝 — -static-libstdc++ 적용 후 libstdc++.so.6이 NEEDED에서
        # 사라지면(libgcc_s만 남는 일반적 패턴) 같은 검사가 통과로 뒤집힘을 증명한다
        # (변이 테스트: 위반 제거 → 결과 반전, 게이트가 no-op이 아님을 확인).
        result = evaluate_binary(
            binary_name="control_plane_tests",
            needed=["libgcc_s.so.1", "libc.so.6", "ld-linux-aarch64.so.1"],
            rpaths=[],
            max_glibc=(2, 31),
        )
        assert result.ok


class TestNvidiaTier2OptIn:
    def test_nvidia_runtime_rejected_by_default(self) -> None:
        result = evaluate_binary(
            binary_name="perception_app",
            needed=["libc.so.6", "libnvinfer.so.8"],
            rpaths=[],
            max_glibc=(2, 31),
        )
        assert not result.ok
        assert result.findings[0].code == "DISALLOWED_NVIDIA_DYNAMIC_LINK"

    def test_nvidia_runtime_allowed_with_explicit_opt_in(self) -> None:
        result = evaluate_binary(
            binary_name="perception_app",
            needed=["libc.so.6", "libnvinfer.so.8", "libcudart.so.11.0"],
            rpaths=[],
            max_glibc=(2, 31),
            allow_nvidia_libs=True,
        )
        assert result.ok


class TestGlibcCeiling:
    def test_requirement_above_ceiling_is_rejected(self) -> None:
        result = evaluate_binary(
            binary_name="myapp",
            needed=["libc.so.6"],
            rpaths=[],
            max_glibc=(2, 35),
            glibc_ceiling=DEFAULT_MAX_GLIBC,
        )
        assert not result.ok
        assert result.findings[0].code == "GLIBC_TOO_NEW"

    def test_requirement_at_or_below_ceiling_passes(self) -> None:
        result = evaluate_binary(
            binary_name="myapp",
            needed=["libc.so.6"],
            rpaths=[],
            max_glibc=(2, 31),
            glibc_ceiling=DEFAULT_MAX_GLIBC,
        )
        assert result.ok

    def test_no_glibc_requirement_at_all_is_not_a_failure(self) -> None:
        # 정적 바이너리처럼 버전 요구가 아예 없으면 비교할 게 없다 — 통과다.
        result = evaluate_binary(
            binary_name="static_myapp",
            needed=[],
            rpaths=[],
            max_glibc=None,
        )
        assert result.ok


class TestRpathPolicy:
    def test_absolute_rpath_is_rejected(self) -> None:
        result = evaluate_binary(
            binary_name="myapp",
            needed=["libc.so.6"],
            rpaths=["/opt/psdk/lib"],
            max_glibc=(2, 31),
        )
        assert not result.ok
        assert result.findings[0].code == "ABSOLUTE_RPATH"

    def test_origin_relative_rpath_passes(self) -> None:
        result = evaluate_binary(
            binary_name="myapp",
            needed=["libc.so.6"],
            rpaths=["$ORIGIN/../lib"],
            max_glibc=(2, 31),
        )
        assert result.ok
