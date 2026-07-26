"""KSI Core FastAPI 앱 팩토리 (Stage C-2, ADR-KSI-001).

Core는 지리공간·워크플로 control plane이다 — 비행 중 실시간 판단은 Manifold Edge가,
저수준 비행 안전은 DJI Flight Controller가 소유한다(INV-001). 이 앱은 그 경계를
코드로 지킨다:

- **프레임별 비행제어 엔드포인트를 두지 않는다.** Core가 노출하는 것은 계약·정책·
  상태 조회이지 조종 명령이 아니다(INV-001, 00_READ_FIRST "구현 금지").
- **Capability는 VERIFIED만 노출한다.** ``/capabilities``는
  :meth:`~ksi_core.capability.registry.CapabilityRegistry.list_operational` 만
  호출한다 — SPIKE_REQUIRED/BLOCKED가 운영 API로 새어나가지 않는다(INV-041).

Stage C 범위는 앱 팩토리 + health + capability 조회 골격까지다. 인증·현장·임무·
이벤트 도메인 라우터는 이후 단계에서 붙인다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes


def create_app(*, registry: CapabilityRegistry | None = None) -> FastAPI:
    """Core 앱을 만든다.

    Args:
        registry: 주입할 Capability Registry. ``None``이면 PRD §20.3 SPIKE 9종을
            시드한 새 레지스트리를 만든다 — 시드 직후 노출 가능한 capability는
            0건이다(실기 검증 증거가 없으므로, INV-041).
    """
    capability_registry = registry if registry is not None else CapabilityRegistry()
    if registry is None:
        seed_prd_spikes(capability_registry)

    app = FastAPI(
        title="KSI Core",
        version="0.0.1",
        summary="KSI Site Intelligence Core — 계약·정책·상태 control plane (비행제어 없음)",
    )
    app.state.capability_registry = capability_registry

    @app.get("/health")
    def health() -> dict[str, str]:
        """liveness — 의존 서비스 상태를 확인하지 않는 순수 프로세스 생존 신호."""
        return {"status": "ok"}

    @app.get("/capabilities")
    def list_capabilities() -> dict[str, Any]:
        """**운영 가능한(VERIFIED) capability만** 반환한다 (INV-041).

        SPIKE_REQUIRED/BLOCKED 항목은 이 응답에 절대 포함되지 않는다 — 미검증 기능이
        운영 UI·Mission Contract 정책 선택지에 노출되는 것을 막는 게이트다. 감사용
        전체 목록은 이 공개 API가 아니라 내부 경로로 제공한다.
        """
        operational = capability_registry.list_operational()
        return {
            "capabilities": [
                {
                    "capabilityId": record.capability_id,
                    "title": record.title,
                    "state": record.state.value,
                    "firmware": record.firmware,
                    "sdk": record.sdk,
                    "aircraft": record.aircraft,
                    "verifiedAt": record.verified_at.isoformat()
                    if record.verified_at is not None
                    else None,
                }
                for record in operational
            ],
            "count": len(operational),
        }

    return app
