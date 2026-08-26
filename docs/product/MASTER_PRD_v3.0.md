# KSI Site Intelligence Platform — Master Product & System Requirements

> 문서 버전: **3.0.0**  
> 기준일: **2026-07-24**  
> 상태: **APPROVED / PRODUCT DECISION FREEZE / IMPLEMENTATION BASELINE**  
> 공식 플랫폼명: **KSI Site Intelligence Platform**  
> 고객용 제품명: **KSI Site Intelligence**  
> 기준 하드웨어: **DJI Matrice 4D + DJI RC Plus 2 + DJI Manifold 3**  
> 기존 참고 자산: **KSI Platform / KSI-Terra / KSI-Scout**  
> 대상 독자: 제품 책임자, 설계자, 웹/백엔드/엣지/AI/공간정보 개발자, Claude Code, Codex 및 기타 개발 에이전트

> **2026-08-21 승인 addendum(ADR-KSI-024):** 사용자 프론트엔드는 하나의 반응형
> `KSI Operations Console`이다. Pilot 2는 비행 전용이며 KSI 업무 UI를 표시하지 않는다.
> 1024px 미만은 조회·이벤트 트리아지·분석·Copilot용 제한 표현이고, Mission 발급·승인·
> 상태 전이·복구 행동은 현장 노트북/컴퓨터에서 수행한다. 이 addendum은 아래의 과거
> “모바일 임무 생성” 문구를 대체한다.

---

# Table of Contents

- KSI Site Intelligence Platform — Master Product & System Requirements
- 1. 최종 제품 정의
- 2. 핵심 제품 결정
- 3. 목표와 비목표
- 4. 사용자와 핵심 업무
- 5. 제품 기능 카탈로그
- 6. 서비스 수명주기: Continuous Spatial Intelligence Loop
- 7. 사용자 경험 및 메뉴
- 8. 제어권과 안전 경계
- 9. KSI Edge Autonomy Runtime
- 10. Geo-Referenced Perception — 핵심 IP 1
- 11. 4D Site World Model — 핵심 IP 2
- 12. Equipment Intelligence & Dynamic Risk — 핵심 IP 3
- 13. Active Perception & Viewpoint Planning — 핵심 IP 4
- 14. Local Planning, 회피와 임무복구
- 15. Mapping과 Continuous World Model
- 16. 구조물·자산 점검
- 17. Event, Finding, Action Workflow
- 18. Data Flywheel와 MLOps
- 19. Core Backend 및 데이터 아키텍처
- 20. DJI Integration과 Capability Gate
- 21. 비기능 요구사항
- 22. 보안·개인정보·배포
- 23. 시장 적용과 산업 확장
- 24. 개발 구조와 저장소
- 25. 구현 단계
- 26. 제품 완료 기준
- 27. 시험전략
- 28. 주요 위험과 대응
- 29. 에이전트 구현 규칙
- 30. 제품 결정 동결과 변경관리
- 31. 공식/시장 참고자료
- Appendix A. 핵심 요구사항 ID
- Appendix B. Final Locked Requirement IDs

---

## 0. 문서 목적과 규범

이 문서는 **KSI Site Intelligence Platform**의 최종 제품 결정, 시스템 경계, 사용자 흐름, Manifold 기반 Edge Autonomy, 4D 공간인지, 자체 공간처리, 데이터·학습 체계와 완료 기준을 정의한다. KSI Site Intelligence는 이 플랫폼을 현장 사용자에게 제공하는 통합 제품이다.

- `MUST`: 제품 또는 안전성 확보를 위해 필수다.
- `SHOULD`: 특별한 사유가 없다면 적용한다.
- `MAY`: 선택 또는 후속 확장이다.
- `VERIFIED`: 공식 문서 또는 실기로 확인됐다.
- `SPIKE_REQUIRED`: 공식 문서만으로 확정할 수 없어 실제 장비 검증이 필요하다.
- `BLOCKED`: 외부 제약 또는 미지원으로 현재 구현을 확정할 수 없다.

이 문서는 “초기 데모를 빠르게 만드는 방법”이 아니라 **궁극적 제품 구조를 처음부터 유지하면서 기능 깊이를 단계적으로 확장하는 방법**을 정의한다. 2026-07-24 제품책임자 인터뷰에서 확정된 결정은 본문에 잠금 결정으로 반영됐으며, 제품 범위와 책임 경계에 관한 추가 해석은 구현자가 임의로 변경할 수 없다. 단기 일정 때문에 서버 중심 실시간 제어, 수동 장비 반경, Bounding Box 직접 노출 등 기술적 우회구조를 핵심 아키텍처로 채택해서는 안 된다.

---

# 1. 최종 제품 정의

## 1.1 한 문장 정의

> **정본은 `docs/product/PRODUCT_CONSTITUTION.md` "제품 정체성"이다** (docs/00_READ_FIRST.md
> 권위 순서상 이 문서보다 우선). 아래는 그 정의를 그대로 옮긴 것이며, 이 절을 고칠 때는
> 헌법을 먼저 고치고 여기를 동기화한다 — 반대 방향으로 갈리면(2026-08-11 실제로
> 발생했던 상태) 이 문서를 읽는 사람이 폐기된 옛 범위를 정본으로 오인한다.

**KSI Site Intelligence는 건설 현장의 반복 비행 데이터를 자동으로 수집·정합·비교해, 현장의 상태·변화·물량을 시계열로 답하고 부족한 데이터의 재수집을 스스로 계획하는 폐루프(closed-loop) 현장 공간 인텔리전스 플랫폼이다.** 건설은 첫 번째 Vertical이며, 현재 채택된 수집 장비는 Matrice 4D + RC Plus 2 + Manifold 3다(장비는 정의의 중심이 아니라 현재의 수집 수단).

## 1.2 제품을 구성하는 세 계층

### A. KSI Operations Console

Next.js 기반 공통 프론트엔드다.

- 하나의 반응형 Web으로 노트북·데스크톱·태블릿·모바일 브라우저 지원
- 전체 운영·승인·Mission 발급은 1024px 이상 현장 노트북·컴퓨터에서 수행
- 1024px 미만에서는 조회·이벤트 트리아지·분석 검토·Copilot 질의만 제공
- RC Plus 2/Pilot 2에는 KSI 업무 UI를 제공하지 않음
- 현장·건물·시설물 선택
- 통합 현장조사 임무 생성
- 비행 가능·금지 공간과 고정 정책 관리
- 임무 상태·관찰 커버리지·이벤트 확인
- 2D·3D·BIM·정사영상·시계열 변화 조회
- 검토·조치·재점검·보고서
- 데이터 라벨 교정·모델 운영 상태 확인
- 라이브뷰는 기본 화면이 아니라 예외·진단·수동개입 기능

### B. KSI Edge Autonomy

물리 구성은 **DJI Matrice 4D + Manifold 3 + KSI Edge Runtime**이다.

- 영상과 기체 텔레메트리의 시간 동기화
- 사람·장비·인양물·결함 후보 탐지
- 다중 객체 추적
- 영상 좌표를 현장 3D 좌표로 변환
- 4D 현장 세계모델 유지
- 장비 자세·작업상태·기구학 추정
- 현재 및 미래 동적 위험장 생성
- 관찰 불확실성 계산
- 다음 최적 관측점 선택
- 감속·호버링·기체 Yaw·짐벌·렌즈·재촬영 결정
- 의미 기반 경로 회피와 대체 관측점 선택
- 이벤트·증거·추론 계보 로컬 생성
- 서버 단절 시 임무 계약 범위 내 자율 운용

Manifold 3는 16GB LPDDR5, 256GB SSD, 최대 100 TOPS의 온보드 컴퓨팅과 Matrice 4D 계열 지원을 제공한다. 다만 최대 TOPS는 특정 INT8 희소 연산 조건의 이론값이며 실제 모델 처리량은 장비 시험으로 결정한다. [R1][R2]

### C. KSI Platform Backend

중앙 플랫폼은 단일 거대 서버가 아니라 논리적으로 분리한다.

1. **KSI Core Server**: 인증, 조직, 현장, 임무, 정책, 이벤트, PostGIS, 감사로그
2. **DJI Integration Gateway**: DJI Cloud API, MQTT/HTTPS/WebSocket, Wayline, 미디어·상태 연동
3. **KSI Processing**: 정사영상, 포인트클라우드, 3D Mesh/Tiles, 결함·변화·BIM 분석
4. **Storage & Data Platform**: 원본, 이벤트 증거, 텔레메트리, 모델·데이터 계보
5. **Model/Data Plane**: Dataset Builder, Model Registry, Evaluation, Shadow/Canary 배포

Core는 상시 GPU를 필요로 하지 않는다. GPU 작업은 Queue 기반 Processing Worker로 분리한다.

---

## 1.3 공식 명칭과 시장 구조

- 공식 플랫폼명: **KSI Site Intelligence Platform**
- 고객용 제품명: **KSI Site Intelligence**
- 저장소명: **`ksi-site-intelligence-platform`**
- 첫 번째 Solution Pack: **Construction Safety & Site Operations**
- 공통 플랫폼은 산업 중립적으로 설계하고 산업별 객체·위험규칙·검사 Template·보고서·보존정책을 Pack으로 제공한다.

```text
KSI Site Intelligence Platform
├─ KSI Site Intelligence                 # 고객 통합 제품
├─ KSI Edge Autonomy                     # Manifold Runtime
├─ KSI Spatial Intelligence              # 3D/4D World Model
├─ KSI Safety & Event Intelligence       # Event/Evidence/Action
├─ KSI Spatial Processing Fabric         # Reconstruction/Change/Map Compiler
├─ KSI Data & ML Platform                # Dataset/Model Governance
└─ Industry Solution Packs
   ├─ Construction Safety
   ├─ Industrial Facility Inspection
   ├─ Infrastructure Monitoring
   ├─ Energy Asset Inspection
   ├─ Logistics Yard Intelligence
   └─ Emergency Site Assessment
```

# 2. 핵심 제품 결정

**DEC-001 — 공식 플랫폼명은 `KSI Site Intelligence Platform`이다.**  
건설에 한정하지 않고 다양한 물리적 운영현장에 확장한다.

**DEC-002 — 고객 제품명은 `KSI Site Intelligence`다.**  
현장소장·안전관리자 등 사용자는 하나의 통합 제품을 사용한다.

