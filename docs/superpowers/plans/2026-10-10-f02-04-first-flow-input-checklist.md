# F-02~04 first-flow input checklist (2026-10-10)

- Status: 착수됨 — 환경 준비 1단계(실바이트 레인 리허설, synthetic) 완료. 고객측 실제 자료 입력 대기.
- Scope: 외부 산출물 등록 → 적합성 검사 → Analysis API → 실제 워커 → Result/Evidence 저장 → 외부 소비를
  **실제(Terra 계열) 자료 기준, same-Site t0/t1/t2**로 완주하는 경로. production/배포·정확도 주장은 제외.
- Related: [rebaseline 원장](2026-10-07-agent-first-platform-rebaseline.md) F-02~04 항목,
  [P5 통합 감사](../audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md) F-02..04,
  [external release plan](2026-09-06-external-reconstruction-release.md),
  [staging acceptance](../acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md),
  [DEV external runbook](../ops/DEV_EXTERNAL_RUNBOOK.md).

## 1. 이미 준비된 것 (2026-10-10, synthetic 환경 검증)

- 격리 로컬 오브젝트 스토리지: 캐시된 `127.0.0.1:5000/ksi-minio:037d636-r2` 컨테이너(loopback 9100,
  전용 data 디렉터리, synthetic 자격 — 저장소·원장에 비밀 없음). presign PUT→PUT→HEAD 왕복 확인.
- Core dev 스택을 `--s3-endpoint/--s3-bucket`(+boto3 기본 체인 자격)으로 기동. **실바이트 레인
  리허설 성공**: Site/WorkArea/외부 WorkOrder 생성 → 등록(`ers-v1-…` 수신증) → 업로드 grant
  (MinIO presigned URL) → 실제 PUT(ortho·dsm) → **seal SEALED** → inspection 조회
  `INSPECTION_PENDING_POLICY`(=검사 정책/권위 구성 필요, F-03 항목).
- 증거: `/tmp/opencode/f02-prep-20261010-194828/evidence/rehearsal-0{1..4}.txt`(실패→성공 순 보존,
  해시는 원장). 재실행 스크립트: 같은 디렉터리 `scripts/rehearse_f02.py`(synthetic 바이트).
- 한계: synthetic 바이트이므로 고객 자료·형식 호환·정확도·수용 증거가 아니다. 검사는 미구성.

## 2. 고객측(사용자) 입력 — 이 입력이 있어야 실제 경로가 닫힌다

- A. 자료(한 Site/WorkArea, Terra 계열 export):
  1. t0: ortho GeoTIFF(필수 1개) + DSM GeoTIFF(높이/상대물량용)
  2. t1: 같은 Site/WorkArea의 ortho(+DSM)
  3. t2: 두 번째 주기 재사용 검증용(가능하면 동일 조건)
  - 각 파일: CRS·수직기준(예: EPSG:5186/KNGeoid2018) **일치**, 캡처 시작/끝 시각(UTC),
    sha256/크기 계산 가능. 원본 사진은 고객 장비 보관(업로드 불요).
- B. 권리·동의: KSI가 등록·보관·검사·분석·표시하는 것에 대한 조직 내부 허가, AI 외부 반출 허용
  여부, 데이터 거주(jurisdiction) 선언.
- C. (정량 결과용) 시점별 독립 검사점(checkpoint) CSV — external relative-volume V1 규칙.
  없으면 결과 대신 typed blocker가 반환되며 첫 완주는 blocker+재관측 경로로 가능.
- D. 외부 소비자 1개+호스트: Analysis MCP(stdio) / Spatial Data MCP / SDK 스크립트 / 직접 API 중 선택.
- E. 수용 참여: 2-cycle 운영 검토 참여(관찰·판정) 주체.

## 3. 우리측 준비 상태

- **F-03 phase 1 — 완료(2026-10-10, synthetic)**: 서명 Analysis activation trio(runtime/envelope/activation
  + 검증키)와 ADMIN/ANALYSIS_WORKER 토큰을 만드는 생성기(`scripts/gen_f03_material.py`)로 보호 구성을
  만들고, **production factory**(uvicorn factory)를 로컬 부팅해 검증했다 — `/ready` 200, analysis 계열
  route 12·external-reconstruction route 15 마운트, 더미 create가 404 scope(503 activation-expired 아님
  = 서명 activation 실제 수용). 보호 파일 로더는 그룹 쓰기 가능 조상을 `CONFIG_FILE`로 거부하므로
  material은 `~/.cache/ksi-f03-*/analysis`(0700/0600)에 둔다. 증거: prep dir `evidence/f03-*`.
- **F-03 phase 2 — 남음**: 외부 workflow/provider pair(서명 snapshot에 policy/catalog authority record
  포함)와 workflow config 생성 → Core를 authority 구성으로 재부팅 → **검사 정책 admit**(authority
  operations 경로 또는 검증된 시드)로 `INSPECTION_PENDING_POLICY` 해소.
- **검사기·Analysis 워커 — 남음**: 로컬 합성 한정 inspector lane 실행 경로 확정(UDS inspector 체인 —
  staging의 ACL activation blocker와 구분해 표기), `ksi-external-analysis-worker` CLI를 worker config·
  토큰으로 실행해 실제 계산→결과/증거 저장.
- **F-02 접수 절차**: 실제 자료 수신(격리 위치·sha256 확인·선언 값 대조)과 업로드 스크립트 정비.
- **F-04**: 선택된 소비자 클라이언트(`services/analysis-mcp`, `services/spatial-data-mcp` 소스 실행)
  준비, 2-cycle 시퀀스 스크립트, 브라우저/API 증거 수집.

## 4. 순서

1. (완료 2026-10-10) 스토리지+Core+등록→PUT→seal 리허설 — synthetic.
2. 우리측: F-03 보호 구성(합성 로컬) + 검사 lane 활성화 → synthetic 자료로 검사→분석→결과/증거까지.
3. 고객측 A~E 도착 → 같은 환경에서 실제 자료 등록/검사/분석/결과 → 외부 소비자 E2E → 기록.
4. t2 주기 재사용 → F-04 운영/고객 수용 기록(별도 판정).

## 5. 현재 차단/한계

- 검사 미구성(`INSPECTION_PENDING_POLICY`) — F-03 준비로 해소 예정.
- real-data admission(형식·CRS·수직기준·프로파일)은 실제 Terra export로만 검증된다.
- 정량 결과는 검사점·정책·실행 활성화 구성이 필요하며, 이는 P7-A2/새 rail과 무관한 별도 F-03 작업이다.
- production/배포·CI/AMD64/TLS·고객/EXT-VAL 수용은 계속 별도 게이트다.
