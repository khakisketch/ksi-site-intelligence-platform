"""WorkArea 계약·저장소 — 기하 불변과 "값으로 복사"가 이 파일이 지키는 두 문장 (M4-C).

1. **등록된 기하는 바뀌지 않는다.** 고치면 새 구역이고 이전 것은 보관된다 — 이미
   그 구역으로 낸 리포트가 가리키는 범위가 사후에 달라지지 않게.
2. **요청은 참조가 아니라 값을 싣는다.** ``resolve_zones`` 를 통과한 뒤로는 어느
   코드도 작업구역을 다시 보지 않는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.work_areas import (
    MAX_ACTIVE_WORK_AREAS,
    WorkAreaStore,
    WorkAreaStoreRecoveryError,
    WorkAreaVerdict,
)
from ksi_event_contracts.work_area import WorkArea, WorkAreaStatus
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "work-area.v1.json"

_NOW = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)


def _ring(x: float = 127.0, y: float = 37.0) -> list[list[float]]:
    return [[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]


def _polygon(x: float = 127.0, y: float = 37.0) -> dict[str, object]:
    return {"type": "Polygon", "coordinates": [_ring(x, y)]}


def _store(tmp_path: Path, *, known_sites: set[str] | None = None) -> WorkAreaStore:
    sites = known_sites
    return WorkAreaStore(
        DurableJournal(tmp_path / "work-areas.jsonl"),
        site_exists=None if sites is None else (lambda site_id: site_id in sites),
    )


# ── 계약 ────────────────────────────────────────────────────────────────
def test_roundtrips_against_the_json_schema() -> None:
    """계약 모델이 낸 wire 표현이 contracts/schemas SSOT 를 만족한다."""
    area = WorkArea(
        work_area_id="wa-site-1-0001",
        site_id="site-1",
        name="A공구 절토부",
        polygon=_polygon(),
        crs="EPSG:4326",
        status=WorkAreaStatus.ACTIVE,
        created_at="2026-08-13T04:00:00+00:00",
    )
    wire = area.model_dump(by_alias=True, mode="json")
    jsonschema.validate(wire, json.loads(_SCHEMA.read_text(encoding="utf-8")))
    assert WorkArea.model_validate(wire) == area


@pytest.mark.parametrize(
    ("polygon", "expected"),
    [
        ({"type": "MultiPolygon", "coordinates": []}, "Polygon"),
        ({"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [1.0, 2.0]]]}, "4개 이상"),
        (
            {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]]},
            "닫혀 있지 않다",
        ),
        ({"type": "Polygon", "coordinates": []}, "비어 있지 않은"),
        (
            {
                "type": "Polygon",
                "coordinates": [[[1.0, 2.0], [float("nan"), 4.0], [5.0, 6.0], [1.0, 2.0]]],
            },
            "유한하지 않다",
        ),
        (
            {"type": "Polygon", "coordinates": [_ring()], "crs": "EPSG:4326"},
            "알 수 없는 키",
        ),
    ],
)
def test_unusable_polygons_are_refused_at_registration(
    polygon: dict[str, object], expected: str
) -> None:
    """래스터 마스킹까지 갔다면 사람이 못 읽을 예외로 터졌을 것들 — 여기서 사람 말로 막는다."""
    with pytest.raises(ValidationError, match=expected):
        WorkArea(
            work_area_id="wa-site-1-0001",
            site_id="site-1",
            name="구역",
            polygon=polygon,
            crs="EPSG:5186",
            status=WorkAreaStatus.ACTIVE,
            created_at="2026-08-13T04:00:00+00:00",
        )


def test_lonlat_range_is_checked_only_for_epsg4326() -> None:
    """투영좌표계는 값 범위가 제각각이라 여기서 판정하지 않는다 — 경위도만 본다."""
    out_of_range = {"type": "Polygon", "coordinates": [_ring(x=200.0, y=37.0)]}
    with pytest.raises(ValidationError, match="경도가 범위 밖"):
        WorkArea(
            work_area_id="wa-1",
            site_id="s",
            name="n",
            polygon=out_of_range,
            crs="EPSG:4326",
            status=WorkAreaStatus.ACTIVE,
            created_at="2026-08-13T04:00:00+00:00",
        )
    # 같은 좌표가 투영좌표계에서는 정상값이다(200m 는 흔한 좌표다).
    assert WorkArea(
        work_area_id="wa-1",
        site_id="s",
        name="n",
        polygon=out_of_range,
        crs="EPSG:5186",
        status=WorkAreaStatus.ACTIVE,
        created_at="2026-08-13T04:00:00+00:00",
    )


def test_bool_coordinates_are_not_silently_read_as_numbers() -> None:
    """bool 은 int 의 하위형이라 isinstance 로는 걸러지지 않는다 — True 가 1.0 이 되면 안 된다."""
    ring = [[True, 2.0], [3.0, 4.0], [5.0, 6.0], [True, 2.0]]
    with pytest.raises(ValidationError, match="수가 아니다"):
        WorkArea(
            work_area_id="wa-1",
            site_id="s",
            name="n",
            polygon={"type": "Polygon", "coordinates": [ring]},
            crs="EPSG:5186",
            status=WorkAreaStatus.ACTIVE,
            created_at="2026-08-13T04:00:00+00:00",
        )


# ── 저장소 ──────────────────────────────────────────────────────────────
def test_registers_and_lists_active_areas(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.register(
        "site-1",
        name="A공구 절토부",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    )
    assert result.verdict is WorkAreaVerdict.REGISTERED
    assert result.work_area is not None
    assert result.work_area.work_area_id == "wa-site-1-0001"
    assert [a.work_area_id for a in store.list_for_site("site-1")] == ["wa-site-1-0001"]


def test_fixing_geometry_makes_a_new_area_and_archives_the_old_one(tmp_path: Path) -> None:
    """제자리 수정이 없다 — 과거 리포트가 가리키는 범위가 사후에 바뀌지 않게."""
    store = _store(tmp_path)
    first = store.register(
        "site-1",
        name="A공구",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert first is not None
    second = store.register(
        "site-1",
        name="A공구(정정)",
        polygon=_polygon(x=127.002),
        crs="EPSG:4326",
        supersedes=first.work_area_id,
        now=_NOW,
        actor="admin",
    ).work_area
    assert second is not None
    assert second.supersedes == first.work_area_id
    # 이전 구역의 기하는 그대로고 상태만 보관됨이다 — 지우지 않는다.
    archived = store.get(first.work_area_id)
    assert archived is not None
    assert archived.status is WorkAreaStatus.ARCHIVED
    assert archived.polygon == first.polygon
    assert [a.work_area_id for a in store.list_for_site("site-1")] == [second.work_area_id]


def test_archived_areas_cannot_be_chosen_for_new_comparisons(tmp_path: Path) -> None:
    store = _store(tmp_path)
    area = store.register(
        "site-1",
        name="A공구",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert area is not None
    store.archive(area.work_area_id, site_id="site-1", now=_NOW, actor="admin")
    outcome = store.resolve_zones([area.work_area_id], site_id="site-1")
    assert isinstance(outcome, str)
    assert "보관됨" in outcome


def test_resolve_zones_copies_polygons_as_values(tmp_path: Path) -> None:
    """이 함수를 통과한 뒤로는 아무도 작업구역을 다시 보지 않는다 — zoneId 는 workAreaId 다."""
    store = _store(tmp_path)
    ids = []
    for index in range(2):
        area = store.register(
            "site-1",
            name=f"구역{index}",
            polygon=_polygon(x=127.0 + index * 0.01),
            crs="EPSG:4326",
            supersedes=None,
            now=_NOW,
            actor="admin",
        ).work_area
        assert area is not None
        ids.append(area.work_area_id)
    outcome = store.resolve_zones(ids, site_id="site-1")
    assert not isinstance(outcome, str)
    zones, zone_crs = outcome
    assert set(zones) == set(ids)
    assert zone_crs == "EPSG:4326"
    assert zones[ids[0]] == _polygon()


def test_mixed_coordinate_systems_are_refused(tmp_path: Path) -> None:
    """한 비교의 구역들이 다른 좌표계면 면적이 서로 다른 뜻이 된다."""
    store = _store(tmp_path)
    first = store.register(
        "site-1",
        name="경위도",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    second = store.register(
        "site-1",
        name="투영",
        polygon=_polygon(),
        crs="EPSG:5186",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert first is not None and second is not None
    outcome = store.resolve_zones(
        [first.work_area_id, second.work_area_id], site_id="site-1"
    )
    assert isinstance(outcome, str)
    assert "좌표계가 서로 다르다" in outcome


def test_other_sites_areas_are_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    area = store.register(
        "site-1",
        name="A공구",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert area is not None
    outcome = store.resolve_zones([area.work_area_id], site_id="site-2")
    assert isinstance(outcome, str)
    assert "site-1" in outcome


def test_unknown_site_is_refused_when_the_site_store_is_wired(tmp_path: Path) -> None:
    """등록된 적 없는 현장의 구역은 어느 비교에도 쓰이지 못한 채 원장에만 쌓인다."""
    store = _store(tmp_path, known_sites={"site-1"})
    result = store.register(
        "site-unregistered",
        name="A공구",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    )
    assert result.verdict is WorkAreaVerdict.UNKNOWN_SITE


def test_active_count_is_capped_but_supersede_is_not_a_net_increase(tmp_path: Path) -> None:
    store = _store(tmp_path)
    last_id = ""
    for index in range(MAX_ACTIVE_WORK_AREAS):
        area = store.register(
            "site-1",
            name=f"구역{index}",
            polygon=_polygon(),
            crs="EPSG:4326",
            supersedes=None,
            now=_NOW,
            actor="admin",
        ).work_area
        assert area is not None
        last_id = area.work_area_id
    over = store.register(
        "site-1",
        name="하나 더",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    )
    assert over.verdict is WorkAreaVerdict.TOO_MANY_ACTIVE
    # 대체는 순증이 아니다 — 상한에 걸려 있어도 기하를 고칠 수 있어야 한다.
    fixed = store.register(
        "site-1",
        name="정정",
        polygon=_polygon(x=127.5),
        crs="EPSG:4326",
        supersedes=last_id,
        now=_NOW,
        actor="admin",
    )
    assert fixed.verdict is WorkAreaVerdict.REGISTERED


def test_superseding_an_already_archived_area_is_refused(tmp_path: Path) -> None:
    """이미 ARCHIVED 된 구역을 다시 '대체'하면 안 된다.

    이 경로가 상한 검사를 면제받으므로(대체는 순증이 아니다), 이미 보관된 대상을
    반복해서 대체하면 상한 없이 ACTIVE 구역을 계속 만들 수 있었다(재보관은
    무보수 no-op 이고 새 등록만 순증으로 남는다). supersedes 대상은 ACTIVE 여야만
    한다.
    """
    store = _store(tmp_path)
    area = store.register(
        "site-1",
        name="A공구",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert area is not None
    archived = store.archive(area.work_area_id, site_id="site-1", now=_NOW, actor="admin")
    assert archived.verdict is WorkAreaVerdict.ARCHIVED

    before = len(store.list_for_site("site-1", include_archived=True))
    result = store.register(
        "site-1",
        name="재대체 시도",
        polygon=_polygon(x=127.02),
        crs="EPSG:4326",
        supersedes=area.work_area_id,
        now=_NOW,
        actor="admin",
    )
    assert result.verdict is WorkAreaVerdict.SUPERSEDES_NOT_ACTIVE
    assert result.work_area is None
    # 거부됐으니 아무 레코드도 새로 생기지 않는다 — 상한 우회 통로가 닫혀 있다.
    assert len(store.list_for_site("site-1", include_archived=True)) == before

    # 반복 호출해도 계속 거부된다 — N번 불러 ACTIVE 를 상한 없이 늘릴 수 없다.
    for _ in range(3):
        repeat = store.register(
            "site-1",
            name="재대체 재시도",
            polygon=_polygon(x=127.03),
            crs="EPSG:4326",
            supersedes=area.work_area_id,
            now=_NOW,
            actor="admin",
        )
        assert repeat.verdict is WorkAreaVerdict.SUPERSEDES_NOT_ACTIVE
    active = [
        a
        for a in store.list_for_site("site-1", include_archived=True)
        if a.status is WorkAreaStatus.ACTIVE
    ]
    assert active == []


def test_replay_refuses_a_supersede_of_a_non_active_target(tmp_path: Path) -> None:
    """레코드가 이미 ARCHIVED 인 대상을 대체한다고 적혀 있으면 재생을 거부한다(fail-closed).

    register() 가 이 상태를 이제 막지만, 옛 journal(결함이 있던 시절에 쓰인)이나
    변조된 레코드를 재생할 때는 이 검사가 마지막 방어선이다.
    """
    journal_path = tmp_path / "work-areas.jsonl"
    first = WorkArea(
        work_area_id="wa-site-1-0001",
        site_id="site-1",
        name="A",
        polygon=_polygon(),
        crs="EPSG:4326",
        status=WorkAreaStatus.ARCHIVED,
        created_at="2026-08-13T04:00:00+00:00",
    )
    second = WorkArea(
        work_area_id="wa-site-1-0002",
        site_id="site-1",
        name="A(정정)",
        polygon=_polygon(x=127.01),
        crs="EPSG:4326",
        status=WorkAreaStatus.ACTIVE,
        supersedes="wa-site-1-0001",
        created_at="2026-08-13T04:00:00+00:00",
    )
    with journal_path.open("w", encoding="utf-8") as fh:
        for area in (first, second):
            fh.write(
                json.dumps(
                    {
                        "kind": "work-area-registered",
                        "ts": "2026-08-13T04:00:00+00:00",
                        "actor": "admin",
                        "siteId": "site-1",
                        "workAreaId": area.work_area_id,
                        "workArea": area.model_dump(by_alias=True, mode="json"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    with pytest.raises(WorkAreaStoreRecoveryError, match="이미 ACTIVE 가 아니다"):
        _store(tmp_path)


def test_replay_restores_status_including_the_supersede_side_effect(tmp_path: Path) -> None:
    """대체가 이전 것을 보관시키는 부수효과까지 재생돼야 projection 이 기록과 갈라지지 않는다."""
    store = _store(tmp_path)
    first = store.register(
        "site-1",
        name="A",
        polygon=_polygon(),
        crs="EPSG:4326",
        supersedes=None,
        now=_NOW,
        actor="admin",
    ).work_area
    assert first is not None
    store.register(
        "site-1",
        name="A(정정)",
        polygon=_polygon(x=127.01),
        crs="EPSG:4326",
        supersedes=first.work_area_id,
        now=_NOW,
        actor="admin",
    )
    store._journal.close()  # noqa: SLF001 -- 재생 검증에 필요한 테스트 전용 조작

    revived = _store(tmp_path)
    assert [
        (a.work_area_id, a.status.value)
        for a in revived.list_for_site("site-1", include_archived=True)
    ] == [("wa-site-1-0001", "ARCHIVED"), ("wa-site-1-0002", "ACTIVE")]


def test_replay_refuses_a_dangling_supersede(tmp_path: Path) -> None:
    """없는 구역을 대체한다고 적힌 레코드가 재생되면 기동을 거부한다(fail-closed)."""
    journal_path = tmp_path / "work-areas.jsonl"
    area = WorkArea(
        work_area_id="wa-site-1-0001",
        site_id="site-1",
        name="A",
        polygon=_polygon(),
        crs="EPSG:4326",
        status=WorkAreaStatus.ACTIVE,
        supersedes="wa-site-1-9999",
        created_at="2026-08-13T04:00:00+00:00",
    )
    journal_path.write_text(
        json.dumps(
            {
                "kind": "work-area-registered",
                "ts": "2026-08-13T04:00:00+00:00",
                "actor": "admin",
                "siteId": "site-1",
                "workAreaId": area.work_area_id,
                "workArea": area.model_dump(by_alias=True, mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkAreaStoreRecoveryError, match="supersedes 대상이 없다"):
        _store(tmp_path)
