# 완성형까지의 잔여 작업 계획 (2026-08-08 개정)

> 상태의 SSOT는 goal-ledger(`ksi-goals.py status`)다 — 이 문서는 구조 개요만 담고
> 진행 상태를 복제하지 않는다. 근거: ADR-KSI-016(제품 범위·공간 아키텍처 확정,
> 2026-08-07 대표자 확정) + 2026-08-07 전체 저장소 실태 조사.
>
> **2026-07-29판과의 차이**: 그때의 소프트웨어 트랙(S1~S4)은 전부 완료됐다
> (`mission-geometry-route`·`core-domain-query`·`dashboard-mvp`·
> `ops-serving-hardening`). 그 계획은 "임무 거버넌스와 조회 계층을 세운다"까지를
> 다뤘고, 실제로 그것이 섰다. 이 개정판은 그 위에서 **공간 데이터의 실체**를
> 만드는 트랙을 다룬다 — 실태 조사가 드러낸 공백이 정확히 거기다.

## 마일스톤 트랙 (하드웨어 불요 — 지금 진행)

| 순서 | Goal ID | 내용 | 왜 이 순서인가 |
|---|---|---|---|
| M1 | `m1-spatial-epoch-pipeline` | 재구성 산출물 바이트 영속 → 정좌표(EPSG:5186·수직기준) → 두 시점 DSM 차분 체적·변화 리포트 → 대시보드 표시 | 재구성은 이미 돌지만 **산출물 바이트를 버린다**(`odm.py` `plan_artifacts` — digest만 계산). 사람이 볼 수 있는 것이 남지 않으면 그 위의 어떤 분석도 실물이 아니다. 고객이 돈을 내는 최소 단위이기도 하다 |
| M2 | (미등록) | 폐루프 실물 — 변화 신호 → 재촬영 AOI → 임무 초안 → 승인 발급 | M1의 변화·체적이 있어야 "무엇을 다시 찍을지"가 정해진다. 제품 정의(ADR-KSI-016 D1)의 "재수집을 스스로 계획한다"가 여기서 실물이 된다 |
| M3 | (미등록) | 상용 기반 — PostgreSQL/PostGIS 전환, 실사용자 인증·발급·회수, retention 집행 | **이것 없이는 어떤 고객에게도 나갈 수 없다** — 현재 실행 경로가 dev 토큰 5개를 하드코딩한 `scripts/run_core_dev.py`(자칭 "프로덕션 조립 아님") 하나뿐이고 SQL DB가 없다. M1·M2보다 먼저 하지 않는 이유는 무엇을 저장할지가 M1에서 정해지기 때문이다 |
| M4 | (미등록) | 설계층 v1(도면·계획고 대비) + 실기 트랙 합류 | BIM 정합은 이미 착수돼 있고(`services/bim-integration`), M1의 좌표계 위에서만 의미를 갖는다 |

## 하드웨어 트랙 (도착·승인 대기 — 준비 완료 상태 유지)

| ID | 내용 | 게이트 |
|---|---|---|
| H1 | 벤치 SSH 인계 → 환경 인벤토리 → B2 TensorRT 온타깃 검증 | USB-C 이더넷 어댑터 (track-b 잔여) |
| H2 | Cellular Dongle 2 + 국내 유심 실측 (`ip addr`/`ping`/`curl` — ADR-KSI-005 정정 검증) | 동글+유심 구매 |
| H3 | Track A PSDK 스파이크: 9항목 SpikeEvidence + 비행상태 topic(ADR-KSI-006) + Frame-Telemetry p95≤50ms | 기체 + PSDK 개발자 승인 |
| H4 | KMZ 실기 임포트 검증 (Pilot 2 — WPML 스펙 caveats 해소: wpmz/ 폴더명·M4D droneEnumValue) | RC Plus 2 |

하드웨어 트랙은 마일스톤 트랙과 **경합하지 않는다** — 구매·승인 대기가 게이트라
개발 리소스를 나눠 쓰지 않는다. 실기 사진이 확보되면 M1이 만든 같은 파이프라인으로
교체 검증한다(M1은 ODM 공개 샘플 데이터셋으로 먼저 뚫는다).

## 두 축의 현재 (ADR-KSI-016 D2)

제품은 **Site Intelligence Core(WHAT/WHY) ↔ Autonomous Acquisition(HOW)의
폐루프**다. 위 두 트랙 표는 그 축들의 현재 진행 상태를 사람이 읽는 형태로
적은 것이고, 기계가 읽는 형태는 `PHASE_REGISTRY.yaml`의 `axes` 절이다.

| 축 | 지금 | 왜 |
|---|---|---|
| Site Intelligence Core | **진행** | 막힌 것 없음 — M1~M3이 이 축이다 |
| Autonomous Acquisition | **차단** | 우선순위가 아니라 게이트다 — H1~H4가 장비·PSDK 승인 대기 |

**차단과 강등을 구분한다.** Acquisition 축은 뒤로 미룬 것이 아니라 막혀 있고,
게이트가 열리는 즉시 착수한다. 이 구분을 흐리면 하드웨어 도착 시 "그건 낮은
순위였는데"가 다시 나온다.

## 지금 추가 투자를 하지 않는 것 (ADR-KSI-016 D5)

전부 범위 안에 있고 구현물도 유지한다. "몇 순위"가 아니라 "신규 투자 없음"이다.

- phase-3 장비 kinematics·CPA/TTC·위험장 → Acquisition 축 기능, 축이 열릴 때까지 신규 투자 없음
- phase-5 Dock·Fleet·산업중립 팩 → 첫 유료 건설 현장 전까지 동결
- Edge perception 신규 코드 → 하드웨어 스파이크(H1~H4) 전 착수 금지(ADR-KSI-006)
- 자연어 질의·LLM 보고서 표면 → 데이터 계층 이후

## 확정된 설계 전제 (이 계획이 기대는 ADR)

- 제품 정의·우선순위·공간 데이터 계층·Build vs Buy — ADR-KSI-016
- Point Cloud 원본 SSOT / Mesh·정사영상·DSM 파생 — ADR-KSI-003, INV-051
- 재구성 엔진 기본값 ODM + AGPL 프로세스 경계 + 현장당 과금 — ADR-KSI-012
- 오프라인이 정상 동작, 온라인은 가속(저장 후 전달 단일 경로) — ADR-KSI-005
- 임무 정의 = 이원 산출물(KMZ→기체 / Mission Contract→Manifold) — ADR-KSI-007
- 실시간 텔레메트리 스트림·라이브 지도 = 스코프 제외(RTMP는 RC 네이티브) — ADR-KSI-005
- 앱 자동 기동·이착륙 트리거 = 목표 설계, Track A에서 실증 — ADR-KSI-006
