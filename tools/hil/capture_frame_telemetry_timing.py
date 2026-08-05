"""Frame–Telemetry 시간차 실측 도구 (HARDWARE_SESSION_PLAYBOOK.md 7단계).

MASTER_PRD §21.1 "Sensor Timestamp alignment: p95 50ms 이하 목표"의 실측 도구다.
이 실측은 `docs/product/DOMAIN_INVARIANTS.md` INV-025의 전제조건이기도 하다 —
``WorldEntity.uncertainty.localization_state = CONFIRMED``는 ``CALIBRATED_POSE``
시점 증거를 요구하는데, 그 시점 증거의 정확도는 결국 Frame과 Telemetry가 실제로
얼마나 시간적으로 정렬돼 있는지에 달려 있다. 여기서 나온 p50/p95/max 없이는
"시간동기가 맞다"는 주장 자체가 근거가 없다(`docs/hil/CAPABILITY_ACCEPTANCE.md` 참고).

## P0-1: 측정(measurement_status) ≠ 목표달성(acceptance_status)

"측정을 성공적으로 수행했다"와 "요구사항(p95 ≤ 50ms)을 만족했다"는 다른 질문이다.
이 도구는 둘을 분리한 2축으로 판정을 출력한다(``judge_acceptance``) —
``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행이 이 2축의 SSOT다. 어느 쪽이든
사람이 임의로 PASS/VERIFIED를 선언할 근거로 이 스크립트의 출력을 오독해서는 안 된다.

## P0-2: 공식 Acceptance Profile은 CLI로 완화할 수 없다 + 증거 무결성 게이트

독립 재검토에서 지적된 두 우회 경로를 막는다:

1. **기준값 CLI 완화**: ``--target-p95-ms``/``--min-sample-count``/``--delta-tolerance-ms``를
   느슨한 값으로 주면 조작된 증거도 "PASS"로 보일 수 있었다. 이제 공식 판정 기준은
   :data:`OFFICIAL_PROFILE`(``profile_id="ksi-frame-telemetry-alignment-v1"``)에 고정되고,
   ``--mode official``(기본값)에서는 이 세 플래그를 CLI로 넘기는 것 자체가 오류다(값이
   무엇이든). 다른 값을 실험하고 싶다면 ``--mode exploratory``로만 가능하고, 그 결과는
   ``acceptance_status``가 항상 ``null``이며 VERIFIED 승격 근거로 쓸 수 없다.
2. **손상 줄 제외 후 PASS**: 검증에 실패한 줄(``rejected``)이 있어도 "남은 유효 표본"만으로
   PASS를 낼 수 있었고, 서로 다른 ``session_id``/``aircraft_sn``이 섞여도 목록만 출력하고
   거부하지 않았다. 이제 :func:`evaluate_evidence`가 독립된 ``evidence_status`` 축
   (``VALID``/``INVALID``)을 계산하고, :func:`judge_official`은 evidence가 ``INVALID``이면
   숫자상 PASS가 나오더라도 공식 ``acceptance_status``를 강제로 ``FAIL``로 내린다
   (``reason_code=EVIDENCE_INVALID``로 이유를 구분해서 남긴다 — "목표 미달"과 "증거
   자체가 무효"는 다른 사유다).

## 입력 JSONL은 신뢰하지 않는다 (증거 판정 도구 수준)

이 도구가 다루는 JSONL은 실기에서 수집된 원본 증거다 — 저장된 ``delta_ms``를 그대로
믿고 요약하면, 임의로 조작된(또는 손상된) 파일로 좋은 p95를 위조할 수 있다. 그래서
``load_frame_telemetry_jsonl``은 각 줄을 다음 기준으로 재검증하고, 위반 줄은 사유와
함께 거부한다(전체 로드를 막지 않되 조용히 사라지지도 않는다):

- 파일 전체의 UTF-8 decode 자체가 실패하면 전체를 표본 0건 + 거부 사유 1건으로 다룬다
  (예외로 프로그램을 죽이지 않는다 — 증거 판정 도구가 크래시하면 "판정 불가"라는
  사실 자체가 사라진다).
- JSON 파싱 자체가 NaN/Infinity/-Infinity 같은 비표준 상수를 거부한다.
- ``frame_timestamp_utc``/``telemetry_timestamp_utc``는 UTC(offset ``+00:00``,
  ``Z`` 서픽스 허용)가 아니면 거부한다.
- 저장된 ``delta_ms``는 두 timestamp로부터 재계산한 값과 tolerance(기본 0.5ms) 내에서
  일치해야 한다 — 벗어나면 위조/오기로 간주해 거부한다.
- ``session_id``/``aircraft_sn``은 공백일 수 없다.
- ``sample_index``는 음수 불가·중복 거부. 불연속은 거부하지 않되 경고로 남긴다.

그리고 파일이 통째로 "유효한 증거"인지는 줄 단위 검증과 별개로 :func:`evaluate_evidence`가
판정한다(중복 없어도 여러 세션/기체가 섞였거나 index가 0부터 시작하지 않으면 무효).

## 여러 세션·기체 합산 금지

``append_sample_jsonl``은 대상 파일에 이미 다른 ``session_id``/``aircraft_sn``의 표본이
있으면 append 자체를 거부한다(:func:`_existing_session_aircraft`) — 세션·기체 조합당
별도 파일·별도 Summary만 허용한다는 정책을 쓰기 시점에도 강제한다.

## 이 파일에서 완전히 구현된 것 / 아닌 것

- **완전 구현 + 순수 함수(단위테스트 가능)**: :func:`percentile`, :func:`summarize_deltas`,
  :func:`compute_delta_ms`, :func:`parse_utc_timestamp`, :func:`judge_acceptance`,
  :func:`evaluate_evidence`, :func:`judge_official`, :func:`judge_exploratory`,
  JSONL 직렬화/역직렬화·검증, ``summarize`` CLI 서브커맨드. 이미 수집된 JSONL 파일이
  있다면 실기 없이도 오늘 바로 돌릴 수 있다.
- **미구현(실기 세션에서 채움)**: :func:`read_next_frame_telemetry_timestamps` —
  DJI PSDK 콜백 연동 자리. 지금은 항상 ``NotImplementedError``를 낸다. 가짜 값으로
  채우면 "실기 미검증"을 숨기게 되므로(INV-040 정신), 절대 임시 return 값을 넣지 않는다.

## 사용법

```bash
# 실기 세션 중 수집(현재는 PSDK 미연동이라 NotImplementedError로 즉시 중단됨 — 의도된 동작)
uv run python tools/hil/capture_frame_telemetry_timing.py collect \\
    --session-id SESS-20260728T060000Z-<기체SN> \\
    --aircraft-sn <기체SN> \\
    --out hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \\
    --num-samples 200

# 이미 수집된 JSONL로부터 공식 판정(고정 Acceptance Profile, CLI로 완화 불가)
uv run python tools/hil/capture_frame_telemetry_timing.py summarize \\
    --in hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry.jsonl \\
    --out hil_raw_logs/SESS-.../07_frame_telemetry_timing/<UTC_ts>__frame_telemetry_summary.json

# 실험적으로 다른 기준값을 보고 싶을 때만(VERIFIED 근거로 쓸 수 없음)
uv run python tools/hil/capture_frame_telemetry_timing.py summarize \\
    --in ... --mode exploratory --target-p95-ms 80 --min-sample-count 20
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# exploratory 모드 전용 기본값 — 공식 판정 기준이 아니다(P0-2).
# 공식 판정 기준은 아래 OFFICIAL_PROFILE(고정 상수)만 쓴다. 숫자가 우연히 같더라도
# 의미는 다르다: 이 DEFAULT_* 는 --mode exploratory에서 사용자가 아무 값도 안 줬을 때
# 쓰는 "기본 실험값"이고, OFFICIAL_PROFILE은 --mode official(기본 모드)에서 CLI로
# 절대 바꿀 수 없는 값이다.
# --------------------------------------------------------------------------- #
DEFAULT_TARGET_P95_MS = 50.0
DEFAULT_MIN_SAMPLE_COUNT = 100
DEFAULT_DELTA_TOLERANCE_MS = 0.5

_REQUIRED_FIELDS = (
    "sample_index",
    "session_id",
    "aircraft_sn",
    "frame_timestamp_utc",
    "telemetry_timestamp_utc",
    "delta_ms",
)


# --------------------------------------------------------------------------- #
# 인자 검증 헬퍼 — CLI 경로뿐 아니라 함수를 직접 호출하는 경로(테스트 등)도 지킨다.
# --------------------------------------------------------------------------- #


def validate_positive_int(value: Any, *, name: str) -> int:
    """``value``가 bool이 아닌 1 이상의 정수인지 강제한다.

    ``bool``은 ``int``의 서브클래스라 ``isinstance(True, int)``가 ``True``이므로
    별도로 걸러낸다 — ``num_samples=True`` 같은 실수를 "1"로 조용히 받아들이지 않는다.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}는 bool이 아닌 정수여야 한다 (받음: {value!r})")
    if value <= 0:
        raise ValueError(f"{name}는 1 이상의 정수여야 한다 (받음: {value})")
    return value


def validate_finite_positive(value: Any, *, name: str) -> float:
    """``value``가 유한한 양수(0 불가, NaN/Infinity/bool 불가)인지 강제한다."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name}는 숫자여야 한다 (받음: {value!r})")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name}는 유한한 양수여야 한다 (받음: {value!r})")
    return numeric


def validate_finite_nonnegative(value: Any, *, name: str) -> float:
    """``value``가 유한하고 음수가 아닌지(0은 허용, NaN/Infinity/bool 불가) 강제한다."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name}는 숫자여야 한다 (받음: {value!r})")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name}는 유한하고 음수가 아니어야 한다 (받음: {value!r})")
    return numeric


