# Cloud Provider Due Diligence — 고객 데이터 배포 Release Gate

상태: **NOT APPROVED / DEVELOPMENT AND SYNTHETIC DATA ONLY**

이 체크리스트는 특정 사업자를 추천하거나 적법성을 선언하지 않는다. 승인된 Cloud 사업자와
계약·법무·보안 검토가 끝나기 전 `compose.vm.yaml`은 개발·합성 데이터의 배포 준비 검증에만
사용한다. 각 항목은 승인자, 근거 문서, 적용 region, 승인일, 재검토일을 기록해야 닫힌다.

| Gate | 확인할 내용 | 필요한 증거 | 상태 |
|---|---|---|---|
| 데이터 소재지 | 원본 사진·위치정보·공간모델·백업·로그의 실제 저장/처리 region | 아키텍처와 사업자 region 명세 | OPEN |
| 국외이전 | 국외이전 여부, 법적 근거, 고지·동의 및 이전국/수탁자 | 법무 검토서 | OPEN |
| 처리위탁 | 개인정보 처리위탁·재위탁자, 변경 통지, 감사권 | 계약/DPA/하위처리자 목록 | OPEN |
| 암호화 | 전송 TLS, 저장 암호화, key 소유·회전·폐기 | 설정 증거와 key lifecycle | OPEN |
| IAM/MFA | 사람·서비스 계정 최소권한, MFA, break-glass | IAM policy와 접근검토 기록 | OPEN |
| 로그·통지 | 감사로그 보존, 보안관제, 침해 탐지·통지 SLA | IR 절차와 예행연습 | OPEN |
| 백업·복구 | RPO/RTO, 불변/격리 백업, 정기 restore 실증 | 최근 restore report | OPEN |
| 보존·삭제 | 사진·위치·모델별 보존기간, 파생물·복제본 삭제 | retention/delete test | OPEN |
| 반환·종료 | 계약 종료 시 표준 형식 반출, 완전 삭제, 사업자 lock-in | exit plan과 export test | OPEN |
| 가용성 | region 장애·서비스 종료·요금 급증 대응 | SLA, DR, cost guardrail | OPEN |

Release 판정:

- 모든 항목이 승인되고 `docs/security` 또는 승인된 외부 문서 위치에 증거가 연결될 것
- 조직 격리와 실제 고객 보존정책 migration이 완료될 것(INV-060)
- 실제 restore와 삭제 검증이 같은 배포 profile에서 통과할 것
- 그 전에는 “적법한 Cloud 선정 완료”, “고객 데이터 운영 가능”으로 표시하지 않을 것
