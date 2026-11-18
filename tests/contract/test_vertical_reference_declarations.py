"""수직 기준 선언 원장 — 주장을 관측과 섞지 않고, 멱등·범위 격리·재생을 지킨다.

합성 값만 쓴다. 이 시험은 저장소·API 경계의 증거이지 측량 정확도의 증거가 아니다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.domains.external.ingress.vertical_reference_declarations import (
    AssetFacts,
    DeclarationVerdict,
    VerticalReferenceDeclarationRecoveryError,
    VerticalReferenceDeclarationStore,
    mount_vertical_reference_declarations,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import VerticalDatum
from ksi_event_contracts.vertical_reference_declaration import (
    MAX_DECLARATIONS_PER_ASSET,
    DeclareVerticalReferenceV1,
    VerticalReferenceDeclarationV1,
    WithdrawVerticalReferenceV1,
)

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
ORG, OTHER_ORG = "org-1", "org-2"
SITE, AREA = "site-1", "area-1"
ASSET = "ksa-v1-" + "a" * 64
OTHER_ASSET = "ksa-v1-" + "b" * 64


def facts(**overrides: Any) -> AssetFacts:
    values: dict[str, Any] = {
        "site_id": SITE,
        "work_area_id": AREA,
        "asset_ref": ASSET,
        "kind": ProcessingArtifactKind.DSM,
        "measured": True,
        "observed_vertical_reference": False,
    }
    values.update(overrides)
    return AssetFacts(**values)


def declare_body(
    datum: VerticalDatum = VerticalDatum.ORTHOMETRIC_KNGEOID2018,
    basis: str = "Terra에서 정표고(KNGeoid18)로 내보냄",
    expected: int = 0,
) -> DeclareVerticalReferenceV1:
    return DeclareVerticalReferenceV1(datum=datum, basis=basis, expected_sequence=expected)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.coordinator = ExternalAuthorityCurrentnessCoordinator()
        self.store = self._open()

    def _open(self) -> VerticalReferenceDeclarationStore:
        return VerticalReferenceDeclarationStore(
            DurableJournal(self.tmp / "declarations.jsonl"), coordinator=self.coordinator
        )

    def reopen(self) -> VerticalReferenceDeclarationStore:
        self.store._journal.close()  # noqa: SLF001 - 재시작처럼 같은 원장을 다시 연다
        self.store = self._open()
        return self.store

    def declare(
        self,
        *,
        org: str = ORG,
        principal: str = "alice",
        key: str = "k1",
        asset: AssetFacts | None = None,
        body: DeclareVerticalReferenceV1 | None = None,
    ) -> Any:
        return self.store.declare(
            organization_id=org,
            principal_id=principal,
            facts=facts() if asset is None else asset,
            body=body or declare_body(),
            idempotency_key=key,
            now=NOW,
        )

    def withdraw(
        self,
        *,
        expected: int,
        org: str = ORG,
        principal: str = "alice",
        key: str = "w1",
        asset: AssetFacts | None = None,
    ) -> Any:
        return self.store.withdraw(
            organization_id=org,
            principal_id=principal,
            facts=facts() if asset is None else asset,
            body=WithdrawVerticalReferenceV1(expected_sequence=expected),
            idempotency_key=key,
            now=NOW,
        )

    def current(self, *, org: str = ORG, asset: str = ASSET) -> Any:
        return self.store.current(organization_id=org, site_id=SITE, asset_ref=asset)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_declare_seals_an_active_record_bound_to_the_asset(world: World) -> None:
    result = world.declare()
    assert result.verdict is DeclarationVerdict.DECLARED
    record = result.declaration
    assert record is not None and record.sequence == 1 and record.status == "ACTIVE"
    assert record.declaration_digest == record.canonical_digest()
    assert record.declaration_id.startswith("vrd-") and len(record.declaration_id) == 36
    assert (record.site_id, record.work_area_id, record.asset_ref) == (SITE, AREA, ASSET)
    assert record.datum is VerticalDatum.ORTHOMETRIC_KNGEOID2018
    assert record.unit == "metre" and record.declared_by == "alice"
    assert world.current() == record


def test_a_file_that_carries_its_own_vertical_reference_takes_no_declaration(world: World) -> None:
    result = world.declare(asset=facts(observed_vertical_reference=True))
    assert result.verdict is DeclarationVerdict.OBSERVED_REFERENCE_PRESENT
    assert world.current() is None
    assert world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET) == ()


def test_only_measured_dsm_assets_can_be_declared(world: World) -> None:
    assert world.declare(asset=facts(kind=ProcessingArtifactKind.ORTHO)).verdict is (
        DeclarationVerdict.NOT_A_DSM
    )
    assert world.declare(asset=facts(measured=False)).verdict is DeclarationVerdict.NOT_MEASURED
    assert world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET) == ()


def test_an_unknown_asset_is_refused_without_a_record(world: World) -> None:
    result = world.store.declare(
        organization_id=ORG,
        principal_id="alice",
        facts=None,
        body=declare_body(),
        idempotency_key="k",
        now=NOW,
    )
    assert result.verdict is DeclarationVerdict.UNKNOWN_ASSET


def test_the_same_key_and_body_returns_the_original_and_writes_nothing_new(world: World) -> None:
    first = world.declare()
    again = world.declare()
    assert again.verdict is DeclarationVerdict.REPLAYED
    assert again.declaration == first.declaration
    assert len(world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET)) == 1


def test_the_same_key_with_another_body_conflicts(world: World) -> None:
    world.declare()
    other = declare_body(datum=VerticalDatum.ELLIPSOIDAL)
    assert world.declare(body=other).verdict is DeclarationVerdict.IDEMPOTENCY_CONFLICT
    assert world.declare(body=declare_body(basis="다른 근거")).verdict is (
        DeclarationVerdict.IDEMPOTENCY_CONFLICT
    )


def test_a_declare_key_cannot_be_reused_for_a_withdrawal(world: World) -> None:
    world.declare(key="same")
    assert world.withdraw(expected=1, key="same").verdict is DeclarationVerdict.IDEMPOTENCY_CONFLICT


def test_another_principal_may_reuse_a_key_independently(world: World) -> None:
    mine = world.declare()
    theirs = world.declare(principal="bob", body=declare_body(expected=1))
    assert mine.verdict is DeclarationVerdict.DECLARED
    assert theirs.verdict is DeclarationVerdict.DECLARED
    assert theirs.declaration is not None and theirs.declaration.sequence == 2


def test_a_correction_is_a_new_record_and_the_old_one_stays_readable(world: World) -> None:
    first = world.declare().declaration
    second = world.declare(
        key="k2",
        body=declare_body(datum=VerticalDatum.ELLIPSOIDAL, basis="RTK 타원체고", expected=1),
    )
    assert second.verdict is DeclarationVerdict.DECLARED
    assert second.declaration is not None and second.declaration.sequence == 2
    history = world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET)
    assert [item.sequence for item in history] == [1, 2]
    assert history[0] == first
    current = world.current()
    assert current is not None and current.datum is VerticalDatum.ELLIPSOIDAL


def test_a_stale_declaration_conflicts_instead_of_overwriting(world: World) -> None:
    world.declare()
    stale = world.declare(
        principal="bob", key="k9", body=declare_body(basis="다른 사람", expected=0)
    )
    assert stale.verdict is DeclarationVerdict.SEQUENCE_CONFLICT
    current = world.current()
    assert current is not None and current.declared_by == "alice"


def test_a_withdrawal_ends_the_declaration_and_is_itself_a_record(world: World) -> None:
    world.declare()
    result = world.withdraw(expected=1)
    assert result.verdict is DeclarationVerdict.WITHDRAWN
    assert result.declaration is not None
    assert result.declaration.status == "WITHDRAWN" and result.declaration.sequence == 2
    assert result.declaration.datum is None and result.declaration.basis is None
    assert world.current() is None
    history = world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET)
    assert [item.status for item in history] == ["ACTIVE", "WITHDRAWN"]


def test_there_is_nothing_to_withdraw_without_an_active_declaration(world: World) -> None:
    # 선언이 한 번도 없으면 1번 기록을 봤다는 주장부터 틀렸다.
    assert world.withdraw(expected=1).verdict is DeclarationVerdict.SEQUENCE_CONFLICT
    world.declare()
    world.withdraw(expected=1)
    assert world.withdraw(expected=2, key="w2").verdict is DeclarationVerdict.NOTHING_TO_WITHDRAW


def test_a_withdrawal_names_the_sequence_it_saw(world: World) -> None:
    world.declare()
    assert world.withdraw(expected=5).verdict is DeclarationVerdict.SEQUENCE_CONFLICT
    assert world.current() is not None


def test_a_declaration_can_follow_a_withdrawal(world: World) -> None:
    world.declare()
    world.withdraw(expected=1)
    again = world.declare(key="k3", body=declare_body(expected=2))
    assert again.verdict is DeclarationVerdict.DECLARED
    assert again.declaration is not None and again.declaration.sequence == 3
    assert world.current() == again.declaration


def test_the_declaration_in_force_at_a_past_instant_is_answered_from_the_ledger(
    world: World,
) -> None:
    from datetime import timedelta

    later = NOW + timedelta(hours=1)
    world.declare()  # NOW 에 선언
    world.store.withdraw(
        organization_id=ORG,
        principal_id="alice",
        facts=facts(),
        body=WithdrawVerticalReferenceV1(expected_sequence=1),
        idempotency_key="w-later",
        now=later,
    )

    def active(at: datetime | None) -> Any:
        return world.store.active_declaration(
            organization_id=ORG, site_id=SITE, asset_ref=ASSET, at=at
        )

    assert active(NOW - timedelta(seconds=1)) is None  # 선언 전
    assert active(NOW) is not None  # 선언 시각
    assert active(later - timedelta(seconds=1)) is not None  # 철회 직전
    assert active(later) is None  # 철회 시각
    assert active(None) is None  # 지금은 철회됨
    assert (
        world.store.active_declaration(
            organization_id=OTHER_ORG, site_id=SITE, asset_ref=ASSET, at=NOW
        )
        is None
    )


def test_the_ledger_is_bounded_but_the_last_slot_always_withdraws(world: World) -> None:
    usable = MAX_DECLARATIONS_PER_ASSET - 1  # 마지막 한 칸은 철회 전용
    for number in range(usable):
        result = world.declare(
            key=f"k{number}", body=declare_body(basis=f"근거 {number}", expected=number)
        )
        assert result.verdict is DeclarationVerdict.DECLARED
    over = world.declare(key="over", body=declare_body(expected=usable))
    assert over.verdict is DeclarationVerdict.TOO_MANY_DECLARATIONS
    assert world.current() is not None
    # 상한 직전의 활성 선언도 철회할 수 있다 — 틀린 선언이 영구히 숫자를 열어 두지 않는다.
    closed = world.withdraw(key="close", expected=usable)
    assert closed.verdict is DeclarationVerdict.WITHDRAWN
    assert world.current() is None
    assert len(world.store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET)) == (
        MAX_DECLARATIONS_PER_ASSET
    )
    # 이제 더 쓸 수 없다: 새 선언도, 철회할 것도 없다.
    again = world.declare(key="again", body=declare_body(expected=MAX_DECLARATIONS_PER_ASSET))
    assert again.verdict is DeclarationVerdict.TOO_MANY_DECLARATIONS
    nothing = world.withdraw(key="nothing", expected=MAX_DECLARATIONS_PER_ASSET)
    assert nothing.verdict is DeclarationVerdict.NOTHING_TO_WITHDRAW


def test_another_organization_or_asset_sees_nothing(world: World) -> None:
    world.declare()
    assert world.current(org=OTHER_ORG) is None
    assert world.current(asset=OTHER_ASSET) is None
    assert world.store.history(organization_id=OTHER_ORG, site_id=SITE, asset_ref=ASSET) == ()
    assert world.store.history(organization_id=ORG, site_id="site-2", asset_ref=ASSET) == ()
    # 다른 조직의 같은 자료 참조는 독립된 원장이다.
    foreign = world.declare(org=OTHER_ORG, principal="eve")
    assert foreign.verdict is DeclarationVerdict.DECLARED
    assert foreign.declaration is not None and foreign.declaration.sequence == 1
    assert foreign.declaration.declaration_id != world.current().declaration_id


def test_a_bad_idempotency_key_is_invalid(world: World) -> None:
    for key in ("", "   ", "a\nb", "x" * 256):
        assert world.declare(key=key).verdict is DeclarationVerdict.INVALID


def test_restart_replays_records_and_keeps_idempotency(world: World) -> None:
    world.declare()
    world.withdraw(expected=1)
    store = world.reopen()
    assert store.current(organization_id=ORG, site_id=SITE, asset_ref=ASSET) is None
    assert len(store.history(organization_id=ORG, site_id=SITE, asset_ref=ASSET)) == 2
    assert world.declare().verdict is DeclarationVerdict.REPLAYED
    assert world.withdraw(expected=1).verdict is DeclarationVerdict.REPLAYED
    assert world.declare(body=declare_body(basis="다른 근거")).verdict is (
        DeclarationVerdict.IDEMPOTENCY_CONFLICT
    )


def test_the_raw_idempotency_key_is_never_written(world: World) -> None:
    world.declare(key="secret-client-key-12345")
    text = (world.tmp / "declarations.jsonl").read_text(encoding="utf-8")
    assert "secret-client-key-12345" not in text


def _records(world: World) -> list[dict[str, Any]]:
    path = world.tmp / "declarations.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rewrite(world: World, records: list[dict[str, Any]]) -> None:
    world.store._journal.close()  # noqa: SLF001
    (world.tmp / "declarations.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def test_replay_refuses_a_record_edited_in_place(world: World) -> None:
    world.declare()
    records = _records(world)
    records[0]["declaration"]["basis"] = "고쳐 쓴 근거"
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_an_unsealed_or_wrongly_sealed_record(world: World) -> None:
    world.declare()
    records = _records(world)
    records[0]["declaration"]["declarationDigest"] = None
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="서명"):
        world._open()  # noqa: SLF001
    records[0]["declaration"]["declarationDigest"] = "sha256:" + "0" * 64
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_skipped_sequence(world: World) -> None:
    world.declare()
    world.withdraw(expected=1)
    _rewrite(world, _records(world)[1:])
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="이어지지"):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_withdrawal_with_nothing_active(world: World) -> None:
    world.declare()
    world.withdraw(expected=1)
    records = _records(world)
    # 선언을 지우고 철회만 sequence 1 로 다시 쓴 원장은 이어붙일 수 없다.
    withdrawal = records[1]
    withdrawal["declaration"]["sequence"] = 1
    withdrawal["declaration"]["declarationId"] = records[0]["declaration"]["declarationId"]
    withdrawal["declaration"]["declarationDigest"] = None
    _rewrite(world, [withdrawal])
    with pytest.raises(VerticalReferenceDeclarationRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_an_actor_that_differs_from_the_declarant(world: World) -> None:
    world.declare()
    records = _records(world)
    records[0]["actor"] = "mallory"
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="선언자"):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_record_moved_to_another_organization(world: World) -> None:
    world.declare()
    world.declare(key="k2", body=declare_body(basis="두 번째", expected=1))
    records = _records(world)
    records[1]["organizationId"] = OTHER_ORG
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_an_unknown_kind_and_a_foreign_declaration_id(world: World) -> None:
    world.declare()
    records = _records(world)
    records[0]["kind"] = "something-else"
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="알 수 없는 kind"):
        world._open()  # noqa: SLF001
    records[0]["kind"] = "vertical-reference-declaration"
    other = dict(records[0]["declaration"], declarationId="vrd-" + "9" * 32, declarationDigest=None)
    records[0]["declaration"] = other
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError):
        world._open()  # noqa: SLF001


def _resealed(declaration: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """서명이 맞는 기록으로 다시 만든다 — 내용 변조가 아니라 원장 규칙 위반만 시험하려는 것이다."""
    fixed = {**declaration, **changes, "declarationDigest": None}
    sealed = VerticalReferenceDeclarationV1.model_validate(fixed).sealed()
    return sealed.model_dump(by_alias=True, mode="json")


def test_replay_refuses_a_validly_sealed_record_for_another_work_area(world: World) -> None:
    world.declare()
    world.declare(key="k2", body=declare_body(basis="두 번째", expected=1))
    records = _records(world)
    records[1]["declaration"] = _resealed(records[1]["declaration"], workAreaId="area-9")
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="작업구역"):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_validly_sealed_record_with_a_foreign_identifier(world: World) -> None:
    world.declare()
    records = _records(world)
    records[0]["declaration"] = _resealed(
        records[0]["declaration"], declarationId="vrd-" + "9" * 32
    )
    _rewrite(world, records)
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="식별자"):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_validly_sealed_withdrawal_that_has_nothing_to_end(world: World) -> None:
    world.declare()
    world.withdraw(expected=1)
    records = _records(world)
    # 철회를 두 번 잇는다: 두 번째 철회는 끝낼 활성 선언이 없다.
    second = json.loads(json.dumps(records[1]))
    identifier = VerticalReferenceDeclarationStore._declaration_id(ORG, SITE, ASSET, 3)  # noqa: SLF001
    second["declaration"] = _resealed(
        records[1]["declaration"], sequence=3, declarationId=identifier
    )
    second["keyHash"] = "sha256:" + "1" * 64
    _rewrite(world, [*records, second])
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="활성 선언"):
        world._open()  # noqa: SLF001
    # 선언 없이 첫 기록이 철회인 원장도 같다.
    first = json.loads(json.dumps(records[1]))
    first["declaration"] = _resealed(
        records[1]["declaration"],
        sequence=1,
        declarationId=VerticalReferenceDeclarationStore._declaration_id(ORG, SITE, ASSET, 1),  # noqa: SLF001
    )
    _rewrite(world, [first])
    with pytest.raises(VerticalReferenceDeclarationRecoveryError, match="활성 선언"):
        world._open()  # noqa: SLF001


# ── HTTP ─────────────────────────────────────────────────────────────────
TOKENS = {
    "admin": ("tok-admin", ORG, Role.ADMIN),
    "viewer": ("tok-viewer", ORG, Role.VIEWER),
    "foreign": ("tok-foreign", OTHER_ORG, Role.ADMIN),
}


class FakeAssets:
    """카탈로그 대신 자료 사실을 돌려주는 포트. 조직·현장·구역이 다르면 404 로 숨긴다."""

    def __init__(self) -> None:
        self.current = facts()

    def facts(
        self, *, principal: Principal, site_id: str, work_area_id: str, asset_ref: str
    ) -> AssetFacts | None:
        if principal.organization_id != ORG or (site_id, work_area_id, asset_ref) != (
            SITE,
            AREA,
            ASSET,
        ):
            raise HTTPException(status_code=404, detail="자료를 찾을 수 없다")
        return self.current


def _client(world: World, assets: FakeAssets) -> TestClient:
    def record(name: str) -> PrincipalTokenRecord:
        token, org, role = TOKENS[name]
        return PrincipalTokenRecord(
            token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            principal=Principal(
                principal_id=f"{org}-{name}",
                kind=PrincipalKind.OPERATOR,
                role=role,
                device_id=None,
                organization_id=org,
            ),
        )

    app = FastAPI()
    mount_auth(app, AuthRegistry([record(name) for name in TOKENS]))
    mount_vertical_reference_declarations(app, world.store, assets, clock=lambda: NOW)
    return TestClient(app)


def _h(name: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {TOKENS[name][0]}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


BASE = f"/v1/sites/{SITE}/work-areas/{AREA}/spatial-assets/{ASSET}/vertical-reference"
BODY = {
    "datum": "orthometric_kngeoid2018",
    "unit": "metre",
    "basis": "Terra에서 정표고(KNGeoid18)로 내보냄",
    "expectedSequence": 0,
}


def test_http_declare_read_withdraw_round_trip(world: World) -> None:
    client = _client(world, FakeAssets())
    empty = client.get(BASE, headers=_h("viewer"))
    assert empty.status_code == 200
    assert empty.json() == {"assetRef": ASSET, "observed": False, "current": None, "history": []}

    created = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k1"))
    assert created.status_code == 201
    assert created.json()["verdict"] == "DECLARED"
    declaration = created.json()["declaration"]
    assert declaration["status"] == "ACTIVE" and declaration["unit"] == "metre"
    assert declaration["declaredBy"] == f"{ORG}-admin"

    # 읽기는 조회 권한만으로 된다.
    seen = client.get(BASE, headers=_h("viewer")).json()
    assert seen["current"] == declaration and seen["observed"] is False

    replay = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k1"))
    assert replay.status_code == 200 and replay.json()["verdict"] == "REPLAYED"

    withdrawn = client.post(
        BASE + "/withdrawals", json={"expectedSequence": 1}, headers=_h("admin", "w1")
    )
    assert withdrawn.status_code == 201 and withdrawn.json()["verdict"] == "WITHDRAWN"
    after = client.get(BASE, headers=_h("viewer")).json()
    assert after["current"] is None and len(after["history"]) == 2


def test_http_writes_need_the_registration_permission_and_a_key(world: World) -> None:
    client = _client(world, FakeAssets())
    assert (
        client.post(BASE + "/declarations", json=BODY, headers=_h("viewer", "k")).status_code == 403
    )
    assert client.post(BASE + "/declarations", json=BODY, headers={}).status_code in {401, 403}
    assert client.post(BASE + "/declarations", json=BODY, headers=_h("admin")).status_code == 422
    assert (
        client.post(
            BASE + "/withdrawals", json={"expectedSequence": 1}, headers=_h("viewer", "k")
        ).status_code
        == 403
    )
    assert world.current() is None


def test_http_hides_other_organizations_and_unknown_assets(world: World) -> None:
    client = _client(world, FakeAssets())
    assert client.get(BASE, headers=_h("foreign")).status_code == 404
    assert (
        client.post(BASE + "/declarations", json=BODY, headers=_h("foreign", "k")).status_code
        == 404
    )
    other = BASE.replace(ASSET, OTHER_ASSET)
    assert client.get(other, headers=_h("admin")).status_code == 404
    assert (
        client.post(other + "/declarations", json=BODY, headers=_h("admin", "k")).status_code == 404
    )
    assert world.store.history(organization_id=ORG, site_id=SITE, asset_ref=OTHER_ASSET) == ()


def test_http_refusals_are_typed_and_leak_nothing(world: World) -> None:
    assets = FakeAssets()
    client = _client(world, assets)
    assets.current = facts(observed_vertical_reference=True)
    refused = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k1"))
    assert refused.status_code == 409
    assert refused.json()["verdict"] == "OBSERVED_REFERENCE_PRESENT"
    assert set(refused.json()) == {"verdict", "detail"}
    state = client.get(BASE, headers=_h("viewer")).json()
    assert state["observed"] is True and state["current"] is None

    assets.current = facts(kind=ProcessingArtifactKind.ORTHO)
    assert (
        client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k2")).json()["verdict"]
        == "NOT_A_DSM"
    )
    assets.current = facts()
    stale = client.post(
        BASE + "/declarations", json={**BODY, "expectedSequence": 3}, headers=_h("admin", "k3")
    )
    assert stale.status_code == 409 and stale.json()["verdict"] == "SEQUENCE_CONFLICT"
    nothing = client.post(
        BASE + "/withdrawals", json={"expectedSequence": 1}, headers=_h("admin", "k4")
    )
    assert nothing.status_code == 409 and nothing.json()["verdict"] == "SEQUENCE_CONFLICT"


def test_http_a_port_that_finds_no_asset_hides_it_on_read_and_write(world: World) -> None:
    class Nothing:
        def facts(self, **_: Any) -> None:
            return None

    client = _client(world, Nothing())  # type: ignore[arg-type]
    assert client.get(BASE, headers=_h("admin")).status_code == 404
    refused = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k"))
    assert refused.status_code == 404 and refused.json()["verdict"] == "UNKNOWN_ASSET"


def test_http_rejects_a_body_that_tries_to_set_scope_unit_or_datum_text(world: World) -> None:
    client = _client(world, FakeAssets())
    for bad in (
        {**BODY, "siteId": "other"},
        {**BODY, "unit": "foot"},
        {**BODY, "datum": "EGM96"},
        {**BODY, "expectedSequence": "0"},
        {k: v for k, v in BODY.items() if k != "basis"},
    ):
        response = client.post(BASE + "/declarations", json=bad, headers=_h("admin", "kx"))
        assert response.status_code == 422, bad
    assert world.current() is None


def test_http_sealed_journal_is_service_unavailable_and_writes_nothing(world: World) -> None:
    client = _client(world, FakeAssets())
    world.store._journal.close()  # noqa: SLF001 - 닫힌(봉인된) 원장 상태를 만든다
    response = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k1"))
    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"
    assert response.headers["Retry-After"] == "30"


# ── 공개 계약과 실제 라우트의 일치 ──────────────────────────────────────────
def test_the_published_openapi_matches_the_mounted_routes(world: World) -> None:
    import yaml
    from fastapi.routing import APIRoute
    from ksi_core.domains.external.ingress.vertical_reference_declarations import (
        build_vertical_reference_declaration_router,
    )

    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load((root / "contracts/api/openapi-core.yaml").read_text())
    published = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        if "vertical-reference" in path
        for method in item
        if method in {"get", "post", "put", "delete", "patch"}
    }
    router = build_vertical_reference_declaration_router(
        world.store, FakeAssets(), clock=lambda: NOW
    )
    mounted = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set())
    }
    assert mounted == published and len(mounted) == 3


def test_http_bodies_validate_against_the_published_schema(world: World) -> None:
    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "contracts/schemas/vertical-reference-declaration.v1.json").read_text()
    )

    def validator(name: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]})

    client = _client(world, FakeAssets())
    validator("DeclareVerticalReferenceV1").validate(BODY)
    created = client.post(BASE + "/declarations", json=BODY, headers=_h("admin", "k1"))
    validator("VerticalReferenceDeclarationWriteViewV1").validate(created.json())
    validator("VerticalReferenceDeclarationStateViewV1").validate(
        client.get(BASE, headers=_h("viewer")).json()
    )
    conflict = client.post(
        BASE + "/declarations", json={**BODY, "basis": "다른 근거"}, headers=_h("admin", "k1")
    )
    assert conflict.status_code == 409
    validator("VerticalReferenceDeclarationRefusalV1").validate(conflict.json())
    validator("WithdrawVerticalReferenceV1").validate({"expectedSequence": 1})
    withdrawn = client.post(
        BASE + "/withdrawals", json={"expectedSequence": 1}, headers=_h("admin", "w1")
    )
    validator("VerticalReferenceDeclarationWriteViewV1").validate(withdrawn.json())
