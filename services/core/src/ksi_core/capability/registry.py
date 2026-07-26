"""Capability Registry (P0-5, INV-041) — 장비 기능 검증 상태의 Core 소유 레지스트리.

MASTER_PRD §20.1(DJI 공식 확인사항) vs §20.3(SPIKE_REQUIRED)의 구분을 코드로 강제한다:
"공식 문서에 기능이 언급됐다"는 VERIFIED가 아니다. VERIFIED는 실기 검증 증거가 있을
때만 도달하며, 그 전까지는 :meth:`CapabilityRegistry.list_operational` 이 노출을
차단한다(운영 UI·Mission Contract 정책 선택지에 나타나지 않는다).

주의: 여기서 다루는 ``CapabilityVerificationState`` 는 **장비 기능(API·연동) 검증**
축이다. 장비 클래스(탐지 대상)의 지원 단계(``EquipmentSupportLevel``)는 별개
개념이며, 두 축을 이 레지스트리 안에서 섞지 않는다(``ksi_domain.capability`` 모듈
docstring 참고).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from ksi_domain.capability import (
    CapabilityVerificationState,
    IllegalCapabilityTransitionError,
    assert_capability_transition,
)
from ksi_domain.spike_evidence import SpikeEvidence


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """capability 레코드 1건.

    Attributes:
        capability_id: 안정적 식별자(예: ``SPIKE-DJI-01``).
        title: 사람이 읽는 설명.
        state: 현재 검증 상태.
        evidence: 현재 상태로 전이할 때 제시된 증거 참조(문서·HIL 로그 등). 초기
            등록(SPIKE_REQUIRED) 시점엔 아직 증거가 없을 수 있어 ``None`` 허용.
        firmware: 검증 시점 DJI 펌웨어 버전(선택).
        sdk: 검증 시점 PSDK/Cloud API 버전(선택).
        aircraft: 검증 대상 기체(선택, 예: ``Matrice 4D``).
        verified_at: ``VERIFIED`` 로 전이한 시각(그 외 상태면 ``None``).
        spike_evidence: ``VERIFIED`` 승격 시 제시된 구조화 Spike 증거(11개 필드).
            ``VERIFIED`` 상태에서는 **반드시** 존재한다 — 문자열 evidence만으로는
            "테스트했음" 같은 값이 통과하므로(Track A) 실기 승격에는 구조를 요구한다.
    """

    capability_id: str
    title: str
    state: CapabilityVerificationState
    evidence: str | None = None
    firmware: str | None = None
    sdk: str | None = None
    aircraft: str | None = None
    verified_at: datetime | None = None
    spike_evidence: SpikeEvidence | None = None


class CapabilityRegistry:
    """``capability_id → CapabilityRecord``. Core가 소유하는 단일 SSOT.

    :meth:`list_operational` 이 이 레지스트리의 핵심 불변식이다 — VERIFIED가 아닌
    항목은 그 조회에 절대 나타나지 않는다.
    """

    def __init__(self) -> None:
        self._records: dict[str, CapabilityRecord] = {}

    def register(
        self,
        capability_id: str,
        title: str,
        *,
        state: CapabilityVerificationState = CapabilityVerificationState.SPIKE_REQUIRED,
        evidence: str | None = None,
        firmware: str | None = None,
        sdk: str | None = None,
        aircraft: str | None = None,
    ) -> None:
        """신규 capability를 등록한다.

        초기 등록은 ``SPIKE_REQUIRED``(기본) 또는 ``BLOCKED``(사유 필수)만 허용한다 —
        ``VERIFIED``는 반드시 evidence를 강제하는 :meth:`transition` 을 거쳐야 하며
        초기 등록으로 직접 부여할 수 없다(반증 리뷰 2026-07-26 P0 — evidence 없이
        VERIFIED를 만들어 ``list_operational()`` 노출 게이트를 완전히 우회하는 결함이었다).
        중복 ``capability_id`` 등록은 거부한다(덮어쓰기 금지).

        Raises:
            ValueError: capability_id가 이미 등록돼 있을 때.
            IllegalCapabilityTransitionError: state=VERIFIED로 초기 등록을 시도하거나,
                state=BLOCKED인데 evidence가 비어있을 때.
        """
        if capability_id in self._records:
            raise ValueError(f"capability_id 중복 등록: {capability_id!r}")
        if state is CapabilityVerificationState.VERIFIED:
            raise IllegalCapabilityTransitionError(
                "VERIFIED는 초기 등록으로 부여할 수 없다 — SPIKE_REQUIRED로 등록 후 "
                "transition()으로 evidence와 함께 승격해야 한다(INV-041)"
            )
        if state is CapabilityVerificationState.BLOCKED and not (evidence and evidence.strip()):
            raise IllegalCapabilityTransitionError("BLOCKED 초기 등록에는 evidence(사유)가 필수다")

        self._records[capability_id] = CapabilityRecord(
            capability_id=capability_id,
            title=title,
            state=state,
            evidence=evidence,
            firmware=firmware,
            sdk=sdk,
            aircraft=aircraft,
            verified_at=None,  # 초기 등록은 VERIFIED를 금지하므로 항상 None
        )

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._records.get(capability_id)

    def transition(
        self,
        capability_id: str,
        nxt: CapabilityVerificationState,
        *,
        evidence: str,
        firmware: str | None = None,
        sdk: str | None = None,
        aircraft: str | None = None,
        now: datetime | None = None,
        spike_evidence: SpikeEvidence | None = None,
    ) -> CapabilityRecord:
        """등록된 capability의 상태를 전이한다 — evidence 없으면 거부(INV-041).

        ``VERIFIED`` 승격에는 문자열 evidence만으로 부족하고 **구조화된
        :class:`~ksi_domain.spike_evidence.SpikeEvidence`** 가 필수다(Track A) —
        "테스트했음" 같은 문자열이 실기 검증으로 통과하는 것을 막는다. BLOCKED 등
        다른 전이는 문자열 사유로 충분하다(차단은 보수적 방향이므로).

        Raises:
            KeyError: 미등록 capability_id.
            IllegalCapabilityTransitionError: 전이표 밖의 전이, evidence 누락, 또는
                VERIFIED 승격에 spike_evidence 누락.
        """
        current = self._records[capability_id]
        assert_capability_transition(current.state, nxt, evidence=evidence)
        if nxt is CapabilityVerificationState.VERIFIED and spike_evidence is None:
            raise IllegalCapabilityTransitionError(
                f"{capability_id}: VERIFIED 승격에는 구조화된 SpikeEvidence 가 필수다 "
                "(11개 필드 — 기체·RC 펌웨어, Manifold 이미지, PSDK 버전, build commit, "
                "시험절차, raw log, 지연 결과, 실패 결과, operator, 시각)"
            )
        updated = replace(
            current,
            state=nxt,
            evidence=evidence,
            firmware=firmware if firmware is not None else current.firmware,
            sdk=sdk if sdk is not None else current.sdk,
            aircraft=aircraft if aircraft is not None else current.aircraft,
            verified_at=(now or datetime.now(UTC))
            if nxt is CapabilityVerificationState.VERIFIED
            else None,
            # VERIFIED 를 벗어나면 증거도 함께 지운다 — 낡은 증거가 남아 다음 승격을
            # 정당화하는 것처럼 보이면 안 된다(회귀 후 재승격은 새 증거를 요구한다).
            spike_evidence=(
                spike_evidence if nxt is CapabilityVerificationState.VERIFIED else None
            ),
        )
        self._records[capability_id] = updated
        return updated

    def list_all(self) -> list[CapabilityRecord]:
        """전체 레코드(검증 상태 무관) — 감사·내부 대시보드용, 운영 노출 아님."""
        return list(self._records.values())

    def list_operational(self) -> list[CapabilityRecord]:
        """**VERIFIED만** 반환한다 (INV-041 강제 지점).

        SPIKE_REQUIRED/BLOCKED 항목은 이 메서드가 절대 반환하지 않는다 — 운영
        UI·Mission Contract 정책 선택지는 이 메서드만 호출해야 한다.
        """
        return [
            r for r in self._records.values() if r.state is CapabilityVerificationState.VERIFIED
        ]


@dataclass(frozen=True, slots=True)
class _PrdSpikeSeed:
    capability_id: str
    title: str


_PRD_20_3_SPIKES: list[_PrdSpikeSeed] = [
    _PrdSpikeSeed("SPIKE-DJI-01", "M4D 카메라별 실시간 프레임 접근"),
    _PrdSpikeSeed("SPIKE-DJI-02", "광각/중망원/망원 전환과 촬영·초점 제어"),
    _PrdSpikeSeed("SPIKE-DJI-03", "기체 Yaw/짐벌 Pitch API와 지연"),
    _PrdSpikeSeed("SPIKE-DJI-04", "FlyTo/Hold/Rejoin/Route Update"),
    _PrdSpikeSeed("SPIKE-DJI-05", "DJI 장애물 회피와 KSI 명령 동시동작"),
    _PrdSpikeSeed("SPIKE-DJI-06", "Pilot 2/Cloud API/PSDK 동시 제어권"),
    _PrdSpikeSeed("SPIKE-DJI-07", "Manifold 이벤트 네트워크 경로"),
    _PrdSpikeSeed("SPIKE-DJI-08", "Dock 3 물리 수납·전원·충전·운용"),
    _PrdSpikeSeed("SPIKE-DJI-09", "비행시간/발열/전력 영향"),
]
"""MASTER_PRD §20.3 SPIKE_REQUIRED 항목 9종 (원문 그대로, 순서 보존)."""


def seed_prd_spikes(registry: CapabilityRegistry) -> None:
    """PRD §20.3의 9개 SPIKE_REQUIRED 항목을 레지스트리에 시드한다.

    전부 ``SPIKE_REQUIRED`` 로 시작하며 등록 직후 ``list_operational()`` 에는
    하나도 나타나지 않아야 한다 — 이것이 "공식 문서 언급 ≠ VERIFIED"의 코드 증명이다.
    """
    for spike in _PRD_20_3_SPIKES:
        registry.register(spike.capability_id, spike.title)
