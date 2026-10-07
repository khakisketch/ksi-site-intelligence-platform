# KSI Site Intelligence Platform — Final Decision Ledger v1.0

- 상태: APPROVED / FROZEN
- 승인일: 2026-07-24
- 적용 PRD: MASTER_PRD v3.0
- 개정: 2026-08-07 §고객·가치 (ADR-KSI-016) · 2026-08-08 오기 정정 + 선형
  순위 폐기·2축 구조 전환(대표자 확정) · 2026-08-20 공정·상대 물량 첫 상품과
  zero-touch/Copilot 결정(ADR-KSI-022) · 2026-08-21 RC-first Connected Edge와
  선택형 Manifold 직접망 결정(ADR-KSI-023) · 하나의 반응형 Operations Console과
  Pilot 2 비행 전용 화면 경계(ADR-KSI-024) · 근거 중심 다현장 Home과 최근 업데이트
  구조(ADR-KSI-025) · 현장 작업공간과 근거형 AX 계약(ADR-KSI-026) · 2026-08-27 Mission
  Intent/Flight Artifact 권한 및 Observation Epoch/Analysis Readiness 계약(ADR-KSI-028/029) — 동결 문서의 개정이므로 근거 ADR 없이
  이 줄을 바꾸지 않는다 · 2026-08-28 토목 시계열·물량의 immutable KSI-managed
  NodeODM profile, LandXML 설계면 ingress 및 fail-closed comparison compatibility
  (ADR-KSI-030) · 2026-08-29 봉인된 독립 검사점 CSV를 DSM과 서버에서 직접 대조해
  오차한계 근거를 생산하되 상대 물량·현장 수용 경계를 유지하는 결정(ADR-KSI-031) ·
  2026-08-30 제품 소유 runtime image digest pin과 Core-owned versioned processing
  resource admission snapshot 결정(ADR-KSI-032) · 2026-08-31 native `ksi_psdk_app`을
  유일한 production Edge runtime으로 두고 Python perception을 offline replay/model
  evaluation으로 격리한 결정(ADR-KSI-009 D8) · 2026-08-31 source-media automatic
  offload를 ordinary DPK의 기본 경로로 삼지 않고, explicit Manifold/activation/Core-sync/
  private-control/mount/byte-bound build와 one-shot operator approval로만 조립하며 HIL 전
  capability는 `NOT_VERIFIED`로 유지하는 결정(ADR-KSI-013 D3/D5) · 2026-09-04
  PSDK Liveview=Manifold 로컬 입력, `EDGE_UPLINK`=bounded metadata, 현재 원본
  ingress=SD/현장 PC/Web, 자동 media=별도 목표 capability로 분리하고 중앙 지속 영상
  수신을 핵심 제품 경로에서 제외한 결정(ADR-KSI-033) · 2026-09-20 external first-release의
  customer-PC DJI Terra reference workflow, M4D RTK field-validation role, KSI의
  derived-result inspection/analysis boundary를 ADR-KSI-036 D6로 명확화 · 2026-09-20
  API-first 현장 관측·분석 근거 서비스와 WorkArea별 주간 2시점 관측 지형 물량 변화 MVP를
  ADR-KSI-037로 결정 · 같은 날 implementation-condition amendment로 KSI GIS worker의
  fixed V2 profile, checkpoint 부재 잠정 수치, 알려진 실패/상충 근거의 보완 필요 분리를
  목표 요구로 확정 (기존 strict V1은 보존) · 2026-09-30 ADR-KSI-038로 공간데이터 제공과
  재현 가능한 분석을 외부 프로젝트가 사용하는 플랫폼 방향을 확정. 문서·장기 계획만 반영하며 개발은 보류
· 2026-10-07 ADR-KSI-039로 비행·자율 취득·전술 인지/제어·고객 production 재구성을
장기 제품 책임 밖으로 확정하고 Constitution·PRD·ADR037 D6/ADR038 취득 조항의 책임
라우팅을 supersede. 수치·원본·불변식·EXT-VAL·역사적 milestone 증거는 불변

