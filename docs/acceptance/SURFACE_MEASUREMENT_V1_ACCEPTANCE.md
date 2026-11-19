# Surface measurement v1 — Acceptance target

- Status: TARGET / SOFTWARE_ONLY / CUSTOMER_NOT_EVALUATED.
  순수 단면 계산·계약·로컬 계산 어댑터·단일 subject HEIGHT 판정·저장 선과
  단면 작업의 Core 요청자/일꾼 HTTP·명시적 opt-in 조립이 구현되어 있다.
  단면 일꾼 실행기(`run_once`: 원본 capability로 받은 바이트 대조, 파일 사실 재대조, 한도 있는 계산, receipt 보고)가 있다.
  서명된 설정으로 폴링하는 상시 실행 진입점(`surface_profile_service`)이 있다.
  Console의 측정 선 화면(`/sites/{id}/measurements`)에서 선을 그려 저장하고 날짜별 단면을 요청해 그래프와 CSV를 열 수 있다.
  같은 개정의 선에서 두 날짜의 높이차를 요청할 수 있다. Core는 각 DSM의 독립 검증 근거와 두 시점의 승인된 호환성을 확인한다. 선 저장과 작업 요청은 1024px 이상에서 제공한다.
  운영자 CLI는 Console에서 사용한 작업과 판정을 다시 읽는다. 단면 워커는 고정된 Linux 격리 실행기에 계산을 맡긴다. 운영 호스트에서 단면 작업 전체를 실행하는 검증, 운영 활성화와 호환성 승인 자료, MCP 단면 접근은 남아 있다.
  로컬 Linux에서 배포용 Core 이미지를 서명된 시험 설정과 기본 기동 명령으로 실행했다. 읽기 전용 파일시스템에서 비특권 사용자로 기동했고 권한 공급자의 준비 응답(HTTP 200)과 두 시점 비교 생성·조회 경로를 확인했다.
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
| SM-AC-01 | Heights and distances match analytical ground truth on synthetic surfaces; reprojection from WGS84 agrees with the projected line | local synthetic contract tests and an independent reference on the same samples | 합성 DSM 두 장에서 실제 워커가 읽은 45개 지점을 해석식과 대조했다. 같은 픽셀 중심을 GDAL 3.11.4로 독립 조회했다. 경계 처리 차이는 아래에 기록했다. |
| SM-AC-02 | Unknown stays unknown: outside, edge band, NoData sentinel, NaN, and one-sided unknown in a comparison never become a number or `0` | contract tests | 바깥·가장자리·NaN·NoData에 대한 계산 시험과 두 DSM의 HTTP 통합 시험을 통과했다. 한쪽에만 값이 없는 4곳은 누락 사유와 함께 차이가 비었다. |
| SM-AC-03 | Reads are bounded by policy: single read window, source storage-block size, vertices, samples, line length; over-limit input is refused, never coarsened silently | contract tests; worker-level time, memory, cancellation and concurrency limits | 워커는 읽기 전에 원본 해시·좌표계·격자 범위·결측 표현과 허가된 창을 대조한다. 타일·스트립 전체의 압축 해제량, 독립 마스크 블록, 반환하는 마스크와 결과 크기를 한도에 포함한다. 계산 중 권한·기한을 재확인하고 작업 디렉터리는 한 프로세스만 점유한다. 자원 한도가 적용된 Linux 자식에서 합성 표고 17개를 해석식과 대조했다. 운영 호스트의 작업별 네임스페이스 검증은 남아 있다. |
| SM-AC-04 | A request is bound to exact asset ID, submission, revision and digest; comparison runs only after the existing Core preflight (INV-053: processing profile, CRS, vertical reference, lineage) and returns typed blockers otherwise | Core route and replay tests | 두 완료 작업·결과·영수증과 저장 선 개정을 결속한다. 각 DSM의 검사·독립 근거·촬영 순서·호환성 승인을 재확인한다. 승인이 없으면 사유와 빈 결과를 반환한다. |
| SM-AC-05 | Saved line geometry is revisioned; editing creates a new revision, old results stay bound to the old one; the same line is reusable for the next observation with a new request and result | contract and persistence tests including restart and duplicate request | 편집 전 결과는 원래 개정에 남는다. 두 시점 비교는 같은 선 개정과 표본 위치에 결속하며 동일한 요청 키로 다시 요청하면 최초 판정을 읽는다. |
| SM-AC-06 | Rights and egress: no read, CSV or agent response widens the caller's current site/work-area permission or AI-egress consent; exports carry no credentials or signed URLs | permission, revocation and egress tests | 날짜별 CSV는 선택한 모든 작업을 현재 권한으로 다시 읽고 수직 기준 출처를 기록한다. 높이차 CSV는 두 원본과 비교 승인을 다시 확인한다. 한쪽 자료의 읽기 권한이나 비교 승인이 철회되면 높이차가 닫힌다. MCP 단면 접근은 거부되며 에이전트 외부 전송은 미구현이다. |
| SM-AC-07 | Console, API, CLI and MCP return the same input revision, result ID, values and unknown reasons | cross-surface contract test | Console CSV와 같은 로컬 Core를 조회한 운영자 CLI에서 두 결과와 비교 다이제스트, 45개 지점의 값과 결측 사유가 일치했다. 비교 승인 철회 후 CLI는 HTTP 409와 사유를 반환하고 표준 출력은 비어 있었다. MCP 단면 접근은 미구현이다. |
| SM-AC-08 | A field user completes draw → read graph → change date → export in the real browser at 390/768/1280/1440px and 200% zoom, with keyboard and touch, stale values withdrawn on input change, and no write request from selection alone | real-browser test; later unaided task test with field staff | draw (map, laptop only), request per date, read graph, change date, CSV export, keyboard: implemented in the Console; checked at 390 and 1440 px against a stand-in Core, and the request → real worker → graph path at 1440 px against the real Core owners and worker; the real-Core page was also loaded at 390, 768, 1280 px and at a 200 % zoom equivalent (720 CSS px, device scale 2): no horizontal overflow, the date selector present, and the request buttons hidden below 1024 px and shown at 1280 px (layout checked from screenshots at 768 px); the request panel's keyboard operation (Tab order, Space/Enter to request and cancel, visible focus, the blocked-reason alert) was checked in a real browser against a stand-in Core and its status text is an `aria-live` region (no screen reader was run); the two-date comparison and CSV were also checked in Chromium at 390/768/1280/1440 px, with keyboard and an emulated touch tap linked to the saved-line map; physical touch hardware, real 200 % browser zoom and the unaided field test remain open |
| SM-AC-09 | Real customer data: the P-AC customer sample (same work area, t0/t1/t2 DSM, intended lines, CRS/vertical/quality evidence, usage rights) read with an independent reference comparison | customer-approved data and independent review | not evaluated |

