# KSI Site Intelligence Platform — 실제 UI/UX 및 구현 성숙도 감사

- 감사 실행: 2026-08-13 ~ 2026-08-14
- 기준 브랜치/HEAD: `main` / `fde4803`
- 대상: `apps/dashboard` + 로컬 Core 개발 조립
- 뷰포트: 1440×1000, 1024×768 coarse pointer, 390×844 coarse pointer
- 데이터: 로컬 개발 fixture만 사용

## 결론

현재 상태는 **핵심 업무를 실제 데이터 계보와 함께 시연할 수 있는 소프트웨어 기반 내부 알파**다.
로그인, 현장, 조사 임무 발급 전 검토, 임무, 이벤트 트리아지, 설계면/처리 요청 UI까지는
연결돼 있다. 반면 World·자산·보고서 허브·설정은 선택기 또는 목록 중심의 부분 구현이고,
Fleet·Edge와 Data·AI는 명시적인 준비 중 화면이다. 실기 PSDK 경로가 열리지 않았으므로
현장 운용 준비 완료 제품으로 볼 수는 없다.

한 개의 전체 퍼센트는 범위를 왜곡한다. 다음처럼 나누어 보는 것이 정확하다.

| 영역 | 판정 | 근거 |
|---|---|---|
| Core 도메인·계약 | 강함 | 목표 원장 기준 완료 56개, 대시보드가 실제 API와 계보를 표시 |
| 운영 Dashboard | 내부 알파 | 주요 CRUD/조회/발급 전 검토/트리아지 흐름이 실제 렌더링 |
| 분석 워크플로 | 기능 구현 중 | 설계면·비교·진척·보고서 진입점은 있으나 결과 중심 UX가 부족 |
| 2D·3D / 자산 / 보고서 허브 | 부분 구현 | 대부분 선택기·목록·빈 상태이며 핵심 결과 화면이 약함 |
| Autonomous Acquisition | 실기 차단 | 장비 부족이 아니라 `psdk_tap` 크래시와 USB bulk 채널 확인이 관문 |
| 현장 배포 준비도 | 낮음 | HIL/기체 검증 미완료, 서명 검증·RiskField·IFC 관련 원장 리스크 존재 |

## 개발 서버와 Tailscale

- Core health: `http://127.0.0.1:8010/health` → HTTP 200
- Dashboard Tailscale IPv4: `http://100.116.163.1:3020/login` → HTTP 200
- Dashboard MagicDNS: `http://dgx-spark-1.tailda9552.ts.net:3020/login` → HTTP 200
- Dashboard는 `0.0.0.0:3020`에 실행 중이다.
- `next.config.ts`에 `KSI_DASHBOARD_ALLOWED_DEV_ORIGINS`를 추가했다. 기존에는 HTML은
  열려도 Tailscale 호스트에서 Next dev chunk가 403이어서 화면과 HMR이 깨졌다.
- 실행 명령:

  ```bash
  KSI_DASHBOARD_ALLOWED_DEV_ORIGINS='100.116.163.1,dgx-spark-1.tailda9552.ts.net' \
    npm run dev -- --hostname 0.0.0.0 --port 3020
  ```

## 검증 게이트

| 게이트 | 결과 |
|---|---|
| Dashboard Vitest | PASS — 21 files, 211 tests |
| Dashboard ESLint | PASS |
| Dashboard TypeScript | PASS |
| Dashboard Next production build | PASS — 16 static pages + dynamic routes |
| Repo Ruff | PASS |
| `git diff --check` | PASS |
| Root Pytest | FAIL at collection |
| Root Mypy | FAIL at duplicate module discovery |

Root 실패는 제품 로직 단언 실패가 아니라 같은 모듈 이름을 가진
`tests/contract/test_dsm_diff.py`와 `services/change-detection/tests/test_dsm_diff.py`의
수집 충돌이다. 그러나 현재 CI가 같은 명령을 사용하므로 **현재 main의 전체 게이트는
green이라고 주장할 수 없다.**

