"""장비 클래스 지원단계 등록·전이·조회 계약 — INV-041 **런타임** 강제 (MASTER_PRD §23.3/§26.7).

``assert_support_level_transition`` 은 정확하게 구현돼 있었지만 프로덕션 호출부가
0건이었다 — 설계된 게이트가 테스트 안에서만 존재했다(risk
capability-support-level-transition-unwired). ``is_production_supported`` 도 같았다.

이 파일이 확인하는 것은 셋이다.

**① 게이트가 실제로 막는가(음성 케이스).** green≠막혔다 — 승급이 되는 것만 보면
게이트가 없어도 통과한다. 단계 스킵·증거 없는 승급·등록으로 우회하는 경로가 전부
**거부되는지**가 이 파일의 중심이다.

**② 상용지원 표시가 파생값인가.** ``00_READ_FIRST.md`` 구현금지 "미검증 장비를
상용지원으로 표시" — PRODUCTION_SUPPORTED 바로 아래 단계(RISK_VALIDATED)가
supported 로 보이면 안 된다.

**③ 강등이 증거를 물려받지 않는가.** 강등된 상태가 승급 때의 증거를 달고 있으면
"이 단계는 검증됐다"는 잘못된 신호가 된다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Permission,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
    principal_permissions,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.equipment_support import (
    EquipmentSupportRecoveryError,
    EquipmentSupportStore,
    EquipmentSupportVerdict,
    mount_equipment_support,
)
from ksi_domain.capability import EquipmentSupportLevel

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "equipment-support-state.v1.json"

_ADMIN_TOKEN = "admin-token"  # noqa: S105 — 테스트 고정값
_OPERATOR_TOKEN = "field-operator-token"  # noqa: S105
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_CLASS_ID = "Excavator"
_NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)

# 승급 사다리 — 등록 직후(DATASET_AVAILABLE)부터 순서대로.
_LADDER = [
    EquipmentSupportLevel.BASELINE_DETECTION,
    EquipmentSupportLevel.FIELD_VALIDATED,
    EquipmentSupportLevel.GEO_VALIDATED,
    EquipmentSupportLevel.RISK_VALIDATED,
    EquipmentSupportLevel.PRODUCTION_SUPPORTED,
]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


@pytest.fixture
def store(tmp_path: Path) -> EquipmentSupportStore:
    return EquipmentSupportStore(DurableJournal(tmp_path / "equipment-support.jsonl"))


def _client(store: EquipmentSupportStore, *, token: str = _ADMIN_TOKEN) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_equipment_support(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _register(client: TestClient, class_id: str = _CLASS_ID) -> Any:
    return client.post(
        "/v1/equipment-support",
        json={"classId": class_id, "evidenceRefs": ["dataset://coco-excavator-v1"]},
    )


def _patch(
    client: TestClient,
    state: EquipmentSupportLevel,
    *,
    evidence: list[str] | None = None,
    class_id: str = _CLASS_ID,
) -> Any:
    body: dict[str, Any] = {"state": state.value}
    if evidence is not None:
        body["evidenceRefs"] = evidence
    return client.patch(f"/v1/equipment-support/{class_id}", json=body)


def _promote_to(client: TestClient, target: EquipmentSupportLevel) -> None:
    """사다리를 한 단계씩 올라 target 까지 — 우회 없이 실제 게이트를 통과한다."""
    if target not in _LADDER:
        # 사다리 밖(등록 직후 단계)을 넘기면 예전 구현은 끝까지 올라간 뒤 실패했다 —
        # 헬퍼가 의도와 다른 상태를 만들어 놓고 죽는 함정이라 진입 시점에 막는다.
        raise AssertionError(f"{target} 는 사다리에 없다 — 등록 직후 단계는 승급 대상이 아니다")
    for level in _LADDER:
        response = _patch(client, level, evidence=[f"report://{level.value.lower()}"])
        assert response.status_code == 200, response.json()
        if level is target:
            return


# ── 계약 스키마 정합 ────────────────────────────────────────────────────────


def test_response_satisfies_contract_schema(store: EquipmentSupportStore) -> None:
    """응답의 계약 필드가 equipment-support-state.v1.json 을 만족한다."""
    client = _client(store)
    _register(client)
    view = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    contract_subset = {
        "classId": view["classId"],
        "state": view["state"],
        "evidenceRefs": view["evidenceRefs"],
    }
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    assert not sorted(validator.iter_errors(contract_subset), key=lambda e: e.path)


def test_every_schema_state_is_reachable_through_the_ladder(
    store: EquipmentSupportStore,
) -> None:
    """스키마 enum 전건이 실제 전이로 도달 가능하다 — 한쪽만 늘어나는 drift 차단."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    schema_states = set(schema["properties"]["state"]["enum"])
    ladder_states = {EquipmentSupportLevel.DATASET_AVAILABLE.value} | {
        level.value for level in _LADDER
    }
    assert ladder_states == schema_states

    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["state"] == (
        EquipmentSupportLevel.PRODUCTION_SUPPORTED.value
    )


