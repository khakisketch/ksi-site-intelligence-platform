# KSI Site Intelligence Product Constitution

> **개정 이력**
> - 2026-09-30 — ADR-KSI-038: 제품 정체성을 외부 에이전트·산업용 소프트웨어가 사용하는
>   공간데이터·분석 기반으로 명확화한다. 데이터 제공과 분석을 두 제품 경로로 두고,
>   주간 토공 파일럿은 첫 분석 사례로 유지한다. 문서·장기 계획 반영만 승인됐으며 개발은 보류다.
> - 2026-09-20 — ADR-KSI-037 implementation-condition amendment: 외부 재구성 산출물은
>   KSI GIS worker의 고정 profile로 측정하고, checkpoint 부재의 잠정 수치와 알려진 실패의
>   보완 필요를 구분한다. 기존 strict V1 정책은 유지한다.
> - 2026-09-20 — ADR-KSI-037로 제품 우선순위를 API-first 현장 관측·분석 근거 서비스로
>   정했다. 첫 완결 MVP는 WorkArea별 주간 2시점 관측 지형 물량 변화 검토다. API·향후 MCP·UI는
>   같은 계산 기록을 조회하며, 자율 취득·BIM 원본 편집·재구성 엔진은 이 MVP의 실행 약속이
>   아니다. 이 개정은 current `EXT-VAL` slice, 기존 runtime, 불변식 또는 정량 관문을 바꾸지 않는다.
> - 2026-09-20 — ADR-KSI-036 D6로 첫 출시의 재구성 책임을 더 명확히 했다. 회사의
>   RTK-equipped Matrice 4D는 초기 현장 검증 장비이고, 고객이 통제하는 현장 PC의 DJI
>   Terra는 초기 MVP 재구성 참조 흐름이다. KSI는 제출된 파생 산출물을 검사·비교·계측·
>   업무/재관측으로 연결하며 자체 사진측량 엔진이나 고객 production 재구성 서비스를
>   약속하지 않는다. 이 문구는 license/export/RTK 정확도/현장 수용을 검증하지 않고,
>   managed NodeODM·ProcessingJob·source-authority 규칙도 바꾸지 않는다.
> - 2026-09-04 — Repository Normalization R0-R2에서 PSDK Liveview, bounded
>   `EDGE_UPLINK`, 원본 `MEDIA_PULL`/`MEDIA_UPLOAD`를 서로 다른 경로로 고정했다.
>   당시 source-media ingress는 SD/저장매체→현장 PC→KSI 웹 업로드였으며 중앙 지속
>   영상 수신은 핵심 제품 경로가 아니다(ADR-KSI-033). 외부 첫 출시의 결과 경로는
>   2026-09-20 ADR-KSI-036 D6을 따른다.
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
> **이 문서에 진행 상태를 적지 않는다.** `docs/superpowers/product-state.md`와 그 named
> slice ledger는 현재 제품 Slice·Backlog와 활성 bounded checkout task가 없을 때의 제품 수준
> 다음 작업 선택을 소유하고 slice close에서만 갱신한다. 활성 checkout task는 Git 재검증 뒤
> checkpoint와 named task ledger로 재개하며 Slice를 닫거나 우선순위를 바꾸지 않는다.
> `docs/goals/PHASE_REGISTRY.yaml`은 capability-track index다. 이 문서나 과거 next action은
> 외부 권한을 만들지 않는다.

## 제품 정체성

KSI Site Intelligence Platform은 **외부 재구성 엔진이 생성한 현장 공간데이터를
등록·검사·구조화하고, 필요한 공간데이터와 재현 가능한 분석 결과를 API·MCP로 제공하여
고객의 에이전트와 산업용 소프트웨어가 재사용하게 하는 데이터·분석 기반**이다.
제품은 공간데이터 제공과 서버 분석의 두 경로를 갖는다. 공통 Core가 자산·시점·구역·버전,
권한·용도별 적합성·작업·결과·계보·근거를 소유하며 UI·MCP·향후 SDK/CLI는 그 계약을
사용한다. 분석 파사드와 클라이언트는 별도 계산·권위를 만들지 않는다(ADR-KSI-038).