def validate_nonblank_str(value: Any, *, name: str) -> str:
    """``value``가 공백이 아닌 문자열인지 강제한다."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}는 공백이 아닌 문자열이어야 한다 (받음: {value!r})")
    return value


# --------------------------------------------------------------------------- #
# 공식 Acceptance Profile (P0-2) — frozen 상수, CLI로 override 불가.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AcceptanceProfile:
    """Versioned Acceptance Profile.

    ``OFFICIAL_PROFILE``은 대표자 지정 기준(2026-07-28)에 따라 고정된 상수다.
    ``--mode official``(CLI 기본값)은 항상 이 값을 그대로 쓰고, 어떤 CLI 플래그로도
    override를 허용하지 않는다 — 기준을 완화할 수 있다면 "공식 PASS"라는 말 자체가
    증거가치를 잃는다. 다른 값을 실험하려면 ``--mode exploratory``로 별도 Profile을
    만든다(이 클래스를 그대로 재사용하되 ``profile_id``가 공식 ID와 다르다).
    """

    profile_id: str
    target_p95_ms: float
    min_sample_count: int
    delta_tolerance_ms: float

    def __post_init__(self) -> None:
        validate_nonblank_str(self.profile_id, name="profile_id")
        validate_finite_positive(self.target_p95_ms, name="target_p95_ms")
        validate_positive_int(self.min_sample_count, name="min_sample_count")
        validate_finite_nonnegative(self.delta_tolerance_ms, name="delta_tolerance_ms")


OFFICIAL_PROFILE = AcceptanceProfile(
    profile_id="ksi-frame-telemetry-alignment-v1",
    target_p95_ms=50.0,
    min_sample_count=100,
    delta_tolerance_ms=0.5,
)

# exploratory Profile의 profile_id는 항상 이 값이다 — OFFICIAL_PROFILE.profile_id와
# 절대 같을 수 없으므로("official profile ID 아님"을 값 자체로 명시), Summary만 봐도
# 이게 공식 판정이 아님을 알 수 있다.
EXPLORATORY_PROFILE_ID = "exploratory-adhoc"


# --------------------------------------------------------------------------- #
# 스키마
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FrameTelemetrySample:
    """Frame 수신 시각과 그에 대응하는 Telemetry 수신 시각 1쌍 (JSONL 1줄).

    Attributes:
        sample_index: 세션 내 순번(0부터 시작).
        session_id: ``docs/hil/RAW_LOG_CONVENTIONS.md`` 형식의 세션 ID.
        aircraft_sn: 기체 시리얼넘버.
        frame_timestamp_utc: 카메라 Frame 캡처/수신 시각(UTC, ISO 8601, ``Z`` 서픽스).
        telemetry_timestamp_utc: 그 Frame에 대응시킨 Telemetry 샘플의 시각
            (UTC, ISO 8601, ``Z`` 서픽스).
        delta_ms: ``frame_timestamp_utc - telemetry_timestamp_utc`` (밀리초). 부호가
            있다 — 양수면 Frame이 Telemetry보다 늦게 도착했다는 뜻이다. JSONL에서
            읽어들인 값은 두 timestamp로부터 재계산한 값이다(저장값을 그대로
            신뢰하지 않는다 — 모듈 docstring 참고).
        timestamp_basis: 이 표본의 timestamp가 어떤 정의로 찍혔는지 —
            ``"sensor"``(카메라/FC 장치 자체 타임스탬프) 또는 ``"recv"``(호스트가
            수신한 monotonic clock 기준 시각) 또는 ``None``(``--source psdk`` 경로 등
            basis 정보가 없는 기존 표본). **선택 필드다 — 6개 필수 필드에 포함되지
            않으며 ``_REQUIRED_FIELDS``/기존 검증 로직에 영향을 주지 않는다.**
            ``--timestamp-basis recv``로 낸 PASS를 "센서 시각 정합"으로 오독하지
            않도록 값을 보존해 summarize 출력까지 전파한다(``--source tap-log``
            변환 규칙 참고).
    """

    sample_index: int
    session_id: str
    aircraft_sn: str
    frame_timestamp_utc: str
    telemetry_timestamp_utc: str
    delta_ms: float
    timestamp_basis: str | None = None


@dataclass(frozen=True, slots=True)
class RejectedLine:
    """검증에 실패해 유효 표본에서 제외된 JSONL 줄 1건."""

    line_no: int
    reason: str


@dataclass(frozen=True, slots=True)
class FrameTelemetryLoadResult:
    """JSONL 파일 1개를 검증하며 읽은 결과 (증거 판정에 필요한 전체 맥락).

    Attributes:
        samples: 검증을 통과한 표본(파일 등장 순서).
        rejected: 검증에 실패해 제외된 줄(line_no 오름차순). ``line_no=0``은 파일
            전체 decode 실패처럼 특정 줄에 귀속되지 않는 거부를 뜻한다.
        warnings: 거부까지는 아니지만 기록해 둘 사항(예: sample_index 불연속).
        sha256: 입력 파일 원본 바이트의 SHA-256 hexdigest — 어떤 파일을 근거로
            판정했는지 증거로 고정한다.
        validation_profile_id: 이 결과를 만든 검증 조건의 profile ID —
            증거가 **어떤 기준으로 검증됐는지**를 결과 자체에 보존한다(독립 재검토
            P0: relaxed tolerance 로 로드한 결과를 공식 판정에 주입하는 우회 차단).
        validation_delta_tolerance_ms: 검증에 실제 사용된 delta 재계산 tolerance.
    """

    samples: tuple[FrameTelemetrySample, ...]
    rejected: tuple[RejectedLine, ...]
    warnings: tuple[str, ...]
    sha256: str
    validation_profile_id: str
    validation_delta_tolerance_ms: float


class MeasurementStatus(StrEnum):
    """측정을 성공적으로 수행했는가 (P0-1 2축 중 1축)."""

    MEASURED = "MEASURED"
    NOT_MEASURED = "NOT_MEASURED"


class AcceptanceStatus(StrEnum):
    """요구사항(p95 ≤ target)을 만족했는가 (P0-1 2축 중 1축).

    ``measurement_status=NOT_MEASURED``면 판정 대상 자체가 없으므로 이 값은 쓰이지
    않는다(``Acceptance.acceptance_status``가 ``None``이 된다).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"


class EvidenceStatus(StrEnum):
    """입력 파일 전체가 "공식 PASS 판정을 낼 자격이 있는 증거"인가 (P0-2, 측정 축과 별개).

    ``AcceptanceStatus``/``MeasurementStatus``가 "수치가 무엇인가"를 다루는 반면,
    이 축은 "그 수치를 낸 증거 파일 자체를 신뢰할 수 있는가"를 다룬다 — 거부된 줄이
    있거나, 서로 다른 세션/기체가 섞였거나, sample_index가 0부터 연속하지 않으면
    통계상 PASS가 나와도 ``INVALID``다(:func:`evaluate_evidence`).
    """

    VALID = "VALID"
    INVALID = "INVALID"


class AcceptanceReasonCode(StrEnum):
    """공식 판정(``judge_official``)이 그 ``acceptance_status``에 도달한 구체적 사유.

    "목표 미달(FAIL)"과 "증거 자체가 무효라서 FAIL로 강제됨"은 같은 ``FAIL``이어도
    운영상 의미가 다르므로(전자는 재측정, 후자는 재수집이 필요) 별도 코드로 남긴다.
    """

    OK = "OK"
    REQUIREMENT_NOT_MET = "REQUIREMENT_NOT_MET"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    NOT_MEASURED = "NOT_MEASURED"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


@dataclass(frozen=True, slots=True)
class Acceptance:
    """P0-1 2축 판정 결과 (``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행 SSOT).

    증거 무결성(``EvidenceStatus``)을 반영하지 않은 순수 통계 판정이다 — 공식 CLI
    출력은 이 값을 그대로 노출하지 않고 :func:`judge_official`을 거친다.
    """

    measurement_status: MeasurementStatus
    acceptance_status: AcceptanceStatus | None


@dataclass(frozen=True, slots=True)
class TimingSummary:
    """:class:`FrameTelemetrySample` 모음의 시간차 통계 요약.

    Attributes:
        sample_count: 요약에 쓰인 표본 수. 0이면 :func:`summarize_deltas`가
            먼저 예외를 낸다 — ``sample_count=0``인 ``TimingSummary``는 존재하지 않는다
            (표본 수 없는 p50/p95/max 주장을 코드로 막는다).
        p50_ms: 중앙값(50th percentile), 절대값 기준.
        p95_ms: 95th percentile, 절대값 기준.
        max_ms: 최대값, 절대값 기준.
        mean_ms: 산술평균, 절대값 기준.
        target_p95_ms: 비교 대상 목표값(PRD §21.1, 기본 50.0).
        meets_target: ``p95_ms <= target_p95_ms``. **VERIFIED 승격 근거가 아니다** —
            판정은 :func:`judge_official`의 ``acceptance_status``를 따른다(P0-1/P0-2).
    """

    sample_count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float
    target_p95_ms: float
    meets_target: bool