## 명칭·시장

- 플랫폼: KSI Site Intelligence Platform
- 제품: KSI Site Intelligence
- 저장소: `ksi-site-intelligence-platform`
- 첫 Vertical: 건설현장 안전·공간관리
- 확장: 산업중립 Core + Industry Solution Packs

## 고객·가치

- 우선 고객 가설: 현장 산출물을 보유하고 다른 시스템에 반복 연결하는 건설사 디지털팀,
  현장 솔루션 개발사, SI·AI 개발팀. 현장 담당자는 결과 사용자이며 기존 토공 파일럿 역할을
  유지한다. 구매자·지불 의사·시간 절감은 고객 검증 대상이다(ADR-KSI-038).
- 제품 구조: **API-first Site Intelligence Core**가 현장 공간데이터를 등록·검사·구조화하고,
  필요한 데이터와 재현 가능한 분석을 출처·시점·좌표·조건·근거와 함께 외부 프로젝트에
  제공한다(ADR-KSI-038). 데이터 접근과 서버 분석은 별도 제품 경로다. 얇은 Analysis
  facade와 UI/향후 MCP는 같은 Core 기록을 생성·조회하며 독립 권한/계산을 만들지 않는다;
  외부 재구성 산출물의 첫 분석은 KSI GIS worker의 고정 V2 profile이 맡는다. 이 문구는
  구현된 MCP 또는 외부 endpoint를 뜻하지 않는다.
  Site Intelligence Core(WHAT/WHY) ↔ Autonomous Acquisition(HOW)의 기존 폐루프는
  장기 관측·취득 roadmap으로 보존한다. 선형 가치 순위는 폐기했다 —
  플랫폼 기술·분석 기능·임무 유형이 한 목록에 섞여 있어 줄 세우기 자체가 분류
  오류였다. 자율 안전순찰·구조물 점검은 Acquisition 축의 **임무 유형**이며
  서로 순위를 두지 않는다(정본: `ksi_domain.enums.MissionType`).
  전 개정본의 "자율 안전순찰은 KSI Safety 제품 축으로 이동"은 오기였다 —
  이 제품의 범위에 그대로 있다. 장기 취득 축의 제품 책임은 2026-10-07
  ADR-KSI-039로 out-of-product이며, 이 단락은 역사적 결정 기록이다.
- UX: 현장 노트북·컴퓨터의 하나의 반응형 KSI Operations Console + 제한된 전문가 모드.
  모바일은 같은 Web에서 확인 항목·분석·Copilot을 우선하고 임무·재관측·장비 행동은
  노트북으로 안내한다. Home은 다현장 구매자·운영 책임자에게 실제 근거가 있는 확인 현장과
  최근 결과만 브리핑하고, 공간 결과·보고서·조사 이력은 각 현장이 소유한다. RC Plus 2/Pilot
  2에는 KSI 업무 UI를 표시하지 않는다.
- IA/AX: 전역 메뉴는 홈·현장·작업·확인 항목이며, 변화·물량·공간 결과·보고서·조사
  이력은 현장 작업공간이 소유한다. 현장 AI는 저장형 대화와 검증된 citation으로만 답하고,
  외부 반출은 Site별 별도 동의가 없으면 fail-closed한다(ADR-KSI-026).
- 첫 플랫폼 검증: DSM·정사영상으로 같은 현장의 분석 요청과 외부 코드용 구역 데이터
  활용을 모두 수용한다. 최소 Console은 등록·상태·보완·근거·접근·사용량을 지원한다.
  Point cloud·Mesh·외부 분석 레이어 및 추가 client/SDK/산업 어댑터는 별도 후속 계약이다.
  상위 단계·보완 결정은 [SDP-20260930](../superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md)이 소유한다.
