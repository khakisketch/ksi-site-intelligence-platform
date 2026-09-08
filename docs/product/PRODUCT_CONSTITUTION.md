# KSI Site Intelligence Product Constitution

> **개정 이력**
> - 2026-09-04 — Repository Normalization R0-R2에서 PSDK Liveview, bounded
>   `EDGE_UPLINK`, 원본 `MEDIA_PULL`/`MEDIA_UPLOAD`를 서로 다른 경로로 고정했다.
>   현재 정상 원본 ingress는 SD/저장매체→현장 PC→KSI 웹 업로드이며 중앙 지속
>   영상 수신은 핵심 제품 경로가 아니다(ADR-KSI-033).
> - 2026-08-30 — 판매 가능한 Civil Operations pilot의 실행 재현성과 자원 보호를
>   위해 제품 소유 runtime image의 OCI digest pin, Core 소유 versioned processing
>   resource policy와 발급 snapshot 결속을 확정했다. 이는 비용·정확도·외부 Cloud
>   승인이 아니라 운영 admission 경계다(ADR-KSI-032).
> - 2026-08-29 — 독립 검사점은 DSM별 봉인 CSV와 서버 직접 대조로만 오차한계 근거가
>   되며 사용자가 RMSE를 입력하지 않는 경계를 확정했다. 기존 Console·상대 물량·현장
>   수용 경계는 유지한다(ADR-KSI-031).
> - 2026-08-28 — 첫 토목 시계열·물량의 처리 일관성을 immutable KSI-managed
>   NodeODM profile, LandXML 설계면 ingress, fail-closed 비교 적합성으로 확정했다.
>   결과는 운영관리용 상대 물량이며, Console 정보구조와 FIELD/DJI capability 상태는
>   바꾸지 않는다(ADR-KSI-030).
> - 2026-08-23 (2차) — 현장 작업공간과 근거형 AX 계약을 확정했다. 전역 메뉴를
>   홈·현장·작업·확인 항목으로 줄이고 공간 결과·보고서·조사 이력을 현장에 귀속하며,
>   외부 AI는 근거 검증·별도 반출 동의·사람 결정권 경계를 따른다(ADR-KSI-026).
> - 2026-08-23 — Operations Console Home을 실제 근거 중심의 다현장 브리핑으로
>   확정했다. 현장 상세·작업 원장을 복제하지 않고 확인 현장과 사용자 의미가 있는
>   최근 업데이트만 표시한다(ADR-KSI-025).
> - 2026-08-21 (2차) — 사람의 KSI 업무 화면을 현장 노트북·컴퓨터의 하나의 반응형
>   **KSI Operations Console**로 확정했다. RC Plus 2/Pilot 2는 비행 전용이며 KSI
>   업무 UI를 표시하지 않는다. 모바일은 같은 Web의 제한 표현이다(ADR-KSI-024).
> - 2026-08-21 — 기본 제품을 **RC-first Connected Edge**로 확정했다. RC 인터넷은
>   새 임무 발급 전 필수, Manifold SIM은 선택 Add-on이며 활성 계약은 인터넷
>   단절만으로 무효화하지 않는다(ADR-KSI-023).
> - 2026-08-27 — Core의 권위를 Mission Intent·정책·검증된 최종 Flight Artifact의
>   revision/digest 결속으로 명확히 하고, 경로 compiler 독점은 요구하지 않기로 했다.
>   Observation Epoch와 증거 기반 Analysis Readiness를 별도 파생 계약으로 추가했다
>   (ADR-KSI-028/029).
> - 2026-08-20 — 첫 유료 제품을 **공정·상대 물량 폐루프**로 고정하고,
>   정상 현장 경로의 무파일 UX·LLM/사람 결정권 경계를 명시(ADR-KSI-022).
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

사용자 경험에서 KSI는 현장 데이터를 AI가 읽어 **무엇이 달라졌고, 왜 중요한지,
지금 무엇을 결정해야 하는지**를 검증된 근거와 함께 제시하고, 사용자의 결정을 다음
관측과 업무로 연결하는 AX 제품이다. AI는 사실 원장을 대체하거나 승인·Mission·비행
명령을 직접 만들지 않는다.