## Decision: two-epoch difference gate (2026-11-17, user)

The difference between two dates' profiles is opened under the **same standard as RELATIVE_VOLUME**:
a new pair use (`PROFILE_DIFFERENCE`, no zone) that needs per-epoch independently attested evidence
for the measured DSM and a Core compatibility authority (INV-053). The signed catalog supports a
separate approval for the exact pair and WorkArea. It checks the active profile policy, both
inspection reports, ordered capture intervals and each DSM's independent evidence before it admits
the mapping. Removing profile approval withdraws numerical access on the next read. A missing
approval leaves the comparison blocked, with the two per-date profiles available under their own
permissions. [Operator provisioning](../ops/DEV_EXTERNAL_RUNBOOK.md#3b-approving-a-saved-line-profile-comparison)

**HEIGHT (single subject) is open as of 2026-11-17.** Core now issues an ELIGIBLE `HEIGHT` decision
when the current policy permits it, the inspection report binds the exact subject/policy, and a MEASURED
single-band Float32/Float64 DSM carries a parser-observed vertical reference. A missing DSM, wrong
profile, missing vertical reference, absent policy or withdrawn inspection is a typed blocker; no unit is
guessed from the horizontal axis. HEIGHT binds no display receipt, evidence, zone or compatibility mapping
and is **not** a quantitative, comparability, accuracy or customer-acceptance claim. Decisions made before
this change keep their retained `HEIGHT_PRODUCT_DEFINITION_UNRESOLVED` blocker and are never rewritten.
작업 HTTP가 단일 subject 판정을 다시 확인하고, C3 일꾼은 봉인된 파일의 바이트와 공간 정보를 대조한 뒤 단면을 계산한다. 이 경로는 로컬에서 검증했고 운영 활성화는 남아 있다.

부모 워커는 원본을 전송받고, 격리된 자식은 같은 파일의 길이와 SHA-256을 다시 확인한다. 열린 파일에서 가로·세로 크기, 자료형, 원점과 해상도를 포함한 격자 변환, 수평·수직 기준을 대조한다. 읽기 창이 승인된 픽셀 또는 실제 지상 범위와 다르면 계산을 거부한다. 같은 Linux 자식에 주소 공간 1 GiB·CPU 시간 15초를 적용한 로컬 시험에서 합성면의 17개 높이가 해석값과 일치했다. 이 시험의 자식은 컨테이너 네임스페이스를 상속했다. 운영자 자재와 기동 조건은 [공간데이터 운영 지침](../ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md)에 있다.

**Declared vertical reference (decided 2026-11-17; ledger, HEIGHT, profile consumers and Console
screens implemented 2026-11-18).** Most DSM exports carry no
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
the observed value. The Console declares, corrects and withdraws on the asset detail, shows the provenance
("file observed" or "user declared, not verified") next to the numbers, warns when two dates sit on different
bases, and marks the CSV with a `vertical_reference` column. The measurements screen asks for a date's profile
only through a Core HEIGHT decision made by asset reference (`POST …/spatial-assets/{asset_ref}/height-decision`,
human operator with SITES_WRITE, scope-checked through the same catalog as every asset read, BLOCKED returned
with its reasons); a BLOCKED date is explained and points at the declaration instead of creating a job. Still
absent: the declared read on a production stack (the surface lane is not activated there), an independent
check that a declaration is right (Core never verifies it), and any use of a declaration beyond height and
profile.

## 두 시점 비교의 수치 확인

**경주 봉길리 공개 DSM.** 2020년 5월 22일과 10월 20일 UAV 관측의 원본은 EPSG:32652, 포항 기본수준면 기준의 1 m 격자 중심 CSV다. 각 행을 공통 1 m 격자의 가장 가까운 셀에 한 번씩 배치했다. 원본 좌표와 셀 중심의 최대 평면 거리는 0.142 m 미만이었다. 누락 셀은 내부 마스크로 보존했다. 원래 높이를 보존한 파일과 연구자가 명시한 `H = z − 0.357 m`를 적용한 국가수직기준 파생본을 각각 만들었다. 로컬 Console에서 국가수직기준 파생본 두 장을 등록하고 Linux 검사기가 파일의 수직 기준 EPSG:5193을 확인했다. Core의 날짜별 높이 판정은 두 건 모두 `HEIGHT_ELIGIBLE`이었다. [공개 원본 및 저자 설명, Figshare v2](https://doi.org/10.6084/m9.figshare.33971680.v2)

같은 30 m 동서 측정 선에서 두 날짜의 작업을 완료했다. 운영자 CLI에서 다시 읽은 각 31개 높이와 Chromium의 날짜별 CSV 62행을 원본 CSV에서 독립적으로 환산한 값에 대조했다. 각 날짜에서 제품이 읽은 높이와 해당 날짜의 원본 환산값 사이의 최대 절대차는 0 m였다. 두 날짜 사이의 높이차 요청은 `POLICY_UNAVAILABLE`로 판정되어 결과가 비어 있었다. 이 자료에 대한 현장 정확도와 고객 수락은 별도 검증 대상이다.

봉길리 5월 DSM의 자료 상세에서 새 측정 선을 열고 약 20 m 선을 경위도로 저장했다. 10월 자료도 등록돼 있었으며 선 저장과 편집 뒤에는 5월 파일과 해당 선 개정이 선택되어 있었다. 별도로 요청하기 전 단면 작업은 0건이었다. 첫 개정은 보간에 필요한 격자가 읽기 허가의 북쪽 경계를 0.5 m 넘어 `GRANT_REQUIRED`로 거절됐다. 같은 허가 범위 안으로 옮긴 두 번째 개정은 Console 요청과 로컬 Linux 워커 처리를 거쳐 1 m 간격 및 끝점의 5월 높이 22개를 반환했다. Chromium에서 내보낸 22행의 촬영일, 수직 기준, 좌표, 거리, 높이가 결과 기록과 일치했다. 같은 저장선으로 10월 DSM을 Core API에서 요청해 같은 위치 22곳의 높이를 읽었다. 두 날짜 각각의 원본 CSV에서 이웃 셀로 독립 계산한 높이와 제품 높이의 최대 절대차는 모두 0.00000001 m 미만이었다. 이 선의 두 시점 높이차도 승인 매핑이 없어 보류됐다.

이 판정을 Console에서 복사하면 사유, 담당자와 조치, 두 날짜와 자료 참조, 저장 주소가 함께 담긴다. 봉길리 자료의 판정을 1440 px Chromium에서 복사하고 같은 요청자 계정으로 768 px와 390 px에서 다시 열었다. 두 화면 모두 새 비교 요청 없이 같은 판정을 표시했다. 클립보드 쓰기를 거절한 390 px 화면에서는 키보드로 직접 복사할 수 있도록 판정 전문이 선택됐다.

Console의 높이차 그래프와 표는 승인된 지점별 결과를 함께 사용한다. 그래프는 0 m를 표시하고 한쪽 값이 없는 구간을 끊는다. 그래프에서 거리를 선택하면 측정 선 위에 같은 지점을 표시한다. Console은 수집 날짜를 선택해도 계산을 시작하지 않는다. 두 단면의 표본 간격이 다르면 사용자가 공통 간격을 확인한 뒤 필요한 날짜만 다시 읽을 수 있다. 완료된 결과에서 같은 선과 두 날짜를 이어서 비교한다. 비교 고유 주소를 열면 두 작업과 기존 판정을 현재 권한으로 조회한다. Chromium의 390 px 새 세션에서 같은 사용자가 고유 주소로 표를 읽고 CSV를 받았다. 선을 편집한 뒤에도 고유 주소는 원래 개정을 열고, 현재 개정으로 돌아가는 링크를 제공한다.

로컬 통합 시험은 같은 44 m 선에서 1 m 간격으로 두 합성 DSM의 픽셀 중심 45곳을 읽는다. 두 값이 모두 있는 41곳의 차이는 해석식과 일치한다. 상승·변화 없음·하강과 서로 다른 네 곳의 NoData를 포함한다. [HTTP 통합 시험](../../tests/contract/test_surface_profile_comparison_http.py)

같은 합성 표면에 시험용 서명 카탈로그를 적용해 승인 전후를 검증했다. 두 DSM의 별도 체크포인트 검증과 단면 작업을 마쳐도 매핑 등록 전에는 높이차가 보류됐다. 등록 후 저장된 HTTP 주소에서 41개 차이와 4개 결측 사유를 읽었다. 철회 후 같은 주소는 HTTP 409를 반환했고, Core를 다시 조립한 뒤에도 원래 판정과 매핑 다이제스트는 이력에서 확인됐다. [서명·단면 워커·HTTP·재생 통합 시험](../../tests/contract/test_external_profile_difference_signed_core_lifecycle.py)

GDAL 3.11.4의 `gdallocationinfo`로 같은 원본에서 픽셀 중심을 직접 읽으면 45곳의 높이와 NoData가 시점별로 일치한다. GDAL의 bilinear 옵션은 NoData 바로 앞의 중심 1곳씩도 NoData로 반환했다. KSI의 단면 보간은 가중치가 0인 이웃을 제외하므로 이 두 위치에서는 중심 셀의 유효한 높이를 반환한다. 양쪽 구현이 값을 반환한 위치의 차이는 0 m였다.

**국내 공개 자료.** Kim, Jo, Choi가 공개한 신시도 하부 갯벌의 2019년 8월·10월 드론 표고 파일 두 장과 연구진의 같은 기간 차이 지도(DoD)를 확보하고 배포처 SHA-256과 대조했다. 두 표고 파일을 로컬 Console에서 등록·봉인했다. Linux 검사기가 두 파일에서 같은 638 × 458 격자와 EPSG:32652를 확인했다. 공개본에서 확인되는 촬영 월과 Pix4D 4.0.25는 출처와 함께 저장했고, 정확한 촬영일은 미상으로 두었다. 재조회에서도 출처·월·파일 해시가 유지됐다. 두 원본 모두 파일에서 읽을 수 있는 수직 기준이 없어 Core의 높이 판정은 `VERTICAL_REFERENCE_UNKNOWN`이었다. 연구진의 차이 지도는 외부 참고 자료로 보관했다. 공개 원본과 라이선스는 [Kim, Jo, Choi (2021), Mendeley Data V1, Figure 13, CC BY 4.0](https://data.mendeley.com/datasets/f66r4hvrdg/1)에 있다.

**독립 검증점이 있는 해외 후보.** USGS의 Town Neck Beach 배포 목록에서 2023년 12월 19일과 2024년 4월 15일의 25 cm 라이다 DSM과 각 시점의 별도 GPS 검증점 파일을 확인했다. 두 조사 설명을 확보했다. 파일 배포 서버가 HTTP 403을 반환해 두 격자의 중첩 범위와 DSM 높이의 검증점 잔차는 확인하지 못했다. 두 DSM의 좌표계와 높이 기준(NAD83(2011) / UTM 19N, NAVD88)은 현재 국내 분석 지원 범위 밖이다. [2023년 USGS 자료 설명](https://cmgds.marine.usgs.gov/catalog/whcmsc/SB_data_release/DR_P1UBZZFA/2023028FA_TNB_metadata.html) · [2024년 USGS 자료 설명](https://cmgds.marine.usgs.gov/catalog/whcmsc/SB_data_release/DR_P1UBZZFA/2024-018-FA_TNB_Apr_meta.html)

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
| 2026-11-17~18 | 수직 기준 선언(D1–D6, 올리기 전 점검, 선언 화면): 선언 원장·HEIGHT/단면 소비·동결·영수증 되풀이·Core 재대조, 자료 상세의 선언·정정·철회, 숫자 옆 출처 표시·CSV 열, 브라우저의 올리기 전 첫 IFD 점검(검사기 규칙 거울, 실제 검사기와 대조). `test_vertical_reference_declaration*.py`·`test_surface_profile_*`·`test_asset_height_decision.py`(12개, 실제 카탈로그·작업 저장소 위)와 실제 소유자 loopback 통합(선언 전 BLOCKED → 선언 → ELIGIBLE → 작업 → 영수증 DECLARED, 실제 일꾼이 선언 기준으로 읽음, 철회 시 숫자 닫힘). 주입 결함은 의미 있는 것 모두 검출(사람 확인 방어 코드는 기존 경로와 같아 새 시험으로 도달하지 못함) | 합성 DSM과 실제 검사기 1건(user-defined 투영 CRS DSM)만. 선언의 정확성은 검증하지 않는다. 운영 스택의 단면 활성화 없음. Pix4D·Terra 등 실제 벤더 산출물은 시험하지 않았다 |
| 2026-11-18 | 측정 선 그리기(PR B)와 날짜별 단면 요청(PR C): 지도에서 그려 저장·새 개정으로 고치기(`expectedRevision`), 봉인된 DSM마다 요청·진행·취소·재요청·사유 안내(BFF가 자료 참조로 판정을 받아 작업 발급, 키 파생으로 재시도 중복 방지, 판정이 ELIGIBLE이 아니면 작업 없음), 요청자 목록의 `feature_id` 필터(한도 적용 전 선 단위로 좁힘). 대시보드 전체 vitest 3979개·`next build`·tsc 통과, Core 관련 시험 통과, 필터 변이 3건 검출. 실제 브라우저: 가짜 Core로 막힘·거부·진행→자동 갱신→완료·취소·모바일(요청 버튼 숨김·가로 넘침 없음), 실제 Core 소유자·실제 일꾼으로 요청→처리→그래프(1440 px) | 이 Mac은 전체 백엔드 시험을 돌릴 수 없다: 384개 시험 파일 중 80개가 실패·시간 초과이며 `main`에서도 같은 개수로 실패했다(원인 미분석, Linux 전용 검사기·컨테이너·소켓으로 추정). 실제 Core 확인은 시험용 조립을 임시로 띄운 것이며 운영 활성화·배포 증거가 아니다. 목록은 Core 정책의 `max_list_records`를 넘으면 오래된 요청이 보이지 않는다. 두 시점 차이 화면은 없다 |