@dataclass(frozen=True, slots=True)
class OfficialJudgement:
    """``--mode official``의 최종 판정 (P0-2) — evidence 축과 acceptance 축을 합성한다.

    Attributes:
        evidence_status: :func:`evaluate_evidence`의 결과.
        evidence_reasons: ``evidence_status=INVALID``일 때의 구체적 사유들(빈 튜플이면
            VALID).
        measurement_status: 순수 통계 판정의 측정 축(``Acceptance.measurement_status``).
        acceptance_status: 공식 판정. **evidence_status가 INVALID이면 숫자상 PASS/FAIL이
            무엇이었든 PASS를 절대 내지 않는다**(``FAIL``로 강제).
        reason_code: 판정 사유 code — "목표 미달"과 "증거 무효"를 구분한다.
        summary: 계산된 통계(표본이 있었다면). ``measurement_status=NOT_MEASURED``면
            ``None``.
    """

    evidence_status: EvidenceStatus
    evidence_reasons: tuple[str, ...]
    measurement_status: MeasurementStatus
    acceptance_status: AcceptanceStatus | None
    reason_code: AcceptanceReasonCode
    summary: TimingSummary | None


@dataclass(frozen=True, slots=True)
class ExploratoryJudgement:
    """``--mode exploratory``의 판정 — ``acceptance_status`` 개념이 아예 없다(P0-2 요구 3).

    이 결과는 어떤 값이든 capability VERIFIED 승격 근거가 될 수 없다. 공식 판정은
    :func:`judge_official`만 낸다.
    """

    measurement_status: MeasurementStatus
    meets_target: bool | None
    summary: TimingSummary | None


# --------------------------------------------------------------------------- #
# 순수 함수 — 단위테스트 대상
# --------------------------------------------------------------------------- #


def compute_delta_ms(frame_ts: datetime, telemetry_ts: datetime) -> float:
    """``frame_ts - telemetry_ts``를 밀리초로 반환한다 (부호 보존).

    Raises:
        ValueError: 둘 중 하나라도 tz-aware가 아니거나, UTC(offset ``+00:00``)가
            아닐 때. tz-aware이기만 하면 통과시키지 않는다 — 다른 타임존이 섞여
            들어오면 delta_ms가 시간 단위로 틀어질 수 있다(``SpikeEvidence.observed_at``과
            동일한 UTC 강제 원칙).
    """
    for name, ts in (("frame_ts", frame_ts), ("telemetry_ts", telemetry_ts)):
        if ts.tzinfo is None:
            raise ValueError(f"{name}는 tz-aware(UTC)여야 한다")
        offset = ts.utcoffset()
        if offset is None or offset != timedelta(0):
            raise ValueError(f"{name}는 UTC(offset +00:00)여야 한다 (받은 offset: {offset})")
    delta = frame_ts - telemetry_ts
    return delta.total_seconds() * 1000.0


def parse_utc_timestamp(value: str, *, field_name: str) -> datetime:
    """ISO 8601 timestamp 문자열을 UTC(offset ``+00:00``) tz-aware ``datetime``으로
    엄격 파싱한다.

    ``Z`` 서픽스는 UTC로 허용한다. 그 외 offset은 어떤 것이든(비어있는 naive 포함)
    전부 거부한다 — "tz-aware이기만 하면 됨"이 아니라 **UTC 강제**다.

    Raises:
        ValueError: ISO8601 파싱 실패, naive datetime, 또는 offset이 ``+00:00``이
            아닐 때.
    """
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name}: ISO8601 파싱 실패 — {value!r} ({exc})") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}: tz-aware(UTC)여야 한다 (받음: {value!r})")
    offset = parsed.utcoffset()
    if offset is None or offset != timedelta(0):
        raise ValueError(
            f"{field_name}: UTC(offset +00:00, 'Z' 허용)여야 한다 "
            f"(받음: {value!r}, offset: {offset})"
        )
    return parsed


def percentile(values: Sequence[float], pct: float) -> float:
    """``values``의 ``pct`` 백분위수를 선형보간(linear interpolation)으로 계산한다.

    NumPy 기본 방식(``method="linear"``, Excel ``PERCENTILE.INC``와 동일)과 같은
    정의를 쓴다 — 재현 가능성을 위해 방식을 명시한다: 정렬된 배열에서 순위
    ``r = pct/100 * (n-1)`` 위치를 인접한 두 값 사이에서 선형보간한다.

    Args:
        values: 백분위수를 계산할 값들(빈 시퀀스 불가).
        pct: 0~100 사이의 백분위(예: 50, 95).

    Raises:
        ValueError: ``values``가 비었거나 ``pct``가 [0, 100] 범위 밖일 때.
    """
    if not values:
        raise ValueError("percentile: 빈 표본으로는 계산할 수 없다")
    if not (0.0 <= pct <= 100.0):
        raise ValueError(f"percentile: pct는 0~100 범위여야 한다 (받음: {pct})")

    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    rank = (pct / 100.0) * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    frac = rank - lower_idx
    return sorted_values[lower_idx] + frac * (sorted_values[upper_idx] - sorted_values[lower_idx])


def summarize_deltas(
    deltas_ms: Sequence[float],
    *,
    target_p95_ms: float = DEFAULT_TARGET_P95_MS,
) -> TimingSummary:
    """시간차 표본들로부터 :class:`TimingSummary`를 만든다.

    p50/p95/max/mean은 절대값(``abs``) 기준으로 계산한다 — Frame이 Telemetry보다
    먼저 오든 나중에 오든 "시간이 얼마나 어긋났는가"가 정렬 품질의 척도이지, 부호
    자체가 정렬 품질을 뜻하지 않는다. 부호 정보(어느 쪽이 체계적으로 앞서는가)는
    원본 JSONL의 ``delta_ms``에 그대로 남아 있으므로 손실되지 않는다.

    Raises:
        ValueError: ``deltas_ms``가 비어 있거나, ``target_p95_ms``가 유한한 양수가
            아닐 때 — "표본 수 0"으로 VERIFIED를 주장하는 것을 막는다
            (``docs/hil/CAPABILITY_ACCEPTANCE.md`` 시간동기 기준).
    """
    if not deltas_ms:
        raise ValueError(
            "summarize_deltas: 표본이 0건이다 — 시간동기 VERIFIED에는 실측 표본이 "
            "필수다('미측정 + 이유'는 이 함수가 아니라 사람이 별도로 기록하는 문장이다)"
        )
    validate_finite_positive(target_p95_ms, name="target_p95_ms")
    abs_values = [abs(v) for v in deltas_ms]
    p50 = percentile(abs_values, 50.0)
    p95 = percentile(abs_values, 95.0)
    max_v = max(abs_values)
    mean_v = sum(abs_values) / len(abs_values)
    return TimingSummary(
        sample_count=len(deltas_ms),
        p50_ms=p50,
        p95_ms=p95,
        max_ms=max_v,
        mean_ms=mean_v,
        target_p95_ms=target_p95_ms,
        meets_target=p95 <= target_p95_ms,
    )


def judge_acceptance(
    summary: TimingSummary | None,
    *,
    min_sample_count: int = DEFAULT_MIN_SAMPLE_COUNT,
) -> Acceptance:
    """``docs/hil/CAPABILITY_ACCEPTANCE.md`` "시간동기" 행의 2축 판정 규칙을 코드로
    강제한다 (P0-1). 순수 통계 판정 — 증거 무결성(P0-2)은 반영하지 않는다.

    - ``summary is None``(표본 0건) → ``NOT_MEASURED`` / 판정 없음.
    - 표본 수 < ``min_sample_count`` → ``MEASURED`` / ``INSUFFICIENT_SAMPLES``.
    - p95 ≤ target → ``MEASURED`` / ``PASS``.
    - p95 > target → ``MEASURED`` / ``FAIL`` (표본 수가 충분해도 VERIFIED 승격 금지).

    사람이 이 판정을 임의로 뒤집어 VERIFIED를 선언하는 경로는 이 함수 밖에 있다 —
    이 함수는 그 뒤집기가 "실측 절차를 따랐다"는 근거가 되지 않는다는 점만 코드로
    확정한다. 공식 CLI 출력은 이 함수를 직접 노출하지 않고 :func:`judge_official`을
    거친다(증거 무결성 게이트 포함).
    """
    validate_positive_int(min_sample_count, name="min_sample_count")
    if summary is None or summary.sample_count == 0:
        return Acceptance(measurement_status=MeasurementStatus.NOT_MEASURED, acceptance_status=None)
    if summary.sample_count < min_sample_count:
        return Acceptance(
            measurement_status=MeasurementStatus.MEASURED,
            acceptance_status=AcceptanceStatus.INSUFFICIENT_SAMPLES,
        )
    status = (
        AcceptanceStatus.PASS if summary.p95_ms <= summary.target_p95_ms else AcceptanceStatus.FAIL
    )
    return Acceptance(measurement_status=MeasurementStatus.MEASURED, acceptance_status=status)


