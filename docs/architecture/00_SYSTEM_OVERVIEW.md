# KSI Site Intelligence — 시스템 전체 구성 (한 장 개요)

> 2026-08-23 대표자 확정(ADR-KSI-023·024·026 반영). 이 문서는 **목표 구성도**와 **현재 도달점**을 한 장에
> 담는다 — 둘을 섞어 말하지 않는다(green≠작동 원칙). 개별 결정의 근거는 각 ADR이
> 정본이고, 이 문서는 그 결정들이 모여 만드는 전체 그림이다.

## 한 문장 정의

**KSI는 반복 관측한 현장 데이터를 AI가 읽어 무엇이 달라졌고 왜 중요한지, 지금
무엇을 결정해야 하는지를 근거와 함께 제시하고, 사람의 결정을 다음 관측과 업무로
연결하는 현장 AX 시스템이다.**

## 전체 구성도 (목표)

```text
  현장 노트북/컴퓨터                         건 설 현 장
┌─────────────────────┐         ┌──────────────────────────────────────┐
│ KSI Operations      │   TLS   │  Matrice 4D        실제 비행·촬영·RTK │
│ Console             ├────┐    │      │ E-Port / PSDK                  │
│ · 업무·검토·승인     │    │    │  Manifold 3        KSI Edge SW        │
│ · 분석·Copilot       │    │    │   · 임무 계약 수신·검증 (서명·TTL)     │
└─────────────────────┘    │    │   · 관측 품질·누락·재관측 판단          │
                           │    │   · 통신두절 시 로컬 지속(저장후전달)   │
                           │    └──────┬───────────────────────────────┘
                           │           │ DJI 기체↔RC 무선 링크
                           │    ┌──────▼───────────────────────────────┐
                           │    │  RC Plus 2 / DJI Pilot 2              │
                           │    │   · 조종자 비행 운용(이륙 승인은 사람) │
                           │    │   · 지상 통신 게이트웨이               │
                           │    │   · KSI 업무 UI 없음                   │
                           │    └──────┬───────────────────────────────┘
                           │           │ RC Wi-Fi(기본) / RC 4G(대체·보조)
                           │           │
                           └─────┬─────┘
                                 ▼
        ┌──────────────────────────────────────────────┐
        │  외부 배포 KSI CLOUD                          │
        │   ① CORE          현장·임무·계약·권한          │
        │   ② SPATIAL       사진→정사영상·DSM·3D         │
        │   ③ INTELLIGENCE  이전↔현재·설계↔현재          │
        │   ④ PLANNER       어디를 다시 볼지             │
        └──────────────────────────────────────────────┘
```

RC의 인터넷 readiness와 Operations Console의 사용자 세션·접속 상태는 서로 다른
관측값이다. RC/Pilot 2에는 KSI 업무 화면을 넣지 않는다. Operations Console은 현장
노트북·컴퓨터를 기본으로 하며 같은 반응형 Web을 모바일에서도 제한된 조회·트리아지·
분석·Copilot 용도로 사용할 수 있다.

Operations Console의 전역 업무는 `홈·현장·작업·확인 항목`이다. 변화·상대 물량·
공간 산출물·보고서·조사 이력과 저장형 KSI AI 대화는 모두 현장 작업공간에 귀속한다.
Copilot은 검증된 구조화 결과와 citation metadata만 외부 provider에 전달하며 승인,
Mission 발급, 비행 좌표·명령 권한을 갖지 않는다. 외부 AI 반출 동의가 없는 현장은
호출을 fail-closed한다.

<!-- ADR-KSI-024 이전 구성도는 위의 역할 분리 구성도로 대체되었다. -->

```text
                        건 설 현 장 (장비 내부 경로 상세)
        ┌──────────────────────────────────────┐
        │  Matrice 4D        실제 비행·촬영·RTK │
        │      │ E-Port / PSDK                  │
        │  Manifold 3        KSI Edge SW        │
        │   · 임무 계약 수신·검증 (서명·TTL)     │
        │   · 관측 품질·누락·재관측 판단          │
        │   · 통신두절 시 로컬 지속(저장후전달)   │
        └──────┬───────────────────────────────┘
               │ DJI 기체↔RC 무선 링크
        ┌──────▼───────────────────────────────┐
        │  RC Plus 2 / DJI Pilot 2              │
        │   · 조종자 비행 운용(이륙 승인은 사람) │
        │   · 지상 통신 게이트웨이               │
        └──────┬───────────────────────────────┘
               │ RC Wi-Fi(기본) / RC 4G(대체·보조)
        ┌──────▼───────────────────────────────┐
        │  KSI SERVER                           │
        │   ① CORE          현장·임무·계약·권한  │
        │   ② SPATIAL       사진→정사영상·DSM·3D │
        │   ③ INTELLIGENCE  이전↔현재·설계↔현재  │
        │   ④ PLANNER       어디를 다시 볼지     │
        └──────┬───────────────────────────────┘
               │ 다음 임무 (서명된 계약 + 경로)
               ▼
           Matrice 4D  ──────────────── ↺
```

