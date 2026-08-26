# ADR-KSI-024 — Operations Console 화면 경계와 반응형 현장 UX

- 상태: ACCEPTED (2026-08-21, 대표자 확정)
- 관련 요구사항: REQ-UX-101, REQ-WRK-101, REQ-MSN-101, REQ-ACQ-101/102,
  REQ-SEC-101
- 관련 불변식: INV-001/002, INV-011/012, INV-040/041, INV-050/051, INV-060
- 대체 범위: ADR-KSI-017의 “Pilot 2 웹뷰·RC 브라우저에서 KSI 현장 화면 사용” 결정
  (MSDK 비행 앱을 만들지 않는 결정과 preflight/postflight Bridge 조건은 유지)

## 맥락

RC Plus 2와 Pilot 2는 이륙·비행·촬영·기체 상태를 다루는 비행 전용 화면이다.
KSI의 작업 승인, 공간정보 검토, 원본 동기화, 분석과 Copilot을 같은 화면에 얹으면
조종자의 주의를 나누고 RC가 KSI 업무 시스템의 성립 조건이 된다. RC가 KSI Cloud의
지상 gateway라는 사실과 사람이 KSI 업무 화면을 보는 단말은 서로 다른 책임이다.

현장 노트북·컴퓨터는 지도, 시점 비교, 원본과 계보, 긴 근거 문장을 검토하기에 적합하다.
스마트폰도 같은 KSI Cloud에 접근할 수 있으나, 작은 화면에서 Mission 발급·재관측 승인·
장비 전이를 정상 행동으로 제공하는 것은 피한다. 별도 모바일 제품을 만들면 계약·상태·
권한과 디자인이 두 벌로 갈라지므로 하나의 반응형 Web을 유지한다.

## 결정

### D1 — 하나의 KSI Operations Console을 사용한다

- `apps/dashboard` 하나가 데스크톱·태블릿·모바일을 모두 담당한다.
- 현장 업무의 기본 단말은 노트북 또는 현장 컴퓨터다.
- 기존 `/field` URL과 deep link는 유지하되 일반 Dashboard shell 안의 작업 큐로
  재정의한다. RC 전용 chromeless shell이나 별도 로그인 흐름을 사용하지 않는다.
- RC Plus 2는 Pilot 2 비행 화면과 KSI Cloud gateway 통신만 담당한다. 제품의 정상
  경로에서 RC에 KSI 업무 화면을 표시하지 않는다.

### D2 — 1024px에서 행동 밀도를 나눈다

- `1024px 이상`은 전체 Operations Console이다.
- 그 미만은 같은 URL·계약·계정의 압축 표현이다. 조회, 이벤트 triage, 분석 검토,
  보고서 열람·다운로드와 Copilot 질의를 제공한다.
- WorkOrder 승인, 재관측 승인, Mission 발급·비행 준비, Site/장비 전이, manual
  dispatch, 원본 업로드·봉인과 복구 행동은 작은 화면에서 렌더하지 않고
  “노트북에서 계속” 안내를 표시한다.
- Copilot은 모바일에서도 재관측 **초안**을 만들 수 있지만 승인하거나 실행 계약을
  발급하지 않는다(INV-002).

이 화면 폭 분기는 실수 방지를 위한 UX·운영 절차이며 보안 신원이 아니다. Core는
클라이언트가 주장한 viewport를 신뢰하지 않고 기존 사람 Principal·permission·조직 범위로
모든 요청을 계속 검증한다. 향후 특정 인증·규제가 등록 워크스테이션을 요구할 때만
장치 신뢰 계약을 별도 ADR로 추가한다.

### D3 — 사람은 OIDC, 장비는 별도 자격을 쓴다

- 외부 배포에서 사람 OPERATOR는 OIDC Authorization Code + PKCE로 로그인한다.
- `GATEWAY_DEVICE`, `EDGE_DEVICE`, `PROCESSING_WORKER`의 별도 최소권한 자격은 OIDC
  사람 세션과 합치지 않는다.
- OIDC 사업자는 배포 환경에서 교체할 수 있어야 하며 issuer·audience·KSI claim
  계약으로만 Core와 결합한다.
- 개발용 opaque 사람 토큰은 localhost 개발과 migration에만 유지한다. 외부 공개
  production은 OIDC 설정이 없으면 기동을 거부한다.

### D4 — Pilot Bridge 진단은 HIL 도구다

- `window.djiBridge` 탐지는 제품 화면과 기능 gate에서 제거한다.
- Bridge key 관측은 non-production HIL 전용 경로에서만 수행하고 production에서는
  404다.
- Cloud 하향 또는 media 회수 실패 시 조건부 MSDK Bridge를 검토한다는
  ADR-KSI-023 D5는 유지하지만, Bridge도 KSI 비행 화면을 만들지 않는다.

### D5 — 외부 Cloud는 준비와 승인 배포를 구분한다

- 첫 구현은 KSI 개발 장비에서 TLS·OIDC·백업·복구가 가능한 VM 조립을 검증한다.
- 특정 Cloud 사업자를 코드에 고정하지 않는다.
- 실제 고객 원본·위치정보·공간모델은 데이터 소재지, 처리위탁·재위탁, 국외이전,
  암호화, IAM/MFA, 침해 통지, 보존·삭제·반환과 복구 조건을 검토해 승인된 Cloud가
  정해진 뒤에만 외부 배포한다.

## 구현·수용 기준

- `/field`는 일반 Dashboard navigation과 session을 사용한다.
- 390/768px에서는 이벤트·Copilot은 동작하고 비행·Mission·장비 관련 primary action은
  존재하지 않는다. 1024/1440px에서는 권한 있는 사용자가 같은 URL에서 전체 행동을 본다.
- RC 인터넷 readiness와 Operations Console 사용자 세션 상태를 하나의 “연결됨”으로
  합치지 않는다.
- production profile은 OIDC·TLS·secret 누락을 fail-closed하며 mock IdP나 static
  always-go를 사용하지 않는다(INV-040).
- 실제 DJI capability와 HIL 등급은 이 UI 결정으로 승격하지 않는다(INV-041).

## Rollback

- `/field` URL과 WorkOrder/Mission 원장은 바꾸지 않아 데이터 migration이 없다.
- VM compose는 기존 로컬 compose에 대한 additive override로 둔다.
- OIDC migration은 `DUAL`로 되돌릴 수 있으나 외부 공개 환경에서 opaque 사람 토큰을
  정상 운영 경로로 사용하지 않는다.
- RC 전용 KSI 화면은 rollback 경로로 복원하지 않는다. Bridge probe만 HIL 도구로 남긴다.
