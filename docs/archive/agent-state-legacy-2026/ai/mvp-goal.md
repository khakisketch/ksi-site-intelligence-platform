> HISTORICAL / NOT CURRENT: This preserved record is context only. Read `docs/00_READ_FIRST.md`,
> `docs/superpowers/product-state.md`, and its named ledger; revalidate Git. No old next action here
> supplies external authorization.

# KSI MVP goal (2026-08-20, UX reset)

현장 작업자가 KMZ, USB, SD 카드, 사진 폴더, EXIF, processing job을 직접 다루지 않고
`오늘 작업 선택 → 비행 승인 → 자동 수집·처리 → 근거가 있는 답변 → 재관측 승인`을
완료하는 KSI Site Intelligence MVP를 만든다.

제품의 첫 유료 가치는 “더 좋은 waypoint 편집기”가 아니라 건설현장의 반복 관측을
변화·공정·물량·점검 결과로 바꾸고, 비전문가도 자연어로 묻고 근거를 확인하게 하는
것이다. 파일 수동 이관은 정상 경로가 아니라 검증·장애 복구용 fallback이다.

## 제품 경계

- DJI Flight Controller: 비행 안정화, 저수준 제어, DJI 보호기능과 RTH
- DJI Pilot 2: 조종사의 비행·안전 표면. 가능한 한 교체하지 않는다.
- KSI Field UX: 오늘 작업, 준비상태, 승인, 전송·처리 상태, 실패 복구만 보여준다.
- KSI Server: 원본·공간모델·시계열 비교·변화·공정·물량·계보의 계산과 저장
- KSI Copilot: 검증된 서버 결과를 도구로 조회해 설명·요약·업무 초안을 만든다.
  원시 사진에서 숫자를 지어내거나 비행 좌표·안전 명령을 만들지 않는다.
- 사람: 이륙, 안전 예외, 재관측, finding, 대외 보고와 계약성 물량을 최종 승인한다.
- PSDK/Manifold 3: 흐림·가림·관측 누락·target loss처럼 비행 중 즉시 복구해야 하는
  국소 판단과 offline store-and-forward를 담당한다. 수백~수천 장의 재구성·시점
  비교·전체 현장 물량 계산은 서버에 둔다.
- MSDK: Pilot 2 Cloud/FlightHub 2 또는 Manifold 경로로 무파일 UX를 달성하지 못할
  때만 얇은 현장 앱으로 도입한다. Pilot 2 기능 전체를 복제하지 않는다.

## 현재 마일스톤

M4D + RC Plus 2에서 다음 세 후보를 실기로 비교하는 `Zero-touch Integration Spike`를
먼저 수행한다.

1. FlightHub 2 / Pilot-to-Cloud: KSI 작업 표시, cloud wayline 확보, 자동 media upload
2. Manifold 3 PSDK: KSI 작업 수신, camera media download, 직접 store-and-forward
3. MSDK V5: 위 두 경로가 막힐 때 작업 수신, KMZ upload/execute, media download/upload

사용자가 이미 내려받은 사진 폴더를 받는 현재 `ingest_watch --mission-id`는 Spike가
실패하거나 네트워크가 없는 경우의 fallback으로 유지한다.

## 완료 경계

- 실제 장비에서 경로와 원본이 자동 왕복하기 전에는 zero-touch를 완료로 주장하지 않는다.
- M4D + RC Plus 2의 Pilot-to-Cloud 기능 조합은 공식 문서 표기가 일치하지 않으므로
  실기에서 검증하기 전까지 `NOT_VERIFIED`다.
- MSDK와 Pilot 2의 동시 운용은 검증 전까지 전제하지 않는다.
- 원본 사진을 이동·변경·삭제하지 않는다.
- 기존 KMZ·수동 ingest·FIELD/HIL 증거는 rollback과 진단을 위해 보존한다.