이 정의는 표어가 아니라 범위 판정 도구다 — "수집을 스스로 계획한다"가 임무 거버넌스를 만드는 근거이고, "비교해서 답한다"가 epoch 정합·측지·물량을 만드는 근거이며, 그 밖의 것은 만들지 않는 근거다.

현재 채택된 수집 장비는 Matrice 4D + RC Plus 2 + Manifold 3다. 장비는 제품 정의의 중심이 아니라 현재의 수집 수단이며, 수집 계층은 장비 교체를 견디도록 설계한다. 건설은 첫 번째 Vertical이다.

기본 운용은 RC Plus 2/Pilot 2가 사람의 비행 운영과 인터넷 gateway를, Manifold 3가
인터넷과 독립된 현장 지능을 맡는다. RC 인터넷은 새 임무 발급 전에 필요하지만
Manifold SIM은 선택형 Connectivity Add-on이다. 연결 유무와 비행 제어권을 섞지
않으며, 이미 유효하게 활성화된 계약은 서버 연결 단절만으로 취소하지 않는다.

사람의 KSI 업무 화면은 현장 노트북·컴퓨터에서 여는 하나의 반응형
**KSI Operations Console**이다. RC Plus 2/Pilot 2에는 KSI 업무 UI를 표시하지 않고
비행과 gateway 책임만 둔다. 스마트폰은 별도 제품이 아니라 같은 Console의 압축
표현이며 이벤트·분석·근거형 질의에는 사용할 수 있지만 Mission 발급·비행 준비·
WorkOrder·재관측 승인과 장비 전이를 정상 행동으로 제공하지 않는다.

Console Home은 다현장 포트폴리오의 입구다. KSI가 실제 원장에서 확인한 변화·결과·
사람 결정 대기만 현장별 근거와 한계로 요약하며, 공간 결과·보고서·조사 이력은 각
현장이 소유한다. 합성 현장 사진이나 기술 처리 로그로 경영 브리핑을 꾸미지 않는다.

첫 유료 제품은 **반복 관측 → 촬영 품질 보충 → 시점 간 변화·공정·상대 물량 →
근거형 질의 → 사람 승인 재관측**을 하나의 작업으로 닫는다. 계약 정산·측량급
정확도는 독립 checkpoint 검증 없이는 주장하지 않는다. 수동 KMZ 편집, USB 복구와
raw 파일 조작은 정상 사용자 흐름이 아니라 장애 복구와 검증을 위한 전문가 경로다.
단, ADR-KSI-035의 KSI planned artifact download/Pilot import·예외 편집은 Pilot-default
planning profile의 명시적 정상 행동이고, 현행 원본 ingress는 아래의 SD/현장 PC/Web
정상 경로를 따른다. 이 범위 정정은 자동 media, device capability 또는 flight safety
주장이 아니다.

첫 토목 처리의 기본 경로는 현장 PC가 SD/저장매체의 원본을 KSI 웹에 올리고,
고정된 `ksi-odm-civil-v1` profile로 재구성한 뒤, 검증된 설계면과 시점 간 상대
물량을 비교하는 것이다. profile, 원본 계보, CRS, 수직기준, Analysis Readiness,
설계면 revision/정규화 규칙 중 하나라도 미상 또는 불일치이면 수치를 추정하지 않고
비교를 막아 사유를 표시한다. LandXML TIN Surface와 GeoTIFF는 설계면 입력이고,
IFC→GeoTIFF 변환도 유지한다. DWG/DXF 직접 해석, 엔진·버전 혼합 비교, 독립
checkpoint 없는 절대 정확도 주장은 제품 범위가 아니다(ADR-KSI-030).