- 첫 분석 사례의 완결 MVP: Site·WorkArea·Epoch/version을 지속 매핑한 주간 2시점 관측 지형 물량 변화
  검토. `t0→t1` 후 같은 WorkArea/mapping/template로 `t1→t2`를 재사용한다. 결과는
  기록된 계산 결과이며, 기하 변화·순물량·설계 차이가 공정·승인 작업·정산·품질·현장 수용을
  증명하지 않는다.
- KSI-managed 토목 처리 기본값: `ksi-odm-civil-v1` (NodeODM 2.2.4 / ODM 3.5.6, digest-pinned
  image, DSM·DTM, `pc-quality=medium`, dynamic-object masking OFF). profile을 고쳐
  과거 결과의 의미를 바꾸지 않으며, 새 엔진·전처리·마스킹은 새 profile과 별도
  적합성 검증을 거친다.
- 2026-09-06 ADR-KSI-036: 새 첫 출시 기본은 고객이 자기 장비에서 재구성하고 KSI가
  export artifact를 등록·검증·분석하는 방향이다. KSI-managed NodeODM는 test/demo
  scope이며 기존 profile·ProcessingJob·결과는 immutable로 유지한다. 외부 import는
  성공 ProcessingJob, 봉인 raw bundle, source authority 또는 기존 profile identity를
  만들지 못한다. 등록≠검증≠정량 사용 가능이고, provenance/CRS/수직기준/품질/계보/
  호환성 미상은 의존 claim을 fail-closed로 제한한다(INV-051/053/060). BIM 일괄 전제,
  근거 없는 진척률, vendor 선택·보증·license 승인은 하지 않는다. 후속 Human 결정으로
  원본은 고객 장비에 남고 전체 raw 업로드는 정상 경로의 필수가 아니다. KSI는 제출된
  산출물과 provenance/품질 근거를 보관한다. 정사영상만의 등록을 허용하고 DSM 등의
  부족은 의존하는 주장만 제한한다. 원본 미업로드만으로 정량 사용을 영구 금지하지
  않는다. 형식·실제 export 호환성·검증 정책은 후속 명세/수용 대상이다. bounded Core
  ingress API의 local software evidence는
  [`audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md`](../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md)에,
  현재 product/goal 상태는 [`superpowers/product-state.md`](../superpowers/product-state.md)와
  그 named plan ledger에 기록된다.
  이는 semantic analysis, release/device/vendor/deployment acceptance를 뜻하지 않는다
  (ADR-KSI-036 D4/D5).
- 2026-09-20 D6: 초기 재구성 입력 참조 흐름은 RTK-equipped M4D capture → 고객이
  통제하는 현장 PC의 DJI Terra 재구성 → KSI의 제출 파생 산출물/근거 검사·호환 비교·
  상대 물량/업무·재관측이다. 이는 Terra license/export/provider integration이나 RTK/map
  accuracy를 승인하지 않는다. KSI는 proprietary photogrammetry engine 또는 고객
  production reconstruction service가 아니다. ortho-only registration은 가능하고, DSM은
  eligible height/relative-volume에, point cloud/DTM은 기능별 입력에, mesh는 선택
  visualization에 쓴다. 등록≠검증≠정량 사용 가능이며 RTK FIX는 정산/측량 보증이 아니다.
- 설계면: GeoTIFF 직접 등록과 IFC→GeoTIFF를 유지하고, meter-unit LandXML TIN Surface를
  원본 digest·selector·정규화 계보와 함께 받는다. DWG/DXF 직접 해석은 하지 않고
  LandXML 또는 GeoTIFF 내보내기를 안내한다. 그러나 현재-설계 잔여 절성토는 실제 고객 설계
  데이터와 별도 provenance 계약이 필요한 조건부 후속이고, BIM 원본의 작성·편집·관리는 고객
  도구에 남는다.
