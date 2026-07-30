"""KSI Core FastAPI 앱 팩토리 (ADR-KSI-001, ADR-KSI-008).

Core는 지리공간·워크플로 control plane이다 — 비행 중 실시간 판단은 Manifold Edge가,
저수준 비행 안전은 DJI Flight Controller가 소유한다(INV-001). 이 앱은 그 경계를
코드로 지킨다:

- **프레임별 비행제어 엔드포인트를 두지 않는다.** Core가 노출하는 것은 계약·정책·
  상태 조회이지 조종 명령이 아니다(INV-001, 00_READ_FIRST "구현 금지").
- **Capability는 VERIFIED만 노출한다.** ``/capabilities``는
  :meth:`~ksi_core.capability.registry.CapabilityRegistry.list_operational` 만
  호출한다 — SPIKE_REQUIRED/BLOCKED가 운영 API로 새어나가지 않는다(INV-041).

## fail-closed 조립 (ADR-KSI-008 §3) — "인증 없는 보호 표면은 존재할 수 없다"

``create_app`` 은 다음 결합 위반을 :class:`ValueError` 로 즉시 거부한다(오염된
조립으로 기동하지 않는다):

1. 보호 표면(``edge_sync_store``·``event_store``·``site_store``·``mission_store``·
   서명키) 을 하나라도 주입하면 ``auth_registry`` 가 필수다.
2. 서명키(``mission_signing_key``/``mission_signing_key_id``) 가 주어지면
   ``mission_store``·``site_store`` 가 모두 필수다 — 발급 레코드가 durable
   기록되기 전에는 201 을 반환하지 않는다(고아 발급 금지).
3. ``edge_sync_store`` 가 주어지면 ``event_store`` 가 필수다 — 수신은 ACK 했는데
   트리아지에 보이지 않는 조용한 유실 표면을 막는다.
4. 서명키·edge_sync_store 는 각각 절반만 주어질 수 없다(기존 규칙 유지).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from ksi_core.auth import AuthRegistry
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_core.events import EventStore
    from ksi_core.mission_records import MissionStore
    from ksi_core.sites import SiteStore


def create_app(
    *,
    registry: CapabilityRegistry | None = None,
    auth_registry: AuthRegistry | None = None,
    edge_sync_store: EdgeSyncStore | None = None,
    event_store: EventStore | None = None,
    site_store: SiteStore | None = None,
    mission_store: MissionStore | None = None,
    mission_signing_key: Ed25519PrivateKey | None = None,
    mission_signing_key_id: str | None = None,
    expose_docs: bool = True,
) -> FastAPI:
    """Core 앱을 만든다.

    Args:
        registry: 주입할 Capability Registry. ``None``이면 PRD §20.3 SPIKE 9종을
            시드한 새 레지스트리를 만든다 — 시드 직후 노출 가능한 capability는
            0건이다(실기 검증 증거가 없으므로, INV-041).
        expose_docs: ``True``(기본)면 FastAPI 기본 문서 라우트(``/openapi.json``·
            ``/docs``·``/redoc``)가 무인증으로 열린다 — 이 셋은 ``/health``·
            ``/capabilities`` 와 함께 공개 allowlist 다(계약 서술 자체가 민감
            정보는 아니다). 운영 배포에서 계약 표면을 외부에 노출하고 싶지 않으면
            ``False`` 로 꺼서 세 라우트를 전부 존재하지 않게 만든다(감사 #25·#35
            재검토 — "문서 라우트만 공개" 주장이 스위치 부재로 반증됐던 사각지대).
        auth_registry: bearer 토큰 → Principal 매핑(ADR-KSI-008 §2). 보호 표면
            (아래 5개 인자 중 하나라도)을 주입하려면 이것도 함께 줘야 한다 —
            인증 없는 보호 표면은 조립 자체가 거부된다. 단독으로 주면
            ``/v1/auth/whoami`` 만 장착된다.
        edge_sync_store: Edge→Core EventBundle 멱등 수신 저장소. ``None``이면
            edge-sync 엔드포인트가 **존재하지 않는다** — durable 저장 없이 수신
            API 만 열리는 구성(ACK 후 유실 경로)을 타입이 아니라 조립에서 막는다.
        event_store: Event projection·트리아지 저장소. ``edge_sync_store``가
            주어지면 **함께 주어져야 한다**(ADR-KSI-008 §3) — 수신은 ACK 했는데
            트리아지에 보이지 않는 조용한 유실 표면을 조립에서 막는다. edge-sync
            없이 단독으로 주어지면 ``/v1/events`` 조회·트리아지 엔드포인트만
            장착된다(예: Site/Mission 만 있고 Edge 수신은 아직 없는 배포).
        site_store: Site 상태머신 영속·조회·전이 저장소. 주어지면 ``/v1/sites``
            표면이 장착되고, 서명키 발급 경로의 site 등록 대조(존재+siteFrame
            일치)도 이 저장소로
            배선된다(``site_store.get``).
        mission_store: Mission 발급 이력 영속·조회 저장소. 주어지면 ``/v1/missions``
            조회 표면(``mount_mission_records``)이 장착된다. 서명키가 주어지면
            ``site_store`` 와 함께 필수다(위 조립 규칙 2).
        mission_signing_key: Mission Contract 발급 서명키. ``mission_signing_key_id``와
            둘 다 주어져야 발급 엔드포인트가 장착된다(ADR-KSI-007) — 서명키 없이는
            엔드포인트가 존재하지 않는다(edge_sync_store와 동일한 fail-closed 조립).
            주어지면 ``mission_store``·``site_store`` 가 모두 필수다(ADR-KSI-008 §3
            — 발급 레코드가 durable 기록되기 전에는 201 을 반환하지 않는다).
        mission_signing_key_id: 서명 블록에 실릴 keyId — 검증 측 KeyRegistry에
            등록된 것과 일치해야 한다.
    """
    capability_registry = registry if registry is not None else CapabilityRegistry()
    if registry is None:
        seed_prd_spikes(capability_registry)

    app = FastAPI(
        title="KSI Core",
        version="0.0.1",
        summary="KSI Site Intelligence Core — 계약·정책·상태 control plane (비행제어 없음)",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
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
        # 공개 응답은 식별·상태만(감사 #49) — firmware/PSDK 버전은 배치 기체의
        # 취약점 표적화에 쓰이는 정보라 인증된 내부·감사 경로에서만 제공한다.
        return {
            "capabilities": [
                {
                    "capabilityId": record.capability_id,
                    "title": record.title,
                    "state": record.state.value,
                }
                for record in operational
            ],
            "count": len(operational),
        }

    # ── fail-closed 결합 검증(장착 전에 전부 확인 — 절반 조립으로 기동하지 않는다) ──

    if mission_signing_key is not None or mission_signing_key_id is not None:
        if mission_signing_key is None or mission_signing_key_id is None:
            raise ValueError(
                "mission_signing_key와 mission_signing_key_id는 함께 주어져야 한다"
                " — 절반만 있는 서명 설정으로 조립하지 않는다"
            )
        if mission_store is None or site_store is None:
            raise ValueError(
                "mission_signing_key 가 주어지면 mission_store 와 site_store 가 모두"
                " 필수다(ADR-KSI-008 §3) — 발급 레코드가 durable 기록되기 전에는 201 을"
                " 반환하지 않는다(고아 발급 금지)"
            )

    if edge_sync_store is not None and event_store is None:
        raise ValueError(
            "edge_sync_store 는 event_store 와 함께 주어져야 한다(ADR-KSI-008 §3)"
            " — 수신은 ACK 했는데 트리아지에 보이지 않는 유실 표면으로 조립하지 않는다"
        )

    protected_surface = any(
        surface is not None
        for surface in (
            edge_sync_store,
            event_store,
            site_store,
            mission_store,
            mission_signing_key,
        )
    )
    if protected_surface and auth_registry is None:
        raise ValueError(
            "보호 표면(edge_sync_store·event_store·site_store·mission_store·서명키)을"
            " 하나라도 주입하려면 auth_registry 가 필수다(ADR-KSI-008 §3) — 인증 없는"
            " 보호 표면은 존재할 수 없다"
        )

    # ── 장착(순서: 인증 → site → edge-sync/events → mission 발급 → mission 조회) ──

    if auth_registry is not None:
        from ksi_core.auth import mount_auth

        mount_auth(app, auth_registry)

    if site_store is not None:
        from ksi_core.sites import mount_sites

        mount_sites(app, site_store)

    if edge_sync_store is not None:
        from ksi_core.edge_sync import mount_edge_sync

        # event_store 는 위에서 함께 주어졌음을 확인했다(None 이 아니다).
        assert event_store is not None  # noqa: S101 -- 위 결합 검증이 보장
        mount_edge_sync(app, edge_sync_store, event_store=event_store)

    if event_store is not None:
        from ksi_core.events import mount_events

        # edge_sync_store 유무와 무관하게 /v1/events 조회·트리아지 표면은 event_store
        # 가 있으면 항상 장착된다 — edge 수신이 있는 배포에서도 트리아지 화면이
        # 필요하다(mount_edge_sync 는 ingest 라우터만 소유한다).
        mount_events(app, event_store)

    if mission_signing_key is not None:
        # 위 결합 검증이 mission_signing_key_id·mission_store·site_store 를
        # 전부 non-None 으로 보장한다.
        assert mission_signing_key_id is not None  # noqa: S101
        assert mission_store is not None  # noqa: S101
        assert site_store is not None  # noqa: S101

        from ksi_core.mission_issuance import mount_mission_issuance
        from ksi_core.mission_plans import mount_mission_plans

        _mission_store = mission_store
        _site_store = site_store

        def _site_frame_lookup(site_id: str) -> dict[str, Any] | None:
            """등록된 site 의 canonical siteFrame(camelCase dict) — 미등록이면 None.

            발급 요청의 siteFrame 과 정확 일치 대조(SITE_FRAME_MISMATCH)에 쓰인다
            — 등록 좌표계와 어긋난 계약·KMZ 짝 발급 차단(ADR-KSI-007).
            """
            record = _site_store.get(site_id)
            return None if record is None else dict(record.site_frame)

        mount_mission_issuance(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            site_frame_lookup=_site_frame_lookup,
        )
        mount_mission_plans(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            site_frame_lookup=_site_frame_lookup,
        )

    if mission_store is not None:
        from ksi_core.mission_records import mount_mission_records

        mount_mission_records(app, mission_store=mission_store)

    return app
