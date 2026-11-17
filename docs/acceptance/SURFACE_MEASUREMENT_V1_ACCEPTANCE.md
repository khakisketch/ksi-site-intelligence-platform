# Surface measurement v1 — Acceptance target

- Status: TARGET / SOFTWARE_ONLY / CUSTOMER_NOT_EVALUATED.
  순수 단면 계산·계약·로컬 계산 어댑터·단일 subject HEIGHT 판정·저장 선과
  단면 작업의 Core 요청자/일꾼 HTTP·명시적 opt-in 조립이 구현되어 있다.
  단면 일꾼 실행기(`run_once`: 원본 capability로 받은 바이트 대조, 파일 사실 재대조, 한도 있는 계산, receipt 보고)가 있다.
  서명된 설정으로 폴링하는 상시 실행 진입점(`surface_profile_service`)이 있다.
  Console에는 읽기 전용 단면 화면(`/sites/{id}/measurements`)이 있다. 선 그리기·저장, 단면 요청, 두 시점 차이,
  OS 수준 격리·Core 운영 활성화·CLI·MCP 단면 도구는 아직 없다.
  이 상태는 EXT-VAL-01..08이나 P-AC-01..06을 변경하지 않는다.
- Authority: PRODUCT_CONSTITUTION; MASTER_PRD v3.0 (external technology adoption boundary);
  DOMAIN_INVARIANTS; `docs/superpowers/product-state.md`.
- Invariants: INV-017/018/020/023/024/040/050/051/053/060.
- Owner of the first slice: a saved **line** read on one or two registered surfaces (DSM/DTM GeoTIFF),
  then the same line on the next observation.

## Why this exists

Customers who compare observations over one site expect basic measurement tools — pick a place on the
map, read the heights along it, compare two dates, export the numbers. Agent integration does not
replace those tools; it uses the same ones. This target defines the first of them so that Console, API,
CLI and MCP return the same result with the same limits.

## Scope