첫 플랫폼 검증은 DSM·정사영상으로 같은 현장 데이터의 분석 경로와 외부 코드의 구역 데이터
활용 경로를 모두 입증한다. Point cloud·Mesh·외부 분석 레이어·산업별 어댑터는 후속
계약·수용 대상이다. 등록·조회·추출·분석·정확도 평가·사람 검토는 서로 다른 상태다.
표준·포맷 지원이나 구현 완료는 이 정의에서 추론하지 않는다. 상세 책임·미결정 항목은
[ADR-KSI-038](../architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md), 장기 과제는
[SDP-20260930](../superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md)을 따른다.

사용자 경험에서 KSI는 현장 데이터를 AI가 읽어 **무엇이 달라졌고, 왜 중요한지,
지금 무엇을 결정해야 하는지**를 검증된 근거와 함께 제시하고, 사용자의 결정을 다음
관측과 업무로 연결하는 AX 제품이다. AI는 사실 원장을 대체하거나 승인·Mission·비행
명령을 직접 만들지 않는다.

이 정의는 범위 판정 도구다. Core는 Site·WorkArea·Observation Epoch·버전의 지속적 매핑,
입력 admission, 재현 가능한 계산과 근거, 권한, 결과 조회를 소유한다. LLM은 검증된 도구를
조율할 수 있지만 수치 사실을 추정하거나 계산·사람 검토·발행을 대체하지 않는다.

RTK-equipped Matrice 4D는 초기 현장 검증 장비이자 관측 입력 참조다. 장비는 제품 정의의
중심이 아니며, 고객 통제 현장 PC/DJI Terra 재구성 흐름도 입력 참조일 뿐 KSI의 API·계산
엔진·license/export 지원 약속이 아니다. 건설과 토공 운영이 첫 Vertical이고,
디지털·스마트건설 소프트웨어 파트너는 통합 고객이다.

장기 취득·현장 검증 profile에서는 RC Plus 2/Pilot 2가 사람의 비행 운영과 인터넷 gateway를,
Manifold 3가 인터넷과 독립된 현장 지능을 맡는다. 이 profile은 API-first MVP의 입력
admission·계산·결과 조회 전제가 아니다. RC 인터넷은 새 임무 발급 전에 필요하지만
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

첫 분석 사례의 완결 MVP는 **같은 WorkArea의 주간 2시점 관측 지형 물량 변화 검토**다.
그 수용만으로 공간데이터 제공을 포함한 플랫폼 전체 완료를 주장하지 않는다. 동일한
Site·WorkArea·mapping/template를 재사용해 `t0→t1` 다음 `t1→t2` 요청을 수행하고, 각
결과는 출처·좌표·변환·프로파일·공통 유효/제외 영역과 함께 기록한다. 기하 변화,
증가·감소·순물량 또는 설계 차이는 승인 작업·진척·정산·품질·측량·현장 수용을 증명하지
않는다. 독립 checkpoint는 정확도 근거일 뿐 그것만으로 계약 정산·검측·품질 승인을 만들지
않으며, MVP 약속은 운영 검토용 관측 변화다. 수동 KMZ 편집, USB 복구와
raw 파일 조작은 정상 사용자 흐름이 아니라 장애 복구와 검증을 위한 전문가 경로다.
MVP 수용에는 하나의 명시적으로 선택·검증된 인증 외부 agent/MCP client와 재사용 가능한
예시 workflow가 UI/API와 같은 KSI 계산 결과 또는 blocker 기록을 반환하는 것도 포함한다.
이는 모든 client 지원이나 현재 MCP runtime을 뜻하지 않는다.
단, ADR-KSI-035의 KSI planned artifact download/Pilot import·예외 편집은 Pilot-default
planning profile의 명시적 정상 행동이다. 외부 첫 출시 결과 ingress는 아래의 고객
현장 PC 재구성→파생 산출물/근거 등록 경로를 따르며, SD/현장 PC/Web raw 경로는
managed/test 또는 별도 승인 source-media scope다. 이 범위 정정은 자동 media, device
capability 또는 flight safety 주장이 아니다.