# ── ① 게이트가 실제로 막는다 (음성 케이스가 중심) ───────────────────────────


def test_registration_always_starts_at_the_lowest_level(store: EquipmentSupportStore) -> None:
    """등록으로 단계를 건너뛸 수 없다 — 요청에 state 를 실을 자리 자체가 없다."""
    client = _client(store)
    assert _register(client).status_code == 201
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["state"] == (
        EquipmentSupportLevel.DATASET_AVAILABLE.value
    )
    # 계약상 state 를 보내는 것 자체가 거부된다(extra="forbid").
    rejected = client.post(
        "/v1/equipment-support",
        json={"classId": "Crane", "state": "PRODUCTION_SUPPORTED", "evidenceRefs": ["x"]},
    )
    assert rejected.status_code == 422


def test_skipping_a_level_is_rejected(store: EquipmentSupportStore) -> None:
    """[핵심] DATASET_AVAILABLE → PRODUCTION_SUPPORTED 한 방 승급은 막힌다."""
    client = _client(store)
    _register(client)
    response = _patch(
        client, EquipmentSupportLevel.PRODUCTION_SUPPORTED, evidence=["report://everything"]
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == EquipmentSupportVerdict.ILLEGAL_TRANSITION.value
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["state"] == (
        EquipmentSupportLevel.DATASET_AVAILABLE.value
    )


@pytest.mark.parametrize("evidence", [None, [], [""], ["   "], ["  ", " "]])
def test_promotion_without_evidence_is_rejected(
    store: EquipmentSupportStore, evidence: list[str] | None
) -> None:
    """[핵심] 빈 배열도, 공백만인 문자열도 증거가 아니다."""
    client = _client(store)
    _register(client)
    response = _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=evidence)
    assert response.status_code == 422
    assert response.json()["verdict"] == EquipmentSupportVerdict.ILLEGAL_TRANSITION.value


def test_promotion_with_evidence_succeeds(store: EquipmentSupportStore) -> None:
    """게이트가 정상 경로를 막는 게 아니라는 확인 — 한 단계씩 + 증거면 통과한다."""
    client = _client(store)
    _register(client)
    response = _patch(
        client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://baseline-eval"]
    )
    assert response.status_code == 200, response.json()
    assert response.json()["record"]["state"] == EquipmentSupportLevel.BASELINE_DETECTION.value