## 가장 중요한 발견

### P0 — 신뢰성과 개발 게이트

1. **설계 기준면과 이벤트 상세에서 hydration mismatch가 재현된다.**
   Node SSR은 `PM`, 브라우저는 `오후`로 날짜를 포맷해 React가 해당 트리를 다시 만든다.
   `DesignSurfacePanel.tsx:151`, `EvidencePanel.tsx:166` 부근의 locale 시간 포맷을
   결정론적 24시간 포맷으로 통일하고 SSR hydration 회귀 테스트를 추가해야 한다.
2. **Root Pytest/Mypy 수집 충돌을 닫아야 한다.** 기능 변경 전에도 CI 신뢰도를 훼손한다.
3. **리스크 원장 자체 정합성이 필요하다.** `bim-integration-ifc-mm-unit-double-scale`는
   `resolve_evidence`가 있는데도 `open/high` 상태다. 구현이 고쳐졌는지, 원장 상태가
   뒤처졌는지 확인하기 전에는 해소로 간주하면 안 된다.

### P1 — 사용자가 더 빨리 판단하고 행동하게 만들기

1. 홈을 9개 현장 카탈로그에서 **오늘의 작업 큐**로 바꾼다. 긴급 이벤트, 처리 중 작업,
   모델 최신성, 오늘 임무, 차단된 다음 행동을 먼저 보여주고 현장은 우선순위 3개만 노출한다.
2. 이벤트 상세를 **증거 우선**으로 바꾼다. 이미지/클립, 지도 위치, RiskField/궤적 근거를
   중심에 놓고 확인·미확정·오탐·담당자·기한·재확인 행동을 고정 액션 영역에 둔다.
3. 임무 상세를 계약 필드 묶음이 아니라 `발급 → 촬영 → 업로드 → 처리 → World 갱신 → 검토`
   단계 타임라인으로 바꾸고 현재 단계의 한 가지 주 행동을 강조한다.
4. 8단계 현장 등록에서 미지원 단계를 제거하거나 사전조건으로 분리한다. CRS, datum,
   WPML enum, policy ID는 기본 흐름에서 자동 추론하고 전문가 모드로 숨긴다.
5. World·자산·보고서·설정을 결과 중심으로 완성하기 전에는 기본 내비게이션 비중을 줄인다.
   준비 중인 Fleet·Edge/Data·AI는 로드맵이나 실험실 영역으로 묶어 dead end를 줄인다.

### P2 — 구조와 접근성

1. TopBar와 본문이 동시에 `h1`인 상세 화면을 한 개의 canonical `h1`로 통일한다.
2. 모바일에서 44px 미만인 `전체 보기`, `이벤트 이력`, 지도 zoom, 상세 인라인 링크의
   터치 영역을 확대한다. 라디오 input 자체는 13px지만 행 전체 label이 터치되므로 오탐이다.
3. raw ID/digest/enum은 복사 가능한 보조 정보로 접고, 한국어 업무 용어를 먼저 표시한다.
4. 스크린샷 검사는 완전한 WCAG 판정이 아니다. axe, VoiceOver/TalkBack, 확대/고대비,
   오류 상태와 modal focus-trap 검증을 별도 게이트로 둔다.

## 페이지별 감사

