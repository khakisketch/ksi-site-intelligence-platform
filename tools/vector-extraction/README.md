# tools/vector-extraction

Golden test vector 추출 스크립트 (P0-3). `packages/test-vectors/vectors/` 아래
`legacy_compat/`(참고 구현 실행 캡처)와 `ksi_correctness/`(해석적 진리)를 채운다.

## 왜 `tools/`인가 (가드 정책)

`docs/product/DOMAIN_INVARIANTS.md` INV-003과 `AGENTS.md` 는 `references/repos/` 를
runtime 코드에서 직접 import 하는 것을 금지하고, `scripts/check_no_reference_imports.sh`
가 그 4중 가드(import/manifest/symlink/dirty)를 CI에서 상시 강제한다. 그 가드의
`CODE_DIRS`(검사 대상)는 `apps services edge workers packages tests` 뿐이다 —
`tools/` 는 의도적으로 제외되어 있다.

**이 디렉토리는 그 예외 지점이다.** 골든 벡터를 "손 전사"하지 않고 참고 구현을
**실제로 실행**해 입력→출력을 캡처하려면(대표자 반영사항 8, 손 전사 금지) 어딘가는
`references/`를 import 해야 한다 — `packages/`나 `tests/` 안에서 그렇게 하면 가드
위반이지만, `tools/vector-extraction/` 은 "1회성 추출 스크립트" 전용 디렉토리로
가드 예외 목록에 있어 여기서는 허용된다. 이 스크립트들이 만든 **산출물**(JSON
벡터)만 `packages/test-vectors/`(가드 대상 디렉토리)에 들어가고, 그 JSON은 순수
데이터라 참고 코드에 대한 런타임 의존이 전혀 없다.

## 재추출 방법

### Scout GeoProjector → `legacy_compat/geo_projection.json`

원 구현: `references/repos/ksi-scout/ksi_scout/geo/projection.py` (`project_foot_point`,
`LiveGeoProjector`) — numpy/pydantic/shapely 만 필요(ultralytics/opencv 등 Scout 본체
의존성은 이 벡터 캡처엔 불필요). **repo 루트의 `pyproject.toml`/`uv.lock` 은 건드리지
않는다** — 스크래치패드에 별도 임시 venv를 만든다.

```bash
uv venv --python 3.12 /path/to/scratch/.venv-scout
uv pip install --python /path/to/scratch/.venv-scout/bin/python numpy pydantic shapely
/path/to/scratch/.venv-scout/bin/python tools/vector-extraction/capture_scout_projection.py
```

### Platform proximity-distance.ts → `legacy_compat/proximity_distance.json`

원 구현: `references/repos/ksi-platform/ksi-safety/src/lib/proximity-distance.ts` —
이 파일 → `proximity.ts` → `safety-zone.ts` 체인은 순수 TS/JS로 next/react/zod 등
런타임 npm 의존이 전혀 없어, `ksi-safety/node_modules` 설치 없이 `tsx` 단독으로
실행된다. `@/*` path alias 해석을 위해 참고 레포 **자체의**
`ksi-safety/tsconfig.json`(읽기만, 수정 없음)을 `--tsconfig` 로 넘긴다.

```bash
cd tools/vector-extraction
npx -y tsx --tsconfig ../../references/repos/ksi-platform/ksi-safety/tsconfig.json \
  capture_platform_proximity.mts
```

### Platform zone-intrusion.ts → `legacy_compat/zone_intrusion.json`

원 구현: `references/repos/ksi-platform/ksi-safety/src/lib/zone-intrusion.ts`. 실행
방법은 위와 동일(같은 tsconfig, 같은 의존 체인).

```bash
cd tools/vector-extraction
npx -y tsx --tsconfig ../../references/repos/ksi-platform/ksi-safety/tsconfig.json \
  capture_platform_zone.mts
```

### `ksi_correctness/*.json` (해석적 진리)

`geo_projection_analytic.json`/`polygon_point_membership.json`/`enu_wgs84_roundtrip.json`
은 어느 참고 구현도 실행하지 않는다 — 삼각비·등장방형 좌표변환의 역함수 관계처럼
손으로 유도 가능한 항등식을 스크래치패드의 1회성 계산(파이썬 표준 `math` 모듈)으로
평가해 반올림 실수를 피했을 뿐, 값의 "정답"은 각 파일의 `derivation_basis` 필드에
적힌 수학적 근거에서 나온다(재실행용 영속 스크립트가 없는 이유이기도 하다 — 재현하려면
`derivation_basis`의 공식을 그대로 다시 평가하면 된다).

## 벡터 ↔ 원천 매핑

| 벡터 파일 | 카테고리 | 원천 repo | 원천 파일 | 커밋 |
|---|---|---|---|---|
| `geo_projection.json` | legacy_compat | ksi-scout | `ksi_scout/geo/projection.py` | `42ccc0db` |
| `proximity_distance.json` | legacy_compat | ksi-platform | `ksi-safety/src/lib/proximity-distance.ts` | `030ebd5a` |
| `zone_intrusion.json` | legacy_compat | ksi-platform | `ksi-safety/src/lib/zone-intrusion.ts` | `030ebd5a` |
| `telemetry_interpolation.json`* | legacy_compat | ksi-scout | `ksi_scout/dal/sync.py` | `42ccc0d…` |
| `geo_projection_analytic.json` | ksi_correctness | — (analytic) | — | — |
| `polygon_point_membership.json` | ksi_correctness | — (analytic) | — | — |
| `enu_wgs84_roundtrip.json` | ksi_correctness | — (analytic) | — | — |

\* `telemetry_interpolation.json`과 그 추출 스크립트(`capture_scout_sync.py`)는 다른
워커 소유 — 표는 완결성을 위해 참고만 싣는다.

커밋 핀은 `references/repos/{ksi-scout,ksi-platform}` 서브모듈의 현재 체크아웃
커밋이며, `scripts/verify_reference_pins.sh` 로 확인할 수 있다. 참고 레포가
`UPDATE_REFERENCE_PIN` 태스크로 새 커밋으로 이동하면, 위 재추출 명령을 다시 돌려
`legacy_compat/` 벡터를 새 커밋 기준으로 갱신하고 이 표의 커밋 열도 함께 갱신한다.
`ksi_correctness/` 는 참고 레포 커밋과 무관하므로 재추출 불필요.
