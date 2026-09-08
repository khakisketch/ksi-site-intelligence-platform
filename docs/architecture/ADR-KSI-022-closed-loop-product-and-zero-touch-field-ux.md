# ADR-KSI-022 — 공정·상대 물량 폐루프와 zero-touch 현장 UX

- 상태: ACCEPTED (2026-08-20, 대표자 확정)
- 관련: ADR-KSI-016, ADR-KSI-017(일부 대체), ADR-KSI-019~021,
  INV-001·002·010~015·020·023·024·040~042·050~052·060·061

## 결정

1. 첫 유료 제품은 반복 관측으로 변화·공정·운영관리용 상대 물량을 계산하고,
   부족한 증거의 재관측을 사람 승인으로 닫는 건설 현장 인텔리전스다.
2. 정상 사용자 경로에서 KMZ·사진 파일을 직접 다운로드·복사·선택하지 않는다.
   Cloud+PSDK를 우선 검증하고, 실패 시에만 Pilot 2를 복제하지 않는 얇은 MSDK
   Field adapter를 별도 결정으로 도입한다.
3. 비행 중 첫 자율성은 촬영 품질 보충이다. 동일 위치 재촬영, 짐벌 조정,
   사전 승인 대체 관측점만 단계적으로 연다. 동적 사람·장비 추적 접근은 MVP가 아니다.
4. KSI Server의 결정적 계산기가 변화·공정·물량과 재관측 대상을 계산한다.
   Copilot은 typed query로 이를 설명하고 재관측 초안만 요청한다. 사람만 승인한다.
5. 데이터 배치는 정책형 하이브리드다. 외부 LLM에는 현장 반출 정책이 허용한
   구조화 파생 데이터만 전달하며 원본 media/BIM은 기본 반출하지 않는다.
6. FIELD-0a Pilot-export 비교는 계속 `in_progress`다. 대표자가 수용한 잔여 위험은
   다음 소프트웨어 개발 동결만 해제하며 field acceptance를 대신하지 않는다.

## ADR-KSI-017 대체 범위

- "MSDK를 만들지 않는다"는 "Cloud+PSDK가 실기에서 성립하면 만들지 않는다"로 좁힌다.
- v1 수동 파일 전달은 정상 경로 결정에서 삭제하고 복구 경로로만 보존한다.
- Pilot 2를 비행 중 기본 운용 화면으로 유지하고 화면에 판정 로직을 복제하지 않는
  결정은 유지한다.

## 구현·Rollback

- Provider adapter, automatic media pull, active capture, schedule, Copilot을 각각 독립
  feature flag로 둔다.
- 계약은 additive/dual-reader로 배포하고 기존 Mission API와 수동 복구 도구를 제거하지 않는다.
- DJI 기능은 실기 증거 전까지 `NOT_VERIFIED`; 실제 장비 Profile이 자동 전달·회수를
  모두 통과하지 못하면 zero-touch MVP를 완료로 주장하지 않는다.

## 2026-09-06 ADR-KSI-035 scope amendment

The recovery-only statement for manual KMZ/file handling does not apply to the explicit
Pilot-default KSI plan download/import/edit profile in ADR-KSI-035. That bounded planning flow is
normal only for its profile; it neither promotes manual original-media transfer to zero-touch nor
proves any Cloud/PSDK/MSDK capability, device support, or field acceptance.