| 단계 | 페이지/흐름 | 상태 | 강점 | 핵심 문제와 개선 방향 |
|---:|---|---|---|---|
| 01 | 로그인 | 양호(개발용) | label, 오류 경계, httpOnly cookie | Bearer token은 개발자 UX다. 운영은 SSO/OTP, 환경 배지, 만료 복구 필요 |
| 02 | 홈 | 동작하지만 과밀 | 긴급 CTA, SLA/미조치/신뢰 상태가 정직함 | 9개 현장 전체가 모바일 2,700px 이상. 업무 큐 + 상위 3개로 축약 |
| 03 | 현장 목록 | 양호 | 긴 이름 줄바꿈, 미매핑 이유 명확 | 검색·필터·정렬·최근 갱신·주의 필요 그룹이 없음 |
| 04 | 현장 상세 | 기능적 | AOI 지도, 설계·작업구역·임무·이벤트 연결 | 분석과 관리가 한 긴 페이지에 경쟁. 상태 전이는 관리자/전문가 영역으로 이동 |
| 05 | 작업구역 | 부분 구현 | 지도와 생성 컨텍스트 존재 | 빈 상태와 기술적 입력 중심. 지도에서 먼저 그리기/선택하고 계획·진척 의미를 미리보기 |
| 06 | 설계 기준면 | 기능적·오류 | CRS, 수직 기준, 계보, sealed 상태가 명확 | hydration 오류. digest/CRS를 고급 옵션으로 접고 활성 revision과 신뢰도를 먼저 표시 |
| 07 | 계획 대비 진척 | 얇은 셸 | 설계면 호환성을 먼저 확인 | 선택기 뒤 큰 공백. 최신 sealed 기준 자동 선택 + 최근 결과·불확실성 요약 필요 |
| 08 | 현장 보고서 | 얇은 셸 | 설계면 기준을 분명히 함 | 보고서 preview/history가 없고 선택기만 보임. eligible 최신 결과 기본 표시 |
| 09 | 등록 방식 선택 | 양호 | 빠른 등록과 전체 흐름을 명시적으로 분리 | 대상 사용자·예상 시간·요구 자료·추천 경로를 비교해 기본 추천 제공 |
| 10 | 현장만 등록 | 양호 | data residency를 unset/deny로 안전하게 처리 | 초보자에게 정책 용어가 어려움. 사람 말 설명과 조직 기본값 필요 |
| 11–16 | 전체 현장 등록 1–6단계 | 기능적·과도한 단계 | 자동저장, 실제 Leaflet AOI, 미지원 BIM의 정직한 표기 | 미지원 BIM/회피 단계가 dead step. 위치로 CRS 추론, 고급 필드 숨김, 동적 단계 구성 |
| 17 | 임무 목록 | 양호 | 발급 사실과 ID가 일관됨 | 전부 issued 카드처럼 보여 운영 상태를 알기 어려움. 준비/비행/처리/완료 필터 필요 |
| 18 | 임무 상세 | 기능적·복잡 | KMZ, source media, 처리, 비교, conformance 계보가 연결 | 패널이 평면적으로 누적. 단계 타임라인과 현재 주 CTA로 재구성 |
| 19 | 이벤트 목록 | 가장 성숙 | SLA dwell, 필터, split view, 불확실 상태 표현 | 증거 thumbnail, 현장/기간 검색, 담당자·기한 필터 부족 |
| 20 | 이벤트 상세 | 기능적·오류 | 오탐 종결을 근거 입력 전 차단, 계보 보존 | hydration 오류, 증거가 파일 행에 머묾. 증거·지도 중심 + sticky triage action |
| 21 | 자산·시설물 | 부분 구현 | 실제 mission media를 보여줌 | 제목은 asset registry지만 내용은 source media. 두 정보구조를 분리 |
| 22 | 2D·3D World | 부분 구현 | 사이트 선택 경계가 명확 | 실제 World보다 사이트 선택기다. 마지막 현장 기본값, layer/freshness/uncertainty, 2D/3D 전환 필요 |
| 23 | 보고서 허브 | 부분 구현 | eligible mission을 찾을 수 있음 | 보고서 catalog/history/preview/filter가 없음 |
| 24 | 설정 | 부분 구현 | 장비 지원단계 빈 상태를 숨기지 않음 | 범용 설정 제목과 단일 장비 관리 내용 불일치. 역할 기반 관리자 메뉴로 명확화 |
| 25 | Fleet·Edge | 준비 중 | 미구현을 mock으로 숨기지 않음(INV-040) | 기본 내비게이션의 지속적인 dead end. 로드맵/실험실로 이동 |
| 26 | Data·AI | 준비 중 | 미구현을 명확히 고지 | Fleet와 동일 |
| 27–30 | 조사 임무 Wizard 1–4단계 | 기능적 | site-state gating, 비활성 사유, 발급 전 검토가 정직함 | raw enum/policy 노출, 비활성 옵션 과다, 지도 경로·시간·배터리·기체 준비도 preview 부재 |
| 31–39 | 태블릿/모바일 재검증 | 대체로 양호 | 가로 overflow 없음, 5-tab nav, 주요 control 44px | 인라인 링크와 Leaflet control target, 긴 홈, 중복 h1 개선 필요 |

