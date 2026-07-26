"""Hardware Spike 증거 레코드 (Track A, INV-041 강제 강화).

## 왜 문자열 evidence로는 부족한가

P0-5의 ``CapabilityRegistry.transition()`` 은 evidence를 **비어있지 않은 문자열**로만
요구했다. 그러면 ``evidence="테스트했음"`` 같은 값으로도 VERIFIED 승격이 가능하다 —
증거 게이트가 형식적으로만 존재하는 상태다.

독립 검토(2026-07-27)가 지정한 11개 필드를 구조로 요구해, "무엇을 어떤 조건에서 어떻게
확인했고 실패는 무엇이었나"가 없으면 승격 자체가 불가능하게 한다. 실기 세션에서 이
레코드를 채우는 것이 곧 Spike 절차다.

## 실패를 기록하도록 강제한다

``failure_result`` 는 **필수**다(빈 문자열 금지). 실패가 없었다면 "관측된 실패 없음"과
그 근거를 적어야 한다 — 실패 칸이 비어 있는 증거는 "실패를 안 봤다"와 "실패를 찾지
않았다"를 구분할 수 없고, 후자를 전자로 읽으면 검증되지 않은 기능이 VERIFIED가 된다.

## 범위

이 모듈은 증거의 **형식**을 강제한다. 증거 내용의 진위는 코드가 판정할 수 없다 —
그것은 사람(operator)과 raw log의 몫이며, 그래서 두 필드를 모두 요구한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class IncompleteSpikeEvidenceError(ValueError):
    """Spike 증거 레코드의 필수 필드가 비어 있음 — VERIFIED 승격 불가."""


@dataclass(frozen=True, slots=True)
class SpikeEvidence:
    """실기 Spike 1건의 증거. 모든 필드가 비어있지 않아야 유효하다.

    Attributes:
        aircraft_firmware: 기체 펌웨어 버전(예: ``M4D v08.02.0100``).
        rc_firmware: RC(조종기) 펌웨어 버전.
        manifold_image: Manifold 3 이미지/JetPack 식별자.
        psdk_version: PSDK 버전.
        build_commit: 시험한 KSI 빌드의 git commit SHA.
        test_procedure: 무엇을 어떤 순서로 했는지 — 재현 가능한 절차.
        raw_log_ref: 원본 로그 아티팩트 참조(경로·객체스토리지 URI 등).
        latency_result: 측정된 지연 결과. 측정하지 않았다면 그 사실과 이유를 적는다.
        failure_result: 관측된 실패. 없었다면 "관측된 실패 없음 + 근거"를 적는다
            (빈 값 금지 — 위 모듈 docstring 참고).
        operator: 시험을 수행한 사람.
        observed_at: 시험 시각(UTC, tz-aware).
    """

    aircraft_firmware: str
    rc_firmware: str
    manifold_image: str
    psdk_version: str
    build_commit: str
    test_procedure: str
    raw_log_ref: str
    latency_result: str
    failure_result: str
    operator: str
    observed_at: datetime

    def __post_init__(self) -> None:
        blank = [name for name, value in self._text_fields() if not value.strip()]
        if blank:
            raise IncompleteSpikeEvidenceError(
                f"Spike 증거 필수 필드가 비어 있다: {sorted(blank)} — "
                "VERIFIED 승격에는 11개 필드가 모두 필요하다"
            )
        if self.observed_at.tzinfo is None:
            raise IncompleteSpikeEvidenceError("observed_at 은 tz-aware 여야 한다")
        if self.observed_at.utcoffset() != _ZERO_OFFSET:
            raise IncompleteSpikeEvidenceError(
                f"observed_at 은 UTC여야 한다 (offset={self.observed_at.utcoffset()})"
            )

    def _text_fields(self) -> list[tuple[str, str]]:
        return [
            ("aircraft_firmware", self.aircraft_firmware),
            ("rc_firmware", self.rc_firmware),
            ("manifold_image", self.manifold_image),
            ("psdk_version", self.psdk_version),
            ("build_commit", self.build_commit),
            ("test_procedure", self.test_procedure),
            ("raw_log_ref", self.raw_log_ref),
            ("latency_result", self.latency_result),
            ("failure_result", self.failure_result),
            ("operator", self.operator),
        ]

    def summary(self) -> str:
        """Capability 레코드에 저장할 한 줄 요약(전체 레코드는 별도 보관)."""
        return (
            f"spike@{self.observed_at.isoformat()} by {self.operator} — "
            f"aircraft={self.aircraft_firmware} rc={self.rc_firmware} "
            f"manifold={self.manifold_image} psdk={self.psdk_version} "
            f"build={self.build_commit} log={self.raw_log_ref}"
        )


_ZERO_OFFSET = datetime(2000, 1, 1, tzinfo=UTC).utcoffset()