- 운영 처리 경계: 제품 소유 외부 runtime image는 exact version+OCI digest로 고정한다.
  ProcessingJob은 Core registry의 `ksi-civil-pilot-r1` resource policy로 봉인 원본과
  조직별 활성 작업을 판정하고 발급 당시 snapshot/digest를 보존한다. 상한 변경은 같은
  ID 수정이 아니라 새 policy 발급이다. 통과는 정확도·과금·Cloud 승인이 아니다.
- 정상 전달: RC Plus 2/Pilot 2가 비행·인터넷 gateway, Manifold 3가 로컬 Edge다.
  사람의 KSI 업무는 Operations Console이 담당한다.
  RC 인터넷은 새 임무 발급 전 필수이고 Manifold SIM은 선택 Add-on이다. USB·SD·
  수동 KMZ는 복구 전용이다(ADR-KSI-023). ADR-KSI-035 범위에서는 KSI planned artifact의
  laptop download와 Pilot import/exception edit가 Pilot-default 정상 planning 경로이며,
  현행 원본은 다음 SD/현장 PC/Web ingress를 따른다. 이는 자동 전달 또는 DJI capability
  수용 주장이 아니다.
- 원본 반출: `SD/저장매체 → 현장 PC → KSI 웹 업로드`가 현재 정상 제품 경로다.
  `ksi_psdk_app`의 source-media automatic offload는 기본 OFF이며, explicit Manifold/native
  activation/Core sync/private control directory/verified camera mount/measured byte bound가
  모두 있는 별도 DPK에서만 operator prepare → baseline → activation → one-shot trigger의
  exact delta를 시도한다. 이는 HIL 전 `NOT_VERIFIED` capability이고 signed Mission Contract,
  Core RBAC, SD/PC/Web fallback 또는 어떤 flight/camera/gimbal command도 대체하지 않는다
  (ADR-KSI-013 D3/D5).
- 경로 분리: PSDK Liveview는 Manifold 로컬 acquisition/perception 입력이고,
  `EDGE_UPLINK`는 bounded EventBundle/EdgeBundle metadata와 object reference만 전달한다.
  자동 원본은 별도 `MEDIA_PULL`→`MEDIA_UPLOAD` 목표 경로이며 물리 HIL 전에는
  `NOT_VERIFIED`/OFF다. Core·Vercel·Operations Console의 중앙 지속 영상 수신은 첫 유료
  폐루프나 공간·시간 판단의 전제가 아니다(ADR-KSI-033).
- 비행 산출물: Core는 Mission Intent와 검증된 최종 Flight Artifact의
  source·revision·digest·Mission Contract 결속을 소유한다. Core KMZ compiler는 현재
  candidate/fallback이며, Pilot 2 import/export FIELD 증거 전에는 제거하거나 자동 기본
  경로로 바꾸지 않는다(ADR-KSI-028). ADR-KSI-035의 기본값은 KSI candidate artifact를
  Pilot planning의 제안으로 삼는 것이며, field evidence 전 `field-compatible default` 또는
  actual execution으로 승격하지 않는다.
- 2026-09-06 ADR-KSI-035 범위 정정: Pilot-default 관측에서는 KSI가 결정적
  terrain-aware 후보를 만들고 Pilot이 import·예외 편집·최종 실행판단을 한다. Pilot은
  편집본을 비행 전 KSI에 반환할 필요가 없고, 그 경우 KSI는 원안과 pilot 선언/actual log/
  actual capture를 혼동하거나 미반환 편집을 KSI 승인 artifact로 표시하지 않는다. 미래 자율
  execution의 signed/digest/device/activation gate는 이 예외로 약화하지 않는다.
- 배치: 정책형 하이브리드(KSI Cloud 제어면 + 현장별 데이터 실행 위치)
- Copilot: 외부 LLM 공급자 중립 adapter, 근거 조회·설명·재관측 초안 전용

## 하드웨어·자율성 (현장 검증·장기 취득 roadmap)