## 반응형·접근성 관찰

- 1440/1024/390에서 감사한 모든 화면에 가로 overflow가 없었다.
- desktop Tab 첫 8단계는 홈→현장→임무→이벤트→자산→World→보고서→Fleet 순으로 이동했고
  2px solid focus outline이 보였다.
- 주요 nav/button은 coarse pointer에서 44px였지만 일부 텍스트 링크와 Leaflet zoom은 작았다.
- 모든 가시 form control은 자동 검사에서 접근 가능한 이름을 가졌다.
- 색만으로 상태를 표현하지 않고 대부분 텍스트를 병기한다.
- 상세 화면 다수에 `h1`이 두 개다. 스크린리더 문서 구조와 화면 계층 모두에 혼선을 준다.

## 문서/현실 불일치

- `PHASE_REGISTRY.yaml`은 아직 H1–H4를 장비 조달·승인과 `AIRCRAFT_LINK_DOWN`으로 묘사한다.
- `REMAINING_WORK_PLAN.md`와 목표 원장은 2026-08-13 실측으로 장비·자격이 확보됐고,
  실제 blocker가 `psdk_tap` 크래시와 USB bulk 채널임을 명시한다.
- 따라서 제품/로드맵 UI도 “장비 대기”가 아니라 “실기 디버깅·검증 대기”로 표현해야 한다.

## 목표 원장과 남은 위험

- 목표 상태: completed 56, in_progress 2, blocked 3, abandoned 5,
  false_positive_complete 1.
- accepted/high: 카메라 없는 직접 API 간격 경로에서 40ha/사진 10장도 coverageRatio 1.0 가능.
  Dashboard의 일반 사용자 경로는 CameraSpec 전용이라 노출이 제한되지만 H4 후 정책 재검토가 필요하다.
- open/medium: Mission Contract 서명 검증 프로덕션 consumer 0.
- open/medium: CRITICAL event RiskField evidence가 실존/내용 검증이 아니라 presence gate에 머묾.
- open/high: IFC mm georeference 이중 scale 항목은 원장 상태와 resolve evidence가 충돌한다.
- open/low: patrol capture cadence의 실제 비행 시간·배터리 미검증.
- open/low: comparison/design workers가 OSError 시 FAILED로 수렴하지 않을 수 있음.

## 증거와 감사 한계

- DOM/콘솔/요청 증거: `2026-08-13-ui-ux/browser-evidence.json`
- 반응형/터치/키보드/지도 증거: `2026-08-13-ui-ux/responsive-evidence.json`
- 원본 화면: `2026-08-13-ui-ux/screenshots/`
- 감사 중 로컬 데이터를 바꾸지 않기 위해 현장 생성 마지막 제출, Mission Contract 발급,
  source upload/processing 실행, event triage 저장은 누르지 않았다.
- 실제 기체, RC, Manifold, HIL이 없으므로 비행·텔레메트리·카메라·배터리·KMZ import·RTH를
  검증하지 않았다. Dashboard가 렌더링된다는 사실을 Autonomous Acquisition 완료 증거로 쓰지 않는다.

## 권장 다음 마일스톤

