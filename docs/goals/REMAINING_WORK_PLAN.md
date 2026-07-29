# 완성형까지의 잔여 작업 계획 (2026-07-29 확정)

> 상태의 SSOT는 goal-ledger(`ksi-goals.py status`)다 — 이 문서는 구조 개요만 담고
> 진행 상태를 복제하지 않는다. 근거: 2026-07-29 전수 갭 스캔(PRD·코드·원장·WPML
> 스펙 6축 병렬 대조, workflow wf_ff556013) + ADR-KSI-005/006/007.

## 소프트웨어 트랙 (하드웨어 불요 — 지금 진행)

| 순서 | Goal ID | 내용 | 왜 이 순서인가 |
|---|---|---|---|
| S1 | `mission-geometry-route` | AOI 폴리곤 도메인 모델 + 구역→커버리지 경로 생성기(매핑=lawnmower·순찰=외곽) + WPML/KMZ 생성기 | ADR-KSI-007의 미구현 절반. S2·S3의 선행 결손(AOI 모델이 없으면 현장 등록도 임무 정의도 못 만든다) |
| S2 | `core-domain-query` | Site 도메인(상태머신)·Mission 영속/조회·Event 조회+트리아지 전이 API·인증/권한 | 대시보드가 소비할 읽기 계층 전체가 missing. 인증은 edge-sync P1-4 risk(위조 sequence 락아웃)의 해소 경로이기도 함 |
| S3 | `dashboard-mvp` | Next.js 대시보드: 홈·이벤트 트리아지·임무·현장 + 현장등록/조사 Wizard (UX 목표 선행 작성) | S2의 API 위에서만 실물이 됨. apps/dashboard는 현재 README뿐 |
| S4 | `ops-serving-hardening` | Evidence 미디어 스토리지(presigned)·retention 집행·서명키 수명주기·journal 회전(인증과 결합) | 운영 표면 — S2의 인증·DB 결정과 결합해야 재작업이 없음 |

부수 P2 백로그(원장 노트 소유): slice-inference-exception-channel(track-b에서 폐쇄
구현·review_pending), coverage-report 완료 게이트(INV-010 강제 지점 미구현 — S1
범위에 스키마 소비만, 실계산은 실기 커버리지 데이터 이후), model-lineage-coco-residual
(법무 검토 대기), 처리 파이프라인 후단(workers/* — ODM·map-compiler·change-detection,
Phase 2 이후).

## 하드웨어 트랙 (도착·승인 대기 — 준비 완료 상태 유지)

| ID | 내용 | 게이트 |
|---|---|---|
| H1 | 벤치 SSH 인계 → 환경 인벤토리 → B2 TensorRT 온타깃 검증 | USB-C 이더넷 어댑터 (track-b 잔여) |
| H2 | Cellular Dongle 2 + 국내 유심 실측 (`ip addr`/`ping`/`curl` — ADR-KSI-005 정정 검증) | 동글+유심 구매 |
| H3 | Track A PSDK 스파이크: 9항목 SpikeEvidence + 비행상태 topic(ADR-KSI-006) + Frame-Telemetry p95≤50ms | 기체 + PSDK 개발자 승인 |
| H4 | KMZ 실기 임포트 검증 (Pilot 2 — WPML 스펙 caveats 해소: wpmz/ 폴더명·M4D droneEnumValue) | RC Plus 2 |

## 확정된 설계 전제 (이 계획이 기대는 ADR)

- 오프라인이 정상 동작, 온라인은 가속(저장 후 전달 단일 경로) — ADR-KSI-005
- 임무 정의 = 이원 산출물(KMZ→기체 / Mission Contract→Manifold, 동일 site_frame·policy_version 짝) — ADR-KSI-007
- 상시 LTE 1순위 = DJI Cellular Dongle 2(공식 payload network access), 대안 = USB-C LTE 라우터 — ADR-KSI-005(정정)
- 실시간 텔레메트리 스트림·라이브 지도 = 스코프 제외(RTMP는 RC 네이티브) — ADR-KSI-005
- 앱 자동 기동·이착륙 트리거 = 목표 설계, Track A에서 실증 — ADR-KSI-006