def evaluate_evidence(
    load_result: FrameTelemetryLoadResult,
) -> tuple[EvidenceStatus, tuple[str, ...]]:
    """입력 파일 전체가 공식 PASS 판정을 낼 자격이 있는 증거인지 판정한다 (P0-2).

    다음 중 하나라도 있으면 ``INVALID``다:

    - 검증에 실패해 제외된 줄이 1개 이상 있음(``rejected_line_count>0`` — 중복
      ``sample_index``도 :func:`_validate_sample_indices`에서 거부로 처리되므로
      여기 포함된다).
    - 유효 표본의 ``session_id``가 정확히 1개가 아님(0개 또는 2개 이상).
    - 유효 표본의 ``aircraft_sn``이 정확히 1개가 아님.
    - 유효 표본의 ``sample_index``가 0부터 시작하지 않음.
    - 유효 표본의 ``sample_index``에 gap이 있음(최솟값~최댓값 구간이 표본 수와 다름).
    - 유효 표본이 0건(판정할 증거 자체가 없음).
    """
    reasons: list[str] = []

    if load_result.rejected:
        reasons.append(
            f"rejected_line_count={len(load_result.rejected)} (0이어야 공식 PASS 가능)"
        )

    session_ids = sorted({s.session_id for s in load_result.samples})
    if len(session_ids) != 1:
        observed = session_ids if session_ids else "없음(표본 0건)"
        reasons.append(f"session_id가 정확히 1개가 아니다 (관측: {observed})")

    aircraft_sns = sorted({s.aircraft_sn for s in load_result.samples})
    if len(aircraft_sns) != 1:
        reasons.append(
            "aircraft_sn이 정확히 1개가 아니다 "
            f"(관측: {aircraft_sns if aircraft_sns else '없음(표본 0건)'})"
        )

    indices = sorted(s.sample_index for s in load_result.samples)
    if indices:
        if indices[0] != 0:
            reasons.append(f"sample_index가 0부터 시작하지 않는다 (최솟값: {indices[0]})")
        span = indices[-1] - indices[0] + 1
        if span != len(indices):
            reasons.append(
                f"sample_index에 gap이 있다 (최솟값 {indices[0]}~최댓값 {indices[-1]}, "
                f"유효 표본 {len(indices)}건, 기대 연속 개수 {span}건)"
            )
    else:
        reasons.append("유효 표본이 0건이다")

    status = EvidenceStatus.VALID if not reasons else EvidenceStatus.INVALID
    return status, tuple(reasons)


def judge_official(
    load_result: FrameTelemetryLoadResult,
) -> OfficialJudgement:
    """``--mode official``의 최종 판정 (P0-2) — evidence 게이트 + 2축 통계 판정을 합성한다.

    **profile 주입 불가** (독립 재검토 P0, 2026-07-28): 이전 시그니처는
    ``profile=`` 인자를 받고 profile_id 만 비교해서, 공식 ID 를 단 완화 profile
    (target=100000·min=1)로 기준을 우회할 수 있었다. 공식 판정은 이 함수 내부의
    ``OFFICIAL_PROFILE`` 상수만 쓴다 — 테스트용 가변 기준은 exploratory 경로
    (``judge_acceptance``/``summarize_deltas`` 직접 호출)에서만 가능하며 그 결과는
    공식 판정이 아니다.

    evidence provenance binding: ``load_result`` 가 공식 tolerance 로 검증된
    결과인지 exact 비교한다 — relaxed loader 산출물 주입은 EVIDENCE_INVALID.

    evidence가 ``INVALID``이면 통계상 PASS가 나오더라도 ``acceptance_status``를
    ``FAIL``로 강제한다(``reason_code=EVIDENCE_INVALID``로 사유를 구분해 남긴다).
    """
    profile = OFFICIAL_PROFILE
    binding_reasons: list[str] = []
    if load_result.validation_profile_id != profile.profile_id:
        binding_reasons.append(
            f"증거가 공식 profile 로 검증되지 않았다 — validation_profile_id="
            f"{load_result.validation_profile_id!r} ≠ {profile.profile_id!r} "
            "(load_official_evidence 로 다시 로드하라)"
        )
    if load_result.validation_delta_tolerance_ms != profile.delta_tolerance_ms:
        binding_reasons.append(
            f"증거 검증 tolerance {load_result.validation_delta_tolerance_ms!r}ms ≠ "
            f"공식 {profile.delta_tolerance_ms!r}ms — relaxed 검증 결과는 공식 판정 불가"
        )
    if binding_reasons:
        evidence_status = EvidenceStatus.INVALID
        evidence_reasons: tuple[str, ...] = tuple(binding_reasons)
    else:
        evidence_status, evidence_reasons = evaluate_evidence(load_result)

    deltas = [s.delta_ms for s in load_result.samples]
    summary = summarize_deltas(deltas, target_p95_ms=profile.target_p95_ms) if deltas else None
    acceptance = judge_acceptance(summary, min_sample_count=profile.min_sample_count)

    if acceptance.measurement_status is MeasurementStatus.NOT_MEASURED:
        return OfficialJudgement(
            evidence_status=evidence_status,
            evidence_reasons=evidence_reasons,
            measurement_status=MeasurementStatus.NOT_MEASURED,
            acceptance_status=None,
            reason_code=AcceptanceReasonCode.NOT_MEASURED,
            summary=None,
        )

    if evidence_status is EvidenceStatus.INVALID:
        return OfficialJudgement(
            evidence_status=evidence_status,
            evidence_reasons=evidence_reasons,
            measurement_status=acceptance.measurement_status,
            acceptance_status=AcceptanceStatus.FAIL,
            reason_code=AcceptanceReasonCode.EVIDENCE_INVALID,
            summary=summary,
        )

    if acceptance.acceptance_status is AcceptanceStatus.INSUFFICIENT_SAMPLES:
        reason_code = AcceptanceReasonCode.INSUFFICIENT_SAMPLES
    elif acceptance.acceptance_status is AcceptanceStatus.PASS:
        reason_code = AcceptanceReasonCode.OK
    else:
        reason_code = AcceptanceReasonCode.REQUIREMENT_NOT_MET

    return OfficialJudgement(
        evidence_status=evidence_status,
        evidence_reasons=evidence_reasons,
        measurement_status=acceptance.measurement_status,
        acceptance_status=acceptance.acceptance_status,
        reason_code=reason_code,
        summary=summary,
    )


def judge_exploratory(
    load_result: FrameTelemetryLoadResult,
    *,
    profile: AcceptanceProfile,
) -> ExploratoryJudgement:
    """``--mode exploratory``의 판정 — ``acceptance_status`` 개념 자체가 없다.

    어떤 ``meets_target`` 값이 나오든 이 결과는 capability VERIFIED 승격 근거가
    될 수 없다(공식 판정은 :func:`judge_official`만 낸다, P0-2 요구 3).
    """
    deltas = [s.delta_ms for s in load_result.samples]
    if not deltas:
        return ExploratoryJudgement(
            measurement_status=MeasurementStatus.NOT_MEASURED, meets_target=None, summary=None
        )
    summary = summarize_deltas(deltas, target_p95_ms=profile.target_p95_ms)
    return ExploratoryJudgement(
        measurement_status=MeasurementStatus.MEASURED,
        meets_target=summary.meets_target,
        summary=summary,
    )


# --------------------------------------------------------------------------- #
# JSONL I/O + 검증 — 입력을 신뢰하지 않는다(모듈 docstring 참고)
# --------------------------------------------------------------------------- #


def _reject_json_constant(constant: str) -> float:
    """``json.loads(parse_constant=...)`` 훅 — NaN/Infinity/-Infinity를 거부한다.

    표준 JSON에는 없는 비표준 토큰이다. 기본 ``json`` 모듈은 이를 조용히
    ``float("nan")``/``float("inf")``로 받아들이는데, 그 값이 ``delta_ms``에 섞이면
    percentile 계산이 오염되거나(NaN 비교는 항상 False) 비현실적인 좋은 p95를
    만들 수 있다 — 그래서 파싱 단계에서 즉시 거부한다.
    """
    raise ValueError(f"허용되지 않는 JSON 상수: {constant} (NaN/Infinity/-Infinity 금지)")