**DEC-003 — 사용자 프론트엔드는 하나의 Next.js 반응형 Operations Console을 유지한다.**
노트북·데스크톱이 전체 운영 화면을 소유하고 모바일·소형 태블릿은 제한 표현을 사용한다.
Pilot 2는 비행 전용이며 업무 화면을 소유하지 않는다(ADR-KSI-024).

**DEC-004 — MVP 구매자는 건설사이며 실사용자는 개별 현장 소장·안전관리자다.**  
건설사 영업을 통해 여러 현장으로 확장한다.

**DEC-005 — 제품은 Site Intelligence Core(WHAT/WHY) ↔ Autonomous Acquisition(HOW)의 폐루프다. 선형 가치 순위는 두지 않는다.**  
2026-08-08 개정(ADR-KSI-016 D2). 기존 순서 `자율 안전순찰 > 지도 최신화 >
공정·변화·물량 > 자산점검`은 플랫폼 기술·분석 기능·임무 유형을 한 줄에 세운
분류 오류였다. 자율 안전순찰·구조물 점검은 Acquisition 축의 **임무 유형**이고
(정본 `ksi_domain.enums.MissionType`), 서로 순위를 두지 않는다. 제품 구조의
SSOT는 `docs/product/PRODUCT_CONSTITUTION.md` §두 축과 폐루프다. **개발 순서·
차단 상태는 `docs/goals/PHASE_REGISTRY.yaml`과 goal-ledger가 소유한다.**

**DEC-006 — 일반 사용자는 통합 자동모드, 전문가는 제한된 전문가 모드를 사용한다.**  
사용성과 전문성의 균형을 유지한다.

**DEC-007 — 비행 중 저지연 판단과 자율 임무 제어는 Manifold가 책임진다.**  
서버 지연·통신두절에 판단과 비행이 종속되지 않는다.

**DEC-008 — DJI Flight Controller가 자세·모터·기본 장애물회피·RTH 등 저수준 안전을 책임진다.**  
KSI가 저수준 비행제어를 재구현하지 않는다.

**DEC-009 — MVP 이착륙은 RC Plus 2 운영자가 관리하고, 이륙 후 순찰은 Manifold가 자율 수행한다.**  
Dock 미보유 상태에서 실현 가능한 Edge-first MVP를 만든다.

**DEC-010 — 사용자는 Mission Contract를 임무 시작 전에 한 번 승인한다.**  
승인된 범위 안에서 Edge가 경로·관측점·재관찰을 결정한다.

**DEC-011 — 현장 정책 승인 후 정기 임무는 자동 실행할 수 있다.**  
반복 순찰 운영을 제품 기본역량으로 한다.

**DEC-012 — 목표 자율성은 승인된 현장 전체 자유 자율탐색이다.**  
단순 Wayline 재생이 아니라 정보이득 기반 조사다.

**DEC-013 — 미매핑 공간은 Edge가 판단하되 속도·거리·행동을 크게 제한한다.**  
자유탐색과 보수적 안전을 함께 만족한다.

**DEC-014 — 서버 통신이 끊겨도 Mission Contract가 유효하고 안전조건이 유지되면 임무를 계속한다.**  
서버는 비행 중 필수 제어경로가 아니다.

**DEC-015 — RC Command Link 단절은 검증된 DJI Flight Controller Lost-link 정책을 따른다.**  
서버·인터넷 단절과 Command Link 단절을 구분한다.

**DEC-016 — 새 장애물은 위험도와 인지신뢰도에 따라 정지·후퇴·재관찰·우회·접근보류한다.**  
Unknown을 낙관적으로 통과하지 않는다.

**DEC-017 — 반개방 공간은 사전에 매핑된 안전회랑 안에서 제한적으로 자율순찰한다.**  
완전 GNSS-denied 자유탐색은 별도 제품단계다.

**DEC-018 — 순찰 완료는 필수 위험구역 100%, 필수 자산·표면 100%, 접근가능 일반영역 95% 이상이다.**  
경로 완료를 임무 완료로 보지 않는다.

**DEC-019 — 배터리 귀환은 현장별 설정이며 기본은 예상 귀환에너지 + 30% Reserve다.**  
DJI 경고보다 덜 보수적으로 행동하지 않는다.

**DEC-020 — 사건 응답시간은 Critical/High/Medium 심각도별 SLO를 적용한다.**  
즉시 위험은 증거완성을 기다리지 않고 경보한다.

**DEC-021 — 증거 길이는 Candidate 전후 3초, High 전후 5초, Critical 전후 10초를 기본으로 한다.**  
심각도에 따라 저장비용과 증거력을 조절한다.

**DEC-022 — 위치 불확실성을 포함해도 위험조건이 유지될 때만 Confirmed로 승격한다.**  
불확실성을 숨기지 않는다.

**DEC-023 — 지도는 매 비행 Delta, 변화 시 부분 재스캔, 기본 주 1회 전체 갱신을 사용한다.**  
시간과 변화기반 갱신을 결합한다.

**DEC-024 — 일반 Candidate 30일, 순찰 원본 90일, Confirmed Event·감사·조치 3년을 기본 보존한다.**  
고객·법령에 따라 조정 가능하다.

**DEC-025 — 장비 지원은 `DATASET_AVAILABLE`부터 `PRODUCTION_SUPPORTED`까지 단계로 표시한다.**  
탐지 가능과 상용 안전지원 주장을 구분한다.

**DEC-026 — 수동 Polygon은 고정 정책구역에만 사용하고 동적 장비 위험의 기본 수단으로 사용하지 않는다.**  
장비 기구학·궤적 기반 Risk Field를 제품 해자로 한다.

**DEC-027 — LLM은 실행 가능한 비행좌표나 안전제어 명령을 생성하지 않는다.**  
언어모델과 안전제어를 분리한다.

**DEC-028 — KSI Platform, KSI-Terra, KSI-Scout는 읽기 전용 참고 구현이다.**  
유용한 계약·수학·운영패턴을 선별 이식하되 과거 철학을 계승하지 않는다.

# 3. 목표와 비목표

## 3.1 제품 목표

1. 사용자가 현장과 목적을 몇 번의 터치로 선택하면 시스템이 필요한 비행·관측·처리 계획을 생성한다.
2. 서버 연결 없이도 Edge가 실시간 인식·공간화·위험판단·재관찰·임무복귀를 수행한다.
3. 모든 동적 객체는 가능한 경우 세계좌표, 속도, 궤적, 불확실성을 가진다.
4. 크레인·인양물·굴착기·지게차 등 지원 장비는 수동 위치·반경 입력 없이 자동 인지한다.
5. 위험판단은 정적인 거리뿐 아니라 작업상태, 장비 기구학, 예상 최근접 거리와 충돌시간을 포함한다.
6. 비행 종료 후 최신 2D·3D 현장모델, 변화결과, 이벤트가 하나의 Site Timeline에 연결된다.
7. 검토 과정에서 오탐·미탐·교정이 학습 데이터로 전환된다.
8. 제품은 건설을 첫 시장으로 하되 물류, 제조, 에너지, 광산, 인프라, 재난 대응에 Mission Pack으로 확장 가능해야 한다.

## 3.2 비목표

- 모든 환경과 모든 위험을 이해하는 범용 AI
- LLM이 실시간 비행좌표를 직접 생성하는 구조
- Manifold가 DJI Flight Controller를 대체하는 구조
- 일반 순찰사진만으로 측량급 결과를 항상 보장하는 주장
- 구조적 안전등급·붕괴 가능성·보수공법의 자동 최종 판정
- 얼굴인식 기반 작업자 식별
- 관찰하지 못한 영역을 완료로 표기
- 검증되지 않은 Dock 3 + M4D + Manifold 조합을 구현 완료로 간주

---

# 4. 사용자와 핵심 업무

## 4.1 상용 고객 구조

- 구매 고객: 건설사 본사 또는 사업부
- 실사용자: 개별 현장 소장, 안전관리자
- 보조 사용자: 드론 운영자, 공사관리자, 시설점검자, 본사 관리자, AI/Data 관리자
- 확장 고객: 산업시설·물류·에너지·인프라·재난현장의 운영주체

- **현장소장**: 현장상태·공정·이벤트·조치를 총괄한다. 여러 도구와 비정형 보고서 취합을 줄인다.
- **안전관리자**: 위험을 검토하고 담당자·조치를 관리한다. 영상 상시시청과 장비반경 수동작성을 줄인다.
- **드론 운영자**: RC 이착륙, Mission Contract 승인과 예외개입을 담당한다. 웨이포인트·짐벌·카메라 수동설정을 줄인다.
- **공사·운영관리자**: 변화·물량·자재·장비를 파악한다. 반복 현장확인과 수작업 비교를 줄인다.
- **구조·시설 점검자**: 결함후보와 증거를 검토한다. 위험 위치 접근과 반복촬영을 줄인다.
- **본사 관리자**: 다현장 사건·추세·감사를 관리한다. 현장별 보고취합을 줄인다.
- **AI/Data 관리자**: Dataset·Model 배포와 성능을 감시한다. 운영데이터와 학습데이터의 단절을 줄인다.

# 5. 제품 기능 카탈로그

## 5.1 기본 사용자 임무

### 5.1.1 Unified Site Survey — 기본 임무

사용자는 하나의 `현장 조사`를 만든다. 시스템은 현장 상태에 따라 내부 작업을 조합한다.

- Baseline Mapping
- Spatial Refresh
- Autonomous Patrol
- Adaptive Inspection
- Progress Capture
- Coverage Recovery
- Processing & World Model Update

### 5.1.2 Safety Intelligence Pack

- 사람·PPE
- 정적 출입금지구역 침입
- 작업자·장비 근접 및 접근 위험
- 굴착기 Swept Volume 침입
- 지게차 진행·후진 위험
- 크레인 인양물 하부·이동경로 위험
- 통로·비상동선 차단
- 추락 가장자리·개구부 주변 작업자
- 연기·화재 후보(RGB), 열 이상은 M4TD Pack

### 5.1.3 Asset Inspection Pack

- 외벽, 옥상, 파라펫, 설비 선택
- 표면 법선 기반 관측점
- 균열·박락·부식·누수·부품 누락 후보
- 광각 문맥 + 망원 증거
- 동일 위치 시계열 비교
- 전문가 검토 이벤트

### 5.1.4 Progress & Change Pack

- 시공단계별 3D Snapshot
- BIM/as-designed 대비 as-built 변화
- 신규 구조물·비계·컨테이너·자재 변화
- 고정 Viewpoint 반복 촬영
- 공정 리포트

