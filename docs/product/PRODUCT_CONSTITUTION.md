# KSI Site Intelligence Product Constitution

> **개정 이력**
> - 2026-08-08 (2차) — **선형 핵심가치 목록을 폐기하고 2축 폐루프 구조로 교체**
>   (대표자 확정). 한 목록에 플랫폼 기술(시계열 공간 이해)·분석 기능(공정·물량)·
>   임무 유형(안전순찰·구조물점검)이 섞여 있어 줄 세우기 자체가 분류 오류였다.
>   임무 유형끼리의 순위 논쟁이 여기서 사라진다.
> - 2026-08-08 (1차) — 2026-08-07 개정의 오기 정정 (대표자 지적). 자율 안전순찰이
>   "KSI Safety 제품 축으로 이동"으로 적혔으나 사실이 아니다 — 이 제품의 범위에
>   그대로 남아 있다.
> - 2026-08-07 — §제품 정체성·§핵심 가치 개정 (ADR-KSI-016, 대표자 확정).
>   개정 근거와 대가는 ADR-KSI-016이 SSOT다.
> - 2026-07-24 — 최초 승인.
>
> **이 문서에 진행 상태를 적지 않는다.** 무엇이 진행 중이고 무엇이 막혔는지는
> `docs/goals/PHASE_REGISTRY.yaml`과 goal-ledger가 소유한다 — 몇 주 만에 뒤집히는
> 사실을 헌법에 넣으면 헌법을 계속 고쳐야 하고, 그러면 동결 문서의 의미가 없다.

## 제품 정체성

KSI Site Intelligence는 **건설 현장의 반복 비행 데이터를 자동으로 수집·정합·비교해, 현장의 상태·변화·물량을 시계열로 답하고 부족한 데이터의 재수집을 스스로 계획하는 폐루프(closed-loop) 현장 공간 인텔리전스 플랫폼**이다.

이 정의는 표어가 아니라 범위 판정 도구다 — "수집을 스스로 계획한다"가 임무 거버넌스를 만드는 근거이고, "비교해서 답한다"가 epoch 정합·측지·물량을 만드는 근거이며, 그 밖의 것은 만들지 않는 근거다.

현재 채택된 수집 장비는 Matrice 4D + RC Plus 2 + Manifold 3다. 장비는 제품 정의의 중심이 아니라 현재의 수집 수단이며, 수집 계층은 장비 교체를 견디도록 설계한다. 건설은 첫 번째 Vertical이다.

## 두 축과 폐루프

이 제품은 기능을 줄 세운 목록이 아니라 **두 축이 닫는 하나의 루프**다.

```text
KSI Site Intelligence Platform
│
├─ Site Intelligence Core ─────────────────────── WHAT / WHY
│   ├─ Spatial / Temporal World State
│   ├─ Reality ↔ Design
│   ├─ Change / Progress / Quantity
│   ├─ Uncertainty
│   └─ Mission Planning
│
└─ Autonomous Acquisition ─────────────────────── HOW
    ├─ Manifold Runtime
    ├─ Perception
    ├─ Local World Model
    ├─ Viewpoint / Path Decision
    └─ Mission Execution
```

**Core는 무엇을 왜 관측할지 정하고, Acquisition은 지금 어떻게 관측할지 정한다.**
어느 방향에서 접근할지, 어떤 거리에서 볼지, 가림이 생겼을 때 어디로 옮길지,
목표가 프레임에서 빠졌을 때 다시 잡을지는 현장에서 결정되어야 한다 — 그것을
서버가 정하려 들면 통신 지연·단절 때문에 로봇 시스템이 성립하지 않는다(§제어
철학 "서버가 프레임별 조종 명령을 보내지 않는다"가 같은 경계를 말한다).

두 축은 계약으로 닫힌다: 하행은 서명된 Mission Contract, 상행은 EventBundle ·
CoverageReport · ActionIntent다. **이 루프(Observe → Understand → Decide →
Re-observe)를 닫는 것 자체가 이 제품의 핵심 기술이며, 어느 한 축만으로는
제품이 성립하지 않는다.**

## 관측 임무 유형

자율 안전순찰·구조물 점검·매핑·재관찰은 **가치의 순위가 아니라 Acquisition
축이 수행하는 임무 유형**이다. 서로 경쟁하는 항목이 아니라 같은 수집 엔진의
형제이므로 이 문서는 그 사이에 순위를 두지 않는다.

임무 유형의 정본은 `ksi_domain.enums.MissionType`이다 — **여기 복제하지
않는다.** 각 유형이 어느 현장 상태에서 발급 가능한지는
`ksi_domain.mission_gating` 모듈 docstring이 SSOT다(INV-052).

실시간 안전관리를 CCTV·작업자 단말·중장비 위치·IoT 등 드론 밖 센서까지 확장하는
별도 제품 구상(KSI Safety)이 있다. 그것은 **이 제품의 안전순찰 임무를 대체하지
않는다** — 저쪽은 다중 센서 실시간 안전 운영 제품이고, 이쪽은 드론이 수행하는
현장 관측 임무다. 겹치지만 같은 것이 아니다(ADR-KSI-016 D2).

## 제어 철학

- DJI Flight Controller는 비행 안정화, 저수준 기체 제어, 반응형 충돌회피와 RTH를 담당한다.
- Manifold KSI Edge는 센서 동기화, 인지, 추적, 4D World Model, 위험판단, 재관찰, 로컬 경로·관측점 결정을 담당한다.
- KSI Core는 Mission Contract, 정책, 지도·모델 버전, 이벤트·증거·검토와 운영을 담당한다.
- 서버가 프레임별 조종 명령을 보내지 않는다.
- LLM은 비행 좌표와 안전 제어 명령을 직접 생성하지 않는다.

## 지도 철학

- 사전 지도는 Prior이며 현재 현실의 절대 진실이 아니다.
- 비행은 `map-informed, sensor-guarded` 방식이다.
- 고해상도 Mesh를 직접 충돌회피에 사용하지 않고 Terrain, Occupancy, ESDF, Surface, Semantic Layer로 컴파일한다.
- 지도는 좌표계, 수직기준, 버전, 시각, 불확실성, Provenance를 가진다.

## 참고 저장소 철학

- `KSI Platform`, `KSI-Terra`, `KSI-Scout`는 참고 구현이다.
- Domain, Algorithm, Test, Operational Knowledge는 채택할 수 있다.
- 과거의 중앙추론·수동비행·Dock 중심·평지지도 한계는 목표 아키텍처를 제약하지 않는다.
- 참고 저장소에서 직접 Import하지 않는다. 필요한 코드는 검토·추출·이식 후 KSI 소유 모듈로 만든다.


## Locked Product Defaults

- Coverage: 위험구역 100%, 필수자산 100%, 일반 접근영역 95%
- Battery Reserve: 현장별 설정, 기본 30%
- Offline: 서버단절 중 조건부 계속, RC Link Lost는 DJI 정책
- Evidence: Candidate/High/Critical 전후 3/5/10초
- Retention: 고객별 설정 + 승인된 기본값