def _parse_sample_line(
    line: str,
    *,
    delta_tolerance_ms: float,
) -> FrameTelemetrySample:
    """JSONL 한 줄을 검증하며 :class:`FrameTelemetrySample`로 파싱한다.

    Raises:
        ValueError: 아래 중 하나라도 위반 시 구체적 사유와 함께.
            - JSON 파싱 실패(NaN/Infinity 포함) 또는 최상위가 객체(dict)가 아님
            - 필수 필드 누락
            - ``session_id``/``aircraft_sn``이 공백
            - ``sample_index``가 정수가 아니거나 음수
            - timestamp가 UTC(offset ``+00:00``) tz-aware ISO8601이 아님
            - 저장된 ``delta_ms``가 두 timestamp로부터 재계산한 값과
              ``delta_tolerance_ms`` 이내로 일치하지 않음(위조/오기 의심)
    """
    try:
        payload: Any = json.loads(line, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패 — {exc}") from exc
    except ValueError as exc:
        # _reject_json_constant가 던진 ValueError — 그대로 전파(사유가 이미 구체적).
        raise ValueError(str(exc)) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 아님 (받음 타입: {type(payload).__name__})")

    missing = [f for f in _REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"필수 필드 누락: {', '.join(missing)}")

    sample_index = payload["sample_index"]
    if not isinstance(sample_index, int) or isinstance(sample_index, bool):
        raise ValueError(f"sample_index는 정수여야 한다 (받음: {sample_index!r})")
    if sample_index < 0:
        raise ValueError(f"sample_index는 음수일 수 없다 (받음: {sample_index})")

    session_id = payload["session_id"]
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(f"session_id는 공백이 아닌 문자열이어야 한다 (받음: {session_id!r})")

    aircraft_sn = payload["aircraft_sn"]
    if not isinstance(aircraft_sn, str) or not aircraft_sn.strip():
        raise ValueError(f"aircraft_sn은 공백이 아닌 문자열이어야 한다 (받음: {aircraft_sn!r})")

    frame_ts_raw = payload["frame_timestamp_utc"]
    telemetry_ts_raw = payload["telemetry_timestamp_utc"]
    if not isinstance(frame_ts_raw, str) or not isinstance(telemetry_ts_raw, str):
        raise ValueError("frame_timestamp_utc/telemetry_timestamp_utc는 문자열이어야 한다")

    frame_ts = parse_utc_timestamp(frame_ts_raw, field_name="frame_timestamp_utc")
    telemetry_ts = parse_utc_timestamp(telemetry_ts_raw, field_name="telemetry_timestamp_utc")

    stored_delta_raw = payload["delta_ms"]
    if isinstance(stored_delta_raw, bool) or not isinstance(stored_delta_raw, int | float):
        raise ValueError(f"delta_ms는 숫자여야 한다 (받음: {stored_delta_raw!r})")
    stored_delta = float(stored_delta_raw)
    if not math.isfinite(stored_delta):
        raise ValueError(f"delta_ms는 유한한 값이어야 한다 (받음: {stored_delta})")

    recomputed_delta = compute_delta_ms(frame_ts, telemetry_ts)
    if abs(recomputed_delta - stored_delta) > delta_tolerance_ms:
        raise ValueError(
            f"저장된 delta_ms={stored_delta:.3f}가 timestamp 재계산값="
            f"{recomputed_delta:.3f}과 tolerance({delta_tolerance_ms}ms)를 벗어난다 "
            "— 임의 조작/오기 의심(가짜 delta_ms=0 주입 등)"
        )

    timestamp_basis = payload.get("timestamp_basis")
    if timestamp_basis is not None and timestamp_basis not in ("sensor", "recv"):
        raise ValueError(
            f"timestamp_basis는 'sensor'/'recv'/누락 중 하나여야 한다 (받음: {timestamp_basis!r})"
        )

    return FrameTelemetrySample(
        sample_index=sample_index,
        session_id=session_id,
        aircraft_sn=aircraft_sn,
        frame_timestamp_utc=frame_ts_raw,
        telemetry_timestamp_utc=telemetry_ts_raw,
        delta_ms=recomputed_delta,
        timestamp_basis=timestamp_basis,
    )


def _validate_sample_indices(
    parsed: Sequence[tuple[int, FrameTelemetrySample]],
) -> tuple[list[FrameTelemetrySample], list[RejectedLine], list[str]]:
    """파싱된 ``(line_no, sample)`` 목록에서 ``sample_index`` 중복을 거부하고
    불연속을 경고한다.

    음수 ``sample_index``는 이미 :func:`_parse_sample_line`에서 걸러지므로 여기서는
    다루지 않는다. 순수 함수 — 입력만으로 결과가 결정된다.
    """
    valid: list[FrameTelemetrySample] = []
    rejected: list[RejectedLine] = []
    seen_at: dict[int, int] = {}

    for line_no, sample in parsed:
        first_line_no = seen_at.get(sample.sample_index)
        if first_line_no is not None:
            rejected.append(
                RejectedLine(
                    line_no=line_no,
                    reason=(
                        f"중복 sample_index={sample.sample_index} "
                        f"(최초 등장: line {first_line_no})"
                    ),
                )
            )
            continue
        seen_at[sample.sample_index] = line_no
        valid.append(sample)

    warnings: list[str] = []
    sorted_indices = sorted(s.sample_index for s in valid)
    # pairwise 순회 — sorted_indices[1:]는 정의상 원본보다 정확히 1개 짧다(정상 형태).
    for prev_idx, cur_idx in zip(sorted_indices, sorted_indices[1:], strict=False):
        gap = cur_idx - prev_idx
        if gap > 1:
            warnings.append(f"sample_index 불연속: {prev_idx} 다음이 {cur_idx} (간격 {gap})")

    return valid, rejected, warnings


def load_official_evidence(path: Path) -> FrameTelemetryLoadResult:
    """공식 판정용 로드 — 검증 조건은 ``OFFICIAL_PROFILE`` 고정, 호출자가 완화할
    인자 자체가 없다. :func:`judge_official` 은 이 함수의 산출물만 통과시킨다."""
    return load_frame_telemetry_jsonl(
        path,
        delta_tolerance_ms=OFFICIAL_PROFILE.delta_tolerance_ms,
        _validation_profile_id=OFFICIAL_PROFILE.profile_id,
    )


def load_exploratory_evidence(
    path: Path, *, delta_tolerance_ms: float = DEFAULT_DELTA_TOLERANCE_MS
) -> FrameTelemetryLoadResult:
    """실험용 로드 — 임의 tolerance 허용. 산출물의 provenance 가
    ``EXPLORATORY_PROFILE_ID`` 로 찍히므로 공식 판정(:func:`judge_official`)에
    넣으면 EVIDENCE_INVALID 다."""
    return load_frame_telemetry_jsonl(path, delta_tolerance_ms=delta_tolerance_ms)


def load_frame_telemetry_jsonl(
    path: Path,
    *,
    delta_tolerance_ms: float = DEFAULT_DELTA_TOLERANCE_MS,
    _validation_profile_id: str = EXPLORATORY_PROFILE_ID,
) -> FrameTelemetryLoadResult:
    """JSONL 파일을 검증하며 읽어 :class:`FrameTelemetryLoadResult`를 만든다.

    직접 호출은 **exploratory provenance** 로 기록된다 — 공식 판정에 쓸 증거는
    :func:`load_official_evidence` 로만 만든다(``_validation_profile_id`` 는 그
    전용 내부 통로다).

    한 줄이라도 검증에 실패하면(JSON 파싱·필수 필드·UTC·delta 재계산 불일치·
    음수/중복 index 등) 그 줄은 유효 표본에서 제외되고 사유와 함께 ``rejected``에
    남는다 — 한 줄의 결함이 전체 파일 로드를 막지 않되, 조용히 사라지지도 않는다.
    빈 줄은 건너뛴다(거부로 집계하지 않는다).

    파일 전체의 UTF-8 decode가 실패하면(예: 손상된 바이너리) 예외를 내지 않고
    표본 0건 + ``line_no=0`` 거부 사유 1건으로 다룬다 — 증거 판정 도구가 크래시하면
    "판정 불가"라는 사실 자체가 사라지기 때문이다.

    Raises:
        ValueError: ``delta_tolerance_ms``가 유한하고 음수가 아닌 값이 아닐 때.
    """
    validate_finite_nonnegative(delta_tolerance_ms, name="delta_tolerance_ms")

    raw_bytes = path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return FrameTelemetryLoadResult(
            samples=(),
            rejected=(RejectedLine(line_no=0, reason=f"파일 UTF-8 decode 실패 — {exc}"),),
            warnings=(),
            sha256=sha256,
            validation_profile_id=_validation_profile_id,
            validation_delta_tolerance_ms=delta_tolerance_ms,
        )

    parsed: list[tuple[int, FrameTelemetrySample]] = []
    rejected: list[RejectedLine] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            sample = _parse_sample_line(line, delta_tolerance_ms=delta_tolerance_ms)
        except ValueError as exc:
            rejected.append(RejectedLine(line_no=line_no, reason=str(exc)))
            continue
        parsed.append((line_no, sample))

    valid_samples, dup_rejected, warnings = _validate_sample_indices(parsed)
    rejected.extend(dup_rejected)
    rejected.sort(key=lambda r: r.line_no)

    return FrameTelemetryLoadResult(
        samples=tuple(valid_samples),
        rejected=tuple(rejected),
        warnings=tuple(warnings),
        sha256=sha256,
        validation_profile_id=_validation_profile_id,
        validation_delta_tolerance_ms=delta_tolerance_ms,
    )


def sample_to_json_line(sample: FrameTelemetrySample) -> str:
    """``sample``을 JSONL 한 줄(개행 없음)로 직렬화한다."""
    return json.dumps(asdict(sample), ensure_ascii=False, sort_keys=True)


def _existing_session_aircraft(path: Path) -> tuple[str, str] | None:
    """``path``에 이미 기록된 표본이 있다면 그 ``(session_id, aircraft_sn)``을 돌려준다.

    :func:`append_sample_jsonl`의 "여러 세션/기체 합산 금지" 정책 검사용이다 —
    :func:`load_frame_telemetry_jsonl`처럼 엄격 재검증까지는 하지 않는다(그 목적은
    이 시점에 필요 없다). 파일이 없거나 파싱 가능한 줄이 하나도 없으면 ``None``.
    """
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and "session_id" in payload and "aircraft_sn" in payload:
            return str(payload["session_id"]), str(payload["aircraft_sn"])
    return None


def append_sample_jsonl(path: Path, sample: FrameTelemetrySample) -> None:
    """``sample``을 ``path``에 한 줄 추가한다(append). 부모 디렉터리는 미리 만든다.

    **정책(여러 세션·기체 합산 금지)**: ``path``에 이미 다른 ``session_id`` 또는
    ``aircraft_sn``의 표본이 있으면 append 자체를 즉시 거부한다 — 세션·기체 조합당
    별도 파일·별도 Summary만 허용한다. 이 검사를 우회하려면 별도 파일 경로를 써야 한다
    (의도된 마찰 — 실수로 두 세션을 한 파일에 섞는 것을 쓰기 시점에 막는다).

    Raises:
        ValueError: 기존 파일의 session_id/aircraft_sn이 ``sample``과 다를 때.
    """
    existing = _existing_session_aircraft(path)
    if existing is not None:
        existing_session, existing_aircraft = existing
        if existing_session != sample.session_id or existing_aircraft != sample.aircraft_sn:
            raise ValueError(
                "정책 위반(여러 세션/기체 합산 금지): 기존 out 파일에 이미 "
                f"session_id={existing_session!r}/aircraft_sn={existing_aircraft!r} 표본이 "
                f"있는데 session_id={sample.session_id!r}/aircraft_sn={sample.aircraft_sn!r}를 "
                f"같은 파일({path})에 append하려 했다 — 세션·기체 조합당 별도 파일을 쓸 것."
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(sample_to_json_line(sample))
        f.write("\n")


# --------------------------------------------------------------------------- #
# tap-log 변환 — edge/psdk-tap이 쓴 raw NDJSON → 공식 6필드 JSONL (ADR-KSI-009 D3)
#
# 실기 Python(3.8.10)은 StrEnum/datetime.UTC/dataclass(slots=True)를 못 쓴다
# (이 파일 전체가 Python 3.12 전용인 이유이기도 하다). 그래서 실기 수집은 C로
# 컴파일되는 edge/psdk-tap이 담당하고, 이 파일은 그 결과물(raw NDJSON)만 신뢰하지
# 않고 재검증하며 기존 6필드 스키마로 변환한다 — NDJSON이 두 언어의 계약이다.
# --------------------------------------------------------------------------- #


def _mono_ns_to_utc(mono_ns: int, *, anchor_mono_ns: int, anchor_wall_utc: datetime) -> datetime:
    """단조시계 값(나노초)을 ``meta.clock`` 앵커 기준으로 UTC ``datetime``으로 환산한다.

    ``anchor_wall_utc``는 ``anchor_mono_ns`` 시점에 C tap이 함께 찍은 UTC 벽시계
    시각이다(둘은 같은 순간의 값으로 간주한다). monotonic clock은 정의상 NTP
    보정 등으로 뒤로 흐르지 않으므로, 앵커 이후 경과한 나노초 델타를 그대로
    벽시계에 더하면 그 순간의 UTC가 나온다.
    """
    delta_ns = mono_ns - anchor_mono_ns
    return anchor_wall_utc + timedelta(microseconds=delta_ns / 1000.0)


def _mono_us_to_utc(mono_us: float, *, anchor_mono_ns: int, anchor_wall_utc: datetime) -> datetime:
    """단조시계 값(마이크로초)을 :func:`_mono_ns_to_utc`와 동일한 앵커로 환산한다.

    ``sensor_us``(``--timestamp-basis sensor``)가 이 함수를 쓴다. **가정**: C tap이
    쓰는 ``sensor_us``는 이미 호스트의 ``CLOCK_MONOTONIC``(=``meta.clock.mono_ns``와
    같은 도메인)으로 정규화된 값이라고 전제한다 — PSDK 조사 결과(Q2)에 따르면
    liveview 콜백은 카메라 자체 타임스탬프를 노출하지 않고, FC subscription의
    ``T_DjiDataTimestamp``는 기종별로 다른 로컬 클록(FC 전원인가 후 경과 등) 기준이라
    호스트 monotonic과 원천적으로 다른 도메인이다. 두 도메인을 하나의 ``meta.clock``
    앵커만으로 환산하는 것은 C tap이 자체적으로 두 클록 간 오프셋을 추정해
    ``sensor_us``를 호스트 monotonic 도메인으로 이미 정규화해 뒀을 때만 물리적으로
    맞다. 이 전제가 C tap 구현과 실제로 일치하는지는 이 파일만으로 확인할 수
    없다 — 계약 문서(위 모듈 docstring 인용)가 "단조시계 값은 meta.clock 앵커로
    UTC로 환산한다"고 명시한 것을 문자 그대로 따른 것이며, 어긋난다면 tap-log
    계약 자체를 수정해야 한다(이 파일 단독으로 고칠 수 없다).
    """
    return _mono_ns_to_utc(
        round(mono_us * 1000.0), anchor_mono_ns=anchor_mono_ns, anchor_wall_utc=anchor_wall_utc
    )


def _convert_tap_sample(
    record: dict[str, Any],
    *,
    line_no: int,
    session_id: str,
    aircraft_sn: str,
    timestamp_basis: str,
    anchor_mono_ns: int,
    anchor_wall_utc: datetime,
) -> FrameTelemetrySample:
    """tap-log의 ``{"type":"sample",...}`` 레코드 1건을 :class:`FrameTelemetrySample`로
    변환한다.

    Raises:
        ValueError: 필수 필드 누락, ``i``가 정수가 아님, 또는
            ``timestamp_basis="sensor"``인데 이 표본의 ``sensor_us``가
            ``null``(fail-closed — ``recv``로 조용히 대체하지 않는다).
    """
    try:
        sample_i = record["i"]
        frame = record["frame"]
        telemetry = record["telemetry"]
    except KeyError as exc:
        raise ValueError(f"tap-log line {line_no}: sample 필드 누락 — {exc}") from exc

    if not isinstance(sample_i, int) or isinstance(sample_i, bool):
        raise ValueError(f"tap-log line {line_no}: sample.i는 정수여야 한다 (받음: {sample_i!r})")
    if not isinstance(frame, dict) or not isinstance(telemetry, dict):
        raise ValueError(f"tap-log line {line_no}: sample.frame/telemetry는 객체여야 한다")

    if timestamp_basis == "sensor":
        frame_sensor_us = frame.get("sensor_us")
        telemetry_sensor_us = telemetry.get("sensor_us")
        if frame_sensor_us is None or telemetry_sensor_us is None:
            raise ValueError(
                f"tap-log line {line_no}: --timestamp-basis sensor 요청인데 이 표본의 "
                f"sensor_us가 null이다 (frame.sensor_us={frame_sensor_us!r}, "
                f"telemetry.sensor_us={telemetry_sensor_us!r}) — fail-closed: recv로 "
                "조용히 대체하지 않는다"
            )
        frame_ts = _mono_us_to_utc(
            float(frame_sensor_us), anchor_mono_ns=anchor_mono_ns, anchor_wall_utc=anchor_wall_utc
        )
        telemetry_ts = _mono_us_to_utc(
            float(telemetry_sensor_us),
            anchor_mono_ns=anchor_mono_ns,
            anchor_wall_utc=anchor_wall_utc,
        )
    else:  # "recv"
        try:
            frame_recv_mono_ns = frame["recv_mono_ns"]
            telemetry_recv_mono_ns = telemetry["recv_mono_ns"]
        except KeyError as exc:
            raise ValueError(f"tap-log line {line_no}: recv_mono_ns 필드 누락 — {exc}") from exc
        frame_ts = _mono_ns_to_utc(
            int(frame_recv_mono_ns), anchor_mono_ns=anchor_mono_ns, anchor_wall_utc=anchor_wall_utc
        )
        telemetry_ts = _mono_ns_to_utc(
            int(telemetry_recv_mono_ns),
            anchor_mono_ns=anchor_mono_ns,
            anchor_wall_utc=anchor_wall_utc,
        )

    return FrameTelemetrySample(
        sample_index=sample_i,
        session_id=session_id,
        aircraft_sn=aircraft_sn,
        frame_timestamp_utc=frame_ts.isoformat(),
        telemetry_timestamp_utc=telemetry_ts.isoformat(),
        delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
        timestamp_basis=timestamp_basis,
    )


def convert_tap_log_to_samples(
    tap_log_path: Path,
    *,
    session_id: str,
    aircraft_sn: str,
    timestamp_basis: str,
) -> list[FrameTelemetrySample]:
    """``edge/psdk-tap``이 쓴 raw NDJSON을 읽어 공식 6필드 표본 목록으로 변환한다.

    입력 계약(다른 워커가 같은 계약으로 구현):

    - ``{"type":"meta",...,"clock":{"mono_ns":...,"wall_utc":"..."},
      "capabilities":{"frame_sensor_ts":bool,"telemetry_sensor_ts":bool}}`` — 정확히
      1개, 반드시 이후 sample 레코드보다 먼저.
    - ``{"type":"sample","i":N,"frame":{"recv_mono_ns":...,"sensor_us":...|null},
      "telemetry":{...}}`` — 0개 이상.
    - ``{"type":"stat",...}`` — 변환 대상이 아니므로 무시한다.

    ``timestamp_basis="sensor"``인데 ``meta.capabilities.frame_sensor_ts`` 또는
    ``telemetry_sensor_ts``가 ``false``이면 **파일 전체를 fail-closed로 중단**한다
    (``recv``로 조용히 대체하지 않는다 — 이게 이 인자가 존재하는 이유다). 개별
    표본의 ``sensor_us``가 ``null``이면 그 표본에서 중단한다(둘 다 "중단"이지
    "건너뛰기"가 아니다).

    Raises:
        ValueError: JSON 파싱 실패, meta 레코드 누락/중복/순서 위반, capability
            불충족, 알 수 없는 ``type``, 그 외 스키마 위반.
    """
    if timestamp_basis not in ("sensor", "recv"):
        raise ValueError(
            f"timestamp_basis는 'sensor' 또는 'recv'여야 한다 (받음: {timestamp_basis!r})"
        )

    raw_text = tap_log_path.read_text(encoding="utf-8")

    meta_seen = False
    anchor_mono_ns: int | None = None
    anchor_wall_utc: datetime | None = None
    samples: list[FrameTelemetrySample] = []

    for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line, parse_constant=_reject_json_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"tap-log line {line_no}: JSON 파싱 실패 — {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"tap-log line {line_no}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"tap-log line {line_no}: JSON 객체가 아니다")

        record_type = record.get("type")

        if record_type == "meta":
            if meta_seen:
                raise ValueError(f"tap-log line {line_no}: meta 레코드가 두 번 이상 등장한다")
            meta_seen = True
            try:
                clock = record["clock"]
                anchor_mono_ns = int(clock["mono_ns"])
                anchor_wall_utc_raw = clock["wall_utc"]
            except KeyError as exc:
                raise ValueError(f"tap-log line {line_no}: meta.clock 필드 누락 — {exc}") from exc
            if not isinstance(anchor_wall_utc_raw, str):
                raise ValueError(f"tap-log line {line_no}: meta.clock.wall_utc는 문자열이어야 한다")
            anchor_wall_utc = parse_utc_timestamp(
                anchor_wall_utc_raw, field_name="meta.clock.wall_utc"
            )

            if timestamp_basis == "sensor":
                capabilities = record.get("capabilities", {})
                if not isinstance(capabilities, dict):
                    raise ValueError(f"tap-log line {line_no}: meta.capabilities는 객체여야 한다")
                frame_ok = bool(capabilities.get("frame_sensor_ts", False))
                telemetry_ok = bool(capabilities.get("telemetry_sensor_ts", False))
                if not frame_ok or not telemetry_ok:
                    raise ValueError(
                        f"tap-log line {line_no}: --timestamp-basis sensor 요청인데 "
                        f"meta.capabilities.frame_sensor_ts={frame_ok}/"
                        f"telemetry_sensor_ts={telemetry_ok} — 둘 다 true여야 한다 "
                        "(fail-closed: recv로 조용히 대체하지 않는다)"
                    )
            continue

        if record_type == "stat":
            continue  # 통계 레코드 — 변환 대상이 아니다.

        if record_type != "sample":
            raise ValueError(f"tap-log line {line_no}: 알 수 없는 type={record_type!r}")

        if not meta_seen or anchor_mono_ns is None or anchor_wall_utc is None:
            raise ValueError(f"tap-log line {line_no}: sample 레코드가 meta보다 먼저 등장했다")

        samples.append(
            _convert_tap_sample(
                record,
                line_no=line_no,
                session_id=session_id,
                aircraft_sn=aircraft_sn,
                timestamp_basis=timestamp_basis,
                anchor_mono_ns=anchor_mono_ns,
                anchor_wall_utc=anchor_wall_utc,
            )
        )

    if not meta_seen:
        raise ValueError("tap-log: meta 레코드가 없다 — clock 앵커/capabilities 없이는 변환 불가")

    return samples


def _timestamp_basis_notice(timestamp_bases: Sequence[str]) -> str | None:
    """summarize 출력에 basis를 명시적으로 노출한다 — 대체 정의(``recv``)로 낸 PASS를
    "센서 시각 정합"으로 오독하지 않도록 경고 문구를 만든다.

    ``timestamp_bases``가 정확히 1개의 값으로 수렴할 때만 문구를 낸다 — 여러 basis가
    섞였거나(비정상) 관측되지 않았으면(구버전 파일·``--source psdk`` 경로 등
    basis 정보 자체가 없는 표본) ``None``이다.
    """
    if len(timestamp_bases) != 1:
        return None
    basis = timestamp_bases[0]
    if basis == "recv":
        return (
            "이 표본은 --timestamp-basis recv로 수집됐다 — frame/telemetry 모두 호스트가 "
            "'수신한' monotonic clock 기준 시각이며, 카메라/FC의 실제 센서 타임스탬프가 "
            "아니다. 이 결과의 PASS는 '수신 정합'이지 '센서 시각 정합'이 아니다 — PRD "
            "§21.1의 Sensor Timestamp alignment 주장 근거로 쓰려면 --timestamp-basis "
            "sensor 로 재수집해야 한다."
        )
    if basis == "sensor":
        return (
            "이 표본은 --timestamp-basis sensor로 수집됐다 — meta.capabilities가 두 "
            "타임스탬프 모두 장치 자체 센서 타임스탬프임을 보증한 표본만 포함한다."
        )
    return None


# --------------------------------------------------------------------------- #
# PSDK 연동 자리 — 실기 세션에서 채움
# --------------------------------------------------------------------------- #


def read_next_frame_telemetry_timestamps() -> tuple[datetime, datetime]:
    """PSDK에서 다음 Frame·Telemetry 시각 쌍을 읽는다.

    TODO(실기 세션, HARDWARE_SESSION_PLAYBOOK.md 7단계): DJI Payload SDK 콜백 연동
    필요. 예상 형태 — 카메라 프레임 콜백이 프레임 수신 시각을 주고, 그 프레임과
    가장 가까운 Telemetry(비행 상태) 콜백의 시각을 짝짓는다. 정확한 콜백 함수명·
    시그니처는 이 문서 작성 시점에 확정하지 않는다(불확실한 API 이름을 단정하지
    말 것) — 2단계 "DJI 공식 샘플 빌드"에서 실제로 확인한 API로 이 함수 본문을
    교체할 것.

    Raises:
        NotImplementedError: PSDK 연동 전까지 항상 발생한다. 가짜 timestamp를
            반환하도록 절대 고치지 말 것 — 그러면 이 도구가 "측정했다"는 거짓
            신호를 내게 된다(INV-040: mock/placeholder로 실패를 가리지 않는다).
    """
    raise NotImplementedError(
        "PSDK 카메라 프레임 콜백 + Telemetry 콜백 미연동. "
        "docs/hil/HARDWARE_SESSION_PLAYBOOK.md 2·7단계를 실기에서 완료한 뒤 "
        "이 함수를 실제 PSDK API 호출로 교체할 것."
    )


def collect_session(
    *,
    session_id: str,
    aircraft_sn: str,
    out_path: Path,
    num_samples: int,
) -> None:
    """``num_samples``개의 Frame–Telemetry 쌍을 수집해 ``out_path``에 JSONL로 쓴다.

    :func:`read_next_frame_telemetry_timestamps`가 미구현인 동안은 첫 호출에서
    바로 ``NotImplementedError``가 전파된다 — 의도된 fail-closed 동작이다.

    Raises:
        ValueError: ``session_id``/``aircraft_sn``이 공백이거나 ``num_samples``가
            bool이거나 1 미만일 때(CLI 경유가 아닌 직접 호출도 지킨다).
    """
    validate_nonblank_str(session_id, name="session_id")
    validate_nonblank_str(aircraft_sn, name="aircraft_sn")
    validate_positive_int(num_samples, name="num_samples")

    for i in range(num_samples):
        frame_ts, telemetry_ts = read_next_frame_telemetry_timestamps()
        sample = FrameTelemetrySample(
            sample_index=i,
            session_id=session_id,
            aircraft_sn=aircraft_sn,
            frame_timestamp_utc=frame_ts.isoformat(),
            telemetry_timestamp_utc=telemetry_ts.isoformat(),
            delta_ms=compute_delta_ms(frame_ts, telemetry_ts),
        )
        append_sample_jsonl(out_path, sample)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _cmd_collect(args: argparse.Namespace) -> int:  # noqa: PLR0911
    try:
        session_id = validate_nonblank_str(args.session_id, name="--session-id")
        aircraft_sn = validate_nonblank_str(args.aircraft_sn, name="--aircraft-sn")
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    # --timestamp-basis는 argparse required=True로 이미 강제되지만(무의식적 선택
    # 차단), --source와 무관하게 여기서도 방어적으로 재확인한다.
    timestamp_basis: str = args.timestamp_basis
    if timestamp_basis not in ("sensor", "recv"):
        print(
            f"오류: --timestamp-basis는 'sensor' 또는 'recv'여야 한다 (받음: {timestamp_basis!r})",
            file=sys.stderr,
        )
        return 2

    if args.source == "tap-log":
        if not args.tap_log:
            print("오류: --source tap-log 에는 --tap-log PATH가 필수다", file=sys.stderr)
            return 2
        try:
            samples = convert_tap_log_to_samples(
                Path(args.tap_log),
                session_id=session_id,
                aircraft_sn=aircraft_sn,
                timestamp_basis=timestamp_basis,
            )
        except ValueError as exc:
            print(f"오류: tap-log 변환 실패 — {exc}", file=sys.stderr)
            return 2

        out_path = Path(args.out)
        for sample in samples:
            append_sample_jsonl(out_path, sample)
        print(
            f"수집 완료(tap-log 변환): {args.out} ({len(samples)}건, "
            f"timestamp_basis={timestamp_basis})"
        )
        return 0

    # --source psdk(기본값) — 기존 미구현 경로, fail-closed 유지(D3).
    try:
        num_samples = validate_positive_int(args.num_samples, name="--num-samples")
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    collect_session(
        session_id=session_id,
        aircraft_sn=aircraft_sn,
        out_path=Path(args.out),
        num_samples=num_samples,
    )
    print(f"수집 완료: {args.out}")
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:  # noqa: PLR0912, PLR0915
    mode: str = args.mode
    override_flags = {
        "--target-p95-ms": args.target_p95_ms,
        "--min-sample-count": args.min_sample_count,
        "--delta-tolerance-ms": args.delta_tolerance_ms,
    }
    supplied_overrides = [name for name, value in override_flags.items() if value is not None]

    if mode == "official":
        if supplied_overrides:
            joined = ", ".join(supplied_overrides)
            print(
                "오류: --mode official(기본값)에서는 공식 Acceptance Profile"
                f"({OFFICIAL_PROFILE.profile_id!r})의 값을 CLI로 완화할 수 없다 — "
                f"제공된 override 플래그: {joined}. 실험적으로 다른 값을 쓰려면 "
                "--mode exploratory를 명시할 것(단, exploratory 결과는 acceptance_status가 "
                "항상 null이며 PASS/VERIFIED 근거로 쓸 수 없다).",
                file=sys.stderr,
            )
            return 2
        profile = OFFICIAL_PROFILE
    else:
        try:
            target_p95_ms = validate_finite_positive(
                args.target_p95_ms if args.target_p95_ms is not None else DEFAULT_TARGET_P95_MS,
                name="--target-p95-ms",
            )
            min_sample_count = validate_positive_int(
                args.min_sample_count
                if args.min_sample_count is not None
                else DEFAULT_MIN_SAMPLE_COUNT,
                name="--min-sample-count",
            )
            delta_tolerance_ms = validate_finite_nonnegative(
                args.delta_tolerance_ms
                if args.delta_tolerance_ms is not None
                else DEFAULT_DELTA_TOLERANCE_MS,
                name="--delta-tolerance-ms",
            )
            profile = AcceptanceProfile(
                profile_id=EXPLORATORY_PROFILE_ID,
                target_p95_ms=target_p95_ms,
                min_sample_count=min_sample_count,
                delta_tolerance_ms=delta_tolerance_ms,
            )
        except ValueError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 2

    in_path = Path(args.inp)
    load_result = (
        load_official_evidence(in_path)
        if mode == "official"
        else load_exploratory_evidence(in_path, delta_tolerance_ms=profile.delta_tolerance_ms)
    )

    sample_indices = [s.sample_index for s in load_result.samples]
    session_ids = sorted({s.session_id for s in load_result.samples})
    aircraft_sns = sorted({s.aircraft_sn for s in load_result.samples})
    timestamp_bases = sorted(
        {s.timestamp_basis for s in load_result.samples if s.timestamp_basis is not None}
    )

    base_fields: dict[str, Any] = {
        "mode": mode,
        "input": str(in_path),
        "input_sha256": load_result.sha256,
        "summarized_at_utc": datetime.now(UTC).isoformat(),
        "acceptance_profile_id": profile.profile_id,
        "profile_target_p95_ms": profile.target_p95_ms,
        "profile_min_sample_count": profile.min_sample_count,
        "profile_delta_tolerance_ms": profile.delta_tolerance_ms,
        "session_id": session_ids[0] if len(session_ids) == 1 else None,
        "session_ids_observed": session_ids,
        "aircraft_sn": aircraft_sns[0] if len(aircraft_sns) == 1 else None,
        "aircraft_sns_observed": aircraft_sns,
        "timestamp_basis": timestamp_bases[0] if len(timestamp_bases) == 1 else None,
        "timestamp_basis_observed": timestamp_bases,
        "timestamp_basis_notice": _timestamp_basis_notice(timestamp_bases),
        "sample_index_first": min(sample_indices) if sample_indices else None,
        "sample_index_last": max(sample_indices) if sample_indices else None,
        "valid_sample_count": len(load_result.samples),
        "rejected_line_count": len(load_result.rejected),
        "rejected_lines": [asdict(r) for r in load_result.rejected],
        "warnings": list(load_result.warnings),
    }

    if mode == "official":
        judgement = judge_official(load_result)
        result: dict[str, Any] = {
            **base_fields,
            "summary": asdict(judgement.summary) if judgement.summary is not None else None,
            "evidence_status": judgement.evidence_status.value,
            "evidence_reasons": list(judgement.evidence_reasons),
            "measurement_status": judgement.measurement_status.value,
            "acceptance_status": (
                judgement.acceptance_status.value if judgement.acceptance_status else None
            ),
            "reason_code": judgement.reason_code.value,
        }
    else:
        exploratory = judge_exploratory(load_result, profile=profile)
        result = {
            **base_fields,
            "summary": asdict(exploratory.summary) if exploratory.summary is not None else None,
            "measurement_status": exploratory.measurement_status.value,
            "acceptance_status": None,
            "exploratory_meets_target": exploratory.meets_target,
            "reason_code": (
                AcceptanceReasonCode.NOT_MEASURED.value
                if exploratory.measurement_status is MeasurementStatus.NOT_MEASURED
                else "EXPLORATORY_NOT_OFFICIAL"
            ),
            "notice": (
                f"EXPLORATORY 모드 결과다(profile_id={profile.profile_id!r}, 공식 profile="
                f"{OFFICIAL_PROFILE.profile_id!r} 아님) — acceptance_status/"
                "exploratory_meets_target은 capability VERIFIED 승격 근거로 쓸 수 없다. "
                "공식 판정은 --mode official(기본값)로만 낸다."
            ),
        }

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"요약 기록: {out_path}", file=sys.stderr)

    if load_result.rejected:
        print(
            f"주의: {len(load_result.rejected)}개 줄이 검증에 실패해 제외됐다 — "
            "rejected_lines 참고",
            file=sys.stderr,
        )

    if mode == "official":
        if judgement.evidence_status is EvidenceStatus.INVALID:
            print(
                "주의: evidence_status=INVALID — 공식 PASS 불가. 사유: "
                + "; ".join(judgement.evidence_reasons),
                file=sys.stderr,
            )
        if (
            judgement.acceptance_status is AcceptanceStatus.FAIL
            and judgement.reason_code is AcceptanceReasonCode.REQUIREMENT_NOT_MET
        ):
            assert judgement.summary is not None
            print(
                f"주의: acceptance_status=FAIL — p95={judgement.summary.p95_ms:.2f}ms > 목표 "
                f"{judgement.summary.target_p95_ms:.2f}ms. 이 결과로 VERIFIED 승격 금지 "
                "(docs/hil/CAPABILITY_ACCEPTANCE.md 절차를 따를 것 — 이 스크립트는 승격 "
                "판정을 내리지 않는다)",
                file=sys.stderr,
            )
        elif judgement.measurement_status is MeasurementStatus.NOT_MEASURED:
            print(
                "주의: measurement_status=NOT_MEASURED(표본 0건) — VERIFIED 승격 근거 없음",
                file=sys.stderr,
            )
        elif judgement.acceptance_status is AcceptanceStatus.INSUFFICIENT_SAMPLES:
            assert judgement.summary is not None
            print(
                f"주의: acceptance_status=INSUFFICIENT_SAMPLES — 표본 "
                f"{judgement.summary.sample_count}건 < 권장 최소 {profile.min_sample_count}건. "
                "PASS/FAIL 어느 쪽도 아직 주장하지 않는다",
                file=sys.stderr,
            )
    else:
        print(
            "주의: --mode exploratory 결과다 — acceptance_status는 항상 null이며 "
            "capability VERIFIED 승격 근거로 사용할 수 없다.",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frame–Telemetry 시간차 수집·요약 (PRD §21.1, INV-025 전제조건).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser(
        "collect", help="실기에서 Frame/Telemetry 쌍을 수집한다 (PSDK 미연동 — 현재 항상 실패)."
    )
    p_collect.add_argument(
        "--session-id", required=True, help="docs/hil/RAW_LOG_CONVENTIONS.md 형식의 세션 ID"
    )
    p_collect.add_argument("--aircraft-sn", required=True, help="기체 시리얼넘버")
    p_collect.add_argument("--out", required=True, help="출력 JSONL 경로")
    p_collect.add_argument(
        "--num-samples", type=int, default=200, help="수집할 표본 수 (기본 200, --source psdk 전용)"
    )
    p_collect.add_argument(
        "--source",
        choices=["tap-log", "psdk"],
        default="psdk",
        help=(
            "psdk(기본값): PSDK 직접 연동(현재 미구현 — NotImplementedError). "
            "tap-log: edge/psdk-tap이 쓴 raw NDJSON(--tap-log)을 공식 JSONL로 변환한다."
        ),
    )
    p_collect.add_argument(
        "--tap-log", default=None, help="--source tap-log일 때 필수 — C tap이 쓴 raw NDJSON 경로"
    )
    p_collect.add_argument(
        "--timestamp-basis",
        choices=["sensor", "recv"],
        required=True,
        help=(
            "필수(기본값 없음 — 무의식적 선택을 차단, HARDWARE_SESSION_PLAYBOOK.md 7단계). "
            "sensor: 카메라/FC 장치 자체 타임스탬프(capability 미충족 시 fail-closed 중단). "
            "recv: 호스트가 수신한 monotonic clock 기준 시각 — 센서 시각 정합이 아니다."
        ),
    )
    p_collect.set_defaults(func=_cmd_collect)

    p_summarize = sub.add_parser(
        "summarize",
        help=(
            "이미 수집된 JSONL을 검증하며 읽어 공식/실험 판정을 낸다 (실기 없이 실행 가능)."
        ),
    )
    p_summarize.add_argument("--in", dest="inp", required=True, help="입력 JSONL 경로")
    p_summarize.add_argument("--out", default=None, help="요약 JSON 출력 경로(선택)")
    p_summarize.add_argument(
        "--mode",
        choices=["official", "exploratory"],
        default="official",
        help=(
            "official(기본값): 공식 Acceptance Profile "
            f"({OFFICIAL_PROFILE.profile_id!r})만 쓴다 — CLI override 불가. "
            "exploratory: 아래 세 플래그로 다른 값을 실험할 수 있으나 acceptance_status는 "
            "항상 null이며 VERIFIED 근거로 쓸 수 없다."
        ),
    )
    p_summarize.add_argument(
        "--target-p95-ms",
        type=float,
        default=None,
        help=(
            f"[--mode exploratory 전용] 비교 대상 p95 목표값 ms (기본 {DEFAULT_TARGET_P95_MS}). "
            "official 모드에서 지정하면 오류."
        ),
    )
    p_summarize.add_argument(
        "--min-sample-count",
        type=int,
        default=None,
        help=(
            "[--mode exploratory 전용] 최소 표본 수 "
            f"(기본 {DEFAULT_MIN_SAMPLE_COUNT}). official 모드에서 지정하면 오류."
        ),
    )
    p_summarize.add_argument(
        "--delta-tolerance-ms",
        type=float,
        default=None,
        help=(
            "[--mode exploratory 전용] 저장된 delta_ms와 timestamp 재계산값 사이 허용 오차 ms "
            f"(기본 {DEFAULT_DELTA_TOLERANCE_MS}). official 모드에서 지정하면 오류."
        ),
    )
    p_summarize.set_defaults(func=_cmd_summarize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