ADR-KSI-036의 새 첫 출시 방향에서는 고객이 자기 장비에서 외부 재구성 소프트웨어를
운영하고 KSI는 export artifact를 등록·검증·분석한다. 등록은 검증이나 정량 사용 가능과
동일하지 않으며, provenance/CRS/수직기준/품질/계보 또는 호환성이 미상이면 의존하는
주장을 제한한다. KSI-managed NodeODM와 그 기존 결과는 immutable managed/test·demo
범위로 유지한다. 외부 import가 ProcessingJob 성공, 봉인 raw bundle, source authority 또는
기존 profile identity를 위장할 수 없다. 2026-09-06 후속 확정에 따라 원본 사진은 고객
장비에 보관하며 정상 경로에서 전체 원본 업로드를 요구하지 않는다. KSI는 제출된
산출물과 provenance/품질 근거를 보관한다. 정사영상만의 등록을 허용하고 DSM·수직기준
등의 부족은 높이·물량처럼 의존하는 주장만 제한한다. 원본 미업로드 자체를 외부 결과의
영구 정량 금지 사유로 삼지 않는다. 지원 형식·실제 export 호환성·검증 정책은 구현과
별도 수용 증거가 필요하다(ADR-KSI-036 D4/D5).

독립 checkpoint가 있으면 사용자는 좌표계·수직기준·재구성 입력과 분리된 근거를
명시하고 원본 CSV를 봉인한다. KSI 처리 워커가 그 bytes와 대상 DSM bytes를 직접 읽어
전점을 대조하며, 사용자가 RMSE를 입력하는 표면은 두지 않는다. 이 software 검증은
운영 물량의 오차한계 근거이지 측량급·계약 정산 수용을 자동 승인하는 경로가 아니다
(ADR-KSI-031).

Civil Operations runtime은 애플리케이션 lockfile뿐 아니라 모든 제품 소유 외부
container image의 정확한 version과 OCI digest를 고정한다. 새 처리 작업은 Core가
봉인 원본의 파일 수·신고 byte·megapixel과 조직별 활성 작업 수를 versioned resource
policy로 판정한 뒤에만 발급한다. 클라이언트가 상한이나 override를 제출하지 않으며,
발급 당시 snapshot/digest를 journal에 결속한다. 이 admission은 처리 성공·비용 확정·
현장 정확도 또는 고객 데이터 배포 승인이 아니다(ADR-KSI-032).

## 데이터 경로 경계

- PSDK Liveview는 Manifold의 로컬 acquisition/perception 입력이다. Core·Vercel·
  Operations Console이 지속 영상을 중앙 수신하는 것은 핵심 제품 경로가 아니다.
- `EDGE_UPLINK`는 bounded EventBundle/EdgeBundle metadata와 object reference를 전달한다.
  Liveview frame, 원본 사진, RTK/POS stream 또는 공간 산출물 bytes를 운반하지 않는다.
- 현재 정상 원본 ingress는 `SD/저장매체 → 현장 PC → KSI 웹 업로드`다.
- 자동 원본 반출은 별도 `MEDIA_PULL`과 `MEDIA_UPLOAD` capability다. 정확한 adapter,
  권한, 조직/Site/Mission 결속과 물리 HIL 전에는 목표 경로이며 ordinary DPK는 OFF다.
- ingress adapter가 바뀌어도 SourceMedia 봉인, Observation Epoch temporal policy,
  Processing, 비교와 원본/파생 계보는 바뀌지 않는다(ADR-KSI-033, INV-018/051/060).

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
ADR-KSI-035의 Pilot-default profile에서만, Core의 결정적 planner는 사전
`how to observe` 후보(coverage·terrain/known-structure·transit intent)를 만든다. 이는
현장/비행 중의 관측점·경로 판단, 실제 비행 실행, 회피 또는 RTH의 권한을 Core로 옮기지
않으며, missing prior data를 안전 보증으로 바꾸지도 않는다.
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
- KSI Core는 Mission Intent, 서명된 Mission Contract, 정책, 지도·모델 버전,
  검증된 최종 Flight Artifact의 revision/digest 결속, 이벤트·증거·검토와 운영을 담당한다.
  Core는 경로 compiler를 독점하지 않지만, 어느 artifact가 정책을 통과해 계약에
  결속됐는지의 권위는 유지한다.
- 서버가 프레임별 조종 명령을 보내지 않는다.
- LLM은 비행 좌표와 안전 제어 명령을 직접 생성하지 않는다.
- LLM은 검증된 서버 결과를 설명하고 재관측 초안을 요청할 수 있으나, 임무 승인·
  발급 권한은 갖지 않는다. 사용자가 재관측을 승인하고 Core의 결정적 Planner가
  실행 계약을 만든다.

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
