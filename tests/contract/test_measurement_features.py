"""저장 선(측정 대상) — 영역에 속한 불변 revision, 멱등, 범위 격리, 재생.

합성 값만 쓴다. 이 시험은 저장소·API 경계의 증거이지 측량 정확도의 증거가 아니다.
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
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.domains.sites import measurement_features as mf
from ksi_core.domains.sites.measurement_features import (
    MeasurementFeatureStore,
    MeasurementFeatureStoreRecoveryError,
    MeasurementFeatureVerdict,
    build_measurement_feature_router,
    mount_measurement_features,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.work_areas import WorkAreaStore, WorkAreaVerdict
from ksi_event_contracts.measurement_feature import (
    CreateMeasurementFeatureV1,
    MeasurementLineV1,
    ReviseMeasurementFeatureV1,
)

NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
ORG, OTHER_ORG = "org-1", "org-2"
SITE = "site-1"
LINE = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (30.0, 0.0), (30.0, 40.0)))
MOVED = MeasurementLineV1(crs="EPSG:5186", vertices=((0.0, 0.0), (35.0, 0.0)))
TOKENS = {
    "admin": ("tok-admin", ORG, Role.ADMIN),
    "viewer": ("tok-viewer", ORG, Role.VIEWER),
    "foreign": ("tok-foreign", OTHER_ORG, Role.ADMIN),
}


def _ring() -> list[list[float]]:
    return [[127.0, 37.0], [127.001, 37.0], [127.001, 37.001], [127.0, 37.001], [127.0, 37.0]]


class World:
    """한 조직의 현장·영역과 저장소. 다른 조직 현장은 보이지 않는다."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.site_owner = {SITE: ORG, "site-2": ORG, "foreign-site": OTHER_ORG}
        self.areas = WorkAreaStore(
            DurableJournal(tmp_path / "areas.jsonl"),
            site_exists=lambda site_id: site_id in self.site_owner,
        )
        self.area_id = self._register(SITE)
        self.store = self._open()

    def _register(self, site_id: str) -> str:
        result = self.areas.register(
            site_id,
            name="A공구",
            polygon={"type": "Polygon", "coordinates": [_ring()]},
            crs="EPSG:4326",
            supersedes=None,
            now=NOW,
            actor="admin",
        )
        assert result.verdict is WorkAreaVerdict.REGISTERED and result.work_area is not None
        return result.work_area.work_area_id

    def _open(self) -> MeasurementFeatureStore:
        return MeasurementFeatureStore(
            DurableJournal(self.tmp / "features.jsonl"),
            work_areas=self.areas,
            site_visible_to=lambda site_id, org: self.site_owner.get(site_id) == org,
        )

    def reopen(self) -> MeasurementFeatureStore:
        self.store._journal.close()  # noqa: SLF001 - 재시작처럼 같은 원장을 다시 연다
        self.store = self._open()
        return self.store

    def create(
        self,
        *,
        org: str = ORG,
        site: str = SITE,
        area: str | None = None,
        key: str = "k1",
        line: MeasurementLineV1 = LINE,
        name: str = "북쪽 경사면",
        principal: str = "alice",
    ) -> mf.MeasurementFeatureResult:
        area = area or self.area_id
        return self.store.create(
            organization_id=org,
            site_id=site,
            work_area_id=area,
            principal_id=principal,
            body=CreateMeasurementFeatureV1(work_area_id=area, name=name, line=line),
            idempotency_key=key,
            now=NOW,
        )

    def revise(
        self,
        feature_id: str,
        *,
        expected: int,
        key: str = "r1",
        line: MeasurementLineV1 = MOVED,
        org: str = ORG,
        principal: str = "alice",
    ) -> mf.MeasurementFeatureResult:
        return self.store.revise(
            organization_id=org,
            site_id=SITE,
            work_area_id=self.area_id,
            feature_id=feature_id,
            principal_id=principal,
            body=ReviseMeasurementFeatureV1(expected_revision=expected, name="수정", line=line),
            idempotency_key=key,
            now=NOW,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_create_seals_a_first_revision_bound_to_the_line(world: World) -> None:
    result = world.create()

    assert result.verdict is MeasurementFeatureVerdict.CREATED
    revision = result.revision
    assert revision is not None and revision.revision == 1
    assert revision.feature_id.startswith("mf-") and len(revision.feature_id) == 35
    assert revision.revision_digest == revision.canonical_digest()
    assert revision.line_digest == LINE.digest()
    assert (revision.site_id, revision.work_area_id) == (SITE, world.area_id)


def test_the_same_key_and_body_returns_the_original_and_writes_nothing_new(world: World) -> None:
    first = world.create()
    again = world.create()

    assert again.verdict is MeasurementFeatureVerdict.REPLAYED
    assert again.revision == first.revision
    listed = world.store.list_latest(organization_id=ORG, site_id=SITE, work_area_id=world.area_id)
    assert listed is not None and len(listed) == 1


def test_the_same_key_with_another_body_conflicts(world: World) -> None:
    world.create()
    assert world.create(line=MOVED).verdict is MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT
    assert world.create(name="다른 이름").verdict is MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT


def test_another_principal_may_reuse_a_key_independently(world: World) -> None:
    mine, theirs = world.create(), world.create(principal="bob")
    assert theirs.verdict is MeasurementFeatureVerdict.CREATED
    assert theirs.revision is not None and mine.revision is not None
    assert theirs.revision.feature_id != mine.revision.feature_id


def test_an_edit_is_a_new_revision_and_the_old_one_stays_readable(world: World) -> None:
    created = world.create().revision
    assert created is not None
    revised = world.revise(created.feature_id, expected=1)

    assert revised.verdict is MeasurementFeatureVerdict.REVISED
    assert revised.revision is not None and revised.revision.revision == 2
    old = world.store.get(
        organization_id=ORG,
        site_id=SITE,
        work_area_id=world.area_id,
        feature_id=created.feature_id,
        revision=1,
    )
    assert old == created and old.line_digest == LINE.digest()
    latest = world.store.get(
        organization_id=ORG, site_id=SITE, work_area_id=world.area_id, feature_id=created.feature_id
    )
    assert latest is not None and latest.revision == 2 and latest.line_digest == MOVED.digest()
    history = world.store.list_revisions(
        organization_id=ORG, site_id=SITE, work_area_id=world.area_id, feature_id=created.feature_id
    )
    assert history is not None and [item.revision for item in history] == [1, 2]


def test_a_stale_edit_conflicts_and_a_retry_of_the_edit_is_idempotent(world: World) -> None:
    created = world.create().revision
    assert created is not None
    first = world.revise(created.feature_id, expected=1)
    stale = world.revise(created.feature_id, expected=1, key="r2", line=LINE)

    assert stale.verdict is MeasurementFeatureVerdict.REVISION_CONFLICT
    retried = world.revise(created.feature_id, expected=1)
    assert retried.verdict is MeasurementFeatureVerdict.REPLAYED
    assert retried.revision == first.revision


def test_unknown_or_foreign_scope_is_not_disclosed(world: World) -> None:
    created = world.create().revision
    assert created is not None
    foreign_read = world.store.get(
        organization_id=OTHER_ORG,
        site_id=SITE,
        work_area_id=world.area_id,
        feature_id=created.feature_id,
    )
    assert foreign_read is None
    assert world.revise(created.feature_id, expected=1, org=OTHER_ORG).verdict is (
        MeasurementFeatureVerdict.UNKNOWN_WORK_AREA
    )
    assert world.revise("mf-" + "0" * 32, expected=1).verdict is (
        MeasurementFeatureVerdict.UNKNOWN_FEATURE
    )
    # 같은 조직이라도 다른 현장 경로로는 이 영역을 읽지 못한다.
    assert (
        world.store.get(
            organization_id=ORG,
            site_id="site-2",
            work_area_id=world.area_id,
            feature_id=created.feature_id,
        )
        is None
    )
    assert world.create(org=OTHER_ORG).verdict is MeasurementFeatureVerdict.UNKNOWN_WORK_AREA
    assert (
        world.store.list_latest(organization_id=OTHER_ORG, site_id=SITE, work_area_id=world.area_id)
        is None
    )


def test_the_body_work_area_must_match_the_path(world: World) -> None:
    result = world.store.create(
        organization_id=ORG,
        site_id=SITE,
        work_area_id=world.area_id,
        principal_id="alice",
        body=CreateMeasurementFeatureV1(work_area_id="wa-other", name="n", line=LINE),
        idempotency_key="k",
        now=NOW,
    )
    assert result.verdict is MeasurementFeatureVerdict.INVALID


@pytest.mark.parametrize("key", ["", "   ", "a" * 256, "bad\nkey", "bad\x7fkey"])
def test_unusable_idempotency_keys_are_refused(world: World, key: str) -> None:
    assert world.create(key=key).verdict is MeasurementFeatureVerdict.INVALID


def test_an_archived_area_refuses_new_writes_but_keeps_history_readable(world: World) -> None:
    created = world.create().revision
    assert created is not None
    assert (
        world.areas.archive(world.area_id, site_id=SITE, now=NOW, actor="admin").verdict
        is WorkAreaVerdict.ARCHIVED
    )

    assert world.create(key="new").verdict is MeasurementFeatureVerdict.WORK_AREA_NOT_ACTIVE
    assert world.revise(created.feature_id, expected=1).verdict is (
        MeasurementFeatureVerdict.WORK_AREA_NOT_ACTIVE
    )
    # 응답을 잃은 같은 요청의 재시도는 원래 결과를 돌려준다.
    assert world.create().verdict is MeasurementFeatureVerdict.REPLAYED
    kept = world.store.get(
        organization_id=ORG, site_id=SITE, work_area_id=world.area_id, feature_id=created.feature_id
    )
    assert kept == created


def test_limits_refuse_rather_than_grow_without_bound(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mf, "MAX_FEATURES_PER_WORK_AREA", 2)
    monkeypatch.setattr(mf, "MAX_REVISIONS_PER_FEATURE", 2)
    first = world.create(key="a").revision
    assert first is not None
    assert world.create(key="b").verdict is MeasurementFeatureVerdict.CREATED
    assert world.create(key="c").verdict is MeasurementFeatureVerdict.TOO_MANY_FEATURES
    assert world.revise(first.feature_id, expected=1, key="r1").verdict is (
        MeasurementFeatureVerdict.REVISED
    )
    assert world.revise(first.feature_id, expected=2, key="r2", line=LINE).verdict is (
        MeasurementFeatureVerdict.TOO_MANY_REVISIONS
    )


def test_restart_replays_revisions_and_keeps_idempotency(world: World) -> None:
    created = world.create().revision
    assert created is not None
    world.revise(created.feature_id, expected=1)

    store = world.reopen()
    latest = store.get(
        organization_id=ORG, site_id=SITE, work_area_id=world.area_id, feature_id=created.feature_id
    )
    assert latest is not None and latest.revision == 2
    assert world.create().verdict is MeasurementFeatureVerdict.REPLAYED
    assert world.revise(created.feature_id, expected=1).verdict is (
        MeasurementFeatureVerdict.REPLAYED
    )
    assert world.create(line=MOVED).verdict is MeasurementFeatureVerdict.IDEMPOTENCY_CONFLICT


def test_the_raw_idempotency_key_is_never_written(world: World) -> None:
    world.create(key="secret-client-key-12345")
    text = (world.tmp / "features.jsonl").read_text(encoding="utf-8")
    assert "secret-client-key-12345" not in text


def _records(world: World) -> list[dict[str, Any]]:
    path = world.tmp / "features.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rewrite(world: World, records: list[dict[str, Any]]) -> None:
    world.store._journal.close()  # noqa: SLF001
    (world.tmp / "features.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def test_replay_refuses_a_revision_whose_line_was_edited_in_place(world: World) -> None:
    world.create()
    records = _records(world)
    records[0]["revision"]["line"]["vertices"][1] = [99.0, 0.0]
    _rewrite(world, records)
    with pytest.raises(MeasurementFeatureStoreRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_an_unsealed_or_renamed_revision(world: World) -> None:
    world.create()
    records = _records(world)
    records[0]["revision"]["revisionDigest"] = None
    _rewrite(world, records)
    with pytest.raises(MeasurementFeatureStoreRecoveryError, match="서명"):
        world._open()  # noqa: SLF001
    records[0]["revision"]["revisionDigest"] = "sha256:" + "0" * 64
    _rewrite(world, records)
    with pytest.raises(MeasurementFeatureStoreRecoveryError):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_skipped_revision_number(world: World) -> None:
    created = world.create().revision
    assert created is not None
    world.revise(created.feature_id, expected=1)
    records = _records(world)
    _rewrite(world, records[1:])  # 1번 revision 이 사라진 원장
    with pytest.raises(MeasurementFeatureStoreRecoveryError, match="이어지지"):
        world._open()  # noqa: SLF001


def test_replay_refuses_a_revision_appended_from_another_organization(world: World) -> None:
    created = world.create().revision
    assert created is not None
    world.revise(created.feature_id, expected=1)
    records = _records(world)
    records[1]["organizationId"] = OTHER_ORG
    _rewrite(world, records)
    with pytest.raises(MeasurementFeatureStoreRecoveryError, match="다른 조직"):
        world._open()  # noqa: SLF001


def test_replay_refuses_an_unknown_record_kind(world: World) -> None:
    world.create()
    records = _records(world)
    records[0]["kind"] = "something-else"
    _rewrite(world, records)
    with pytest.raises(MeasurementFeatureStoreRecoveryError, match="알 수 없는 kind"):
        world._open()  # noqa: SLF001


# ── HTTP ─────────────────────────────────────────────────────────────────
def _client(world: World) -> TestClient:
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
    mount_measurement_features(app, world.store, clock=lambda: NOW)
    return TestClient(app)


def _h(name: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {TOKENS[name][0]}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _base(world: World) -> str:
    return f"/v1/sites/{SITE}/work-areas/{world.area_id}/measurement-features"


def _body(world: World, line: MeasurementLineV1 = LINE) -> dict[str, Any]:
    return {
        "workAreaId": world.area_id,
        "name": "북쪽 경사면",
        "line": line.model_dump(by_alias=True, mode="json"),
    }


def test_http_create_read_edit_and_exact_revision(world: World) -> None:
    client = _client(world)
    created = client.post(_base(world), json=_body(world), headers=_h("admin", "k1"))
    assert created.status_code == 201, created.text
    revision = created.json()["revision"]
    feature_id = revision["featureId"]
    assert created.json()["verdict"] == "CREATED"

    replay = client.post(_base(world), json=_body(world), headers=_h("admin", "k1"))
    assert replay.status_code == 200 and replay.json()["revision"] == revision

    revised = client.post(
        f"{_base(world)}/{feature_id}/revisions",
        json={
            "expectedRevision": 1,
            "name": "수정",
            "line": MOVED.model_dump(by_alias=True, mode="json"),
        },
        headers=_h("admin", "r1"),
    )
    assert revised.status_code == 201 and revised.json()["revision"]["revision"] == 2

    assert client.get(f"{_base(world)}/{feature_id}", headers=_h("viewer")).json()["revision"] == 2
    first = client.get(f"{_base(world)}/{feature_id}/revisions/1", headers=_h("viewer"))
    assert first.status_code == 200 and first.json() == revision
    history = client.get(f"{_base(world)}/{feature_id}/revisions", headers=_h("viewer"))
    assert [item["revision"] for item in history.json()["revisions"]] == [1, 2]
    listing = client.get(_base(world), headers=_h("viewer"))
    assert [item["featureId"] for item in listing.json()["features"]] == [feature_id]


def test_http_conflicts_and_missing_header(world: World) -> None:
    client = _client(world)
    client.post(_base(world), json=_body(world), headers=_h("admin", "k1"))
    conflict = client.post(_base(world), json=_body(world, MOVED), headers=_h("admin", "k1"))
    assert conflict.status_code == 409 and conflict.json()["verdict"] == "IDEMPOTENCY_CONFLICT"
    assert client.post(_base(world), json=_body(world), headers=_h("admin")).status_code == 422


def test_http_a_viewer_reads_but_cannot_write(world: World) -> None:
    client = _client(world)
    denied = client.post(_base(world), json=_body(world), headers=_h("viewer", "k1"))
    assert denied.status_code == 403
    assert client.get(_base(world), headers=_h("viewer")).status_code == 200
    assert client.get(_base(world)).status_code in (401, 403)


def test_http_a_foreign_organization_sees_nothing(world: World) -> None:
    client = _client(world)
    created = client.post(_base(world), json=_body(world), headers=_h("admin", "k1"))
    feature_id = created.json()["revision"]["featureId"]
    for response in (
        client.get(_base(world), headers=_h("foreign")),
        client.get(f"{_base(world)}/{feature_id}", headers=_h("foreign")),
        client.get(f"{_base(world)}/{feature_id}/revisions/1", headers=_h("foreign")),
        client.post(_base(world), json=_body(world), headers=_h("foreign", "x")),
    ):
        assert response.status_code == 404, response.text


def test_http_rejects_unknown_fields_and_bad_geometry(world: World) -> None:
    client = _client(world)
    extra = {**_body(world), "organizationId": "org-2"}
    assert client.post(_base(world), json=extra, headers=_h("admin", "a")).status_code == 422
    bad = {**_body(world), "line": {"crs": "EPSG:5186", "vertices": [[1.0, 1.0], [1.0, 1.0]]}}
    assert client.post(_base(world), json=bad, headers=_h("admin", "b")).status_code == 422
    assert not world.store.list_latest(
        organization_id=ORG, site_id=SITE, work_area_id=world.area_id
    )


def _scoped_client(world: World, *, areas: frozenset[str], sites: frozenset[str]) -> TestClient:
    scoped = Principal(
        principal_id="scoped",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=ORG,
        allowed_site_ids=sites,
        allowed_work_area_ids=areas,
    )
    token = "tok-scoped"  # noqa: S105 - fixed test token
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=scoped
                )
            ]
        ),
    )
    mount_measurement_features(app, world.store, clock=lambda: NOW)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_http_a_scoped_operator_reaches_only_its_granted_area(world: World) -> None:
    allowed = _scoped_client(world, areas=frozenset({world.area_id}), sites=frozenset({SITE}))
    created = allowed.post(_base(world), json=_body(world), headers={"Idempotency-Key": "k"})
    assert created.status_code == 201, created.text
    feature_id = created.json()["revision"]["featureId"]
    assert allowed.get(f"{_base(world)}/{feature_id}").status_code == 200

    other_area = _scoped_client(world, areas=frozenset({"wa-site-1-9999"}), sites=frozenset({SITE}))
    other_site = _scoped_client(
        world, areas=frozenset({world.area_id}), sites=frozenset({"site-2"})
    )
    for client in (other_area, other_site):
        assert client.get(_base(world)).status_code == 404
        assert client.get(f"{_base(world)}/{feature_id}").status_code == 404
        assert (
            client.post(_base(world), json=_body(world), headers={"Idempotency-Key": "z"})
        ).status_code == 404


