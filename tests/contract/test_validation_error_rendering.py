"""요청 검증 422 는 **어느 라우트에서도** JSON 으로 그려진다 — 500 유출 횡단 게이트.

2026-08-18 전수 조사가 찾은 결함 클래스: pydantic 은 올바르게 검증 오류를 내는데,
FastAPI 기본 핸들러가 오류 상세의 ``input`` 에 **문제의 값을 그대로 되싣고**,
Starlette ``JSONResponse.render`` 의 ``json.dumps(allow_nan=False)`` / ``.encode("utf-8")``
가 그 값에서 터진다. 아무도 안 잡아 **500 + text/plain** 이 나간다.

이게 왜 중요한가: 워커의 ``core_client._post`` 는 본문 JSON 파싱 실패를
``NON_JSON_RESPONSE`` 로 싼다 — 운영자·워커가 **"생산자의 영구 계약 위반"과
"Core 일시 장애"를 구분할 수 없다.** 전자는 재시도해도 영원히 실패하고 후자는
재시도가 맞는데 응답이 같아 판단이 불가능하다.

**입력은 전부 문법적으로 합법인 JSON 이다.** ``1e400`` 은 RFC 8259 상 정상 숫자
리터럴이고 ``\\ud800`` 이스케이프도 유효하다 — 파서 우회가 아니라 정상 요청이라
제약이 걸린 필드를 가진 **모든** 라우트에서 재현된다. 그래서 라우트별 회귀가 아니라
이 횡단 게이트가 필요하다.

**기법 주의**: 반드시 ``raise_server_exceptions=False`` 로 클라이언트를 만든다.
기본값이면 500 이 예외로 튀어 테스트가 "에러"로만 보이고 "422 가 아니다"로는
안 보인다 — 기존 계약 테스트 전부가 이걸 안 해서 이 클래스를 통째로 못 봤다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.sites import SiteStore

_ADMIN_TOKEN = "test-admin-token"


def _auth_registry() -> AuthRegistry:
    """다른 계약 테스트와 같은 관용구(`test_processing_jobs.py:_auth_registry`)."""
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_ADMIN_TOKEN.encode()).hexdigest(),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _client(tmp_path: Path) -> TestClient:
    """``/v1/sites`` 가 **실제로 장착된** 앱 — 조립에 라우트가 없으면 본문 검증 층에
    닿지 못해 이 게이트가 통째로 공허해진다(초록불이 거짓말이 된다)."""
    app = create_app(
        auth_registry=_auth_registry(),
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    return client


# 문법상 합법이지만 그대로 되실으면 JSON 렌더가 깨지는 값들.
_HOSTILE_BODIES: list[tuple[str, str]] = [
    ("NaN", '{"x": NaN}'),
    ("Infinity", '{"x": Infinity}'),
    ("-Infinity", '{"x": -Infinity}'),
    ("1e400(오버플로 리터럴)", '{"x": 1e400}'),
    ("lone surrogate", '{"x": "a\\ud800b"}'),
    ("중첩된 lone surrogate", '{"x": {"y": ["a\\udfffb"]}}'),
]


@pytest.mark.parametrize(("label", "raw"), _HOSTILE_BODIES, ids=[c[0] for c in _HOSTILE_BODIES])
def test_hostile_json_body_never_renders_as_a_500(label: str, raw: str, tmp_path: Path) -> None:
    """장착된 표면에 쏴도 500 + text/plain 이 나오지 않는다."""
    client = _client(tmp_path)
    response = client.post(
        "/v1/sites", content=raw.encode("utf-8", "surrogatepass"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 500, f"{label}: {response.status_code} {response.text[:200]}"


@pytest.mark.parametrize(("label", "raw"), _HOSTILE_BODIES, ids=[c[0] for c in _HOSTILE_BODIES])
def test_hostile_json_body_error_is_machine_readable(
    label: str, raw: str, tmp_path: Path
) -> None:
    """거부 응답이 **JSON 이어야** 워커가 '계약 위반'과 '서버 장애'를 가른다.

    404(라우트 미장착)면 본문 검증까지 가지 않으므로 이 단언의 대상이 아니다.
    """
    client = _client(tmp_path)
    response = client.post(
        "/v1/sites", content=raw.encode("utf-8", "surrogatepass"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 404, "라우트가 장착되지 않으면 이 게이트는 공허하다"
    assert response.headers["content-type"].startswith("application/json"), (
        f"{label}: content-type={response.headers.get('content-type')!r} body={response.text[:200]}"
    )
    json.loads(response.text)  # 파싱 자체가 되는지 — 워커의 _post 가 하는 일


def test_render_safe_keeps_the_offending_value_visible() -> None:
    """[비공허 대조] 값을 지워버리지 않는다 — 요청자가 어느 값이 문제인지 알아야 고친다."""
    from ksi_core.api_base import _render_safe  # noqa: PLC2701 -- 순수 판정 함수 직접 시험

    assert _render_safe(float("nan")) == "nan"
    assert _render_safe(float("inf")) == "inf"
    assert _render_safe(1.5) == 1.5
    assert _render_safe("정상") == "정상"
    assert "\\ud800" in _render_safe("a\ud800b")
    nested: dict[str, Any] = {"k": [float("-inf"), {"deep": "a\ud800"}]}
    rendered = _render_safe(nested)
    json.dumps(rendered, allow_nan=False)  # 이게 터지지 않는 것이 이 함수의 계약이다


def test_normal_body_is_unaffected(tmp_path: Path) -> None:
    """[비공허 대조] 정상 요청은 이 핸들러를 타지 않는다 — 422 를 남발하지 않는다."""
    client = _client(tmp_path)
    response = client.post("/v1/sites", json={"siteId": "site-1"})
    # 필드가 모자라 422 인 것은 정상이다 — 이 게이트가 막는 것은 500 하나다.
    assert response.status_code != 500, response.text
    assert response.status_code != 404, "라우트가 장착되지 않으면 이 게이트는 공허하다"


# ── 자리별 결함 — 전수 조사 Class B/C 회귀 (2026-08-18) ──────────────────────
#
# 아래는 라우트 픽스처가 필요 없는 순수 계약·계산 층 회귀다. HTTP 표면 회귀는
# 각 모듈의 계약 테스트 파일이 자기 관례로 갖는다.


def test_oversized_integer_coordinate_is_a_typed_refusal_not_an_overflow() -> None:
    """[Class B] 파이썬 int 는 자리수 제한이 없어 ``10**400`` 이 그대로 들어온다.

    ``math.isfinite`` 가 float 변환에서 **OverflowError** 를 던지면 그건 ValueError 가
    아니라 호출자의 typed 거부를 지나쳐 500 이 된다 — 이 헬퍼를 쓰는 세 표면
    (작업구역 등록·비교 요청·설계 대비 요청)이 전부 그랬다.
    """
    from ksi_event_contracts.work_area import assert_polygon_is_usable

    huge = 10**400
    ring = [[huge, 0.0], [1.0, 0.0], [1.0, 1.0], [huge, 0.0]]
    with pytest.raises(ValueError, match="표현 범위"):
        assert_polygon_is_usable({"type": "Polygon", "coordinates": [ring]}, crs="EPSG:5186")


def test_normal_polygon_is_still_usable() -> None:
    """[비공허 대조] 정상 폴리곤은 그대로 통과한다 — 과잉 거부가 아니다."""
    from ksi_event_contracts.work_area import assert_polygon_is_usable

    ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    assert_polygon_is_usable({"type": "Polygon", "coordinates": [ring]}, crs="EPSG:5186")


def test_subnormal_focal_length_is_a_typed_refusal_not_a_zero_division() -> None:
    """[Class B] subnormal 초점거리는 ``/1000`` 에서 0.0 으로 언더플로한다.

    ``CameraSpec`` 의 ``gt=0`` 은 ``5e-324`` 를 통과시키므로 계산까지 도달하고,
    ``ZeroDivisionError`` 는 typed 실패가 아니라 500 으로 샌다.
    """
    from ksi_mission_planning.camera import CameraSpec, CameraSpecError, compute_gsd_m

    camera = CameraSpec(
        sensor_width_mm=17.3, focal_length_mm=5e-324, image_width_px=5280, image_height_px=3956
    )
    with pytest.raises(CameraSpecError, match="언더플로"):
        compute_gsd_m(camera, 40.0)


def test_normal_camera_still_computes_gsd() -> None:
    """[비공허 대조] 정상 카메라의 GSD 계산은 그대로다."""
    from ksi_mission_planning.camera import CameraSpec, compute_gsd_m

    camera = CameraSpec(
        sensor_width_mm=17.3, focal_length_mm=12.0, image_width_px=5280, image_height_px=3956
    )
    assert compute_gsd_m(camera, 40.0) == pytest.approx(0.010922, rel=1e-3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_contract_models_reject_non_finite_floats(bad: float) -> None:
    """[Class C] 계약 베이스가 비유한 실수를 거부한다 — 원장 봉인 차단.

    ``DurableJournal`` 은 ``json.dumps(allow_nan=False)`` 를 쓰고 append 예외를
    **봉인으로 승격**한다. 비유한 값이 검증을 통과해 원장에 닿으면 그 저장소가
    프로세스 수명 내내 죽는다 — 한 요청으로 서비스가 영구히 멈추는 경로다.
    """
    from ksi_event_contracts.coverage_report import CoverageCell, CoverageCellState
    from pydantic import ValidationError

    state = next(iter(CoverageCellState))
    with pytest.raises(ValidationError):
        CoverageCell(cell_id="c1", state=state, quality=bad)


def test_contract_models_still_accept_finite_floats() -> None:
    """[비공허 대조] 정상 실수와 None 은 그대로 통과한다."""
    from ksi_event_contracts.coverage_report import CoverageCell, CoverageCellState

    state = next(iter(CoverageCellState))
    assert CoverageCell(cell_id="c1", state=state, quality=0.9).quality == 0.9
    assert CoverageCell(cell_id="c2", state=state, quality=None).quality is None


def _nested_geometry(depth: int) -> dict[str, Any]:
    geometry: dict[str, Any] = {"type": "Point", "coordinates": [[1.0, 2.0], [3.0, 4.0]]}
    for _ in range(depth):
        geometry = {"type": "GeometryCollection", "geometries": [geometry]}
    return geometry


@pytest.mark.parametrize("depth", [400, 900, 5000])
def test_deeply_nested_geometry_is_refused_not_a_recursion_error(depth: int) -> None:
    """[Class B] 깊게 중첩된 GeometryCollection 이 ``RecursionError`` 를 내면 안 된다.

    ``RecursionError`` 는 ``ValueError`` 도 ``ValidationError`` 도 아니라 어떤 typed
    거부에도 안 걸려 500 으로 샌다. 상한을 넘으면 **퇴화로 판정**한다 — Core 가
    끝까지 읽지 못한 구조를 CRITICAL 확정 근거로 삼을 수 없다(fail-closed).
    """
    from ksi_core.events import _geometry_is_degenerate  # noqa: PLC2701 -- 순수 판정 함수

    assert _geometry_is_degenerate(_nested_geometry(depth)) is not None


@pytest.mark.parametrize("depth", [0, 1, 3])
def test_shallow_geometry_is_still_accepted(depth: int) -> None:
    """[비공허 대조] 실제 위험장이 쓰는 얕은 형상은 퇴화로 판정되지 않는다."""
    from ksi_core.events import _geometry_is_degenerate  # noqa: PLC2701

    assert _geometry_is_degenerate(_nested_geometry(depth)) is None


# ── 재조사(2026-08-18, 미조사 라우터 6개)가 찾은 결함 회귀 ───────────────────


@pytest.mark.parametrize("depth", [968, 2000, 9000])
def test_deeply_nested_legal_json_renders_as_422_json(depth: int, tmp_path: Path) -> None:
    """[F5] 깊게 중첩된 **합법** JSON 도 422 를 JSON 으로 받는다.

    이전에는 pydantic 이 올바르게 422 를 판정한 뒤, 그 오류 상세에 되실린 입력을
    ``jsonable_encoder`` 가 그리다 RecursionError 로 500 이 났다. 임계 깊이는 그
    시점 스택 잔량에 따라 968~1000 사이에서 흔들리므로 회귀 테스트는 여유 있는
    깊이를 쓴다(재조사 판정의 테스트 주의사항).
    """
    client = _client(tmp_path)
    nested = "[" * depth + "1" + "]" * depth
    response = client.post(
        "/v1/sites",
        content=('{"siteId": ' + nested + "}").encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 500, response.text[:200]
    assert response.headers["content-type"].startswith("application/json")


def test_defect_measurement_infinity_is_rejected_by_the_contract() -> None:
    """[F1] 결함후보 measurements 의 ``+inf`` 는 계약이 거부한다 — 원장 봉인 차단.

    다섯 모델이 자체 ConfigDict 를 재정의해 베이스의 유한성 게이트에서 빠져
    있었고, ``ge=0.0`` 은 ``inf >= 0`` 이 참이라 +inf 를 통과시켰다(실측: 접수
    503 + 원장 봉인 → 이후 정상 요청도 영구 503).
    """
    from ksi_event_contracts.defect_candidate import DefectMeasurements
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DefectMeasurements(area_px2=float("inf"))
    assert DefectMeasurements(area_px2=12.5).area_px2 == 12.5  # 비공허 대조


def test_lone_surrogate_in_mapping_keys_is_found() -> None:
    """[F2 부속] surrogate **키**도 잡는다 — 값만 보면 pydantic 의 json-mode dump 가
    그 키를 U+FFFD 로 바꿔, 생산자가 보낸 것과 **다른 키**가 원장에 남는다(조용한 오염)."""
    from ksi_core.mission_records import find_lone_surrogate_path

    assert find_lone_surrogate_path({"w\ud801eights": "v"}) is not None
    assert find_lone_surrogate_path({"weights": "v\ud801x"}) is not None
    assert find_lone_surrogate_path({"weights": "value"}) is None  # 비공허 대조


def test_edge_payload_nesting_is_capped_before_the_ledger() -> None:
    """[F3/F4] 원장이 받아 적은 payload 는 재적재·투영 경로가 반드시 읽을 수 있어야 한다.

    쓰기(json.dumps)는 사실상 무제한인데 읽기 한계는 낮다(pydantic 재적재 ~199단,
    투영 deepcopy ~500단). 상한 없이는 **201 ACK 를 준 payload 가 재기동을 영구히
    막는다** — ACK 후 Edge 는 로컬 사본을 지우므로 곧 현장 데이터 유실이다.
    """
    from ksi_core.edge_sync import _payload_depth_violation  # noqa: PLC2701

    def nest(depth: int) -> dict[str, Any]:
        value: dict[str, Any] = {"a": 1}
        for _ in range(depth):
            value = {"a": value}
        return value

    assert _payload_depth_violation(nest(199)) is not None
    assert _payload_depth_violation(nest(5000)) is not None  # 검사 자체도 재귀가 아니다
    assert _payload_depth_violation(nest(3)) is None  # 비공허 대조


def test_overflowing_progress_ratio_folds_into_a_typed_reason() -> None:
    """[F6] 진척 비율이 float 범위를 넘으면 500 이 아니라 typed 사유다.

    리포트가 원장에 남아 있는 한 조회가 영원히 500 이던 자리 — 이 함수의 계약
    ("못 내면 이유를 낸다")대로 표현 불가 구역을 사유로 접는다.
    """
    from datetime import UTC, datetime

    from ksi_event_contracts.volume_change_report import ZoneVolumeDelta

    def zone(cut: float) -> ZoneVolumeDelta:
        return ZoneVolumeDelta(
            zone_id="z1", cut_m3=cut, fill_m3=0.0, net_m3=-cut, area_m2=1.0,
            threshold_m=0.05, uncertainty_note="검증 전",
        )

    def report(cut: float, when: str) -> Any:

        # DesignConformanceReport 의 필수 필드 구성은 픽스처가 길어 여기서는 파생
        # 함수의 구역 비교 로직만 시험한다 — derive_progress 는 순수 함수라
        # 최소 속성만 갖춘 대역으로 충분하다.
        class _Report:
            def __init__(self) -> None:
                self.zones = [zone(cut)]
                self.computed_at = datetime.fromisoformat(when).replace(tzinfo=UTC)

        return _Report()

    # 실제 재현값(재조사 F6): 기준 1.001e-6 / 최신 1e308 → done/planned 오버플로.
    # derive_progress 전체를 태우려면 리포트 픽스처가 무거우므로, 여기서는 오버플로
    # 조합이 ZoneProgress 검증에서 ValidationError 를 내는 성질만 고정한다 —
    # derive_progress 의 접기 분기는 그 예외 타입 하나에 걸려 있다.
    from ksi_core.design_progress import _zone_progress  # noqa: PLC2701
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _zone_progress(zone(1.001e-6), zone(1e308), None)
    assert _zone_progress(zone(5000.0), zone(1240.0), None).cut_progress_ratio is not None


def test_auth_registry_refuses_a_principal_id_that_cannot_be_serialized() -> None:
    """[경계] 직렬화 불가한 신원은 **조립 시점**에 거부한다.

    `principal_id` 는 요청으로 조작할 수 없고 배포 설정
    (`KSI_CORE_PRINCIPAL_TOKENS_JSON`)으로만 들어온다. lone surrogate 가 섞이면 그
    신원으로 인증한 응답의 직렬화가 터져 500 이 된다 — 잘못된 설정으로 뜬 서버는
    뜨는 순간 실패해야 한다(요청 표면이 아니라 여기가 막을 자리인 이유).
    """
    from ksi_core.auth import AuthRegistryError

    with pytest.raises(AuthRegistryError, match="UTF-8"):
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"t").hexdigest(),
                    principal=Principal(
                        principal_id="op-\ud800-1",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                    ),
                )
            ]
        )


def test_auth_registry_still_accepts_a_normal_principal_id() -> None:
    """[비공허 대조] 정상 신원은 그대로 조립된다 — 과잉 거부가 아니다."""
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"t").hexdigest(),
                principal=Principal(
                    principal_id="운영자-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    assert registry is not None
