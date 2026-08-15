# DJI Cloud API — Wayline(임무) 원격 배포 경로 조사 (G3용)

> **[2026-08-15 범위 한정 — ADR-KSI-020]** 이 조사는 **Cloud API 축만** 다뤘다.
> 아래 §핵심 결론의 "Dock을 사지 않는 한 DJI 쪽에 그런 경로 자체가 없다"는 문장을
> **온보드(PSDK) 축까지 일반화해 읽으면 안 된다** — 그 축은 이 조사의 대상이
> 아니었고, 실제로는 `DjiWaypointV3_UploadKmzFile` + `_Action(START)` 로 Dock 없이
> 성립 가능한 경로가 핀된 PSDK 3.16.0 안에 있다(ADR-KSI-020 §2).
>
> **Cloud API 축의 조사 결과 자체는 유효하며 철회하지 않는다** — 사람이 현장에
> 없는 형태(서버→기체 원격 배포)를 원할 때 다시 필요하다.

> 2026-08-15 조사. 출처는 DJI 공식 GitHub 미러 `dji-sdk/Cloud-API-Doc`(developer.dji.com
> Cloud API 문서의 원문 소스로 보임)와 그 사이트 자체를 검색엔진 경유로 확인한 결과다.
> **주의**: `dji-sdk/Cloud-API-Doc` 저장소의 마지막 커밋은 2024-11-07(v1.11.3)이다 —
> 이후(2025-02-27 갱신 등)는 이 GitHub 미러에는 반영되지 않았고, 라이브 사이트
> (developer.dji.com)는 JS 렌더링이라 이 세션의 웹 조회 도구로 원문을 직접 못 읽었다.
> 그래서 2025-02-27 이후 항목은 검색엔진 요약을 근거로 삼았다 — 표에 "근거 등급"으로
> 구분해 뒀다. 직접 원문을 인용한 것은 GitHub raw 파일뿐이다.

## 핵심 결론 — G3 설계에 가장 중요한 것

**"Wayline Management"(사전 계획된 임무 파일을 업로드해 발급·실행·취소하는 기능,
G3가 필요로 하는 바로 그 기능)는 DJI Cloud API 안에서 지금까지 확인된 모든 문서
경로가 예외 없이 `Dock-to-Cloud` 쪽에만 있다. `Pilot-to-Cloud`(Dock 없이 Pilot 2 +
RC 만 쓰는 경로 — 이 저장소의 Profile A 구성과 동일) 쪽에는 Wayline Management 파일
자체가 문서 구조 어디에도 없다.** Pilot-to-Cloud 쪽에 있는 것은 "Live Flight
Controls(DRC)"뿐인데, 이건 사전 계획 임무 업로드가 아니라 **실시간 조이스틱형
원격조종**(fly-to-point, 짐벌 회전, 이·착륙 등을 그때그때 명령)이다 — 계획을 미리
짜서 던져놓고 무인으로 실행시키는 것과는 다른 기능이다.

즉 지금 확보한 근거로는: **Dock 없이 M4D + RC Plus 2 + Pilot 2 조합만으로 서버가
사전 계획 임무(KMZ/WPML)를 무인 배포·실행시키는 공식 Cloud API 경로는 존재하지
않을 가능성이 높다.** 이게 맞다면 G3의 "임무를 기체까지 자동으로 보내는 공식
경로 없음"은 "아직 확인이 안 됐다"가 아니라 "**Dock을 사지 않는 한 DJI 쪽에
그런 경로 자체가 없다**"에 더 가깝다 — ADR-KSI-004가 미확인으로 남겨둔 지점을
한 단계 더 좁힌다.

## 확인됨 (GitHub raw 파일 원문 직접 인용)

1. **Cloud API 공식 지원기종 표**(`dji-sdk/Cloud-API-Doc`, `docs/en/10.overview/30.product-support.md`,
   2024-11-07 시점)에는 Matrice 4D/4TD·RC Plus 2가 **전혀 없다**. 이 표의 아키텍트는
   Matrice 350 RTK·Matrice 300 RTK·Matrice 30/30T·Mavic 3 Enterprise·Matrice 3D/3TD
   (Dock 2 전용) 뿐이다.
   URL: https://github.com/dji-sdk/Cloud-API-Doc/blob/master/docs/en/10.overview/30.product-support.md

