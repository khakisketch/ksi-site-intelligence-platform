# Product State - KSI-Site-Intelligence-Platform

Summary updated: **2026-10-29**. Owner: Build. This reorganization does not close, reprioritize,
or change the product slice, EXT-VAL, milestone outcomes, customer/field acceptance or execution approval.
Existing dated results are references, not tests rerun by this document edit. Revalidate Git and the
named work ledger before treating a statement as current implementation.

## Goal

물리적 현장 관측을 근거형 Site State/Change로 연결하는 Site Intelligence 기반이다.
공간데이터 제공·외부 재사용과 고정 분석의 API·MCP 제공은 두 제품 경로다(ADR-KSI-038/039).
고객 원본·재구성 실행은 고객 장비에 남고 KSI는 외부 파생 산출물의 등록·검사·조건을 충족한
분석과 근거를 소유한다(ADR-KSI-036). 비행·자율 취득·전술 인지/제어·고객 production 재구성은
out-of-product이며 과거 취득 구현은 현재 지원이나 다음 작업 후보가 아니다.

## 핵심 제품 기능 체크리스트

이 표는 제품 기능과 현재 증거의 **요약 투영**이다. 별도의 작업 원장·새 우선순위·권한이
아니며, [현재 작업 원장](../ledger/CURRENT.md), 해당 구현/증거 및
[P-AC-01..06](plans/2026-09-30-spatial-data-platform-roadmap.md#첫-플랫폼-수용-기준-목표-미검증)을
대체하지 않는다. `로컬`은 기록된 소스·합성 자료·시험 환경에 한정하고 고객·현장·운영
수용을 뜻하지 않는다. 각 기능의 추가 작업과 최신 증거는 연결된 기존 원장에서 확인한다.

| 핵심 사용자 일 / 기능 | 현재 구현·검증 범위 | 남은 제품 수용 경계 |
| --- | --- | --- |
| 현장·구역을 등록하고 시점별 자료와 공간 상태를 탐색한다 | 기존 Site/WorkArea/epoch/revision/digest와 자산 카탈로그를 사용한다. 로컬 현장·구역 등록과 Console·API·MCP 조회 근거가 있다. 준비된 자료가 없거나 만료되면 실제 등록 범위와 제한을 구분한다. | 실제 고객 자료·권한과 독립 사용자의 등록·발견·선택은 미수용. |
| 고객이 만든 산출물을 등록·봉인하고 실제 바이트를 검사한다 | 외부 산출물 등록, 봉인, 관측된 형식·공간 메타데이터 검사 경로와 합성 검증이 있다. 제공자 선언은 관측 사실과 구분한다. | 최신 후보의 격리 파서→검토는 현재 워크스테이션에서 차단; 준비된 호스트와 고객 export 확인 필요. |
| 자료 유효성·용도별 적합성·정확도 평가를 구분한다 | 읽기/추출과 정량 분석의 권한·적합성, 차단 사유 및 평가 상태를 분리하는 로컬 계약·음성 시험이 있다. | 실제 입력의 좌표·수직 기준·품질 및 현장 담당자의 보완 판단은 미수용. |
| 권한 있는 DSM·정사영상의 구역 자료를 외부 코드가 사용한다 | native-grid 구역 준비·전달과 [최신 설치 adapter의 MCP/HTTP 소비 경로](../ops/SPATIAL_DATA_MCP_SOFTWARE_EVIDENCE.md)에 합성 DSM/RGB/RGBA 바이트·좌표·마스크 독립 대조 근거가 있다. | 실제 고객 파일·권리·독립 소비자 및 운영 호스트 수용은 미검증. 이 경로가 정량 분석 적합성을 보장하지 않는다. |
| 동일 구역의 두 관측 시점 변화를 계산한다 | Core가 고정한 상대 지형 변화와 선택 마스크/coverage의 로컬 구현·합성 검증이 있다. V2와 별도 V3 프로파일 및 과거 결과는 구분한다. | 고객 입력·독립 정확도 근거·현장 수용은 미검증. 검사점이 없는 결과는 잠정이며 정산 수치가 아니다. |
| 질문을 근거 있는 작업과 다음 행동으로 연결한다 | 관측 변화에 한해 의도·기존 구역 선택→조건 확인→동일 작업 재개·결과 확인 경로가 로컬에 있다. AI는 계산·권한·사람의 결정을 대체하지 않는다. | 실제 외부 호스트 및 고객 사용은 미검증. 일반적인 선제 제안·보고서 초안·수치 질의 등 AX-5..7은 완성으로 선언하지 않으며 별도 방향·계약을 따른다. |
| 결과·범위·제한·근거를 조회하고 사람이 검토한다 | Console·API·Analysis MCP의 동일 결과/근거 조회, coverage 표시 및 검토 경로에 로컬 증거가 있다. 입력·구역·프로필·정책·엔진과 주요 설정의 재현 조건을 보존하며, 불변 결과와 현재 활용 적합성, 완료·평가·검토는 별개다. | 고객의 의미 이해와 실제 스크린리더·물리 기기 사용은 미검증. |
| 다음 관측에서 같은 업무를 반복한다 | 합성 `t0→t1`, `t1→t2`의 새 입력·결과 결속, 이전 결과 보존 및 UI/API/MCP 대조가 로컬에서 검증됐다. | 고객의 실제 두 주기 사용, 변경 영향 이해와 반복 준비 시간은 미수용. |
| 사람과 외부 소프트웨어가 동일한 Core 기록을 사용한다 | 로컬 Console·API와 제한된 stdio MCP/소비 예제가 같은 권위의 기록을 사용한다. 범용 AI 클라이언트나 임의 코드 실행을 약속하지 않는다. | 동일 고객 자산의 데이터 제공·분석 양 경로 교차, 선택한 외부 호스트·인증·동의·독립 고객 연동은 미수용. |
| 권한·반출·실패·중단 후 재시도를 안전하게 다룬다 | 조직/현장/구역 범위, AI 반출 동의, 실패·멱등성·현재성에 로컬 양성/음성·replay 근거가 있다. 합성 OIDC·로컬 Core에서 작업 운영 재시도와 증거 선언·업로드 승인 재시도를 확인했다. 시험 전용 루프백 저장소에서는 합성 증거의 실제 전송·Core 봉인과 응답 유실 후 동일 기록 회복도 확인했다. Console의 일부 재시도 보호는 같은 화면에 한정된다. | 팀원 재시도와 실제 권한/저장소/호스트는 미검증. 봉인 유실 후 UI는 동일 선언을 재시도해 기록을 회복했고, 동일 봉인 키 재시도는 별도 BFF 직접 요청으로 확인했다. 다른 계정 차단은 선언 단계에서 확인했으며 승인 단계 계정 전환은 별도다. 일부 지도는 제3자 타일을 요청하므로 위치 범위·접속 정보의 외부 노출 처리는 [별도 결정](../product/BETA_PROGRAM.md)이 필요하다. |
| 작업 상태·실패와 자원 한도·사용량을 확인한다 | 로컬 작업 상태·실패/보완 안내와 유한 자원 제한 근거가 있다. 구역 자료 목록·상세는 정확히 결속된 완료 출력의 준비 당시 개별 파일 크기를 표시한다. | 총 사용량 표시의 구현 근거는 확인하지 못했다. 집계 정의·권한 및 대표 크기 자료의 저장·연산·전송 실측이 필요하다. 개별 파일 크기를 누적 사용량으로 취급하지 않으며 가격·SLA는 확정하지 않는다. |
| 운영자가 안전하게 배포·복구하고 고객이 수용한다 | 로컬 빌드·패키징·회귀 및 일부 장애 차단 증거가 있다. | 서명·호스트 격리·접근·백업/복원·원격 CI와 고객 권리·보관·반출·지원·비용 및 두 경로 수용은 별도 증거와 승인이 필요하다. |

세부 소스·증거·실패 이력은 [Console 통합](../ledger/work/2026-10-26-console.md),
[공간 엔진 통합](plans/2026-10-25-spatial-intelligence-engine-integration.md),
[공간데이터 로컬 검증](../ops/SPATIAL_DATA_LOCAL_VERIFICATION.md) 및
[rebaseline 원장](plans/2026-10-07-agent-first-platform-rebaseline.md)을 따른다. 점군·Mesh·외부
분석 레이어 등은 별도 후속 계약·수용 대상이고, 비행·자율 취득·고객 production 재구성은
현재 제품 책임 밖이다. 이 표는 현재 `EXT-VAL` slice를 닫지 않는다.

## Current work and evidence

- Current bounded work: [`../ledger/CURRENT.md`](../ledger/CURRENT.md) and its named work files.
  An active Human-assigned checkout task takes precedence for work selection without changing the slice.
  The checkpoint is a pointer, not another task or priority authority.
- Platform/engine approval, implementation and verification:
  [rebaseline ledger](plans/2026-10-07-agent-first-platform-rebaseline.md). This is a separate active
  stream; this summary does not declare it closed or copy its incremental progress.
- Console direction and delivered evidence: [current spec](../design/CONSOLE_CURRENT_SPEC.md) and
  [console work](../ledger/work/2026-10-26-console.md). The concurrent `d70d099d` record reports viewer-first
  공간/자료 deployed from `viewer-first-20261026` (product `153b0f7e`, branch HEAD `10bacff0`) with its
  source-bound image/render evidence. This documentation task did not deploy or rerender it; the main
  checkout, separate branch and deployed image must not be treated as the same source version.
- Real Floreat imagery remains retention-expired. Local/software/synthetic/render evidence does not
  establish genuine imagery, quantitative/settlement suitability or customer/field acceptance.
- The later first-use and retry candidate has source-bound Dashboard packaging, generated browser
  recovery and two-period UI/API/MCP evidence. The transient title gap, intercepted delayed-session
  observation and mixed-version recovery risk remain explicit. A synthetic WorkArea rollback case
  reproduced a hidden pending original and duplicate POST; a later local guarded-Core case refused
  the retry without a second record. Actual release binaries, operating cutover and Site registration
  remain unverified. The separate backend snapshot has only a scoped post-edit byte
  comparison. Owning evidence/limits remain in the
  [Console work entry](../ledger/work/2026-10-26-console.md#2026-10-29-development-handoff-follow-through--still-blocked);
  this is not a deployment, real external consumer-host configuration or first-customer acceptance.
- A delayed prior-account response can restore that account after a new login in synthetic HTTP
  tests. Core-owned encrypted session authority is the chosen local direction, **not yet a verified
  fix**; current acceptance and cutover limits are in the [work entry](../ledger/work/2026-10-26-console.md#2026-10-29-development-handoff-follow-through--still-blocked).
- Product authority and source ownership: [`../00_READ_FIRST.md`](../00_READ_FIRST.md),
  [`../DOCUMENT_STATUS.md`](../DOCUMENT_STATUS.md), and root `REPOSITORY_STRUCTURE.md`.

## Milestones

Dated milestone rows and prior P2–P7/F-01 receipts are preserved in
[the historical state snapshot](product-state-history-2026-10-26.md#milestones). Their literal baseline
preservation digest is unchanged; they are history, not a competing current-work selector.

## Current slice
- Name: 외부 재구성 산출물 파일 검사와 용도별 사용 적합성 판정
- Acceptance (user-visible end-to-end): EXT-VAL-01 actual sealed derived bytes format and spatial metadata inspection; EXT-VAL-02 customer declarations separated from measured facts; EXT-VAL-03 versioned Core per-use display comparison height volume decisions with evidence-bound positive and negative paths; EXT-VAL-04 explicit remediation without blanket raw-upload or DSM absence denial; EXT-VAL-05 bounded resources transient retry fencing tenant isolation and restart replay; EXT-VAL-06 mounted Core and processing-controller workflow without managed identity impersonation; EXT-VAL-07 reviewed detailed plan contracts tests independent and integrated verification; EXT-VAL-08 durable docs goal evidence and local versus release acceptance boundaries
- Plan ledger: docs/superpowers/plans/2026-09-07-external-artifact-validation.md
## Next slices
- phase-3: Phase 3 (PRD §25)
- phase-4: Phase 4 (PRD §25) — acquisition-only pieces out-of-product per ADR-KSI-039; spatial/inspection reuse scope retained (not a completion claim)
- phase-5: Phase 5 (PRD §25) — acquisition-only pieces out-of-product per ADR-KSI-039; industry reuse scope retained (not a completion claim)
- track-a: Track A: DJI Hardware Capability Spike — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- track-b: Track B: Perception Vertical Slice (실기 입력 전환) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- autonomous-acquisition-closed-loop: Autonomous Acquisition Closed Loop — 실제 M4D 기준 종단 폐루프 1회 완주 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-1-spatial-model-lifecycle: AOL-1 G1: 공간모델 생애주기 — 현장이 '공간모델 없음/있음/오래됨'을 서버가 판단한다
- aol-1-capture-auto-ingest: AOL-1 G4: 촬영 → 서버 자동 ingest — 사람 손 사진 업로드 제거 (ADR-KSI-018 P1) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-1-mission-to-aircraft-delivery: AOL-1 G3: 임무를 기체까지 보내는 공식 경로 — 현재는 운영자가 KMZ 를 손으로 옮긴다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-3-terrain-aware-planning: AOL-3 G6: 공간모델 인지 경로계획 — DSM/Point Cloud 를 경로계획 입력으로 (AOL-1 이후에만 착수) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-0-ground-integration: FIELD-0 지상 통합 — 비행 없이 매니폴드·기체·임무파일이 실제로 이어지는지 확인 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-1-first-mapping-flight: FIELD-1 첫 실제 매핑 비행 — 우리 현장 사진으로 공간모델이 처음 만들어진다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-2-reobservation-loop-field: FIELD-2 현장 폐루프 — 1회차 분석이 만든 재관측 임무로 2회차를 실제로 난다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-3-terrain-aware-flight: FIELD-3 지형추종 비행 — 웨이포인트마다 다른 고도가 실제 비행파일에 실린다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- decision-psdk-flight-execution-authorization: KSI가 매니폴드를 통해 기체를 직접 실행시키는 것을 허용할 것인가 (FIELD-1 이후 판단) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-0a-kmz-acceptance: FIELD-0a 비행파일 수용성 + 카메라 실측 — 조종기만 있으면 오늘 할 수 있다 (FIELD-1의 유일한 전제) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- decision-flight-ceiling-reference-split: 법적 비행 상한과 DJI 고도 기준을 어떻게 분리할 것인가 (FIELD-3 전 확정) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s1-upload-only: C2-S1: 임무 업로드만 (Action 없이) — 빌드 자물쇠 1단계 개방 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s2-propellerless-start: C2-S2: 프로펠러 없는 START — 개념적으로 안전하지 않은 단계, 매 진입 대표자 서면 승인 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s3-supervised-flight: C2-S3: 사람 감시 하 실비행 — ADR-KSI-022(수직기준) 완료가 전제, 빌드 자물쇠는 안 늘어난다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s4-routine-operation: C2-S4: 일상 운용 — arming TTL 을 세션 단위로 완화 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-1-ground-control: FIELD-1 조사에 한국 좌표계 기준점(GCP) 부착 — 두 시점 비교의 전제 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- terrain-aware-planning-software: 지형 인지 정사 계획·다운로드·사후 증거 소프트웨어 흐름 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- terrain-aware-planning-field-acceptance: M4D·Pilot 실제 계획 운용과 관측 품질 수용 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- pilot-default-external-reconstruction-release: 고객 원본 보관·외부 재구성 기반 KSI Pilot-default 첫 출시 완성 — open as KSI external derived-result registration, inspection and customer/ops acceptance only; capture/customer engine execution excluded per ADR-KSI-039
## Backlog
- 플랫폼 SDP-01..10 / GAP-01..10과 고객 표본·계약·권리/운영 검증은
  [플랫폼 원장](plans/2026-09-30-spatial-data-platform-roadmap.md)에서 추적한다. 기존 EXT-VAL에 소급 추가하지 않는다.
- 카탈로그의 유한 조회 예산·부하/페이지 재설계는 [카탈로그 계획](plans/2026-09-30-spatial-asset-catalog-v1.md)을 따른다.
  이 문서 정리는 기존256/2048/256/128/64 한도나 명시적503 의미를 변경하지 않는다.
- 외부 authority의 시간 창 밖 안전 부팅은
  `docs/superpowers/specs/2026-10-15-external-authority-degraded-boot.md` §6의 승인·구현 상태를 따른다.
  만료·미발효·catalog binding·signing-key 네 게이트는 이미 구현되어 있으며,
  2026-10-27 현 checkout의 관련 production-factory 계약 테스트7개가 다시 통과했다.
  손상된 서명/체인과 누락된 필수 설정은 여전히 fatal이며, 자동 활성화나 운영 배포 수용은 뜻하지 않는다.
- [경험 개선 원장](plans/2026-09-17-dashboard-experience-improvements.md)의 남은 항목과
  SV-3b 선택 직후 reload 지연은 각각의 기록을 유지한다. rehearsal M-3 보고서 digest 설명은
  [SV-4 기록](plans/2026-09-18-single-volume-sv4.md)에 2026-10-15 보완 완료로 기록되어 있다.
  당시 machine-local 증거 파일은 현재 checkout에서 재확인되지 않았다.
- 이미 정정·종결한 중복 mapping·음수0·날짜표시·환경 실패 가설 등은
  [분리 전 Backlog](product-state-history-2026-10-26.md#backlog)에 보존한다. 현재 실패로 재등록하지 않는다.
