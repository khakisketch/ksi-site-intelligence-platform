# AOL-3 Unit 1 — 지형추종 고도 계획기 설계

- 상태: 대표자 승인(2026-08-15, 대화 중 "다 진행해줘"로 확정 — 세부 판단은 위임됨)
- 관련: `docs/architecture/ADR-KSI-019-autonomous-observation-loop.md`(§3 D2·D3, §4 G6),
  `tests/contract/test_anti_circularity_gate.py`

## 배경

ADR-KSI-019 §5는 AOL-3(지형 인지 경로계획)을 "실제 현장 검증 이후에만 착수"로 순서를
고정해뒀다. 대표자가 2026-08-15 대화에서 이 순서를 의도적으로 깨고 지금 바로 착수하기로
결정했다 — 실기 검증이 어려운 부분도 미리 개발해두고, 실제 기체 연동 시점에 검증·보정하는
전략. 이 스펙은 AOL-3의 5개 하위 기능(지형추종·구조물이격·장애물인지·데이터부족 적응촬영·
동적재계획) 중 **첫 번째, 지형추종(고도 계산)**만 다룬다 — 대표자가 이 순서를 명시적으로
지정했다("나머지 넷의 기반이 되는 가장 작은 단위").

## 목표

공간모델(DTM/DSM)을 입력받아, 계획된 XY 경로의 각 지점에서 **안전한 지형추종 비행고도**를
계산하는 순수 계획 계층을 만든다. **실제 기체 제어·KMZ 발급·비행 실행은 이 범위에 없다** —
계산기 자체를 먼저 결정론적으로 증명한다.

## 조사로 확인한 사실 (재구현 금지 대상)

- **DTM은 이미 실제로 생성된다.** `services/processing-controller/src/ksi_processing_controller/odm_assets.py`
  가 NodeODM 산출물 중 `odm_dem/dtm.tif` 를 `ProcessingArtifactKind.DTM` 으로 등록한다
  (`odm.py:plan_artifacts()`, 실제 파이프라인 경로). enum 뿐인 미사용 값이 아니다.
- **단일 지점 표고 샘플링 유틸은 없다.** `packages/geo-spatial/src/ksi_geo_spatial/vertical.py`
  의 `GeoidGrid.height_at(*, lat_deg, lon_deg)` 가 유일한 선례다 — 지오이드 격자를
  bilinear 보간하고, 격자 범위 밖이면 값을 지어내지 않고 실패한다(`GeoidUnavailableError`).
  이 패턴을 그대로 복제한다.
- **`packages/mission-planning` 은 Core의 공간모델 코드를 import할 수 없다** — 빌드 게이트로
  강제됨(`tests/contract/test_anti_circularity_gate.py::test_mission_planning_package_does_not_import_spatial_model_modules`,
  `ksi_core.processing_jobs`·`ksi_core.spatial_model`·`processing_artifact`·`point_cloud`
  문자열이 있으면 실패). 새 모듈은 표고값을 **미리 읽어온 데이터**로만 받아야 한다.
- **고도는 지금 임무 전체에 단일 스칼라다.** `coverage.py`의 `lawnmower_route`/`perimeter_route`
  는 `altitude_m` 하나를 모든 웨이포인트에 동일하게 찍는다. `wpml.py`의 `_validate_route()`
  는 웨이포인트 간 고도가 다르면 `KmzBuildError` 로 **적극적으로 거부한다**(전역 높이 전략만
  지원, per-point 고도는 ellipsoid height 계산이 필요한데 그 계산이 없다는 이유). 이 스펙은
  `wpml.py` 를 건드리지 않는다 — 그건 후속 Unit이다.
- **웨이포인트 간 고도변화율 제한은 전혀 없다.** `WaylineParams` 는 수평 속도·이륙고도만
  갖고 있다.
- INV-014(150m 상한)는 `FlightEnvelope.max_altitude_m` 필드 자체의 상한으로 이미 강제된다
  — 이 계획기의 출력도 결국 그 봉투 안에서 검증돼야 한다.

## 아키텍처

```text
DTM/DSM GeoTIFF (Core 가 이미 갖고 있음, job/artifact 경유)
        │  (이 스펙 범위 밖 — 아직 소비자가 없어 배선하지 않는다)
        ▼
TerrainGrid.elevation_at(lat_deg, lon_deg)      ← packages/geo-spatial (신규 terrain.py)
        │  웨이포인트별 지형고도 배열 (계산 불가 지점은 None)
        ▼
compute_altitude_profile(...)                    ← packages/mission-planning (신규 terrain.py)
        │  웨이포인트별 (지형고도·계획고도·여유값·상태)
        ▼
TerrainAltitudeProfile                            ← 이 스펙의 최종 산출물(순수 데이터)
```