2. **저장소 최신 커�밋은 2024-11-07**(v1.11.3) — 그 뒤로 이 GitHub 미러는 갱신되지
   않았다. 즉 위 1번은 "M4D가 영원히 미지원"의 근거가 아니라 "그 시점까지는
   미지원이었다"는 근거일 뿐이다.
   URL: https://github.com/dji-sdk/Cloud-API-Doc/commits/master

3. **Pilot-to-Cloud 접속 구조**(`docs/en/30.feature-set/10.pilot-feature-set/10.pilot-access-to-cloud.md`) —
   Pilot 2 안에 내장된 웹뷰가 우리 서버의 HTML 페이지를 HTTPS로 로드하고,
   `window.djiBridge.*` JSBridge 함수로 인증(라이선스 검증·토큰 조회)과 워크스페이스
   설정을 한 뒤, **MQTT 자격증명**을 서버에서 받아 클라우드 모듈을 연다. 즉 JSBridge는
   부트스트랩(인증·UI 로딩) 계층이고, 실제 데이터는 MQTT로 흐른다 — 이 저장소가 이미
   실기로 확인한 "RC Plus 2 브라우저로 사내 대시보드 접속 가능"(ADR-KSI-004)이 바로
   이 웹뷰 진입점일 가능성이 높다.
   URL: https://github.com/dji-sdk/Cloud-API-Doc/blob/master/docs/en/30.feature-set/10.pilot-feature-set/10.pilot-access-to-cloud.md

4. **문서 구조상 "wayline" 파일은 전부 `dock-to-cloud` 경로 아래에만 있다**
   (`.../dock-to-cloud/mqtt/dock/dock1/wayline.md`, `.../dock2/50.wayline.md` 등).
   `pilot-to-cloud` 아래에는 wayline 관련 파일이 검색·구조 조회 어느 쪽에서도
   나오지 않았다 — 있는 것은 `mqtt/rc-pro/drc.html`(Live Flight Controls)과
   `mqtt/rc-pro/remote-control.html`(원격조종 프로토콜)뿐이다.
   URL: https://github.com/dji-sdk/Cloud-API-Doc/blob/master/docs/en/30.feature-set/20.dock-feature-set/50.dock-wayline-management.md
   (Dock 쪽 것 — 이게 Wayline Management 문서가 실제로 사는 유일한 자리라는 증거)

## 확인됨이지만 근거가 검색엔진 요약(직접 원문 인용 아님) — 2025-02-27 이후 갱신분

5. Cloud API가 **2025-02-27**에 `DJI Dock 3`·`Matrice 4D/4TD`·`AL1 Searchlight`·
   `AS1 Megaphone`을 새로 지원하기 시작했다. 이 갱신은 두 곳에 걸쳐 있다:
   - **Dock-to-Cloud**: DJI Dock 3가 Custom Flight Area·Remote Unlocking·강제착륙·
     가상조종석 경유 항로 배포·시뮬레이터 고도 설정을 새로 지원.
   - **Pilot-to-Cloud**: Matrice 4D/4TD가 **Live Flight Controls의 POI Mode**를
     새로 지원(=DRC 계열, Wayline Management 아님).
   두 차례 독립된 검색에서 같은 문구로 일관되게 나왔다(release-note 특유의 표현
   패턴과도 일치) — 신뢰도는 높지만 GitHub raw 파일로 직접 대조하진 못했다(그
   시점 갱신분이 이 미러에 없다, 위 2번).
   검색 근거: developer.dji.com Cloud API release notes 요약(2025-02-27)에 대한
   검색엔진 조회 — 직접 URL 앵커는 확보하지 못함(developer.dji.com 라이브 페이지가
   이 세션의 WebFetch로는 JS 셸만 보이고 본문이 안 읽힘).

6. `docs/dji/11_DJI_CAPABILITY_VERIFICATION.md`(이 저장소, 이전 조사)도 "Cloud API
   supports Dock 3 and Matrice 4D/4TD"라고 이미 적어뒀다 — 5번과 정합적이나, 그
   문서도 Pilot-to-Cloud 대 Dock-to-Cloud 구분은 하지 않았다.

## 미확인 (공식 문서에서 못 찾음 — 추측하지 않는다)