### 5.1.5 Inventory & Logistics Pack

- 차량·장비 수량과 위치
- 자재 야적·통로 점유
- Stockpile 변화와 체적 처리 연동
- 물류 Yard의 차량·보행자 위험

### 5.1.6 Incident & Emergency Pack

- 사고 직후 현장 Snapshot
- 증거 보존 모드
- 접근 불가 구역 원격 조사
- 수색 우선순위와 이벤트 타임라인
- 전체 원본·로그 보존정책

### 5.1.7 Environmental/Thermal Pack

Matrice 4TD 또는 열화상 지원 플랫폼에서 활성화한다.

- 설비 과열
- 화재 조기 징후
- 야간 인명 후보
- 열 누설·태양광 패널 이상

## 5.2 전문가 모드

전문가 모드는 역할 권한에 따라 제공한다.

전문가가 조정할 수 있는 항목:

- 조사 AOI와 우선순위
- 필수 자산·표면
- Coverage 목표(플랫폼 최소치보다 높게만 설정 가능)
- 카메라·렌즈·영상품질
- 안전범위 안 최대속도
- 관찰거리·촬영중복도
- 재관찰 민감도
- Map Refresh 정책
- Survey-grade Mapping, GCP/Checkpoint, 원본 Export

전문가도 변경할 수 없는 Hard Limit:

- DJI Flight Controller 보호기능
- 서명된 Vehicle Safety Profile의 절대 안전상한
- 센서 이상·위치손실 시 정지·후퇴·귀환 원칙
- LLM 직접 제어 금지
- 미매핑 공간 제한정책의 완전 해제
- 증거·감사로그 비활성화
- 검증되지 않은 장비를 Production Supported로 표시하는 기능

# 6. 서비스 수명주기: Continuous Spatial Intelligence Loop

## 6.1 최초 현장 등록

1. 현장 외곽, 좌표계, 기본 정책을 등록한다.
2. BIM·도면·기존 정사영상이 있으면 가져온다.
3. 시스템이 Baseline Mapping Mission을 생성한다.
4. 드론이 규칙적인 광각 촬영과 경사 촬영을 수행한다.
5. KSI Processing이 정사영상·포인트클라우드·3D 모델을 생성한다.
6. 시스템이 구조물, 지면, 비행 가능 Volume, 안전 이격면, 사각지대 후보를 생성한다.
7. 품질 검증을 통과하면 현장은 `PATROL_READY`가 된다.

## 6.2 일상 현장 조사

1. 사용자는 조사 범위·목적·수준만 선택한다.
2. Mission Orchestrator가 World Model freshness를 평가한다.
3. 최신 모델이면 `Spatial Refresh Backbone + Adaptive Patrol`을 수행한다.
4. 모델이 오래됐거나 큰 변화가 감지되면 부분 또는 전체 재매핑을 선행한다.
5. 이벤트 조사를 위해 경로를 이탈하면 Edge가 누락된 촬영 커버리지를 보완한다.
6. 비행 후 World Model Delta를 처리하고 다음 임무에 배포한다.

## 6.3 현장 상태

- `UNMAPPED`
- `BASELINE_MAPPING`
- `MODEL_PROCESSING`
- `MODEL_VALIDATION`
- `PROVISIONAL_AUTONOMY`
- `PATROL_READY`
- `PATROL_ACTIVE`
- `MODEL_STALE`
- `REMAP_REQUIRED`
- `SUSPENDED`

## 6.4 통합 임무 내부 그래프

```text
PREPARE
  -> BASELINE_OR_REFRESH_CAPTURE
  -> PATROL_SEARCH
  -> TRACK_AND_ASSESS
  -> ACTIVE_REOBSERVATION
  -> COVERAGE_RECOVERY
  -> RETURN_AND_SYNC
  -> PROCESSING
  -> WORLD_MODEL_PUBLISH
  -> REVIEW_AND_ACTION
```

사용자에게는 하나의 임무로 보일 수 있지만 각 Stage는 별도 성공·부분성공·실패 상태를 가진다.

---

# 7. 사용자 경험 및 메뉴

## 7.1 반응형 정보구조

### 모바일/태블릿 하단 메뉴

- 홈
- 현장
- 작업
- 확인 항목
- 더보기

### 데스크톱 사이드 메뉴

- 홈
- 현장
- 작업
- 확인 항목

`비행 임무 이력 · Gateway/Edge 연결 · 장비 지원단계 · 전문가 복구`는 운영 지원에 둔다.
변화·상대 물량·정사영상·DSM·공간모델·설계·확인 항목·조사 이력·보고서는 각 현장
작업공간이 소유한다. 내부 Event 계약과 `/events` URL은 유지하지만 고객 화면에서는
`확인 항목`으로 표시한다(ADR-KSI-026).

### 현장 작업공간

- 브리핑 — 변화, 중요도, 지금 검토할 결정, 근거·불확실성, 저장된 KSI AI 대화
- 현장 데이터 — 변화·상대 물량·공간 산출물·설계 기준면·작업구역
- 확인 항목 — 해당 현장 발견의 근거와 사람 판단
- 작업·조사 — WorkOrder·취득 진행·원본 동기화·처리·비행 임무 이력
- 보고서 — 경영 요약·현장 근거·결정·다음 관측

## 7.2 홈

- `전체 N곳 · 확인 필요 M곳` 다현장 요약
- 현장이 있으면 안건 유무와 무관하게 큰 시각 캐러셀 영역 유지
- 미조치 사건 → 사람 결정 WorkOrder → 재관측 필요 Site 순의 현장별 확인 카드
- 운영 안건 0건이면 실제 최근 현장과 Event evidence를 같은 큰 시각 영역에서 표시
- 큰 시각 영역 아래 `초기 설정이 필요한 현장` 카드, 그 아래 최근 업데이트 순서 유지
- 전 폭에서 한 현장씩 넘겨보는 수동 캐러셀(자동 넘김 없음). 1024px 이상은 이미지와 설명을 좌우 배치
- 결과 준비·완료 조사·사람이 정리한 안건 중심의 최근 업데이트
- 실제 등록된 Event evidence 이미지와 근거·한계 표시
- `REVIEW_READY` 결과에서 근거형 Copilot 질의로 연결

Home은 작업·처리·장비 원장을 복제하지 않는다. 장비 연결·동기화·처리 시작은 해당 작업과
운영 지원 화면에서 다루고, 현장 2D·3D World와 보고서는 각 현장이 소유한다. 증거 이미지가
없거나 실패하면 합성 이미지로 대체하지 않으며, `미조치 없음`을 현장 전체의 정상·안전으로
표현하지 않는다(ADR-KSI-025).

Home의 `포트폴리오 요약 → 큰 시각 캐러셀 → 초기 설정 필요 현장 → 최근 업데이트`
위계와 안건 0건의 최근 현장 전환은 승인된 Visual Contract다. 제품책임자의 명시 승인,
ADR 개정, 390/768/1024/1440px 기준 이미지와 회귀 검사 갱신 없이 변경하지 않는다.

## 7.3 현장 등록 Wizard

1. 현장 기본정보
2. 지도 외곽(AOI)·좌표계
3. 확인·등록

Baseline 조사는 등록 완료 뒤 현장 작업공간에서 별도로 시작한다. 등록 성공을 비행 임무
발급이나 자율운영 활성화로 표현하지 않는다.

## 7.4 새 현장조사 Wizard

### Step 1 — 대상

- 현장 전체
- 구역
- 건물
- 외벽/옥상
- 설비
- 야적장/통로

### Step 2 — 목적

- 안전 위험
- 공간 모델 갱신
- 공정 변화
- 구조물 결함
- 장비·자재 현황
- 사고조사

### Step 3 — 조사 수준

- 빠른
- 표준
- 정밀

프리셋은 속도, 촬영 밀도, 재관찰 횟수, 렌즈, 최소 픽셀 크기, 이격거리, 배터리 예비율을 내부적으로 설정한다.

### Step 4 — 자동 계획 검토

- 예상 Sortie 수
- 예상 시간·배터리
- 조사 가능/제한 영역
- 사용 카메라와 모델
- World Model 신뢰도
- 비상·통신두절 정책

### Step 5 — 전송 및 승인

- Mission Contract 생성
- Edge 준비상태 확인
- 운영자 최종 승인

## 7.5 비행 중 Mission Intelligence 화면

기본 표시:

- 임무 진행률과 Coverage 상태
- 필수 위험구역·필수 자산·일반영역 달성률
- 현재 행동과 판단 근거
- 현재 관측 대상과 Next Best View
- Event 후보·확정 수
- 배터리, 예상 귀환에너지, Reserve
- RTK·Localization·RC Link·Server Link·Edge 상태
- 미관찰·가림·접근불가·위험·센서제한 영역
- 원 계획과 실제 이동
- 정적·동적·예측 Risk Field
- 자동 재관찰과 Coverage Recovery 타임라인

주요 버튼:

- 일시정지
- 임무 재개
- 귀환
- 수동 인계
- 임무 중단
- 라이브뷰 열기

라이브뷰는 자동 재생하지 않으며 스트림 장애가 임무를 중단시키지 않는다. 서버 연결이 끊겨도 Edge는 로컬 상태와 Mission Contract로 화면 없는 임무를 계속할 수 있다.

## 7.6 이벤트 상세

- 유형·심각도·상태
- 자동경보 시각과 사용자 전달 시각
- 2D/3D 위치와 Covariance
- 광각 문맥사진·세부사진·Crop
- 사건 전후 Clip
- 관련 객체 궤적
- 당시 Risk Field와 TTC/CPA
- 판단 규칙·모델·정책·보정 버전
- Mission Contract·MapVersion·Edge Runtime Version
- 위치·분류·추적·증거 신뢰도
- 확정/오탐/판단불가/유형수정
- 담당자·기한·조치·재점검

기본 증거 길이:

- **Candidate**: 사건 전 3초 + 사건 후 3초
- **High Confirmed**: 사건 전 5초 + 사건 후 5초
- **Critical**: 사건 전 10초 + 사건 후 10초

# 8. 제어권과 안전 경계

## 8.1 Control Authority Matrix

