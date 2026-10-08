"""Shadow DPK의 DJI 기체 기동(motion-commanding) 경계를 검증한다.

이 도구는 세 사실을 의도적으로 분리한다.

1. KSI C/C++ source에 금지 header(``_FLIGHT_HEADERS``) include 또는
   금지 비행/카메라/짐벌 action API 직접 호출이 없는가.
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

## 2026-08-16 — 자물쇠를 둘로 나눈다 (ADR-KSI-021)

대표자가 임무 실행(``DjiWaypointV3_*``)을 **단계적으로** 승인했다(C2-S0~S4). 이
파일이 다루는 것은 그 중 **빌드 자물쇠**뿐이다 — "이 바이너리가 그 함수를 부를 수
있는가". "지금 이 기체가 실제로 부를 것인가"는 런타임 서명 인가(Core가 발급하는
비행 인가 + 현장 arming)의 몫이고 이 파일과 무관하다. 자물쇠를 둘로 나눈 이유는
가장 위험한 전이(실제 이륙)가 새 심볼 허용 없이 서명 한 필드로만 열리고 닫히게
하기 위해서다 — 되돌리기가 재빌드를 요구하지 않는다.

**단계별로 허용되는 심볼의 전체 집합은 이 파일에 하드코딩된다**(``_STAGE_SYMBOL_UNIVERSE``).
매니페스트(``edge/flight-execution-allowlist.v1.json``)는 그 **부분집합만** 고를 수
있다 — 매니페스트를 편집하는 것만으로 상위 단계의 심볼을 열 수 없다. 그리고
``DjiFlightController_*``·``DjiWaypointV2_*``·``DjiInterestPoint_*``·``DjiFts_*``
4개 계열은 **어느 단계 유니버스에도 없다** — 영구 차단이며 매니페스트로도 코드
수정으로도(이 파일을 고치지 않는 한) 못 연다.

매니페스트가 없거나 비어 있으면(단계 미지정 = C2-S0) 이 게이트는 **2026-08-15
이전과 완전히 동일하게** 동작한다 — 즉 오늘까지의 보증이 회귀 없이 유지된다.
``tests/contract/test_shadow_flight_boundary_gate.py`` 의 기존 판정들이 문구
그대로 이를 고정한다.

1·2는 KSI가 직접 보장할 수 있는 shadow-only 경계라 기본 실행에서 실패 사유다.
3은 비행 심볼에 대해서만 ``--require-zero-defined-symbols``일 때 실패로 승격한다.
카메라/짐벌은 공식 archive가 많은 action 정의를 포함하므로 정의 자체를 KSI 호출로
오인하지 않고, source·undefined reference·objdump direct-call 세 층만 적용한다.
PSDK 3.16.0의
``dji_error.c.o``는 generic error mapping과
``DjiFlightController_GetDjiErrorCode``를 한 section에 함께 넣어, KSI가 해당 함수를
호출하지 않아도 정의 하나가 ELF에 남는다. 이를 strip/rename해 검사만 통과시키지 않고
명시적 strict gate로 계속 보고한다. 매니페스트가 ``knownVendorDefinitions`` 로
그런 벤더 정의를 선언하면, strict 층은 그 집합과의 **차집합**만 보고한다 — 매
빌드마다 같은 벤더 잡음을 다시 설명하지 않는다.

직접 호출 판정은 source scan, ``nm -u``, 그리고 objdump의 branch/call target을 함께
쓴다. 단순히 ``nm``의 정의가 보인다는 이유만으로 KSI call로 오판하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

_ELF_MAGIC = b"\x7fELF"
_SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"})

#: 기체를 움직이거나 비행을 종료시키는 PSDK 3.16.0 header. 파일명은 실측이다
#: (``edge/third_party/psdk/psdk_lib/include/``) — 추정으로 적지 않는다.
_FLIGHT_HEADERS = (
    "dji_flight_controller.h",  # 이·착륙·RTH·joystick·긴급제동 — 영구 차단
    "dji_waypoint_v2.h",  # 임무 실행(구세대) — 영구 차단
    "dji_waypoint_v3.h",  # KMZ 업로드 + 임무 START — 단계적 개방 대상
    "dji_interest_point.h",  # 관심지점 선회 비행 — 영구 차단
    "dji_fts.h",  # 비행종료장치(낙하산) 트리거 — 영구 차단
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

# HIL-1은 업링크 검증 중 카메라 촬영/설정/저장소 변경이나 짐벌 운동을 일으키면
# non-actuating이 아니다. 다만 Camera Manager의 Get/Download/rights와 Init/DeInit은
# 기존 read-only media 경로에 필요하므로 차단하지 않는다. 아래 동사 집합은 핀된
# PSDK 3.16 헤더의 직접 상태변경/action API만 포괄한다.
_CAMERA_GIMBAL_ACTION_PATTERNS = (
    r"DjiCameraManager_(?:Set|Start|Stop|Reset|Format|Delete|Enable|Disable|Unlock|Change|Tap|Trigger)[A-Za-z0-9_]*",
    r"DjiGimbalManager_(?:Set|Reset|Rotate|Restore)[A-Za-z0-9_]*",
)

_HEADER_ALTERNATION = "|".join(re.escape(header) for header in _FLIGHT_HEADERS)
_SYMBOL_ALTERNATION = "|".join(_MOTION_SYMBOL_PREFIXES)
_DIRECT_SYMBOL_PATTERN = (
    rf"(?:(?:{_SYMBOL_ALTERNATION})_[A-Za-z0-9_]*|"
    + "|".join(_CAMERA_GIMBAL_ACTION_PATTERNS)
    + ")"
)

_FLIGHT_HEADER_RE = re.compile(
    rf'^[^\S\r\n]*#\s*include\s*[<"](?:{_HEADER_ALTERNATION})[>"]', re.MULTILINE
)
_FLIGHT_CALL_RE = re.compile(rf"\b({_DIRECT_SYMBOL_PATTERN})\s*\(")
_FLIGHT_SYMBOL_RE = re.compile(rf"\b((?:{_SYMBOL_ALTERNATION})_[A-Za-z0-9_]*)\b")
_DIRECT_SYMBOL_RE = re.compile(rf"\b({_DIRECT_SYMBOL_PATTERN})\b")
_OBJDUMP_FUNCTION_RE = re.compile(r"^[0-9a-fA-F]+ <(?P<symbol>[^>]+)>:")
_OBJDUMP_DIRECT_CALL_RE = re.compile(
    rf"\b(?:bl|blx|callq?|jal)\b[^\n<]*<(?P<symbol>{_DIRECT_SYMBOL_PATTERN})>",
    re.IGNORECASE,
)
_VENDOR_CAMERA_GIMBAL_CALLER_RE = re.compile(r"^Dji(?:CameraManager|GimbalManager)_")
_CAMERA_GIMBAL_ACTION_RE = re.compile(
    rf"^(?:{'|'.join(_CAMERA_GIMBAL_ACTION_PATTERNS)})$"
)

# --- ADR-KSI-021: 단계별 심볼 유니버스 (코드 고정, 매니페스트가 못 넓힌다) --------

#: 임무 실행(WaypointV3)만 단계적으로 연다. 헤더 실측 근거는 dji_waypoint_v3.h
#: (2026-08-15 PSDK 3.16.0 확인). ``DeInit`` 은 대문자 I — 오타 하나가 allowlist를
#: 조용히 무력화하므로 이 상수가 유일한 정본이다.
_WAYPOINT_V3_UPLOAD_ONLY_SYMBOLS = frozenset(
    {
        "DjiWaypointV3_Init",
        "DjiWaypointV3_DeInit",
        "DjiWaypointV3_UploadKmzFile",
        "DjiWaypointV3_RegMissionStateCallback",
        "DjiWaypointV3_RegActionStateCallback",
    }
)
#: S2부터는 여기에 ``Action`` 하나만 더한다 — 시동·이륙까지 가는 유일한 함수.
_WAYPOINT_V3_START_SYMBOLS = _WAYPOINT_V3_UPLOAD_ONLY_SYMBOLS | {"DjiWaypointV3_Action"}

#: 단계 순서. 매니페스트의 ``stage`` 는 이 중 하나여야 한다.
STAGE_ORDER: tuple[str, ...] = ("C2-S0", "C2-S1", "C2-S2", "C2-S3", "C2-S4")

#: 단계별로 **허용 가능한 최대 집합**(유니버스). 매니페스트는 이 부분집합만 고를 수
#: 있다 — 초과분은 로딩 단계에서 거부한다(스캔까지 가지 않는다).
_STAGE_SYMBOL_UNIVERSE: dict[str, frozenset[str]] = {
    "C2-S0": frozenset(),
    "C2-S1": _WAYPOINT_V3_UPLOAD_ONLY_SYMBOLS,
    "C2-S2": _WAYPOINT_V3_START_SYMBOLS,
    "C2-S3": _WAYPOINT_V3_START_SYMBOLS,  # 빌드 자물쇠는 S2와 동일 — 여는 건 런타임 인가뿐
    "C2-S4": _WAYPOINT_V3_START_SYMBOLS,
}
#: 단계별로 허용 가능한 header 유니버스. WaypointV3 하나뿐이며, 4계열 영구 차단
#: 헤더는 어느 단계에도 없다.
_STAGE_HEADER_UNIVERSE: dict[str, frozenset[str]] = {
    "C2-S0": frozenset(),
    "C2-S1": frozenset({"dji_waypoint_v3.h"}),
    "C2-S2": frozenset({"dji_waypoint_v3.h"}),
    "C2-S3": frozenset({"dji_waypoint_v3.h"}),
    "C2-S4": frozenset({"dji_waypoint_v3.h"}),
}
#: 영구 차단 계열 — 어느 단계 유니버스에도 등장하지 않는다는 것을 시험이 직접
#: assert한다(test_shadow_flight_boundary_gate.py::test_4계열은_영구히_차단된다류).
PERMANENTLY_BLOCKED_PREFIXES: frozenset[str] = frozenset(
    {"DjiFlightController", "DjiWaypointV2", "DjiInterestPoint", "DjiFts"}
)
PERMANENTLY_BLOCKED_HEADERS: frozenset[str] = frozenset(
    {"dji_flight_controller.h", "dji_waypoint_v2.h", "dji_interest_point.h", "dji_fts.h"}
)

#: 임무 실행 어댑터가 살 수 있는 유일한 디렉터리(반드시 이 안에서만, 파일 수 상한).
_FLIGHT_EXECUTION_MODULE_DIR = "edge/psdk-app/src/flight_execution/"
_MAX_ALLOWED_FILES = 4


class AllowlistError(ValueError):
    """매니페스트가 fail-closed로 거부됐다 — typed 예외, 조용히 빈 값으로 안 떨어진다."""


@dataclass(frozen=True)
class AllowlistEntry:
    symbol: str
    header: str
    allowed_in: tuple[str, ...]
    rationale: str = ""
    evidence_ref: str = ""


@dataclass(frozen=True)
class FlightExecutionAllowlist:
    """빌드 자물쇠의 현재 개방 범위. 매니페스트 파일 1개에서 로드한다."""

    stage: str = "C2-S0"
    decision_ref: str = ""
    adr_ref: str = ""
    approved_by: str = ""
    approved_at: str = ""
    entries: tuple[AllowlistEntry, ...] = ()
    known_vendor_definitions: frozenset[str] = field(default_factory=frozenset)
    source_path: Path | None = None

    @property
    def symbols(self) -> frozenset[str]:
        return frozenset(entry.symbol for entry in self.entries)

    @property
    def allowed_files(self) -> frozenset[str]:
        result: set[str] = set()
        for entry in self.entries:
            result.update(entry.allowed_in)
        return frozenset(result)

    def permits_call(self, symbol: str, display_path: str) -> bool:
        return any(
            entry.symbol == symbol and display_path in entry.allowed_in for entry in self.entries
        )

    def permits_header(self, header: str, display_path: str) -> bool:
        return any(
            entry.header == header and display_path in entry.allowed_in for entry in self.entries
        )

    def permits_link(self, symbol: str) -> bool:
        return symbol in self.symbols

    def unused_entries(self, *, called_symbols: frozenset[str]) -> tuple[AllowlistEntry, ...]:
        """소스 어디에서도 실제로 호출되지 않는 허가 — 죽은 허가가 쌓이는 것을 막는다."""
        return tuple(entry for entry in self.entries if entry.symbol not in called_symbols)


_EMPTY_ALLOWLIST = FlightExecutionAllowlist()


def load_flight_execution_allowlist(path: Path | None) -> FlightExecutionAllowlist:
    """매니페스트를 로드한다. 없으면 빈 S0(=오늘까지의 보증)을 반환한다.

    매니페스트가 있는데 형식이 틀리면 **조용히 빈 값으로 떨어지지 않는다** — 그러면
    오류의 성격이 "설정이 깨졌다"가 아니라 "소스 위반"으로 잘못 보고되어, 사람이
    엉뚱한 곳(소스)을 고치러 간다. 대신 :class:`AllowlistError` 를 던져 호출자가
    tool_errors로 fail-closed 보고하게 한다.
    """
    if path is None:
        return _EMPTY_ALLOWLIST
    if not path.is_file():
        raise AllowlistError(f"{path}: allowlist manifest가 지정됐으나 파일이 없다")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistError(f"{path}: allowlist manifest를 읽을 수 없다: {exc}") from exc
    if not isinstance(raw, dict):
        raise AllowlistError(f"{path}: allowlist manifest는 object여야 한다")

    stage = raw.get("stage")
    if stage not in STAGE_ORDER:
        raise AllowlistError(f"{path}: 알 수 없는 stage {stage!r} — {STAGE_ORDER} 중 하나여야 한다")

    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise AllowlistError(f"{path}: entries는 배열이어야 한다")

    symbol_universe = _STAGE_SYMBOL_UNIVERSE[stage]
    header_universe = _STAGE_HEADER_UNIVERSE[stage]
    entries: list[AllowlistEntry] = []
    seen_pairs: set[tuple[str, str]] = set()
    allowed_files: set[str] = set()

    for index, raw_entry in enumerate(entries_raw):
        if not isinstance(raw_entry, dict):
            raise AllowlistError(f"{path}: entries[{index}]는 object여야 한다")
        symbol = raw_entry.get("symbol")
        header = raw_entry.get("header")
        allowed_in = raw_entry.get("allowedIn")
        if not isinstance(symbol, str) or not symbol:
            raise AllowlistError(f"{path}: entries[{index}].symbol이 없거나 문자열이 아니다")
        if not isinstance(header, str) or not header:
            raise AllowlistError(f"{path}: entries[{index}].header가 없거나 문자열이 아니다")
        if not isinstance(allowed_in, list) or not allowed_in:
            raise AllowlistError(f"{path}: entries[{index}].allowedIn이 비었거나 배열이 아니다")
        if any(not isinstance(item, str) for item in allowed_in):
            raise AllowlistError(f"{path}: entries[{index}].allowedIn 원소는 전부 문자열이어야 한다")  # noqa: E501

        # 단계 유니버스 초과분은 로딩 단계에서 거부한다 — 매니페스트 편집만으로
        # 상위 단계 심볼을 여는 것을 막는 이중 잠금의 핵심.
        if symbol not in symbol_universe:
            raise AllowlistError(
                f"{path}: symbol {symbol!r} 는 stage {stage!r} 유니버스 밖이다 "
                f"(허용: {sorted(symbol_universe)})"
            )
        if header not in header_universe:
            raise AllowlistError(
                f"{path}: header {header!r} 는 stage {stage!r} 유니버스 밖이다 "
                f"(허용: {sorted(header_universe)})"
            )
        if symbol.split("_", 1)[0] in PERMANENTLY_BLOCKED_PREFIXES:
            raise AllowlistError(f"{path}: symbol {symbol!r} 는 영구 차단 계열이다")
        if header in PERMANENTLY_BLOCKED_HEADERS:
            raise AllowlistError(f"{path}: header {header!r} 는 영구 차단 대상이다")

        for allowed_path in allowed_in:
            normalized = allowed_path.replace("\\", "/")
            if not normalized.startswith(_FLIGHT_EXECUTION_MODULE_DIR):
                raise AllowlistError(
                    f"{path}: allowedIn 경로 {allowed_path!r} 는 "
                    f"{_FLIGHT_EXECUTION_MODULE_DIR} 밖이다"
                )
            allowed_files.add(normalized)

        pair = (symbol, header)
        if pair in seen_pairs:
            raise AllowlistError(f"{path}: entries[{index}] — ({symbol}, {header}) 중복 항목")
        seen_pairs.add(pair)

        entries.append(
            AllowlistEntry(
                symbol=symbol,
                header=header,
                allowed_in=tuple(allowed_in),
                rationale=str(raw_entry.get("rationale", "")),
                evidence_ref=str(raw_entry.get("evidenceRef", "")),
            )
        )

    if len(allowed_files) > _MAX_ALLOWED_FILES:
        raise AllowlistError(
            f"{path}: 허용 파일 {len(allowed_files)}개 — 상한 {_MAX_ALLOWED_FILES}개를 넘는다"
        )

    known_vendor_raw = raw.get("knownVendorDefinitions", [])
    if not isinstance(known_vendor_raw, list) or any(
        not isinstance(item, str) for item in known_vendor_raw
    ):
        raise AllowlistError(f"{path}: knownVendorDefinitions는 문자열 배열이어야 한다")

    return FlightExecutionAllowlist(
        stage=stage,
        decision_ref=str(raw.get("decisionRef", "")),
        adr_ref=str(raw.get("adrRef", "")),
        approved_by=str(raw.get("approvedBy", "")),
        approved_at=str(raw.get("approvedAt", "")),
        entries=tuple(entries),
        known_vendor_definitions=frozenset(known_vendor_raw),
        source_path=path,
    )


@dataclass(frozen=True)
class FlightBoundaryResult:
    """검사 결과. strict vendor-symbol 상태는 direct boundary와 분리한다."""

    source_violations: tuple[str, ...] = ()
    undefined_symbols: tuple[str, ...] = ()
    direct_call_symbols: tuple[str, ...] = ()
    defined_symbols: tuple[str, ...] = ()
    tool_errors: tuple[str, ...] = ()
    stale_allowlist_entries: tuple[str, ...] = ()
    allowlist_stage: str = "C2-S0"

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


def scan_source_text(
    text: str,
    *,
    display_path: str,
    allowlist: FlightExecutionAllowlist = _EMPTY_ALLOWLIST,
) -> tuple[str, ...]:
    """한 소스 파일에서 실제 header/call token만 찾아 line-labelled 위반을 만든다.

    ``allowlist`` 가 비어 있으면(기본값) 2026-08-15 이전과 완전히 동일하게 전부
    위반이다. 항목이 있으면 **그 심볼×그 파일 조합**만 면제된다 — 같은 파일에서
    허용 안 된 다른 계열을 부르면 여전히 위반이다.
    """
    without_comments = strip_c_comments(text)
    violations: list[str] = []
    for match in _FLIGHT_HEADER_RE.finditer(without_comments):
        # 매치 문자열에서 실제 header 파일명만 뽑는다.
        header_match = re.search(r'[<"]([^<>"]+)[>"]', match.group(0))
        header_name = header_match.group(1) if header_match else ""
        if allowlist.permits_header(header_name, display_path):
            continue
        line = _line_number(without_comments, match.start())
        violations.append(f"{display_path}:{line}: forbidden header")
    without_literals = strip_c_literals(without_comments)
    for match in _FLIGHT_CALL_RE.finditer(without_literals):
        symbol = match.group(1)
        if allowlist.permits_call(symbol, display_path):
            continue
        violations.append(
            f"{display_path}:{_line_number(without_literals, match.start())}: "
            f"forbidden direct call {symbol}"
        )
    return tuple(violations)


def scan_source_roots(
    source_roots: Sequence[Path],
    *,
    allowlist: FlightExecutionAllowlist = _EMPTY_ALLOWLIST,
) -> tuple[str, ...]:
    """지정 source root의 C/C++ 파일 전체를 검사한다. 누락 root도 fail-closed다."""
    violations: list[str] = []
    for root in source_roots:
        if not root.is_dir():
            violations.append(f"{root}: source root does not exist or is not a directory")
            continue
        for path in sorted(path for path in root.rglob("*") if path.suffix in _SOURCE_SUFFIXES):
            if not path.is_file():
                continue
            normalized = str(path).replace("\\", "/")
            candidate_marker = _FLIGHT_EXECUTION_MODULE_DIR.rstrip("/")
            if allowlist.stage == "C2-S0" and (
                normalized.startswith(candidate_marker)
                or f"/{candidate_marker}/" in f"/{normalized}"
            ):
                # Candidate S1 source is not linked into the default DPK. The default
                # binary nm/objdump layers still fail if it is accidentally compiled.
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"{path}: cannot read source: {exc}")
                continue
            except UnicodeDecodeError:
                violations.append(f"{path}: source is not UTF-8; cannot inspect flight boundary")
                continue
            violations.extend(
                scan_source_text(source, display_path=str(path), allowlist=allowlist)
            )
    return tuple(violations)


def scan_called_symbols(
    source_roots: Sequence[Path],
    *,
    prefixes: tuple[str, ...] = _MOTION_SYMBOL_PREFIXES,
) -> frozenset[str]:
    """실제로 호출된(선언이 아니라 call 형태로 등장한) 심볼 집합 — 잉여 allowlist 검출용."""
    called: set[str] = set()
    prefix_pattern = rf"(?:{'|'.join(re.escape(p) for p in prefixes)})_[A-Za-z0-9_]*"
    call_re = re.compile(
        rf"\b((?:{prefix_pattern}|{'|'.join(_CAMERA_GIMBAL_ACTION_PATTERNS)}))\s*\("
    )
    for root in source_roots:
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.suffix in _SOURCE_SUFFIXES):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            without_comments = strip_c_comments(text)
            without_literals = strip_c_literals(without_comments)
            called.update(match.group(1) for match in call_re.finditer(without_literals))
    return frozenset(called)


def parse_flight_symbols(text: str) -> tuple[str, ...]:
    """``nm`` 출력의 FlightController symbol을 stable order로 deduplicate한다."""
    return tuple(sorted(set(_FLIGHT_SYMBOL_RE.findall(text))))


def parse_prohibited_direct_symbols(text: str) -> tuple[str, ...]:
    """Return flight plus camera/gimbal action references, excluding mere vendor definitions."""

    return tuple(sorted(set(_DIRECT_SYMBOL_RE.findall(text))))


def _parse_objdump_direct_call_edges(text: str) -> frozenset[tuple[str, str]]:
    """Return named caller/target edges from one objdump disassembly."""

    edges: set[tuple[str, str]] = set()
    caller = ""
    for line in text.splitlines():
        function = _OBJDUMP_FUNCTION_RE.match(line)
        if function is not None:
            caller = function.group("symbol").split("+", 1)[0]
            continue
        match = _OBJDUMP_DIRECT_CALL_RE.search(line)
        if match is not None:
            edges.add((caller, match.group("symbol")))
    return frozenset(edges)


def parse_objdump_direct_calls(
    text: str, *, vendor_archive_text: str = ""
) -> tuple[str, ...]:
    """disassembly의 named direct branch/call target만 추출한다.

    ``DjiFlightController_*`` 함수의 label 자체는 call이 아니다. ``bl``/``call``/``jal``
    mnemonic와 함께 나온 target만 direct invocation 증거로 취급한다.
    """
    symbols: set[str] = set()
    vendor_edges = _parse_objdump_direct_call_edges(vendor_archive_text)
    for caller, target in _parse_objdump_direct_call_edges(text):
        # Static libpayloadsdk.a contains Camera/Gimbal action implementations
        # that call other vendor action implementations.  A final-ELF target
        # match alone cannot turn that vendor-internal edge into a KSI call. An
        # exact caller/target edge also present in the pinned archive is vendor
        # provenance, including lower-case internal helper callers.
        # Source and undefined-reference layers still catch KSI direct use; an
        # actual KSI call edge in this disassembly is retained here.
        if (
            _CAMERA_GIMBAL_ACTION_RE.fullmatch(target) is not None
            and (
                (caller, target) in vendor_edges
                or _VENDOR_CAMERA_GIMBAL_CALLER_RE.match(caller) is not None
            )
        ):
            continue
        symbols.add(target)
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
    vendor_archive: Path | None = None,
    allowlist: FlightExecutionAllowlist = _EMPTY_ALLOWLIST,
) -> FlightBoundaryResult:
    """실제 source와 ELF 양쪽을 검사한다. 도구/ELF 불능은 fail-closed다."""
    source_violations = scan_source_roots(source_roots, allowlist=allowlist)
    called_symbols = scan_called_symbols(source_roots)
    stale_entries = tuple(
        f"{entry.symbol} in {', '.join(entry.allowed_in)}"
        for entry in allowlist.unused_entries(called_symbols=called_symbols)
    )
    tool_errors: list[str] = []
    if not binary.is_file():
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: binary does not exist",),
            stale_allowlist_entries=stale_entries,
            allowlist_stage=allowlist.stage,
        )
    try:
        is_elf = binary.read_bytes()[:4] == _ELF_MAGIC
    except OSError as exc:
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: cannot read binary: {exc}",),
            stale_allowlist_entries=stale_entries,
            allowlist_stage=allowlist.stage,
        )
    if not is_elf:
        return FlightBoundaryResult(
            source_violations=source_violations,
            tool_errors=(f"{binary}: not an ELF binary",),
            stale_allowlist_entries=stale_entries,
            allowlist_stage=allowlist.stage,
        )

    undefined_output, undefined_error = _run_tool((nm_tool, "-u", str(binary)))
    defined_output, defined_error = _run_tool((nm_tool, "--defined-only", str(binary)))
    disassembly, objdump_error = _objdump_output(binary, objdump_tool)
    vendor_disassembly: str | None = ""
    vendor_error: str | None = None
    if vendor_archive is not None:
        if not vendor_archive.is_file():
            vendor_error = f"{vendor_archive}: vendor archive does not exist"
        else:
            vendor_disassembly, vendor_error = _objdump_output(
                vendor_archive, objdump_tool
            )
    for error in (undefined_error, defined_error, objdump_error, vendor_error):
        if error:
            tool_errors.append(error)

    undefined_all = parse_prohibited_direct_symbols(undefined_output or "")
    direct_calls_all = parse_objdump_direct_calls(
        disassembly or "", vendor_archive_text=vendor_disassembly or ""
    )
    defined_all = parse_flight_symbols(defined_output or "")

    undefined_symbols = tuple(s for s in undefined_all if not allowlist.permits_link(s))
    direct_call_symbols = tuple(s for s in direct_calls_all if not allowlist.permits_link(s))
    # strict 층: reviewed stage symbols and known vendor definitions are expected;
    # any other motion definition remains a failure.
    defined_symbols = tuple(
        s
        for s in defined_all
        if s not in allowlist.symbols and s not in allowlist.known_vendor_definitions
    )

    return FlightBoundaryResult(
        source_violations=source_violations,
        undefined_symbols=undefined_symbols,
        direct_call_symbols=direct_call_symbols,
        defined_symbols=defined_symbols,
        tool_errors=tuple(tool_errors),
        stale_allowlist_entries=stale_entries,
        allowlist_stage=allowlist.stage,
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
    for stale in result.stale_allowlist_entries:
        print(f"! stale allowlist entry (never called): {stale}", file=sys.stderr)

    if not result.direct_boundary_ok:
        return 1

    if result.allowlist_stage == "C2-S0":
        print("✓ KSI source and direct ELF call boundary contain no DJI Flight Control invocation")
    else:
        print(
            f"✓ boundary ok — allowlist stage={result.allowlist_stage} "
            f"({len(result.stale_allowlist_entries) == 0 and '유효' or '잉여 항목 있음'})"
        )
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
        "--vendor-archive",
        type=Path,
        help=(
            "pinned libpayloadsdk.a used to subtract exact vendor-internal "
            "camera/gimbal call edges"
        ),
    )
    parser.add_argument(
        "--require-zero-defined-symbols",
        action="store_true",
        help="vendor archive의 defined FlightController symbol도 0개가 아니면 실패한다",
    )
    parser.add_argument(
        "--allow-mission-execution",
        type=Path,
        default=None,
        metavar="MANIFEST_JSON",
        help=(
            "flight-execution allowlist manifest 경로. 지정하지 않으면 C2-S0"
            "(2026-08-15 이전과 동일한 전면 차단)로 동작한다."
        ),
    )
    args = parser.parse_args(argv)
    try:
        allowlist = load_flight_execution_allowlist(args.allow_mission_execution)
    except AllowlistError as exc:
        print(f"✗ allowlist manifest rejected: {exc}", file=sys.stderr)
        return 1
    result = check_flight_boundary(
        binary=args.binary,
        source_roots=args.source_roots,
        nm_tool=args.nm,
        objdump_tool=args.objdump,
        vendor_archive=args.vendor_archive,
        allowlist=allowlist,
    )
    return _print_result(result, strict=args.require_zero_defined_symbols)


if __name__ == "__main__":
    raise SystemExit(main())