- Matrice 4D/4TD + RC Plus 2(Dock 없음) 조합에서 Wayline Management 가 **전혀
  안 되는지**, 아니면 문서화가 늦어졌을 뿐 실제로는 되는지 — GitHub 미러가
  2024-11-07 이후 멈춰 있어 이 시점 이후 신설 여부를 원문으로 확인할 방법이 이
  세션엔 없었다.
- JSBridge의 "wayline management module"(HTTPS 경유로 로드된다는 언급이 검색
  요약에 있었다)이 실제로 사전 계획 임무를 업로드·실행시키는 기능인지, 아니면
  지도에 항로를 "보여주기"만 하는 뷰어 수준 기능인지 — 원문을 못 읽어 구분 불가.
- PSDK(Manifold ↔ 기체) 쪽 M4D 공식 지원 매트릭스 — 이번 조사는 Cloud API에
  집중했고 PSDK 지원표는 확인하지 않았다(Track A HIL 세션 기록이 이미 실기로
  PSDK App Key/샘플 빌드까지 확인했으므로 이 조사의 시급도가 낮다고 판단해
  건너뜀 — 필요하면 별도 조사).
- RC Plus 2 자체의 독립 프로그래밍 인터페이스(웹뷰/JSBridge 말고 다른 것) —
  못 찾음.

## M4D/Pilot Cloud 지원 여부 — 최종 결론

**기종별로 다르고, 기능별로도 다르다.** Matrice 4D/4TD 는:
- Dock-to-Cloud(Dock 3 경유): Wayline Management **포함** 폭넓게 지원(2025-02-27~).
- Pilot-to-Cloud(Dock 없음, 이 저장소의 실제 구성): Live Flight Controls(DRC,
  실시간 조종)만 확인됨. **Wayline Management 는 이 경로에서 지원된다는 근거를
  찾지 못했고, 문서 구조상 애초에 그 카테고리 자체가 Pilot-to-Cloud 에 없다.**

## G3 설계에 주는 시사점

1. **"프로토콜-무관 부분만 먼저 만든다"는 선택지가 지금은 사실상 유일하게 안전한
   경로다.** MQTT/Wayline 클라이언트를 Pilot-to-Cloud 대상으로 지금 만들면, 그
   기능이 애초에 그 경로에 없을 가능성이 있는 것을 만드는 셈이다 — 이미 이번
   세션에서 완성한 `MissionExecutionStatus`·디스패치 큐·재시도·관측성(AOL-1 G2)이
   바로 그 "프로토콜-무관 부분"이고, 이미 돼 있다.
2. **웹뷰/JSBridge 경로(위 3번)는 재평가할 가치가 있다.** MQTT Wayline이 막혀 있어도,
   Pilot 2 웹뷰에 우리 대시보드를 띄우고 JSBridge로 "이 항로를 로드해라" 정도의
   상호작용이 실제로 가능하다면, 완전 수동(KMZ 파일을 손으로 옮김)과 완전 자동
   사이의 절충안이 된다 — 사람이 Pilot 2 를 열고 우리 화면을 보는 것까지는 여전히
   필요하지만, 그 다음부터는 클릭 한 번으로 항로가 실린다. 다만 "wayline management
   module"의 실제 기능 범위가 미확인이라 이것도 실기 확인이 선행돼야 한다.
3. **DJI Dock 3 도입은 제품 결정 사항이지 이 조사의 결론이 아니다.** Dock 경로는
   Wayline Management 를 포함해 훨씬 폭넓게 지원되지만, Dock 도입은 ADR-KSI-004가
   이미 Phase 5(Profile B)로 미뤄둔 별도 결정이고 이 조사가 그 결정을 뒤집을
   근거는 못 된다 — Dock 없이 얼마나 갈 수 있는지를 밝히는 게 이 조사의 목적이었다.
4. 다음 실기 세션에서 실제로 값싸게 확인할 수 있는 것: RC Plus 2 웹뷰에서
   `window.djiBridge` 가 실제로 존재하는지, `platformVerifyLicense`/`apiGetToken`
   이 우리 App Key/License 로 실제로 통과하는지 — 이건 Wayline 발급을 안 걸어도
   되는 read-only에 가까운 확인이라 위험이 낮다(ADR-KSI-004 결정 4번이 이미
   같은 취지로 "최소 접속점만 먼저 만들어 확인한다"고 정해뒀다).
