"""``ksi_core.app.create_app`` fail-closed 결합 규칙 전수 검증 (ADR-KSI-008 §3).

app.py 의 조립 규칙(모듈 docstring "fail-closed 조립" 절, 4항목)이 실제로
``ValueError`` 를 던지는지 이전에는 0건이 검증하고 있었다(재검토 P3) — 오염된
부분 조립(인증 없는 보호 표면·미기록 발급·조용한 유실 표면)이 조용히 기동해도
어떤 테스트도 잡지 못하는 사각지대였다.

이 파일은 4 갈래를 전수 검증한다:
1. 보호 표면(edge_sync_store·event_store·site_store·mission_store) 각각
   단독으로 주어지고 ``auth_registry`` 가 없으면 ``ValueError``.
2. 서명키(+key_id)만 주어지고 ``mission_store``/``site_store`` 가 없으면
   ``ValueError``(고아 발급 금지 규칙이 auth_registry 규칙보다 먼저 걸린다).
3. ``edge_sync_store`` 만 주어지고 ``event_store`` 가 없으면 ``ValueError``
   (조용한 유실 표면 방지 규칙).
4. 위 규칙을 전부 만족하는 전량 정상 조립은 성공한다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core import app as app_module
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.change_detection import ChangeDetectionStore
from ksi_core.defect_candidates import DefectCandidateStore
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore
from ksi_core.equipment_states import EquipmentStateStore
from ksi_core.events import EventStore
from ksi_core.mission_records import MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore


def _digest(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("assembly-test-token"),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _event_store(tmp_path: Path) -> EventStore:
    return EventStore(DurableJournal(tmp_path / "events" / "journal.jsonl"))


def _site_store(tmp_path: Path) -> SiteStore:
    return SiteStore(DurableJournal(tmp_path / "sites.jsonl"))


def _mission_store(tmp_path: Path) -> MissionStore:
    return MissionStore(DurableJournal(tmp_path / "missions.jsonl"))


def _edge_sync_store(tmp_path: Path) -> EdgeSyncStore:
    return EdgeSyncStore(tmp_path / "edge-journal.jsonl")


def _defect_candidate_store(tmp_path: Path, mission_store: MissionStore) -> DefectCandidateStore:
    return DefectCandidateStore(
        DurableJournal(tmp_path / "defects.jsonl"),
        mission_store=mission_store,
        source_media_store=SourceMediaStore(
            DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
        ),
    )


# ── 규칙 1: 보호 표면 각각 단독으로 auth_registry 없이 → ValueError ──────────
#
# edge_sync_store·서명키는 각자 다른 규칙(3·2)이 auth_registry 검사보다 먼저
# 걸리므로, 규칙 1 을 순수하게 격리하려면 그 선행 규칙을 만족시키는 동반 인자를
# 함께 준다(그래도 auth_registry 는 여전히 없다).


def test_event_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(event_store=_event_store(tmp_path))


def test_site_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(site_store=_site_store(tmp_path))


def test_mission_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(mission_store=_mission_store(tmp_path))


def test_edge_sync_store_with_event_store_but_no_auth_registry_raises(tmp_path: Path) -> None:
    """edge_sync_store 규칙(규칙 3)을 만족시켜 규칙 1(auth_registry)만 격리."""
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(
            edge_sync_store=_edge_sync_store(tmp_path),
            event_store=_event_store(tmp_path),
        )


def test_signing_key_with_stores_but_no_auth_registry_raises(tmp_path: Path) -> None:
    """서명키 규칙(규칙 2)을 만족시켜 규칙 1(auth_registry)만 격리."""
    with pytest.raises(ValueError, match="auth_registry"):
        create_app(
            mission_store=_mission_store(tmp_path),
            site_store=_site_store(tmp_path),
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="k",
        )


# ── 규칙 2: 서명키만(스토어 없이) → ValueError ────────────────────────────


def test_signing_key_alone_without_stores_raises(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(ValueError, match="mission_store.*site_store"):
        create_app(
            mission_signing_key=Ed25519PrivateKey.generate(),
            mission_signing_key_id="k",
        )


def test_signing_key_half_configured_raises(tmp_path: Path) -> None:
    """key 만 있고 key_id 가 없으면(또는 그 반대) 절반 서명 설정으로 조립하지 않는다."""
    del tmp_path
    with pytest.raises(ValueError, match="mission_signing_key"):
        create_app(mission_signing_key=Ed25519PrivateKey.generate())


# ── 규칙 3: edge_sync_store 만(event_store 없이) → ValueError ──────────────


def test_edge_sync_store_alone_without_event_store_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="event_store"):
        create_app(edge_sync_store=_edge_sync_store(tmp_path))


# ── 규칙 4: 전량 정상 조립 → 성공 ──────────────────────────────────────────


def test_full_assembly_succeeds(tmp_path: Path) -> None:
    app = create_app(
        auth_registry=_auth_registry(),
        edge_sync_store=_edge_sync_store(tmp_path),
        event_store=_event_store(tmp_path),
        site_store=_site_store(tmp_path),
        mission_store=_mission_store(tmp_path),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="assembly-test-key",
    )
    paths = set(app.openapi()["paths"])
    # 전량 조립이면 각 표면의 대표 경로가 전부 장착된다(조건부 라우터 누락 방지).
    assert {
        "/v1/sites",
        "/v1/events",
        "/v1/edge-sync/event-bundles",
        "/v1/missions/contracts",
        "/v1/missions/plans",
        "/v1/missions",
    } <= paths


# ── expose_docs 스위치 (재검토 P2 — "문서 라우트만 공개" 반증에 대한 조치) ──


_DOC_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def test_expose_docs_default_true_exposes_doc_routes() -> None:
    app = create_app(expose_docs=True)
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert route_paths >= _DOC_ROUTES


def test_expose_docs_false_removes_doc_routes() -> None:
    app = create_app(expose_docs=False)
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert not (_DOC_ROUTES & route_paths)


def test_authenticated_minimal_assembly_exposes_read_only_resource_policy() -> None:
    """Evidence storage가 없는 축소 조립도 전역 정책을 인증 후 조회할 수 있다.

    처리 작업 발급 라우트까지 함께 열어서는 안 된다. 이 구분이 Dashboard에서
    정책 미상과 실행 인프라 미조립을 서로 다른 상태로 보여주게 한다.
    """
    app = create_app(auth_registry=_auth_registry())
    paths = set(app.openapi()["paths"])
    assert "/v1/processing-resource-policies" in paths
    assert "/v1/missions/{mission_id}/processing-jobs" not in paths

    client = TestClient(app)
    assert client.get("/v1/processing-resource-policies").status_code == 401
    response = client.get(
        "/v1/processing-resource-policies",
        headers={"Authorization": "Bearer assembly-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["currentPolicyId"] == "ksi-civil-pilot-r1"


def test_documented_public_allowlist_matches_actual_unauthenticated_surface() -> None:
    """[서술↔실제] create_app docstring 이 세는 공개 라우트가 실제와 같아야 한다.

    서술이 실제보다 좁으면 "무엇이 인증 없이 열려 있나"를 문서로 감사할 수 없다 —
    /docs/oauth2-redirect 가 정확히 그렇게 빠져 있었다(s2-residual-hardening #5).
    """
    docstring = create_app.__doc__ or ""
    for path in _DOC_ROUTES:
        assert f"``{path}``" in docstring, f"{path} 가 공개 allowlist 서술에 없다"

    on = {getattr(route, "path", None) for route in create_app(expose_docs=True).routes}
    off = {getattr(route, "path", None) for route in create_app(expose_docs=False).routes}
    assert on - off == _DOC_ROUTES, "스위치가 켜고 끄는 라우트 집합이 서술과 다르다"


# ── 규칙 5: 결함 후보 저장소는 참조 대조 대상 없이 조립되지 않는다 ──────────
#
# 결함 후보는 "어느 임무의 어느 사진 위 픽셀 좌표인가"로만 의미를 갖는다. 대조할
# 저장소 없이 표면만 열면 서버가 검증할 수 없는 도형을 그대로 받아 적고, 그 오염은
# 조회 시점에 정상으로 보인다(defect_candidates.py "서버는 후보를 그대로 받아 적지
# 않는다").


def test_defect_candidate_store_without_mission_store_raises(tmp_path: Path) -> None:
    """mission_store 없이는 어떤 조합으로도 조립되지 않는다.

    메시지가 ``defect_candidate_store`` 규칙이 아니라 ``source_media_store`` 규칙에서
    나올 수 있다 — 그쪽도 mission_store 를 요구하고 검사 순서가 앞이다. 여기서
    검증하는 것은 "어느 규칙이 말했는가"가 아니라 **mission_store 없이 이 표면이
    열리는 조합이 존재하지 않는가**다.
    """
    missions = _mission_store(tmp_path)
    with pytest.raises(ValueError, match="mission_store"):
        create_app(
            auth_registry=_auth_registry(),
            source_media_store=SourceMediaStore(
                DurableJournal(tmp_path / "source-media.jsonl"), mission_store=missions
            ),
            defect_candidate_store=_defect_candidate_store(tmp_path / "dc", missions),
        )


def test_defect_candidate_store_without_source_media_store_raises(tmp_path: Path) -> None:
    missions = _mission_store(tmp_path)
    with pytest.raises(ValueError, match="defect_candidate_store"):
        create_app(
            auth_registry=_auth_registry(),
            mission_store=missions,
            defect_candidate_store=_defect_candidate_store(tmp_path / "dc", missions),
        )


def test_defect_candidate_store_alone_without_auth_registry_raises(tmp_path: Path) -> None:
    missions = _mission_store(tmp_path)
    with pytest.raises(ValueError, match="defect_candidate_store|auth_registry"):
        create_app(defect_candidate_store=_defect_candidate_store(tmp_path / "dc", missions))


# ── 규칙 6: 변화 탐지 저장소는 비교 대상을 대조할 작업 원장 없이 조립되지 않는다 ──


def _change_detection_store(tmp_path: Path, mission_store: MissionStore) -> ChangeDetectionStore:
    media = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    return ChangeDetectionStore(
        DurableJournal(tmp_path / "change-detection.jsonl"),
        mission_store=mission_store,
        processing_job_store=ProcessingJobStore(
            DurableJournal(tmp_path / "processing-jobs.jsonl"),
            source_media_store=media,
            site_store=_site_store(tmp_path),
        ),
    )


def test_change_detection_store_without_processing_job_store_raises(tmp_path: Path) -> None:
    """'변화가 있었다'는 두 point cloud 산출물을 지목하지 못하면 아무도 재현할 수
    없는 주장이다 — 그 참조를 대조할 작업 원장 없이 표면만 열지 않는다."""
    missions = _mission_store(tmp_path)
    with pytest.raises(ValueError, match="change_detection_store"):
        create_app(
            auth_registry=_auth_registry(),
            mission_store=missions,
            change_detection_store=_change_detection_store(tmp_path / "cd", missions),
        )


def test_change_detection_store_without_mission_store_raises(tmp_path: Path) -> None:
    missions = _mission_store(tmp_path)
    with pytest.raises(ValueError, match="mission_store"):
        create_app(
            auth_registry=_auth_registry(),
            change_detection_store=_change_detection_store(tmp_path / "cd", missions),
        )


# ── 규칙 7: 운동상태 저장소는 현장 등록 좌표계 없이 조립되지 않는다 ─────────


def test_equipment_state_store_without_site_store_raises(tmp_path: Path) -> None:
    """cpa_ttc 의 site_frame 검사는 두 상태끼리만 본다 — 둘 다 같은 잘못된 좌표계면
    통과한다. 현장 등록 좌표계와 대조할 저장소가 없으면 그 구멍을 막을 수 없다."""
    with pytest.raises(ValueError, match="equipment_state_store"):
        create_app(
            auth_registry=_auth_registry(),
            equipment_state_store=EquipmentStateStore(
                DurableJournal(tmp_path / "equipment-states.jsonl"),
                site_store=_site_store(tmp_path),
            ),
        )


# ── 규칙 8: 결합 규칙 표가 create_app 시그니처와 어긋나지 않는다 ────────────


def test_assembly_requirements_table_keys_match_create_app_store_parameters() -> None:
    """``_ASSEMBLY_REQUIREMENTS`` 표의 키 집합이 ``create_app`` 의 store 파라미터
    집합과 정확히 일치하는지 검사한다.

    새 store 를 ``create_app`` 에 추가하면서 결합 규칙(또는 "결합 없음") 등록을
    깜빡하는 사고를 구조적으로 막는다 — 시그니처에는 있는데 표에 없거나, 표에는
    있는데 시그니처에서 이름이 바뀌거나 사라지면 이 테스트가 즉시 잡는다.
    """
    signature_params = set(inspect.signature(create_app).parameters)
    # mission_signing_key·evidence_storage 는 "*_store" 로 끝나지 않지만
    # protected_surface 에 참여하는 보호 표면이다(app.py 결합 규칙 표 주석 참조).
    non_store_protected_params = {
        "mission_signing_key",
        "evidence_storage",
        "copilot_service",
        "copilot_conversation_service",
        "site_workspace_projector",
        "site_briefing_service",
        "civil_readiness_projector",
        "runtime_capability_projector",
        "external_use_evaluator",
        "external_volume_input_capability_issuer",
        "external_single_volume",
        "external_result_workflow_service",
        "external_result_read_projector",
    }
    expected = {name for name in signature_params if name.endswith("_store")} | (
        signature_params & non_store_protected_params
    )

    table_keys = {row[0] for row in app_module._ASSEMBLY_REQUIREMENTS}

    assert table_keys == expected
