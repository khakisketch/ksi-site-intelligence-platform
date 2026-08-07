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
    from ksi_core.coverage_reports import CoverageReportStore
    from ksi_core.defect_candidates import DefectCandidateStore
    from ksi_core.edge_sync import EdgeSyncStore
    from ksi_core.events import EventStore
    from ksi_core.evidence import EvidenceStorage
    from ksi_core.mission_records import MissionStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore


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
    evidence_storage: EvidenceStorage | None = None,
    coverage_report_store: CoverageReportStore | None = None,
    source_media_store: SourceMediaStore | None = None,
    processing_job_store: ProcessingJobStore | None = None,
    defect_candidate_store: DefectCandidateStore | None = None,
    expose_docs: bool = True,
) -> FastAPI:
    """Core 앱을 만든다.

    Args:
        registry: 주입할 Capability Registry. ``None``이면 PRD §20.3 SPIKE 9종을
            시드한 새 레지스트리를 만든다 — 시드 직후 노출 가능한 capability는
            0건이다(실기 검증 증거가 없으므로, INV-041).
        expose_docs: ``True``(기본)면 FastAPI 기본 문서 라우트(``/openapi.json``·
            ``/docs``·``/docs/oauth2-redirect``·``/redoc``)가 무인증으로 열린다 —
            이 **넷**은 ``/health``·``/capabilities`` 와 함께 공개 allowlist 다
            (계약 서술 자체가 민감 정보는 아니다). ``/docs/oauth2-redirect`` 는
            ``/docs`` 를 켜면 FastAPI 가 함께 다는 라우트라 서술에서 빠져 있었다
            (s2-residual-hardening #5 — 서술이 실제 표면보다 좁으면 "무엇이
            공개인가"를 문서로 감사할 수 없다). 운영 배포에서 계약 표면을 외부에
            노출하고 싶지 않으면 ``False`` 로 꺼서 네 라우트를 전부 존재하지 않게
            만든다(감사 #25·#35 재검토 — "문서 라우트만 공개" 주장이 스위치 부재로
            반증됐던 사각지대).
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
        source_media_store: 원본 사진 번들(3D 파이프라인 입구) 등록·봉인 저장소.
            주어지면 ``mission_store`` 가 필수다(발급된 적 없는 임무의 번들은
            받지 않는다, coverage_report_store 와 동일 원칙). 라우트 장착은 그와
            별개로 ``evidence_storage`` 유무를 따른다 — presigned URL 을 발급할
            스토리지가 없으면 이 표면 자체가 장착되지 않는다(evidence 라우트와
            같은 관습).
        processing_job_store: 3D 재구성 처리 작업(ADR-KSI-012) 발급·상태전이
            저장소. ``source_media_store`` 와 ``site_store`` 가 모두 필수다 —
            입력은 봉인된 번들에서, 반출 허용 여부는 현장에서 읽는다(INV-050).
            둘 중 하나라도 없으면 요청이 그 값들을 스스로 주장하는 구성이 되므로
            조립에서 거부한다.
        defect_candidate_store: Phase 4 결함 후보(균열) 수신·조회 저장소.
            ``mission_store`` 와 ``source_media_store`` 가 모두 필수다 — 후보는
            "어느 임무의 어느 사진 위 픽셀 좌표인가"로만 의미를 가지므로, 그
            참조를 대조할 저장소 없이는 검증 불가능한 도형을 그대로 받게 된다.
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

    if evidence_storage is not None and event_store is None and source_media_store is None:
        raise ValueError(
            "evidence_storage 는 소비자 저장소(event_store 또는 source_media_store)와"
            " 함께 주어져야 한다(ADR-KSI-010 §1) — 아무도 쓰지 않는 오브젝트 스토리지를"
            " 매단 채 기동하지 않는다."
            "\n"
            " 원래 이 가드는 event_store 만 요구했다(증거는 사건에 매달리는 것이라 사건"
            " 원장 없이는 등록할 곳이 없다). 3D 파이프라인 입구(source_media)가 같은"
            " 스토리지 포트를 두 번째 소비자로 쓰면서 그 전제가 좁아졌다 — 가드를 푼"
            " 것이 아니라 소비자 집합을 실제에 맞춘 것이고, 소비자가 하나도 없으면"
            " 여전히 거부한다."
        )

    if edge_sync_store is not None and event_store is None:
        raise ValueError(
            "edge_sync_store 는 event_store 와 함께 주어져야 한다(ADR-KSI-008 §3)"
            " — 수신은 ACK 했는데 트리아지에 보이지 않는 유실 표면으로 조립하지 않는다"
        )

    if coverage_report_store is not None and mission_store is None:
        raise ValueError(
            "coverage_report_store 는 mission_store 와 함께 주어져야 한다(INV-010)"
            " — 발급된 적 없는 임무의 커버리지 보고는 '무슨 근거로 날았나'에 답할 수"
            " 없다. 보고서는 임무 발급 기록과 대조해서만 받는다"
        )

    if source_media_store is not None and mission_store is None:
        raise ValueError(
            "source_media_store 는 mission_store 와 함께 주어져야 한다"
            " — 발급된 적 없는 임무의 원본 미디어 번들은 '어느 site 소속인지'조차"
            " 알 수 없다(객체 키가 siteId 를 필요로 한다). coverage_report_store 와"
            " 동일 원칙"
        )

    if processing_job_store is not None and (
        source_media_store is None or site_store is None or evidence_storage is None
    ):
        raise ValueError(
            "processing_job_store 는 source_media_store·site_store·evidence_storage 와"
            " 함께 주어져야 한다(ADR-KSI-012, INV-050) — 처리 작업의 입력(장수·화소·"
            "digest)은 봉인된 번들이 정하고 반출 허용 여부는 현장이 정한다. 하나라도"
            " 없으면 그 값들을 요청이 스스로 주장하는 구성이 되므로 조립하지 않는다."
            " evidence_storage 는 워커가 원본을 받아갈 다운로드 URL 발급에 필요하다"
            " — 없으면 워커가 바이트를 읽을 수 없어 실측 대조가 성립하지 않고,"
            " 그러면 SUCCEEDED 게이트가 영구히 닫힌 조립이 된다"
        )

    if defect_candidate_store is not None and (
        mission_store is None or source_media_store is None
    ):
        raise ValueError(
            "defect_candidate_store 는 mission_store·source_media_store 와 함께 주어져야"
            " 한다 — 결함 후보는 '어느 임무의 어느 사진 위 좌표인가'로만 의미를 갖는다."
            " 참조 대상을 대조할 저장소가 없으면 서버는 그릴 수 없는 도형을 원장에"
            " 쌓게 되고, 그건 조회 시점에 정상으로 보인다(defect_candidates.py"
            " '서버는 후보를 그대로 받아 적지 않는다')"
        )

    protected_surface = any(
        surface is not None
        for surface in (
            edge_sync_store,
            event_store,
            site_store,
            mission_store,
            mission_signing_key,
            evidence_storage,
            coverage_report_store,
            source_media_store,
            processing_job_store,
            defect_candidate_store,
        )
    )
    if protected_surface and auth_registry is None:
        raise ValueError(
            "보호 표면(edge_sync_store·event_store·site_store·mission_store·서명키·"
            "커버리지 보고)을 하나라도 주입하려면 auth_registry 가 필수다(ADR-KSI-008 §3)"
            " — 인증 없는"
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
        # evidence_storage 가 없으면 증거 경로는 장착되지 않는다(404) — 스토리지
        # 없이 라우트만 살려두면 "업로드했는데 어디에도 없다"가 2xx 로 보인다
        # (ADR-KSI-010 §1).
        mount_events(app, event_store, evidence_storage=evidence_storage)

    if mission_signing_key is not None:
        # 위 결합 검증이 mission_signing_key_id·mission_store·site_store 를
        # 전부 non-None 으로 보장한다.
        assert mission_signing_key_id is not None  # noqa: S101
        assert mission_store is not None  # noqa: S101
        assert site_store is not None  # noqa: S101

        from ksi_core.mission_issuance import mount_mission_issuance
        from ksi_core.mission_plans import mount_mission_plans
        from ksi_core.mission_records import SiteLookupResult

        _mission_store = mission_store
        _site_store = site_store

        def _site_lookup(site_id: str) -> SiteLookupResult | None:
            """등록된 site 의 canonical siteFrame + 현재 상태 — 미등록이면 None.

            siteFrame 은 발급 요청과의 정확 일치 대조(SITE_FRAME_MISMATCH)에
            쓰인다 — 등록 좌표계와 어긋난 계약·KMZ 짝 발급 차단(ADR-KSI-007).
            status 는 임무타입×현장상태 게이트(INV-052, "먼저 매핑, 그 다음
            사전지도 기반 자율")에 쓰인다 — 이 둘을 한 스냅샷으로 묶어 반환하는
            이유는 SiteLookupResult docstring 참조.
            """
            record = _site_store.get(site_id)
            if record is None:
                return None
            return SiteLookupResult(site_frame=dict(record.site_frame), status=record.status)

        mount_mission_issuance(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            site_lookup=_site_lookup,
        )
        mount_mission_plans(
            app,
            private_key=mission_signing_key,
            key_id=mission_signing_key_id,
            mission_store=_mission_store,
            site_lookup=_site_lookup,
        )

    if mission_store is not None:
        from ksi_core.mission_records import mount_mission_records

        # coverage_report_store 는 mission_store 보다 늦게(279행) 조건부 장착되지만,
        # 이 시점에 이미 함수 인자로 들어와 있다(결합 검증이 mission_store 동반을
        # 보장) — 목록/상세 응답에 파생 커버리지 필드를 싣기 위해 여기서 넘긴다.
        mount_mission_records(
            app, mission_store=mission_store, coverage_report_store=coverage_report_store
        )

    if coverage_report_store is not None:
        from ksi_core.coverage_reports import mount_coverage_reports

        mount_coverage_reports(app, coverage_report_store)

    if source_media_store is not None and evidence_storage is not None:
        # evidence_storage 없이는 라우트를 장착하지 않는다(evidence 라우트와 같은
        # 관습) — presigned URL 을 낼 스토리지가 없으면 "업로드했는데 어디에도
        # 없다"가 2xx 로 보이는 경로를 만들지 않는다. store 자체(journal)는
        # evidence_storage 없이도 구성될 수 있지만(위 결합 검증은 mission_store만
        # 요구), 그 경우 이 표면은 존재하지 않는다.
        from ksi_core.source_media import mount_source_media

        mount_source_media(app, source_media_store, evidence_storage)

    if processing_job_store is not None:
        # evidence_storage 는 위 결합 검증이 이미 보장한다(워커가 원본을 받아갈
        # 다운로드 URL 발급에 필요 — GET .../input).
        assert evidence_storage is not None  # noqa: S101 -- 위 결합 검증의 사후조건
        from ksi_core.processing_jobs import mount_processing_jobs

        mount_processing_jobs(app, processing_job_store, evidence_storage)

    if defect_candidate_store is not None:
        from ksi_core.defect_candidates import mount_defect_candidates

        mount_defect_candidates(app, defect_candidate_store)

    return app