- 초기 field-validation equipment: RTK-equipped Matrice 4D + RC Plus 2 + Manifold 3.
  이는 API-first MVP의 자동 비행·로봇 실행 약속이 아니다.
- RC Plus 2가 Pilot 2 이착륙·수동인계와 지상 인터넷 gateway를 담당한다
- Manifold가 인터넷과 무관하게 비행 중 인지·탐색·재관찰·우회·복귀를 담당한다
- Gateway(RC/Dock)와 Edge(Manifold)는 별도 장치 신원·최소권한을 사용한다
- Manifold SIM 직접망은 전송용 Connectivity Add-on이며 Edge 지능의 조건이 아니다
- Mission Contract 사전 1회 승인
- 현장정책 승인 후 정기임무 자동실행
- 미매핑 공간은 제한속도·거리·행동으로 탐색
- 반개방 공간은 사전 매핑된 안전회랑만

## 안전·완료

- 위험구역 100%, 필수자산·표면 100%, 일반 접근영역 95%
- 서버통신 단절: 유효계약과 안전조건이 유지되면 계속
- RC Link Lost: DJI Flight Controller 정책
- 배터리: 현장별 설정, 기본 예상귀환 + 30% Reserve
- Unknown obstacle: 정지·재관찰·후퇴·확인 후 우회

## 사건·증거

- Critical: Edge 후보 1초, 로컬경보 2초, 서버알림 5초
- High: 10초 이내 확인·알림
- Medium: 최대 30초 재관찰·재검증
- Candidate Clip: 전후 3초
- High Clip: 전후 5초
- Critical Clip: 전후 10초
- 불확실성을 포함해도 위험이 유지될 때만 Confirmed

## 지도·데이터

- 매 비행 Map Delta
- 변화 시 부분재스캔
- 기본 전체갱신 주 1회, 빠른 변화단계 주 2~3회, 안정단계 2~4주
- 일반 Candidate 30일
- 순찰 원본 90일
- Confirmed Event 3년
- Telemetry·Mission 1년
- 감사·조치 3년
- 공간산출물 계약기간 + 90일

## 장비·모델

- 공개데이터와 자체데이터로 범용지원 확대
- Manifold production Edge runtime은 native `ksi_psdk_app` 하나다. Python recorded
  perception은 offline replay/model evaluation 전용이며, 그 EventBundle은 Core가
  `NON_PRODUCTION_EVIDENCE`로 원장 반영 전에 거부한다(ADR-KSI-009 D8).
- 지원단계: DATASET_AVAILABLE → BASELINE_DETECTION → FIELD_VALIDATED → GEO_VALIDATED → RISK_VALIDATED → PRODUCTION_SUPPORTED
- Production Supported만 공식 상용지원

## 사용자 결정권·정확도

- 비행 중 촬영 품질 보충은 서명된 계약과 Capture Policy 범위 안에서 Manifold가 수행
- 범위·비용이 증가하는 재관측은 사용자가 승인
- LLM은 비행 좌표·안전 명령·승인을 생성하지 않음
- MVP 물량은 운영관리용 시점 간 상대값이며 계약 정산·측량급으로 표시하지 않음
- 정량 비교는 Analysis Readiness, processing profile digest, 원본/설계면 lineage, CRS,
  수직기준 및 설계면 revision/정규화 digest가 모두 알려지고 일치할 때만 허용한다.
  하나라도 미상·불일치이면 서버가 typed blocker를 반환하며 Console은 이를 숨기지
  않는다. 독립 checkpoint 없이는 절대 정확도·RMSE를 주장하지 않는다.
- 독립 checkpoint는 DSM별 봉인 CSV로 등록하고 서버 워커가 원본 DSM과 전점을 직접
  대조한다. 사용자는 독립성 근거를 증언하지만 RMSE를 입력하지 않으며, software
  검증 결과만으로 측량급·계약 정산 정확도를 주장하지 않는다.
