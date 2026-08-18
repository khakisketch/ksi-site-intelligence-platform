# Goal

현재 작업 트리의 Dashboard 후속 변경을 안전하게 통합하고, 현장 운용을 차단하는 세
항목(Mission Contract 소비자 검증, CRITICAL RiskField 실증거 검증, IFC mm
georeference 이중 배율)을 코드·계약 테스트·원장 증거로 닫는다.

## Scope

- 기존 Dashboard/DSM 테스트 변경의 충돌·중복 검토와 전체 게이트
- Manifold에서 실행 전 Mission Contract 서명·digest·schema·TTL을 fail-closed 검증하는
  구체적 소비자 및 활성화 기록
- CRITICAL 확정 전 등록된 RiskField artifact의 실존, 스토리지 바이트, 계약 내용,
  event 시점·entity 연계를 확인하는 Core 게이트
- IFC mm + georeference의 단위 이중 적용 수정과 설계면 변환 소비자 회귀
- H3/H4 장비 접근 가능성 확인 및 실증거/미검증 상태의 정직한 기록

## Out of scope

- 검증되지 않은 비행·배터리·RTH·카메라·DJI 제어 기능의 지원 승격
- RiskField 3D geometry 합성 정책 자체의 신규 제품 결정
- H2 Cellular Dongle 2/유심 조달
- 프로덕션 배포, Git commit/push/tag/release

## Domain invariants

- INV-011: 계약 활성화 전에 구조·서명·digest·schemaVersion·TTL을 함께 검증한다.
- INV-020: IFC 프로젝트 단위와 map CRS 단위를 섞거나 이중 환산하지 않는다.
- INV-021: 실제 RiskField 증거가 event 시점과 entity를 뒷받침할 때만 CRITICAL 확정을 허용한다.
- INV-010/040/041/050/052: 기존 완료 근거·mock 금지·지원 단계·반출·임무 발급 게이트를 보존한다.