- **전역 임무 목표·정책**: Core가 소유하고 사용자가 승인하며 Edge가 캐시·실행한다.
- **실시간 객체 인지**: Manifold Edge가 소유하고 사용자가 결과를 검토한다.
- **다음 관측점 선택**: Core는 사전정보를 제공하고 Edge가 실시간 결정한다.
- **실제 목표점 이동**: Edge가 고수준 Intent를 요청하고 DJI Flight Controller가 실행한다. 사용자는 수동인계할 수 있다.
- **자세·모터 안정화**: DJI Flight Controller가 소유한다.
- **기본 센서 장애물 회피**: DJI Flight Controller가 소유하며 Edge는 의미정보를 보조한다.
- **의미 기반 위험 회피**: Core가 정책을 정의하고 Edge가 경로를 결정하며 DJI가 실행한다.
- **RTH·비상안전**: DJI Flight Controller가 최종 소유하며 Edge·사용자가 요청할 수 있다.
- **이벤트·증거**: Edge가 생성하고 Core가 저장하며 사용자가 업무적으로 확정한다.

## 8.2 금지 아키텍처

- 브라우저 또는 Core가 10Hz 이상 위치·속도 명령을 전송
- LLM 출력이 Flight Command로 직접 연결
- 네트워크 응답 실패 시 기체가 비정상 상태로 남음
- AI Detector가 Flight Controller 안전제약을 우회
- 라이브뷰 프레임이 Vercel Function 또는 Core API를 통과

## 8.3 Mission Contract

Core가 Edge에 전달하는 계약에는 반드시 다음이 포함된다.

- 조사 대상 Geometry와 Sector
- 허용 Flight Volume과 Exclusion Volume
- 최소·최대 고도, 구조물·사람 이격거리
- 임무 목표와 우선순위
- 필수 위험구역·필수 자산·필수 표면
- Coverage 목표: 위험구역 100%, 필수 자산·표면 100%, 접근가능 일반영역 기본 95%
- 모델·정책 Pack과 Version
- 카메라·Viewpoint·Active Perception Policy
- 미매핑 공간의 제한속도·관찰·진입정책
- Unknown obstacle 행동정책
- 서버통신 두절 Continue 조건
- RC Link Lost 처리 위임정책
- 배터리 귀환정책: 현장별 설정, 기본 예상귀환 + 30% Reserve
- 위치·지도·센서 불확실성 Fallback
- 사건 SLO와 Evidence Policy
- 데이터 보존·업로드 정책
- 서명·Digest·TTL

Mission Contract는 불변 입력이 아니라 Versioned·Signed 실행계약이다. Edge는 유효한 계약 범위에서만 자율적으로 행동하며, 계약 TTL·안전조건이 깨지면 새로운 조사행동을 시작하지 않는다.

# 9. KSI Edge Autonomy Runtime

## 9.1 권장 기술 구조

- 제어·상태·공간 런타임: C++17 이상
- AI 추론: TensorRT/CUDA/DLA, 모델별 프로파일
- 영상/카메라: DJI PSDK Adapter + 하드웨어 디코딩 가능성 검증
- 수학/기하: Eigen, Sophus 또는 동등 라이브러리
- 비전: OpenCV 및 검증된 추적·포즈 라이브러리
- 메시지: Protobuf
- 로컬 저장: SQLite/RocksDB + 파일 스풀
- 프로세스: systemd, Watchdog, Health Supervisor
- Python은 학습·실험·비행 후 분석에 사용 가능하나 하드 안전 루프의 필수 런타임으로 사용하지 않는다.

## 9.2 모듈

1. Hardware/PSDK Adapter
2. Sensor Synchronizer
3. Calibration Manager
4. Perception Runtime
5. Multi-Object Tracker
6. Geo-Referenced Localization
7. 4D World Model
8. Equipment State Estimator
9. Spatiotemporal Risk Engine
10. Coverage & Observability Map
11. Active Perception Manager
12. Viewpoint Planner
13. Local Mission Planner
14. Flight Supervisor
15. Evidence/Event Builder
16. Edge Sync & Store-and-Forward
17. Health/Resource Manager

## 9.3 상태 머신

- `BOOT`
- `SELF_TEST`
- `MISSION_LOAD`
- `PRE_FLIGHT`
- `TRANSIT`
- `SPATIAL_CAPTURE`
- `SEARCH`
- `TRACK`
- `ASSESS`
- `REPOSITION`
- `INSPECT`
- `EVENT_BUILD`
- `REJOIN`
- `COVERAGE_RECOVERY`
- `RETURN`
- `SYNC`
- `COMPLETE`

예외 상태:

- `OBSTACLE_BLOCKED`
- `TARGET_LOST`
- `LOCALIZATION_UNCERTAIN`
- `CAMERA_DEGRADED`
- `MODEL_DEGRADED`
- `LOW_BATTERY`
- `LINK_LOST`
- `STORAGE_LOW`
- `MANUAL_OVERRIDE`
- `EMERGENCY_RTH`

## 9.4 리소스 관리

Manifold는 모든 모델을 무조건 동시에 실행하지 않는다.

- Mission Pack에 필요한 모델만 로드
- 광각 탐색 모델과 정밀 재촬영 모델 분리
- GPU/DLA 파이프라인 분배
- 온도·전력·프레임 지연에 따라 FPS/해상도 조정
- 안전·추적·공간화가 부가 분석보다 우선
- 리소스 고갈 시 탐지 기능을 축소하되 Flight Supervisor와 데이터 보존은 유지

---

# 10. Geo-Referenced Perception — 핵심 IP 1

## 10.1 목적

영상의 객체를 `화면의 Bounding Box`가 아니라 현장 세계좌표를 가진 Entity로 변환한다.

## 10.2 필수 입력

- RGB 프레임과 정확한 Timestamp
- 드론 RTK/GNSS 위치
- 기체 Roll/Pitch/Yaw
- 짐벌 Pitch/Yaw/Roll 또는 가용 자세
- 렌즈·카메라 ID·초점거리·줌
- 카메라 Intrinsics/Distortion
- 카메라-짐벌-기체 Extrinsics
- 지면/DEM/3D Mesh/BIM
- 레이저 거리(가용 시)
- 다중 시점 Track

## 10.3 좌표계

- 원본 지리좌표: WGS84/고도 기준
- 현장 로컬 좌표: ENU 또는 명시된 Project CRS
- 모든 Geometry는 CRS, Vertical Datum, Unit을 가져야 한다.
- Edge와 Core는 동일 Site Transform 버전을 사용해야 한다.

## 10.4 처리 파이프라인

```text
Detection/Segmentation/Keypoint
 -> Object Contact Point or 3D Pose Hypothesis
 -> Camera Ray
 -> Transform to Site Frame
 -> Ray-Surface Intersection or Multi-view Triangulation
 -> Temporal/Multi-view Fusion
 -> Position + Covariance
 -> World Entity Update
```

## 10.5 시간 동기화

영상, RTK, 기체 자세, 짐벌, 렌즈 상태의 Timestamp 오프셋을 교정한다. 동기화 오차는 위치오차에 직접 반영한다.

## 10.6 보정

- 카메라·렌즈별 Intrinsic 프로파일
- 광각/중망원/망원별 별도 보정
- Zoom 단계가 연속이면 보간 또는 사용 가능한 공식 파라미터 활용
- 기체/짐벌 장착 Extrinsic 검증
- 정기 Calibration Health Check

## 10.7 위치 상태

모든 객체 위치는 다음 상태 중 하나다.

- `CONFIRMED`
- `LIKELY`
- `BOUNDARY_UNCERTAIN`
- `INSUFFICIENT_OBSERVATION`
- `STALE`
- `LOST`

## 10.8 불확실성

위치는 단일 점이 아니라 평균과 공분산 또는 동등한 오차표현을 가진다.

위치 불확실성이 위험구역 경계와 겹치면 자동 확정하지 않고 Active Perception을 요청한다.

## 10.9 다중 시점 능동 보정

단일 시점의 깊이 추정에 의존하지 않는다.

- 드론 이동 전후 동일 Track 관찰
- 시차 기반 삼각측량
- 지면/3D 표면 교차
- 레이저 기준점 융합
- 이상치 제거와 Kalman/EKF/Factor Graph 중 검증된 방법 사용

---

# 11. 4D Site World Model — 핵심 IP 2

## 11.1 계층

- Static Geometry Layer
- Semantic Surface/Zone Layer
- Traversability/Flight Volume Layer
- Dynamic Entity Layer
- Equipment Kinematic Layer
- Occlusion & Observability Layer
- Uncertainty Layer
- Risk Field Layer
- Event/History Layer

## 11.2 주요 Entity

- Person
- Vehicle
- Equipment
- Crane
- SuspendedLoad
- Structure
- Surface
- Opening
- Scaffold
- MaterialStack
- Route/Walkway
- Drone
- RiskField

각 Entity는 ID, Class, Pose, Velocity, Shape, Uncertainty, Track History, Source Observations, Model Version을 가진다.

## 11.3 Scene Graph 관계

- `locatedOn`
- `inside`
- `approaching`
- `carriedBy`
- `connectedTo`
- `occludedBy`
- `movingToward`
- `intersectsRiskField`
- `belongsToAsset`
- `observedFrom`

이벤트 규칙은 객체 목록이 아니라 Scene Graph와 시간 상태를 평가한다.

---

# 12. Equipment Intelligence & Dynamic Risk — 핵심 IP 3

## 12.1 원칙

지원 장비의 위치·반경을 사용자가 수동 지정하지 않아도 시스템이 자동 탐지·추적·상태추정·위험장 생성을 수행해야 한다.

수동 구역은 고정 정책 또는 자동인지 실패 시 Fallback이며 기본 사용흐름이 아니다.

## 12.2 Equipment Model Pack

각 장비 Pack은 다음을 포함한다.

- Detector/Segmenter
- 구성요소 Keypoint/Pose 모델
- Kinematic State Schema
- Reachable/Swept Volume 모델
- Risk Policy
- 증거 요구조건
- ODD와 성능 Benchmark

## 12.3 크레인

### 추정 상태

- 마스트/차체 위치
- 지브/붐 방향
- 트롤리 또는 붐 끝 위치
- 후크 위치
- 인양물 3D Pose와 크기
- 인양물 속도·흔들림

### 자동 위험장

- Suspended Load Fall Volume
- Load Motion Corridor
- Boom/Jib Swept Volume
- Ground Projection with Uncertainty Margin

### 이벤트

- 인양물 하부 작업자
- 인양경로 침입
- 크레인 작업공간 중첩
- 증거 불충분 시 다각도 재관찰

