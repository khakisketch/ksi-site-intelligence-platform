"""Shadow DPK의 DJI 기체 기동(motion-commanding) 경계를 검증한다.

이 도구는 세 사실을 의도적으로 분리한다.

1. KSI C/C++ source에 금지 header(``_FLIGHT_HEADERS``) include 또는
   금지 API(``_MOTION_SYMBOL_PREFIXES``) 직접 호출이 없는가.
2. 최종 ELF가 해결하지 못한 그 API의 외부 참조를 갖지 않는가.
3. 공식 PSDK static archive가 같은 object file에 남기는 *정의*까지 0개인가.

## 2026-08-15 — 경계 대상이 넓어졌다 (ADR-KSI-020)

원래 이 게이트는 ``DjiFlightController_*`` 한 계열만 봤다. 그런데 PSDK 3.16.0에는
**기체를 실제로 움직이는 API가 그 계열 말고도 더 있다** — 특히
``DjiWaypointV3_UploadKmzFile`` + ``DjiWaypointV3_Action(START)`` 두 줄이면
KMZ 임무를 기체에 올려 시동·이륙·비행·착륙까지 시킬 수 있다(공식 샘플
``samples/sample_c/module_sample/waypoint_v3/test_waypoint_v3.c`` 가 그 전 과정을
그대로 보여준다). ``DjiFlightController_`` 만 막는 게이트는 이 경로를 통과시킨다 —
즉 "KSI 바이너리는 기체를 못 움직인다"는 보증이 실제로는 성립하지 않았다.

또 하나: 원래 header 검사는 ``dji_flight_control.h`` 를 찾았는데 PSDK의 실제 파일명은
``dji_flight_controller.h`` 다. 존재하지 않는 이름을 찾고 있었으므로 header 층은
한 번도 발화할 수 없었다(호출·심볼 층이 받쳐서 경계 자체가 뚫린 건 아니다).

두 가지 모두 이 개정에서 닫는다. **경계 자체를 넓히는 결정이 아니라, 원래 선언한
경계("KSI 는 기체를 직접 움직이지 않는다")를 실제로 강제하게 만드는 수정이다.**

1·2는 KSI가 직접 보장할 수 있는 shadow-only 경계라 기본 실행에서 실패 사유다.
3은 ``--require-zero-defined-symbols``일 때만 실패로 승격한다. PSDK 3.16.0의
``dji_error.c.o``는 generic error mapping과
``DjiFlightController_GetDjiErrorCode``를 한 section에 함께 넣어, KSI가 해당 함수를
호출하지 않아도 정의 하나가 ELF에 남는다. 이를 strip/rename해 검사만 통과시키지 않고
명시적 strict gate로 계속 보고한다.

직접 호출 판정은 source scan, ``nm -u``, 그리고 objdump의 branch/call target을 함께
쓴다. 단순히 ``nm``의 정의가 보인다는 이유만으로 KSI call로 오판하지 않는다.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_ELF_MAGIC = b"\x7fELF"
_SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"})
#: 기체를 움직이거나 비행을 종료시키는 PSDK 3.16.0 header. 파일명은 실측이다
#: (``edge/third_party/psdk/psdk_lib/include/``) — 추정으로 적지 않는다.
_FLIGHT_HEADERS = (
    "dji_flight_controller.h",  # 이·착륙·RTH·joystick·긴급제동
    "dji_waypoint_v2.h",  # 임무 실행(구세대)
    "dji_waypoint_v3.h",  # KMZ 업로드 + 임무 START — 시동·이륙까지 포함
    "dji_interest_point.h",  # 관심지점 선회 비행
    "dji_fts.h",  # 비행종료장치(낙하산) 트리거
)
#: 위 header가 노출하는 함수 계열. header include 없이 extern 선언만으로 부르는
#: 우회를 막으려면 심볼 쪽도 같은 집합이어야 한다.
_MOTION_SYMBOL_PREFIXES = (
    "DjiFlightController",
    "DjiWaypointV2",
    "DjiWaypointV3",
    "DjiInterestPoint",
    "DjiFts",
)

_HEADER_ALTERNATION = "|".join(re.escape(header) for header in _FLIGHT_HEADERS)
_SYMBOL_ALTERNATION = "|".join(_MOTION_SYMBOL_PREFIXES)

_FLIGHT_HEADER_RE = re.compile(
    rf'^[^\S\r\n]*#\s*include\s*[<"](?:{_HEADER_ALTERNATION})[>"]', re.MULTILINE
)
_FLIGHT_CALL_RE = re.compile(rf"\b((?:{_SYMBOL_ALTERNATION})_[A-Za-z0-9_]*)\s*\(")
_FLIGHT_SYMBOL_RE = re.compile(rf"\b((?:{_SYMBOL_ALTERNATION})_[A-Za-z0-9_]*)\b")
_OBJDUMP_DIRECT_CALL_RE = re.compile(
    rf"\b(?:bl|blx|callq?|jal)\b[^\n<]*<(?P<symbol>(?:{_SYMBOL_ALTERNATION})_[A-Za-z0-9_]*)>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FlightBoundaryResult:
    """검사 결과. strict vendor-symbol 상태는 direct boundary와 분리한다."""

    source_violations: tuple[str, ...] = ()
    undefined_symbols: tuple[str, ...] = ()
    direct_call_symbols: tuple[str, ...] = ()
    defined_symbols: tuple[str, ...] = ()
    tool_errors: tuple[str, ...] = ()

    @property
    def direct_boundary_ok(self) -> bool:
        return not (
            self.source_violations
            or self.undefined_symbols
            or self.direct_call_symbols
            or self.tool_errors
        )

    @property
    def strict_zero_symbols_ok(self) -> bool:
        return self.direct_boundary_ok and not self.defined_symbols


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def strip_c_comments(text: str) -> str:
    """C/C++ comment만 공백으로 치환한다. 문자열과 줄 수는 보존한다."""
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if current == "/" and following == "/":
                output.extend((" ", " "))
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                output.extend((" ", " "))
                index += 2
                state = "block_comment"
                continue
            output.append(current)
            if current in ('"', "'"):
                state = "literal"
                quote = current
            index += 1
            continue
        if state == "line_comment":
            output.append("\n" if current == "\n" else " ")
            if current == "\n":
                state = "code"
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                output.extend((" ", " "))
                index += 2
                state = "code"
                continue
            output.append("\n" if current == "\n" else " ")
            index += 1
            continue

        # string/character literal. Keep it untouched here so #include detection
        # can still distinguish a real quoted include from a comment.
        output.append(current)
        if current == "\\" and index + 1 < len(text):
            output.append(text[index + 1])
            index += 2
            continue
        if current == quote:
            state = "code"
        index += 1
    return "".join(output)


def strip_c_literals(text: str) -> str:
    """C/C++ string·character literal content을 공백으로 치환한다."""
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        current = text[index]
        if state == "code":
            output.append(current)
            if current in ('"', "'"):
                state = "literal"
                quote = current
            index += 1
            continue

        output.append("\n" if current == "\n" else " ")
        if current == "\\" and index + 1 < len(text):
            next_character = text[index + 1]
            output.append("\n" if next_character == "\n" else " ")
            index += 2
            continue
        if current == quote:
            state = "code"
        index += 1
    return "".join(output)


def scan_source_text(text: str, *, display_path: str) -> tuple[str, ...]:
    """한 소스 파일에서 실제 header/call token만 찾아 line-labelled 위반을 만든다."""
    without_comments = strip_c_comments(text)
    violations: list[str] = []
    for match in _FLIGHT_HEADER_RE.finditer(without_comments):
        line = _line_number(without_comments, match.start())
        violations.append(f"{display_path}:{line}: forbidden header")
    without_literals = strip_c_literals(without_comments)
    for match in _FLIGHT_CALL_RE.finditer(without_literals):
        violations.append(
            f"{display_path}:{_line_number(without_literals, match.start())}: "
            f"forbidden direct call {match.group(1)}"
        )
    return tuple(violations)


def scan_source_roots(source_roots: Sequence[Path]) -> tuple[str, ...]:
    """지정 source root의 C/C++ 파일 전체를 검사한다. 누락 root도 fail-closed다."""
    violations: list[str] = []
    for root in source_roots:
        if not root.is_dir():
            violations.append(f"{root}: source root does not exist or is not a directory")
            continue
        for path in sorted(path for path in root.rglob("*") if path.suffix in _SOURCE_SUFFIXES):
            if not path.is_file():
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"{path}: cannot read source: {exc}")
                continue
            except UnicodeDecodeError:
                violations.append(f"{path}: source is not UTF-8; cannot inspect flight boundary")
                continue
            violations.extend(scan_source_text(source, display_path=str(path)))
    return tuple(violations)


def parse_flight_symbols(text: str) -> tuple[str, ...]:
    """``nm`` 출력의 FlightController symbol을 stable order로 deduplicate한다."""
    return tuple(sorted(set(_FLIGHT_SYMBOL_RE.findall(text))))


def parse_objdump_direct_calls(text: str) -> tuple[str, ...]:
    """disassembly의 named direct branch/call target만 추출한다.

    ``DjiFlightController_*`` 함수의 label 자체는 call이 아니다. ``bl``/``call``/``jal``
    mnemonic와 함께 나온 target만 direct invocation 증거로 취급한다.
    """
    symbols = {match.group("symbol") for match in _OBJDUMP_DIRECT_CALL_RE.finditer(text)}
    return tuple(sorted(symbols))


def _run_tool(command: Sequence[str]) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None, f"required tool unavailable: {command[0]}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if not detail:
            detail = f"exit {completed.returncode}"
        return None, f"{' '.join(command[:2])} failed: {detail}"
    return completed.stdout, None


def _objdump_output(binary: Path, requested_tool: str | None) -> tuple[str | None, str | None]:
    candidates = [requested_tool] if requested_tool else []
    candidates.extend(("aarch64-linux-gnu-objdump", "objdump", "llvm-objdump"))
    errors: list[str] = []
    seen: set[str] = set()
    for tool in candidates:
        if not tool or tool in seen:
            continue
        seen.add(tool)
        if shutil.which(tool) is None:
            errors.append(f"required tool unavailable: {tool}")
            continue
        output, error = _run_tool((tool, "-d", str(binary)))
        if error is None:
            return output, None
        errors.append(error)
    return None, "; ".join(errors)


def check_flight_boundary(
    *,
    binary: Path,
    source_roots: Sequence[Path],
    nm_tool: str = "nm",
    objdump_tool: str | None = None,
) -> FlightBoundaryResult:
    """실제 source와 ELF 양쪽을 검사한다. 도구/ELF 불능은 fail-closed다."""
    source_violations = scan_source_roots(source_roots)
    tool_errors: list[str] = []
    if not binary.is_file():
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: binary does not exist",),
        )
    try:
        is_elf = binary.read_bytes()[:4] == _ELF_MAGIC
    except OSError as exc:
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: cannot read binary: {exc}",),
        )
    if not is_elf:
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: not an ELF binary",),
        )

    undefined_output, undefined_error = _run_tool((nm_tool, "-u", str(binary)))
    defined_output, defined_error = _run_tool((nm_tool, "--defined-only", str(binary)))
    disassembly, objdump_error = _objdump_output(binary, objdump_tool)
    for error in (undefined_error, defined_error, objdump_error):
        if error:
            tool_errors.append(error)
    return FlightBoundaryResult(
        source_violations=source_violations,
        undefined_symbols=parse_flight_symbols(undefined_output or ""),
        direct_call_symbols=parse_objdump_direct_calls(disassembly or ""),
        defined_symbols=parse_flight_symbols(defined_output or ""),
        tool_errors=tuple(tool_errors),
    )


def _print_result(result: FlightBoundaryResult, *, strict: bool) -> int:
    for violation in result.source_violations:
        print(f"✗ source: {violation}", file=sys.stderr)
    for symbol in result.undefined_symbols:
        print(f"✗ unresolved Flight Control symbol: {symbol}", file=sys.stderr)
    for symbol in result.direct_call_symbols:
        print(f"✗ direct Flight Control call in ELF: {symbol}", file=sys.stderr)
    for error in result.tool_errors:
        print(f"✗ gate unavailable: {error}", file=sys.stderr)

    if not result.direct_boundary_ok:
        return 1

    print("✓ KSI source and direct ELF call boundary contain no DJI Flight Control invocation")
    if result.defined_symbols:
        names = ", ".join(result.defined_symbols)
        if strict:
            print(f"✗ strict zero-symbol gate failed: {names}", file=sys.stderr)
            return 1
        print(
            f"! vendor-defined Flight Control symbol(s) retained: {names}; "
            "run with --require-zero-defined-symbols to make this an error",
            file=sys.stderr,
        )
    elif strict:
        print("✓ strict zero-symbol gate passed")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="검사할 target ELF")
    parser.add_argument(
        "source_roots",
        type=Path,
        nargs="+",
        help="검사할 KSI C/C++ source root (예: edge/psdk-app/src)",
    )
    parser.add_argument("--nm", default="nm", help="nm executable (기본: nm)")
    parser.add_argument("--objdump", help="objdump executable (기본: aarch64 우선 자동 탐색)")
    parser.add_argument(
        "--require-zero-defined-symbols",
        action="store_true",
        help="vendor archive의 defined FlightController symbol도 0개가 아니면 실패한다",
    )
    args = parser.parse_args(argv)
    result = check_flight_boundary(
        binary=args.binary,
        source_roots=args.source_roots,
        nm_tool=args.nm,
        objdump_tool=args.objdump,
    )
    return _print_result(result, strict=args.require_zero_defined_symbols)


if __name__ == "__main__":
    raise SystemExit(main())