### 컴포넌트 1 — `packages/geo-spatial/src/ksi_geo_spatial/terrain.py` (신규)

`GeoidGrid` 와 동형이다. 책임: DTM 또는 DSM GeoTIFF 파일 경로를 열어, 임의의 위경도 지점의
표고를 bilinear 보간으로 읽는다.

```python
@dataclass(frozen=True, slots=True)
class TerrainGrid:
    """단일 표고 래스터(DTM 또는 DSM) — GeoidGrid 와 동일한 계약."""
    # array, transform, crs, bounds — GeoidGrid 내부 표현과 동형

    @classmethod
    def from_path(cls, path: Path) -> TerrainGrid: ...

    def elevation_at(self, *, lat_deg: float, lon_deg: float) -> float | None:
        """범위 밖이거나 그 지점이 nodata 면 None — 지어내지 않는다."""
```

- CRS 처리는 `ksi_geo_spatial.crs.normalise_crs`/`assert_supported_project_crs` 를 그대로 쓴다.
- `GeoidGrid` 와 달리 **전역 싱글턴 로더는 두지 않는다** — DTM/DSM 은 현장마다 다른 파일이라
  지오이드 격자(고정 1개 파일)와 성격이 다르다. 호출자가 `TerrainGrid.from_path()` 로 그때그때
  연다.

### 컴포넌트 2 — `packages/mission-planning/src/ksi_mission_planning/terrain.py` (신규)

순수 함수. Core·스토리지·파일 경로를 전혀 모른다 — 이미 샘플링된 숫자만 받는다.

```python
@dataclass(frozen=True, slots=True)
class WaypointTerrainSample:
    waypoint: GeoPoint             # 기존 ksi_mission_planning.geometry.GeoPoint 재사용
    terrain_elevation_m: float | None   # DTM 샘플. None = 그 지점 표고를 모른다.
    surface_elevation_m: float | None = None  # DSM 샘플(선택). 있으면 이격 계산에 쓴다.


class AltitudeSegmentStatus(StrEnum):
    OK = "OK"
    TERRAIN_DATA_MISSING = "TERRAIN_DATA_MISSING"        # 해당 지점 지형고도 없음
    ENVELOPE_VIOLATION = "ENVELOPE_VIOLATION"             # 봉투 [min,max] 밖
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"           # 이웃 지점 대비 고도변화율 초과


@dataclass(frozen=True, slots=True)
class WaypointAltitudePlan:
    waypoint: GeoPoint
    terrain_elevation_m: float | None
    commanded_altitude_m: float | None    # 지형고도 + target_agl_m, 상태가 OK 일 때만 값이 있다
    clearance_m: float | None             # commanded_altitude_m - surface_elevation_m (DSM 없으면 None)
    status: AltitudeSegmentStatus
    rationale: tuple[str, ...]            # reobservation.py 관례 그대로 — 근거 없는 자동판정 금지


@dataclass(frozen=True, slots=True)
class TerrainAltitudeProfile:
    segments: tuple[WaypointAltitudePlan, ...]
    provenance: str                       # 호출자가 넘긴 근거 문자열(예: epochJobId) — 그대로 통과
    all_ok: bool                          # 모든 세그먼트가 OK 인지 — 호출자가 즉시 판단 가능


def compute_altitude_profile(
    *,
    samples: Sequence[WaypointTerrainSample],
    target_agl_m: float,
    safety_margin_m: float,
    max_altitude_change_ratio: float,   # 수평거리 대비 최대 고도변화 비율 (아래 "판단" 참조)
    envelope: FlightEnvelope,
    provenance: str,
) -> TerrainAltitudeProfile: ...
```

**계산 규칙:**

1. `terrain_elevation_m is None` → 그 세그먼트는 `TERRAIN_DATA_MISSING`, `commanded_altitude_m
   = None`. 이웃 지점 값으로 보간·추정하지 않는다(지어내지 않는다 원칙).
2. 그 외: `commanded_altitude_m = terrain_elevation_m + target_agl_m + safety_margin_m`.
3. `commanded_altitude_m` 이 `[envelope.min_altitude_m, envelope.max_altitude_m]` 밖이면
   `ENVELOPE_VIOLATION`(INV-014 를 이 계층에서도 존중 — 최종 게이트는 여전히
   `mission_plans.py`/`FlightEnvelope` 이지만, 계획 단계에서 이미 불가능한 값을 보여주지
   않는다는 점에서 `reobservation.py` 의 클램프 철학과 동형이다. 여기서는 클램프하지 않고
   **거부만** 한다 — 지형 때문에 봉투를 넘는 고도가 필요하다는 사실 자체가 사람이 봐야 할
   신호라서, 조용히 깎으면 그 신호가 사라진다).
