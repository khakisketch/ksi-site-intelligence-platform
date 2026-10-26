# Product State - KSI-Site-Intelligence-Platform

Summary updated: **2026-10-26**. Owner: Build. This reorganization does not close, reprioritize,
or change the product slice, EXT-VAL, milestone outcomes, customer/field acceptance or execution approval.
Existing dated results are references, not tests rerun by this document edit. Revalidate Git and the
named work ledger before treating a statement as current implementation.

## Goal

물리적 현장 관측을 근거형 Site State/Change로 연결하는 Site Intelligence 기반이다.
공간데이터 제공·외부 재사용과 고정 분석의 API·MCP 제공은 두 제품 경로다(ADR-KSI-038/039).
고객 원본·재구성 실행은 고객 장비에 남고 KSI는 외부 파생 산출물의 등록·검사·조건을 충족한
분석과 근거를 소유한다(ADR-KSI-036). 비행·자율 취득·전술 인지/제어·고객 production 재구성은
out-of-product이며 과거 취득 구현은 현재 지원이나 다음 작업 후보가 아니다.

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
- 외부 authority future-issued 부팅 실패와 두 시간 게이트 보정은
  `docs/superpowers/specs/2026-10-15-external-authority-degraded-boot.md`의 제안/검토 상태를 따른다.
  window-expired의 기존 BLOCKED 관찰과 구현 승인을 혼동하지 않는다.
- [경험 개선 원장](plans/2026-09-17-dashboard-experience-improvements.md)의 남은 항목,
  SV-3b 선택 직후 reload 지연, rehearsal M-3 보고서 digest 설명 보완은 각각의 기록을 유지한다.
- 이미 정정·종결한 중복 mapping·음수0·날짜표시·환경 실패 가설 등은
  [분리 전 Backlog](product-state-history-2026-10-26.md#backlog)에 보존한다. 현재 실패로 재등록하지 않는다.