- Point and line **surface profile** on one registered DSM/DTM: horizontal distance along the line
  (m, planar in the raster's projected CRS) and surface elevation (m).
- **Two-surface profile comparison**: the same line and sample positions read from two exact registered
  surfaces; difference = current − baseline.
- A saved **measurement feature** (line, later point/polygon) bound to a work area, with immutable
  geometry revisions. A new revision never rewrites an earlier result.
- Result export (CSV) and Console graph linked to a map position.

## Non-scope (separate input, acceptance and decision required)

- Volume from a line. A line has no area; cut/fill is a polygon/zone calculation (existing masked and
  single-volume paths), and cross-section area or corridor/multi-section earthwork tables need their own
  geometry and calculation contract.
- Design-surface profile or progress-to-design, grade/surface length, contours, DXF output, point cloud,
  mesh/3D, ground (DTM) extraction from a DSM.
- Any survey, settlement, progress or field-accuracy claim. A profile is the height of this grid along
  this line; it is not a measured accuracy.

## What each number means

| Value | Meaning | Never |
|---|---|---|
| distance (m) | planar distance along the polyline after projection to the raster CRS | surface length, geodesic length |
| elevation (m) | bilinear value at pixel centres of the exact registered grid | a surveyed height, an interpolated guess across NoData |
| difference (m) | current − baseline at identical sample positions, only where both are known | zero when either side is unknown |
| unknown | outside surface, within half a cell of the edge (no extrapolation), or NoData/non-finite neighbour | `0`, a neighbour value, a straight line across the gap |

## Acceptance criteria (target, not yet satisfied end to end)

| ID | Criterion | Evidence needed | Current status |
|---|---|---|---|
| SM-AC-01 | Heights and distances match analytical ground truth on synthetic surfaces; reprojection from WGS84 agrees with the projected line | local synthetic contract tests; later an independent reference (GDAL/QGIS) on the same samples | primitive: local synthetic pass |
| SM-AC-02 | Unknown stays unknown: outside, edge band, NoData sentinel, NaN, and one-sided unknown in a comparison never become a number or `0` | contract tests | primitive: local synthetic pass |
| SM-AC-03 | Reads are bounded by policy: single read window, source storage-block size, vertices, samples, line length; over-limit input is refused, never coarsened silently | contract tests; worker-level time, memory, cancellation and concurrency limits | 순수 계산의 창·블록·정점·표본·길이 및 HTTP 본문 한도 통과; C3 워커 시간·메모리·취소·동시성 한도는 미구현 |
| SM-AC-04 | A request is bound to exact asset ID, submission, revision and digest; comparison runs only after the existing Core preflight (INV-053: processing profile, CRS, vertical reference, lineage) and returns typed blockers otherwise | Core route and replay tests | 단일 DSM의 job/input/receipt 정확한 결속·Core HTTP·완료 재생 통과; 두 시점 차이 경로는 미구현 |
| SM-AC-05 | Saved line geometry is revisioned; editing creates a new revision, old results stay bound to the old one; the same line is reusable for the next observation with a new request and result | contract and persistence tests including restart and duplicate request | 저장 선·결과의 exact revision 결속, 편집 뒤 과거 결과 유지, 멱등·작업 재생 통과; 두 시점 비교 흐름은 별도 |
| SM-AC-06 | Rights and egress: no read, CSV or agent response widens the caller's current site/work-area permission or AI-egress consent; exports carry no credentials or signed URLs | permission, revocation and egress tests | Core HTTP의 현재 grant·HEIGHT 정책 철회와 자격 재확인 통과; MCP 단면 접근은 거부, CSV·AI-egress 경로는 미구현 |
| SM-AC-07 | Console, API, CLI and MCP return the same input revision, result ID, values and unknown reasons | cross-surface contract test | not implemented |
| SM-AC-08 | A field user completes draw → read graph → change date → export in the real browser at 390/768/1280/1440px and 200% zoom, with keyboard and touch, stale values withdrawn on input change, and no write request from selection alone | real-browser test; later unaided task test with field staff | read graph / change date / CSV export / keyboard: implemented in a read-only Console view and checked at 390 and 1440 px against a stand-in Core; draw, 768/1280 px, 200% zoom, touch and the unaided field test not done |
| SM-AC-09 | Real customer data: the P-AC customer sample (same work area, t0/t1/t2 DSM, intended lines, CRS/vertical/quality evidence, usage rights) read with an independent reference comparison | customer-approved data and independent review | not evaluated |

## Decision: two-epoch difference gate (2026-11-17, user)

The difference between two dates' profiles is opened under the **same standard as RELATIVE_VOLUME**:
a new pair use (`PROFILE_DIFFERENCE`, no zone) that needs per-epoch independently attested evidence
for the measured DSM and a Core compatibility authority (INV-053). It is not derived from inspection
reports alone. Consequence to state plainly: the production compatibility authority port is
default-closed today, so the difference stays BLOCKED (per-date height profiles still shown) until a
mapping source and independent evidence are approved, exactly as for relative volume.

**HEIGHT (single subject) is open as of 2026-11-17.** Core now issues an ELIGIBLE `HEIGHT` decision
when the current policy permits it, the inspection report binds the exact subject/policy, and a MEASURED
single-band Float32/Float64 DSM carries a parser-observed vertical reference. A missing DSM, wrong
profile, missing vertical reference, absent policy or withdrawn inspection is a typed blocker; no unit is
guessed from the horizontal axis. HEIGHT binds no display receipt, evidence, zone or compatibility mapping
and is **not** a quantitative, comparability, accuracy or customer-acceptance claim. Decisions made before
this change keep their retained `HEIGHT_PRODUCT_DEFINITION_UNRESOLVED` blocker and are never rewritten.
단일 subject 판정으로 유지된다. C2c는 이 판정을 재확인하는 작업 HTTP와 완료 검증을 제공하지만, 실제 파일을 읽는 C3 워커와 운영 활성화는 아직 제공하지 않는다.

**Declared vertical reference (decided 2026-11-17; ledger, HEIGHT and profile consumers implemented
2026-11-18, no Console yet).** Most DSM exports carry no
vertical CRS, so their heights could never be read. A person who knows the basis may declare it for one
registered DSM (asset), so a single-surface height or profile read can proceed. The declaration is a claim,
never an observation: it has its own append-only record (`vertical-reference-declaration.v1`), keyed by asset
and not part of the submission or any recorded decision, so no existing digest changes. Heights are metres
only; the datum is the closed platform vocabulary, not free text; a correction or withdrawal is a new record.
A file that carries its own vertical reference needs no declaration and one is refused. A declared basis never
feeds quantitative comparison, relative volume or analysis readiness, which keep reading the observed value
only (INV-017, INV-020, INV-053), and no result may call a declared basis observed or accurate (INV-024,
INV-040). Implemented: the append-only ledger and its read/declare/withdraw routes (WORK_ORDERS_WRITE to
write), the HEIGHT decision accepting a current declaration only when the file carries no vertical reference
(decision issue, current re-proof and historical verification, the latter as of the decision time), and a
profile job that freezes the provenance (`OBSERVED` or `DECLARED` with the declaration record digest). The
worker receipt repeats it and Core refuses a receipt that changes it. A job frozen on a declaration continues
only while that exact record is current; a correction or withdrawal closes new reads and withholds the
numbers. A test pins that only the assembly imports the ledger, so comparison, volume and readiness stay on
the observed value. Still absent: any Console screen to declare or to show the "declared" label next to the
numbers, and the export marking. Until those land, a declared read must not be offered to users.

## Boundaries

A passing local synthetic test, a green software matrix or an exported CSV is not customer, field,
accuracy, settlement or deployment acceptance. Reading a surface is separate from file inspection,
suitability for a use, quantitative analysis, accuracy evaluation and human review.

## Evidence log

| Date | Evidence | Scope |
|---|---|---|
| 2026-11-16 | `packages/geo-spatial/src/ksi_geo_spatial/surface_profile.py`; `tests/contract/test_geo_spatial_surface_profile.py` (39 tests; ten injected defects — NoData as valid, edge extrapolation, out-of-surface read, nearest-neighbour sampling, inverted difference, no window limit, no block limit, missing vertices, mixed plans, ignored scale — were each detected) | pure primitive only; synthetic grids; no contract, Core, worker, UI, API, CLI or MCP |
| 2026-11-17 | `contracts/schemas/measurement-feature.v1.json`, `surface-profile.v1.json` (generated by `tools/generate_surface_profile_schemas.py --check`); `tests/contract/test_surface_profile_contracts.py` (41 tests, ten injected defects detected); `services/processing-controller/.../surface_profile_worker.py` + `tests/contract/test_surface_profile_worker.py` (8 tests; nine injected defects, including a reversed line, detected) | request/result shapes and a local adapter over an already-authorised raster path; synthetic grids only; no Core route, grant, egress or storage wiring |
| 2026-11-17 | 경계값 보정: 극소 표본 간격·극소 선·계약 상한 초과·복소수 래스터·복합 CRS(m 수직 성분만)·표본 null/사유 wire 스키마 (`test_geo_spatial_surface_profile.py` 46, `test_surface_profile_worker.py` 13, `test_surface_profile_contracts.py` 48개; 주입 결함 7개 중 6개 검출, 복합 CRS 성분 개수 방어 분기는 시험으로 도달시키지 못함) | 순수 계산·계약·로컬 어댑터만. 수직 성분은 선언 사실로 보존할 뿐 호환성 판정이 아님 |
| 2026-11-17 | HEIGHT 판정: `external_use_evaluator.py`(발급·이력 재검증), blocker 카탈로그·대시보드 사본 동기화; `test_external_use_evaluator.py` +13개(허용·블로커 6종·ORTHO-only·재시작 replay·변조 거부·DISPLAY 불변; 주입 결함 6개 검출) | 합성 정책·보고서. 관련 시험 176 통과, 사전부터 있던 7 실패(macOS에서 실제 GeoTIFF 검사기 필요)는 변경 전후 동일. 단면 실행 경로는 없음 |
| 2026-11-17 | 저장 선(C1): `domains/sites/measurement_features.py`(원장·멱등·재생)·REST 6개(`/v1/sites/{site}/work-areas/{area}/measurement-features…`)·OpenAPI·`measurement-feature.v1` 보기 모델·OIDC 범위 운영자 허용목록 6항목; `test_measurement_features.py` 30개(주입 결함 9개 중 8개 검출 후 서명 누락 재생 시험 추가) | 합성 조직/현장/영역. 읽기/쓰기는 부모 영역의 현재 범위가 상한이며 어떤 표면 읽기 권한도 만들지 않는다. 단면 실행 경로는 아직 없음 |
| 2026-11-17 | 실행 전 확인(C0): `surface_profile.profile_support_blocker` — 검사 보고서 사실만으로 이 엔진이 읽을 수 있는지(수평 CRS 화이트리스트·북향 격자·단일 밴드 실수형·관측된 수직기준). HEIGHT 허용이 EPSG:3857·회전 격자도 통과시키던 차이를 읽기 전에 거른다(`test_geo_spatial_surface_profile.py` +10개, 실제 읽기와의 일치 시험, 주입 결함 4개 검출) | 보고서는 파일의 증거가 아니다 — 읽는 쪽이 파일 사실을 다시 확인해야 한다. Core 경로에는 아직 연결되지 않음 |
| 2026-11-17 | 단면 작업(C2a): `surface_profile_job.py`(동결 입력·정책·런타임·attempt·receipt·보기 계약, `surface-profile-job.v1.json`)와 `surface_profile_jobs.py`(발급·멱등·할당량·lease/fence·검증된 완료·재시도·취소·만료·재생·결과 릴리스); 완료 검증은 Core가 계획을 다시 계산하고(`plan_surface_profile`) 기하만으로 알 수 없는 표본을 `locate_profile_samples`로 대조한다; `test_surface_profile_jobs.py` 53개 + `test_surface_profile_job_contracts.py` 41개(주입 결함 33개 중 31개 검출, 2개는 다른 검증과 중복되는 방어 분기) | 인메모리 권한 포트와 실제 계산을 쓴 합성 시험. 실제 권한 포트(자료·grant·HEIGHT 판정 연결)·워커 HTTP API·워커 프로세스는 아직 없다 |
| 2026-11-17 | 단면 권한 포트(C2b): `surface_profile_authority.py`가 자료(`SpatialDataSourceResolver`)·grant(PREPARE/READ를 **실제 읽을 셀 창** 기준으로)·저장 선·HEIGHT 판정의 현재성(`ExternalUseEvaluator.height_blocker_now`)·엔진 지원 범위(`profile_support_blocker`)·일꾼 activation을 발급과 모든 전이에서 다시 묻는다; 선이 표면에 닿지 않으면 `LINE_OUTSIDE_SURFACE`로 거부; `test_surface_profile_authority.py` 30개(주입 결함 12개 모두 검출) + evaluator +2개 | 소유자는 좁은 가짜로 대체한 시험. 실제 소유자와의 통합·HTTP 라우트·워커 프로세스는 아직 없다 |
| 2026-11-17 | 단면 Core HTTP(C2c): 전용 요청자·일꾼 라우트, 명시적 조립·전용 원장·OpenAPI, 일반 클라이언트와 scoped operator 허용목록을 MCP와 분리. pending은 jobId만, input은 활성 instance와 현재 attempt digest에 결속. 완료 재생 때 receipt·정확한 lease·표본 계획을 재검증하고 다른 일꾼의 복사 attempt 사용을 거부. `test_surface_profile_api.py`·`test_surface_profile_worker_api.py`·`test_surface_profile_assembly.py`·`test_surface_profile_http_integration.py`와 인접 단면 시험 314개 통과, 기존 native/auth 회귀 131개 통과. 실제 소유자 loopback HTTP 10개에 grant·HEIGHT 정책 철회, activation 만료, 편집 후 과거 revision 결과 유지 포함. 린트·스키마 동기화·모듈 경계 통과, mypy는 변경 전과 동일한 Linux 전용 오류 12건. 전체 pytest는 macOS에서 Linux 전용 `lgetxattr` import 수집 오류 3건으로 중단됐으며, 깨끗한 변경 전 HEAD에서도 동일하게 재현됨 | 실제 site·등록 DSM·검사 원장·저장 선·grant·HEIGHT evaluator·AuthRegistry를 연결. TIFF parser entrypoint는 프로세스 안에서 실행하며 Linux UDS/격리는 검증하지 않음. storage/currentness는 로컬 시험 backend, 결과·receipt 제출도 시험 일꾼이 수행. Core는 픽셀 높이 자체를 독립 재계산하지 않으며 C3·운영·두 시점 차이·고객/현장 수락의 증거가 아님 |
| 2026-11-17 | 단면 일꾼(C3 1단계): Core 입력이 활성 instance·현재 attempt digest를 증명한 뒤 lease·작업 기한·grant·활성화 중 가장 이른 만료의 원본 읽기 capability를 발급하고, 발급 뒤 요청자·권한을 다시 증명(`surface_profile_worker_api.py`). 일꾼 `surface_profile_core_client.py`·`surface_profile_runner.py`는 받은 바이트의 길이·SHA-256을 봉인 값과 대조하고, 읽은 파일 사실(폭·높이·해상도·CRS)을 봉인된 측정값과 다시 대조한 뒤에만 계산해 receipt를 보고. 계산 거부는 같은 이름의 사유로 작업을 실패시키고, 저장소 연결 장애만 재시도 대기로 돌림. `test_surface_profile_runner.py` 8개(주입 결함 4개 검출: 폭·해상도·CRS 대조 제거, 거부 처리 제거), `test_surface_profile_worker_api.py` +3개, 실제 소유자 loopback 통합 +1개(봉인 DSM 바이트를 rasterio 이중선형 독립 기준과 비교). 관련 회귀 467개 통과, 린트 통과, mypy는 변경 전과 동일 | 일꾼은 프로세스 안에서 계산하며 OS 격리·시간·메모리·동시성 한도는 증명하지 않음(SM-AC-03 일꾼 한도 미완). 객체 저장소는 loopback 대역이며 서명·만료·철회는 실제 저장소로 검증하지 않음. 상시 실행 진입점과 운영 설정은 없음. 정확도·고객 수락의 증거가 아님 |
| 2026-11-17 | 단면 일꾼 상시 실행(C3-2): `surface_profile_worker_config.py`(운영자가 고정한 Ed25519 키의 분리 서명 `ksi-surface-profile-activation.v1`, 철회·유효 기간, 유한 예산, 소유자 전용 파일, 환경 자격 없음)와 `surface_profile_service.py`(매 Core 호출 전 설정을 다시 읽어 철회·교체 반영, 자격 파일 재읽기, `--once`). `test_surface_profile_worker_config.py` 22개(서명 대상 분리·철회·만료·예산 시험, 주입 결함 4개 검출), `test_surface_profile_service.py` 4개(서명 설정으로 작업 완료, 시작 뒤 철회 시 lease 전 호출 중단, 자격 파일 보호 상실 시 중단, 환경 자격 무시). 관련 시험·린트 통과, mypy는 변경 전과 동일 | 일꾼은 여전히 프로세스 안에서 계산하며 OS 격리·시간·메모리·동시성 한도는 증명하지 않음. 기존 native 일꾼의 격리는 Linux 전용이라 이 호스트에서 검증하지 못함. Core 운영 활성화(서명된 단면 activation 로드)는 없음 |
| 2026-11-17 | Console 읽기 전용 단면 화면(PR-A): `apps/dashboard/src/app/sites/[siteId]/measurements/`(서버 페이지·작업대·그래프·보드), `lib/measurement-*.ts`. 승인 시안 `docs/design/MEASUREMENT_PROFILE_DESIGN_2026-11-17.html`. 저장 선·단면 작업 목록·결과를 읽기만 하고 날짜는 이미 있는 완료 결과 가운데서만 고른다(선택만으로 요청을 보내지 않음). 선 모양·자료·작업구역이 어긋난 결과는 표시하지 않고, 권한 철회·접근 기한 만료·미연결(404)은 이유와 함께 알린다. 모르는 지점은 선을 끊고 이유를 보이며 0으로 채우지 않는다(CSV도 빈 칸과 이유 코드). 구간 선택은 키보드·마우스로 길이·높이 차·기울기를 읽고 보드에 같은 구간을 표시한다. 시험 대시보드 +82개(순수 계산 21·형식 가드 16·선택 규칙 13·상호작용 16·서버 페이지 16, 주입 결함 17개 중 처음 13개 검출, 놓친 4개는 시험을 보강해 모두 검출), 대시보드 전체 3649 통과. 실제 Chromium으로 1440·390 px 정상·권한 철회·실패·빈 상태, 마우스 끌기, 키보드, 날짜 변경을 확인하고 7–22 m 구간 기울기를 손계산(+0.88 m, 5.9 %)과 대조 | 응답은 임시 가짜 Core로 대신했다. 실제 Core의 단면 활성화·실제 소유자와의 통합, 단면 요청·선 그리기·두 시점 차이 화면은 없다. 색은 이 앱의 중립 토큰을 쓴다(시안의 청록과 다름). 고객·현장 수락이나 사용성 시험이 아니다 |