새 KSI Mission 발급 전에는 RC 인터넷이 필수다. 이미 서명·활성화된 계약은 비행 중
RC 인터넷 단절만으로 무효화하지 않는다. Manifold SIM은 선택형 Connectivity Add-on이며,
장착 시 Edge 이벤트·원본 업로드가 Manifold 직접 HTTPS를 우선한다. SIM이 없어도
Manifold의 로컬 지능과 outbox는 동일하게 동작한다.

## 핵심 설계 원칙 — 폐루프는 두 개다

하나의 중앙제어 시스템으로 만들지 않는다. 시간축이 다른 두 지능을 분리한다.

**① 기체 안의 빠른 폐루프 (Manifold 3, 수초 단위)**
"사진이 흔들렸다 / A구역이 가려졌다 / 각도가 안 맞다 → 옆으로 이동해 다시 보자."
이 판단을 서버까지 보내 답을 기다리지 않는다 — Manifold이 처리하고, 통신이
끊겨도 이 루프는 계속 돈다. (근거: CLAUDE.md Control boundaries,
`01_ARCHITECTURE_AND_CONTROL`, ADR-KSI-005 결정 3)

**② 서버의 큰 폐루프 (KSI Server, 비행·일 단위)**
"어제와 비교하니 A구역이 이상하다 / B구역 토공량 확인 필요 / C구역 데이터 부족
→ 다음 비행에서 여길 보자." 여러 비행·여러 날짜를 비교하는 긴 시간축 판단이다.

## 데이터 경로 — 역할과 크기를 함께 나눈다 (ADR-KSI-023)

| 데이터 | RC 기본형 | Connectivity Add-on |
|---|---|---|
| KSI 작업·검토·승인 | Operations Console | 동일 |
| 비행 운영 | RC Plus 2 / Pilot 2 | 동일 |
| Mission Contract | 검증된 Cloud 하향, 실패 시 조건부 MSDK Bridge | Manifold 직접 HTTPS 우선 |
| Edge 이벤트·품질 | 검증된 Pilot Cloud 업링크 | Manifold direct 우선, Pilot 경로 fallback |
| 전체 원본 | 착륙 후 검증된 RC media 경로 | 착륙 후 direct 우선 |

어떤 경로도 실기 증거 전에는 `VERIFIED`가 아니다. 전송 경로가 바뀌어도 같은
idempotency key와 digest를 사용하고, 대용량 원본은 **store-and-forward**로 유실 없이
재개한다.

## MSDK의 위치 (ADR-KSI-023·024)

기본 제품 경로는 `KSI Server ↔ RC Plus 2/Pilot 2 ↔ M4D + Manifold 3`다. MSDK는
Cloud 하향 전달 또는 자동 media 회수가 M4D + RC Plus 2 실기에서 성립하지 않을
때만 도입하는 preflight/postflight Field Bridge다. 비행 시작·Virtual Stick·경로·
짐벌 제어는 넣지 않는다.
USB·SD·수동 KMZ/사진 전달은 정상 제품 경로가 아니라 복구·검증 경로다.

## 책임 분담

| 구성 | 책임 |
|---|---|
| Matrice 4D | 움직이고 촬영 (저수준 비행·회피·RTH는 DJI FC 소유) |
| Manifold 3 | 현장에서 보고 판단 (빠른 폐루프) |
| RC Plus 2 + Pilot 2 | 비행 운용과 Cloud gateway (이륙 승인은 항상 사람, KSI 업무 UI 없음) |
| KSI Operations Console | 현장 노트북·컴퓨터에서 업무·검토·승인·분석·Copilot 제공 |
| KSI Core | 현장·임무·서명 계약·권한·감사 |
| Spatial Processing | 사진 → 공간정보 (NodeODM 재구성) |
| KSI Intelligence | 무엇이 달라졌는지 판단 (변화·토공량·공정률·이상영역) |
| Planner | 어디를 다시 볼지 결정 → 다음 임무 |
| Dashboard | 하나의 반응형 Operations Console과 모바일 제한 UX |