## 12.4 굴착기

- 차체와 주행 방향
- 상부 회전체 방향
- 붐·암·버킷 Pose
- 이동/굴착/선회 상태
- Body Collision Volume
- Rear Blind Zone
- Boom/Bucket Swept Volume
- 단기 Reachable Volume

## 12.5 지게차

- 차체, 진행/후진, 조향
- 포크·적재물 돌출
- 속도와 정지거리
- Forward/Reverse Occupancy Field
- 적재물 가림과 전복 관련 정책(센서 범위 내)

## 12.6 Risk Field

위험은 단순 Polygon 내부/외부만이 아니라 위치와 시간에 따른 확률적 장으로 표현한다.

```text
Risk(x,y,z,t) =
  P(entity reaches space)
  × P(hazard interaction)
  × severity
  × uncertainty adjustment
```

구현은 해석 가능한 규칙·기구학·확률 모델을 우선하며, 학습 모델은 각 요소를 보조한다.

## 12.7 예측 지표

- Current Distance
- Predicted Closest Point of Approach
- Time to Closest Approach
- Time to Collision 후보
- Risk Duration
- Field Intersection Probability
- Occlusion Confidence

## 12.8 이벤트 상태

- `OBSERVATION`
- `CANDIDATE`
- `EVIDENCE_COLLECTION`
- `FINDING`
- `CONFIRMED_EVENT`
- `DISMISSED`
- `UNRESOLVED`

---

# 13. Active Perception & Viewpoint Planning — 핵심 IP 4

## 13.1 목적

AI가 주어진 영상만 수동적으로 판단하지 않고 필요한 정보를 얻기 위해 안전한 관측 행동을 선택한다.

## 13.2 Viewpoint 구성

- Position XYZ
- Aircraft Yaw
- Gimbal Pitch/Yaw 가용 범위
- Camera/Lens
- Target/Surface
- Standoff Distance
- Speed/Hold Time
- Capture Actions
- Expected Information Gain
- Risk/Cost

## 13.3 후보 점수

```text
Score =
  Information Gain
  + Coverage Gain
  + Expected Localization Improvement
  + Evidence Quality
  - Flight Risk
  - Energy/Time Cost
  - Redundancy
```

후보는 Flight Envelope, Exclusion Volume, 구조물 이격, 사람 상공 비행 금지, 배터리, 센서상태를 통과해야 한다.

## 13.4 일반 행동 Template

- `HOLD_AND_ZOOM`
- `YAW_TO_TARGET`
- `SIDE_STEP_VIEW`
- `ALTITUDE_ADJUST_VIEW`
- `CONTEXT_THEN_DETAIL_CAPTURE`
- `MULTI_VIEW_TRIANGULATION`
- `SURFACE_NORMAL_CAPTURE`
- `REJOIN_BASE_PATH`

## 13.5 정보 부족 처리

- 카메라 해상도 부족
- 위치 경계 불확실
- 객체 일부 가림
- 장비 부품 Pose 불확실
- 이벤트 문맥 부족

위 조건이면 이벤트를 무리하게 확정하지 않고 `REPOSITION` 또는 `UNRESOLVED`로 처리한다.

---

# 14. Local Planning, 회피와 임무복구

## 14.1 두 종류의 회피

1. **Reactive Avoidance**: DJI Flight Controller의 센서 기반 정지·우회
2. **Semantic Avoidance**: KSI Edge가 사람, 작업장비, 크레인 작업공간, 금지 Volume을 고려해 위험한 목적지와 경로를 선택하지 않음

## 14.2 계획 구조

- Core: 전역 Coverage Plan, World Model, Mission Contract
- Edge: Receding Horizon Local Plan, Next Best View, Rejoin Plan
- DJI: 실제 목표점 이동과 기체 안전

## 14.3 실패·통신·배터리 정책

### 목적지와 장애물

- 목적지 차단: 안전거리 확보 후 대체 Viewpoint 탐색
- Unknown obstacle: 감속 또는 정지 → Yaw·Gimbal·관측점 변경 → 지도불일치 평가
- 안전 Clearance 확인: 제한속도로 우회
- 확인 불가: 후퇴·접근보류·부분 재스캔·Coverage Gap 기록
- 얇은 전선·케이블·망·투명·반사체: 일반 대형 장애물보다 보수적으로 처리

### 위치·센서

- Localization 저하: Hold → 능동 재관찰·재초기화 → 직전 신뢰지점 후퇴 → RTH
- 반개방 회랑에서 위치복구 실패: 더 깊이 진입하지 않고 직전 신뢰지점으로 후퇴
- 센서 불일치 또는 Edge Health 저하: 새로운 조사행동 중단

### 통신

서버·인터넷 통신이 끊겨도 다음 조건이 유지되는 동안 로컬 임무를 계속한다.

- Mission Contract와 TTL 유효
- Localization·Map Confidence 정상
- Camera·Sensor·Edge Health 정상
- Flight Controller Warning 없음
- Battery Return Reserve 정상
- 새로운 미확인 고위험 장애물 없음

RC Command Link 단절은 Manifold의 임의 정책이 아니라 검증된 DJI Flight Controller Lost-link 정책을 적용한다.

### 배터리

다음 중 먼저 발생하는 조건에서 새로운 조사·재관찰을 중단하고 귀환한다.

- DJI Smart RTH 또는 Flight Controller 배터리 경고
- 예상 귀환에너지 + 현장 Reserve(기본 30%) 도달
- Mission Contract 최대 비행시간
- 바람·고도·경로·위치불확실성으로 귀환비용 증가

KSI는 DJI의 더 보수적인 보호판단을 무시할 수 없다.

# 15. Mapping과 Continuous World Model

## 15.1 최초 Baseline Mapping

- 일정 중복도와 광각 촬영
- 수직 + 필요 시 경사 교차 촬영
- RTK, POS, 카메라 메타데이터
- Edge 품질 검사
- 서버 고밀도 재구성
- World Model 검증

## 15.2 순찰에 포함되는 Spatial Refresh

순찰의 기본 경로는 3D 갱신에 필요한 Spatial Capture Backbone을 포함한다.

- 광각 재구성용 사진을 일정 간격으로 수집
- 이벤트 발생 시 Adaptive Patrol로 분기
- 분기로 인한 촬영공백을 Coverage Recovery가 보완
- 동적 객체 영역은 재구성에서 마스킹 또는 낮은 가중치
- 변화 후보 영역은 추가 시점 수집

## 15.3 비행 중 Edge의 Mapping 역할

- Blur/Exposure/Feature 품질
- 이미지 중복도 추정
- 표면 관찰 Coverage
- Reconstruction-ready 상태
- 미촬영/가림/접근불가 분류
- 저해상도 Sparse Map과 기존 World Model 정합
- 변화 후보와 Remap 요청

## 15.4 비행 후 Processing

- Camera Pose Optimization
- Orthomosaic/DSM
- Dense Point Cloud
- Mesh/Texture/3D Tiles
- 부분 재구성 및 Model Delta
- 이전 모델 변화
- BIM 정합
- 품질 보고서

DJI Terra는 Windows/NVIDIA 기반 별도 재구성 소프트웨어로 사용할 수 있으나 KSI Processing은 Provider Adapter를 통해 Terra, ODM/Pix4D 또는 자체 파이프라인을 교체 가능하게 설계한다. [R11][R12]

## 15.5 커버리지 상태와 임무 완료

Coverage Cell 상태:

- `OBSERVED_HIGH_CONFIDENCE`
- `OBSERVED_PARTIAL`
- `RECONSTRUCTION_READY`
- `EVENT_INSPECTED`
- `OCCLUDED`
- `UNREACHABLE`
- `UNSAFE`
- `SENSOR_LIMITED`
- `TIME_LIMITED`
- `BATTERY_LIMITED`
- `NOT_OBSERVED`

정상 완료 조건:

- 필수 위험구역 관찰 100%
- 지정된 필수 자산·표면 관찰 100%
- 접근 가능한 일반 조사영역 95% 이상
- 요구 영상 품질·관측각도·중복도 충족
- 모든 미관찰 Cell에 원인코드와 후속처리 기록

상태:

- `COMPLETED`: 모든 완료조건 만족
- `COMPLETED_WITH_GAPS`: 안전상 허용된 Gap이 남고 원인·후속임무가 생성됨
- `ABORTED_SAFE`: 안전정책으로 중단하고 귀환
- `FAILED`: 결과계보 또는 안전종료가 보장되지 않음

임무 완료는 경로 완료가 아니라 Coverage, Evidence, Safety와 데이터 품질 기준으로 판단한다.

# 16. 구조물·자산 점검

## 16.1 대상 선택

사용자는 2D/3D에서 건물, 외벽, 옥상, 설비, 교량 부재 등 자산 또는 표면을 선택한다.

## 16.2 데이터 성숙도 Level

- L0: 2D 외곽 — 보수적 외곽 정찰
- L1: 높이/단순 3D — 면별 스트립 촬영
- L2: 검증된 Mesh/BIM — 표면 법선·일정 이격 촬영
- L3: 검증된 비행공간 — 적응형 근접점검

## 16.3 Edge 동작

- 표면 방향과 촬영거리 평가
- 카메라 해상도/GSD 후보
- 흐림·노출·입사각 검사
- 결함 후보 발견
- 광각 문맥 + 망원 세부
- 다각도 재촬영
- 3D 표면좌표 생성

## 16.4 Processing 동작

- 균열 Segmentation
- 길이·폭 후보와 측정 불확실성
- 박락·부식·누수 변화
- 과거 동일 위치 비교
- BIM 부재 연결

결과는 `자동 구조안전 진단`이 아니라 `외관 결함 후보·증거·변화관리`로 표현한다.

---

# 17. Event, Finding, Action Workflow

## 17.1 Event Bundle 필수요소

- Mission/Site/Time
- Mission Contract Digest와 MapVersion
- Event Type/Severity/Status
- 관련 Entity·Track·Observation
- Position, Geometry, Covariance
- Risk Field Snapshot과 TTC/CPA
- Rule/Model/Policy/Calibration Version
- Context Image, Detail Image, Crop
- Severity별 Pre/Post Clip
- Trajectory와 Viewpoint History
- Edge/Camera/Telemetry Health
- Human Review와 Action/Resolution
- Bundle Hash와 Edge Signature

Evidence 기본 정책:

