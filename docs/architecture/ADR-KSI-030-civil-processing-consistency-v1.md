# ADR-KSI-030 — 토목 시계열·물량 처리 일관성 v1

- Status: Accepted
- Date: 2026-08-28
- Requirements: REQ-WRK-101, REQ-INT-101/102/103/104, REQ-SEC-101, REQ-UX-101
- Invariants: INV-017/018/020/023/024/040/050/051/053/060
- Related: ADR-KSI-003, ADR-KSI-012, ADR-KSI-013, ADR-KSI-022, ADR-KSI-024,
  ADR-KSI-026, ADR-KSI-029
- Supersedes: 없음. 기존 ProcessingJob, SourceMedia, 설계면, 보고서, Mission Contract와
  FIELD-0a/DJI capability 원장의 의미를 바꾸지 않는다.

## Context

첫 토목 상품은 설계면 대비 절토·성토 잔량, 두 시점의 토공·적치량 변화, 구역별
공정률과 보고서를 하나의 근거 흐름으로 제공한다. 이 결과는 서로 다른 엔진 버전,
좌표·수직기준, 원본 계보 또는 설계면 정규화 규칙이 섞이면 수치가 있어도 비교
의미를 잃는다. Processing 성공만으로 비교 가능하다고 표시하거나, 과거 결과의
누락된 설정을 추정해 채우는 경로는 이 문제를 숨긴다.

국내 토목 설계면은 LandXML 교환이 일반적이므로, v1은 GeoTIFF 직접 등록과 기존
IFC→GeoTIFF 변환을 유지하면서 LandXML TIN Surface를 첫 입력 경로로 추가한다.
DWG/DXF를 서버가 임의 해석하는 것은 좌표·surface 의미를 확정할 근거가 없어 v1
범위에서 제외한다.

## Decision

### D1 — KSI 관리 기본 프로필은 immutable NodeODM profile이다

기본 재구성 프로필은 다음 immutable snapshot으로 고정한다.

| 항목 | 값 |
|---|---|
| `processingProfileId` | `ksi-odm-civil-v1` |
| 엔진 | NodeODM 2.2.4 / ODM 3.5.6 |
| OCI image | `opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2` |
| 실행 위치 | KSI-managed NodeODM (배포 policy가 허용한 서버/온프렘 실행 위치) |
| 처리값 | `dsm=true`, `dtm=true`, `pc-quality=medium` |
| 동적 객체 마스킹 | `OFF` |
| 필수 산출물 | DSM, DTM, source-authority point cloud와 그 파생물 계보 |

Core registry가 profile ID를 canonical spec과 digest로 확장한다. 일반 사용자는
`processingProfileId`만 제출하며 임의 provider, image, parameter를 같은 profile로
위장할 수 없다. 과거 원장은 `LEGACY_UNMANAGED`로 dual-read하되 누락된 값을 추정하지
않고, 그 결과로 새 정량 비교를 만들지 않는다. 엔진·버전·마스킹·전처리 변경은
기존 profile 수정이 아니라 새 profile 발급과 별도 비교 적합성 검증을 요구한다.

Compose와 배포 검증은 tag가 아닌 위 OCI digest를 사용하고, 실행 image digest와
NodeODM `/info`의 ODM 버전을 함께 검증한다.

NodeODM은 AGPL-3.0이므로 ADR-KSI-012의 무수정 컨테이너 + REST 프로세스 경계를
유지한다. 고객 온프렘으로 이미지를 전달하는 배포는 해당 컴포넌트의 소스 제공 고지와
법무 검토를 별도 배포 게이트로 둔다. Pix4D, Metashape, `customer_workstation`은 미래
adapter 경계로만 보존하고 v1 기본 UI에는 노출하지 않는다.

ADR-KSI-036이 정한 새 첫 출시 방향에서는 이 KSI-managed runtime은 test/demo 및 기존
immutable managed 결과의 역사적 scope이며 기본 경로가 아니다. 외부 결과의 raw-media
lineage, submission/manifest/validation, 형식, 신뢰 근거 및 정량 비교 적합성은 후속
상세 명세가 정한다. 이 scoped notice는 D1의 profile identity, 기존 ProcessingJob, OCI
pin, license gate 또는 비교 fail-closed 계약을 변경하지 않는다.

### D2 — LandXML은 원본 보존형 설계면 ingress다

`sourceFormat=geotiff|landxml`과 LandXML `surfaceSelector`를 설계면 등록 계약에
추가한다. LandXML 1.0~1.2의 meter 단위 TIN Surface subset만 지원하며, 여러 Surface가
있으면 사용자가 기존지반/계획지반 중 하나를 명시적으로 선택한다. 서버는 선택 이름과
TIN 구조를 재검증한다.