4. `surface_elevation_m` 이 있으면 `clearance_m = commanded_altitude_m - surface_elevation_m`.
   없으면 `None`(값을 0이나 임의값으로 채우지 않는다).
5. 인접한 두 세그먼트 사이 `|Δ고도| / 수평거리(m)` 가 `max_altitude_change_ratio` 를 넘으면
   뒤 세그먼트가 `RATE_LIMIT_EXCEEDED`.

### 판단: 고도변화율을 왜 "수평거리 대비 비율"로 표현하는가

기존 코드 어디에도 상승·하강률(m/s) 제약이 없고, 이 계층은 속도 데이터를 갖고 있지 않다
(`WaylineParams.autoFlightSpeedMs` 는 수평 속도다). 시간 기반 제약을 흉내 내려면 속도 가정을
새로 지어내야 하는데, 이는 "지어내지 않는다" 원칙과 충돌한다. 대신 **기하학적으로 검증
가능한 값**(수평거리 대비 고도변화 비율)으로 표현한다 — ADR-KSI-011 D3 의 "측면 간격이
고도×1.5 를 넘을 수 없다" 와 같은 지위의 **정책값**이다(물리 증명이 아니라 보수적 시작점).
호출자(장래의 Unit)가 실제 상승률 제약을 붙이고 싶으면 웨이포인트 간격과 속도로 시간을
역산해 이 비율로 변환하면 된다 — 이 계층이 시간 개념을 갖지 않아도 된다.

## 명시적 범위 밖 (지금 하지 않는다)

- 실제 DJI 비행 명령 활성화, FlyTo/웨이포인트 실행.
- Point Cloud 기반 장애물 회피(Unit 3).
- 임무 중 동적 재계획(Unit 5).
- `wpml.py`/`coverage.py` 변경 — 이 산출물을 실제 KMZ 발급 경로에 잇는 것은 후속 작업이다
  (그 시점에 `useGlobalHeight=0`·ellipsoid height 계산이 별도로 필요하다 — `wpml.py` 자체
  docstring이 이미 그 한계를 적어뒀다).
- Core 쪽 배선(현장의 공간모델을 찾아 DTM 을 내려받아 이 두 함수에 먹이는 것) — 아직 이
  산출물을 쓸 소비자(화면·API)가 없어 배선하지 않는다. 필요해지면 별도 계획.

## 테스트

`tests/contract/test_terrain_altitude_planner.py` (신규, 결정론적 순수 함수 — 서버 조립
불필요):

- 지형고도 있는 정상 경로 → 전 구간 `OK`, `commanded_altitude_m` 이 예상대로 계산됨.
- 특정 지점 `terrain_elevation_m=None` → 그 지점만 `TERRAIN_DATA_MISSING`, 이웃 지점은 영향
  없음(보간해서 채우지 않는다).
- 계산된 고도가 봉투 상한/하한을 넘음 → `ENVELOPE_VIOLATION`, 근거 문장에 실제 초과값 포함.
- 인접 지점 간 고도 변화가 비율 상한을 넘음 → `RATE_LIMIT_EXCEEDED`.
- `surface_elevation_m` 없음 → `clearance_m is None`(0 이나 다른 값으로 채워지지 않음).
- `surface_elevation_m` 있음 → `clearance_m` 이 정확히 계산됨.
- `provenance` 문자열이 입력 그대로 출력에 실린다(계산에 관여하지 않는다).
- `TerrainAltitudeProfile.all_ok` 가 전 세그먼트 OK 일 때만 참.

`packages/geo-spatial` 쪽 `TerrainGrid` 도 별도 유닛 테스트(실제 작은 GeoTIFF 로 bilinear
보간·범위 밖 실패를 확인 — `GeoidGrid` 테스트 관례를 그대로 따른다).

## 자기 검토

- 자리표시자 없음. 모든 필드·함수 시그니처가 구체적이다.
- 범위 밖 항목을 명시해 스코프가 새지 않게 했다.
- ADR-KSI-019 D3(반순환 불변식)과 정합 — 이 유닛은 공간모델을 **선택 입력**으로도 안 받는다
  (아예 안 받는다, Core 배선이 없으므로) — 나중에 배선이 붙어도 "선택적 강화"라는 원칙을
  자연히 지킨다.