- Candidate: 대표 원본·Annotated·판단근거 + 전후 3초
- High Confirmed: 전체 계보 + 전후 5초
- Critical: Risk Field·Trajectory·Viewpoint 포함 + 전후 10초
- 증거 저장실패는 숨기지 않고 `EVIDENCE_DEGRADED`로 기록한다.

## 17.2 업무 흐름과 심각도별 확정

```text
DETECTION
 -> OBSERVATION
 -> CANDIDATE
 -> EVIDENCE_COLLECTION
 -> FINDING
 -> CONFIRMED_EVENT / DISMISSED / UNRESOLVED
 -> ASSIGNED
 -> ACTION_IN_PROGRESS
 -> REINSPECTION_REQUESTED
 -> RESOLVED
 -> CLOSED
```

심각도 정책:

- `CRITICAL`: 충돌 임박, 장비·사람 초근접, 인양물 하부 등은 충분한 증거수집 완료를 기다리지 않고 즉시 로컬경보한다. 사후검토는 유지한다.
- `HIGH`: 위험구역 진입, 반복 장비 근접 등은 짧은 Temporal Evidence 후 자동경보할 수 있다.
- `MEDIUM`: PPE 의심, 통로폐색, 적치불량 등은 재검증·재관찰 후 Finding 또는 검토대기 Candidate로 생성한다.

위치 불확실성과 위험공간이 겹치면 Candidate를 생성한다. 불확실성 영역을 포함해도 위험조건이 유지될 때만 Confirmed로 승격한다. 불확실성이 크면 `SUSPECTED` 또는 `UNVERIFIABLE`로 유지한다.

## 17.3 이벤트 중복 제거

- Track 기반 동일 대상
- 시간·공간 Cluster
- 동일 Risk Field 지속상태
- 이벤트 재개/종료 규칙

---

# 18. Data Flywheel와 MLOps

## 18.1 수집 원칙

모든 임무는 운영 결과와 학습 가능한 데이터를 함께 생성한다.

- 확정 위험
- 오탐/Hard Negative
- 미탐 교정
- 불확실 사례
- Active Perception 전후
- 다양한 거리·각도·조도·가림
- 모델·정책·보정·기체 버전

## 18.2 저장 계층

- Observation Store
- Event Store
- World Model Store
- Media/Object Storage
- Dataset Registry
- Model Registry
- Evaluation Store

## 18.3 검토가 라벨링이 되도록 설계

관리자가 `확정/오탐/판단불가`, 클래스·위치·심각도·증거충분성을 수정하면 라벨 후보로 저장한다.

## 18.4 Dataset Builder

필터 예:

- 관리자 검토 완료
- 특정 카메라/거리/현장
- 위치 불확실성 기준
- 망원 증거 존재
- 고객사 학습동의
- 중복 Track 제거

## 18.5 데이터 분할

연속 프레임을 임의 분할하지 않는다. Site/Mission/Date/Customer 단위로 Train/Validation/Test를 분리한다.

## 18.6 모델 배포

```text
TRAIN
 -> OFFLINE EVALUATION
 -> REPLAY/SIMULATION
 -> SHADOW
 -> CANARY
 -> ROLLOUT
 -> MONITOR
 -> ROLLBACK
```

## 18.7 성능 지표

- 객체 Precision/Recall/AP
- 세계좌표 오차
- Track 유지율
- Event Recall/False Events per Flight Hour
- Evidence Capture Success
- Active Perception 성공률
- Risk Field 경계 정확도
- Edge Latency/Temperature/Power
- Site/환경별 Drift

---

# 19. Core Backend 및 데이터 아키텍처

## 19.1 권장 구성

- Next.js: UI와 BFF
- Core API: TypeScript 기반 별도 서비스 권장
- PostgreSQL + PostGIS
- Object Storage(S3 호환)
- Message Bus/MQTT
- Job Queue
- WebSocket/SSE Realtime
- Processing Workers
- Model/Dataset Registry

## 19.2 주요 Domain

- Tenant/Organization/User/Role
- Site/CoordinateSystem
- Asset/Surface/Zone
- Mission/MissionContract/Stage/Sortie
- Aircraft/EdgeDevice/Capability
- WorldModel/Entity/Track
- Observation/Finding/Event/Evidence
- RiskPolicy/RiskField
- ProcessingJob/Artifact
- Action/Resolution
- Dataset/Model/Deployment

## 19.3 API 원칙

- 계약은 JSON Schema/Protobuf로 버전관리
- Idempotency Key
- Edge Store-and-Forward
- Event Sourcing 또는 최소 변경이력
- 대용량 미디어는 Presigned Upload
- 3D Tiles/COG/점군은 타일 스트리밍
- Vercel은 대용량 처리·미디어 프록시를 담당하지 않음

---

# 20. DJI Integration과 Capability Gate

## 20.1 현재 공식 확인사항

- Manifold 3는 Matrice 4D Series 지원 모델로 명시돼 있다. [R1][R5]
- PSDK는 Manifold에서 미디어·센서 데이터, 비행제어와 경로계획 기능을 제공하는 개발경로를 설명한다. [R3][R4]
- DJI Cloud API는 Dock 3와 Matrice 4D/4TD 지원을 명시한다. [R6]
- DJI Cloud API 지원표는 Dock 3 + M4D/4TD에서 제3자 Payload 미지원 문구를 포함한다. [R7]

## 20.2 제품 Hardware Profile

### Profile A — Primary R&D / Early Product

- Matrice 4D
- RC Plus 2/Pilot 2
- Manifold 3
- KSI Edge
- KSI Core와 직접 Edge Sync

### Profile B — Dock Operations

- Dock 3 + Matrice 4D
- DJI Cloud API
- Manifold 동시운용은 Capability Spike 및 DJI 확인 후 활성화

### Profile C — Thermal

- Matrice 4TD + 지원되는 Edge/Dock 조합

## 20.3 SPIKE_REQUIRED 항목

- M4D 카메라별 실시간 프레임 접근
- 광각/중망원/망원 전환과 촬영·초점 제어
- 기체 Yaw/짐벌 Pitch API와 지연
- FlyTo/Hold/Rejoin/Route Update
- DJI 장애물 회피와 KSI 명령 동시동작
- Pilot 2/Cloud API/PSDK 동시 제어권
- Manifold 이벤트 네트워크 경로
- Dock 3 물리 수납·전원·충전·운용
- 비행시간/발열/전력 영향

각 기능은 `Capability Registry`에서 VERIFIED가 되기 전 운영 UI에 노출하지 않는다.

---

# 21. 비기능 요구사항

## 21.1 Edge 실시간 목표

- Sensor Timestamp alignment: p95 50ms 이하 목표
- 광각 탐지 업데이트: ODD 내 5~15Hz 목표
- Track/World Update: 10Hz 목표
- Risk Field Update: 2~5Hz 목표
- 위험후보에서 Edge 행동결정: p95 500ms 이하 목표

사건별 사용자 SLO:

- **Critical**: Edge 후보 1초 이내, 로컬경보 2초 이내, 서버 연결 시 사용자 알림 5초 이내.
- **High**: Edge 후보 3초 이내, Temporal 확인과 알림 10초 이내.
- **Medium**: 최대 30초 재관찰·재검증 후 Finding 또는 운영정책에 따른 알림.

수치는 실제 M4D + Manifold 3 Benchmark와 ODD별 Profile로 검증하되, 제품의 심각도별 우선순위는 변경하지 않는다.

## 21.2 가용성과 Offline Autonomy

- Core API 99.9% 목표
- Edge는 서버 단절 상태에서 유효 Mission Contract와 안전조건이 유지되면 해당 Sortie를 계속 수행
- RC Command Link Lost는 DJI Flight Controller 정책 적용
- 재동기화는 멱등성 보장
- Edge Event Journal은 서버 복구 후 순서와 계보를 보존해 동기화
- Processing 실패는 원본·이벤트·비행 데이터를 손실시키지 않음

## 21.3 안전

- 수동 인계와 RTH 항상 가능
- Flight Supervisor보다 AI 모델이 높은 권한을 가질 수 없음
- 위치 불확실성 기준 초과 시 공격적 근접비행 금지
- Unknown obstacle의 낙관적 통과 금지
- ODD 밖에서는 기능저하·보수적 동작
- Hard Limit은 전문가도 해제할 수 없음

## 21.4 데이터 무결성

- 원본 Hash와 Capture Manifest
- Mission Contract 서명·Digest
- Event/Observation lineage
- 모델·정책·보정·Edge Runtime Version
- 원본과 파생결과 연결
- 서명되지 않거나 Version 불일치인 Edge Map/Model Pack 실행 금지

## 21.5 접근성·UX

- 터치 대상 최소 44px 이상
- 장갑·야외 대비 고대비 모드
- 기술 코드보다 원인과 복구행동 표시
- 데스크톱 Operations Console에서 5단계 이내 기본 임무 생성
- 모바일에서는 임무 생성·승인 대신 "노트북에서 계속" 안내
- 일반모드에서는 안전한 기본값을 자동 적용

# 22. 보안·개인정보·배포

## 22.1 데이터·개인정보·보존 원칙

- 얼굴인식 기본 금지
- 익명 Track ID
- 얼굴·번호판 비식별화 옵션
- 고객사별 데이터·Encryption Key 격리
- 학습 사용 동의와 Dataset lineage 추적
- 원본 열람·Export·삭제 감사로그

기본 보존기간:

- 일반 Candidate 원본: **30일**
- 일반 순찰 원본 영상·사진: **90일**
- Confirmed Event 증거: **3년**
- Telemetry·Mission 실행기록: **1년**
- 감사로그·조치이력: **3년**
- 공간지도·3D 산출물: **계약기간 + 종료 후 90일**

고객 정책과 적용 법령에 따라 연장·단축할 수 있다. 삭제 시 실제 Object와 파생복제본을 제거하고 Tombstone·삭제감사기록을 유지한다.

## 22.2 배포 형태

- KSI Cloud
- Customer On-Premises
- Hybrid: 원본은 고객사, 메타데이터·정책은 KSI Cloud

## 22.3 Plane 분리

- Control Plane: 조직, 라이선스, 모델, 정책
- Site Data Plane: 현장 DB, 미디어, Processing
- Edge Plane: Manifold, 로컬 World Model, Store-and-Forward

---

# 23. 시장 적용과 산업 확장

## 23.1 첫 번째 Vertical

첫 상용 Vertical은 건설현장 안전·공간관리다.