원본 LandXML bytes와 SHA-256은 보존하고, 선택 surface, parser version, 0.5m
normalization profile, 생성 canonical GeoTIFF digest를 `sourceLineage`에 함께
결속한다. 원본을 파생 GeoTIFF로 덮어쓰지 않는다. IFC 변환과 LandXML 정규화는 같은
결정론적 TIN rasterizer를 사용한다.

다음은 typed rejection이다: DTD/외부 entity, XML 크기·깊이·격자 상한 초과, 중복 ID,
미지 face 참조, NaN/Inf, 퇴화 삼각형, 지원하지 않는 namespace/구조, 비미터 단위.
DWG/DXF는 직접 해석하지 않으며 LandXML 또는 GeoTIFF 내보내기를 안내한다.

### D3 — 정량 비교는 서버 preflight가 fail-closed로 판정한다

비교 생성과 Console은 같은 서버 preflight를 사용한다. 다음 reason code 중 하나라도
있으면 수치 계산을 시작하지 않고 사용자에게 원인과 다음 행동을 보인다.

- `ANALYSIS_NOT_READY`
- `PROCESSING_PROFILE_UNKNOWN`
- `PROCESSING_PROFILE_MISMATCH`
- `SOURCE_LINEAGE_GAP`
- `CRS_MISMATCH`
- `VERTICAL_REFERENCE_MISMATCH`
- `DESIGN_SURFACE_NOT_VERIFIED`
- `DESIGN_NORMALIZATION_MISMATCH`

v1 자동 비교는 동일 `processingProfileDigest`만 허용한다. 설계 진척 비교는 동일
설계면 revision과 normalization digest도 요구한다. 서로 다른 엔진·버전·profile은
benchmark로 검증된 명시적 compatibility mapping이 추가되기 전까지 비교 불가다.

화면과 보고서의 표현은 **운영관리용 상대 물량**이다. 독립 checkpoint가 없으면 계약
정산, 측량급 정확도, 절대 정확도 또는 RMSE를 주장하지 않는다. 결과 조회는 남기되,
profile을 모르는 과거 결과로 새 정량 비교를 생성하지 않는다.

### D4 — Console과 media ingress는 additive로 유지한다

현재 Operations Console의 Home·현장·작업·확인 항목 정보구조와 시각 디자인은
바꾸지 않는다. 기존 업로드·설계·비교·보고서 패널 안에 다음만 추가한다.

- Source Upload: `KSI 표준 처리 v1`, 파일/폴더 재선택 재시도, 진행 건수와 실패 파일.
- Design Surface: GeoTIFF/LandXML 선택 및 LandXML Surface 선택.
- Comparison: 비교 불가 사유와 다음 행동을 숨기지 않는 preflight 표현.

v1 사진 입구는 `SD/저장매체 → 현장 PC → KSI 웹 업로드`이며, 대량 데이터는 기존
로컬 업로더가 같은 profile ID를 사용한다. 향후 Pilot 2/Manifold 자동 반출이 검증돼도
이 ingress만 교체하고 processing·lineage·comparison 계약은 유지한다.

### D5 — feature flags와 rollback은 안전 게이트를 느슨하게 하지 않는다

profile issuance, LandXML ingress, civil comparison UI는 각각 독립 feature flag로
배포한다. 문제 시 새 발급·변환·비교 생성만 read-only/disabled로 내리고, 기존 원본,
설계면, ProcessingJob, 산출물, 리포트를 삭제·재작성하지 않는다. rollback은
compatibility preflight를 우회하거나 `READY`/정량 비교를 낙관적으로 표시하지 않는다.

## Consequences

- Core는 profile snapshot/digest, 비교 적합성, 원장과 조직 격리를 소유한다.
- Processing Controller는 NodeODM 실행 identity와 LandXML→canonical GeoTIFF 정규화를
  소유한다.
- Dashboard는 기존 Console 패널에서 profile과 blocker를 설명할 뿐, 독자적으로 비교
  가능성을 판단하지 않는다.
- 이 ADR은 비행, motor, waypoint 실행, camera/gimbal control, DPK 설치, Pilot 2/Manifold
  자동 media egress 또는 DJI capability 승격을 열지 않는다. FIELD-0a의 `BLOCKED`와
  DJI field capability의 `NOT_VERIFIED`는 독립 상태로 유지한다.

## Acceptance and rollback

`docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md`가 contract/replay, LandXML 보안·계보,
수치 fixture, fixed-image NodeODM identity, Console regression, repository hygiene와 현장
수용의 분리를 정의한다. 코드·단위 테스트 통과는 실제 토목 현장 수용이 아니다. 현장
수용은 익명화한 국내 LandXML, 동일 현장의 두 회차 원본 사진, 독립 기준 물량 또는
checkpoint 대조가 있을 때만 별도로 기록한다.