# ── 공개 계약과 실제 라우트의 일치 ──────────────────────────────────────────
def test_the_published_openapi_matches_the_mounted_routes(world: World) -> None:
    import yaml
    from fastapi.routing import APIRoute

    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load((root / "contracts/api/openapi-core.yaml").read_text())
    published = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        if "measurement-features" in path
        for method in item
        if method in {"get", "post"}
    }
    router = build_measurement_feature_router(world.store, clock=lambda: NOW)
    mounted = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute) and "measurement-features" in route.path
        for method in (route.methods or set())
    }
    assert mounted == published and len(mounted) == 6


def test_http_bodies_validate_against_the_published_schema(world: World) -> None:
    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "contracts/schemas/measurement-feature.v1.json").read_text())

    def validator(name: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]})

    client = _client(world)
    created = client.post(_base(world), json=_body(world), headers=_h("admin", "k1"))
    validator("MeasurementFeatureWriteViewV1").validate(created.json())
    validator("CreateMeasurementFeatureV1").validate(_body(world))
    feature_id = created.json()["revision"]["featureId"]
    validator("MeasurementFeatureListViewV1").validate(
        client.get(_base(world), headers=_h("viewer")).json()
    )
    validator("MeasurementFeatureRevisionListViewV1").validate(
        client.get(f"{_base(world)}/{feature_id}/revisions", headers=_h("viewer")).json()
    )
    conflict = client.post(_base(world), json=_body(world, MOVED), headers=_h("admin", "k1"))
    assert conflict.status_code == 409
    validator("MeasurementFeatureRefusalV1").validate(conflict.json())
    revise = {
        "expectedRevision": 1,
        "name": "수정",
        "line": MOVED.model_dump(by_alias=True, mode="json"),
    }
    validator("ReviseMeasurementFeatureV1").validate(revise)
    assert list(validator("CreateMeasurementFeatureV1").iter_errors({**_body(world), "x": 1}))