- 구매자: 건설사
- 실사용자: 현장소장·안전관리자
- 영업확장: 한 건설사 내 다수 현장
- 제품 구조: Site Intelligence Core(이해·계획) ↔ Autonomous Acquisition(관측·실행)
  폐루프 (2026-08-08 개정, ADR-KSI-016 D2)
- Core가 내놓는 것: 시계열 공간 상태, 변화·공정·물량, 설계 대비, 불확실 구역 판단
- Acquisition이 하는 것: 매핑·순찰·점검·재관찰 등 임무 수행(정본 `MissionType`)
- **자율 안전순찰은 이 제품이 한다** — Acquisition 축의 임무 유형이며 범위에서
  빠지지 않았다. 같은 비행이 공정 epoch와 안전 증거를 함께 채집하는 것이
  이 제품의 구조적 이점이다

건설은 플랫폼의 첫 검증시장이지 상위 플랫폼의 영구 산업경계가 아니다.

## 23.2 산업 확장 방식

하나의 Core·Edge·Spatial·Event 계약을 유지하고 산업별 Solution Pack으로 확장한다.

- Industrial Facility Inspection
- Infrastructure Monitoring
- Energy Asset Inspection
- Logistics Yard Intelligence
- Mining/Quarry Site Intelligence
- Agriculture Facility Monitoring
- Emergency Site Assessment

공통계층:

- Mission Contract
- Edge Autonomy
- Spatial Processing
- 4D World Model
- Event·Evidence·Action
- Data·ML Platform

산업별 계층:

- 객체와 장비 Class
- 위험·검사 Rule
- Mission Template
- 보고서와 전문용어
- 규제·보존정책

## 23.3 장비 지원표시

장비·객체별 제품상태:

```text
DATASET_AVAILABLE
BASELINE_DETECTION
FIELD_VALIDATED
GEO_VALIDATED
RISK_VALIDATED
PRODUCTION_SUPPORTED
```

`PRODUCTION_SUPPORTED`만 공식 상용 안전지원으로 표시한다. 공개데이터에 클래스가 있거나 Baseline Detector가 동작해도 현장·Geo·Risk 검증 전에는 Experimental/Beta다.

## 23.4 KSI 차별화

1. DJI Enterprise 하드웨어 활용
2. Manifold 기반 Edge-first 자율판단
3. Geo-Referenced Perception과 불확실성
4. 장비 Kinematic Library
5. 4D World Model과 Probabilistic Risk Field
6. Active Perception과 증거 재수집
7. 안전 이벤트에서 조치 완료까지의 업무시스템
8. 매핑·순찰·점검의 Continuous Spatial Intelligence Loop
9. 운영검토가 학습데이터가 되는 Data Flywheel
10. 산업 Pack으로 확장 가능한 공통 Site Intelligence 계약

## 23.5 상용 패키지

- KSI Dashboard/Core 구독
- KSI Edge Autonomy 기체 라이선스
- Industry/Mission Packs
- Processing 크레딧 또는 On-Prem 라이선스
- Enterprise Model/Data Management

# 24. 개발 구조와 저장소

공식 저장소명은 **`ksi-site-intelligence-platform`**이다.

```text
ksi-site-intelligence-platform/
├─ AGENTS.md
├─ CLAUDE.md
├─ docs/
├─ contracts/
├─ apps/
│  └─ dashboard/
├─ services/
│  ├─ core/
│  ├─ dji-gateway/
│  └─ processing-controller/
├─ edge/
│  └─ manifold-runtime/
├─ packages/
│  ├─ domain/
│  ├─ geo-core/
│  ├─ event-contracts/
│  ├─ mission-contracts/
│  └─ test-vectors/
├─ tests/
│  ├─ contract/
│  ├─ golden/
│  ├─ replay/
│  ├─ hil/
│  └─ e2e/
└─ references/
   └─ repos/
      ├─ ksi-platform/   # read-only submodule
      ├─ ksi-terra/      # read-only submodule
      └─ ksi-scout/      # read-only submodule
```

참고 저장소는 빌드대상이나 Runtime Dependency가 아니다. 유용한 Domain·Algorithm·Test·운영패턴은 Adoption Decision과 원출처 Commit을 기록한 뒤 KSI 소유 모듈로 추출·이식한다.

# 25. 구현 단계

단계는 **기능 깊이의 확대**이며 목표 아키텍처를 단순화하지 않는다.

## Phase 0 — Capability & Calibration Foundation

- M4D + Manifold PSDK Spike
- 카메라·렌즈·텔레메트리 접근
- 시간동기화·보정 도구
- Capability Registry
- Replay Harness

## Phase 1 — Geo-Referenced World Model

- 사람·차량·장비 Track
- 다중 시점 세계좌표
- World Entity/Covariance
- 2D/3D 표시
- Event Bundle/Offline Sync

## Phase 2 — Baseline Mapping & Unified Mission

- 현장 Onboarding
- Baseline Processing
- Verified Flight Volume
- Spatial Refresh Backbone
- Coverage Recovery

## Phase 3 — Dynamic Equipment Intelligence

- 우선 장비 1~2종의 구성요소 Pose
- Kinematic State
- Dynamic Risk Field
- CPA/TTC
- Active Reobservation

권장 첫 기술 Pack은 `타워크레인/인양물/작업자` 또는 데이터 접근성이 높은 `굴착기/작업자` 중 하나를 선택해 깊게 완성한다.

## Phase 4 — Asset Inspection & Temporal Intelligence

- 표면 점검
- 균열·박락 후보
- 3D 위치·시계열 변화
- BIM 연계

## Phase 5 — Fleet/Dock & Cross-Industry Packs

- Dock Capability가 검증된 후 원격 반복운영
- 다현장 Fleet
- 물류·산업·에너지 Pack

---

# 26. 제품 완료 기준

## 26.1 Architecture Completion

- Dashboard/Core/Edge/Processing/DJI Gateway 경계가 코드와 계약으로 분리
- 서버 프레임별 연속제어 없음
- LLM 실행좌표 생성경로 없음
- Reference Repository 직접 Import 없음
- Signed Mission Contract, Model Pack, Edge Map Package 적용

## 26.2 Autonomy Completion

정의된 ODD에서:

- RC Plus 2 이착륙 후 Manifold 자율순찰
- 현장 정책과 Mission Contract만으로 임무 실행
- 미매핑 공간 제한탐색
- 기본경로 이탈 재관찰
- 대체 Viewpoint와 우회경로 선택
- 원 임무 재접속과 Coverage Recovery
- 서버통신 단절 중 로컬 계속
- RC Link Lost 시 DJI 정책 준수
- Unknown obstacle의 안전한 정지·재관찰·후퇴
- 수동인계와 RTH

## 26.3 Spatial Intelligence Completion

- 객체 위치와 Covariance 생성
- Terrain/Mesh/BIM Surface Raycast
- 다중시점 융합
- Static/Semi-static/Dynamic Layer
- 장비별 Risk Field와 TTC/CPA
- Boundary Uncertain 처리
- 자동 재관찰 후 재평가
- 불확실성을 무시한 Confirmed Event 0건

장비별 상태는 `PRODUCTION_SUPPORTED`까지 단계적으로 검증한다. 데이터셋 존재만으로 완료처리하지 않는다.

## 26.4 Unified Mission Completion

- 최초 Baseline Mapping부터 Patrol Ready 자동상태 진행
- 필수 위험구역 100%
- 필수 자산·표면 100%
- 접근가능 일반영역 95% 이상
- Event 분기 후 Coverage Recovery
- Gap 원인코드와 후속임무
- 비행 후 MapVersion과 Change 제공

## 26.5 Event & Workflow Completion

- Critical Edge 후보 1초, 로컬경보 2초, 서버알림 5초 목표 달성
- High 10초 이내 Temporal 확인·알림
- Medium 최대 30초 재관찰·재검증
- 심각도별 Evidence Clip 정책 적용
- Event 검토·수정·담당자·조치·재점검·종료
- 모든 Event에 Evidence와 Lineage
- 오탐교정이 Dataset 후보로 연결

## 26.6 Reliability Completion

- 서버통신 단절·복구 데이터 손실 없음
- Edge Crash 후 안전한 재시작 또는 RTH
- 배터리 예상귀환 + 기본 30% Reserve 정책 검증
- Model/Policy rollback
- Processing 재시도와 원본보존
- Production에서 Mock·Placeholder·Static always-go 금지

## 26.7 Data Governance Completion

- 고객별 보존정책 적용
- 기본 보존기간 자동적용
- 삭제·Export·학습복제 계보
- Dataset/Model License Registry
- NC·권리불명 데이터의 상용학습 차단
- 장비 지원상태를 고객 UI와 계약에 정직하게 표시

# 27. 시험전략

## 27.1 Replay-first

실제 비행 전에 기록된 영상·텔레메트리를 재생해 동일 Event/World Model을 재현한다.

## 27.2 Simulation/Hardware-in-the-loop

- Mission State Machine
- Link Loss
- Battery/Storage Fault
- API timeout
- Model Crash
- Coordinate Transform 오류

## 27.3 Calibration Test

- 렌즈별 Intrinsic
- Gimbal/airframe Extrinsic
- Time Offset
- Known Control Point 위치오차

## 27.4 Field Acceptance

- RC Plus 2 이착륙·수동 인계
- 평탄 지상과 3D 표면의 객체좌표
- 층이 다른 작업자
- 가림과 재관찰
- 정지·이동 장비
- 굴착기 선회와 장비·사람 근접
- 크레인·인양물 제한 시나리오
- 구역경계와 위치불확실성
- Event 심각도별 SLO
- Candidate/High/Critical Evidence 길이
- 장애물 차단, 대체경로, Unknown obstacle
- 서버통신 단절 계속수행
- RC Command Link Lost 정책
- Battery Reserve 귀환
- 반개방 안전회랑 위치복구·후퇴
- Coverage 100/100/95와 Gap 분류
- 비행 후 3D 처리·MapVersion·부분재스캔

## 27.5 Safety Case

각 자율행동은 Hazard, ODD, Trigger, Mitigation, Detection, Fallback, Evidence를 문서화한다.

다음 수치는 제품책임자가 임의로 정하지 않고 실제 M4D + Manifold 3 HIL/Field Test 결과를 서명된 Vehicle Safety Profile에 저장한다.