## 현재 도달점 (2026-08-21 갱신 — 목표와 구분해 적는다)

| 구성요소 | 상태 |
|---|---|
| ① CORE | **가동** — 현장·임무·계약·권한·이벤트 전부 구현·검증 |
| ② SPATIAL | **가동** — 업로드→재구성→정사영상·DSM·토공량 종단 완주, 입구(촬영 회수)도 자동화됨(아래 ingest 행) |
| ③ INTELLIGENCE | **가동** — 변화탐지·설계대비·공정률 계산 완성 |
| ④ PLANNER | **소프트웨어 종단 완주** — 경계→매핑→재구성→공간모델(AOL-1), 변화영역→밀도 도출→재관측 발급→모델 갱신(AOL-2) 모두 사람이 현장 상태를 손으로 옮기지 않고 통과. 재관측 승인은 계속 사람 소유 |
| Manifold 3 Edge SW | **소프트웨어 검증 완료, 실기 0회** — DPK 설치·기동을 실기에서 시도한 적 없음 (P0 과제) |
| Acquisition profile/readiness | **소프트웨어 구현·rollout OFF** — 현장별 RC/Dock profile, 만료 heartbeat, 장치 binding, 기능별 capability gate. 실장비 receipt와 기존 Site migration 전에는 production 발급 강제 flag를 켜지 않음 |
| WorkOrder Acquisition coordinator | **소프트웨어 구현** — 승인 회차별 내구성 있는 AcquisitionRun, Mission lineage, capability별 Gateway operation receipt, 미디어·Processing 사실 원장을 합친 진행상태 API. 자동 Mission 생성은 HIL 전 비활성이고 비행 계획값을 추측하지 않음 |
| RC 게이트웨이 (dji-gateway) | **소프트웨어 기반 구현** — 기능별 port/router, v1.2/v1.3 receipt journal과 flag-OFF gate. 실제 Cloud/PSDK/direct adapter와 장비 coordinator는 미구현 |
| Operations Console 현장 작업공간 | **소프트웨어 구현** — 전역 4개 메뉴, 현장 5개 영역, 조직 범위 Workspace projection, 작업·확인 항목, 저장형 AI 대화·근거 브리핑을 연결. 390/768/1024/1440 실제 브라우저 시각 승인과 외부 provider 실연동은 별도 관문 |
| Operations Console readiness UI | **소프트웨어 구현** — RC 인터넷·Manifold·직접망·계약·원본 동기화와 Console 접속을 분리 표시. 실제 heartbeat 연결은 HIL 전 `NOT_VERIFIED` |
| Grounded Site AI | **기본 OFF·소프트웨어 구현** — OpenAI 호환 tool-call adapter, 저장형 대화, citation 검증, `aiEgressAllowed` gate, durable `BLOCKED` 복구 상태. 승인된 외부 AI 계정·고객 데이터 사용은 아직 없음 |
| 온보드 임무 실행 (PSDK WaypointV3) | **능력 존재 · KSI 미사용(정책)** — KMZ 업로드+START 로 시동·이륙까지 가는 API가 핀된 PSDK 3.16.0에 있다. 기종 지원은 호출 1회로 판별(FIELD-0). 안전 게이트가 사용을 차단하며, 허용 여부는 FIELD-1 이후 별도 결정(ADR-KSI-020 D2·D3) |
| 드론→서버 자동 ingest | **가동(소프트웨어)** — `tools/ingest_watch.py` 가 촬영 회수를 자동 트리거. 기체→지상 회수 자체는 여전히 SD카드 수동 오프로드(P1 과제 중 남은 부분) |
| 폐루프 종단 완주 | **소프트웨어 1회 완주(2026-08-15), 실기 0회** — 목표 원장 `autonomous-acquisition-closed-loop` (strict). 실기 완주는 Manifold HIL(P0)이 관문 |

현재 실행 순서는 Operations Console·현장 AX 소프트웨어/UX 관문 → 외부 합성-data
Staging → RC 기본형 HIL → FIELD-0a/0b/1/2다. 이 순서 변경은 장비 capability 완료
등급을 올린다는 뜻이 아니다. 실제 DJI 다섯 capability와 폐루프 실증은 계속
`NOT_VERIFIED`다. 상세는 ADR-KSI-018·023·026과 목표 원장 참조.

## 관측 자율성 3단계 (ADR-KSI-019)

위 "④ PLANNER" 행을 성숙도 축으로 분해한 것이다 — PRD §25의 Phase 번호와 **다른
축**이므로 `AOL-` 접두사를 쓴다.

