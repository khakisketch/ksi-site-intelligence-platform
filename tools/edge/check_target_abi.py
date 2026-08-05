"""Manifold 3 타깃 ABI 게이트 — DPK 정적 링크 제약과 glibc 상한을 기계적으로 강제한다.

배경: DPK 문서는 "서드파티 의존성은 정적 라이브러리만, 동적 라이브러리는 설치·실행
실패를 유발한다"고 규정한다. 이 규정을 리뷰어의 기억에 맡기지 않고, 링크된 산출물
(ELF)을 직접 읽어 강제한다. 또한 실기(2026-08-03 실측: glibc 2.31, Ubuntu 20.04.6)보다
새 glibc 심볼을 링크한 바이너리는 실기에서 로드조차 안 되므로, 이것도 여기서 잡는다
(``cmake/toolchain-manifold3.cmake``의 configure 시점 단언은 "빌드 환경이 맞나"만
보고, 이 스크립트는 "만들어진 바이너리가 실기에서 돌 수 있나"를 산출물에서 직접 본다).

검사 3가지:
  1. NEEDED(동적 링크 의존성)가 허용목록 밖이면 실패 — DPK 정적 링크 제약의 집행.
     Tier 1(무조건 허용): glibc 계열 6종. Tier 2(증거 필요, 기본 거부): NVIDIA
     런타임(TensorRT/CUDA) — "장비 제공 시스템 라이브러리가 DPK 제약의 예외인가"는
     검증되지 않은 가정이므로 ``--allow-nvidia-libs`` 명시 없이는 통과시키지 않는다.
  2. 요구하는 최대 glibc 심볼 버전이 실기 상한(기본 2.31)을 넘으면 실패.
  3. RPATH/RUNPATH에 절대경로가 있으면 실패 — DPK "설정파일은 상대경로만" 제약과
     정렬(런타임에 실행 위치가 바뀌면 절대 RPATH는 이식되지 않는다).

이 스크립트는 ``readelf -d``와 ``readelf -V``의 텍스트 출력을 파싱한다(실제 ELF
바이너리 파서를 새로 만들지 않는다 — binutils가 이미 있고 CI 컨테이너에도 있다).
파싱 함수는 고정 텍스트 픽스처로 단위테스트된다(``tests/contract/test_target_abi_gate.py``)
— 이 저장소의 "게이트가 no-op이 아님을 증명한다" 관례를 따른다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Tier 1: 실기에 항상 존재하는 glibc 계열. 무조건 허용.
ALLOWED_NEEDED_TIER1: frozenset[str] = frozenset(
    {
        "libc.so.6",
        "libm.so.6",
        "libdl.so.2",
        "libpthread.so.0",
        "librt.so.1",
        "libgcc_s.so.1",
    }
)

# 동적 링커(인터프리터) 자체 — 아키텍처별로 이름이 다르다(aarch64: ld-linux-aarch64.so.1,
# x86_64: ld-linux-x86-64.so.2 등). 완전 정적 링크가 아닌 이상 항상 NEEDED로 나열되는
# glibc의 필수 구성요소이지 "서드파티 라이브러리"가 아니므로 무조건 허용한다
# (2026-08-03 실기 검증 중 실제 오탐으로 발견 — ABI 게이트 자체의 회귀 테스트 대상).
DYNAMIC_LINKER_PATTERN = re.compile(r"^ld-linux")

# Tier 2: 장비 제공 시스템 라이브러리(TensorRT/CUDA 등). DPK 제약이 이들에도
# 적용되는지는 미확인 가정이므로, 명시적 옵트인(--allow-nvidia-libs) 없이는 거부한다.
NVIDIA_RUNTIME_NEEDED_PATTERN = re.compile(
    r"^lib(nvinfer|cudart|cuda|cudnn|nvonnxparser|nvparsers)"
)

# 실기 실측(2026-08-03 HIL 세션): Ubuntu 20.04.6, glibc 2.31.
DEFAULT_MAX_GLIBC = (2, 31)

_NEEDED_LINE = re.compile(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]")
_RPATH_LINE = re.compile(r"\((?:RPATH|RUNPATH)\)\s+Library (?:rpath|runpath):\s+\[([^\]]*)\]")
_GLIBC_VERSION = re.compile(r"GLIBC_(\d+)\.(\d+)")


@dataclass(frozen=True)
class AbiFinding:
    """단일 위반 사실. severity 없이 전부 실패 사유다 — 이 게이트는 경고를 내지 않는다."""

    code: str
    detail: str


@dataclass(frozen=True)
class AbiCheckResult:
    binary: str
    findings: list[AbiFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def parse_needed(readelf_dynamic_output: str) -> list[str]:
    """``readelf -d <binary>`` 출력에서 NEEDED 항목을 순서대로 추출한다."""
    return _NEEDED_LINE.findall(readelf_dynamic_output)


def parse_rpaths(readelf_dynamic_output: str) -> list[str]:
    """``readelf -d <binary>`` 출력에서 RPATH/RUNPATH 값을 추출한다(콜론 구분 다중 경로 분해)."""
    paths: list[str] = []
    for raw in _RPATH_LINE.findall(readelf_dynamic_output):
        paths.extend(p for p in raw.split(":") if p)
    return paths


def parse_max_glibc_requirement(readelf_version_output: str) -> tuple[int, int] | None:
    """``readelf -V <binary>`` 출력에서 요구하는 최대 GLIBC_x.y 심볼 버전을 찾는다.

    GLIBC 버전 요구가 전혀 없으면(순수 정적 바이너리 등) None을 반환한다 — 이는
    통과 사유이지 실패 사유가 아니다(비교 대상이 없으므로 상한 검사를 건너뛴다).
    """
    versions = [(int(a), int(b)) for a, b in _GLIBC_VERSION.findall(readelf_version_output)]
    return max(versions) if versions else None


def evaluate_binary(
    *,
    binary_name: str,
    needed: list[str],
    rpaths: list[str],
    max_glibc: tuple[int, int] | None,
    glibc_ceiling: tuple[int, int] = DEFAULT_MAX_GLIBC,
    allow_nvidia_libs: bool = False,
) -> AbiCheckResult:
    """순수 함수 — I/O 없이 이미 파싱된 값만으로 판정한다(단위테스트 대상의 핵심)."""
    findings: list[AbiFinding] = []

    for lib in needed:
        if lib in ALLOWED_NEEDED_TIER1 or DYNAMIC_LINKER_PATTERN.match(lib):
            continue
        if NVIDIA_RUNTIME_NEEDED_PATTERN.match(lib):
            if allow_nvidia_libs:
                continue
            findings.append(
                AbiFinding(
                    "DISALLOWED_NVIDIA_DYNAMIC_LINK",
                    f"{lib}: 장비 제공 NVIDIA 런타임 동적 링크는 --allow-nvidia-libs "
                    "명시 없이는 통과하지 않는다(DPK 정적 링크 제약 적용 여부 미확인).",
                )
            )
            continue
        findings.append(
            AbiFinding(
                "DISALLOWED_DYNAMIC_LINK",
                f"{lib}: 허용목록 밖 동적 라이브러리 — DPK는 서드파티 정적 링크만 허용한다.",
            )
        )

    if max_glibc is not None and max_glibc > glibc_ceiling:
        findings.append(
            AbiFinding(
                "GLIBC_TOO_NEW",
                f"요구 GLIBC_{max_glibc[0]}.{max_glibc[1]} > 실기 상한 "
                f"GLIBC_{glibc_ceiling[0]}.{glibc_ceiling[1]} — "
                "이 바이너리는 실기에서 로드되지 않는다.",
            )
        )

    for rp in rpaths:
        if rp.startswith("/"):
            findings.append(
                AbiFinding(
                    "ABSOLUTE_RPATH",
                    f"{rp}: RPATH/RUNPATH에 절대경로 — DPK 배포 위치가 바뀌면 링크가 깨진다. "
                    "$ORIGIN 기반 상대경로를 쓸 것.",
                )
            )

    return AbiCheckResult(binary=binary_name, findings=findings)


def _run_readelf(args: list[str], binary: Path) -> str:
    proc = subprocess.run(
        ["readelf", *args, str(binary)],
        capture_output=True,
        text=True,
        check=False,
    )
    # 정적 바이너리(.dynamic 섹션 없음)는 readelf가 stderr 경고만 내고 0이 아닌
    # exit일 수 있다 — 그 자체는 실패가 아니다(검사할 동적 의존성이 없다는 뜻).
    # 다만 "도구 부재"와 "비-ELF 입력"은 통과가 아니라 실패여야 하므로, 그 판정은
    # 호출부(check_binary)가 ELF magic·FileNotFoundError로 별도 수행한다.
    return proc.stdout


ELF_MAGIC = b"\x7fELF"


def is_elf(binary: Path) -> bool:
    """파일의 첫 4바이트로 ELF 여부를 판정한다(readelf 출력 파싱에 의존하지 않는다)."""
    try:
        with binary.open("rb") as f:
            return f.read(4) == ELF_MAGIC
    except OSError:
        return False


def check_binary(
    binary: Path,
    *,
    glibc_ceiling: tuple[int, int] = DEFAULT_MAX_GLIBC,
    allow_nvidia_libs: bool = False,
) -> AbiCheckResult:
    """실제 파일을 읽어 판정한다 — 입력이 검사 가능한 형태인지 먼저 확인한다.

    fail-open 방지: readelf가 없거나(도구 부재) 입력이 ELF가 아니면 stdout이 비어
    "NEEDED 0건 = 통과"로 읽히던 문제가 있었다(2026-08-04 감사). 이 저장소가 과거
    겪은 "러너에 rg가 없어 가드가 조용한 no-op이 된" 사고와 같은 클래스라, 둘 다
    명시적 실패로 전환한다.
    """
    if not is_elf(binary):
        return AbiCheckResult(
            binary=str(binary),
            findings=[
                AbiFinding(
                    "NOT_AN_ELF",
                    f"{binary}: ELF 매직(\\x7fELF)이 아니다 — 검사 대상이 아니거나 파일이 "
                    "손상됐다. 통과로 처리하지 않는다.",
                )
            ],
        )

    try:
        dynamic_output = _run_readelf(["-d"], binary)
        version_output = _run_readelf(["-V"], binary)
    except FileNotFoundError:
        return AbiCheckResult(
            binary=str(binary),
            findings=[
                AbiFinding(
                    "READELF_UNAVAILABLE",
                    "readelf(binutils)를 실행할 수 없다 — 이 게이트는 검사를 수행하지 "
                    "못했다. 검사 미수행을 통과로 위장하지 않는다(binutils 설치 필요).",
                )
            ],
        )

    return evaluate_binary(
        binary_name=str(binary),
        needed=parse_needed(dynamic_output),
        rpaths=parse_rpaths(dynamic_output),
        max_glibc=parse_max_glibc_requirement(version_output),
        glibc_ceiling=glibc_ceiling,
        allow_nvidia_libs=allow_nvidia_libs,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "binaries", nargs="+", type=Path, help="검사할 ELF 실행파일/라이브러리 경로"
    )
    parser.add_argument(
        "--allow-nvidia-libs",
        action="store_true",
        help="TensorRT/CUDA 등 장비 제공 NVIDIA 런타임 동적 링크를 허용한다(명시적 opt-in)",
    )
    parser.add_argument(
        "--glibc-ceiling",
        default=f"{DEFAULT_MAX_GLIBC[0]}.{DEFAULT_MAX_GLIBC[1]}",
        help="실기 glibc 상한(기본: 실측값 2.31)",
    )
    args = parser.parse_args(argv)

    major, minor = (int(x) for x in args.glibc_ceiling.split("."))
    exit_code = 0
    for binary in args.binaries:
        if not binary.is_file():
            print(f"✗ {binary}: 파일 없음", file=sys.stderr)
            exit_code = 1
            continue
        result = check_binary(
            binary, glibc_ceiling=(major, minor), allow_nvidia_libs=args.allow_nvidia_libs
        )
        if result.ok:
            print(f"✓ {binary}")
        else:
            exit_code = 1
            print(f"✗ {binary}", file=sys.stderr)
            for f in result.findings:
                print(f"    [{f.code}] {f.detail}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