고정된 `ksi-odm-civil-v1` profile로 원본을 재구성하고 설계면과 시점 간 상대 물량을
비교하는 경로는 기존 **KSI-managed/test·demo** 토목 처리다. 그 profile, 원본 계보,
CRS, 수직기준, Analysis Readiness, 설계면 revision/정규화 규칙 중 하나라도 미상 또는
불일치이면 수치를 추정하지 않고 비교를 막아 사유를 표시한다. LandXML TIN Surface와
GeoTIFF는 설계면 입력이고, IFC→GeoTIFF 변환도 유지한다. DWG/DXF 직접 해석,
엔진·버전 혼합 비교, 독립 checkpoint 없는 절대 정확도 주장은 제품 범위가 아니다
(ADR-KSI-030).

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

ADR-KSI-036 D6의 초기 재구성 입력 참조 흐름은 RTK-equipped Matrice 4D 촬영 → 고객이
통제하는 현장 PC의 DJI Terra 재구성 → 파생 산출물·근거의 KSI 등록/검사 → 호환되는
변화·높이·상대 물량 분석 → 사람 검토와 재관측이다. RTK FIX는 촬영 근거일 뿐 완성
지도·물량의 정확도나 정산 적합성을 보장하지 않는다. Terra의 license, export 호환성,
KSI provider 연동, 자동화, 현장 정확도는 이 결정으로 승인·검증되지 않는다. KSI의
가치는 사진 재구성 자체가 아니라 사용 적합성, 근거, 비교, 업무와 다음 관측을 연결하는
데 있으며, 이 경계는 Acquisition/Edge의 승인된 자율 roadmap을 제거하지 않는다.

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
- 외부 첫 출시의 정상 결과 ingress는 `M4D 촬영 → 고객 현장 PC 재구성 → 파생 산출물과
  bounded provenance/품질 근거의 KSI 등록`이다. 원본 사진은 고객 장비에 남는다.
- `SD/저장매체 → 현장 PC → KSI 웹`의 raw ingress는 기존 managed/test 또는 별도 승인
  source-media 경로다. 이를 외부 첫 출시의 전체 raw-upload 필수조건으로 읽지 않는다.
- 자동 원본 반출은 별도 `MEDIA_PULL`과 `MEDIA_UPLOAD` capability다. 정확한 adapter,
  권한, 조직/Site/Mission 결속과 물리 HIL 전에는 목표 경로이며 ordinary DPK는 OFF다.
- ingress adapter가 바뀌어도 SourceMedia 봉인, Observation Epoch temporal policy,
  Processing, 비교와 원본/파생 계보는 바뀌지 않는다(ADR-KSI-033, INV-018/051/060).

## 장기 관측·취득 축

Site Intelligence Core와 Autonomous Acquisition은 장기 관측·취득 roadmap의 두 책임 축이다.
API-first 공간데이터 제공과 첫 주간 2시점 분석 사례는 Acquisition 자동 실행 없이
검증하는 플랫폼 범위다. 아래의 Mission/Edge 내용은 그 범위를 보존하는 미래 호환 경계이며, 자동
로봇·비행 실행을 현재 제품 약속으로 만들지 않는다.

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

장기 취득 축의 계약은 하행의 서명된 Mission Contract와 상행의 EventBundle ·
CoverageReport · ActionIntent다. API-first 플랫폼은 관측 자산 → 용도별 적합성/권한 →
구역 데이터 또는 분석 결과·근거 → 외부 활용/사람 검토 → 다음 시점 재사용을 기록한다.
Acquisition은 그 기록에 관측을 공급하는 별도 roadmap이다.

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