| 단계 | 내용 | 현재 |
|---|---|---|
| AOL-1 매핑 자율 | 경계 → 매핑 경로 → 승인 → 실행 → 촬영 → 재구성 → 공간모델 등록 | **소프트웨어 종단 완주**(2026-08-15) — 사람이 현장 상태를 옮기지 않는다. 남은 GAP: 임무→기체 전달이 여전히 수동(G3, M4D 실기 확인 관문) |
| AOL-2 분석 기반 재관측 | 공간모델+분석 → 대상 영역 → 재관측 경로 → 승인 → 재촬영 → 모델 갱신 | **소프트웨어 종단 완주**(2026-08-15) — 변화 정도에 맞춘 촬영 밀도(등급·고도·중복도)까지 서버가 도출해 발급까지 이어진다. 발급 자체는 여전히 사람이 위저드를 끝까지 누른다(의도된 경계, D4) |
| AOL-3 공간모델 인지 비행 | DSM/Point Cloud 를 경로계획 입력으로(지형추종·이격·장애물·적응촬영) | **부분 착수** — 지형추종 고도 계산기는 있으나 KMZ 발급 경로에 미배선(FIELD-3). 구조물 이격·장애물 우회·동적 재계획은 `NOT CURRENT PRODUCT SCOPE`(ADR-KSI-020 D6 — 기술적 불가가 아니라 DJI 온보드 기능과 중복·책임 과다) |

## 실기 순서 (ADR-KSI-020 §5)

```text
FIELD-0a  비행파일 수용성 + 카메라 실측        [비행 없음 · 매니폴드 불필요 · 조종기만]
          우리 KMZ 를 Pilot 2 가 임포트하는가 / Pilot 2 가 내보낸 KMZ 와 태그 대조
          지상에서 사진 1장 → EXIF 로 실제 카메라 상수 확보
              │
              ▼
FIELD-1   첫 실제 매핑 비행 → 실제 M4D 사진 → 재구성 → 실제 공간모델
              │
              ▼
FIELD-2   분석 → 재관측 → 2회차 비행 → 모델 갱신              = AOL 현장 실증
              │
              ▼
FIELD-3   실제 DTM 기반 웨이포인트별 고도(지형추종) 배선

FIELD-0b  매니폴드 통합 — 앱 기동 → PSDK 연결 → 임무 실행 API 기종 판별
          위 흐름과 **병렬**이며 서로의 전제가 아니다        [비행 없음 · 매니폴드 필요]
```

ADR-KSI-023 승인으로 RC-first 계약·구조·증거 기반의 소프트웨어 작업은 재개됐다.
그러나 FIELD-1까지의 실제 실행은 기존 방식(사람이 Pilot 2로 시작)으로 닫고,
새 장비 capability를 실기 증거 없이 열지 않는다.

Manifold는 확정 제품 구성의 필수 요소다. 다만 FIELD-1의 기초 매핑 비행 자체는
기존 Pilot 2 실행·복구 경로로 먼저 검증할 수 있다. 이것은 기본 제품에서 Manifold를
제외한다는 뜻이 아니며, Capture Quality Recovery와 Connected Edge product acceptance는
FIELD-0b/후속 HIL 증거가 있어야 닫힌다.

두 단계 모두 완료 등급은 `Backend Ready`이지 `HIL Proven`이 아니다(ADR-KSI-018
완료 판정 규율) — 종단 시험의 커버리지 보고·재구성 워커는 계약대로 행동하는
대역이고, 실제 비행은 여전히 0회다.

반순환 불변식(ADR-KSI-019 D3): **최초 매핑 임무는 공간모델 없이 생성 가능해야
한다** — 경로 생성기에 공간모델을 필수 입력으로 넣는 변경은 금지다.

## 관련 문서

- 제어 권한·경계: `01_ARCHITECTURE_AND_CONTROL.md`, CLAUDE.md Control boundaries
- DJI 연동 이원화: `ADR-KSI-004` · 연결 계층: `ADR-KSI-005` · 임무 이원 산출물: `ADR-KSI-007`
- 과거 RC 웹뷰·MSDK 판단: `ADR-KSI-017` · Phase 3 재정의·폐루프 최우선: `ADR-KSI-018`
- RC-first 제품·기능별 연결: `ADR-KSI-023` · Operations Console 화면 경계: `ADR-KSI-024`
- 현장 작업공간·근거형 AX: `ADR-KSI-026`
- 소스 경계: `04_SOURCE_CODE_BOUNDARIES.md`
- 관측 자율성 3단계·순서 고정·반순환 불변식: `ADR-KSI-019`