- 최대 접근속도
- Unknown obstacle 정지거리
- 구조물·사람·전선 이격거리
- 위치불확실성 중단상한
- 반개방 위치복구 시간
- 장비별 Risk Threshold

이 수치가 아직 미검증이어도 제품 철학과 책임경계는 확정된 상태다. 미검증 Profile은 보수적 Default 또는 기능비활성으로 처리한다.

# 28. 주요 위험과 대응

- **M4D/Manifold API 기능 부족**: Phase 0 Spike, Capability Adapter와 대체 Hardware Profile을 사용한다.
- **Dock 3와 제3자 Payload 제한**: Dock는 독립 Track으로 검증하고 초기 제품은 RC/Manifold Profile을 사용한다.
- **카메라 기반 깊이오차**: 다중시점, 3D Mesh, 레이저 기준, Sensor Adapter와 Covariance로 완화한다.
- **후크·와이어 등 소형물체 미탐**: 망원 Active Perception, 장비 Telematics 융합과 ODD 제한을 적용한다.
- **동적 객체의 3D 재구성 방해**: Dynamic Masking과 정적 World Layer 분리를 적용한다.
- **모델 과부하·발열**: Mission-specific 모델, DLA/GPU 분리와 Resource Manager를 적용한다.
- **현장데이터 부족**: Review Data Flywheel, Shadow와 설계된 데이터 수집임무를 사용한다.
- **과도한 완전자율 주장**: ODD, Coverage와 Uncertainty를 제품 UI와 계약에 명시한다.

---

# 29. 에이전트 구현 규칙

1. `AGENTS.md`와 JSON Schema를 먼저 읽는다.
2. DJI 기능은 Capability Registry에서 VERIFIED가 아니면 구현된 것으로 가정하지 않는다.
3. 서버에서 연속 비행제어 루프를 만들지 않는다.
4. Detector 결과를 Event로 직접 저장하지 않는다.
5. 세계좌표와 Geometry에는 CRS, Unit, Timestamp, Uncertainty를 포함한다.
6. 장비 위험반경 수동 입력을 기본 UX로 만들지 않는다.
7. 수동 Zone은 고정 정책과 Fallback에만 사용한다.
8. Mission/Model/Policy/Calibration Version을 모든 결과에 연결한다.
9. 기존 Next.js를 감사하기 전 재작성하지 않는다.
10. 구현과 문서·계약·테스트를 함께 변경한다.

---

# 30. 제품 결정 동결과 변경관리

본 PRD v3.0에서 다음은 제품책임자 승인 없이 변경할 수 없다.

- 플랫폼·제품 명칭과 산업 Pack 구조
- Manifold Edge의 비행 중 판단 소유권
- DJI Flight Controller의 저수준 안전 소유권
- Mission Contract 사전승인과 정기임무 자동실행
- 서버통신 단절 중 조건부 로컬 계속
- RC Link Lost의 DJI 정책 적용
- 순찰완료 100%/100%/95% 기준
- 배터리 기본 30% Reserve
- 사건 SLO와 Evidence 길이
- 불확실성 기반 사건확정
- Unknown obstacle 보수적 처리
- 지도 시간+변화 기반 갱신
- 전문가 Hard Limit 금지
- 데이터 기본 보존기간
- 장비 지원 단계 표시
- 산업중립 Core + Solution Pack 구조
- Home의 큰 시각 영역, 0건 최근 현장 전환, 초기 설정 카드가 뒤따르는 승인된 시각 위계

실기시험으로 결정할 Vehicle Safety Profile 수치는 제품 모호성이 아니라 검증대상 Parameter다. 수치 변경은 Profile Version, 시험증거, 승인자와 Rollback을 기록해야 한다.

---

# 31. 공식/시장 참고자료

- **R1**: https://enterprise.dji.com/manifold-3/specs
- **R2**: https://enterprise.dji.com/manifold-3
- **R3**: https://developer.dji.com/doc/payload-sdk-tutorial/en/manifold-quick-start/manifold-product.html
- **R4**: https://developer.dji.com/doc/payload-sdk-tutorial/en/function-overview/advanced-function/flight-control.html
- **R5**: https://developer.dji.com/doc/payload-sdk-tutorial/en/manifold-quick-start/development-environment-setup/hardware-environment-setup.html
- **R6**: https://developer.dji.com/doc/cloud-api-tutorial/en/
- **R7**: https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html
- **R8**: https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-introduction.html
- **R9**: https://enterprise.dji.com/dock-3/specs
- **R10**: https://enterprise.dji.com/matrice-4-series/specs
- **R11**: https://enterprise.dji.com/dji-terra/faq
- **R12**: https://enterprise.dji.com/dji-terra/downloads
- **R13**: https://www.skydio.com/solutions/construction-drones
- **R14**: https://www.skydio.com/ja-jp/blog/introducing-skydio-3d-scan
- **R15**: https://www.flyability.com/elios-3
- **R16**: https://www.pix4d.com/
- **R17**: https://www.pix4d.com/product/pix4dmapper-photogrammetry-software


---

# Appendix A. 핵심 요구사항 ID

## Architecture

- ARCH-001: Dashboard, Core, Edge, Processing을 독립 배포 가능하게 분리한다.
- ARCH-002: 비행 중 실시간 판단은 Edge에서 실행한다.
- ARCH-003: 저수준 비행안전은 DJI Flight Controller에 위임한다.
- ARCH-004: Core는 GPU 없이 상시 운영 가능해야 한다.

## Mission

- MISSION-001: 사용자는 대상·목적·수준으로 통합 임무를 생성한다.
- MISSION-002: 최초 현장은 Baseline Mapping을 자동 요구한다.
- MISSION-003: 일상 순찰에 Spatial Refresh와 Coverage Recovery를 포함한다.
- MISSION-004: 부분 성공과 미관찰 영역을 명시한다.

## Spatial

- SPATIAL-001: 객체는 세계좌표와 불확실성을 가진다.
- SPATIAL-002: 영상·RTK·기체·짐벌·렌즈 데이터를 동기화한다.
- SPATIAL-003: 다중 시점 융합을 지원한다.
- SPATIAL-004: 2D/3D/시간 Geometry를 지원한다.

## Risk

- RISK-001: 지원 장비를 자동 탐지·추적한다.
- RISK-002: 장비 구성요소와 기구학 상태를 추정한다.
- RISK-003: 동적 3D 위험장을 자동 생성한다.
- RISK-004: CPA/TTC/지속시간/불확실성을 반영한다.
- RISK-005: 불확실 시 Active Perception을 실행한다.

## Edge

- EDGE-001: 서버 단절 시 Mission Contract 범위에서 운용한다.
- EDGE-002: 모든 고수준 행동은 Flight Supervisor를 통과한다.
- EDGE-003: 리소스 저하 시 안전기능을 최우선 유지한다.
- EDGE-004: Store-and-Forward와 멱등 동기화를 제공한다.

## Data

- DATA-001: 이벤트는 원본·추론·정책·모델 계보를 가진다.
- DATA-002: 운영 검토를 학습 라벨 후보로 저장한다.
- DATA-003: 고객사 학습동의와 보존정책을 적용한다.
- DATA-004: Dataset/Model을 재현 가능하게 버전관리한다.

## UX

- UX-001: 기본 임무 생성은 데스크톱 Operations Console에서 5단계 이내이며, 모바일은
  조회·이벤트 트리아지·분석·Copilot만 제공한다.
- UX-002: 라이브뷰는 기본 OFF다.
- UX-003: Bounding Box 수가 아니라 이벤트·커버리지를 표시한다.
- UX-004: 사용자가 장비 반경을 매일 그리지 않게 한다.


# Appendix B. Final Locked Requirement IDs

- `REQ-PROD-001`: 공식 플랫폼명은 KSI Site Intelligence Platform이다.
- `REQ-MSN-101`: Mission Contract는 임무 전 한 번 승인한다.
- `REQ-MSN-102`: 현장정책 승인 후 정기임무 자동실행을 지원한다.
- `REQ-MSN-103`: 위험구역 100%, 필수자산 100%, 일반 접근영역 95%를 완료기준으로 한다.
- `REQ-EDGE-101`: 서버통신 단절 중 유효계약과 안전조건이 유지되면 임무를 계속한다.
- `REQ-EDGE-102`: RC Link Lost는 DJI Flight Controller 정책을 따른다.
- `REQ-SAFE-101`: 배터리 Reserve는 현장별 설정, 기본 30%다.
- `REQ-SAFE-102`: Unknown obstacle은 정지·재관찰·후퇴·우회 정책을 적용한다.
- `REQ-EVT-101`: Critical 후보 1초, 로컬경보 2초, 서버알림 5초 목표다.
- `REQ-EVT-102`: Candidate/High/Critical Clip은 전후 3/5/10초다.
- `REQ-GEO-101`: 위치불확실성을 포함해도 위험이 유지될 때만 Confirmed다.
- `REQ-MAP-101`: 매 비행 Delta, 변화 시 부분재스캔, 기본 주 1회 전체갱신이다.
- `REQ-DATA-101`: 고객별 보존정책과 기본 보존기간을 지원한다.
- `REQ-MODEL-101`: 장비지원은 Dataset부터 Production Supported까지 단계로 표시한다.
- `REQ-PLAT-101`: 산업중립 공통플랫폼과 산업별 Solution Pack을 사용한다.
- `REQ-WRK-101`: 반복 관측은 사용자에게 하나의 Observation Work Order로 보인다.
- `REQ-ACQ-101`: 정상 경로에서 KMZ·사진 전달에 USB/SD가 필요하지 않다.
- `REQ-ACQ-102`: Edge 재촬영은 서명된 Mission Contract와 Capture Policy 안에서만 가능하다.
- `REQ-INT-101`: 변화·공정·물량은 capture-time·CRS·lineage·uncertainty와 함께 제공한다.
- `REQ-COP-101`: Copilot 사실 응답은 검증 가능한 서버 객체 근거를 포함한다.
- `REQ-COP-102`: Copilot은 재관측 초안만 만들며 승인·임무 발급 권한을 갖지 않는다.
- `REQ-SEC-101`: 모든 사람·장비·워커 접근과 데이터 반출은 조직·현장 범위로 제한한다.
- `REQ-UX-101`: 일반 작업은 5단계 이내·화면별 기본 행동 하나이며, 1024px 미만에서는
  조회·이벤트 트리아지·분석·Copilot만 제공하고 파일 수동 경로는 복구 전용이다.