def test_unknown_class_transition_is_404(store: EquipmentSupportStore) -> None:
    response = _patch(
        _client(store),
        EquipmentSupportLevel.BASELINE_DETECTION,
        evidence=["x"],
        class_id="NeverRegistered",
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == EquipmentSupportVerdict.UNKNOWN_CLASS.value


def test_duplicate_registration_is_conflict(store: EquipmentSupportStore) -> None:
    client = _client(store)
    assert _register(client).status_code == 201
    again = _register(client)
    assert again.status_code == 409
    assert again.json()["verdict"] == EquipmentSupportVerdict.ALREADY_REGISTERED.value


def test_reregistration_cannot_reset_a_promoted_class(store: EquipmentSupportStore) -> None:
    """재등록으로 원장을 초기화해 사다리를 다시 오르는 우회가 없다."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.FIELD_VALIDATED)
    assert _register(client).status_code == 409
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["state"] == (
        EquipmentSupportLevel.FIELD_VALIDATED.value
    )


# ── 권한: 사람 중 ADMIN 만 이 표면을 만진다 ─────────────────────────────────


def test_equipment_support_approve_is_admin_only() -> None:
    """권한표 SSOT 확인 — FIELD_OPERATOR·VIEWER 에게는 없다."""
    def _p(role: Role) -> Principal:
        return Principal(principal_id="x", kind=PrincipalKind.OPERATOR, role=role, device_id=None)

    assert Permission.EQUIPMENT_SUPPORT_APPROVE in principal_permissions(_p(Role.ADMIN))
    assert Permission.EQUIPMENT_SUPPORT_APPROVE not in principal_permissions(
        _p(Role.FIELD_OPERATOR)
    )
    assert Permission.EQUIPMENT_SUPPORT_APPROVE not in principal_permissions(_p(Role.VIEWER))


@pytest.mark.parametrize("token", [_OPERATOR_TOKEN, _VIEWER_TOKEN])
def test_non_admin_cannot_promote(store: EquipmentSupportStore, token: str) -> None:
    _register(_client(store))
    response = _patch(
        _client(store, token=token),
        EquipmentSupportLevel.BASELINE_DETECTION,
        evidence=["report://x"],
    )
    assert response.status_code == 403


@pytest.mark.parametrize("token", [_OPERATOR_TOKEN, _VIEWER_TOKEN])
def test_non_admin_cannot_register(store: EquipmentSupportStore, token: str) -> None:
    assert _register(_client(store, token=token)).status_code == 403


def test_viewer_can_read(store: EquipmentSupportStore) -> None:
    """표시는 모두가 본다 — 읽기까지 막으면 §26.7 "정직하게 표시"가 성립하지 않는다."""
    _register(_client(store))
    assert _client(store, token=_VIEWER_TOKEN).get("/v1/equipment-support").status_code == 200


# ── ② 상용지원 표시는 파생값이다 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "level",
    [
        EquipmentSupportLevel.BASELINE_DETECTION,
        EquipmentSupportLevel.FIELD_VALIDATED,
        EquipmentSupportLevel.GEO_VALIDATED,
        EquipmentSupportLevel.RISK_VALIDATED,
    ],
)
def test_below_production_is_never_shown_as_supported(
    store: EquipmentSupportStore, level: EquipmentSupportLevel
) -> None:
    """[핵심 — 00_READ_FIRST 구현금지] PRODUCTION_SUPPORTED 바로 아래
    (RISK_VALIDATED)도 supported 가 아니다."""
    client = _client(store)
    _register(client)
    _promote_to(client, level)
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["productionSupported"] is False
    listed = client.get("/v1/equipment-support").json()
    assert listed["productionSupportedCount"] == 0


def test_production_supported_is_shown_as_supported(store: EquipmentSupportStore) -> None:
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["productionSupported"] is True
    assert client.get("/v1/equipment-support").json()["productionSupportedCount"] == 1


def test_newly_registered_class_is_not_supported(store: EquipmentSupportStore) -> None:
    """데이터셋이 있다는 것만으로 완료 처리하지 않는다(MASTER_PRD §26.3)."""
    client = _client(store)
    _register(client)
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["productionSupported"] is False


# ── ③ 강등: 막지 않되, 증거를 물려받지 않는다 ───────────────────────────────


def test_demotion_is_allowed_without_evidence(store: EquipmentSupportStore) -> None:
    """현장 재검증 실패에 즉시 대응해야 하는 방향에 마찰을 넣지 않는다."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    response = _patch(client, EquipmentSupportLevel.FIELD_VALIDATED, evidence=[])
    assert response.status_code == 200, response.json()
    assert response.json()["record"]["state"] == EquipmentSupportLevel.FIELD_VALIDATED.value


def test_demotion_clears_the_promotion_evidence(store: EquipmentSupportStore) -> None:
    """[핵심] 강등된 상태가 승급 때의 증거를 달고 있으면 "이 단계는 검증됐다"는
    잘못된 신호가 된다."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["evidenceRefs"] != []
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=[])
    view = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    assert view["evidenceRefs"] == []
    assert view["productionSupported"] is False


def test_demotion_removes_supported_display_immediately(store: EquipmentSupportStore) -> None:
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    assert client.get("/v1/equipment-support").json()["productionSupportedCount"] == 1
    _patch(client, EquipmentSupportLevel.RISK_VALIDATED, evidence=[])
    assert client.get("/v1/equipment-support").json()["productionSupportedCount"] == 0


def test_repromotion_after_demotion_still_needs_the_full_ladder(
    store: EquipmentSupportStore,
) -> None:
    """강등 후 되돌아갈 때도 한 단계씩이다 — 강등이 승급의 지름길이 되지 않는다."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=[])
    skipped = _patch(
        client, EquipmentSupportLevel.PRODUCTION_SUPPORTED, evidence=["report://again"]
    )
    assert skipped.status_code == 422


# ── 감사: 시도와 거부가 원장에 남는다 ───────────────────────────────────────


def test_rejected_promotion_is_journaled(tmp_path: Path) -> None:
    """누가 무슨 승급을 시도해 막혔는지가 감사 입력이다 — 응답으로만 가고 소멸하지 않는다."""
    journal_path = tmp_path / "equipment-support.jsonl"
    journal = DurableJournal(journal_path)
    store = EquipmentSupportStore(journal)
    client = _client(store)
    _register(client)
    _patch(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED, evidence=["report://everything"])
    journal.close()

    kinds = [
        json.loads(line)["kind"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert kinds == ["equipment-support-registered", "equipment-support-rejected"]


def test_transitions_history_records_actor_and_evidence(store: EquipmentSupportStore) -> None:
    client = _client(store)
    _register(client)
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://baseline"])
    history = store.transitions(_CLASS_ID)
    assert [t.to_state for t in history] == [
        EquipmentSupportLevel.DATASET_AVAILABLE,
        EquipmentSupportLevel.BASELINE_DETECTION,
    ]
    assert history[-1].from_state is EquipmentSupportLevel.DATASET_AVAILABLE
    assert history[-1].evidence_refs == ("report://baseline",)
    assert history[-1].actor == "admin-1"


# ── 재생도 같은 게이트를 탄다 ───────────────────────────────────────────────


def test_replay_restores_state(tmp_path: Path) -> None:
    journal_path = tmp_path / "equipment-support.jsonl"
    journal = DurableJournal(journal_path)
    client = _client(EquipmentSupportStore(journal))
    _register(client)
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://baseline"])
    journal.close()

    reborn = DurableJournal(journal_path)
    try:
        record = EquipmentSupportStore(reborn).get(_CLASS_ID)
    finally:
        reborn.close()
    assert record is not None
    assert record.state is EquipmentSupportLevel.BASELINE_DETECTION
    assert record.production_supported is False


def test_replay_refuses_a_skipped_promotion_in_the_journal(tmp_path: Path) -> None:
    """[핵심] journal 을 손으로 고쳐 단계 스킵 승급을 되살릴 수 없다 — 재생이 live
    보다 느슨하면 원장 조작이 게이트 우회 경로가 된다."""
    journal_path = tmp_path / "equipment-support.jsonl"
    journal_path.write_text(
        "\n".join(
            json.dumps(rec)
            for rec in (
                {
                    "kind": "equipment-support-registered",
                    "ts": _NOW.isoformat(),
                    "classId": _CLASS_ID,
                    "state": "DATASET_AVAILABLE",
                    "evidenceRefs": ["dataset://x"],
                    "modelVersion": None,
                    "riskPackVersion": None,
                    "actor": "admin-1",
                },
                {
                    "kind": "equipment-support-transitioned",
                    "ts": _NOW.isoformat(),
                    "classId": _CLASS_ID,
                    "state": "PRODUCTION_SUPPORTED",
                    "evidenceRefs": ["report://forged"],
                    "modelVersion": None,
                    "riskPackVersion": None,
                    "actor": "admin-1",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    journal = DurableJournal(journal_path)
    with pytest.raises(EquipmentSupportRecoveryError, match="스킵"):
        EquipmentSupportStore(journal)


def test_replay_refuses_registration_above_the_lowest_level(tmp_path: Path) -> None:
    """등록 레코드를 고쳐 PRODUCTION_SUPPORTED 로 시작하는 우회도 막는다."""
    journal_path = tmp_path / "equipment-support.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "equipment-support-registered",
                "ts": _NOW.isoformat(),
                "classId": _CLASS_ID,
                "state": "PRODUCTION_SUPPORTED",
                "evidenceRefs": ["report://forged"],
                "modelVersion": None,
                "riskPackVersion": None,
                "actor": "admin-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    journal = DurableJournal(journal_path)
    with pytest.raises(EquipmentSupportRecoveryError, match="DATASET_AVAILABLE"):
        EquipmentSupportStore(journal)


# ── reviewer 지적 후속 (2026-08-08) ─────────────────────────────────────────


def test_same_level_restatement_requires_evidence(store: EquipmentSupportStore) -> None:
    """[F2 회귀] 동일 단계 PATCH 는 강등이 아니라 "이 단계가 여전히 유효하다"는
    주장이다. 증거 없이 통과시키면 productionSupported=true 인데 evidenceRefs=[] 인
    레코드가 만들어진다 — 상용지원 표시의 근거가 게이트 없이 지워진다."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED)
    before = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    assert before["evidenceRefs"] != []

    blocked = _patch(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED, evidence=[])
    assert blocked.status_code == 422
    assert blocked.json()["verdict"] == EquipmentSupportVerdict.ILLEGAL_TRANSITION.value

    after = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    assert after["evidenceRefs"] == before["evidenceRefs"]
    assert after["productionSupported"] is True


def test_same_level_restatement_with_evidence_succeeds(store: EquipmentSupportStore) -> None:
    """재선언 자체를 막는 게 아니다 — 새 증거를 제시하면 갱신된다(재검증 기록)."""
    client = _client(store)
    _register(client)
    _promote_to(client, EquipmentSupportLevel.BASELINE_DETECTION)
    response = _patch(
        client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://revalidated-2026Q3"]
    )
    assert response.status_code == 200, response.json()
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["evidenceRefs"] == [
        "report://revalidated-2026Q3"
    ]


@pytest.mark.parametrize(
    ("char", "name"),
    [
        ("\u200b", "U+200B ZERO WIDTH SPACE"),
        ("\ufeff", "U+FEFF BOM"),
        ("\u200c", "U+200C ZWNJ"),
        ("\u200d", "U+200D ZWJ"),
        ("\u00a0", "U+00A0 NBSP"),
        ("\u3000", "U+3000 IDEOGRAPHIC SPACE"),
        ("\u2028", "U+2028 LINE SEPARATOR"),
    ],
)
def test_invisible_characters_are_not_evidence(
    store: EquipmentSupportStore, char: str, name: str
) -> None:
    """[F3 회귀] strip() 만으로는 U+200B·U+FEFF 가 걸러지지 않는다(isspace()=False)
    — 화면에는 빈 문자열로 보이는데 "증거 있음"으로 승급이 통과했다(실측 재현)."""
    client = _client(store)
    _register(client)
    response = _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=[char])
    assert response.status_code == 422, f"{name} 가 증거로 통과했다"
    assert response.json()["verdict"] == EquipmentSupportVerdict.ILLEGAL_TRANSITION.value


def test_model_version_survives_the_full_ladder(store: EquipmentSupportStore) -> None:
    """[F4 회귀] PATCH 는 부분 갱신이다 — 요청이 버전을 말하지 않으면 이어받는다.

    예전엔 무조건 덮어써서, 정상 경로로 사다리를 올라간 PRODUCTION_SUPPORTED
    레코드가 modelVersion=null 이었다 — 상용지원 선언을 뒷받침할 모델 버전이 정상
    경로로 비워지는 자리였다.
    """
    client = _client(store)
    _register(client)
    first = client.patch(
        f"/v1/equipment-support/{_CLASS_ID}",
        json={
            "state": EquipmentSupportLevel.BASELINE_DETECTION.value,
            "evidenceRefs": ["report://baseline"],
            "modelVersion": "ksi-excavator-1.4.0",
            "riskPackVersion": "risk-pack-2026Q3",
        },
    )
    assert first.status_code == 200, first.json()
    for level in _LADDER[1:]:
        assert _patch(client, level, evidence=[f"report://{level.value}"]).status_code == 200
    view = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    assert view["state"] == EquipmentSupportLevel.PRODUCTION_SUPPORTED.value
    assert view["modelVersion"] == "ksi-excavator-1.4.0"
    assert view["riskPackVersion"] == "risk-pack-2026Q3"


def test_replay_skips_rejected_records_without_dying(tmp_path: Path) -> None:
    """[F5 회귀] 거부가 한 번이라도 있었던 서버가 재기동 가능해야 한다 —
    equipment-support-rejected 레코드는 state 키가 없어 skip 하지 않으면 KeyError 다."""
    journal_path = tmp_path / "equipment-support.jsonl"
    journal = DurableJournal(journal_path)
    client = _client(EquipmentSupportStore(journal))
    _register(client)
    _patch(client, EquipmentSupportLevel.PRODUCTION_SUPPORTED, evidence=["report://skip-attempt"])
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://baseline"])
    journal.close()

    reborn = DurableJournal(journal_path)
    try:
        record = EquipmentSupportStore(reborn).get(_CLASS_ID)
    finally:
        reborn.close()
    assert record is not None
    assert record.state is EquipmentSupportLevel.BASELINE_DETECTION


def test_store_without_auth_registry_is_refused_at_assembly(tmp_path: Path) -> None:
    """[F6 회귀] 인증 없는 보호 표면은 존재할 수 없다(ADR-KSI-008 §3)."""
    from ksi_core.app import create_app

    with pytest.raises(ValueError, match="auth_registry"):
        create_app(
            equipment_support_store=EquipmentSupportStore(
                DurableJournal(tmp_path / "es.jsonl")
            )
        )


def test_unauthenticated_read_is_401(store: EquipmentSupportStore) -> None:
    """[F6 회귀] 토큰 없이는 읽기도 안 된다 — 403 만 검증하면 401 경로가 빈다."""
    app = FastAPI()
    mount_auth(app, _registry())
    mount_equipment_support(app, store)
    assert TestClient(app).get("/v1/equipment-support").status_code == 401


# ── reviewer 재검증 후속 (N2·N3) ────────────────────────────────────────────


def test_invisible_ref_beside_a_real_one_is_not_stored(store: EquipmentSupportStore) -> None:
    """[N2㉡ 회귀] 항목 필터가 strip() 이면 보이지 않는 항목이 실제 증거 옆에 붙어
    그대로 원장에 저장된다 — 전체 판정은 두 번째 항목으로 통과하므로 아무도 못 본다."""
    client = _client(store)
    _register(client)
    response = _patch(
        client,
        EquipmentSupportLevel.BASELINE_DETECTION,
        evidence=["\u200b", "report://baseline", "   "],
    )
    assert response.status_code == 200, response.json()
    assert client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["evidenceRefs"] == [
        "report://baseline"
    ]


def test_demotion_clears_model_version_too(store: EquipmentSupportStore) -> None:
    """[N3㉡ 정책] 강등은 evidenceRefs 와 같은 이유로 버전 메타데이터도 물려받지 않는다.

    "PRODUCTION_SUPPORTED 를 이 모델로 세웠다"는 사실은 그 단계에서 내려온 뒤에는
    더 이상 이 레코드의 근거가 아니다 — 모델 회귀로 강등하는 경우가 특히 그렇다.
    """
    client = _client(store)
    _register(client)
    assert (
        client.patch(
            f"/v1/equipment-support/{_CLASS_ID}",
            json={
                "state": EquipmentSupportLevel.BASELINE_DETECTION.value,
                "evidenceRefs": ["report://baseline"],
                "modelVersion": "ksi-excavator-1.4.0",
                "riskPackVersion": "risk-pack-2026Q3",
            },
        ).status_code
        == 200
    )
    _patch(client, EquipmentSupportLevel.DATASET_AVAILABLE, evidence=[])
    view = client.get(f"/v1/equipment-support/{_CLASS_ID}").json()
    assert view["state"] == EquipmentSupportLevel.DATASET_AVAILABLE.value
    assert view["modelVersion"] is None
    assert view["riskPackVersion"] is None


def test_restatement_carries_versions_forward(store: EquipmentSupportStore) -> None:
    """강등이 아닌 방향(재선언)에서는 이어받는다 — 부분 갱신 의미론."""
    client = _client(store)
    _register(client)
    client.patch(
        f"/v1/equipment-support/{_CLASS_ID}",
        json={
            "state": EquipmentSupportLevel.BASELINE_DETECTION.value,
            "evidenceRefs": ["report://baseline"],
            "modelVersion": "ksi-excavator-1.4.0",
        },
    )
    _patch(client, EquipmentSupportLevel.BASELINE_DETECTION, evidence=["report://revalidated"])
    assert (
        client.get(f"/v1/equipment-support/{_CLASS_ID}").json()["modelVersion"]
        == "ksi-excavator-1.4.0"
    )