1. hydration + root CI 수집 충돌 + 원장 상태 충돌을 먼저 닫는다.
2. 홈/이벤트/임무를 업무 중심 IA로 재구성한다.
3. 등록 Wizard를 동적 단계와 기본/전문가 모드로 단축한다.
4. World·자산·보고서 중 하나를 선택해 selector shell이 아닌 끝까지 완료되는 결과 경험으로 만든다.
5. H1/H3/H4 실기 세션에서 제품 UI가 표시할 실제 준비도·진행 상태·실패 원인을 수집한다.

## 2026-08-14 감사 후속 구현

감사에서 재현된 문제 중 Dashboard만으로 안전하게 고칠 수 있는 항목을 구현했다. Core 계약,
기체 제어, fixture 데이터는 바꾸지 않았으며 다음 항목은 모두 기존 Core 사실만 사용한다.

| 영역 | 반영한 개선 | 확인 방식 |
|---|---|---|
| 시간·신뢰성 | Node/브라우저 locale 차이로 난 hydration mismatch를 Seoul 고정 24시간 포맷으로 통일 | Dashboard 단위 테스트와 실제 Chrome console error 0건 |
| 개발 게이트 | 중복 이름의 change-detection DSM 테스트 파일을 `test_dsm_diff_worker.py`로 변경 | 두 DSM 모듈 동시 수집 12 passed, mypy 294 source files clean |
| 홈 | 9개 현장 카탈로그를 상위 3개 현장 + 실제 미조치 이벤트/차단 현장 기반의 `지금 확인할 일`로 재구성 | 로그인한 Home 렌더 캡처 |
| 현장 | 검색·상태 필터·주의/최근/이름 정렬, 상세의 실제 상태별 다음 행동, 관리자 상태 전이 접기 | `/sites` 실제 렌더 |
| 임무 | 카드의 다음 확인 문구와 계약→비행 보고→사진→재구성→비교의 정직한 라이프사이클 추가 | `/missions`, 임무 상세 실제 렌더 |
| 이벤트 | 현장 필터 추가, 이벤트 상세에서 증거를 이력/제어보다 먼저 배치하고 판단 안내 및 sticky 사실/제어 열 추가 | 상세 DOM에서 `증거`가 `전이 이력`보다 먼저, console error 0건 |
| 분석 허브 | 자산·World·보고서의 raw ID 선택 목록을 현장/임무 맥락 카드로 전환하고, 설계면 선택에는 검증 상태·시각을 표시 | `/assets`, `/world`, `/reports` 실제 렌더 |
| 미지원 기능 | Fleet·Data 준비 중 화면에 현재 가능한 안전한 다음 행동을 추가하고, BIM/제외구역이 실제 제어를 제공하지 않는다는 사실을 명시 | fixture 변경 없이 실제 렌더 |
| 접근성·모바일 | canonical `h1` 하나, skip link, 44px coarse-pointer/지도 zoom, 작은 주요 링크 확대, 이벤트 현장 filter의 긴 option 가로 overflow 수정 | 390px 실측 `scrollWidth = clientWidth`, visible tap target violation 0건 |

새 브라우저 증거는 `2026-08-13-ui-ux/post-improvement-*.png`에 저장했다. Chrome 1440px에서
홈·현장·임무·이벤트·자산·World·보고서·설정·Fleet가 모두 200/오류 오버레이 없음으로
렌더링됐으며, 390px 이벤트 목록도 수평 overflow 없이 렌더링됐다.

### 이번 범위 밖의 잔여 문제

- 실제 비행·기체/배터리/Edge 연결·RTH·카메라 품질은 UI가 확인할 데이터 경로와 HIL 증거가
  없으므로 여전히 미검증이다.
- World의 3D 탐색, 자산대장, 보고서 카탈로그/이력, Fleet·Data 관리 API는 별도 Core 계약과
  운영 데이터가 필요하다. 현재는 기능이 없다는 사실과 이용 가능한 경로만 정직하게 표시한다.
- 설계면 선택은 안전상 자동으로 "최신"을 고르지 않는다. 사용자가 기준면을 명시적으로
  선택하되, 이제 상태·검증 시각을 보고 판단할 수 있다.
