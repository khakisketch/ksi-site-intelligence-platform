# Console 목록·선택 구조 재구성 — 조사 기반 비교본

상태: **비교 프로토타입, Human 선택 대기**. 기존 A/B/C와 운영 코드는 그대로 둔다.
현재 기준은 `CONSOLE_CURRENT_SPEC.md`와 `../ledger/DESIGN.md`이며 이 제안이 이를 대체하지 않는다.
범위는 작업공간·자료의 탐색, 표시 선택, 미리보기·근거 확인이다. 업무/결과의 실제 기능,
등록·계산·V2/V3·권한·보관정책·배포 변경은 포함하지 않는다.

## 조사 질문과 방법

2026-10-27 공식 도움말 본문·첨부 화면을 직접 확인했다. 웹 검색은 HTTP402로 실패했다.
직접 제품 계정으로 조작하거나 실제 사용자를 조사한 것은 아니다. 화면에서 보인 배치,
도움말에 명시된 동작, KSI에 적용할 가정을 구분한다. 경쟁사 정확도·상용성 주장을 KSI에 전이하지 않는다.

| 출처 | 확인한 근거 | 채택 | 미채택 / 확인 한계 |
|---|---|---|---|
| [DroneDeploy: Compare Map Layers](https://help.dronedeploy.com/hc/en-us/articles/1500004860801-Compare-Map-Layers-Side-by-Side) | 본문: primary/comparison 날짜와 Compare; 첨부 화면·날짜 GIF 첫 프레임: 두 날짜 선택과 좌우 화면 | B에서 A 기준/B 비교 역할을 명시하고 자료 목록에서 직접 배정 | 정합 슬라이더·연동 카메라·측정은 미채택. KSI 크롭은 지리정합 증거가 없으므로 독립 표시 |
| [DroneDeploy: Annotation 탐색](https://help.dronedeploy.com/hc/en-us/articles/32954844662679-Filtering-and-Sorting-Annotations) | 본문: 이름 검색, 종류 필터, 날짜 정렬; 첨부 화면: 왼쪽 탐색 패널과 선택 날짜 | 검색·종류·정렬을 해당 목록 위에 배치 | Annotations는 자료 원장과 다른 객체. 해당 workflow·측정 기능은 복제하지 않음 |
| [Propeller: Navigation](https://help.propelleraero.com/hc/en-us/articles/19383551276311-Navigating-the-Propeller-Platform) | 본문: 같은 현장 안에서 Survey Picker로 날짜 변경, 현장 이동과 도구 구분 | 현장→구역→관측/자료의 선택 범위를 명확히 표시 | hardware·processing·취득 메뉴는 KSI 책임 밖 |
| [Propeller: Survey Explorer](https://help.propelleraero.com/hc/en-us/articles/25628038005399-How-to-Use-Survey-Explorer) | 본문·첨부 이미지: 연도/날짜 아래 레이어, 검색·정렬·활성 필터; 표시 레이어는 terrain/measurement를 바꾸지 않는다는 FAQ | A에서 관측 날짜 아래 정사영상/DSM 묶음, 필터 밖 선택 유지 표시, 보기≠분석 구분 | 여러 관측 합성 지도·Fly to·측정·지도범위 필터는 미채택. 크롭에 위치를 꾸며 붙이지 않음 |
| [Angelswing Digital Twin](https://angelswing.io/en/product/angelswing-digital-twin), [공식 랜딩](https://angelswing.io/en) | 제품 본문: 정사영상·DSM·mesh·point cloud 구분. 랜딩 analysis/compatibility 이미지는 결과 표현이며 완전한 탐색 UI는 아님 | 날짜와 자료 종류를 서로 다른 속성으로 구분 | 공개 Notion 가이드 본문을 얻지 못함. 목록 위치·선택 유지·모바일·세부 동작은 **미확인**. 비행/재구성·정확도 주장은 채택 안 함 |
| [Google Maps / Mobbin](https://mobbin.com/screens/a95a57eb-cec1-413c-bf22-63dc2ec20db2) — 인접 패턴 | 실제 참고 이미지: 검색 결과 목록과 지도 동시 표시 | A의 항상 보이는 탐색 목록, 제목·보조정보의 위계 | 지도/POI/평점·마케팅 동작은 채택 안 함. KSI 지도 성능 검증 아님 |
| [Linear / Mobbin](https://mobbin.com/screens/beb9d6b3-ec34-46d7-9332-320fcb32a338) — 인접 패턴 | 실제 참고 이미지: 좌측 탐색→목록→선택 상세, 선택 행 강조 | C의 목록 위치를 유지하는 선택 미리보기와 점진적 상세 | 개인 업무함·상태 workflow는 새로 만들지 않음 |

참고 이미지 원본은 조사 증거로만 로컬 보관하고 프로토타입에 재배포하지 않는다.
Mobbin 이미지는 화면으로 검토했으며 파일로 내보내지 않았다. 위 링크는 만료 이미지 URL이 아닌 정식 화면 링크다.

## 세 문제에 대한 공통 수정

- **목록을 읽기 어려움:** 자료 종류·관측 날짜가 1차 정보, 파일명·출처·형식은 보조정보.
  C에서는 전체 파일명이 셀 안에서 줄바꿈된다. 선택은 색뿐 아니라 A/B 역할 표기로 식별한다.
- **자료 목록이 숨겨짐:** 세 안 모두 기본 열린 목록. A는 왼쪽, B는 아래 배정표, C는 넓은 원장.
  작은 화면은 목록을 먼저 두고 미리보기 이동 링크를 제공한다. 목록을 자동으로 닫지 않는다.
- **관측·구역 선택이 흩어짐:** 구역 선택은 공통 맥락막대 한 곳. 관측과 자료는 같은 목록에서 고른다.
  선택한 A/B, 검색 결과 밖 선택, 자료 종류 불일치를 명시한다. 화면·시안 변경 시 선택을 유지한다.

## 흐름과 상태

공통: 현장 확인 → 구역 선택 → 관측/자료 검색 → 표시 자료 선택 → 공간 보기 → 파일·근거 확인.
B: 목록의 A/B 라디오로 두 역할 배정 → 각각의 독립 크롭 확인 → 같은 종류로 맞추거나 한 장 보기.
C: 표에서 선택 → 오른쪽 미리보기·핵심 사실 → 상세 펼침. 제품의 분석 요청/다운로드로 연결하지 않는다.

| 상태 | 표시·복구 |
|---|---|
| 정상 | 공개 원본에서 이미 만든 표시 크롭 4개. 등록 자료가 아님 |
| 검색 결과 없음 | 검색어·필터 초기화. 기존 선택/미리보기 유지, 결과 밖 선택을 명시 |
| 자료 없는 구역 | 목록·공간 모두 정직한 빈 상태, 원래 구역으로 복귀 |
| 목록 갱신 중 | 이전 목록·선택 유지, 갱신 중 표기. 실제 요청 없음 |
| 목록 오류 | 유지 중인 예시 목록과 오류 원인을 구분, 다시 보기 |
| 일부 미리보기 없음 | DSM2022만 표시 불가, 다른 자료 계속 탐색, 해당 표시만 복구 |
| 보관 만료 | 해당 화면에 크롭을 대체 표시하지 않고 기록·출처만 유지 |
| 권한 없음 | 목록과 이미지 모두 감춤. 예시 상태 해제는 권한 변경이 아님 |

24행 옵션은 같은 4개를 반복한 **합성 목록 부하 예시**다. 관측 횟수·고객 기록을 뜻하지 않는다.
자료 없는 구역도 합성 상태이며 실제 공간 geometry를 발명하지 않는다. URL/뒤로가기/새로고침에
표시 선택을 유지하되 서버·기록·localStorage를 변경하지 않는다.

## Direction contract (development-only)

**THESIS:** 같은 껍데기의 세 배치가 아니라 관측 탐색·두 역할 배정·자료 검토라는 세 업무의 차이를 비교한다.
**OWN-WORLD:** 기존 KSI 중립 팔레트, 어두운 labelled rail, 밝은 목록, 중립 공간 stage, 시스템 한글 글꼴을 계승한다. 새 브랜드/테마 결정은 하지 않는다.
**STORY:** 구역을 한 번 고르고 목록에서 날짜·종류를 이해한 다음 선택한 자료와 출처를 본다. 보기와 정량 활용을 섞지 않는다.
**FIRST VIEWPORT:** A는 336px 관측 트리+넓은 stage, B는 좌우 독립 stage+하단 역할 배정표, C는 약60% 자료 원장+선택 미리보기. 모두 목록 항목을 첫 화면에 노출한다.
**FORM:** 사용자 요청으로 고정된 A/B/C 비교의 연구 보완. 확정안 없음, 새 seed/세계관 선정 없음. Operate/code-led; 실제 적용은 선택 후 별도 승인 범위.
**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance. 기존 DESIGN.md 권위는 보존하며 이 companion과 provenance에 비교본 증거만 남긴다.

## 자료와 제한

`DEMO_MATERIALS.json`과 기존 `CONSOLE_LAYOUT_CHOICES_20261027.provenance.json`의 Cambridge
Coastcare/DataWA Floreat-f3(2021-08-17, 2022-08-24), CC BY4.0 크롭을 바이트 그대로 사용한다.
해안 자료이며 공사 현장/실등록 자료/보관 만료 원본의 복구가 아니다. EPSG:7850 표기는 원본 메타데이터이며
이 UI에 georeference가 있다는 뜻이 아니다. DSM 수직기준 미확인. 정합·면적·물량·정확도·제품 입력 지원을 주장하지 않는다.
INV-020/040/053/060/061 경계와 기존 권한·V2/V3는 변경하지 않는다.

## 검증

비교본 산출물 `docs/design/CONSOLE_LAYOUT_RESEARCH_20261027.html`를
`http://127.0.0.1:8857/preview.html`(원본 8856 보존)에서 검증했다.
너비·배치·화면 36조합(1440/1280/1024/768/390 및 실제 비교 창 1000×700,
각 A/B/C × space/materials)에서 가로 넘침이 없었다. 기본 데스크톱 목록에 2개 이상
온전한 행(B는 3행)을 확인했다. 높이 800px 이하 데스크톱은 잘라내지 않고 페이지를
스크롤하며, B는 목록을 먼저 배치한다. 1000×700 첫 화면에 A/B/C 각각 2/4/3행이 보인다.
선택 유지(시안·화면·새로고침·뒤로가기), 검색 결과 없음 시 선택 유지,
빈 구역 복귀, A/B 네이티브 키보드 배정·종류 불일치·교환, 모달 Esc·포커스 복귀,
각 화면 확대, B 근거 열기·파일명·닫기, 24행 합성 반복 스크롤, 모바일/낮은 창 미리보기 이동을 확인했다.
axe WCAG A/AA 15회 위반 0건(정상 6 + partial/expired/denied 6, 각 1440/390,
그리고 실제 비교 창 A/B/C 3회)이다. 상태는 클라이언트 전용이며 요청은 로컬 문서 GET뿐이다.
독립 검토에서 지적한 B 행 밀도·각 화면 확대·복구 색상·B 근거 토글 수정 후 비교 산출물 범위의
독립 최종 판정은 SHIP이다. 정직한 한계: B 정적 크롭은 여전히 작으며,
확대는 검사 보조이지 정적 동등이 아니다. 스크린리더·물리 터치·실사용자·계정·지리·전체 백엔드
회귀 검증이 아니며, 시안 선정이나 제품 인수가 아니다. 최종 증거 목적지는
`~/.local/state/ksi-console-ia-20261025/integration-20261026/layout-research-20261027/`이며
1·2차 실패 원본과 최종 보고·캡처·출처·재생성 소스를 보관한다.
`CONSOLE_CURRENT_SPEC.md`와 `ledger/DESIGN.md` 권위는 그대로이며 전역 DESIGN.md 개편은 없다.
